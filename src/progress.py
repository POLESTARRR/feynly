"""Per-session, per-concept score history and spaced-repetition state.

On-disk layout (v2):

    {
      "<session_id>": {
        "<concept>": {
          "attempts": [{"score": 7, "ts": "2026-08-18T01:10:00Z"}, ...],
          "review": {"ease": 2.5, "interval_days": 6, "repetitions": 2, "due": "2026-08-24"}
        }
      }
    }

v1 stored the bare attempts list where v2 stores the object. Files in the old
shape are migrated on load, so upgrading never loses history.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from src.scheduler import ReviewState, due_concepts, review_state
from src.storage import read_json, write_json

DEFAULT_STORE_PATH = Path(__file__).resolve().parent.parent / "data" / "progress.json"


class ProgressStore:
    def __init__(self, path: Path | str = DEFAULT_STORE_PATH):
        self.path = Path(path)
        self._data: dict[str, dict[str, dict]] = {}
        self.warning: str | None = None
        self._load()

    # ------------------------------------------------------------------ io

    def _load(self) -> None:
        raw, self.warning = read_json(self.path)
        self._data = {
            session: {concept: self._migrate_entry(entry) for concept, entry in concepts.items()}
            for session, concepts in raw.items()
        }

    @staticmethod
    def _migrate_entry(entry: list | dict) -> dict:
        """Accept a v1 bare attempts list or a v2 object; always return v2 shape."""
        if isinstance(entry, list):
            return {"attempts": entry, "review": ReviewState().to_dict()}
        return {
            "attempts": entry.get("attempts", []),
            "review": entry.get("review") or ReviewState().to_dict(),
        }

    def _save(self) -> None:
        write_json(self.path, self._data)

    def _entry(self, session_id: str | int, concept: str) -> dict:
        session = self._data.setdefault(str(session_id), {})
        return session.setdefault(concept, {"attempts": [], "review": ReviewState().to_dict()})

    # -------------------------------------------------------------- writing

    def record(
        self, session_id: str | int, concept: str, score: float, today: date | None = None
    ) -> ReviewState:
        """Record an attempt and advance its spaced-repetition schedule."""
        entry = self._entry(session_id, concept)
        entry["attempts"].append({
            "score": score,
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
        new_state = review_state(ReviewState.from_dict(entry["review"]), score, today)
        entry["review"] = new_state.to_dict()
        self._save()
        return new_state

    # -------------------------------------------------------------- reading

    def history(self, session_id: str | int, concept: str) -> list[dict]:
        return self._data.get(str(session_id), {}).get(concept, {}).get("attempts", [])

    def average(self, session_id: str | int, concept: str) -> float | None:
        attempts = self.history(session_id, concept)
        if not attempts:
            return None
        return sum(a["score"] for a in attempts) / len(attempts)

    def averages(self, session_id: str | int) -> dict[str, float]:
        """{concept: average_score} for every concept with at least one attempt."""
        return {
            concept: sum(a["score"] for a in entry["attempts"]) / len(entry["attempts"])
            for concept, entry in self._data.get(str(session_id), {}).items()
            if entry["attempts"]
        }

    def latest_score(self, session_id: str | int, concept: str) -> float | None:
        attempts = self.history(session_id, concept)
        return attempts[-1]["score"] if attempts else None

    def review_state(self, session_id: str | int, concept: str) -> ReviewState:
        entry = self._data.get(str(session_id), {}).get(concept)
        return ReviewState.from_dict(entry["review"] if entry else None)

    def review_states(self, session_id: str | int) -> dict[str, ReviewState]:
        return {
            concept: ReviewState.from_dict(entry.get("review"))
            for concept, entry in self._data.get(str(session_id), {}).items()
        }

    def due(self, session_id: str | int, today: date | None = None) -> list[tuple[str, int]]:
        """Concepts due for review now, most overdue first: [(concept, days_overdue)]."""
        return due_concepts(self.review_states(session_id), today)

    def weakest(self, session_id: str | int, limit: int = 5) -> list[tuple[str, float, int]]:
        """[(concept, avg_score, attempts)] sorted ascending by average."""
        rows = [
            (concept, sum(a["score"] for a in entry["attempts"]) / len(entry["attempts"]),
             len(entry["attempts"]))
            for concept, entry in self._data.get(str(session_id), {}).items()
            if entry["attempts"]
        ]
        rows.sort(key=lambda r: (r[1], -r[2]))
        return rows[:limit]

    def studied_concepts(self, session_id: str | int) -> list[str]:
        return sorted(self._data.get(str(session_id), {}).keys())

    def total_attempts(self, session_id: str | int) -> int:
        return sum(
            len(entry["attempts"]) for entry in self._data.get(str(session_id), {}).values()
        )

    def all_attempts(self, session_id: str | int) -> list[tuple[str, float, str]]:
        """Every attempt as (concept, score, iso_timestamp), oldest first."""
        rows = [
            (concept, attempt["score"], attempt["ts"])
            for concept, entry in self._data.get(str(session_id), {}).items()
            for attempt in entry["attempts"]
        ]
        rows.sort(key=lambda r: r[2])
        return rows
