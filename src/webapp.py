#!/usr/bin/env python3
"""Browser front end, the same engine the terminal uses, with a UI.

    python src/webapp.py                 # http://127.0.0.1:5050
    python src/webapp.py --port 8080

This is a real read/write interface: explain concepts and get graded, upload
photos of notes, ask the tutor, and see your progress. It adds no study logic of
its own, every route delegates to the same modules `study.py` calls, so the two
front ends can never disagree about a score or a schedule.

It binds to localhost by default. `--host 0.0.0.0` exposes it to your network,
which is unauthenticated by design, so it warns loudly.
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, render_template, request, session

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.concepts import UNCATEGORIZED, ConceptStore, parse_markdown_notes  # noqa: E402
from src.gamification import (  # noqa: E402
    ALL_BADGES,
    attempt_xp,
    current_streak,
    earned_badge_keys,
    earned_badges,
    level_for_xp,
    longest_streak,
    total_xp,
)
from src.grader import GradingError, grade_explanation  # noqa: E402
from src.import_notes import ImportError_, transcribe_image  # noqa: E402
from src.progress import ProgressStore  # noqa: E402
from src.scheduler import pick_next  # noqa: E402
from src import db  # noqa: E402
from src.stores import (  # noqa: E402
    LOCAL_USER,
    concept_store,
    progress_store,
    session_key,
    tutor_history,
    using_database,
)
from src.tutor import TutorError  # noqa: E402
from src.tutor import answer as tutor_answer  # noqa: E402

SESSION_ID = LOCAL_USER  # what the terminal uses; overridden per visitor when deployed
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
USER_COOKIE = "feynly_user"

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
# Signing key for the session cookie. Locally a fixed value is fine because the
# cookie only distinguishes one person from themselves; deployed it must be a
# real secret, or anyone could forge a cookie and read another user's notes.
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or (
    "feynly-local-only" if not using_database() else secrets.token_hex(32)
)


if using_database():
    # Create tables once at import, so the first visitor does not hit a
    # missing-table error on a cold container.
    try:
        db.init_schema()
    except Exception as exc:  # noqa: BLE001 - log and continue; routes report it
        print(f"WARNING: could not initialise the database schema: {exc}", file=sys.stderr)


def current_user() -> str:
    """The visitor's own id, minted on first request and kept in a signed cookie.

    Anonymous by design: no sign-up stands between someone and their first
    explanation. The id is what every store scopes to, so two visitors never see
    each other's notes or scores.
    """
    if not using_database():
        return LOCAL_USER
    if USER_COOKIE not in session:
        session[USER_COOKIE] = secrets.token_urlsafe(16)
        session.permanent = True
    return session[USER_COOKIE]


def stores():
    """Fresh stores per request, scoped to whoever is asking."""
    user = current_user()
    return concept_store(user), progress_store(user)


def history_store():
    return tutor_history(current_user())


# ------------------------------------------------------------------ pages


@app.get("/")
def study_page():
    concepts, progress = stores()
    names = concepts.names()

    requested = (request.args.get("concept") or "").strip().lower()
    reason = None
    concept = None

    if requested and concepts.exists(requested):
        concept = requested
    elif names:
        choice = pick_next(names, progress.averages(session_key(current_user())), progress.review_states(session_key(current_user())))
        if choice:
            concept, raw_reason = choice
            reason = {
                "due": "due for review",
                "weak": "a weak spot",
                "strong": "reinforcing a strength",
                "new": "not tried yet",
            }.get(raw_reason, raw_reason)

    # Grouped by subject: a flat list of every concept is unscannable once a few
    # subjects are loaded, which is exactly when newly added material gets lost.
    grouped = [
        (subject, concepts.names(subject))
        for subject in concepts.subjects()
    ]

    return render_template(
        "study.html",
        active="study",
        concept=concept,
        subject=concepts.subject_of(concept) if concept else None,
        reason=reason,
        concepts=names,
        grouped=grouped,
        total_concepts=len(names),
        due_count=len(progress.due(session_key(current_user()))),
    )


@app.get("/dashboard")
def dashboard_page():
    return render_template("dashboard.html", active="dashboard", data=build_dashboard_data())


@app.get("/tutor")
def tutor_page():
    history = history_store()
    return render_template("tutor.html", active="tutor", turns=history.recent(40))


@app.get("/notes")
def import_page():
    concepts, _ = stores()
    return render_template(
        "import.html",
        active="import",
        total_concepts=len(concepts),
        concepts=[
            {"name": n, "subject": concepts.subject_of(n) or UNCATEGORIZED}
            for n in concepts.names()
        ],
    )


# -------------------------------------------------------------------- api


@app.post("/api/explain")
def api_explain():
    payload = request.get_json(silent=True) or {}
    concept = (payload.get("concept") or "").strip().lower()
    explanation = (payload.get("explanation") or "").strip()

    if not concept:
        return jsonify({"error": "No concept given."}), 400
    if not explanation:
        return jsonify({"error": "Write an explanation first."}), 400

    concepts, progress = stores()
    notes = concepts.get(concept)
    if notes is None:
        return jsonify({"error": f'"{concept}" isn\'t loaded.'}), 404

    try:
        result = grade_explanation(concept, notes, explanation)
    except GradingError as exc:
        return jsonify({"error": str(exc)}), 502

    mapping = {n: concepts.subject_of(n) for n in concepts.names()}
    before = earned_badge_keys(progress.all_attempts(session_key(current_user())), mapping)
    state = progress.record(session_key(current_user()), concept, result["score"])
    after = earned_badge_keys(progress.all_attempts(session_key(current_user())), mapping)

    new_badges = [b.name for b in ALL_BADGES if b.key in (after - before)]
    return jsonify({
        **result,
        "concept": concept,
        "next_due": state.due,
        "xp": attempt_xp(result["score"]),
        "new_badges": new_badges,
    })


@app.post("/api/tutor")
def api_tutor():
    payload = request.get_json(silent=True) or {}
    question = (payload.get("question") or "").strip()
    if not question:
        return jsonify({"error": "Ask something first."}), 400

    concepts, progress = stores()
    try:
        reply = tutor_answer(question, concepts, progress, history_store(), session_key(current_user()))
    except TutorError as exc:
        return jsonify({"error": str(exc)}), 502
    return jsonify({"reply": reply})


@app.post("/api/tutor/forget")
def api_tutor_forget():
    history_store().clear()
    return jsonify({"ok": True})


@app.post("/api/import")
def api_import():
    uploads = request.files.getlist("images")
    if not uploads:
        return jsonify({"error": "No images uploaded."}), 400

    subject = (request.form.get("subject") or "").strip() or None
    sections: list[str] = []
    failures: list[str] = []

    for index, upload in enumerate(uploads):
        if not upload.filename:
            continue
        suffix = Path(upload.filename).suffix or ".png"
        # Written to a real file because transcription reads from disk.
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            upload.save(tmp.name)
            temp_path = Path(tmp.name)
        try:
            markdown = transcribe_image(temp_path, subject if index == 0 else None)
            sections.append(markdown)
        except ImportError_ as exc:
            failures.append(f"{upload.filename}: {exc}")
        finally:
            temp_path.unlink(missing_ok=True)

    if not sections:
        return jsonify({"error": "Couldn't read any of those. " + " ".join(failures)}), 502

    combined = "\n\n".join(sections) + "\n"
    return jsonify({
        "markdown": combined,
        "concept_count": len(parse_markdown_notes(combined, default_subject=subject)),
        "failures": failures,
    })


@app.post("/api/import/save")
def api_import_save():
    payload = request.get_json(silent=True) or {}
    markdown = (payload.get("markdown") or "").strip()
    subject = (payload.get("subject") or "").strip() or None

    if not markdown:
        return jsonify({"error": "Nothing to save."}), 400

    parsed = parse_markdown_notes(markdown, default_subject=subject)
    if not parsed:
        return jsonify({"error": "No '## Concept' headings found, nothing to save."}), 400

    concepts, _ = stores()
    concepts.merge(parsed)
    concepts.save()
    # Hand back the names so the page can offer to study what was just added.
    # Otherwise new material is invisible behind the due queue, which always
    # wins, and the user is left wondering whether the save worked at all.
    added = sorted(name.strip().lower() for name in parsed)
    return jsonify({"added": len(parsed), "total": len(concepts), "names": added})


@app.get("/api/data")
def api_data():
    return jsonify(build_dashboard_data())


# -------------------------------------------------------------- dashboard


def build_dashboard_data() -> dict:
    """Everything the dashboard renders, derived from the same stores as the CLI."""
    concepts, progress = stores()

    averages = progress.averages(session_key(current_user()))
    states = progress.review_states(session_key(current_user()))
    due = progress.due(session_key(current_user()))
    attempts = progress.all_attempts(session_key(current_user()))

    per_concept = []
    for name in concepts.names():
        history = progress.history(session_key(current_user()), name)
        state = states.get(name)
        per_concept.append({
            "concept": name,
            "subject": concepts.subject_of(name) or UNCATEGORIZED,
            "average": averages.get(name),
            "attempts": len(history),
            "latest": history[-1]["score"] if history else None,
            "scores": [h["score"] for h in history],
            "due": state.due if state else None,
        })

    per_subject = []
    for subject in concepts.subjects():
        names = concepts.names(subject)
        studied = [n for n in names if n in averages]
        per_subject.append({
            "subject": subject,
            "concepts": len(names),
            "studied": len(studied),
            "average": (sum(averages[n] for n in studied) / len(studied)) if studied else None,
            "due": len([c for c, _ in due if c in set(names)]),
        })

    by_day: dict[str, list[float]] = defaultdict(list)
    for _, score, ts in attempts:
        by_day[ts[:10]].append(score)
    trend = [
        {"date": day, "average": sum(s) / len(s), "count": len(s)}
        for day, s in sorted(by_day.items())
    ]

    mapping = {n: concepts.subject_of(n) for n in concepts.names()}
    xp = total_xp(attempts)
    level = level_for_xp(xp)
    unlocked = {b.key for b in earned_badges(attempts, mapping)}

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "totals": {
            "loaded": len(concepts),
            "studied": len(averages),
            "attempts": progress.total_attempts(session_key(current_user())),
            "due": len(due),
            "overall_average": (sum(averages.values()) / len(averages)) if averages else None,
        },
        "gamification": {
            "xp": xp,
            "level": level.level,
            "xp_into_level": level.xp_into_level,
            "xp_for_next": level.xp_for_next,
            "progress_percent": round(level.progress_fraction * 100),
            "current_streak": current_streak(attempts),
            "longest_streak": longest_streak(attempts),
            "badges": [
                {"name": b.name, "description": b.description, "earned": b.key in unlocked}
                for b in ALL_BADGES
            ],
            "earned_count": len(unlocked),
            "total_count": len(ALL_BADGES),
        },
        "concepts": per_concept,
        "subjects": per_subject,
        "due": [{"concept": c, "days_overdue": d} for c, d in due],
        "trend": trend,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Feynly, browser interface.")
    parser.add_argument("--port", "-p", type=int, default=int(os.environ.get("PORT", "5050")),
                        help="Port to serve on (default 5050; 5000 collides with macOS AirPlay)")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Bind address. Default is localhost only.")
    args = parser.parse_args()

    if args.host != "127.0.0.1":
        print(
            "\n  WARNING: binding to "
            f"{args.host} exposes this to your network with no login,\n"
            "  and anyone who reaches it can spend your Claude subscription.\n"
        )

    print(f"Feynly: http://127.0.0.1:{args.port}  (Ctrl+C to stop)")
    try:
        app.run(host=args.host, port=args.port, debug=False)
    except OSError as exc:
        print(f"\nCould not start on port {args.port}: {exc}", file=sys.stderr)
        print(f"Try:  python src/webapp.py --port {args.port + 1}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
