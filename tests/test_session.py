from datetime import datetime, timedelta, timezone

from src.session import StudySession

START = datetime(2026, 8, 18, 10, 0, tzinfo=timezone.utc)


def result(score, **kwargs):
    base = {
        "score": score,
        "correct": [],
        "vague": [],
        "wrong_or_missing": [],
        "notes_gaps": [],
        "summary": "",
    }
    base.update(kwargs)
    return base


def test_empty_session_has_no_average():
    session = StudySession(started_at=START)
    assert session.count == 0
    assert session.average is None


def test_records_attempts():
    session = StudySession(started_at=START)
    session.record("inflation", result(7))
    session.record("photosynthesis", result(9))
    assert session.count == 2
    assert session.average == 8.0


def test_best_and_worst():
    session = StudySession(started_at=START)
    session.record("a", result(3))
    session.record("b", result(9))
    assert session.best().concept == "b"
    assert session.worst().concept == "a"


def test_best_and_worst_empty():
    session = StudySession(started_at=START)
    assert session.best() is None
    assert session.worst() is None


def test_duration_minutes():
    session = StudySession(started_at=START)
    assert session.duration_minutes(START + timedelta(minutes=25)) == 25.0


def test_duration_never_negative():
    session = StudySession(started_at=START)
    assert session.duration_minutes(START - timedelta(minutes=5)) == 0.0


def test_collects_notes_gaps_across_attempts():
    session = StudySession(started_at=START)
    session.record("inflation", result(7, notes_gaps=["hyperinflation not covered"]))
    session.record("tcp", result(8, notes_gaps=["QUIC not covered", "TLS not covered"]))
    gaps = session.all_notes_gaps()
    assert len(gaps) == 3
    assert ("inflation", "hyperinflation not covered") in gaps


def test_markdown_contains_key_facts():
    session = StudySession(started_at=START)
    session.record("inflation", result(7, summary="Decent.", correct=["prices rise"]), next_due="2026-08-19")
    md = session.to_markdown(START + timedelta(minutes=10))
    assert "# Study session" in md
    assert "inflation" in md
    assert "7/10" in md
    assert "Decent." in md
    assert "prices rise" in md
    assert "2026-08-19" in md


def test_markdown_includes_notes_gap_section():
    session = StudySession(started_at=START)
    session.record("inflation", result(7, notes_gaps=["hyperinflation not covered"]))
    md = session.to_markdown(START + timedelta(minutes=5))
    assert "Possible gaps in your notes" in md
    assert "hyperinflation not covered" in md


def test_markdown_omits_gap_section_when_none():
    session = StudySession(started_at=START)
    session.record("inflation", result(7))
    assert "Possible gaps" not in session.to_markdown(START + timedelta(minutes=5))


def test_markdown_shows_best_and_worst_only_for_multiple_attempts():
    single = StudySession(started_at=START)
    single.record("a", result(7))
    assert "Strongest" not in single.to_markdown(START)

    multi = StudySession(started_at=START)
    multi.record("a", result(3))
    multi.record("b", result(9))
    assert "Strongest" in multi.to_markdown(START)


def test_save_writes_file(tmp_path):
    session = StudySession(started_at=START)
    session.record("inflation", result(7))
    path = session.save(tmp_path)
    assert path is not None
    assert path.exists()
    assert "inflation" in path.read_text()
    assert path.name == "2026-08-18_100000.md"


def test_save_skips_empty_session(tmp_path):
    session = StudySession(started_at=START)
    assert session.save(tmp_path) is None
    assert list(tmp_path.iterdir()) == []


def test_save_creates_directory(tmp_path):
    session = StudySession(started_at=START)
    session.record("inflation", result(7))
    target = tmp_path / "nested" / "sessions"
    path = session.save(target)
    assert path.exists()
