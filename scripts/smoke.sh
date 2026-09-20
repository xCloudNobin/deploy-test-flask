#!/usr/bin/env bash
# Reproducible production smoke test.
#
# Starts the REAL production process (gunicorn), exercises HTTP CRUD and
# negative tests against it, restarts it on the same SQLite database to
# prove persistence, verifies dependency-failure readiness, then cleans up.
#
# Usage:
#   scripts/smoke.sh            # expects ./.venv (installs deps if missing)
#   VENV=/path scripts/smoke.sh # custom venv, created if missing
#
# Exit codes: 0 = all checks passed, nonzero = a check failed.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${VENV:-$ROOT/.venv}"
PY="$VENV/bin/python"

WORK="$(mktemp -d /tmp/taskboard-smoke.XXXXXX)"
PIDFILE="$WORK/server.pid"
JAR="$WORK/cookies.txt"
LOG1="$WORK/server1.log"
LOG2="$WORK/server2.log"
LOG3="$WORK/server-fail.log"
DB="$WORK/tasks.db"

cleanup() {
  local pid
  pid="$(cat "$PIDFILE" 2>/dev/null || true)"
  if [ -n "$pid" ]; then
    kill "$pid" 2>/dev/null || true
    sleep 0.2
    kill -9 "$pid" 2>/dev/null || true
  fi
  rm -rf "$WORK"
}
trap cleanup EXIT

PASS=0
FAIL=0

ok()   { PASS=$((PASS + 1)); printf 'ok   %s\n' "$*"; }
bad()  { FAIL=$((FAIL + 1)); printf 'FAIL %s\n' "$*"; }

expect_status() { # label url expected method data...
  local label="$1" url="$2" expected="$3" method="$4"
  shift 4
  local code hdr extra
  code=$(curl -s -o /dev/null -w '%{http_code}' -b "$JAR" -c "$JAR" \
    -X "$method" "$@" "$url" || true)
  if [ "$code" = "$expected" ]; then
    ok "$label ($code)"
  else
    bad "$label: expected $expected got $code"
  fi
}

pick_port() {
  "$PY" - <<'EOF'
import socket
s = socket.socket()
s.bind(("127.0.0.1", 0))
print(s.getsockname()[1])
s.close()
EOF
}

start_server() { # db_path pidfile logfile
  local db_path="$1" pidfile="$2" logfile="$3"
  local port
  port="$(pick_port)"
  DATABASE_PATH="$db_path" PORT="$port" BUILD_MARKER="smoke-$port" \
    "$VENV/bin/gunicorn" --chdir "$ROOT" -c gunicorn.conf.py app:app \
    --daemon -p "$pidfile" --access-logfile "$logfile" \
    --error-logfile "$logfile"
  echo "$port"
}

wait_ready_http() { # port label logfile
  local port="$1" label="$2" logfile="${3:-}"
  local code=000
  for _ in $(seq 1 40); do
    code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$port/health" || true)
    [ "$code" = "200" ] && { ok "liveness HTTP 200 ($label)"; return 0; }
    sleep 0.3
  done
  bad "server did not answer /health (last code $code, $label)"
  [ -n "$logfile" ] && [ -f "$logfile" ] && tail -5 "$logfile" || true
  return 1
}

stop_server() {
  local pid
  pid="$(cat "$PIDFILE" 2>/dev/null || true)"
  if [ -n "$pid" ]; then
    kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 20); do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.2
    done
    kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$PIDFILE"
}

fetch_token() { # port -> echoes csrf token and updates cookie jar
  local port="$1"
  curl -s -b "$JAR" -c "$JAR" "http://127.0.0.1:$port/tasks/new" \
    | grep -o 'name="csrf_token" value="[^"]*"' \
    | sed 's/.*value="//; s/"$//' \
    | head -1 || true
}

# ---------------------------------------------------------------- bootstrap
if [ ! -x "$VENV/bin/python" ]; then
  echo "creating venv at $VENV"
  python3 -m venv "$VENV"
fi
echo "installing/refreshing dependencies"
"$PY" -m pip install --quiet -r "$ROOT/requirements-dev.txt"

printf '=== smoke start: %s ===\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# ------------------------------------------------------- run 1 (create path)
echo "--- phase 1: production start + CRUD + negatives (fresh DB)"
PORT1="$(start_server "$DB" "$PIDFILE" "$LOG1")"
wait_ready_http "$PORT1" "phase-1"

BODY="$(curl -s -b "$JAR" -c "$JAR" "http://127.0.0.1:$PORT1/ready")"
case "$BODY" in
  *'"status": "ready"'*|*'"status":"ready"'*) ok "readiness reports ready";;
  *) bad "readiness payload: $BODY";;
esac

TOKEN="$(fetch_token "$PORT1")"
[ -n "$TOKEN" ] && ok "csrf token acquired" || bad "csrf token missing"

