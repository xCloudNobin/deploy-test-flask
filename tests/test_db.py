import sqlite3

from app import create_app
from db import SEED_PROJECTS


def _make_app(db_path):
    return create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": db_path,
            "SECRET_KEY": "test-secret",
        }
    )


def _counts(db_path):
    conn = sqlite3.connect(db_path)
    projects = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    tasks = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    conn.close()
    return projects, tasks


def test_seed_is_deterministic(tmp_path):
    first = str(tmp_path / "a.db")
    second = str(tmp_path / "b.db")
    with _make_app(first).app_context():
        from db import get_db

        get_db()
    with _make_app(second).app_context():
        from db import get_db

        get_db()
    assert _counts(first) == _counts(second)
    assert _counts(first) == (len(SEED_PROJECTS), 4)


def test_schema_initialization_is_idempotent(tmp_path):
    db_path = str(tmp_path / "idem.db")
    with _make_app(db_path).app_context():
        from db import get_db

        get_db()
    with _make_app(db_path).app_context():
        from db import get_db

        get_db()
    assert _counts(db_path) == (len(SEED_PROJECTS), 4)


def test_data_survives_app_restart(tmp_path):
    db_path = str(tmp_path / "restart.db")
    app1 = _make_app(db_path)
    with app1.test_client() as client:
        with client.session_transaction() as session:
            session["_csrf_token"] = "persist-token"
        created = client.post(
            "/api/tasks",
            json={
                "title": "Survivor task",
                "status": "in_progress",
                "csrf_token": "persist-token",
            },
            headers={"Accept": "application/json"},
        )
        assert created.status_code == 201
        survivor_id = created.get_json()["task"]["id"]

    app2 = _make_app(db_path)
    with app2.test_client() as client:
        detail = client.get(
            f"/api/tasks/{survivor_id}", headers={"Accept": "application/json"}
        )
        assert detail.status_code == 200
        assert detail.get_json()["task"]["title"] == "Survivor task"
        assert detail.get_json()["task"]["status"] == "in_progress"

    # Seed data must not be duplicated by re-initialization.
    assert _counts(db_path) == (len(SEED_PROJECTS), 5)
