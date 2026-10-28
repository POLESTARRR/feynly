import pytest

from src.concepts import ConceptStore
from src.conversation import ConversationManager
from src.grader import GradingError
from src.progress import ProgressStore


class FakeGrader:
    """Stands in for grade_explanation so tests don't shell out to `claude -p`."""

    def __init__(self, result=None, raises=None):
        self.result = result or {
            "score": 7.0,
            "correct": ["got the core idea"],
            "vague": ["skipped an edge case"],
            "wrong_or_missing": [],
            "summary": "Solid overall.",
        }
        self.raises = raises
        self.calls = []

    def __call__(self, concept, notes, explanation):
        self.calls.append((concept, notes, explanation))
        if self.raises:
            raise self.raises
        return self.result


@pytest.fixture
def concepts(tmp_path):
    store = ConceptStore(tmp_path / "concepts.json")
    store.add("Inflation", "Inflation is a sustained rise in prices.")
    store.add("Photosynthesis", "Plants convert light into chemical energy.")
    return store


@pytest.fixture
def progress(tmp_path):
    return ProgressStore(tmp_path / "progress.json")


def make_convo(concepts, progress, grader=None):
    return ConversationManager(concepts, progress, grader=grader or FakeGrader())


def test_start_command(concepts, progress):
    convo = make_convo(concepts, progress)
    reply = convo.handle_message("chat1", "/start")
    assert "running" in reply.lower()


def test_help_command(concepts, progress):
    convo = make_convo(concepts, progress)
    reply = convo.handle_message("chat1", "/help")
    assert "/list" in reply


def test_list_command_shows_loaded_concepts(concepts, progress):
    convo = make_convo(concepts, progress)
    reply = convo.handle_message("chat1", "/list")
    assert "inflation" in reply
    assert "photosynthesis" in reply


def test_list_command_empty_store(tmp_path, progress):
    empty_store = ConceptStore(tmp_path / "empty.json")
    convo = make_convo(empty_store, progress)
    reply = convo.handle_message("chat1", "/list")
    assert "no concepts" in reply.lower()


def test_unknown_command(concepts, progress):
    convo = make_convo(concepts, progress)
    reply = convo.handle_message("chat1", "/bogus")
    assert "unknown command" in reply.lower()


def test_known_concept_prompts_for_explanation(concepts, progress):
    convo = make_convo(concepts, progress)
    reply = convo.handle_message("chat1", "inflation")
    assert "explain it in your own words" in reply.lower()


def test_unknown_concept_with_suggestion(concepts, progress):
    convo = make_convo(concepts, progress)
    reply = convo.handle_message("chat1", "inflat")
    assert "did you mean" in reply.lower()
    assert "inflation" in reply.lower()


def test_unknown_concept_no_suggestion(concepts, progress):
    convo = make_convo(concepts, progress)
    reply = convo.handle_message("chat1", "quantum entanglement")
    assert "don't have" in reply.lower()
    assert "did you mean" not in reply.lower()


def test_full_explanation_flow_grades_and_records_progress(concepts, progress):
    grader = FakeGrader()
    convo = make_convo(concepts, progress, grader=grader)

    prompt_reply = convo.handle_message("chat1", "inflation")
    assert "explain" in prompt_reply.lower()

    graded_reply = convo.handle_message("chat1", "Prices go up over time.")
    assert "score: 7" in graded_reply.lower()
    assert "got the core idea" in graded_reply
    assert "skipped an edge case" in graded_reply

    assert grader.calls == [("inflation", "Inflation is a sustained rise in prices.", "Prices go up over time.")]
    assert progress.average("chat1", "inflation") == 7.0


def test_state_resets_to_idle_after_grading(concepts, progress):
    convo = make_convo(concepts, progress)
    convo.handle_message("chat1", "inflation")
    convo.handle_message("chat1", "an explanation")

    # A follow-up plain-text message should now be treated as a new concept lookup,
    # not appended as another explanation for the same concept.
    reply = convo.handle_message("chat1", "photosynthesis")
    assert "explain it in your own words" in reply.lower()


def test_cancel_mid_explanation(concepts, progress):
    convo = make_convo(concepts, progress)
    convo.handle_message("chat1", "inflation")
    reply = convo.handle_message("chat1", "/cancel")
    assert "cancelled" in reply.lower()

    # cancelling should return to idle: next plain text is a concept lookup again
    reply2 = convo.handle_message("chat1", "photosynthesis")
    assert "explain it in your own words" in reply2.lower()


def test_cancel_with_nothing_in_progress(concepts, progress):
    convo = make_convo(concepts, progress)
    reply = convo.handle_message("chat1", "/cancel")
    assert "nothing in progress" in reply.lower()


def test_grading_failure_does_not_wedge_chat(concepts, progress):
    grader = FakeGrader(raises=GradingError("boom"))
    convo = make_convo(concepts, progress, grader=grader)

    convo.handle_message("chat1", "inflation")
    reply = convo.handle_message("chat1", "an explanation")
    assert "grading failed" in reply.lower()
    assert progress.average("chat1", "inflation") is None

    # state must have been cleared even though grading failed
    reply2 = convo.handle_message("chat1", "photosynthesis")
    assert "explain it in your own words" in reply2.lower()


def test_weak_command_no_history(concepts, progress):
    convo = make_convo(concepts, progress)
    reply = convo.handle_message("chat1", "/weak")
    assert "no graded attempts" in reply.lower()


def test_weak_command_ranks_by_average(concepts, progress):
    progress.record("chat1", "inflation", 3)
    progress.record("chat1", "photosynthesis", 9)
    convo = make_convo(concepts, progress)

    reply = convo.handle_message("chat1", "/weak")
    lines = reply.splitlines()
    assert lines.index([l for l in lines if "inflation" in l][0]) < lines.index(
        [l for l in lines if "photosynthesis" in l][0]
    )


def test_chats_are_independent(concepts, progress):
    convo = make_convo(concepts, progress)
    convo.handle_message("chat1", "inflation")

    # chat2 hasn't asked about anything, so plain text should be a fresh concept lookup
    reply = convo.handle_message("chat2", "photosynthesis")
    assert "explain it in your own words" in reply.lower()


def test_empty_message(concepts, progress):
    convo = make_convo(concepts, progress)
    reply = convo.handle_message("chat1", "   ")
    assert "send some text" in reply.lower()
