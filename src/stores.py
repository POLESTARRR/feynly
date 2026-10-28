"""Chooses between local JSON stores and per-user Turso stores.

Local use stays exactly as it was: plain files under `data/`, one history, no
database, nothing leaving the machine. Set the Turso environment variables and
the same app becomes multi-user, with every read and write scoped to the visitor
holding the session cookie.

The two implementations expose identical interfaces, so nothing above this
module needs to know which one it has.
"""

from __future__ import annotations

from src import db
from src.concepts import ConceptStore
from src.progress import ProgressStore
from src.tutor import TutorHistory

# The single history used when running locally, shared with the terminal app.
LOCAL_USER = "local"


def using_database() -> bool:
    return db.is_configured()


def concept_store(user_id: str = LOCAL_USER):
    return db.TursoConceptStore(user_id) if using_database() else ConceptStore()


def progress_store(user_id: str = LOCAL_USER):
    return db.TursoProgressStore(user_id) if using_database() else ProgressStore()


def tutor_history(user_id: str = LOCAL_USER):
    return db.TursoTutorHistory(user_id) if using_database() else TutorHistory()


def session_key(user_id: str = LOCAL_USER) -> str:
    """What to pass as the session id to store methods.

    The JSON stores key their contents by this value. The Turso stores are
    already scoped to a user and ignore it, but still accept it so callers have
    one code path.
    """
    return LOCAL_USER if not using_database() else user_id
