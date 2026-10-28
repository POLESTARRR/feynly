"""Subject scoping across the CLI and interactive loop."""

import pytest

from src import study
from src.concepts import ConceptStore
from src.progress import ProgressStore


@pytest.fixture
def stores(tmp_path, monkeypatch):
    concepts = ConceptStore(tmp_path / "concepts.json")
    concepts.add("Covalent Bonding", "Atoms share electron pairs.", subject="Chemistry")
    concepts.add("Acids", "Proton donors.", subject="Chemistry")
    concepts.add("Inertia", "Objects resist change in motion.", subject="Physics")
    concepts.add("Loose Concept", "No subject here.")
    concepts.save()
    progress = ProgressStore(tmp_path / "progress.json")

    monkeypatch.setattr(study, "ConceptStore", lambda *a, **k: concepts)
    monkeypatch.setattr(study, "ProgressStore", lambda *a, **k: progress)
    return concepts, progress


# ------------------------------------------------------------------ listing


def test_list_shows_all_subjects_by_default(stores, capsys):
    assert study.run(["list"]) == 0
    out = capsys.readouterr().out
    assert "covalent bonding" in out
    assert "inertia" in out


def test_list_scoped_to_subject(stores, capsys):
    assert study.run(["list", "--subject", "chemistry"]) == 0
    out = capsys.readouterr().out
    assert "acids" in out
    assert "inertia" not in out


def test_subject_flag_before_subcommand(stores, capsys):
    assert study.run(["--subject", "physics", "list"]) == 0
    out = capsys.readouterr().out
    assert "inertia" in out
    assert "acids" not in out


def test_unknown_subject_is_a_usage_error(stores, capsys):
    assert study.run(["list", "--subject", "astrology"]) == 2
    out = capsys.readouterr().out
    assert "No subject" in out
    assert "chemistry" in out  # tells you what's available


def test_uncategorized_is_selectable(stores, capsys):
    assert study.run(["list", "--subject", "uncategorized"]) == 0
    out = capsys.readouterr().out
    assert "loose concept" in out
    assert "acids" not in out


# ----------------------------------------------------------------- subjects


def test_subjects_command_lists_coverage(stores, capsys):
    assert study.run(["subjects"]) == 0
    out = capsys.readouterr().out
    assert "chemistry" in out
    assert "physics" in out
    assert "uncategorized" in out


def test_subjects_shows_average_after_attempts(stores, capsys):
    _, progress = stores
    progress.record(study.LOCAL_CHAT_ID, "acids", 8)
    assert study.run(["subjects"]) == 0
    assert "8.0/10" in capsys.readouterr().out


# --------------------------------------------------------------------- weak


def test_weak_scoped_to_subject(stores, capsys):
    _, progress = stores
    progress.record(study.LOCAL_CHAT_ID, "acids", 2)
    progress.record(study.LOCAL_CHAT_ID, "inertia", 1)

    assert study.run(["weak", "--subject", "chemistry"]) == 0
    out = capsys.readouterr().out
    assert "acids" in out
    assert "inertia" not in out


def test_weak_limit_flag(stores, capsys):
    _, progress = stores
    for concept, score in [("acids", 1), ("covalent bonding", 2), ("inertia", 3)]:
        progress.record(study.LOCAL_CHAT_ID, concept, score)

    assert study.run(["weak", "--limit", "1"]) == 0
    out = capsys.readouterr().out
    assert "acids" in out
    assert "inertia" not in out


# ---------------------------------------------------------------- due/stats


def test_due_scoped_to_subject(stores, capsys):
    _, progress = stores
    from datetime import date

    progress.record(study.LOCAL_CHAT_ID, "acids", 8, today=date(2026, 1, 1))
    progress.record(study.LOCAL_CHAT_ID, "inertia", 8, today=date(2026, 1, 1))

    assert study.run(["due", "--subject", "physics"]) == 0
    out = capsys.readouterr().out
    assert "inertia" in out
    assert "acids" not in out


