import pytest

from app import create_app

DEFAULT_TOKEN = "test-csrf-token"


@pytest.fixture()
def app(tmp_path):
    return create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "tasks.db"),
            "SECRET_KEY": "test-secret",
            "SERVER_NAME": "localhost",
        }
    )


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def csrf_token(client):
    with client.session_transaction() as session:
        session["_csrf_token"] = DEFAULT_TOKEN
    return DEFAULT_TOKEN


def create_project(client, csrf_token, name="Alpha", description="d"):
    return client.post(
        "/api/projects",
        json={"name": name, "description": description, "csrf_token": csrf_token},
        headers={"Accept": "application/json"},
    )


def create_task(client, csrf_token, title="T1", project_id=None, status="todo"):
    payload = {"title": title, "status": status, "csrf_token": csrf_token}
    if project_id is not None:
        payload["project_id"] = project_id
    return client.post(
        "/api/tasks",
        json=payload,
        headers={"Accept": "application/json"},
    )


@pytest.fixture()
def make_project():
    return create_project


@pytest.fixture()
def make_task():
    return create_task
