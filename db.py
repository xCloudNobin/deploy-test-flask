import sqlite3
import threading
from pathlib import Path

from flask import current_app, g

STATUSES = ("todo", "in_progress", "done")

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"

# Serialize one-time schema/seed initialization so concurrent threads
# never double-seed a fresh database.
_init_lock = threading.Lock()


def get_db():
    """Return a database connection bound to the current request context.

    The connection is opened lazily so that a temporarily unavailable
    database does not prevent the process from booting; liveness stays up
    while readiness reports the dependency failure below.
    """
    db = getattr(g, "_db", None)
    if db is None:
        path = current_app.config["DATABASE_PATH"]
        db = g._db = sqlite3.connect(
            path, timeout=current_app.config["DATABASE_TIMEOUT"]
        )
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA journal_mode = WAL")
        init_db(db)
    return db


def close_db(_exc=None):
    db = g.pop("_db", None)
    if db is not None:
        db.close()


def init_db(db):
    """Create tables (idempotent) and seed deterministic sample data.

    Re-running on an already-initialized database is a no-op; sample data
    is inserted only when the tasks table is empty, always with fixed
    values.
    """
    with _init_lock:
        db.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
        count = db.execute("SELECT COUNT(*) AS n FROM tasks").fetchone()["n"]
        if count == 0:
            seed(db)
        db.commit()


def seed(db):
    for name, description, tasks in SEED_PROJECTS:
        project_id = db.execute(
            "INSERT INTO projects (name, description) VALUES (?, ?)",
            (name, description),
        ).lastrowid
        for title, task_description, status in tasks:
            db.execute(
                "INSERT INTO tasks (project_id, title, description, status)"
                " VALUES (?, ?, ?, ?)",
                (project_id, title, task_description, status),
            )


SEED_PROJECTS = (
    (
        "Website Redesign",
        "Refresh the public marketing site.",
        (
            (
                "Draft new homepage layout",
                "Reorganise the hero section.",
                "in_progress",
            ),
            (
                "Collect stakeholder feedback",
                "Walk the draft past the product team.",
                "todo",
            ),
        ),
    ),
    (
        "Launch Checklist",
        "Tasks required before the next release ships.",
        (
            (
                "Verify environment variables",
                "Confirm all settings exist in production.",
                "done",
            ),
            ("Run smoke tests", "Exercise CRUD plus restart persistence.", "todo"),
        ),
    ),
)
