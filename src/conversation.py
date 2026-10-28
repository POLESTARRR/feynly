"""Transport-agnostic conversation logic.

Owns the small per-session state machine (idle <-> awaiting-explanation) and
formats replies as plain text. Callers feed it (session_id, text) and send the
returned string back over whichever front end they're using, study.py is the
terminal one, but nothing here knows or cares about the terminal.
"""

from __future__ import annotations

from dataclasses import dataclass

from .concepts import ConceptStore
from .grader import GradingError, grade_explanation
from .progress import ProgressStore

HELP_TEXT = (
    "Feynly, the Feynman technique as a study bot.\n\n"
    "Send a concept name and I'll ask you to explain it in your own words, "
    "then grade your explanation against your own notes.\n\n"
    "Commands:\n"
    "/list      see all loaded concepts\n"
    "/weak      see your lowest-scoring concepts\n"
    "/cancel    stop the explanation you're mid-way through\n"
    "/help      this message"
)

WELCOME_TEXT = (
    "Feynly is running. Send a concept name to get started, "
    "or /list to see what's loaded."
)


@dataclass
class _ChatState:
    awaiting: str | None = None  # concept name currently being explained, or None if idle


class ConversationManager:
    def __init__(
        self,
        concept_store: ConceptStore,
        progress_store: ProgressStore,
        grader=grade_explanation,
    ):
        self.concepts = concept_store
        self.progress = progress_store
        self.grade = grader
        self._states: dict[str, _ChatState] = {}

    def _state(self, chat_id: str | int) -> _ChatState:
        key = str(chat_id)
        if key not in self._states:
            self._states[key] = _ChatState()
        return self._states[key]

    def handle_message(self, chat_id: str | int, text: str) -> str:
        text = (text or "").strip()
        if not text:
            return "Send some text: a concept name, or your explanation."

        if text.startswith("/"):
            return self._handle_command(chat_id, text)

        state = self._state(chat_id)
        if state.awaiting:
            return self._handle_explanation(chat_id, state.awaiting, text)
        return self._handle_concept_request(chat_id, text)

    def _handle_command(self, chat_id: str | int, text: str) -> str:
        command = text.split()[0].lower().lstrip("/")
        if command == "start":
            return WELCOME_TEXT
        if command == "help":
            return HELP_TEXT
        if command == "list":
            return self._list_concepts()
        if command == "weak":
            return self._weakest_concepts(chat_id)
        if command == "cancel":
            state = self._state(chat_id)
            if state.awaiting:
                cancelled = state.awaiting
                state.awaiting = None
                return f"Cancelled. You were explaining \"{cancelled}\". Send a concept name whenever you're ready."
            return "Nothing in progress."
        return f"Unknown command: /{command}. Try /help."

    def _list_concepts(self) -> str:
        names = self.concepts.names()
        if not names:
            return "No concepts loaded yet. Run load_notes.py with a notes file first."
        bullets = "\n".join(f"- {n}" for n in names)
        return f"Loaded concepts ({len(names)}):\n{bullets}"

    def _weakest_concepts(self, chat_id: str | int) -> str:
        rows = self.progress.weakest(chat_id)
        if not rows:
            return "No graded attempts yet. Explain a concept first."
        lines = [f"{concept}: avg {avg:.1f}/10 ({attempts} attempt{'s' if attempts != 1 else ''})"
                 for concept, avg, attempts in rows]
        return "Your weakest concepts:\n" + "\n".join(lines)

    def _handle_concept_request(self, chat_id: str | int, text: str) -> str:
        notes = self.concepts.get(text)
        if notes is None:
            suggestions = self.concepts.find_close_matches(text)
            if suggestions:
                bullets = "\n".join(f"- {s}" for s in suggestions)
                return (
                    f"I don't have \"{text}\" loaded. Did you mean:\n{bullets}\n\n"
                    "Or send /list to see everything."
                )
            return f"I don't have \"{text}\" loaded. Send /list to see what's available."

        self._state(chat_id).awaiting = text.strip().lower()
        return (
            f"\U0001F4DA {text.strip()}: explain it in your own words. "
            "Don't worry about sounding polished, just be complete."
        )

    def _handle_explanation(self, chat_id: str | int, concept: str, explanation: str) -> str:
        notes = self.concepts.get(concept)
        state = self._state(chat_id)
        state.awaiting = None  # clear regardless of outcome so a failed grade doesn't wedge the chat

        if notes is None:
            return f"\"{concept}\" isn't loaded anymore. Send /list and pick another concept."

        try:
            result = self.grade(concept, notes, explanation)
        except GradingError as exc:
            return f"Grading failed, sorry. Try again in a moment.\n({exc})"

        self.progress.record(chat_id, concept, result["score"])
        return self._format_feedback(concept, result)

    @staticmethod
    def _format_feedback(concept: str, result: dict) -> str:
        lines = [f"Score: {result['score']:.0f}/10  {concept}"]
        if result["summary"]:
            lines.append(result["summary"])

        def section(title: str, items: list[str]) -> None:
            if items:
                lines.append(f"\n{title}:")
                lines.extend(f"  • {item}" for item in items)

        section("✅ Correct", result["correct"])
        section("⚠️ Vague", result["vague"])
        section("❌ Wrong / missing", result["wrong_or_missing"])
        return "\n".join(lines)
