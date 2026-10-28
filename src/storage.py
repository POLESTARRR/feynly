"""Durable JSON read/write shared by the concept and progress stores.

Two failure modes matter here, because both stores hold data the user cannot
regenerate, their notes and their entire score history:

- A crash (or full disk) partway through a write would otherwise leave a
  truncated file. `write_json` writes to a temp file in the same directory and
  atomically renames it over the target, so the old file survives intact until
  the new one is complete.
- A file that is already corrupt should not take the app down on startup.
  `read_json` moves the bad file aside (keeping it for recovery) and continues
  from the default, telling the caller what happened.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path


class CorruptStoreError(Exception):
    """Raised only when a corrupt file could not even be moved aside."""


def read_json(path: Path | str, default: dict | None = None) -> tuple[dict, str | None]:
    """Read JSON from `path`.

    Returns (data, warning). `warning` is None on success, or a human-readable
    message when the file was missing content/corrupt and was quarantined.
    """
    path = Path(path)
    default = {} if default is None else default

    if not path.exists():
        return dict(default), None

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        backup = _quarantine(path)
        return dict(default), (
            f"{path.name} was unreadable ({exc.__class__.__name__}) and was moved to "
            f"{backup.name}; starting from empty."
        )
    except OSError as exc:
        raise CorruptStoreError(f"Could not read {path}: {exc}") from exc

    if not isinstance(data, dict):
        backup = _quarantine(path)
        return dict(default), (
            f"{path.name} did not contain a JSON object and was moved to "
            f"{backup.name}; starting from empty."
        )

    return data, None


def _quarantine(path: Path) -> Path:
    """Move a bad file aside so it is never silently overwritten."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_suffix(path.suffix + f".corrupt-{stamp}")
    try:
        path.rename(backup)
    except OSError as exc:
        raise CorruptStoreError(f"Could not quarantine corrupt file {path}: {exc}") from exc
    return backup


def write_json(path: Path | str, data: dict, *, sort_keys: bool = False) -> None:
    """Atomically write `data` as JSON to `path`."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Same directory as the target, so the rename stays on one filesystem.
    fd, temp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=sort_keys)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_name, path)
    except BaseException:
        # Leave the original file untouched if anything at all went wrong.
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise
