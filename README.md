# pi-server

HTTP server on the Raspberry Pi. Receives messages from iOS Shortcuts and external integrations, routes them to Claude, and returns responses.

## Overview

**pi-server** is the main HTTP interface to Claude on the Pi. It receives incoming messages, optionally injects conversation history for context, and streams or returns Claude's response.

Runs on port 8765 and integrates with [claude-runner](https://github.com/JJGantt/claude-runner) for core execution logic.

## Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/message` | POST | Send a message to Claude |
| `/status` | GET | Health check |

## Request/Response

**Request:**
```json
{
  "text": "what's the weather?",
  "source": "ios-shortcut"
}
```

**Response:**
```json
{
  "response": "The weather is..."
}
```

## Architecture

- `app.py` — Flask app entry point
- Uses [claude-runner](https://github.com/JJGantt/claude-runner) for execution
- Integrates with [mcp-history](https://github.com/JJGantt/mcp-history) for context injection
- All exchanges logged to shared history via mcp-history

## Service

Runs as a systemd service:

```bash
systemctl status pi-server
systemctl start/stop/restart pi-server
```

Logs to `/home/jaredgantt/pi-server/server.log`

## Configuration

Paths and settings are in [claude-runner/config.json](https://github.com/JJGantt/claude-runner). No hardcoded values.

## Related

- **Executor:** [claude-runner](https://github.com/JJGantt/claude-runner) — Core Claude CLI logic
- **Bot:** [telegram-bot](https://github.com/JJGantt/telegram-bot) — Telegram interface
- **History:** [mcp-history](https://github.com/JJGantt/mcp-history) — Conversation logging & context
