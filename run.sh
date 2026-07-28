#!/usr/bin/env bash
# Cron entrypoint. Uses the local venv and logs to brief.log next to the script.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"
exec "$DIR/venv/bin/python" "$DIR/brief.py" "$@" >> "$DIR/brief.log" 2>&1
