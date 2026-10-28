import pytest

from src import study
from src.concepts import ConceptStore
from src.grader import GradingError
from src.progress import ProgressStore


@pytest.fixture
def stores(tmp_path, monkeypatch):
    """Point study.py's ConceptStore/ProgressStore at temp files."""
    concepts = ConceptStore(tmp_path / "concepts.json")
    concepts.add("Inflation", "Inflation is a sustained rise in the general price level.")
    concepts.save()
    progress = ProgressStore(tmp_path / "progress.json")

    monkeypatch.setattr(study, "ConceptStore", lambda *a, **k: concepts)
    monkeypatch.setattr(study, "ProgressStore", lambda *a, **k: progress)
    return concepts, progress


def test_score_style_thresholds():
    assert study.score_style(9) == "green"
    assert study.score_style(8) == "green"
    assert study.score_style(6) == "yellow"
    assert study.score_style(5) == "yellow"
    assert study.score_style(4) == "red"
    assert study.score_style(0) == "red"


def test_list_command(stores, capsys):
    assert study.run(["list"]) == 0
    assert "inflation" in capsys.readouterr().out


def test_weak_command_with_no_history(stores, capsys):
    assert study.run(["weak"]) == 0
    assert "No graded attempts" in capsys.readouterr().out


def test_weak_command_after_a_score(stores, capsys):
    _, progress = stores
    progress.record(study.LOCAL_CHAT_ID, "inflation", 4)
    assert study.run(["weak"]) == 0
    out = capsys.readouterr().out
    assert "inflation" in out
    assert "4.0/10" in out


def test_unknown_command_exits_with_usage_error(stores):
    # argparse rejects unknown subcommands itself, exiting 2.
    with pytest.raises(SystemExit) as exc:
        study.run(["bogus"])
    assert exc.value.code == 2


def test_explain_without_concept_exits_with_usage_error(stores):
    with pytest.raises(SystemExit) as exc:
        study.run(["explain"])
    assert exc.value.code == 2


