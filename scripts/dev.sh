#!/usr/bin/env bash
# KcpInsights local launcher (macOS / Linux).
# Starts the FastAPI backend (127.0.0.1:8000) and the Next.js frontend (localhost:3000).
# First run: creates backend/.venv, installs dependencies, migrates the SQLite database
# and loads the synthetic demo fixture. No API keys or AI model are required.
#
#   scripts/dev.sh            start everything
#   KCP_SKIP_DEMO=1 scripts/dev.sh   do not load the synthetic demo on an empty database
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
API_PORT="${KCP_API_PORT:-8000}"
WEB_PORT="${KCP_WEB_PORT:-3000}"

red() { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
info() { printf '\033[36m==>\033[0m %s\n' "$*"; }
fail() { red "ERROR: $*"; exit 1; }

# ---- prerequisites ---------------------------------------------------------------
PY="${PYTHON:-}"
if [[ -z "$PY" ]]; then
  for c in python3.13 python3.12 python3.11 python3; do
    if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
  done
fi
[[ -n "$PY" ]] || fail "Python 3.11+ is required (https://www.python.org/downloads/)."
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' || fail "Python 3.11+ is required; found $("$PY" --version)."
command -v node >/dev/null 2>&1 || fail "Node.js 20+ is required (https://nodejs.org)."
node -e 'process.exit(parseInt(process.versions.node) >= 20 ? 0 : 1)' || fail "Node.js 20+ is required; found $(node --version)."
command -v npm >/dev/null 2>&1 || fail "npm is required."

port_busy() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null && exec 3>&- ; }
port_busy "$API_PORT" && fail "Port $API_PORT is already in use (set KCP_API_PORT or stop the other process)."
port_busy "$WEB_PORT" && fail "Port $WEB_PORT is already in use (set KCP_WEB_PORT or stop the other process)."

# ---- backend setup ---------------------------------------------------------------
cd "$BACKEND"
if [[ ! -x .venv/bin/python ]]; then
  info "Creating Python virtual environment (backend/.venv)"
  "$PY" -m venv .venv
fi
STAMP=".venv/.requirements.sha"
REQ_HASH="$(cat requirements.txt requirements-dev.txt | shasum | cut -d' ' -f1)"
if [[ ! -f "$STAMP" || "$(cat "$STAMP")" != "$REQ_HASH" ]]; then
  info "Installing backend dependencies"
  .venv/bin/python -m pip install -q --upgrade pip
  .venv/bin/python -m pip install -q -r requirements-dev.txt || fail "pip install failed — see output above."
  echo "$REQ_HASH" > "$STAMP"
fi
[[ -f .env ]] || { cp .env.example .env; info "Created backend/.env from .env.example"; }

info "Applying database migrations"
.venv/bin/python -m app.cli migrate >/dev/null || fail "Database migration failed. Run: cd backend && .venv/bin/python -m app.cli migrate"

if [[ "${KCP_SKIP_DEMO:-0}" != "1" ]]; then
  COUNT="$(.venv/bin/python - <<'PY'
from sqlalchemy import func, select
from app.db import SessionLocal
from app.models import IPOIssue
print(SessionLocal().execute(select(func.count(IPOIssue.id))).scalar_one())
PY
)"
  if [[ "$COUNT" == "0" ]]; then
    info "Empty database: loading the SYNTHETIC demonstration fixture (fictional companies)"
    .venv/bin/python -m app.cli seed-demo >/dev/null || fail "Demo seed failed."
  fi
fi

# ---- frontend setup --------------------------------------------------------------
cd "$FRONTEND"
if [[ ! -d node_modules || package-lock.json -nt node_modules/.package-lock.json ]]; then
  info "Installing frontend dependencies"
  npm install --no-audit --no-fund || fail "npm install failed — see output above."
fi

# ---- run -------------------------------------------------------------------------
PIDS=()
cleanup() {
  info "Stopping…"
  for p in "${PIDS[@]:-}"; do kill "$p" 2>/dev/null || true; done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

info "Starting API on http://127.0.0.1:$API_PORT"
(cd "$BACKEND" && exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT" --reload --reload-dir app) &
PIDS+=($!)

for i in $(seq 1 40); do
  if curl -fsS "http://127.0.0.1:$API_PORT/api/health" >/dev/null 2>&1; then break; fi
  kill -0 "${PIDS[0]}" 2>/dev/null || fail "Backend exited during startup — see the log above."
  sleep 0.5
  [[ $i == 40 ]] && fail "Backend did not become healthy on port $API_PORT."
done
green "API healthy  → http://127.0.0.1:$API_PORT/api/docs"

if curl -fsS -m 2 "http://127.0.0.1:11434/api/tags" >/dev/null 2>&1; then
  green "Ollama detected — the research agent will use it if the configured model is downloaded."
else
  info "Ollama not running — the research agent uses the deterministic engine (see README to enable local AI)."
fi

info "Starting web app on http://localhost:$WEB_PORT"
(cd "$FRONTEND" && KCP_API_URL="http://127.0.0.1:$API_PORT" exec npx next dev --port "$WEB_PORT") &
PIDS+=($!)

green "KcpInsights is starting → http://localhost:$WEB_PORT  (Ctrl+C to stop)"
# portable "wait for the first child to exit" (macOS ships bash 3.2 without `wait -n`)
while kill -0 "${PIDS[0]}" 2>/dev/null && kill -0 "${PIDS[1]}" 2>/dev/null; do sleep 1; done
red "A process exited; shutting down."
