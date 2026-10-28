#!/usr/bin/env python3
"""Study reminder, sends a macOS notification about what's due.

Designed to be run by launchd (see install_reminder.sh), not by hand, though
running it manually is a fine way to test it.

Exits 0 when a notification was sent, 0 when nothing is due (silent, by design
- a reminder that fires when you're caught up trains you to ignore reminders).
"""

from __future__ import annotations

import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.concepts import ConceptStore  # noqa: E402
from src.progress import ProgressStore  # noqa: E402
from src.scheduler import pick_next  # noqa: E402
from src.study import LOCAL_CHAT_ID  # noqa: E402

TITLE = "Feynly"


def notify(title: str, message: str) -> bool:
    """Post a macOS notification. Returns False if osascript isn't available."""
    script = f'display notification {message!r} with title {title!r}'
    try:
        subprocess.run(["osascript", "-e", script], check=True, capture_output=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def build_message(today: date | None = None) -> str | None:
    """What to nudge about, or None if there's nothing worth interrupting for.

    `today` is injectable so scheduling behavior can be tested against a fixed
    date rather than whatever day the suite happens to run on.
    """
    concepts = ConceptStore()
    progress = ProgressStore()

    if not len(concepts):
        return None

    due = progress.due(LOCAL_CHAT_ID, today=today)
    if due:
        first = due[0][0]
        if len(due) == 1:
            return f"{first} is due for review."
        return f"{len(due)} concepts due, start with {first}."

    # Nothing overdue: only nudge if there's something genuinely new to learn.
    choice = pick_next(concepts.names(), progress.averages(LOCAL_CHAT_ID),
                       progress.review_states(LOCAL_CHAT_ID))
    if choice and choice[1] == "new":
        return f"Nothing due. Try something new: {choice[0]}."
    return None


def main() -> int:
    message = build_message()
    if message is None:
        return 0
    if not notify(TITLE, message):
        # Fall back to stdout so the message isn't lost off-macOS or in CI.
        print(f"{TITLE}: {message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
