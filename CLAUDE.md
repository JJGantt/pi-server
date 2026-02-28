# pi-server

HTTP server on the Raspberry Pi for iOS Shortcuts and other local integrations.
Runs on port 8765.

## Service
- `pi-server.service`

Restart: `sudo systemctl restart pi-server.service`
Logs: `tail -f /home/jaredgantt/pi-server/server.log`

## Endpoints
- `POST /message` — receive text, run Claude, return response
- `POST /log` — log a conversation exchange to history (used by Mac stop hook)
- `GET  /status` — health check

## Files
- `pi_server.py` — main Flask app
- `runner.py` — Claude CLI runner (shared with telegram-bot — keep in sync if modified)
- `codex_runner.py` — Codex variant (shared with telegram-bot — keep in sync)
- `route_state.py` — routing state between claude/codex (shared with telegram-bot — keep in sync)
- `sync_to_mac.sh` — push data to Mac
- `sync_from_mac.sh` — pull data from Mac
- `sync_to_mac_watch.sh` — watches for changes and auto-syncs to Mac (used by pi-to-mac-sync.service)

## Shared code note
`runner.py`, `codex_runner.py`, `route_state.py` are duplicated in `telegram-bot/`. If you modify one, update the other.

## Data
History → `/home/jaredgantt/data/history/`
