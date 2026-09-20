"""Task board: a compact Flask application with project/task CRUD.

Production WSGI entry point is ``app`` (see ``gunicorn.conf.py``). The
backend uses SQLite through parameterized queries and renders data with
Jinja autoescaping enabled; all state-changing requests carry a CSRF
token bound to the session cookie.
"""

import hmac
import os
import secrets
import sqlite3
from pathlib import Path

from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from db import STATUSES, close_db, get_db

_BASE_DIR = Path(__file__).resolve().parent
_DEFAULT_DB_DIR = _BASE_DIR / "data"


def _build_marker():
    marker = os.environ.get("BUILD_MARKER", "").strip()
    if marker:
        return marker
    version_file = _BASE_DIR / "VERSION"
    if version_file.exists():
        return version_file.read_text(encoding="utf-8").strip()
    return "dev"


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(24),
        DATABASE_PATH=os.environ.get("DATABASE_PATH")
        or str(_DEFAULT_DB_DIR / "tasks.db"),
        DATABASE_TIMEOUT=int(os.environ.get("DATABASE_TIMEOUT", "5")),
        MAX_CONTENT_LENGTH=1_000_000,
    )
    if test_config is None and "DATABASE_PATH" not in os.environ:
        _DEFAULT_DB_DIR.mkdir(parents=True, exist_ok=True)
    if test_config:
        app.config.update(test_config)

    app.teardown_appcontext(close_db)

    @app.context_processor
    def inject_globals():
        return {
            "build_marker": _build_marker(),
            "statuses": STATUSES,
            "csrf_token": _csrf_token,
        }

    app.cli.command("init-db")(lambda: _cli_init_db(app))

    register_error_handlers(app)
    register_routes(app)
    return app


def _cli_init_db(app):
    with app.app_context():
        get_db()
        print("Database initialized at", app.config["DATABASE_PATH"])


def _csrf_token():
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(24)
        session["_csrf_token"] = token
    return token


def _validate_csrf():
    supplied = request.form.get("csrf_token")
    if not supplied:
        payload = request.get_json(silent=True)
        if isinstance(payload, dict):
            supplied = payload.get("csrf_token")
    if not supplied:
        supplied = request.headers.get("X-CSRF-Token")
    expected = session.get("_csrf_token")
    if not expected or not supplied or not hmac.compare_digest(expected, supplied):
        abort(400, description="Invalid or missing CSRF token.")


def _clean_text(value, max_length):
    if value is None:
        return ""
    return str(value).strip()[:max_length]


def _validate_project(name, description):
    errors = {}
    if not name:
        errors["name"] = "Project name is required."
    return errors


def _validate_task(title, description, status, project_id):
    errors = {}
    if not title:
        errors["title"] = "Task title is required."
    if status not in STATUSES:
        errors["status"] = "Invalid status. Allowed: todo, in_progress, done."
    if project_id:
        db = get_db()
        if (
            db.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone()
            is None
        ):
            errors["project_id"] = "Selected project does not exist."
    return errors


def _wants_json():
    if request.path.startswith("/api/"):
        return True
    return (
        request.accept_mimetypes.best_match(["text/html", "application/json"])
        == "application/json"
    )


def _task_rows(sql, params):
    db = get_db()
    return db.execute(
        "SELECT t.*, p.name AS project_name FROM tasks t"
        " LEFT JOIN projects p ON p.id = t.project_id"
        f" {sql} ORDER BY t.created_at DESC, t.id DESC",
        params,
    ).fetchall()


def _group_tasks(rows):
    by_project = {}
    unassigned = []
    for row in rows:
        if row["project_id"] is None:
            unassigned.append(row)
        else:
            by_project.setdefault(row["project_id"], []).append(row)
    return by_project, unassigned


def _status_filter():
    status = request.args.get("status", "").strip()
    return status if status in STATUSES else ""


def _search_filter():
    q = _clean_text(request.args.get("q"), 100)
    pattern = f"%{q.lower()}%"
    return q, pattern


