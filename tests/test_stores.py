"""Choosing between local JSON stores and per-user database stores."""

import pytest

from src import db, stores
from src.concepts import ConceptStore
from src.progress import ProgressStore
from src.tutor import TutorHistory


@pytest.fixture
def no_database(monkeypatch):
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    # Cleared too, or a developer with this set in their shell silently tests
    # the database path while reading a test that says local.
    monkeypatch.delenv(db.SQLITE_PATH_VAR, raising=False)


@pytest.fixture
def with_database(monkeypatch):
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://example.turso.io")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "token")
    monkeypatch.delenv(db.SQLITE_PATH_VAR, raising=False)


@pytest.fixture
def with_sqlite(monkeypatch, tmp_path):
    """The fallback: a real database, no cloud account, no credential."""
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.setenv(db.SQLITE_PATH_VAR, str(tmp_path / "feynly.db"))


# ------------------------------------------------------------- selection


def test_local_by_default(no_database):
    assert stores.using_database() is False
    assert isinstance(stores.concept_store(), ConceptStore)
    assert isinstance(stores.progress_store(), ProgressStore)
    assert isinstance(stores.tutor_history(), TutorHistory)


def test_database_when_configured(with_database):
    assert stores.using_database() is True
    assert isinstance(stores.concept_store("u1"), db.TursoConceptStore)
    assert isinstance(stores.progress_store("u1"), db.TursoProgressStore)
    assert isinstance(stores.tutor_history("u1"), db.TursoTutorHistory)


def test_half_configured_stays_local(monkeypatch):
    """A URL without a token must not be treated as a working database."""
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://example.turso.io")
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    assert stores.using_database() is False


def test_database_stores_carry_their_user(with_database):
    assert stores.concept_store("alice").user_id == "alice"
    assert stores.progress_store("bob").user_id == "bob"


# ----------------------------------------------------------- session key


def test_session_key_is_local_when_offline(no_database):
    # Locally everything shares one history, which the terminal also uses.
    assert stores.session_key("anything") == stores.LOCAL_USER


def test_session_key_is_the_user_when_deployed(with_database):
    assert stores.session_key("alice") == "alice"


# ------------------------------------------------------------- contract


def test_both_concept_stores_expose_the_same_surface(with_database):
    """If these drift, the app breaks only once deployed, which is the worst
    possible moment to find out."""
    required = {
        "get", "subject_of", "exists", "names", "subjects", "subject_exists",
        "counts_by_subject", "find_close_matches", "add", "merge", "replace_all", "save",
    }
    assert required <= set(dir(ConceptStore))
    assert required <= set(dir(db.TursoConceptStore))


def test_both_progress_stores_expose_the_same_surface(with_database):
    required = {
        "record", "history", "average", "averages", "latest_score", "review_state",
        "review_states", "due", "weakest", "studied_concepts", "total_attempts",
        "all_attempts",
    }
    assert required <= set(dir(ProgressStore))
    assert required <= set(dir(db.TursoProgressStore))


def test_both_tutor_histories_expose_the_same_surface(with_database, tmp_path):
    """Checked on instances, not classes: the JSON store sets `turns` in
    __init__ while the database one exposes it as a property, so a class-level
    check would miss it on one side and prove nothing."""
    required = {"add", "clear", "recent", "turns"}
    assert required <= set(dir(TutorHistory(tmp_path / "t.json")))
    assert required <= set(dir(db.TursoTutorHistory("u1")))


# ------------------------------------------------------------- database


def test_connect_requires_both_settings(monkeypatch):
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    with pytest.raises(db.DatabaseError, match="TURSO_DATABASE_URL"):
        db.connect()


def test_schema_covers_every_table():
    combined = " ".join(db.SCHEMA)
    for table in ("concepts", "attempts", "review_state", "tutor_turns"):
        assert table in combined


def test_every_table_is_scoped_by_user():
    """The whole isolation guarantee rests on this."""
    for statement in db.SCHEMA:
        if "CREATE TABLE" in statement:
            assert "user_id" in statement


def test_user_scoped_tables_key_on_user_id():
    for statement in db.SCHEMA:
        if "PRIMARY KEY" in statement:
            assert "user_id" in statement.split("PRIMARY KEY")[1]


# --------------------------------------------------------------- sqlite


def test_sqlite_path_counts_as_a_database(with_sqlite):
    """Without this the app falls back to JSON, where every visitor shares one
    account. That is the bug this fallback exists to prevent."""
    assert stores.using_database() is True
    assert isinstance(stores.concept_store("u1"), db.TursoConceptStore)
    assert stores.session_key("alice") == "alice"


def test_turso_wins_when_both_are_configured(monkeypatch, tmp_path):
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://example.turso.io")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "token")
    monkeypatch.setenv(db.SQLITE_PATH_VAR, str(tmp_path / "unused.db"))
    try:
        client = db.connect()
    except db.DatabaseError as exc:
        # libsql-client is a deploy-only dependency, so locally the Turso branch
        # stops at the import. Either outcome proves it did not pick SQLite.
        assert "libsql-client" in str(exc)
    else:
        assert not isinstance(client, db._SqliteClient)
        client.close()


def test_sqlite_creates_a_missing_parent_directory(monkeypatch, tmp_path):
    """A host handing over an empty volume must not 500 on the first visitor."""
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.setenv(db.SQLITE_PATH_VAR, str(tmp_path / "nested" / "dir" / "f.db"))
    with db.connect() as client:
        assert isinstance(client, db._SqliteClient)


def test_sqlite_round_trips_a_concept(with_sqlite):
    db.init_schema()
    store = db.TursoConceptStore("alice")
    store.add("inertia", "An object resists a change in its state of motion.", "physics")
    store.save()

    assert db.TursoConceptStore("alice").get("inertia") is not None
    assert db.TursoConceptStore("alice").subject_of("inertia") == "physics"


def test_sqlite_keeps_two_visitors_apart(with_sqlite):
    """The whole reason the fallback exists, asserted end to end."""
    db.init_schema()

    alice = db.TursoConceptStore("alice")
    alice.add("inertia", "An object resists a change in its state of motion.")
    alice.save()

    assert db.TursoConceptStore("bob").names() == []
    assert db.TursoConceptStore("bob").get("inertia") is None
    assert "inertia" in db.TursoConceptStore("alice").names()


def test_sqlite_keeps_two_visitors_scores_apart(with_sqlite):
    db.init_schema()
    db.TursoProgressStore("alice").record("alice", "inertia", 8.0)

    assert db.TursoProgressStore("bob").total_attempts("bob") == 0
    assert db.TursoProgressStore("alice").total_attempts("alice") == 1


def test_sqlite_survives_reopening(with_sqlite):
    """Each operation opens its own short-lived connection, so the data has to
    outlive the client rather than living in it."""
    db.init_schema()
    store = db.TursoConceptStore("alice")
    store.add("inertia", "An object resists a change in its state of motion.")
    store.save()

    reopened = db.TursoConceptStore("alice")
    assert reopened.get("inertia") is not None
