# Verification

Verification of the Flask task-board implementation on the
`xCloudNobin/deploy-test-flask` repository. This records what was actually
run locally; **no live xCloud deployment was performed**.

- Date (UTC): 2026-09-20
- Repository: `xCloudNobin/deploy-test-flask` (source owner verified, public)
- Branch: `feat/compatibility-taskboard`
- Head commit: see git log; commit SHA captured in the PR
- Status: **local-verified** (NOT **deployment-verified**)

## Environment (local only)

| Component | Version |
| --------- | ------- |
| Python    | 3.11.15 (repo-local `.venv`) |
| Flask     | 3.1.3 |
| Werkzeug  | 3.1.8 |
| gunicorn  | 23.0.0 |
| pytest    | 8.4.2 |
| SQLite    | 3.53.1 (stdlib `sqlite3`) |
| Process   | real gunicorn WSGI (bind `127.0.0.1:<random-port>` for tests) |

No `apt`, no global interpreter changes; dependencies installed only inside the
repo-local `.venv`. Each test/smoke run used an isolated temporary SQLite
database and unique ephemeral ports, cleaned up afterwards.

## Commands and results

### Unit/integration test suite

```bash
.venv/bin/python -m pytest -q
```

Result: `34 passed in 1.20s` (exit 0).

Coverage includes: health/liveness, readiness success and failure (unavailable
database), homepage grouping + seed rendering, build marker, nested routes and
static assets, HTML output escaping, project/task CRUD via forms and JSON API,
search/status filters, validation errors (missing title/name, invalid status,
unknown project), malformed JSON, missing/invalid CSRF token, not-found (404),
unavailable-database degradation (503), deterministic and idempotent schema
with non-duplicated seed, and data persistence across a full app restart.

### Production process smoke test

```bash
scripts/smoke.sh
```

Result: `32 passed, 0 failed` (exit 0). The script starts the real
`gunicorn` production process (not the dev server) and verifies:

- Liveness `/health` → `200`; readiness `/ready` → `200` on a healthy DB.
- HTML create project → `302`; create task → `302`; read on project page;
  edit task; change status; delete task.
- JSON API create/read/search/update/delete, delete-then-404.
- Negative tests: malformed JSON → `400`; missing title → `400`; invalid
  status → `400`; missing CSRF token → `400`; unknown task → `404`; invalid
  status filter → `400`; HTML invalid status and missing CSRF → `400`.
- Build marker (`BUILD_MARKER=smoke-<port>`) rendered on `/`.
- **Persistence:** process gracefully stopped (SIGTERM), restarted on the
  **same SQLite path**, survivor record still present, seed not duplicated
  (idempotent init).
- **Dependency failure:** second instance started with an unusable
  `DATABASE_PATH`; liveness stuck at `200`, readiness and pages → `503`.
- Full cleanup of temporary database, logs, and ports.

### Build marker

```bash
scripts/build.sh          # writes VERSION; also overridable via BUILD_MARKER
```

Validated: script emits the git short SHA and the UI renders the marker.

## Notes / limitations

- **Live xCloud deployment NOT run.** The platform category deployment and
  external checks still need to be executed at the exact candidate commit
  before this can be marked `deployment-verified`.
- App has **no authentication** (demo scope, per brief); public demo must not
  hold private data and should mount a persistent `DATABASE_PATH` volume.
- `SECRET_KEY` default is randomly generated at process boot; gunicorn is
  preloaded so all workers share the key. Production is documented to pin it.
- Logs go to stdout/stderr (gunicorn access/error logs) without credentials.

No repository settings, collaborators, or other repositories were modified.