def test_stats_scoped_to_subject(stores, capsys):
    _, progress = stores
    progress.record(study.LOCAL_CHAT_ID, "acids", 8)

    assert study.run(["stats", "--subject", "chemistry"]) == 0
    out = capsys.readouterr().out
    assert "chemistry" in out
    assert "Concepts loaded:   2" in out


def test_stats_counts_only_scoped_attempts(stores, capsys):
    _, progress = stores
    progress.record(study.LOCAL_CHAT_ID, "acids", 8)
    progress.record(study.LOCAL_CHAT_ID, "inertia", 4)

    study.run(["stats", "--subject", "chemistry"])
    out = capsys.readouterr().out
    assert "Total attempts:    1" in out


# --------------------------------------------------------------------- next


def test_next_stays_within_subject(stores, capsys):
    assert study.run(["next", "--subject", "physics"]) == 0
    assert "inertia" in capsys.readouterr().out


def test_next_returns_error_when_subject_has_no_concepts(stores, monkeypatch, capsys):
    concepts, _ = stores
    monkeypatch.setattr(concepts, "names", lambda subject=None: [])
    assert study.run(["next", "--subject", "physics"]) == 1


# -------------------------------------------------------------- interactive


def test_interactive_focus_scopes_listing(stores, monkeypatch, capsys):
    replies = iter(["/focus physics", "/list", "/exit"])
    monkeypatch.setattr("builtins.input", lambda *a: next(replies))

    assert study.run([]) == 0
    out = capsys.readouterr().out
    assert "Focused on physics" in out
    assert "inertia" in out
    assert "acids" not in out


def test_interactive_focus_can_be_cleared(stores, monkeypatch, capsys):
    replies = iter(["/focus physics", "/focus", "/list", "/exit"])
    monkeypatch.setattr("builtins.input", lambda *a: next(replies))

    assert study.run([]) == 0
    out = capsys.readouterr().out
    assert "Focus cleared" in out
    assert "acids" in out


def test_interactive_focus_rejects_unknown_subject(stores, monkeypatch, capsys):
    replies = iter(["/focus astrology", "/exit"])
    monkeypatch.setattr("builtins.input", lambda *a: next(replies))

    assert study.run([]) == 0
    out = capsys.readouterr().out
    assert "No subject" in out
    assert "Available:" in out


def test_interactive_subjects_command(stores, monkeypatch, capsys):
    replies = iter(["/subjects", "/exit"])
    monkeypatch.setattr("builtins.input", lambda *a: next(replies))

    assert study.run([]) == 0
    assert "chemistry" in capsys.readouterr().out


def test_interactive_starts_focused_from_flag(stores, monkeypatch, capsys):
    replies = iter(["/list", "/exit"])
    monkeypatch.setattr("builtins.input", lambda *a: next(replies))

    assert study.run(["--subject", "physics"]) == 0
    out = capsys.readouterr().out
    assert "inertia" in out
    assert "acids" not in out


def test_interactive_help_lists_commands(stores, monkeypatch, capsys):
    replies = iter(["/help", "/exit"])
    monkeypatch.setattr("builtins.input", lambda *a: next(replies))

    assert study.run([]) == 0
    out = capsys.readouterr().out
    assert "/focus" in out
    assert "/next" in out


# ------------------------------------------------------------- store health


def test_corrupt_store_warning_is_surfaced(tmp_path, monkeypatch, capsys):
    path = tmp_path / "concepts.json"
    path.write_text("{ not json")
    concepts = ConceptStore(path)
    progress = ProgressStore(tmp_path / "progress.json")
    monkeypatch.setattr(study, "ConceptStore", lambda *a, **k: concepts)
    monkeypatch.setattr(study, "ProgressStore", lambda *a, **k: progress)

    study.run(["list"])
    assert "Warning" in capsys.readouterr().out
