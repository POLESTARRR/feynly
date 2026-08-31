"""Turso-backed stores, for the deployed instance.

Two problems the JSON stores cannot solve once Feynly is public:

Free hosts give you an ephemeral filesystem, so `data/*.json` disappears on
every restart and a user's history evaporates with it.

More seriously, the JSON stores key everything under one session id. Deployed
unchanged, every visitor would read and overwrite the same notes and the same
scores. Every table here is keyed by `user_id` and every query filters on it, so
one person's material is never reachable from another's session.

These classes deliberately mirror the JSON stores' interfaces exactly, so the
rest of the app cannot tell which is in use. `stores.py` picks between them.
"""

from __future__ import annotations

import os
import re
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from src.concepts import UNCATEGORIZED, ParsedConcept, _normalize
from src.scheduler import ReviewState, due_concepts, review_state

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS concepts (
        user_id TEXT NOT NULL,
        name    TEXT NOT NULL,
        notes   TEXT NOT NULL,
        subject TEXT,
        PRIMARY KEY (user_id, name)
    )""",
    """CREATE TABLE IF NOT EXISTS attempts (
        user_id TEXT NOT NULL,
        concept TEXT NOT NULL,
        score   REAL NOT NULL,
        ts      TEXT NOT NULL
    )""",
    """CREATE INDEX IF NOT EXISTS attempts_by_user ON attempts (user_id, concept)""",
    """CREATE TABLE IF NOT EXISTS review_state (
        user_id       TEXT NOT NULL,
        concept       TEXT NOT NULL,
        ease          REAL NOT NULL,
        interval_days INTEGER NOT NULL,
        repetitions   INTEGER NOT NULL,
        due           TEXT,
        PRIMARY KEY (user_id, concept)
    )""",
    """CREATE TABLE IF NOT EXISTS tutor_turns (
        user_id TEXT NOT NULL,
        role    TEXT NOT NULL,
        text    TEXT NOT NULL,
        ts      TEXT NOT NULL
    )""",
)


class DatabaseError(RuntimeError):
    pass


# A local SQLite file is the fallback when Turso is not set up. It gives the
# deployed app the one thing the JSON stores cannot: a separate history per
# visitor. What it does not give is persistence, because free hosts wipe the
# filesystem when the container sleeps. That is the honest trade. Turso remains
# the upgrade, and setting its two variables takes precedence automatically.
SQLITE_PATH_VAR = "FEYNLY_SQLITE_PATH"


def turso_configured() -> bool:
    return bool(os.environ.get("TURSO_DATABASE_URL") and os.environ.get("TURSO_AUTH_TOKEN"))


def sqlite_path() -> str:
    return os.environ.get(SQLITE_PATH_VAR, "").strip()


def is_configured() -> bool:
    """True when a real database backs the app, so stores scope per visitor.

    Deliberately false for plain local use, which keeps the terminal app and the
    browser app sharing one JSON history on disk exactly as before.
    """
    return turso_configured() or bool(sqlite_path())


class _SqliteResult:
    """Mirrors the shape libsql_client returns, which is only ever `.rows`."""

    __slots__ = ("rows",)

    def __init__(self, rows):
        self.rows = rows


class _SqliteClient:
    """The slice of the libsql client this module actually uses.

    db.py touches a client three ways: as a context manager, `.execute(sql, args)`
    returning something with `.rows`, and positional access into those rows.
    stdlib sqlite3 satisfies all three, so every store class above works
    unchanged against a file.
    """

    def __init__(self, path: str):
        # One short-lived connection per operation, matching how `_Backed` uses
        # it, so threaded request handling never shares a connection.
        self._conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
        # WAL lets a reader and a writer overlap instead of one blocking on the
        # other, which a threaded web server does constantly.
        self._conn.execute("PRAGMA journal_mode=WAL")

    def execute(self, sql: str, args=None) -> _SqliteResult:
        cursor = self._conn.execute(sql, tuple(args or []))
        rows = cursor.fetchall()
        self._conn.commit()
        return _SqliteResult(rows)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        self.close()
        return False


def connect():
    """Open a database client. Callers are responsible for closing it."""
    url = os.environ.get("TURSO_DATABASE_URL", "")
    token = os.environ.get("TURSO_AUTH_TOKEN", "")

    if url and token:
        try:
            import libsql_client
        except ImportError as exc:
            raise DatabaseError(
                "libsql-client is not installed. Run: pip install libsql-client"
            ) from exc
        # The libsql:// scheme is spoken as https:// by the HTTP client.
        return libsql_client.create_client_sync(
            url=url.replace("libsql://", "https://"), auth_token=token
        )

    path = sqlite_path()
    if path:
        try:
            parent = Path(path).parent
            if str(parent) not in ("", "."):
                parent.mkdir(parents=True, exist_ok=True)
            return _SqliteClient(path)
        except OSError as exc:
            raise DatabaseError(f"Could not open the SQLite file at {path}: {exc}") from exc

    raise DatabaseError(
        f"No database configured. Set TURSO_DATABASE_URL and TURSO_AUTH_TOKEN, "
        f"or {SQLITE_PATH_VAR} for a local file."
    )


def init_schema() -> None:
    with connect() as client:
        for statement in SCHEMA:
            client.execute(statement)


class _Backed:
    """Shared connection handling. One short-lived client per operation keeps
    this safe across the threaded request handling a web server does."""

    def __init__(self, user_id: str):
        self.user_id = str(user_id)
        self.warning: str | None = None

    def _query(self, sql: str, args: list | None = None) -> list:
        try:
            with connect() as client:
                return list(client.execute(sql, args or []).rows)
        except DatabaseError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise DatabaseError(f"Query failed: {exc}") from exc

    def _write(self, statements: list[tuple[str, list]]) -> None:
        try:
            with connect() as client:
                for sql, args in statements:
                    client.execute(sql, args)
        except DatabaseError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise DatabaseError(f"Write failed: {exc}") from exc


# --------------------------------------------------------------- concepts


class TursoConceptStore(_Backed):
    """Same surface as ConceptStore, scoped to one user."""

    def __init__(self, user_id: str):
        super().__init__(user_id)
        self._pending: dict[str, dict] = {}

    def _all(self) -> dict[str, dict]:
        rows = self._query(
            "SELECT name, notes, subject FROM concepts WHERE user_id = ?", [self.user_id]
        )
        return {r[0]: {"notes": r[1], "subject": r[2]} for r in rows}

    # writing -------------------------------------------------------------

    def add(self, name: str, notes: str, subject: str | None = None) -> None:
        self._pending[_normalize(name)] = {
            "notes": notes.strip(),
            "subject": _normalize(subject) if subject else None,
        }

    def merge(self, other: dict) -> None:
        for name, value in other.items():
            if isinstance(value, ParsedConcept):
                self.add(name, value.notes, value.subject)
            else:
                self.add(name, value)

    def replace_all(self, other: dict) -> None:
        self._write([("DELETE FROM concepts WHERE user_id = ?", [self.user_id])])
        self._pending = {}
        self.merge(other)

    def save(self) -> None:
        if not self._pending:
            return
        self._write([
            ("INSERT INTO concepts (user_id, name, notes, subject) VALUES (?, ?, ?, ?) "
             "ON CONFLICT(user_id, name) DO UPDATE SET notes = excluded.notes, "
             "subject = excluded.subject",
             [self.user_id, name, entry["notes"], entry["subject"]])
            for name, entry in self._pending.items()
        ])
        self._pending = {}

    # reading -------------------------------------------------------------

    def get(self, name: str) -> str | None:
        key = _normalize(name)
        if key in self._pending:
            return self._pending[key]["notes"]
        rows = self._query(
            "SELECT notes FROM concepts WHERE user_id = ? AND name = ?", [self.user_id, key]
        )
        return rows[0][0] if rows else None

    def subject_of(self, name: str) -> str | None:
        key = _normalize(name)
        if key in self._pending:
            return self._pending[key]["subject"]
        rows = self._query(
            "SELECT subject FROM concepts WHERE user_id = ? AND name = ?", [self.user_id, key]
        )
        return rows[0][0] if rows else None

    def exists(self, name: str) -> bool:
        return self.get(name) is not None

    def names(self, subject: str | None = None) -> list[str]:
        entries = self._all()
        if subject is None:
            return sorted(entries)
        target = _normalize(subject)
        if target == UNCATEGORIZED:
            return sorted(n for n, e in entries.items() if not e["subject"])
        return sorted(n for n, e in entries.items() if e["subject"] == target)

    def subjects(self) -> list[str]:
        entries = self._all()
        named = sorted({e["subject"] for e in entries.values() if e["subject"]})
        if any(not e["subject"] for e in entries.values()):
            named.append(UNCATEGORIZED)
        return named

    def subject_exists(self, subject: str) -> bool:
        return _normalize(subject) in self.subjects()

    def counts_by_subject(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for entry in self._all().values():
            key = entry["subject"] or UNCATEGORIZED
            counts[key] = counts.get(key, 0) + 1
        return counts

    def __len__(self) -> int:
        rows = self._query("SELECT COUNT(*) FROM concepts WHERE user_id = ?", [self.user_id])
        return int(rows[0][0]) if rows else 0

    def find_close_matches(self, name: str, limit: int = 3) -> list[str]:
        target = _normalize(name)
        if not target:
            return []
        scored = []
        for candidate in self._all():
            if target == candidate:
                continue
            if candidate.startswith(target) or target in candidate:
                scored.append((0, candidate))
            elif candidate in target:
                scored.append((1, candidate))
            else:
                overlap = len(set(target.split()) & set(candidate.split()))
                if overlap:
                    scored.append((2 - overlap, candidate))
        scored.sort(key=lambda t: (t[0], t[1]))
        return [c for _, c in scored[:limit]]


# --------------------------------------------------------------- progress


class TursoProgressStore(_Backed):
    """Same surface as ProgressStore, scoped to one user.

    The session_id argument on every method is accepted and ignored: scoping
    comes from the user this store was built for, so a caller cannot reach
    another user's rows by passing a different id.
    """

    def record(self, session_id, concept: str, score: float, today: date | None = None) -> ReviewState:
        previous = self.review_state(session_id, concept)
        new_state = review_state(previous, score, today)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._write([
            ("INSERT INTO attempts (user_id, concept, score, ts) VALUES (?, ?, ?, ?)",
             [self.user_id, concept, float(score), now]),
            ("INSERT INTO review_state (user_id, concept, ease, interval_days, repetitions, due) "
             "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(user_id, concept) DO UPDATE SET "
             "ease = excluded.ease, interval_days = excluded.interval_days, "
             "repetitions = excluded.repetitions, due = excluded.due",
             [self.user_id, concept, new_state.ease, new_state.interval_days,
              new_state.repetitions, new_state.due]),
        ])
        return new_state

    def history(self, session_id, concept: str) -> list[dict]:
        rows = self._query(
            "SELECT score, ts FROM attempts WHERE user_id = ? AND concept = ? ORDER BY ts",
            [self.user_id, concept],
        )
        return [{"score": r[0], "ts": r[1]} for r in rows]

    def average(self, session_id, concept: str) -> float | None:
        attempts = self.history(session_id, concept)
        return (sum(a["score"] for a in attempts) / len(attempts)) if attempts else None

    def averages(self, session_id) -> dict[str, float]:
        rows = self._query(
            "SELECT concept, AVG(score) FROM attempts WHERE user_id = ? GROUP BY concept",
            [self.user_id],
        )
        return {r[0]: float(r[1]) for r in rows}

    def latest_score(self, session_id, concept: str) -> float | None:
        rows = self._query(
            "SELECT score FROM attempts WHERE user_id = ? AND concept = ? ORDER BY ts DESC LIMIT 1",
            [self.user_id, concept],
        )
        return float(rows[0][0]) if rows else None

    def review_state(self, session_id, concept: str) -> ReviewState:
        rows = self._query(
            "SELECT ease, interval_days, repetitions, due FROM review_state "
            "WHERE user_id = ? AND concept = ?",
            [self.user_id, concept],
        )
        if not rows:
            return ReviewState()
        ease, interval, reps, due = rows[0]
        return ReviewState(ease=float(ease), interval_days=int(interval),
                           repetitions=int(reps), due=due)

    def review_states(self, session_id) -> dict[str, ReviewState]:
        rows = self._query(
            "SELECT concept, ease, interval_days, repetitions, due FROM review_state "
            "WHERE user_id = ?",
            [self.user_id],
        )
        return {
            r[0]: ReviewState(ease=float(r[1]), interval_days=int(r[2]),
                              repetitions=int(r[3]), due=r[4])
            for r in rows
        }

    def due(self, session_id, today: date | None = None) -> list[tuple[str, int]]:
        return due_concepts(self.review_states(session_id), today)

    def weakest(self, session_id, limit: int = 5) -> list[tuple[str, float, int]]:
        rows = self._query(
            "SELECT concept, AVG(score), COUNT(*) FROM attempts WHERE user_id = ? "
            "GROUP BY concept ORDER BY AVG(score) ASC, COUNT(*) DESC LIMIT ?",
            [self.user_id, limit],
        )
        return [(r[0], float(r[1]), int(r[2])) for r in rows]

    def studied_concepts(self, session_id) -> list[str]:
        rows = self._query(
            "SELECT DISTINCT concept FROM attempts WHERE user_id = ? ORDER BY concept",
            [self.user_id],
        )
        return [r[0] for r in rows]

    def total_attempts(self, session_id) -> int:
        rows = self._query("SELECT COUNT(*) FROM attempts WHERE user_id = ?", [self.user_id])
        return int(rows[0][0]) if rows else 0

    def all_attempts(self, session_id) -> list[tuple[str, float, str]]:
        rows = self._query(
            "SELECT concept, score, ts FROM attempts WHERE user_id = ? ORDER BY ts",
            [self.user_id],
        )
        return [(r[0], float(r[1]), r[2]) for r in rows]


# ------------------------------------------------------------------ tutor


class TursoTutorHistory(_Backed):
    """Same surface as TutorHistory, scoped to one user."""

    MAX_KEPT = 200

    @property
    def turns(self) -> list:
        from src.tutor import Turn

        rows = self._query(
            "SELECT role, text, ts FROM tutor_turns WHERE user_id = ? ORDER BY ts, rowid",
            [self.user_id],
        )
        return [Turn(role=r[0], text=r[1], ts=r[2]) for r in rows]

    def add(self, role: str, text: str) -> None:
        self._write([
            ("INSERT INTO tutor_turns (user_id, role, text, ts) VALUES (?, ?, ?, ?)",
             [self.user_id, role, text,
              datetime.now(timezone.utc).isoformat(timespec="seconds")]),
        ])

    def clear(self) -> None:
        self._write([("DELETE FROM tutor_turns WHERE user_id = ?", [self.user_id])])

    def recent(self, limit: int = 12) -> list:
        return self.turns[-limit:]

    def __len__(self) -> int:
        rows = self._query("SELECT COUNT(*) FROM tutor_turns WHERE user_id = ?", [self.user_id])
        return int(rows[0][0]) if rows else 0
