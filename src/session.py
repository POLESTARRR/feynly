"""Study-session recording and end-of-session summaries.

Accumulates what happened during one run of the app, then writes it out as a
markdown log under `data/sessions/` so you can review a session later, including
the notes-gaps it surfaced, which are edits to make to your source material.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_SESSION_DIR = Path(__file__).resolve().parent.parent / "data" / "sessions"


@dataclass
class Attempt:
    concept: str
    score: float
    result: dict
    next_due: str | None = None


@dataclass
class StudySession:
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    attempts: list[Attempt] = field(default_factory=list)

    def record(self, concept: str, result: dict, next_due: str | None = None) -> None:
        self.attempts.append(
            Attempt(concept=concept, score=result["score"], result=result, next_due=next_due)
        )

    # ------------------------------------------------------------- summary

    @property
    def count(self) -> int:
        return len(self.attempts)

    @property
    def average(self) -> float | None:
        if not self.attempts:
            return None
        return sum(a.score for a in self.attempts) / len(self.attempts)

    def duration_minutes(self, now: datetime | None = None) -> float:
        now = now or datetime.now(timezone.utc)
        return max(0.0, (now - self.started_at).total_seconds() / 60.0)

    def best(self) -> Attempt | None:
        return max(self.attempts, key=lambda a: a.score) if self.attempts else None

    def worst(self) -> Attempt | None:
        return min(self.attempts, key=lambda a: a.score) if self.attempts else None

    def all_notes_gaps(self) -> list[tuple[str, str]]:
        """[(concept, gap)] across the whole session, candidate notes improvements."""
        return [
            (a.concept, gap)
            for a in self.attempts
            for gap in a.result.get("notes_gaps", [])
        ]

    # --------------------------------------------------------------- output

    def to_markdown(self, now: datetime | None = None) -> str:
        now = now or datetime.now(timezone.utc)
        started = self.started_at.strftime("%Y-%m-%d %H:%M UTC")
        lines = [
            f"# Study session, {started}",
            "",
            f"- Concepts explained: **{self.count}**",
        ]
        if self.average is not None:
            lines.append(f"- Average score: **{self.average:.1f}/10**")
        lines.append(f"- Duration: **{self.duration_minutes(now):.0f} min**")

        best, worst = self.best(), self.worst()
        if best and worst and self.count > 1:
            lines.append(f"- Strongest: {best.concept} ({best.score:.0f}/10)")
            lines.append(f"- Weakest: {worst.concept} ({worst.score:.0f}/10)")

        lines.append("")
        lines.append("## Attempts")
        for attempt in self.attempts:
            lines.append("")
            lines.append(f"### {attempt.concept}, {attempt.score:.0f}/10")
            if attempt.result.get("summary"):
                lines.append("")
                lines.append(attempt.result["summary"])
            for title, key in (
                ("Correct", "correct"),
                ("Vague", "vague"),
                ("Wrong / missing", "wrong_or_missing"),
            ):
                items = attempt.result.get(key) or []
                if items:
                    lines.append("")
                    lines.append(f"**{title}**")
                    lines.extend(f"- {item}" for item in items)
            if attempt.next_due:
                lines.append("")
                lines.append(f"*Next review: {attempt.next_due}*")

        gaps = self.all_notes_gaps()
        if gaps:
            lines.extend([
                "",
                "## Possible gaps in your notes",
                "",
                "Things you said that your notes don't actually cover, worth adding "
                "if they're correct:",
                "",
            ])
            lines.extend(f"- **{concept}**: {gap}" for concept, gap in gaps)

        return "\n".join(lines) + "\n"

    def save(self, directory: Path | str = DEFAULT_SESSION_DIR, now: datetime | None = None) -> Path | None:
        """Write the session log. Returns the path, or None if nothing was studied."""
        if not self.attempts:
            return None
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        filename = self.started_at.strftime("%Y-%m-%d_%H%M%S") + ".md"
        path = directory / filename
        path.write_text(self.to_markdown(now), encoding="utf-8")
        return path
