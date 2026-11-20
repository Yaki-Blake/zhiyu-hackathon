#!/usr/bin/env bash
# Restore rehearsal: start an isolated instance from a backup and compare counts.
# Usage: scripts/restore-check.sh /srv/zhiyu/backup/zhiyu-2026-11-28-0300.sqlite3 [port]
set -euo pipefail

BACKUP="${1:?usage: restore-check.sh <backup.sqlite3> [port]}"
PORT="${2:-4199}"
PYTHON="${PYTHON:-python3}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

[ -f "$BACKUP" ] || { echo "backup not found: $BACKUP" >&2; exit 1; }
command -v sqlite3 >/dev/null 2>&1 || { echo "sqlite3 not installed" >&2; exit 1; }

WORK="$(mktemp -d)"
PID=""
cleanup() {
  if [ -n "$PID" ]; then kill "$PID" 2>/dev/null || true; fi
  rm -rf "$WORK" 2>/dev/null || true
}
trap cleanup EXIT

winpath() {
  if command -v cygpath >/dev/null 2>&1; then cygpath -w "$1"; else printf '%s' "$1"; fi
}

cp "$BACKUP" "$WORK/restore.sqlite3"
RESTORED="$(winpath "$WORK/restore.sqlite3")"
ZHIYU_DB="$RESTORED" "$PYTHON" "$ROOT/server.py" --port "$PORT" >"$WORK/server.log" 2>&1 &
PID=$!

ready=0
for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 0.3
done
[ "$ready" = "1" ] || { echo "restored instance did not start" >&2; cat "$WORK/server.log" >&2; exit 1; }

echo "health: $(curl -fsS "http://127.0.0.1:$PORT/api/health")"
echo "projects: $(sqlite3 "$RESTORED" 'select count(*) from projects;')"
echo "cards:    $(sqlite3 "$RESTORED" 'select count(*) from cards;')"
echo "feedback: $(sqlite3 "$RESTORED" 'select count(*) from feedback;')"
echo "restore rehearsal ok"
