def test_project_crud_flow(client, csrf_token):
    create = client.post(
        "/projects/new",
        data={
            "name": "Docs Sprint",
            "description": "Write the docs.",
            "csrf_token": csrf_token,
        },
    )
    assert create.status_code == 302
    location = create.headers["Location"]
    assert location.startswith("/projects/")
    project_id = location.rsplit("/", 1)[1]

    detail = client.get(location)
    assert detail.status_code == 200
    assert "Write the docs." in detail.get_data(as_text=True)

    edit = client.post(
        f"/projects/{project_id}/edit",
        data={
            "name": "Docs Sprint v2",
            "description": "Rewritten.",
            "csrf_token": csrf_token,
        },
        follow_redirects=True,
    )
    assert "Docs Sprint v2" in edit.get_data(as_text=True)

    delete = client.post(
        f"/projects/{project_id}/delete",
        data={"csrf_token": csrf_token},
        follow_redirects=True,
    )
    assert "Docs Sprint v2" not in delete.get_data(as_text=True)


def test_project_name_required(client, csrf_token):
    response = client.post(
        "/projects/new",
        data={"name": "  ", "csrf_token": csrf_token},
    )
    assert response.status_code == 400
    assert "Project name is required." in response.get_data(as_text=True)


def test_task_crud_flow(client, csrf_token, make_project):
    project = make_project(client, csrf_token, name="CRUD Project")
    project_id = project.get_json()["project"]["id"]

    new = client.post(
        "/tasks/new",
        data={
            "title": "Fix landing CSS",
            "description": "On mobile.",
            "status": "todo",
            "project_id": project_id,
            "csrf_token": csrf_token,
        },
        follow_redirects=True,
    )
    assert "Fix landing CSS" in new.get_data(as_text=True)
    from db import get_db

    with client.application.app_context():
        row = (
            get_db()
            .execute(
                "SELECT id FROM tasks WHERE title = 'Fix landing CSS' ORDER BY id DESC LIMIT 1"
            )
            .fetchone()
        )
        task_id = row["id"]

    edit = client.post(
        f"/tasks/{task_id}/edit",
        data={
            "title": "Fix landing CSS (mobile)",
            "description": "On phones.",
            "status": "in_progress",
            "project_id": project_id,
            "csrf_token": csrf_token,
        },
        follow_redirects=True,
    )
    body = edit.get_data(as_text=True)
    assert "Fix landing CSS (mobile)" in body
    assert "in_progress" in body

    status_post = client.post(
        f"/tasks/{task_id}/status",
        data={"status": "done", "csrf_token": csrf_token},
    )
    assert status_post.status_code in (200, 302)

    delete = client.post(
        f"/tasks/{task_id}/delete",
        data={"csrf_token": csrf_token},
        follow_redirects=True,
    )
    assert "Fix landing CSS (mobile)" not in delete.get_data(as_text=True)


def test_task_title_required(client, csrf_token):
    response = client.post(
        "/tasks/new",
        data={"title": "", "status": "todo", "csrf_token": csrf_token},
    )
    assert response.status_code == 400
    assert "Task title is required." in response.get_data(as_text=True)


def test_task_invalid_status_rejected(client, csrf_token):
    response = client.post(
        "/tasks/new",
        data={"title": "X", "status": "bogus", "csrf_token": csrf_token},
    )
    assert response.status_code == 400
    assert "Invalid status" in response.get_data(as_text=True)


def test_status_change_invalid_status_rejected(client, csrf_token, make_task):
    task = make_task(client, csrf_token, title="Ink Task")
    task_id = task.get_json()["task"]["id"]
    response = client.post(
        f"/tasks/{task_id}/status",
        data={"status": "nope", "csrf_token": csrf_token},
    )
    assert response.status_code == 400


def test_mutations_require_csrf(client):
    assert client.post("/tasks/new", data={"title": "X"}).status_code == 400
    assert client.post("/projects/new", data={"name": "X"}).status_code == 400


def test_search_and_status_filter(client, csrf_token, make_project, make_task):
    project = make_project(client, csrf_token, name="SearchProj")
    project_id = project.get_json()["project"]["id"]
    make_task(client, csrf_token, title="Unique needle", project_id=project_id)
    make_task(client, csrf_token, title="Ordinary hay", project_id=project_id)

    body = client.get("/?q=needle").get_data(as_text=True)
    assert "Unique needle" in body
    assert "Ordinary hay" not in body

    make_task(
        client, csrf_token, title="done task", project_id=project_id, status="done"
    )
    body = client.get("/?status=done").get_data(as_text=True)
    assert "done task" in body

    body = client.get("/projects/%d?status=done" % project_id).get_data(as_text=True)
    assert "done task" in body
    assert "Unique needle" not in body


def test_project_delete_unassigns_tasks(client, csrf_token, make_project, make_task):
    project = make_project(client, csrf_token, name="ToDelete")
    project_id = project.get_json()["project"]["id"]
    task = make_task(
        client, csrf_token, title="Becomes unassigned", project_id=project_id
    )
    task_id = task.get_json()["task"]["id"]

    delete = client.post(
        f"/projects/{project_id}/delete",
        data={"csrf_token": csrf_token},
        follow_redirects=True,
    )
    assert "ToDelete" not in delete.get_data(as_text=True)
    index = client.get("/").get_data(as_text=True)
    assert "Unassigned tasks" in index
    assert "Becomes unassigned" in index
    detail = client.get(f"/tasks/{task_id}/edit")
    assert detail.status_code == 200


def test_task_edit_form_preselects_project(client, csrf_token, make_project, make_task):
    project = make_project(client, csrf_token, name="Preselect Proj")
    project_id = project.get_json()["project"]["id"]
    task = make_task(client, csrf_token, title="In a project", project_id=project_id)
    task_id = task.get_json()["task"]["id"]

    body = client.get(f"/tasks/{task_id}/edit").get_data(as_text=True)
    needle = f'<option value="{project_id}" selected>'
    assert needle in body

    new_form = client.get("/tasks/new?project_id=%d" % project_id).get_data(
        as_text=True
    )
    assert needle in new_form
