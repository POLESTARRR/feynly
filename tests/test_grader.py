import subprocess

import pytest

from src import grader
from src.grader import GradingError, _extract_json, _validate, grade_explanation


def test_extract_json_plain():
    assert _extract_json('{"score": 5}') == {"score": 5}


def test_extract_json_strips_markdown_fence():
    raw = '```json\n{"score": 5}\n```'
    assert _extract_json(raw) == {"score": 5}


def test_extract_json_finds_object_in_stray_prose():
    raw = 'Sure, here you go:\n{"score": 7, "summary": "ok"}\nHope that helps!'
    assert _extract_json(raw) == {"score": 7, "summary": "ok"}


def test_extract_json_raises_on_garbage():
    with pytest.raises(GradingError):
        _extract_json("not json at all")


def test_validate_fills_defaults():
    result = _validate({"score": 8})
    assert result == {
        "score": 8.0,
        "correct": [],
        "vague": [],
        "wrong_or_missing": [],
        "notes_gaps": [],
        "summary": "",
    }


def test_validate_preserves_notes_gaps():
    result = _validate({"score": 8, "notes_gaps": ["notes don't mention hyperinflation"]})
    assert result["notes_gaps"] == ["notes don't mention hyperinflation"]


def test_validate_clamps_score_range():
    assert _validate({"score": 55})["score"] == 10.0
    assert _validate({"score": -3})["score"] == 0.0


def test_validate_requires_score():
    with pytest.raises(GradingError):
        _validate({"summary": "no score field"})


def test_validate_rejects_non_numeric_score():
    with pytest.raises(GradingError):
        _validate({"score": "not a number"})


@pytest.fixture(autouse=True)
def no_sleeping(monkeypatch):
    """Retry backoff must not make the test suite actually wait."""
    monkeypatch.setattr(grader.time, "sleep", lambda _: None)


def _proc(returncode=0, stdout="", stderr=""):
    class FakeProc:
        pass

    FakeProc.returncode = returncode
    FakeProc.stdout = stdout
    FakeProc.stderr = stderr
    return FakeProc()


GOOD_JSON = '{"score": 8, "correct": ["got the basics"], "vague": [], "wrong_or_missing": [], "summary": "solid"}'


def test_grade_explanation_missing_claude_binary(monkeypatch):
    def fake_run(*args, **kwargs):
        raise FileNotFoundError()

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(GradingError, match="claude") as exc:
        grade_explanation("inflation", "notes", "explanation")
    # A missing binary is permanent, it must not be retried.
    assert exc.value.transient is False


def test_missing_binary_is_not_retried(monkeypatch):
    calls = []

    def fake_run(*args, **kwargs):
        calls.append(1)
        raise FileNotFoundError()

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(GradingError):
        grade_explanation("inflation", "notes", "explanation", attempts=3)
    assert len(calls) == 1


def test_grade_explanation_nonzero_exit(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _proc(1, "", "boom"))
    with pytest.raises(GradingError, match="exited 1"):
        grade_explanation("inflation", "notes", "explanation", attempts=1)


def test_grade_explanation_success(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _proc(0, GOOD_JSON))
    result = grade_explanation("inflation", "notes", "explanation")
    assert result["score"] == 8.0
    assert result["correct"] == ["got the basics"]
    assert result["summary"] == "solid"


def test_grade_explanation_timeout(monkeypatch):
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="claude", timeout=90)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(GradingError, match="timed out"):
        grade_explanation("inflation", "notes", "explanation", attempts=1)


# ------------------------------------------------------------------- retries


def test_transient_failure_is_retried_then_succeeds(monkeypatch):
    results = [_proc(1, "", "flaky"), _proc(0, GOOD_JSON)]
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: results.pop(0))

    result = grade_explanation("inflation", "notes", "explanation", attempts=3)
    assert result["score"] == 8.0
    assert results == []  # both responses consumed


def test_malformed_json_is_retried(monkeypatch):
    results = [_proc(0, "here you go, no json"), _proc(0, GOOD_JSON)]
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: results.pop(0))

    assert grade_explanation("inflation", "notes", "explanation", attempts=3)["score"] == 8.0


def test_retries_are_bounded(monkeypatch):
    calls = []

    def always_fail(*args, **kwargs):
        calls.append(1)
        return _proc(1, "", "always broken")

    monkeypatch.setattr(subprocess, "run", always_fail)
    with pytest.raises(GradingError):
        grade_explanation("inflation", "notes", "explanation", attempts=3)
    assert len(calls) == 3


def test_on_retry_callback_reports_each_retry(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _proc(1, "", "broken"))
    seen = []

    with pytest.raises(GradingError):
        grade_explanation(
            "inflation", "notes", "explanation", attempts=3,
            on_retry=lambda attempt, err: seen.append(attempt),
        )
    # Called before each retry, so one fewer than the total attempts.
    assert seen == [1, 2]


def test_on_retry_not_called_on_success(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _proc(0, GOOD_JSON))
    seen = []
    grade_explanation(
        "inflation", "notes", "explanation",
        on_retry=lambda attempt, err: seen.append(attempt),
    )
    assert seen == []


def test_attempts_of_zero_still_tries_once(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _proc(0, GOOD_JSON))
    assert grade_explanation("inflation", "notes", "explanation", attempts=0)["score"] == 8.0
