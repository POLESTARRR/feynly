"""Routes and API of the browser front end."""

import io
from datetime import date

import pytest

from src import webapp
from src.concepts import ConceptStore
from src.grader import GradingError
from src.import_notes import ImportError_
from src.progress import ProgressStore
from src.tutor import TutorError, TutorHistory

TODAY = date(2026, 8, 18)


@pytest.fixture
def stores(tmp_path, monkeypatch):
    concepts = ConceptStore(tmp_path / "concepts.json")
    concepts.add("Inflation", "Inflation is a sustained rise in prices.", subject="Economics")
    concepts.add("Photosynthesis", "Plants convert light into glucose.", subject="Biology")
    concepts.save()
    progress = ProgressStore(tmp_path / "progress.json")
    history = TutorHistory(tmp_path / "tutor_history.json")

    monkeypatch.setattr(webapp, "stores", lambda: (concepts, progress))
    monkeypatch.setattr(webapp, "history_store", lambda *a, **k: history)
    return concepts, progress, history


@pytest.fixture
def client(stores):
    webapp.app.config["TESTING"] = True
    return webapp.app.test_client()


def fake_grade(score=8.0, **extra):
    result = {
        "score": score,
        "correct": ["got it"],
        "vague": [],
        "wrong_or_missing": [],
        "notes_gaps": [],
        "summary": "Good.",
    }
    result.update(extra)
    return lambda *a, **k: result


# ------------------------------------------------------------------ pages


