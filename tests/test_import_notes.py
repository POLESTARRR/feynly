import subprocess

import pytest

from src import import_notes
from src.import_notes import ImportError_, _strip_fences, transcribe_image

MARKDOWN = "# Chemistry\n\n## Ionic Bonding\n\n- Electrons transfer.\n"


def _proc(returncode=0, stdout="", stderr=""):
    class P:
        pass

    P.returncode = returncode
    P.stdout = stdout
    P.stderr = stderr
    return P()


@pytest.fixture
def image(tmp_path):
    path = tmp_path / "notes.jpg"
    path.write_bytes(b"\xff\xd8\xff\xe0 fake jpeg bytes")
    return path


@pytest.fixture(autouse=True)
def staging(tmp_path, monkeypatch):
    """Stage inside a temp dir so tests never touch the real project."""
    root = tmp_path / "project"
    (root / "data" / ".import").mkdir(parents=True)
    monkeypatch.setattr(import_notes, "PROJECT_ROOT", root)
    monkeypatch.setattr(import_notes, "STAGING_DIR", root / "data" / ".import")
    return root


# ------------------------------------------------------------------ fences


def test_strip_fences_removes_markdown_fence():
    assert _strip_fences("```markdown\n# A\n\n## B\n```") == "# A\n\n## B"


def test_strip_fences_removes_bare_fence():
    assert _strip_fences("```\n## B\n```") == "## B"


def test_strip_fences_leaves_plain_text():
    assert _strip_fences("## B\n\ntext") == "## B\n\ntext"


# ------------------------------------------------------------- transcribing


def test_transcribe_returns_markdown(image, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _proc(0, MARKDOWN))
    assert "## Ionic Bonding" in transcribe_image(image)


def test_transcribe_strips_code_fences(image, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _proc(0, f"```markdown\n{MARKDOWN}```"))
    assert transcribe_image(image).startswith("# Chemistry")


def test_subject_is_injected_into_the_prompt(image, monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["prompt"] = cmd[2]
        return _proc(0, MARKDOWN)

    monkeypatch.setattr(subprocess, "run", fake_run)
    transcribe_image(image, subject="Chemistry")
    assert "# Chemistry" in captured["prompt"]


def test_prompt_forbids_inventing_content(image, monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["prompt"] = cmd[2]
        return _proc(0, MARKDOWN)

    monkeypatch.setattr(subprocess, "run", fake_run)
    transcribe_image(image)
    # Transcriptions become the grading authority, so this instruction must persist.
    assert "do not" in captured["prompt"].lower()
    assert "[unclear]" in captured["prompt"]


def test_missing_claude_binary(image, monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError()

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(ImportError_, match="claude"):
        transcribe_image(image)


def test_timeout(image, monkeypatch):
    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="claude", timeout=180)

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(ImportError_, match="timed out"):
        transcribe_image(image)


def test_nonzero_exit(image, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _proc(1, "", "broken"))
    with pytest.raises(ImportError_, match="exited 1"):
        transcribe_image(image)


def test_empty_transcription_is_rejected(image, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _proc(0, "   "))
    with pytest.raises(ImportError_, match="empty"):
        transcribe_image(image)


def test_transcription_without_headings_is_rejected(image, monkeypatch):
    # A photo of a cat produces prose, not concepts, better to fail loudly.
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _proc(0, "just some prose"))
    with pytest.raises(ImportError_, match="No '## Concept' headings"):
        transcribe_image(image)


def test_staged_copy_is_cleaned_up(image, monkeypatch, staging):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _proc(0, MARKDOWN))
    transcribe_image(image)
    assert list((staging / "data" / ".import").iterdir()) == []


def test_staged_copy_cleaned_up_even_on_failure(image, monkeypatch, staging):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _proc(1, "", "broken"))
    with pytest.raises(ImportError_):
        transcribe_image(image)
    assert list((staging / "data" / ".import").iterdir()) == []


# --------------------------------------------------------------------- CLI


def test_cli_writes_markdown_and_stops(image, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _proc(0, MARKDOWN))
    out = tmp_path / "out.md"

    monkeypatch.setattr("sys.argv", ["import_notes.py", str(image), "-o", str(out)])
    assert import_notes.main() == 0

    assert "## Ionic Bonding" in out.read_text()
    printed = capsys.readouterr().out
    assert "Read it over" in printed  # review step is the default


def test_cli_reports_missing_file(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["import_notes.py", str(tmp_path / "nope.jpg")])
    assert import_notes.main() == 1
    assert "Not found" in capsys.readouterr().err


def test_cli_fails_when_every_image_fails(image, monkeypatch, capsys):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _proc(1, "", "broken"))
    monkeypatch.setattr("sys.argv", ["import_notes.py", str(image)])
    assert import_notes.main() == 1
    assert "Nothing transcribed" in capsys.readouterr().err


def test_cli_continues_after_one_bad_image(tmp_path, monkeypatch, capsys):
    good = tmp_path / "good.jpg"
    bad = tmp_path / "bad.jpg"
    for p in (good, bad):
        p.write_bytes(b"fake")

    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        return _proc(1, "", "broken") if calls["n"] == 1 else _proc(0, MARKDOWN)

    monkeypatch.setattr(subprocess, "run", flaky)
    out = tmp_path / "out.md"
    monkeypatch.setattr("sys.argv", ["import_notes.py", str(bad), str(good), "-o", str(out)])

    assert import_notes.main() == 0
    assert "Ionic Bonding" in out.read_text()


def test_subject_heading_not_repeated_across_pages(tmp_path, monkeypatch):
    one = tmp_path / "1.jpg"
    two = tmp_path / "2.jpg"
    for p in (one, two):
        p.write_bytes(b"fake")

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _proc(0, MARKDOWN))
    out = tmp_path / "out.md"
    monkeypatch.setattr(
        "sys.argv", ["import_notes.py", str(one), str(two), "-s", "Chemistry", "-o", str(out)]
    )
    import_notes.main()

    # Two pages, one subject heading.
    assert out.read_text().count("# Chemistry") == 1
