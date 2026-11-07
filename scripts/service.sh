#!/usr/bin/env bash
# Run KcpInsights unattended on macOS: two launch agents that start at login and restart if they exit.
#   com.kcpinsights.api  FastAPI + the ingestion scheduler (data refresh, document reading, backups, health checks)
#   com.kcpinsights.web  production Next.js server (built once by `install`)
# Logs: ~/Library/Logs/KcpInsights/. Stop scripts/dev.sh first: both use ports 8000 and 3000.
#
#   scripts/service.sh install     build the web app, write and load the launch agents
#   scripts/service.sh status      show whether they run and the latest health problems
#   scripts/service.sh uninstall   unload and remove the launch agents (data is kept)
#
# Linux: use the systemd units printed by `scripts/service.sh systemd` (see docs/DEPLOYMENT.md).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
API_PORT="${KCP_API_PORT:-8000}"
WEB_PORT="${KCP_WEB_PORT:-3000}"
AGENTS="$HOME/Library/LaunchAgents"
LOGS="$HOME/Library/Logs/KcpInsights"
LABELS=(com.kcpinsights.api com.kcpinsights.web)

info() { printf '\033[36m==>\033[0m %s\n' "$*"; }
fail() { printf '\033[31mERROR: %s\033[0m\n' "$*"; exit 1; }

plist() {  # label, working directory, program arguments...
  local label="$1" wd="$2"; shift 2
  printf '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
  printf '<plist version="1.0"><dict>\n  <key>Label</key><string>%s</string>\n  <key>WorkingDirectory</key><string>%s</string>\n' "$label" "$wd"
  printf '  <key>ProgramArguments</key><array>\n'
  for a in "$@"; do printf '    <string>%s</string>\n' "$a"; done
  printf '  </array>\n  <key>EnvironmentVariables</key><dict>\n'
  printf '    <key>PATH</key><string>%s</string>\n    <key>KCP_API_URL</key><string>http://127.0.0.1:%s</string>\n' "$PATH" "$API_PORT"
  printf '  </dict>\n  <key>RunAtLoad</key><true/>\n  <key>KeepAlive</key><true/>\n  <key>ThrottleInterval</key><integer>30</integer>\n'
  printf '  <key>StandardOutPath</key><string>%s/%s.log</string>\n  <key>StandardErrorPath</key><string>%s/%s.log</string>\n' "$LOGS" "$label" "$LOGS" "$label"
  printf '</dict></plist>\n'
}

case "${1:-}" in
  install)
    [[ "$(uname)" == "Darwin" ]] || fail "launch agents are macOS only; on Linux run: scripts/service.sh systemd"
    [[ -x "$BACKEND/.venv/bin/python" ]] || fail "run scripts/dev.sh once first (it creates backend/.venv and installs dependencies)"
    command -v npx >/dev/null 2>&1 || fail "Node.js/npm is required"
    info "Applying database migrations"
    (cd "$BACKEND" && .venv/bin/python -m app.cli migrate)
    info "Building the web app (production)"
    (cd "$FRONTEND" && npm run build)
    mkdir -p "$AGENTS" "$LOGS"
    plist com.kcpinsights.api "$BACKEND" "$BACKEND/.venv/bin/python" -m uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT" \
      > "$AGENTS/com.kcpinsights.api.plist"
    plist com.kcpinsights.web "$FRONTEND" "$(command -v npx)" next start --port "$WEB_PORT" > "$AGENTS/com.kcpinsights.web.plist"
    for l in "${LABELS[@]}"; do
      launchctl bootout "gui/$(id -u)/$l" 2>/dev/null || true
      launchctl bootstrap "gui/$(id -u)" "$AGENTS/$l.plist"
    done
    info "Installed. Web: http://localhost:$WEB_PORT  API: http://127.0.0.1:$API_PORT  Logs: $LOGS"
    ;;
  uninstall)
    for l in "${LABELS[@]}"; do
      launchctl bootout "gui/$(id -u)/$l" 2>/dev/null || true
      rm -f "$AGENTS/$l.plist"
    done
    info "Removed the launch agents; the database, documents and backups in backend/data are kept."
    ;;
  status)
    for l in "${LABELS[@]}"; do
      if launchctl print "gui/$(id -u)/$l" >/dev/null 2>&1; then echo "$l: loaded"; else echo "$l: not installed"; fi
    done
    (cd "$BACKEND" && .venv/bin/python -m app.cli health) || true
    ;;
  systemd)
    cat <<UNITS
# /etc/systemd/system/kcpinsights-api.service
[Unit]
Description=KcpInsights API and ingestion scheduler
After=network-online.target
[Service]
WorkingDirectory=$BACKEND
ExecStartPre=$BACKEND/.venv/bin/python -m app.cli migrate
ExecStart=$BACKEND/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port $API_PORT
Restart=always
User=$(id -un)
[Install]
WantedBy=multi-user.target

# /etc/systemd/system/kcpinsights-web.service  (run "npm run build" in frontend/ first)
[Unit]
Description=KcpInsights web app
After=kcpinsights-api.service
[Service]
WorkingDirectory=$FRONTEND
Environment=KCP_API_URL=http://127.0.0.1:$API_PORT
ExecStart=$(command -v npx || echo /usr/bin/npx) next start --port $WEB_PORT
Restart=always
User=$(id -un)
[Install]
WantedBy=multi-user.target
UNITS
    ;;
  *)
    sed -n '2,12p' "$0"; exit 64 ;;
esac
