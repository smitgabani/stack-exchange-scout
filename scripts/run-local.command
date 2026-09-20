#!/usr/bin/env bash
#
# Double-click this in Finder (or run it from a terminal) to work on
# Stack Exchange Scout entirely on your own machine, without the Vercel
# frontend at all.
#
# What it does:
#   1. Starts the existing Next.js dev server in frontend/ on a free port.
#      That server already proxies /api/* to the deployed Fly backend
#      (see frontend/next.config.ts + frontend/.env.local's BACKEND_URL) --
#      nothing about the backend changes here, only where the UI is served
#      from. This isn't a stopgap for while Vercel is down: it works the
#      same way whether Vercel is up, paused, or gone entirely.
#   2. Opens your default browser to it once it actually responds.
#   3. When you close this window, or press Ctrl-C, it kills the dev
#      server and everything it spawned, and deletes the temporary log
#      it wrote while running. Nothing is left behind afterwards: no PID
#      file, no log file, no background process still listening.
#
# Does not touch git, Fly, or Vercel -- it only runs code that already
# exists in frontend/.
#
# Usage:
#   ./run-local.command          # picks a free port near 4300
#   ./run-local.command 5050     # starts looking for a free port at 5050

set -euo pipefail

# Resolve paths relative to this script rather than the caller's cwd, since
# a Finder double-click starts with an unpredictable working directory.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$SCRIPT_DIR/../frontend"

if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
    echo "frontend/node_modules is missing. Run 'npm install' inside frontend/ once, then try again." >&2
    exit 1
fi

# Everything this run writes lives here and nowhere else, so cleanup is one
# rm -rf rather than a list of files that has to be kept in sync by hand.
WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/scout-local.XXXXXX")"
LOG_FILE="$WORK_DIR/dev-server.log"

DEFAULT_PORT=4300
REQUESTED_PORT="${1:-$DEFAULT_PORT}"

SERVER_PID=""

cleanup() {
    local exit_code=$?
    # The negative PID targets the whole process group `set -m` put the
    # server job in below. Killing only $SERVER_PID would stop npm's wrapper
    # process and leave the actual `next dev` server it spawned running --
    # which is exactly the "trace left behind" this script exists to avoid.
    if [[ -n "$SERVER_PID" ]] && kill -0 "$SERVER_PID" 2>/dev/null; then
        kill -TERM "-$SERVER_PID" 2>/dev/null || true
        wait "$SERVER_PID" 2>/dev/null || true
    fi
    rm -rf "$WORK_DIR"
    exit "$exit_code"
}
trap cleanup EXIT INT TERM HUP

# Finds a free port at or after $1. Checked with lsof rather than trying to
# bind and see what happens, so a stuck-but-not-actually-listening state
# can't leave this script waiting on a port nothing will ever answer on.
find_free_port() {
    local candidate="$1"
    for _ in $(seq 1 20); do
        if ! lsof -iTCP:"$candidate" -sTCP:LISTEN >/dev/null 2>&1; then
            echo "$candidate"
            return 0
        fi
        candidate=$((candidate + 1))
    done
    return 1
}

PORT="$(find_free_port "$REQUESTED_PORT")" || {
    echo "No free port found near $REQUESTED_PORT. Try: ./run-local.command <a different port>" >&2
    exit 1
}

echo "Starting the local app on port $PORT..."

# `set -m` gives the background job its own process group. Without it, the
# negative-PID kill in cleanup() has nothing group-level to target, and
# `next dev`'s actual server process -- npm's child, not $SERVER_PID itself
# -- would survive Ctrl-C.
set -m
(cd "$FRONTEND_DIR" && exec npm run dev -- --port "$PORT") >"$LOG_FILE" 2>&1 &
SERVER_PID=$!
set +m

URL="http://localhost:$PORT"

# Polled rather than slept for a fixed duration: a cold Next.js compile
# takes a few seconds, and there's no fixed number that's always enough and
# never just wasted time.
ready=0
for _ in $(seq 1 60); do
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        # Next.js refuses a second dev instance for the same project
        # *directory*, regardless of port -- it binds, notices another
        # instance already owns this project, and shuts itself back down.
        # That is not a failure to report, it is the common case: you
        # already have a manual `npm run dev` open. Attach to that one
        # instead of erroring, and -- critically -- do not adopt it as
        # something this script owns, so closing this window never kills
        # a session it did not start.
        if grep -q "Another next dev server is already running" "$LOG_FILE"; then
            EXISTING_URL="$(grep -Eo 'http://localhost:[0-9]+' "$LOG_FILE" | tail -n1)"
            if [[ -n "$EXISTING_URL" ]]; then
                echo "A dev server for this project is already running at $EXISTING_URL."
                echo "Opening that instead. Closing this window will not stop it -- this script did not start it."
                SERVER_PID=""
                open "$EXISTING_URL" || echo "Could not open a browser automatically -- visit $EXISTING_URL yourself." >&2
                exit 0
            fi
        fi
        echo "The dev server exited before it started answering. Its log:" >&2
        cat "$LOG_FILE" >&2
        exit 1
    fi
    if curl -s -o /dev/null "$URL"; then
        ready=1
        break
    fi
    sleep 0.5
done

if [[ "$ready" -ne 1 ]]; then
    echo "Timed out waiting for $URL to respond. Its log:" >&2
    cat "$LOG_FILE" >&2
    exit 1
fi

open "$URL" || echo "Could not open a browser automatically -- visit $URL yourself." >&2

echo "Running at $URL -- press Ctrl-C, or close this window, to stop."
wait "$SERVER_PID"
