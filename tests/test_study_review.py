"""The review drill and per-concept history."""

from datetime import date

import pytest

from src import study
from src.concepts import ConceptStore
from src.progress import ProgressStore

LONG_AGO = date(2026, 1, 1)


@pytest.fixture
def stores(tmp_path, monkeypatch):
    concepts = ConceptStore(tmp_path / "concepts.json")
    concepts.add("Acids", "Proton donors.", subject="Chemistry")
    concepts.add("Bonding", "Shared electrons.", subject="Chemistry")
    concepts.add("Inertia", "Resists change.", subject="Physics")
    concepts.save()
    progress = ProgressStore(tmp_path / "progress.json")

    monkeypatch.setattr(study, "ConceptStore", lambda *a, **k: concepts)
    monkeypatch.setattr(study, "ProgressStore", lambda *a, **k: progress)
    return concepts, progress


@pytest.fixture
def fake_grader(monkeypatch):
    """Grade everything 7/10 without shelling out."""
    calls = []

    def grade(concept, notes, explanation, **kwargs):
        calls.append(concept)
        return {
            "score": 7.0,
            "correct": ["ok"],
            "vague": [],
            "wrong_or_missing": [],
            "notes_gaps": [],
            "summary": "Fine.",
        }

    monkeypatch.setattr("src.grader.grade_explanation", grade)
    return calls


# -------------------------------------------------------------------- review


def test_review_reports_nothing_due(stores, capsys):
    assert study.run(["review"]) == 0
    assert "Nothing due" in capsys.readouterr().out


def test_review_drills_every_due_concept(stores, fake_grader, monkeypatch):
    _, progress = stores
    for concept in ["acids", "bonding"]:
        progress.record(study.LOCAL_CHAT_ID, concept, 8, today=LONG_AGO)

    # One explanation line + blank line to submit, for each queued concept.
    replies = iter(["my explanation", "", "another explanation", ""])
    monkeypatch.setattr("builtins.input", lambda *a: next(replies))

    assert study.run(["review"]) == 0
    assert sorted(fake_grader) == ["acids", "bonding"]


def test_review_records_each_score(stores, fake_grader, monkeypatch):
    _, progress = stores
    progress.record(study.LOCAL_CHAT_ID, "acids", 8, today=LONG_AGO)

    replies = iter(["explanation", ""])
    monkeypatch.setattr("builtins.input", lambda *a: next(replies))

    study.run(["review"])
    assert progress.latest_score(study.LOCAL_CHAT_ID, "acids") == 7.0


def test_review_scoped_to_subject(stores, fake_grader, monkeypatch):
    _, progress = stores
    progress.record(study.LOCAL_CHAT_ID, "acids", 8, today=LONG_AGO)
    progress.record(study.LOCAL_CHAT_ID, "inertia", 8, today=LONG_AGO)

    replies = iter(["explanation", ""])
    monkeypatch.setattr("builtins.input", lambda *a: next(replies))

    study.run(["review", "--subject", "chemistry"])
    assert fake_grader == ["acids"]


def test_review_can_be_cancelled_midway(stores, fake_grader, monkeypatch):
    _, progress = stores
    for concept in ["acids", "bonding"]:
        progress.record(study.LOCAL_CHAT_ID, concept, 8, today=LONG_AGO)

    # Grade the first, then cancel out of the second.
    replies = iter(["explanation", "", "/cancel"])
    monkeypatch.setattr("builtins.input", lambda *a: next(replies))

    assert study.run(["review"]) == 0
    assert len(fake_grader) == 1


def test_review_shows_progress_counter(stores, fake_grader, monkeypatch, capsys):
    _, progress = stores
    progress.record(study.LOCAL_CHAT_ID, "acids", 8, today=LONG_AGO)

    replies = iter(["explanation", ""])
    monkeypatch.setattr("builtins.input", lambda *a: next(replies))

    study.run(["review"])
    assert "1 of 1" in capsys.readouterr().out


def test_review_writes_a_session_summary(stores, fake_grader, monkeypatch, capsys):
    _, progress = stores
    progress.record(study.LOCAL_CHAT_ID, "acids", 8, today=LONG_AGO)

    replies = iter(["explanation", ""])
    monkeypatch.setattr("builtins.input", lambda *a: next(replies))

    study.run(["review"])
    assert "Session summary" in capsys.readouterr().out


def test_interactive_review_folds_into_the_session(stores, fake_grader, monkeypatch, capsys):
    _, progress = stores
    progress.record(study.LOCAL_CHAT_ID, "acids", 8, today=LONG_AGO)

    replies = iter(["/review", "explanation", "", "/exit"])
    monkeypatch.setattr("builtins.input", lambda *a: next(replies))

    assert study.run([]) == 0
    out = capsys.readouterr().out
    # One summary at the end of the session, not one per /review.
    assert out.count("Session summary") == 1


# ------------------------------------------------------------------- history


def test_history_for_unknown_concept(stores, capsys):
    assert study.run(["history", "astrology"]) == 1
    assert "isn't loaded" in capsys.readouterr().out


def test_history_with_no_attempts(stores, capsys):
    assert study.run(["history", "acids"]) == 0
    assert "No attempts yet" in capsys.readouterr().out


def test_history_lists_attempts_in_order(stores, capsys):
    _, progress = stores
    progress.record(study.LOCAL_CHAT_ID, "acids", 4)
    progress.record(study.LOCAL_CHAT_ID, "acids", 9)

    assert study.run(["history", "acids"]) == 0
    out = capsys.readouterr().out
    assert "4/10" in out
    assert "9/10" in out
    assert "+5" in out  # improvement is called out
    assert "Average 6.5/10" in out


def test_history_marks_regression(stores, capsys):
    _, progress = stores
    progress.record(study.LOCAL_CHAT_ID, "acids", 9)
    progress.record(study.LOCAL_CHAT_ID, "acids", 4)

    study.run(["history", "acids"])
    assert "-5" in capsys.readouterr().out


def test_history_multiword_concept(stores, capsys):
    concepts, progress = stores
    concepts.add("tcp vs udp", "notes")
    progress.record(study.LOCAL_CHAT_ID, "tcp vs udp", 6)

    assert study.run(["history", "tcp", "vs", "udp"]) == 0
    assert "tcp vs udp" in capsys.readouterr().out


def test_interactive_history_command(stores, monkeypatch, capsys):
    _, progress = stores
    progress.record(study.LOCAL_CHAT_ID, "acids", 6)

    replies = iter(["/history acids", "/exit"])
    monkeypatch.setattr("builtins.input", lambda *a: next(replies))

    assert study.run([]) == 0
    assert "6/10" in capsys.readouterr().out


def test_interactive_history_without_argument(stores, monkeypatch, capsys):
    replies = iter(["/history", "/exit"])
    monkeypatch.setattr("builtins.input", lambda *a: next(replies))

    assert study.run([]) == 0
    assert "Usage" in capsys.readouterr().out
