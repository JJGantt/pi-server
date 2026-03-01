#!/usr/bin/env python3
"""
Lightweight HTTP server on the Pi.
Receives messages from iOS Shortcuts, passes them to Claude, returns the response.
Runs on port 8765.

Note: /log and /status endpoints are handled by mcp-history receiver on port 8766.

All exchanges are saved to /home/jaredgantt/data/history/YYYY-MM-DD.json via
runner.py, which also injects the last 24 hours of history as context
so Claude has continuity across sessions and message sources (Telegram + HTTP).
"""

import logging
import sys
from datetime import datetime
from pathlib import Path
from flask import Flask, request, jsonify

sys.path.insert(0, "/home/jaredgantt/claude-runner")
from runner import run_claude
from codex_runner import run_codex
from route_state import get_mode, set_mode, apply_switch_and_strip

app = Flask(__name__)
LOG_FILE = Path("/home/jaredgantt/pi-server/server.log")

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(),
    ]
)
log = logging.getLogger(__name__)


@app.route("/message", methods=["POST"])
def receive_message():
    data = request.get_json(silent=True) or {}
    text = (data.get("text", "") or "").strip()
    if not text:
        return jsonify({"error": "no text"}), 400
    log.info(f"Shortcut message: {text}")
    # Optional source override (e.g. from ambient voice system)
    source = (data.get("source", "") or "").strip()

    try:
        if source:
            # Direct source — skip mode routing (used by ambient system)
            response = run_claude(text, source)
            return jsonify({"ok": True, "mode": "claude", "response": response}), 200

        cleaned, new_mode, _new_model = apply_switch_and_strip(text)
        if new_mode:
            set_mode(new_mode)
        mode = get_mode()

        if not cleaned and new_mode:
            response = f"Switched default to {mode}."
        else:
            if mode == "codex":
                response = run_codex(cleaned, "codex-http")
            else:
                response = run_claude(cleaned, "claude-http")
        return jsonify({"ok": True, "mode": mode, "response": response}), 200
    except Exception as e:
        log.error(f"Error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500






if __name__ == "__main__":
    log.info("Starting Pi HTTP server on port 8765...")
    app.run(host="0.0.0.0", port=8765, threaded=True)
