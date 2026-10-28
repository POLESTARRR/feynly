"""Spaced repetition (SM-2) and adaptive concept selection.

Two jobs, kept separate:

- `review_state()` runs the SM-2 algorithm: given how well you just explained
  something, when should you see it again?
- `pick_next()` chooses what to study now, due reviews first, then a weighted
  mix of weak / strong / unseen concepts when nothing is overdue.

Pure functions over plain dicts; no I/O. `progress.py` owns persistence.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta, timezone

# SM-2 tuning. Ease never drops below this or intervals collapse to daily forever.
MIN_EASE = 1.3
DEFAULT_EASE = 2.5
FIRST_INTERVAL_DAYS = 1
SECOND_INTERVAL_DAYS = 6

# A 0-10 explanation score maps onto SM-2's 0-5 quality scale.
SCORE_TO_QUALITY_DIVISOR = 2.0
# Below this quality, SM-2 treats the attempt as a lapse and restarts the interval.
LAPSE_QUALITY_THRESHOLD = 3.0

# Mix used by pick_next() when nothing is due for review.
WEAK_SHARE = 0.60
STRONG_SHARE = 0.30
# remaining 0.10 goes to unseen concepts

WEAK_SCORE_CEILING = 6.5  # average at or below this counts as a weak concept


@dataclass
class ReviewState:
    """SM-2 scheduling state for one concept."""

    ease: float = DEFAULT_EASE
    interval_days: int = 0
    repetitions: int = 0
    due: str | None = None  # ISO date; None means "never studied, due now"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> "ReviewState":
        if not data:
            return cls()
        return cls(
            ease=float(data.get("ease", DEFAULT_EASE)),
            interval_days=int(data.get("interval_days", 0)),
            repetitions=int(data.get("repetitions", 0)),
            due=data.get("due"),
        )

    def is_due(self, today: date | None = None) -> bool:
        if self.due is None:
            return True
        today = today or datetime.now(timezone.utc).date()
        return date.fromisoformat(self.due) <= today

    def days_until_due(self, today: date | None = None) -> int:
        """Negative when overdue, 0 when due today."""
        if self.due is None:
            return 0
        today = today or datetime.now(timezone.utc).date()
        return (date.fromisoformat(self.due) - today).days


def score_to_quality(score: float) -> float:
    """Map an explanation score (0-10) onto SM-2's quality scale (0-5)."""
    return max(0.0, min(5.0, score / SCORE_TO_QUALITY_DIVISOR))


def next_ease(current_ease: float, quality: float) -> float:
    """Standard SM-2 ease adjustment, floored at MIN_EASE."""
    delta = 0.1 - (5.0 - quality) * (0.08 + (5.0 - quality) * 0.02)
    return max(MIN_EASE, current_ease + delta)


def review_state(previous: ReviewState, score: float, today: date | None = None) -> ReviewState:
    """Advance SM-2 state after an attempt scored `score` out of 10."""
    today = today or datetime.now(timezone.utc).date()
    quality = score_to_quality(score)
    ease = next_ease(previous.ease, quality)

    if quality < LAPSE_QUALITY_THRESHOLD:
        # Lapse: you didn't really have it. Start the ladder over, but keep the
        # (now lowered) ease so repeated lapses stretch intervals less each time.
        repetitions = 0
        interval = FIRST_INTERVAL_DAYS
    else:
        repetitions = previous.repetitions + 1
        if repetitions == 1:
            interval = FIRST_INTERVAL_DAYS
        elif repetitions == 2:
            interval = SECOND_INTERVAL_DAYS
        else:
            interval = max(1, round(previous.interval_days * ease))

    return ReviewState(
        ease=ease,
        interval_days=interval,
        repetitions=repetitions,
        due=(today + timedelta(days=interval)).isoformat(),
    )


def due_concepts(
    states: dict[str, ReviewState], today: date | None = None
) -> list[tuple[str, int]]:
    """Concepts due for review, most overdue first. Returns [(concept, days_overdue)]."""
    today = today or datetime.now(timezone.utc).date()
    rows = [
        (concept, -state.days_until_due(today))
        for concept, state in states.items()
        if state.is_due(today)
    ]
    rows.sort(key=lambda r: (-r[1], r[0]))
    return rows


def pick_next(
    all_concepts: list[str],
    averages: dict[str, float],
    states: dict[str, ReviewState],
    today: date | None = None,
    rng: random.Random | None = None,
) -> tuple[str, str] | None:
    """Choose the next concept to study.

    Returns (concept, reason) where reason is one of "due", "weak", "strong",
    "new", or None when there are no concepts at all.

    Due reviews always win; spaced repetition is the whole point of tracking
    intervals, so honoring them beats any weighting heuristic. Only when nothing
    is due does the weak/strong/new mix decide.
    """
    if not all_concepts:
        return None

    rng = rng or random.Random()
    today = today or datetime.now(timezone.utc).date()

    studied = {c for c in all_concepts if c in averages}
    tracked_states = {c: states.get(c, ReviewState()) for c in studied}

    overdue = [c for c, _ in due_concepts(tracked_states, today)]
    if overdue:
        return overdue[0], "due"

    weak = sorted(
        (c for c in studied if averages[c] <= WEAK_SCORE_CEILING),
        key=lambda c: averages[c],
    )
    strong = sorted(
        (c for c in studied if averages[c] > WEAK_SCORE_CEILING),
        key=lambda c: averages[c],
        reverse=True,
    )
    unseen = sorted(c for c in all_concepts if c not in studied)

    roll = rng.random()
    if roll < WEAK_SHARE:
        preference = [weak, unseen, strong]
        reasons = ["weak", "new", "strong"]
    elif roll < WEAK_SHARE + STRONG_SHARE:
        preference = [strong, weak, unseen]
        reasons = ["strong", "weak", "new"]
    else:
        preference = [unseen, weak, strong]
        reasons = ["new", "weak", "strong"]

    for bucket, reason in zip(preference, reasons):
        if bucket:
            return bucket[0], reason

    return None
