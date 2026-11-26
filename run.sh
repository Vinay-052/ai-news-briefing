#!/usr/bin/env bash
# Start the dashboard and scheduler, or run an unattended briefing.
#
# This is a BASH script — run it as `./run.sh` or `bash run.sh`.
#
# A bare `./run.sh` keeps working from existing cron entries: with no terminal
# attached (cron, launchd, systemd timers) it runs the headless briefing exactly
# like earlier releases did. From an interactive terminal it starts the dashboard.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"
PYTHON="$DIR/venv/bin/python"

if [[ $# -eq 0 ]]; then
    if [[ -t 0 || -t 1 ]]; then
        set -- serve
    else
        set -- headless
    fi
fi

case "$1" in
    headless)
        shift
        exec "$PYTHON" "$DIR/brief.py" "$@" >> "$DIR/brief.log" 2>&1
        ;;
    --dry-run|--weekly|--event|--event=*)
        exec "$PYTHON" "$DIR/brief.py" "$@" >> "$DIR/brief.log" 2>&1
        ;;
    --help|-h)
        cat <<'HELP'
Usage: ./run.sh                         Dashboard from a terminal; headless briefing from cron
       ./run.sh serve [--port 9000]     Always start the dashboard and scheduler
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