@pytest.mark.parametrize("path", ["/", "/dashboard", "/tutor", "/notes"])
def test_pages_render(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert "feynly" in response.get_data(as_text=True)


def test_study_page_picks_a_concept(client):
    body = client.get("/").get_data(as_text=True)
    assert "inflation" in body or "photosynthesis" in body


def test_study_page_honours_requested_concept(client):
    body = client.get("/?concept=inflation").get_data(as_text=True)
    assert "inflation" in body


def test_study_page_ignores_unknown_concept(client):
    # Falls back to a suggestion rather than erroring.
    assert client.get("/?concept=astrology").status_code == 200


def test_study_page_empty_store(tmp_path, monkeypatch):
    empty = ConceptStore(tmp_path / "empty.json")
    progress = ProgressStore(tmp_path / "p.json")
    monkeypatch.setattr(webapp, "stores", lambda: (empty, progress))
    webapp.app.config["TESTING"] = True

    body = webapp.app.test_client().get("/").get_data(as_text=True)
    assert "Nothing to study yet" in body


def test_notes_page_lists_concepts(client):
    body = client.get("/notes").get_data(as_text=True)
    assert "inflation" in body
    assert "economics" in body


# ---------------------------------------------------------------- explain


def test_explain_grades_and_records(client, stores, monkeypatch):
    _, progress, _ = stores
    monkeypatch.setattr(webapp, "grade_explanation", fake_grade(8.0))

    response = client.post("/api/explain", json={"concept": "inflation", "explanation": "prices rise"})
    assert response.status_code == 200

    data = response.get_json()
    assert data["score"] == 8.0
    assert data["concept"] == "inflation"
    assert data["next_due"]
    assert data["xp"] > 0
    assert progress.average(webapp.SESSION_ID, "inflation") == 8.0


def test_explain_announces_new_badges(client, monkeypatch):
    monkeypatch.setattr(webapp, "grade_explanation", fake_grade(10.0))
    data = client.post("/api/explain", json={"concept": "inflation", "explanation": "x"}).get_json()
    assert "First Steps" in data["new_badges"]
    assert "Perfectionist" in data["new_badges"]


def test_explain_requires_a_concept(client):
    response = client.post("/api/explain", json={"explanation": "text"})
    assert response.status_code == 400


def test_explain_requires_an_explanation(client):
    response = client.post("/api/explain", json={"concept": "inflation", "explanation": "  "})
    assert response.status_code == 400


def test_explain_unknown_concept_is_404(client):
    response = client.post("/api/explain", json={"concept": "astrology", "explanation": "x"})
    assert response.status_code == 404


def test_explain_surfaces_grader_failure(client, monkeypatch):
    def boom(*a, **k):
        raise GradingError("claude down")

    monkeypatch.setattr(webapp, "grade_explanation", boom)
    response = client.post("/api/explain", json={"concept": "inflation", "explanation": "x"})
    assert response.status_code == 502
    assert "claude down" in response.get_json()["error"]


def test_failed_grading_records_nothing(client, stores, monkeypatch):
    _, progress, _ = stores

    def boom(*a, **k):
        raise GradingError("down")

    monkeypatch.setattr(webapp, "grade_explanation", boom)
    client.post("/api/explain", json={"concept": "inflation", "explanation": "x"})
    assert progress.average(webapp.SESSION_ID, "inflation") is None


# ------------------------------------------------------------------ tutor


def test_tutor_answers(client, monkeypatch):
    monkeypatch.setattr(webapp, "tutor_answer", lambda *a, **k: "a grounded reply")
    data = client.post("/api/tutor", json={"question": "how am I doing?"}).get_json()
    assert data["reply"] == "a grounded reply"


def test_tutor_requires_a_question(client):
    assert client.post("/api/tutor", json={"question": ""}).status_code == 400


def test_tutor_surfaces_failure(client, monkeypatch):
    def boom(*a, **k):
        raise TutorError("unavailable")

    monkeypatch.setattr(webapp, "tutor_answer", boom)
    assert client.post("/api/tutor", json={"question": "q"}).status_code == 502


def test_tutor_forget_clears_history(client, stores):
    _, _, history = stores
    history.add("student", "old")
    assert client.post("/api/tutor/forget").status_code == 200
    assert len(history) == 0


# ----------------------------------------------------------------- import


def test_import_transcribes_uploads(client, monkeypatch):
    monkeypatch.setattr(webapp, "transcribe_image", lambda p, s=None: "## Ionic Bonding\n\nnotes")
    data = {"images": (io.BytesIO(b"fake image"), "notes.jpg"), "subject": "Chemistry"}

    response = client.post("/api/import", data=data, content_type="multipart/form-data")
    assert response.status_code == 200
    payload = response.get_json()
    assert "Ionic Bonding" in payload["markdown"]
    assert payload["concept_count"] == 1


def test_import_requires_images(client):
    assert client.post("/api/import", data={}, content_type="multipart/form-data").status_code == 400


def test_import_reports_total_failure(client, monkeypatch):
    def boom(*a, **k):
        raise ImportError_("unreadable")

    monkeypatch.setattr(webapp, "transcribe_image", boom)
    data = {"images": (io.BytesIO(b"x"), "bad.jpg")}
    response = client.post("/api/import", data=data, content_type="multipart/form-data")
    assert response.status_code == 502


def test_import_does_not_save_until_confirmed(client, stores, monkeypatch):
    """Transcription must not enter the store until the user approves it."""
    concepts, _, _ = stores
    before = len(concepts)
    monkeypatch.setattr(webapp, "transcribe_image", lambda p, s=None: "## New Thing\n\nnotes")

    client.post("/api/import", data={"images": (io.BytesIO(b"x"), "n.jpg")},
                content_type="multipart/form-data")
    assert len(concepts) == before


def test_import_save_adds_concepts(client, stores):
    concepts, _, _ = stores
    before = len(concepts)

    response = client.post("/api/import/save",
                           json={"markdown": "## New Thing\n\nsome notes", "subject": "Chemistry"})
    assert response.status_code == 200
    assert response.get_json()["added"] == 1
    assert len(concepts) == before + 1
    assert concepts.get("new thing") == "some notes"


def test_import_save_rejects_empty(client):
    assert client.post("/api/import/save", json={"markdown": "   "}).status_code == 400


def test_import_save_rejects_markdown_without_headings(client):
    response = client.post("/api/import/save", json={"markdown": "just prose, no headings"})
    assert response.status_code == 400
    assert "## Concept" in response.get_json()["error"]


# -------------------------------------------------------------- dashboard


def test_dashboard_data_shape(client, stores):
    _, progress, _ = stores
    progress.record(webapp.SESSION_ID, "inflation", 7, today=TODAY)

    data = client.get("/api/data").get_json()
    assert data["totals"]["loaded"] == 2
    assert data["totals"]["attempts"] == 1
    assert "gamification" in data
    assert data["gamification"]["xp"] > 0
    assert any(s["subject"] == "economics" for s in data["subjects"])


def test_dashboard_matches_cli_derivation(client, stores):
    """The browser and terminal must never disagree about XP."""
    from src.gamification import total_xp

    _, progress, _ = stores
    progress.record(webapp.SESSION_ID, "inflation", 6, today=TODAY)

    data = client.get("/api/data").get_json()
    assert data["gamification"]["xp"] == total_xp(progress.all_attempts(webapp.SESSION_ID))


def test_dashboard_renders_with_history(client, stores):
    _, progress, _ = stores
    progress.record(webapp.SESSION_ID, "inflation", 9, today=TODAY)
    body = client.get("/dashboard").get_data(as_text=True)
    assert "Level" in body
    assert "inflation" in body


def test_dashboard_trend_groups_by_day(client, stores):
    _, progress, _ = stores
    progress.record(webapp.SESSION_ID, "inflation", 6, today=TODAY)
    progress.record(webapp.SESSION_ID, "photosynthesis", 8, today=TODAY)

    trend = client.get("/api/data").get_json()["trend"]
    assert len(trend) == 1
    assert trend[0]["count"] == 2
    assert trend[0]["average"] == 7.0


def test_dashboard_subject_rollup(client, stores):
    _, progress, _ = stores
    progress.record(webapp.SESSION_ID, "inflation", 8, today=TODAY)

    subjects = {s["subject"]: s for s in client.get("/api/data").get_json()["subjects"]}
    assert subjects["economics"]["studied"] == 1
    assert subjects["economics"]["average"] == 8.0
    assert subjects["biology"]["average"] is None


def test_dashboard_includes_unstudied_concepts(client):
    concepts = client.get("/api/data").get_json()["concepts"]
    unstudied = next(c for c in concepts if c["concept"] == "photosynthesis")
    assert unstudied["attempts"] == 0
    assert unstudied["average"] is None


def test_dashboard_reports_due(client, stores):
    _, progress, _ = stores
    progress.record(webapp.SESSION_ID, "inflation", 8, today=date(2026, 1, 1))
    due = client.get("/api/data").get_json()["due"]
    assert any(row["concept"] == "inflation" for row in due)


# --------------------------------------------------- newly added material


def test_saved_notes_are_returned_by_name(client, stores):
    """The page needs the names so it can offer to study what was just added."""
    response = client.post("/api/import/save",
                           json={"markdown": "## Contract\n\nAn agreement.", "subject": "Law"})
    assert response.status_code == 200
    assert response.get_json()["names"] == ["contract"]


def test_saved_names_are_normalised(client, stores):
    data = client.post("/api/import/save",
                       json={"markdown": "## Indian Contract Act, 1872\n\nnotes"}).get_json()
    assert data["names"] == ["indian contract act, 1872"]


def test_study_dropdown_groups_by_subject(client, stores):
    body = client.get("/").get_data(as_text=True)
    assert "<optgroup" in body
    assert 'label="economics"' in body
    assert 'label="biology"' in body


def test_newly_added_concept_appears_in_the_dropdown(client, stores):
    """A new concept loses the due-queue race, so it must still be selectable."""
    client.post("/api/import/save", json={"markdown": "## Contract\n\nnotes", "subject": "Law"})
    body = client.get("/").get_data(as_text=True)
    assert 'label="law"' in body
    assert ">contract<" in body


def test_requested_concept_beats_the_due_queue(client, stores):
    """Following the 'study this' link must open that concept, not the due one."""
    from datetime import date

    _, progress, _ = stores
    progress.record(webapp.SESSION_ID, "inflation", 8, today=date(2026, 1, 1))  # overdue
    client.post("/api/import/save", json={"markdown": "## Contract\n\nnotes", "subject": "Law"})

    body = client.get("/?concept=contract").get_data(as_text=True)
    assert 'id="conceptName"' in body
    # The requested concept is the one presented, not the overdue one.
    assert body.split('id="conceptName"')[1].split("</h2>")[0].endswith("contract")
