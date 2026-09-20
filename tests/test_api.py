import json


def test_api_lists_seed_tasks(client):
    response = client.get("/api/tasks", headers={"Accept": "application/json"})
    assert response.status_code == 200
    tasks = response.get_json()["tasks"]
    assert len(tasks) == 4
    assert {t["status"] for t in tasks} == {"todo", "in_progress", "done"}


def test_api_lists_seed_projects(client):
    response = client.get("/api/projects", headers={"Accept": "application/json"})
    assert response.status_code == 200
    projects = response.get_json()["projects"]
    assert len(projects) == 2
    assert all(p["task_count"] == 2 for p in projects)


def test_api_create_get_patch_delete_task(client, csrf_token, make_project):
    project = make_project(client, csrf_token, name="API Project")
    project_id = project.get_json()["project"]["id"]

    created = client.post(
        "/api/tasks",
        json={
            "title": "API born task",
            "status": "todo",
            "project_id": project_id,
            "csrf_token": csrf_token,
        },
        headers={"Accept": "application/json"},
    )
    assert created.status_code == 201
    task = created.get_json()["task"]
    assert task["title"] == "API born task"
    assert task["status"] == "todo"
    assert task["project_name"] == "API Project"

    detail = client.get(
        f"/api/tasks/{task['id']}", headers={"Accept": "application/json"}
    )
    assert detail.status_code == 200
    assert detail.get_json()["task"]["id"] == task["id"]

    patched = client.patch(
        f"/api/tasks/{task['id']}",
        json={"status": "done", "title": "API patched task", "csrf_token": csrf_token},
        headers={"Accept": "application/json"},
    )
    assert patched.status_code == 200
    updated = patched.get_json()["task"]
    assert updated["status"] == "done"
    assert updated["title"] == "API patched task"

    deleted = client.delete(
        f"/api/tasks/{task['id']}",
        json={"csrf_token": csrf_token},
        headers={"Accept": "application/json"},
    )
    assert deleted.status_code == 204
    missing = client.get(
        f"/api/tasks/{task['id']}", headers={"Accept": "application/json"}
    )
    assert missing.status_code == 404
    assert missing.get_json()["error"] == "Not found"


def test_api_task_create_validation(client, csrf_token):
    empty = client.post(
        "/api/tasks",
        json={"title": "", "csrf_token": csrf_token},
        headers={"Accept": "application/json"},
    )
    assert empty.status_code == 400
    assert "title" in empty.get_json()["errors"]

    bad_status = client.post(
        "/api/tasks",
        json={"title": "X", "status": "sideways", "csrf_token": csrf_token},
        headers={"Accept": "application/json"},
    )
    assert bad_status.status_code == 400
    assert "status" in bad_status.get_json()["errors"]


def test_api_task_malformed_json(client, csrf_token):
    response = client.post(
        "/api/tasks",
        data="{not valid json",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-CSRF-Token": csrf_token,
        },
    )
    assert response.status_code == 400
    body = response.get_json()
    assert body["error"] == "Bad request"
    assert "JSON" in body["detail"]


def test_api_non_object_json(client, csrf_token):
    response = client.post(
        "/api/tasks",
        json=["not", "an", "object"],
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 400


def test_api_requires_csrf(client):
    response = client.post(
        "/api/tasks",
        json={"title": "no token"},
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 400
    assert "CSRF" in response.get_json()["detail"]


def test_api_invalid_status_filter(client):
    response = client.get(
        "/api/tasks?status=bogus", headers={"Accept": "application/json"}
    )
    assert response.status_code == 400


def test_api_not_found(client, csrf_token):
    response = client.get("/api/tasks/999999", headers={"Accept": "application/json"})
    assert response.status_code == 404

    response = client.patch(
        "/api/tasks/999999",
        json={"title": "nope", "csrf_token": csrf_token},
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 404

    response = client.delete(
        "/api/tasks/999999",
        json={"csrf_token": csrf_token},
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 404


def test_api_search_filter(client, csrf_token, make_task):
    make_task(client, csrf_token, title="Needle in haystack")
    make_task(client, csrf_token, title="Plain straw")
    response = client.get("/api/tasks?q=needle", headers={"Accept": "application/json"})
    titles = [t["title"] for t in response.get_json()["tasks"]]
    assert "Needle in haystack" in titles
    assert "Plain straw" not in titles


def test_api_create_project_validation(client, csrf_token):
    response = client.post(
        "/api/projects",
        json={"name": "", "csrf_token": csrf_token},
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 400


def test_api_create_task_rejects_unknown_project(client, csrf_token):
    response = client.post(
        "/api/tasks",
        json={"title": "X", "project_id": 424242, "csrf_token": csrf_token},
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 400
    assert "project_id" in response.get_json()["errors"]
