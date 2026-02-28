#!/bin/bash
# Watch Pi data for changes and push to the Mac.

WATCH_DIR="/home/jaredgantt/data"
SYNC_CMD="/home/jaredgantt/scripts/sync_to_mac.sh"

if ! command -v inotifywait >/dev/null 2>&1; then
  exit 1
fi

inotifywait -m -r -e close_write,create,move,delete --format '%w%f' "$WATCH_DIR" | while read -r _; do
  "$SYNC_CMD"
  sleep 2
done