index="$(curl -s -b "$JAR" "http://127.0.0.1:$PORT1/")"
case "$index" in
  *"smoke-$PORT1"*) ok "build marker rendered on index";;
  *) bad "build marker missing on index";;
esac

# HTML create project
resp=$(curl -s -o /dev/null -w '%{http_code} %{redirect_url}' -b "$JAR" -c "$JAR" \
  -X POST "http://127.0.0.1:$PORT1/projects/new" \
  --data-urlencode "name=Smoke Project" \
  --data-urlencode "description=created over HTTP" \
  --data-urlencode "csrf_token=$TOKEN")
case "$resp" in
  302*) ok "HTML create project ($resp)";;
  *) bad "HTML create project: $resp";;
esac
PROJECT_URL="${resp#302 }"
PROJECT_ID="$(basename "$PROJECT_URL")"

# HTML create task in project
resp=$(curl -s -o /dev/null -w '%{http_code}' -b "$JAR" -c "$JAR" \
  -X POST "http://127.0.0.1:$PORT1/tasks/new" \
  --data-urlencode "title=Smoke Task" \
  --data-urlencode "description=over http" \
  --data-urlencode "status=todo" \
  --data-urlencode "project_id=$PROJECT_ID" \
  --data-urlencode "csrf_token=$TOKEN")
[ "$resp" = "302" ] && ok "HTML create task (302)" || bad "HTML create task: $resp"

# read back on project detail
detail="$(curl -s "$PROJECT_URL")"
case "$detail" in
  *"Smoke Task"*) ok "read: task listed on project page";;
  *) bad "task not listed on project page";;
esac

# HTML edit task
TASK_ID=$(curl -s "$PROJECT_URL" \
  | grep -o '/tasks/[0-9]\+/edit' | head -1 | sed 's#/tasks/##; s#/edit##' || true)
[ -n "$TASK_ID" ] && ok "discovered task id $TASK_ID" || bad "task id not found"
resp=$(curl -s -o /dev/null -w '%{http_code}' -b "$JAR" -c "$JAR" \
  -X POST "http://127.0.0.1:$PORT1/tasks/$TASK_ID/edit" \
  --data-urlencode "title=Smoke Task (updated)" \
  --data-urlencode "description=" \
  --data-urlencode "status=in_progress" \
  --data-urlencode "project_id=$PROJECT_ID" \
  --data-urlencode "csrf_token=$TOKEN")
[ "$resp" = "302" ] && ok "HTML update task (302)" || bad "HTML update task: $resp"

# HTML status change
resp=$(curl -s -o /dev/null -w '%{http_code}' -b "$JAR" -c "$JAR" \
  -X POST "http://127.0.0.1:$PORT1/tasks/$TASK_ID/status" \
  --data-urlencode "status=done" --data-urlencode "csrf_token=$TOKEN")
[ "$resp" = "302" ] && ok "HTML status change (302)" || bad "HTML status change: $resp"

# HTML delete task
resp=$(curl -s -o /dev/null -w '%{http_code}' -b "$JAR" -c "$JAR" \
  -X POST "http://127.0.0.1:$PORT1/tasks/$TASK_ID/delete" \
  --data-urlencode "csrf_token=$TOKEN")
[ "$resp" = "302" ] && ok "HTML delete task (302)" || bad "HTML delete task: $resp"

# ----------------------------------------------- persistence survivor (API)
created=$(curl -s -b "$JAR" -c "$JAR" -X POST \
  -H "Content-Type: application/json" -H "Accept: application/json" \
  -d "{\"title\": \"PERSIST-$$-survivor\", \"status\": \"in_progress\", \"csrf_token\": \"$TOKEN\"}" \
  "http://127.0.0.1:$PORT1/api/tasks")
SURVIVOR_ID=$(printf '%s' "$created" | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["task"]["id"])')
[ -n "$SURVIVOR_ID" ] && ok "API create task (survivor id=$SURVIVOR_ID)" || bad "API create returned no id"

# API read/search
list=$(curl -s -H "Accept: application/json" "http://127.0.0.1:$PORT1/api/tasks?q=survivor")
case "$list" in
  *"PERSIST-$$-survivor"*) ok "API read/search finds survivor";;
  *) bad "API search missing survivor";;
esac

# API update
upd=$(curl -s -b "$JAR" -c "$JAR" -X PATCH \
  -H "Content-Type: application/json" -H "Accept: application/json" \
  -d "{\"status\": \"done\", \"csrf_token\": \"$TOKEN\"}" \
  "http://127.0.0.1:$PORT1/api/tasks/$SURVIVOR_ID")
case "$upd" in
  *'"status":"done"'*|*'"status": "done"'*) ok "API update task (status=done)";;
  *) bad "API update failed: $upd";;
esac

