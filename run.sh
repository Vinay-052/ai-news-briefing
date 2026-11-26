#!/usr/bin/env bash
# Start the dashboard and scheduler, or run an unattended briefing.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"
PYTHON="$DIR/venv/bin/python"

case "${1:-serve}" in
    headless)
        shift
        exec "$PYTHON" "$DIR/brief.py" "$@" >> "$DIR/brief.log" 2>&1
        ;;
    --dry-run|--weekly|--event|--event=*)
        exec "$PYTHON" "$DIR/brief.py" "$@" >> "$DIR/brief.log" 2>&1
        ;;
    --help|-h)
        cat <<'HELP'
Usage: ./run.sh                         Start the dashboard and scheduler
       ./run.sh --port 9000             Start the dashboard on another port
       ./run.sh headless [options]      Run a briefing (logs to brief.log)
       ./run.sh worker                  Run only the scheduler continuously
       ./run.sh tick                    Queue and process due events once

Headless options: --dry-run, --weekly, --event ID
HELP
        ;;
    *)
        exec "$PYTHON" "$DIR/webapp.py" "$@"
        ;;
esac
