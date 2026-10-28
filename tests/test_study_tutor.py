"""The tutor as wired into the CLI and interactive loop."""

import pytest

from src import study
from src.concepts import ConceptStore
from src.progress import ProgressStore
from src.tutor import TutorError, TutorHistory


@pytest.fixture
def stores(tmp_path, monkeypatch):
    concepts = ConceptStore(tmp_path / "concepts.json")
    concepts.add("Inflation", "Prices rise over time.")
    concepts.save()
    progress = ProgressStore(tmp_path / "progress.json")
    history = TutorHistory(tmp_path / "tutor_history.json")

    monkeypatch.setattr(study, "ConceptStore", lambda *a, **k: concepts)
    monkeypatch.setattr(study, "ProgressStore", lambda *a, **k: progress)
    monkeypatch.setattr(study, "TutorHistory", lambda *a, **k: history)
    return concepts, progress, history


@pytest.fixture
def fake_tutor(monkeypatch):
    captured = {}

    def answer(question, concepts, progress, history, session_id, **kwargs):
        captured["question"] = question
        history.add("student", question)
        history.add("tutor", "a grounded answer")
        return "a grounded answer"

    monkeypatch.setattr(study, "tutor_answer", answer)
    return captured


def test_one_shot_question(stores, fake_tutor, capsys):
    assert study.run(["tutor", "what", "is", "inflation?"]) == 0
    assert fake_tutor["question"] == "what is inflation?"
    assert "a grounded answer" in capsys.readouterr().out


def test_tutor_failure_is_reported(stores, monkeypatch, capsys):
    def boom(*a, **k):
        raise TutorError("claude down")

    monkeypatch.setattr(study, "tutor_answer", boom)
    assert study.run(["tutor", "question"]) == 1
    assert "Tutor unavailable" in capsys.readouterr().out


def test_forget_clears_memory(stores, capsys):
    _, _, history = stores
    history.add("student", "old question")

    assert study.run(["tutor", "--forget"]) == 0
    assert len(history) == 0
    assert "memory cleared" in capsys.readouterr().out


def test_tutor_repl_exits_cleanly(stores, fake_tutor, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda *a: "/exit")
    assert study.run(["tutor"]) == 0
    assert "Bye" in capsys.readouterr().out


def test_tutor_repl_answers_then_exits(stores, fake_tutor, monkeypatch, capsys):
    replies = iter(["why am I weak at inflation?", "/exit"])
    monkeypatch.setattr("builtins.input", lambda *a: next(replies))

    assert study.run(["tutor"]) == 0
    assert "a grounded answer" in capsys.readouterr().out


def test_tutor_repl_forget_command(stores, fake_tutor, monkeypatch, capsys):
    _, _, history = stores
    history.add("student", "old")

    replies = iter(["/forget", "/exit"])
    monkeypatch.setattr("builtins.input", lambda *a: next(replies))

    study.run(["tutor"])
    assert len(history) == 0


def test_tutor_repl_survives_ctrl_c(stores, fake_tutor, monkeypatch):
    def interrupt(*a):
        raise KeyboardInterrupt()

    monkeypatch.setattr("builtins.input", interrupt)
    assert study.run(["tutor"]) == 0


def test_interactive_ask_command(stores, fake_tutor, monkeypatch, capsys):
    replies = iter(["/ask what is inflation?", "/exit"])
    monkeypatch.setattr("builtins.input", lambda *a: next(replies))

    assert study.run([]) == 0
    assert fake_tutor["question"] == "what is inflation?"


def test_interactive_ask_without_question(stores, monkeypatch, capsys):
    replies = iter(["/ask", "/exit"])
    monkeypatch.setattr("builtins.input", lambda *a: next(replies))

    assert study.run([]) == 0
    assert "Usage" in capsys.readouterr().out


def test_memory_persists_between_questions(stores, fake_tutor, capsys):
    _, _, history = stores
    study.run(["tutor", "first"])
    study.run(["tutor", "second"])
    assert len(history) == 4  # two exchanges
