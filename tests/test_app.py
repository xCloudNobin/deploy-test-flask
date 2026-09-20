import os

from app import create_app


def test_health_endpoint_reports_okay(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "app": "deploy-test-flask"}


def test_readiness_reports_ready_when_database_available(client):
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ready", "database": "ok"}


def test_readiness_fails_when_database_unavailable(tmp_path):
    bad_dir = tmp_path / "not-a-file"
    bad_dir.mkdir()
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(bad_dir),
            "SECRET_KEY": "test-secret",
        }
    )
    client = app.test_client()
    assert client.get("/health").status_code == 200
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.get_json()["status"] == "unavailable"


def test_unavailable_database_returns_503_on_pages(tmp_path):
    bad_dir = tmp_path / "not-a-file"
    bad_dir.mkdir()
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(bad_dir),
            "SECRET_KEY": "test-secret",
        }
    )
    client = app.test_client()
    assert client.get("/").status_code == 503
    assert (
        client.get("/api/tasks", headers={"Accept": "application/json"}).status_code
        == 503
    )


def test_index_renders_project_groups_and_seed_data(client):
    response = client.get("/")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Website Redesign" in body
    assert "Launch Checklist" in body
    assert "Run smoke tests" in body


def test_index_renders_build_marker(monkeypatch, tmp_path):
    monkeypatch.setenv("BUILD_MARKER", "marker-abc123")
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "tasks.db"),
            "SECRET_KEY": "test-secret",
        }
    )
    body = app.test_client().get("/").get_data(as_text=True)
    assert "marker-abc123" in body
    assert "abc123" in body.split("Build marker:")[1]


def test_nested_routes_and_static_assets(client):
    assert client.get("/static/app.css").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    page = client.get("/tasks/new").get_data(as_text=True)
    assert "static/app.js" in page


def test_html_output_escapes_user_data(client, csrf_token, make_task):
    response = make_task(
        client,
        csrf_token,
        title='<script>alert("xss")</script>',
    )
    assert response.status_code == 201
    body = client.get("/").get_data(as_text=True)
    assert "<script>alert" not in body
    assert "&lt;script&gt;alert" in body


def test_missing_page_returns_html_404(client):
    response = client.get("/projects/999999")
    assert response.status_code == 404
    body = response.get_data(as_text=True)
    assert "404" in body


def test_database_failure_maps_to_503(client):
    import sqlite3

    import app as app_module

    def boom():
        raise sqlite3.OperationalError("database is locked")

    original = app_module.get_db
    app_module.get_db = boom
    try:
        assert client.get("/ready").status_code == 503
        assert client.get("/").status_code == 503
    finally:
        app_module.get_db = original
