# Task Board (Flask)

A compact project/task board built with Flask: project grouping, task CRUD,
statuses, search/filter, a small JSON API, and real SQLite persistence.
Designed as a production-shaped Flask deployment test with proper health,
readiness, validation, and reproducible automated checks.

## Features

- **Projects and tasks** — create, read, update, delete; tasks are grouped under
  projects (deleting a project leaves its tasks as *unassigned*).
- **Statuses** — `todo`, `in_progress`, `done` via inline dropdown (client-side
  autosubmit with a no-JS fallback) or the edit form.
- **Search / filter** — free-text match on title/description plus a status
  filter, on the board and per-project pages.
- **SQLite persistence** — deterministic, idempotent schema (`schema.sql`) with
  repeatable seed data; parameterized queries and Jinja autoescaping
  everywhere; CSRF tokens on all state-changing requests.
- **Health vs readiness** — `/health` is a pure liveness probe; `/ready`
  performs a real `SELECT 1` against the database and returns `503` when the
  database is unavailable while the process stays alive.
- **JSON API** — `/api/tasks` and `/api/projects` for scripting and the smoke
  test, with malformed-JSON, validation, and not-found handling.
- **Build marker** — non-sensitive `VERSION`/`BUILD_MARKER` rendered in the
  footer to identify the deployed revision.

## Requirements

- Python 3.11+
- SQLite (bundled with CPython via the `sqlite3` stdlib module)

## Install (repo-local virtualenv)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt   # runtime + pytest
```

## Configure

Copy `.env.example` and adjust, or export variables in the process
environment. All values are optional; the safe local defaults are shown:

| Variable          | Default            | Purpose                                                       |
| ----------------- | ------------------ | ------------------------------------------------------------- |
| `PORT`            | `8000`             | Listen port                                                   |
| `HOST`            | `0.0.0.0`          | Bind address (required by platforms; do not change)           |
| `DATABASE_PATH`   | `./data/tasks.db`  | Persistent SQLite file                                        |
| `DATABASE_TIMEOUT`| `5`                | Lock timeout in seconds                                       |
| `SECRET_KEY`      | random at boot     | Session/CSRF signing key                                      |
| `BUILD_MARKER`    | `VERSION` file     | Non-sensitive revision marker shown in the UI                 |

> **Persistence is the operator's job.** The default `./data/tasks.db` lives
> inside the release checkout and is wiped on redeploy. In production always
> set `DATABASE_PATH` to a path **outside** the checkout (a mounted volume),
> e.g. `/var/lib/taskboard/tasks.db`. Generate `SECRET_KEY` once with
> `python -c "import secrets; print(secrets.token_hex(24))"` and keep it
> stable so sessions/CSRF tokens survive restarts.

## Run

Development server (local debugging only — not production):

```bash
.venv/bin/python app.py            # FLASK_DEBUG=1 to enable the reloader
```

Production WSGI process (gunicorn, logs to stdout/stderr):

```bash
DATABASE_PATH=/var/lib/taskboard/tasks.db \
SECRET_KEY="$(cat secret.txt)" \
PORT=8000 \
.venv/bin/gunicorn --chdir . -c gunicorn.conf.py app:app
```

The module-level `app = create_app()` in `app.py` is the WSGI entry point
(also exposed as `app:app`). `gunicorn.conf.py` preloads the app so all
workers share one `SECRET_KEY`, binds `HOST:PORT`, and caps workers to the
host's CPU count. Worker/thread counts: `WEB_CONCURRENCY` (default 2) and
`WEB_THREADS` (default 4). Gunicorn handles SIGTERM as a graceful shutdown;
`graceful_timeout` is 15s.

Set or regenerate the build marker before shipping:

```bash
scripts/build.sh                 # writes VERSION (git SHA or BUILD_MARKER)
```

## Schema and seed behavior

`schema.sql` is applied idempotently on first database access
(`CREATE TABLE IF NOT EXISTS`). Seed data (two projects, four tasks) is
inserted **only when the tasks table is empty**, with fixed values, so
re-initialization never duplicates and databases are reproducible. To refresh
from scratch, stop the app and delete the database file (not automatic).

## Endpoints

HTML:

- `GET /` — board: projects with grouped tasks, `?q=` and `?status=` filters
- `GET /projects/<id>` — project detail (nested route) with the same filters
- `GET/POST /projects/new`, `GET/POST /projects/<id>/edit`,
  `POST /projects/<id>/delete`
- `GET/POST /tasks/new`, `GET/POST /tasks/<id>/edit`, `POST /tasks/<id>/status`,
  `POST /tasks/<id>/delete`

JSON API (CSRF token required in the JSON body or `X-CSRF-Token` header):

- `GET /api/tasks?q=&status=`, `POST /api/tasks`, `GET/PATCH/DELETE /api/tasks/<id>`
- `GET /api/projects`, `POST /api/projects`

Health:

- `GET /health` — `{"status":"ok","app":"deploy-test-flask"}` (liveness)
- `GET /ready` — `{"status":"ready","database":"ok"}` or `503` with the error
  detail when the database is unavailable (readiness)

Invalid input returns `400` with field-level `errors`; unknown resources return
`404`; an unavailable database returns `503` while `/health` stays green. Error
responses are HTML for browsers and JSON for `/api/*` paths.

## Public demo limitations

This app has **no authentication** — it is a single-board collaborative demo.
All visitors can create/edit/delete everything; do not put private data on a
public deployment. CSRF tokens are tied to the per-visitor session cookie but
are not a substitute for login. A public demo should also use a persistent
`DATABASE_PATH` volume or expect all data to reset on redeploy.

## Tests and smoke

```bash
.venv/bin/python -m pytest -q        # unit/integration suite (34 tests)
scripts/smoke.sh                     # real-production HTTP smoke + persistence
```

`scripts/smoke.sh` starts the **production gunicorn process** on a temporary
port with an isolated temporary SQLite database, then:

1. exercises HTML and JSON create/read/update/delete and search/filter,
2. runs negative tests (malformed JSON, missing title, invalid status, missing
   CSRF token, missing resources, invalid filters),
3. restarts the server on the **same database path** and proves a record
   survives before cleanup,
4. starts a second instance whose `DATABASE_PATH` is invalid and verifies
   `/health` stays `200` while `/ready` (and pages) fail with `503`,
5. removes the temporary database and port.

No simulated output: every check is a real HTTP request against the running
production process. Build markers, ports, and database paths are ephemeral and
isolated per run.

## License

MIT — see [`LICENSE`](LICENSE). Original upstream notice retained; this is an
extension of the existing `deploy-test-flask` work.