def register_routes(app):
    @app.get("/")
    def index():
        db = get_db()
        status = _status_filter()
        q, pattern = _search_filter()
        rows = _task_rows(
            "WHERE (? = '' OR t.status = ?)"
            " AND (? = '' OR lower(t.title) LIKE ? OR lower(t.description) LIKE ?)",
            (status, status, q, pattern, pattern),
        )
        projects = db.execute(
            "SELECT p.*,"
            " (SELECT COUNT(*) FROM tasks t WHERE t.project_id = p.id) AS task_count"
            " FROM projects p ORDER BY lower(p.name)"
        ).fetchall()
        by_project, unassigned = _group_tasks(rows)
        return render_template(
            "index.html",
            projects=projects,
            by_project=by_project,
            unassigned=unassigned,
            status=status,
            q=q,
        )

    @app.get("/projects/<int:project_id>")
    def project_detail(project_id):
        db = get_db()
        project = db.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if project is None:
            abort(404)
        status = _status_filter()
        q, pattern = _search_filter()
        rows = _task_rows(
            "WHERE t.project_id = ? AND (? = '' OR t.status = ?)"
            " AND (? = '' OR lower(t.title) LIKE ? OR lower(t.description) LIKE ?)",
            (project_id, status, status, q, pattern, pattern),
        )
        return render_template(
            "project.html",
            project=project,
            tasks=rows,
            status=status,
            q=q,
        )

    @app.route("/projects/new", methods=["GET", "POST"])
    def project_new():
        if request.method == "POST":
            _validate_csrf()
            name = _clean_text(request.form.get("name"), 120)
            description = _clean_text(request.form.get("description"), 2000)
            errors = _validate_project(name, description)
            if errors:
                return render_template(
                    "project_form.html",
                    project=None,
                    name=name,
                    description=description,
                    errors=errors,
                ), 400
            db = get_db()
            cur = db.execute(
                "INSERT INTO projects (name, description) VALUES (?, ?)",
                (name, description),
            )
            db.commit()
            flash("Project created.", "success")
            return redirect(url_for("project_detail", project_id=cur.lastrowid))
        return render_template("project_form.html", project=None)

    @app.route("/projects/<int:project_id>/edit", methods=["GET", "POST"])
    def project_edit(project_id):
        db = get_db()
        project = db.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if project is None:
            abort(404)
        if request.method == "POST":
            _validate_csrf()
            name = _clean_text(request.form.get("name"), 120)
            description = _clean_text(request.form.get("description"), 2000)
            errors = _validate_project(name, description)
            if errors:
                return render_template(
                    "project_form.html",
                    project=project,
                    name=name,
                    description=description,
                    errors=errors,
                ), 400
            db.execute(
                "UPDATE projects SET name = ?, description = ? WHERE id = ?",
                (name, description, project_id),
            )
            db.commit()
            flash("Project updated.", "success")
            return redirect(url_for("project_detail", project_id=project_id))
        return render_template("project_form.html", project=project)

    @app.post("/projects/<int:project_id>/delete")
    def project_delete(project_id):
        _validate_csrf()
        db = get_db()
        project = db.execute(
            "SELECT 1 FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if project is None:
            abort(404)
        db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        db.commit()
        flash("Project deleted; its tasks are now unassigned.", "success")
        return redirect(url_for("index"))

    @app.route("/tasks/new", methods=["GET", "POST"])
    def task_new():
        db = get_db()
        if request.method == "POST":
            _validate_csrf()
            title = _clean_text(request.form.get("title"), 200)
            description = _clean_text(request.form.get("description"), 4000)
            status = request.form.get("status", "todo").strip()
            project_id = request.form.get("project_id") or None
            if project_id is not None:
                try:
                    project_id = int(project_id)
                except (TypeError, ValueError):
                    abort(400, description="Invalid project selection.")
            errors = _validate_task(title, description, status, project_id)
            if errors:
                projects = db.execute(
                    "SELECT id, name FROM projects ORDER BY lower(name)"
                ).fetchall()
                return render_template(
                    "task_form.html",
                    task=None,
                    projects=projects,
                    title=title,
                    description=description,
                    status=status,
                    selected_project_id=project_id,
                    errors=errors,
                ), 400
            cur = db.execute(
                "INSERT INTO tasks (project_id, title, description, status)"
                " VALUES (?, ?, ?, ?)",
                (project_id, title, description, status),
            )
            db.commit()
            flash("Task created.", "success")
            return redirect(url_for("index"))
        projects = db.execute(
            "SELECT id, name FROM projects ORDER BY lower(name)"
        ).fetchall()
        selected = request.args.get("project_id", type=int)
        return render_template(
            "task_form.html",
            task=None,
            projects=projects,
            selected_project_id=selected or None,
        )

    @app.route("/tasks/<int:task_id>/edit", methods=["GET", "POST"])
    def task_edit(task_id):
        db = get_db()
        task = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if task is None:
            abort(404)
        if request.method == "POST":
            _validate_csrf()
            title = _clean_text(request.form.get("title"), 200)
            description = _clean_text(request.form.get("description"), 4000)
            status = request.form.get("status", "todo").strip()
            project_id = request.form.get("project_id") or None
            if project_id is not None:
                try:
                    project_id = int(project_id)
                except (TypeError, ValueError):
                    abort(400, description="Invalid project selection.")
            errors = _validate_task(title, description, status, project_id)
            if errors:
                projects = db.execute(
                    "SELECT id, name FROM projects ORDER BY lower(name)"
                ).fetchall()
                return render_template(
                    "task_form.html",
                    task=task,
                    projects=projects,
                    title=title,
                    description=description,
                    status=status,
                    selected_project_id=project_id,
                    errors=errors,
                ), 400
            db.execute(
                "UPDATE tasks SET title = ?, description = ?, status = ?, project_id = ?,"
                " updated_at = datetime('now') WHERE id = ?",
                (title, description, status, project_id, task_id),
            )
            db.commit()
            flash("Task updated.", "success")
            return redirect(url_for("index"))
        projects = db.execute(
            "SELECT id, name FROM projects ORDER BY lower(name)"
        ).fetchall()
        return render_template(
            "task_form.html",
            task=task,
            projects=projects,
            selected_project_id=task["project_id"],
        )

    @app.post("/tasks/<int:task_id>/status")
    def task_status(task_id):
        _validate_csrf()
        status = request.form.get("status", "").strip()
        if status not in STATUSES:
            abort(400, description="Invalid status. Allowed: todo, in_progress, done.")
        db = get_db()
        cur = db.execute(
            "UPDATE tasks SET status = ?, updated_at = datetime('now') WHERE id = ?",
            (status, task_id),
        )
        db.commit()
        if cur.rowcount == 0:
            abort(404)
        flash("Task status updated.", "success")
        return redirect(request.referrer or url_for("index"))

    @app.post("/tasks/<int:task_id>/delete")
    def task_delete(task_id):
        _validate_csrf()
        db = get_db()
        cur = db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        db.commit()
        if cur.rowcount == 0:
            abort(404)
        flash("Task deleted.", "success")
        return redirect(request.referrer or url_for("index"))

    @app.get("/health")
    def health():
        return jsonify(status="ok", app="deploy-test-flask")

    @app.get("/ready")
    def ready():
        try:
            db = get_db()
            db.execute("SELECT 1").fetchone()
        except sqlite3.Error as exc:
            app.logger.warning("readiness check failed: %s", exc)
            return jsonify(status="unavailable", database="error", detail=str(exc)), 503
        return jsonify(status="ready", database="ok")

    register_api_routes(app)


def _api_payload() -> dict:
    if not request.is_json:
        abort(400, description="Request body must be JSON.")
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        abort(400, description="Malformed or non-object JSON body.")
    return data


def _task_json(row):
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "project_name": row["project_name"],
        "title": row["title"],
        "description": row["description"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _project_json(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "created_at": row["created_at"],
        "task_count": row["task_count"],
    }


def register_api_routes(app):
    @app.get("/api/tasks")
    def api_tasks_list():
        status = request.args.get("status", "").strip()
        if status and status not in STATUSES:
            abort(
                400,
                description=f"Invalid status filter. Allowed: {', '.join(STATUSES)}.",
            )
        q = _clean_text(request.args.get("q"), 100)
        pattern = f"%{q.lower()}%"
        rows = _task_rows(
            "WHERE (? = '' OR t.status = ?)"
            " AND (? = '' OR lower(t.title) LIKE ? OR lower(t.description) LIKE ?)",
            (status, status, q, pattern, pattern),
        )
        return jsonify(tasks=[_task_json(r) for r in rows])

    @app.post("/api/tasks")
    def api_tasks_create():
        _validate_csrf()
        data = _api_payload()
        title = _clean_text(data.get("title"), 200)
        description = _clean_text(data.get("description"), 4000)
        status = (data.get("status") or "todo").strip()
        project_id = None
        if data.get("project_id") is not None:
            try:
                project_id = int(data["project_id"])
            except (TypeError, ValueError):
                abort(400, description="project_id must be an integer.")
        errors = _validate_task(title, description, status, project_id)
        if errors:
            return jsonify(errors=errors), 400
        db = get_db()
        cur = db.execute(
            "INSERT INTO tasks (project_id, title, description, status)"
            " VALUES (?, ?, ?, ?)",
            (project_id, title, description, status),
        )
        db.commit()
        row = _task_rows("WHERE t.id = ?", (cur.lastrowid,))[0]
        return jsonify(task=_task_json(row)), 201

    @app.get("/api/tasks/<int:task_id>")
    def api_task_detail(task_id):
        row = _task_rows("WHERE t.id = ?", (task_id,))
        if not row:
            abort(404)
        return jsonify(task=_task_json(row[0]))

    @app.patch("/api/tasks/<int:task_id>")
    def api_task_update(task_id):
        _validate_csrf()
        data = _api_payload()
        db = get_db()
        task = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if task is None:
            abort(404)
        title = _clean_text(data.get("title", task["title"]), 200)
        description = _clean_text(data.get("description", task["description"]), 4000)
        status = (data.get("status") or task["status"]).strip()
        project_id = task["project_id"]
        if data.get("project_id") is not None:
            try:
                project_id = int(data["project_id"])
            except (TypeError, ValueError):
                abort(400, description="project_id must be an integer.")
        elif data.get("project_id") is None and "project_id" in data:
            project_id = None
        errors = _validate_task(title, description, status, project_id)
        if errors:
            return jsonify(errors=errors), 400
        db.execute(
            "UPDATE tasks SET title = ?, description = ?, status = ?, project_id = ?,"
            " updated_at = datetime('now') WHERE id = ?",
            (title, description, status, project_id, task_id),
        )
        db.commit()
        row = _task_rows("WHERE t.id = ?", (task_id,))[0]
        return jsonify(task=_task_json(row))

    @app.delete("/api/tasks/<int:task_id>")
    def api_task_delete(task_id):
        _validate_csrf()
        db = get_db()
        cur = db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        db.commit()
        if cur.rowcount == 0:
            abort(404)
        return "", 204

    @app.get("/api/projects")
    def api_projects_list():
        db = get_db()
        rows = db.execute(
            "SELECT p.*, (SELECT COUNT(*) FROM tasks t WHERE t.project_id = p.id) AS task_count"
            " FROM projects p ORDER BY lower(p.name)"
        ).fetchall()
        return jsonify(projects=[_project_json(r) for r in rows])

    @app.post("/api/projects")
    def api_projects_create():
        _validate_csrf()
        data = _api_payload()
        name = _clean_text(data.get("name"), 120)
        description = _clean_text(data.get("description"), 2000)
        errors = _validate_project(name, description)
        if errors:
            return jsonify(errors=errors), 400
        db = get_db()
        cur = db.execute(
            "INSERT INTO projects (name, description) VALUES (?, ?)",
            (name, description),
        )
        db.commit()
        row = db.execute(
            "SELECT p.*, (SELECT COUNT(*) FROM tasks t WHERE t.project_id = p.id) AS task_count"
            " FROM projects p WHERE p.id = ?",
            (cur.lastrowid,),
        ).fetchone()
        return jsonify(project=_project_json(row)), 201


def register_error_handlers(app):
    @app.errorhandler(sqlite3.OperationalError)
    def database_unavailable(exc):
        app.logger.error("database unavailable: %s", exc)
        message = {
            "status": "unavailable",
            "error": "Database is unavailable. Check the persistent database path.",
            "detail": str(exc),
        }
        status = 503
        return (
            (jsonify(message), status)
            if _wants_json()
            else (
                render_template(
                    "error.html",
                    code=status,
                    title="Service Unavailable",
                    message=message["error"],
                ),
                status,
            )
        )

    @app.errorhandler(400)
    def bad_request(exc):
        message = {
            "error": "Bad request",
            "detail": exc.description or "Invalid input.",
        }
        return (
            (jsonify(message), 400)
            if _wants_json()
            else (
                render_template(
                    "error.html",
                    code=400,
                    title="Bad Request",
                    message=message["detail"],
                ),
                400,
            )
        )

    @app.errorhandler(404)
    def not_found(exc):
        message = {
            "error": "Not found",
            "detail": "The requested resource does not exist.",
        }
        return (
            (jsonify(message), 404)
            if _wants_json()
            else (
                render_template(
                    "error.html", code=404, title="Not Found", message=message["detail"]
                ),
                404,
            )
        )

    @app.errorhandler(413)
    def too_large(exc):
        return jsonify(error="Payload too large."), 413


app = create_app()

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        debug=os.environ.get("FLASK_DEBUG") == "1",
    )
