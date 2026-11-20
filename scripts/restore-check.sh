#!/usr/bin/env bash
# Supply a backup file and, optionally, a specific unused loopback port.
set -euo pipefail
exec "${PYTHON:-python3}" "$(dirname "$0")/dbops.py" restore "$@"
