"""Load and search the concept store (concepts.json).

On-disk layout (v2):

    { "<concept>": {"notes": "...", "subject": "chemistry" | null} }

v1 stored a bare notes string where v2 stores the object; old files are
migrated on load. Concept keys are stored lowercase and looked up
case-insensitively. Subjects group concepts so a teacher covering several
subjects can scope a session to one of them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from src.storage import read_json, write_json

DEFAULT_STORE_PATH = Path(__file__).resolve().parent.parent / "data" / "concepts.json"

UNCATEGORIZED = "uncategorized"


def _normalize(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


@dataclass(frozen=True)
class ParsedConcept:
    """One concept parsed out of a notes file."""

    notes: str
    subject: str | None = None


class ConceptStore:
    def __init__(self, path: Path | str = DEFAULT_STORE_PATH):
        self.path = Path(path)
        self._concepts: dict[str, dict] = {}
        self.warning: str | None = None
        self._load()

    # ------------------------------------------------------------------ io

    def _load(self) -> None:
        raw, self.warning = read_json(self.path)
        self._concepts = {
            name: self._migrate_entry(entry) for name, entry in raw.items()
        }

    @staticmethod
    def _migrate_entry(entry: str | dict) -> dict:
        """Accept a v1 bare notes string or a v2 object; always return v2 shape."""
        if isinstance(entry, str):
            return {"notes": entry, "subject": None}
        return {
            "notes": str(entry.get("notes", "")),
            "subject": entry.get("subject") or None,
        }

    def save(self) -> None:
        write_json(self.path, self._concepts, sort_keys=True)

    # -------------------------------------------------------------- writing

    def add(self, name: str, notes: str, subject: str | None = None) -> None:
        self._concepts[_normalize(name)] = {
            "notes": notes.strip(),
            "subject": _normalize(subject) if subject else None,
        }

    def merge(self, other: dict[str, ParsedConcept | str]) -> None:
        for name, value in other.items():
            if isinstance(value, ParsedConcept):
                self.add(name, value.notes, value.subject)
            else:
                self.add(name, value)

    def replace_all(self, other: dict[str, ParsedConcept | str]) -> None:
        self._concepts = {}
        self.merge(other)

    # -------------------------------------------------------------- reading

    def get(self, name: str) -> str | None:
        """The source notes for a concept, or None if it isn't loaded."""
        entry = self._concepts.get(_normalize(name))
        return entry["notes"] if entry else None

    def subject_of(self, name: str) -> str | None:
        entry = self._concepts.get(_normalize(name))
        return entry["subject"] if entry else None

    def exists(self, name: str) -> bool:
        return _normalize(name) in self._concepts

    def names(self, subject: str | None = None) -> list[str]:
        """All concept names, or only those in `subject`."""
        if subject is None:
            return sorted(self._concepts)
        target = _normalize(subject)
        if target == UNCATEGORIZED:
            return sorted(n for n, e in self._concepts.items() if not e["subject"])
        return sorted(n for n, e in self._concepts.items() if e["subject"] == target)

    def subjects(self) -> list[str]:
        """Every distinct subject, with UNCATEGORIZED last if any concept lacks one."""
        named = sorted({e["subject"] for e in self._concepts.values() if e["subject"]})
        if any(not e["subject"] for e in self._concepts.values()):
            named.append(UNCATEGORIZED)
        return named

    def subject_exists(self, subject: str) -> bool:
        return _normalize(subject) in self.subjects()

    def counts_by_subject(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for entry in self._concepts.values():
            key = entry["subject"] or UNCATEGORIZED
            counts[key] = counts.get(key, 0) + 1
        return counts

    def __len__(self) -> int:
        return len(self._concepts)

    def find_close_matches(self, name: str, limit: int = 3) -> list[str]:
        """Substring / prefix match fallback for typos or partial names."""
        target = _normalize(name)
        if not target:
            return []
        scored = []
        for candidate in self._concepts:
            if target == candidate:
                continue
            if candidate.startswith(target) or target in candidate:
                scored.append((0, candidate))
            elif candidate in target:
                scored.append((1, candidate))
            else:
                overlap = len(set(target.split()) & set(candidate.split()))
                if overlap:
                    scored.append((2 - overlap, candidate))
        scored.sort(key=lambda t: (t[0], t[1]))
        return [c for _, c in scored[:limit]]


def parse_markdown_notes(text: str, default_subject: str | None = None) -> dict[str, ParsedConcept]:
    """Split a markdown file into concepts.

    ``## Heading`` starts a concept. ``# Heading`` sets the subject for every
    concept beneath it, so one file can hold several subjects. `default_subject`
    applies to concepts appearing before any ``#`` heading.
    """
    concepts: dict[str, ParsedConcept] = {}
    current_name: str | None = None
    current_lines: list[str] = []
    current_subject: str | None = default_subject
    in_code_fence = False

    def flush():
        if current_name is not None:
            body = "\n".join(current_lines).strip()
            if body:
                concepts[current_name] = ParsedConcept(notes=body, subject=current_subject)

    for line in text.splitlines():
        # Headings inside fenced code blocks are content, not structure.
        if re.match(r"^\s*```", line):
            in_code_fence = not in_code_fence

        if not in_code_fence:
            subject_heading = re.match(r"^#\s+(.*\S)\s*$", line)
            if subject_heading:
                flush()
                current_name = None
                current_lines = []
                current_subject = subject_heading.group(1)
                continue

            concept_heading = re.match(r"^##\s+(.*\S)\s*$", line)
            if concept_heading:
                flush()
                current_name = concept_heading.group(1)
                current_lines = []
                continue

        if current_name is not None:
            current_lines.append(line)

    flush()
    return concepts
