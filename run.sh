#!/usr/bin/env bash
# Cron entrypoint. Uses the local venv and logs to brief.log next to the script.
#
# This is a BASH script — run it as `./run.sh` or `bash run.sh`.
# `python3 run.sh` will fail with a SyntaxError.
#
#   ./run.sh              build the briefing and email it
#   ./run.sh --dry-run    build only; writes last_briefing.html, sends nothing
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"
exec "$DIR/venv/bin/python" "$DIR/brief.py" "$@" >> "$DIR/brief.log" 2>&1
