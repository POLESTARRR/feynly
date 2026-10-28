import json
import os

import pytest

from src.storage import CorruptStoreError, read_json, write_json


def test_read_missing_file_returns_default(tmp_path):
    data, warning = read_json(tmp_path / "nope.json")
    assert data == {}
    assert warning is None


def test_read_missing_file_returns_copy_of_default(tmp_path):
    default = {"a": 1}
    data, _ = read_json(tmp_path / "nope.json", default)
    data["b"] = 2
    assert default == {"a": 1}  # caller's default must not be mutated


def test_read_valid_json(tmp_path):
    path = tmp_path / "d.json"
    path.write_text(json.dumps({"a": 1}))
    data, warning = read_json(path)
    assert data == {"a": 1}
    assert warning is None


def test_corrupt_json_is_quarantined(tmp_path):
    path = tmp_path / "d.json"
    path.write_text("{ broken")

    data, warning = read_json(path)
    assert data == {}
    assert warning is not None and "moved to" in warning
    assert not path.exists()
    assert len(list(tmp_path.glob("d.json.corrupt-*"))) == 1


def test_quarantined_file_keeps_original_content(tmp_path):
    path = tmp_path / "d.json"
    path.write_text("{ broken but precious")
    read_json(path)
    backup = next(tmp_path.glob("d.json.corrupt-*"))
    assert backup.read_text() == "{ broken but precious"


def test_non_object_json_is_quarantined(tmp_path):
    path = tmp_path / "d.json"
    path.write_text(json.dumps([1, 2, 3]))
    data, warning = read_json(path)
    assert data == {}
    assert "JSON object" in warning


def test_write_then_read_round_trip(tmp_path):
    path = tmp_path / "d.json"
    write_json(path, {"b": 2, "a": 1})
    assert read_json(path)[0] == {"b": 2, "a": 1}


def test_write_creates_parent_dirs(tmp_path):
    path = tmp_path / "nested" / "deep" / "d.json"
    write_json(path, {"a": 1})
    assert path.exists()


def test_write_sorts_keys_when_asked(tmp_path):
    path = tmp_path / "d.json"
    write_json(path, {"b": 2, "a": 1}, sort_keys=True)
    assert list(json.loads(path.read_text())) == ["a", "b"]


def test_write_preserves_unicode(tmp_path):
    path = tmp_path / "d.json"
    write_json(path, {"concept": "光合作用 · تمثيل ضوئي"})
    assert read_json(path)[0]["concept"] == "光合作用 · تمثيل ضوئي"


def test_write_leaves_no_temp_files_behind(tmp_path):
    path = tmp_path / "d.json"
    write_json(path, {"a": 1})
    assert [p.name for p in tmp_path.iterdir()] == ["d.json"]


def test_failed_write_preserves_existing_file(tmp_path, monkeypatch):
    path = tmp_path / "d.json"
    write_json(path, {"good": True})

    def explode(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", explode)
    with pytest.raises(OSError):
        write_json(path, {"bad": True})

    # The original survives intact, and no temp litter is left.
    assert read_json(path)[0] == {"good": True}
    assert [p.name for p in tmp_path.iterdir()] == ["d.json"]


def test_unserializable_payload_preserves_existing_file(tmp_path):
    path = tmp_path / "d.json"
    write_json(path, {"good": True})

    with pytest.raises(TypeError):
        write_json(path, {"bad": object()})

    assert read_json(path)[0] == {"good": True}
    assert [p.name for p in tmp_path.iterdir()] == ["d.json"]


def test_read_unreadable_path_raises(tmp_path):
    # A directory where a file is expected is an environment problem, not
    # corrupt data, it must surface loudly rather than silently reset.
    path = tmp_path / "d.json"
    path.mkdir()
    with pytest.raises(CorruptStoreError):
        read_json(path)
