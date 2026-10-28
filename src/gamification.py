"""XP, levels, streaks, and badges, all derived, never stored.

Everything here is a pure function over the attempt history that `progress.py`
already keeps. Nothing is persisted separately, which means there is no second
source of truth to drift out of sync, and every badge applies retroactively to
study you did before this module existed.

XP rewards effort and quality together: every graded explanation earns XP
proportional to its score, so a wrong answer still earns a little (you showed
up) and a great one earns a lot.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

# XP per attempt = BASE + score * PER_POINT. Showing up is worth something.
XP_BASE = 5
XP_PER_POINT = 10

# Level N starts at LEVEL_STEP * N * (N - 1) / 2 XP, i.e. each level costs
# LEVEL_STEP more than the last: 0, 100, 300, 600, 1000, ...
LEVEL_STEP = 100

PERFECT_SCORE = 10.0
MASTERY_AVERAGE = 8.0
COMEBACK_FLOOR = 4.0
COMEBACK_GAIN = 4.0


@dataclass(frozen=True)
class Badge:
    key: str
    name: str
    description: str


@dataclass(frozen=True)
class LevelInfo:
    level: int
    xp: int
    xp_into_level: int
    xp_for_next: int

    @property
    def progress_fraction(self) -> float:
        if self.xp_for_next <= 0:
            return 1.0
        return min(1.0, self.xp_into_level / self.xp_for_next)


# ------------------------------------------------------------------- XP


def attempt_xp(score: float) -> int:
    return XP_BASE + int(round(score * XP_PER_POINT))


def total_xp(attempts: list[tuple[str, float, str]]) -> int:
    return sum(attempt_xp(score) for _, score, _ in attempts)


def _xp_required_for_level(level: int) -> int:
    """Cumulative XP needed to reach `level` (level 1 starts at 0)."""
    if level <= 1:
        return 0
    return LEVEL_STEP * (level - 1) * level // 2


def level_for_xp(xp: int) -> LevelInfo:
    level = 1
    while xp >= _xp_required_for_level(level + 1):
        level += 1
    floor = _xp_required_for_level(level)
    ceiling = _xp_required_for_level(level + 1)
    return LevelInfo(
        level=level,
        xp=xp,
        xp_into_level=xp - floor,
        xp_for_next=ceiling - floor,
    )


# --------------------------------------------------------------- streaks


def _attempt_dates(attempts: list[tuple[str, float, str]]) -> list[date]:
    seen = {ts[:10] for _, _, ts in attempts}
    out = []
    for day in seen:
        try:
            out.append(date.fromisoformat(day))
        except ValueError:
            continue  # a malformed timestamp must not break the whole tally
    return sorted(out)


def current_streak(attempts: list[tuple[str, float, str]], today: date | None = None) -> int:
    """Consecutive days studied ending today (or yesterday, today isn't over yet)."""
    days = set(_attempt_dates(attempts))
    if not days:
        return 0
    today = today or datetime.now(timezone.utc).date()

    if today in days:
        cursor = today
    elif (today - timedelta(days=1)) in days:
        cursor = today - timedelta(days=1)
    else:
        return 0

    streak = 0
    while cursor in days:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def longest_streak(attempts: list[tuple[str, float, str]]) -> int:
    days = _attempt_dates(attempts)
    if not days:
        return 0
    best = run = 1
    for previous, current in zip(days, days[1:]):
        run = run + 1 if current - previous == timedelta(days=1) else 1
        best = max(best, run)
    return best


# ---------------------------------------------------------------- badges


ALL_BADGES: tuple[Badge, ...] = (
    Badge("first_steps", "First Steps", "Explain your first concept"),
    Badge("perfectionist", "Perfectionist", "Score a perfect 10/10"),
    Badge("comeback", "Comeback", "Recover from 4/10 or below to a 4+ point gain"),
    Badge("deep_diver", "Deep Diver", "Explain one concept 5 times"),
    Badge("explorer", "Explorer", "Explain 10 different concepts"),
    Badge("scholar", "Scholar", "Explain 25 different concepts"),
    Badge("century", "Century", "Reach 100 graded explanations"),
    Badge("consistent", "Consistent", "Study 3 days in a row"),
    Badge("dedicated", "Dedicated", "Study 7 days in a row"),
    Badge("marathon", "Marathon", "Study 30 days in a row"),
    Badge("subject_master", "Subject Master", "Average 8+ across every concept in a subject"),
    Badge("polymath", "Polymath", "Study concepts in 3 different subjects"),
)

BADGES_BY_KEY = {badge.key: badge for badge in ALL_BADGES}


def earned_badge_keys(
    attempts: list[tuple[str, float, str]],
    subjects_by_concept: dict[str, str | None] | None = None,
    today: date | None = None,
) -> set[str]:
    """Which badges the history has earned. Pure, recomputed from scratch each time."""
    if not attempts:
        return set()

    earned: set[str] = {"first_steps"}
    subjects_by_concept = subjects_by_concept or {}

    scores_by_concept: dict[str, list[float]] = {}
    for concept, score, _ in attempts:
        scores_by_concept.setdefault(concept, []).append(score)

    if any(score >= PERFECT_SCORE for _, score, _ in attempts):
        earned.add("perfectionist")

    for scores in scores_by_concept.values():
        if len(scores) >= 5:
            earned.add("deep_diver")
        for previous, current in zip(scores, scores[1:]):
            if previous <= COMEBACK_FLOOR and current - previous >= COMEBACK_GAIN:
                earned.add("comeback")
                break

    distinct = len(scores_by_concept)
    if distinct >= 10:
        earned.add("explorer")
    if distinct >= 25:
        earned.add("scholar")
    if len(attempts) >= 100:
        earned.add("century")

    streak = longest_streak(attempts)
    if streak >= 3:
        earned.add("consistent")
    if streak >= 7:
        earned.add("dedicated")
    if streak >= 30:
        earned.add("marathon")

    studied_subjects = {
        subjects_by_concept.get(concept)
        for concept in scores_by_concept
        if subjects_by_concept.get(concept)
    }
    if len(studied_subjects) >= 3:
        earned.add("polymath")

    # Subject Master needs every concept in a subject studied and averaging 8+,
    # so it can't be earned by cherry-picking the easy ones.
    concepts_by_subject: dict[str, list[str]] = {}
    for concept, subject in subjects_by_concept.items():
        if subject:
            concepts_by_subject.setdefault(subject, []).append(concept)

    for concepts in concepts_by_subject.values():
        if not concepts:
            continue
        if all(concept in scores_by_concept for concept in concepts) and all(
            sum(scores_by_concept[c]) / len(scores_by_concept[c]) >= MASTERY_AVERAGE
            for c in concepts
        ):
            earned.add("subject_master")
            break

    return earned


def earned_badges(
    attempts: list[tuple[str, float, str]],
    subjects_by_concept: dict[str, str | None] | None = None,
    today: date | None = None,
) -> list[Badge]:
    keys = earned_badge_keys(attempts, subjects_by_concept, today)
    return [badge for badge in ALL_BADGES if badge.key in keys]


def locked_badges(
    attempts: list[tuple[str, float, str]],
    subjects_by_concept: dict[str, str | None] | None = None,
    today: date | None = None,
) -> list[Badge]:
    keys = earned_badge_keys(attempts, subjects_by_concept, today)
    return [badge for badge in ALL_BADGES if badge.key not in keys]
