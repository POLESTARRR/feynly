import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scheduling"))

import remind  # noqa: E402

from src.concepts import ConceptStore  # noqa: E402
from src.progress import ProgressStore  # noqa: E402

TODAY = date(2026, 8, 18)


@pytest.fixture
def stores(tmp_path, monkeypatch):
    concepts = ConceptStore(tmp_path / "concepts.json")
    progress = ProgressStore(tmp_path / "progress.json")
    monkeypatch.setattr(remind, "ConceptStore", lambda *a, **k: concepts)
    monkeypatch.setattr(remind, "ProgressStore", lambda *a, **k: progress)
    return concepts, progress


def test_no_message_when_no_concepts_loaded(stores):
    assert remind.build_message(TODAY) is None


def test_nudges_about_a_new_concept(stores):
    concepts, _ = stores
    concepts.add("inflation", "notes")
    concepts.save()
    message = remind.build_message(TODAY)
    assert message is not None
    assert "inflation" in message


def test_nudges_about_a_single_due_concept(stores):
    concepts, progress = stores
    concepts.add("inflation", "notes")
    concepts.save()
    progress.record(remind.LOCAL_CHAT_ID, "inflation", 8, today=date(2026, 8, 1))

    message = remind.build_message(TODAY)
    assert "inflation" in message
    assert "due for review" in message


def test_nudges_with_count_when_several_due(stores):
    concepts, progress = stores
    for name in ["inflation", "photosynthesis"]:
        concepts.add(name, "notes")
        progress.record(remind.LOCAL_CHAT_ID, name, 8, today=date(2026, 8, 1))
    concepts.save()

    message = remind.build_message(TODAY)
    assert "2 concepts due" in message


def test_silent_when_caught_up(stores):
    # Every concept studied, nothing due, nothing new -> no nudge.
    concepts, progress = stores
    concepts.add("inflation", "notes")
    concepts.save()
    progress.record(remind.LOCAL_CHAT_ID, "inflation", 9, today=TODAY)

    assert remind.build_message(TODAY) is None


def test_main_returns_zero_when_silent(stores, capsys):
    assert remind.main() == 0
    assert capsys.readouterr().out == ""


def test_main_falls_back_to_stdout_when_notify_fails(stores, monkeypatch, capsys):
    concepts, _ = stores
    concepts.add("inflation", "notes")
    concepts.save()
    monkeypatch.setattr(remind, "notify", lambda *a: False)

    assert remind.main() == 0
    assert "inflation" in capsys.readouterr().out


def test_main_stays_quiet_when_notification_succeeds(stores, monkeypatch, capsys):
    concepts, _ = stores
    concepts.add("inflation", "notes")
    concepts.save()
    monkeypatch.setattr(remind, "notify", lambda *a: True)

    assert remind.main() == 0
    assert capsys.readouterr().out == ""
