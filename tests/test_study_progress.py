"""XP, badges and the /progress view as wired into the CLI."""

import pytest

from src import study
from src.concepts import ConceptStore
from src.progress import ProgressStore


@pytest.fixture
def stores(tmp_path, monkeypatch):
    concepts = ConceptStore(tmp_path / "concepts.json")
    concepts.add("Acids", "Proton donors.", subject="Chemistry")
    concepts.add("Bonding", "Shared electrons.", subject="Chemistry")
    concepts.save()
    progress = ProgressStore(tmp_path / "progress.json")

    monkeypatch.setattr(study, "ConceptStore", lambda *a, **k: concepts)
    monkeypatch.setattr(study, "ProgressStore", lambda *a, **k: progress)
    return concepts, progress


def grader_scoring(score):
    def grade(concept, notes, explanation, **kwargs):
        return {
            "score": score,
            "correct": [],
            "vague": [],
            "wrong_or_missing": [],
            "notes_gaps": [],
            "summary": "",
        }

    return grade


# ------------------------------------------------------------- progress view


def test_progress_command_on_empty_history(stores, capsys):
    assert study.run(["progress"]) == 0
    out = capsys.readouterr().out
    assert "Level 1" in out
    assert "Badges (0/" in out


def test_progress_shows_level_and_xp(stores, capsys):
    _, progress = stores
    progress.record(study.LOCAL_CHAT_ID, "acids", 8)

    assert study.run(["progress"]) == 0
    out = capsys.readouterr().out
    assert "XP total" in out
    assert "Explanations:    1" in out


def test_progress_lists_earned_and_locked_badges(stores, capsys):
    _, progress = stores
    progress.record(study.LOCAL_CHAT_ID, "acids", 7)

    study.run(["progress"])
    out = capsys.readouterr().out
    assert "First Steps" in out       # earned
    assert "Perfectionist" in out     # still locked, but listed as a goal


def test_progress_reflects_streak(stores, capsys):
    _, progress = stores
    progress.record(study.LOCAL_CHAT_ID, "acids", 7)

    study.run(["progress"])
    assert "Current streak:" in capsys.readouterr().out


def test_interactive_progress_command(stores, monkeypatch, capsys):
    replies = iter(["/progress", "/exit"])
    monkeypatch.setattr("builtins.input", lambda *a: next(replies))

    assert study.run([]) == 0
    assert "Your progress" in capsys.readouterr().out


# --------------------------------------------------------------- xp on grade


def test_grading_reports_xp_earned(stores, monkeypatch, capsys):
    monkeypatch.setattr("src.grader.grade_explanation", grader_scoring(8.0))
    monkeypatch.setattr(study.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(study.sys.stdin, "read", lambda: "explanation")

    assert study.run(["explain", "acids"]) == 0
    assert "XP" in capsys.readouterr().out


def test_first_attempt_announces_first_steps_badge(stores, monkeypatch, capsys):
    monkeypatch.setattr("src.grader.grade_explanation", grader_scoring(7.0))
    monkeypatch.setattr(study.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(study.sys.stdin, "read", lambda: "explanation")

    study.run(["explain", "acids"])
    out = capsys.readouterr().out
    assert "Badge unlocked" in out
    assert "First Steps" in out


def test_perfect_score_announces_perfectionist(stores, monkeypatch, capsys):
    _, progress = stores
    progress.record(study.LOCAL_CHAT_ID, "bonding", 5)  # First Steps already earned

    monkeypatch.setattr("src.grader.grade_explanation", grader_scoring(10.0))
    monkeypatch.setattr(study.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(study.sys.stdin, "read", lambda: "explanation")

    study.run(["explain", "acids"])
    out = capsys.readouterr().out
    assert "Perfectionist" in out


def test_already_earned_badge_is_not_re_announced(stores, monkeypatch, capsys):
    _, progress = stores
    progress.record(study.LOCAL_CHAT_ID, "bonding", 7)  # earns First Steps

    monkeypatch.setattr("src.grader.grade_explanation", grader_scoring(7.0))
    monkeypatch.setattr(study.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(study.sys.stdin, "read", lambda: "explanation")

    study.run(["explain", "acids"])
    assert "First Steps" not in capsys.readouterr().out


def test_failed_grading_awards_no_xp(stores, monkeypatch, capsys):
    from src.grader import GradingError

    def boom(concept, notes, explanation, **kwargs):
        raise GradingError("nope")

    monkeypatch.setattr("src.grader.grade_explanation", boom)
    monkeypatch.setattr(study.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(study.sys.stdin, "read", lambda: "explanation")

    assert study.run(["explain", "acids"]) == 1
    assert "XP" not in capsys.readouterr().out


# ----------------------------------------------------------------- in stats


def test_stats_shows_level_when_unscoped(stores, capsys):
    _, progress = stores
    progress.record(study.LOCAL_CHAT_ID, "acids", 8)

    study.run(["stats"])
    assert "Level" in capsys.readouterr().out


def test_stats_omits_level_when_scoped_to_subject(stores, capsys):
    _, progress = stores
    progress.record(study.LOCAL_CHAT_ID, "acids", 8)

    study.run(["stats", "--subject", "chemistry"])
    # XP and level are global, so a subject-scoped view must not imply otherwise.
    assert "Level" not in capsys.readouterr().out
