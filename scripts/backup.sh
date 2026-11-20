#!/usr/bin/env bash
# Daily SQLite backup for Zhiyu.
# Cron: 0 3 * * * /srv/zhiyu/app/scripts/backup.sh >> /var/log/zhiyu-backup.log 2>&1
#
# Never copy the .sqlite3 file directly while the service is running: in WAL mode
# a plain cp can miss the latest transaction or capture a torn page. Use .backup.
set -euo pipefail

DB="${ZHIYU_DB:-/srv/zhiyu/var/zhiyu.sqlite3}"
OUT="${ZHIYU_BACKUP_DIR:-/srv/zhiyu/backup}"
KEEP_DAYS="${ZHIYU_BACKUP_KEEP:-14}"

command -v sqlite3 >/dev/null 2>&1 || { echo "sqlite3 not installed" >&2; exit 1; }
[ -f "$DB" ] || { echo "database not found: $DB" >&2; exit 1; }

mkdir -p "$OUT"
stamp="$(date +%F-%H%M)"
target="$OUT/zhiyu-$stamp.sqlite3"
partial="$OUT/.zhiyu-$stamp.sqlite3.part"

# The sqlite3 CLI is a native binary; on Git Bash for Windows it needs a
# Windows-style path. On Linux cygpath does not exist and the path passes through.
winpath() {
  if command -v cygpath >/dev/null 2>&1; then cygpath -w "$1"; else printf '%s' "$1"; fi
}

sqlite3 "$(winpath "$DB")" ".timeout 5000" ".backup '$(winpath "$partial")'"

check="$(sqlite3 "$(winpath "$partial")" 'PRAGMA integrity_check;')"
if [ "$check" != "ok" ]; then
  rm -f "$partial"
  echo "integrity check failed: $check" >&2
  exit 1
fi

mv "$partial" "$target"
find "$OUT" -name 'zhiyu-*.sqlite3' -type f -mtime "+$KEEP_DAYS" -delete

echo "backup ok: $target"
