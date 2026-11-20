#!/usr/bin/env bash
# ZHIYU_DB, ZHIYU_BACKUP_DIR and ZHIYU_BACKUP_KEEP are read by dbops.py.
set -euo pipefail
exec "${PYTHON:-python3}" "$(dirname "$0")/dbops.py" backup