def test_explain_grades_and_records(stores, monkeypatch, capsys):
    _, progress = stores
    monkeypatch.setattr(
        "src.grader.grade_explanation",
        lambda concept, notes, explanation, **kwargs: {
            "score": 7.0,
            "correct": ["core idea"],
            "vague": [],
            "wrong_or_missing": ["a gap"],
            "summary": "Decent.",
        },
    )
    monkeypatch.setattr(study.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(study.sys.stdin, "read", lambda: "prices go up over time")

    assert study.run(["explain", "inflation"]) == 0
    out = capsys.readouterr().out
    assert "7/10" in out
    assert "core idea" in out
    assert progress.average(study.LOCAL_CHAT_ID, "inflation") == 7.0


def test_explain_unknown_concept_suggests_matches(stores, capsys):
    assert study.run(["explain", "inflat"]) == 1
    out = capsys.readouterr().out
    assert "isn't loaded" in out
    assert "inflation" in out


def test_explain_multiword_concept_joins_args(stores, monkeypatch):
    concepts, _ = stores
    concepts.add("tcp vs udp", "TCP is reliable, UDP is fast.")
    captured = {}

    def fake_grade(concept, notes, explanation, **kwargs):
        captured["concept"] = concept
        return {"score": 5.0, "correct": [], "vague": [], "wrong_or_missing": [], "summary": ""}

    monkeypatch.setattr("src.grader.grade_explanation", fake_grade)
    monkeypatch.setattr(study.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(study.sys.stdin, "read", lambda: "one is reliable")

    assert study.run(["explain", "tcp", "vs", "udp"]) == 0
    assert captured["concept"] == "tcp vs udp"


def test_grading_failure_surfaces_error_and_records_nothing(stores, monkeypatch, capsys):
    _, progress = stores

    def boom(concept, notes, explanation, **kwargs):
        raise GradingError("claude exploded")

    monkeypatch.setattr("src.grader.grade_explanation", boom)
    monkeypatch.setattr(study.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(study.sys.stdin, "read", lambda: "some explanation")

    assert study.run(["explain", "inflation"]) == 1
    assert "Grading failed" in capsys.readouterr().out
    assert progress.average(study.LOCAL_CHAT_ID, "inflation") is None


def test_explain_empty_stdin_returns_usage_error(stores, monkeypatch, capsys):
    monkeypatch.setattr(study.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(study.sys.stdin, "read", lambda: "   ")
    assert study.run(["explain", "inflation"]) == 2
    assert "No explanation" in capsys.readouterr().out


def test_interactive_exits_cleanly_on_exit_command(stores, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda *a: "/exit")
    assert study.run([]) == 0
    assert "Bye" in capsys.readouterr().out


def test_interactive_list_then_exit(stores, monkeypatch, capsys):
    replies = iter(["/list", "/exit"])
    monkeypatch.setattr("builtins.input", lambda *a: next(replies))
    assert study.run([]) == 0
    assert "inflation" in capsys.readouterr().out


def test_interactive_unknown_concept_then_exit(stores, monkeypatch, capsys):
    replies = iter(["quantum entanglement", "/exit"])
    monkeypatch.setattr("builtins.input", lambda *a: next(replies))
    assert study.run([]) == 0
    assert "isn't loaded" in capsys.readouterr().out


def test_interactive_unknown_slash_command(stores, monkeypatch, capsys):
    replies = iter(["/bogus", "/exit"])
    monkeypatch.setattr("builtins.input", lambda *a: next(replies))
    assert study.run([]) == 0
    assert "Unknown command" in capsys.readouterr().out


def test_interactive_ctrl_c_exits_cleanly(stores, monkeypatch):
    def raise_interrupt(*a):
        raise KeyboardInterrupt()

    monkeypatch.setattr("builtins.input", raise_interrupt)
    assert study.run([]) == 0


def test_interactive_full_explanation_flow(stores, monkeypatch, capsys):
    _, progress = stores
    monkeypatch.setattr(
        "src.grader.grade_explanation",
        lambda c, n, e, **kwargs: {
            "score": 9.0,
            "correct": ["nailed it"],
            "vague": [],
            "wrong_or_missing": [],
            "summary": "Great.",
        },
    )
    # concept name, two explanation lines, blank line to submit, then exit
    replies = iter(["inflation", "prices rise", "money buys less", "", "/exit"])
    monkeypatch.setattr("builtins.input", lambda *a: next(replies))

    assert study.run([]) == 0
    out = capsys.readouterr().out
    assert "9/10" in out
    assert "nailed it" in out
    assert progress.average(study.LOCAL_CHAT_ID, "inflation") == 9.0


def test_read_multiline_explanation_cancel(monkeypatch):
    replies = iter(["/cancel"])
    monkeypatch.setattr("builtins.input", lambda *a: next(replies))
    assert study.read_multiline_explanation("inflation") is None


def test_read_multiline_explanation_joins_lines(monkeypatch):
    replies = iter(["line one", "line two", ""])
    monkeypatch.setattr("builtins.input", lambda *a: next(replies))
    assert study.read_multiline_explanation("inflation") == "line one\nline two"


def test_read_multiline_explanation_skips_leading_blanks(monkeypatch):
    replies = iter(["", "", "actual content", ""])
    monkeypatch.setattr("builtins.input", lambda *a: next(replies))
    assert study.read_multiline_explanation("inflation") == "actual content"


# ------------------------------------------------- explanation preservation


def test_failed_grading_saves_the_explanation(stores, monkeypatch, tmp_path, capsys):
    """A transient failure must never cost the user what they typed."""
    saved = {}

    def fake_save(concept, explanation):
        saved["concept"] = concept
        saved["explanation"] = explanation
        return tmp_path / "saved.txt"

    def boom(concept, notes, explanation, **kwargs):
        raise GradingError("claude exploded")

    monkeypatch.setattr("src.grader.grade_explanation", boom)
    monkeypatch.setattr(study, "save_failed_explanation", fake_save)
    monkeypatch.setattr(study.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(study.sys.stdin, "read", lambda: "a long careful explanation")

    assert study.run(["explain", "inflation"]) == 1
    assert saved["explanation"] == "a long careful explanation"
    assert "saved to" in capsys.readouterr().out


def test_save_failed_explanation_writes_a_file(tmp_path, monkeypatch):
    monkeypatch.setattr(study, "__file__", str(tmp_path / "src" / "study.py"))
    path = study.save_failed_explanation("TCP vs UDP", "my explanation")
    assert path is not None
    assert path.read_text() == "my explanation"
    assert "tcp-vs-udp" in path.name


def test_save_failed_explanation_survives_unwritable_location(monkeypatch):
    def deny(*args, **kwargs):
        raise OSError("read-only filesystem")

    monkeypatch.setattr(study.Path, "mkdir", deny)
    # Returns None rather than raising, the grading error is the real story.
    assert study.save_failed_explanation("inflation", "text") is None