# API delete (of a throwaway) + 404 after
throw=$(curl -s -b "$JAR" -c "$JAR" -X POST \
  -H "Content-Type: application/json" -H "Accept: application/json" \
  -d "{\"title\": \"throwaway\", \"csrf_token\": \"$TOKEN\"}" \
  "http://127.0.0.1:$PORT1/api/tasks")
THROW_ID=$(printf '%s' "$throw" | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["task"]["id"])')
expect_status "API delete task (204 expected)" "http://127.0.0.1:$PORT1/api/tasks/$THROW_ID" 204 DELETE \
  -H "Content-Type: application/json" -d "{\"csrf_token\": \"$TOKEN\"}"
expect_status "API 404 after delete" "http://127.0.0.1:$PORT1/api/tasks/$THROW_ID" 404 GET

# ------------------------------------------------------------- negatives
# malformed JSON (token supplied via header so the JSON parser is the limb under test)
expect_status "malformed JSON -> 400" "http://127.0.0.1:$PORT1/api/tasks" 400 POST \
  -H "Content-Type: application/json" -H "X-CSRF-Token: $TOKEN" -d "{not json"
# missing title
expect_status "missing title -> 400" "http://127.0.0.1:$PORT1/api/tasks" 400 POST \
  -H "Content-Type: application/json" -d "{\"csrf_token\": \"$TOKEN\"}"
# invalid status
expect_status "invalid status -> 400" "http://127.0.0.1:$PORT1/api/tasks" 400 POST \
  -H "Content-Type: application/json" -d "{\"title\":\"x\",\"status\":\"warp\",\"csrf_token\": \"$TOKEN\"}"
# missing csrf token
expect_status "missing CSRF -> 400" "http://127.0.0.1:$PORT1/api/tasks" 400 POST \
  -H "Content-Type: application/json" -d "{\"title\":\"x\"}"
# unknown task
expect_status "unknown task -> 404" "http://127.0.0.1:$PORT1/api/tasks/999999" 404 GET
# invalid status filter
expect_status "invalid status filter -> 400" "http://127.0.0.1:$PORT1/api/tasks?status=nope" 400 GET
# HTML invalid status
expect_status "HTML invalid status -> 400" "http://127.0.0.1:$PORT1/tasks/new" 400 POST \
  --data-urlencode "title=x" --data-urlencode "status=bogus" --data-urlencode "csrf_token=$TOKEN"
# HTML csrf missing
expect_status "HTML missing CSRF -> 400" "http://127.0.0.1:$PORT1/tasks/new" 400 POST \
  --data-urlencode "title=x"
# malformed JSON error body sanity
errbody="$(curl -s -b "$JAR" -X POST -H "Content-Type: application/json" \
  -H "Accept: application/json" -H "X-CSRF-Token: $TOKEN" -d '{oops' \
  "http://127.0.0.1:$PORT1/api/tasks")"
case "$errbody" in
  *"Malformed"*"JSON"*) ok "malformed JSON error body sane";;
  *) bad "unexpected error body: $errbody";;
esac

echo "--- phase 2: graceful stop, restart on same SQLite path"
stop_server
sleep 0.3
echo "--- phase 3: restart persistence check"
PORT2="$(start_server "$DB" "$PIDFILE" "$LOG2")"
wait_ready_http "$PORT2" "phase-3"
found=$(curl -s -H "Accept: application/json" \
  "http://127.0.0.1:$PORT2/api/tasks/$SURVIVOR_ID")
case "$found" in
  *"PERSIST-$$-survivor"*) ok "persistence: survivor task survived restart";;
  *) bad "persistence FAILED: survivor missing after restart";;
esac
seed=$(curl -s -H "Accept: application/json" "http://127.0.0.1:$PORT2/api/tasks")
seed_count=$(printf '%s' "$seed" | "$PY" -c 'import json,sys; d=json.load(sys.stdin); print(len(d["tasks"]))')
case "$seed_count" in
  5) ok "idempotent schema init: no duplicated seed (5 tasks)";;
  *) bad "seed duplicated or lost: task count=$seed_count";;
esac
stop_server

echo "--- phase 4: dependency failure (database unavailable)"
DBDIR3="$(mktemp -d /tmp/taskboard-smoke-fail.XXXXXX)"
PORT3="$(start_server "$DBDIR3" "$PIDFILE" "$LOG3")"
wait_ready_http "$PORT3" "phase-4"
expect_status "liveness /health still 200" "http://127.0.0.1:$PORT3/health" 200 GET
expect_status "readiness fails -> 503" "http://127.0.0.1:$PORT3/ready" 503 GET
expect_status "page routes degrade -> 503" "http://127.0.0.1:$PORT3/" 503 GET
stop_server
rm -rf "$DBDIR3"

echo
printf '=== smoke summary: %s passed, %s failed ===\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]