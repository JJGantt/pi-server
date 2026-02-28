#!/usr/bin/env python3
"""
Shared message runner for all pipelines (Telegram bot, HTTP server, etc.).

HISTORY SYSTEM
==============
Every exchange is saved to a per-day JSON file:
    /home/jaredgantt/data/history/YYYY-MM-DD.json

Each entry contains:
    - user/claude: the raw user message and final response text
    - source: where it came from (claude-telegram, codex-telegram,
              claude-http, codex-http, claude-mac, codex-mac,
              claude-pi, codex-pi, system-error)
    - trace: full JSON conversation trace (tool calls, results, thinking, cost)
    - has_tool_use: boolean flag for quick filtering

CONTEXT INJECTION
=================
When a new message arrives, history from the same channel is injected so the
model sees the same conversation the user sees.

Channel mapping:
    claude-telegram, codex-telegram  →  "telegram" channel
    claude-http, codex-http          →  "http" channel

Mac and Pi interactive sessions have their own built-in context and are logged
to history only for the shared record — they are never injected.

Time gaps of 30+ minutes get a visual separator so the model understands
they may be distinct topics.
"""

import json
import os
import subprocess
import logging
import fcntl
from datetime import datetime, timedelta
from pathlib import Path

HISTORY_DIR = Path("/home/jaredgantt/data/history")
HISTORY_DIR.mkdir(parents=True, exist_ok=True)

log = logging.getLogger(__name__)

# Map each source to its channel for context filtering.
# Sources in the same channel share injected context.
_SOURCE_TO_CHANNEL = {
    # Specialized Telegram bots — each isolated to their own history
    "sonnet-telegram":  "sonnet-telegram",
    "opus-telegram":    "opus-telegram",
    "haiku-telegram":   "haiku-telegram",
    "codex-telegram":   "codex-telegram",
    # General Pi bot — stored in own channel, receives ALL context (see _ALL_CONTEXT_SOURCES)
    "pi-telegram":      "pi-telegram",
    # HTTP
    "claude-http":      "http",
    "codex-http":       "http",
    # Mac (Pi interactive SSH sessions merged into Mac channel)
    "claude-mac":       "mac",
    "codex-mac":        "mac",
    "claude-pi":        "mac",
    "codex-pi":         "mac",
    # Voice
    "claude-voice":     "voice",
    # Ambient (wake-word-free voice)
    "claude-ambient":   "ambient",
    # Legacy names (for old history entries still in the 24h window)
    "claude-telegram":  "telegram",
    "telegram":         "telegram",
    "http":             "http",
    "laptop":           "mac",
    "interactive":      "pi",
}

# Sources that receive full cross-channel context (not filtered to their own channel)
_ALL_CONTEXT_SOURCES = {"pi-telegram"}

# Minimum gap (seconds) between entries before inserting a time separator
_GAP_THRESHOLD_SECS = 30 * 60  # 30 minutes


# ---------------------------------------------------------------------------
# History I/O
# ---------------------------------------------------------------------------

def _day_file(date: datetime) -> Path:
    return HISTORY_DIR / f"{date.strftime('%Y-%m-%d')}.json"


def _load_day(date: datetime) -> list:
    f = _day_file(date)
    if not f.exists():
        return []
    try:
        return json.loads(f.read_text())
    except Exception:
        return []


def _save_day(date: datetime, entries: list):
    target = _day_file(date)
    tmp = target.with_suffix(target.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(entries, indent=2))
    tmp.replace(target)


def _day_lock_file(date: datetime) -> Path:
    return HISTORY_DIR / f"{date.strftime('%Y-%m-%d')}.lock"


def append_history_entry(date: datetime, entry: dict) -> None:
    """Append one entry using a per-day file lock to avoid lost updates."""
    lock_file = _day_lock_file(date)
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    lock_file.touch(exist_ok=True)

    with lock_file.open("r") as lock_fp:
        fcntl.flock(lock_fp, fcntl.LOCK_EX)
        entries = _load_day(date)
        entries.append(entry)
        _save_day(date, entries)
        fcntl.flock(lock_fp, fcntl.LOCK_UN)


def append_exchange(source: str, user_msg: str, claude_response: str,
                    trace: list | None = None, has_tool_use: bool = False):
    """Append a single exchange to today's history file."""
    now = datetime.now()
    entry = {
        "timestamp": now.isoformat(timespec="seconds"),
        "source": source,
        "user": user_msg,
        "claude": claude_response,
        "has_tool_use": has_tool_use,
    }
    if trace is not None:
        entry["trace"] = trace
    append_history_entry(now, entry)


def load_history_range(start: datetime, end: datetime) -> list:
    """
    Return all exchanges between start and end (inclusive by day).
    Efficient — only opens files for days in the range.
    """
    results = []
    day = start.replace(hour=0, minute=0, second=0, microsecond=0)
    end_day = end.replace(hour=0, minute=0, second=0, microsecond=0)
    while day <= end_day:
        for entry in _load_day(day):
            ts = datetime.fromisoformat(entry["timestamp"]).replace(tzinfo=None)
            if start <= ts <= end:
                results.append(entry)
        day += timedelta(days=1)
    results.sort(key=lambda e: e.get("timestamp", ""))
    return results


def load_recent_context(hours: int = 24, channel: str | None = None) -> list:
    """Return exchanges from the last N hours for context injection.

    Args:
        hours:   How far back to look.
        channel: If set, only return entries whose source belongs to this
                 channel (e.g. "telegram" returns telegram + codex-telegram).
                 If None, returns all real sources (legacy behaviour).
    """
    now = datetime.now()
    raw = load_history_range(now - timedelta(hours=hours), now)
    cleaned = []
    for entry in raw:
        src = entry.get("source", "")
        entry_channel = _SOURCE_TO_CHANNEL.get(src)

        # Skip system-error and unrecognised sources
        if entry_channel is None:
            continue

        # Channel filter
        if channel is not None and entry_channel != channel:
            continue

        # Skip entries where the "user" field is actually a meta-prompt
        # (old prompt format leaked "-\nRecent conversation..." into user field)
        user = entry.get("user", "").lstrip(" -\n")
        if user.startswith("Recent conversation history") or \
           user.startswith("A previous Claude subprocess") or \
           user.startswith("The Codex CLI subprocess") or \
           user.startswith("You are responding to"):
            continue

        cleaned.append(entry)
    return cleaned


def _source_channel(source: str) -> str | None:
    """Return the channel for a given source, or None."""
    ch = _SOURCE_TO_CHANNEL.get(source)
    if ch is not None:
        return ch
    # Handle dynamic prefixes (e.g. claude-ambient-mac -> ambient)
    if source.startswith("claude-ambient-"):
        return "ambient"
    return None


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------

def _format_gap(seconds: int) -> str:
    """Human-readable time gap string."""
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} minutes"
    hours = minutes // 60
    remaining = minutes % 60
    if remaining == 0:
        return f"{hours} hour{'s' if hours != 1 else ''}"
    return f"{hours}h {remaining}m"


_CONTEXT_FRAMING = """\
You are responding to a message from Jared sent via a headless pipeline \
(Telegram or HTTP) on a Raspberry Pi. The conversation below is recent \
context from this channel.

Treat this as the active thread:
- If Jared references earlier messages, resolve that from this context first.
- Do not claim you lack memory when relevant details are present below.
- Use external history tools only when this context is insufficient.

Use it for continuity but do not reference this framing — respond naturally \
as if continuing a normal conversation.

---
Previous conversation (oldest -> newest):\
"""


def _build_system_context(context: list) -> str | None:
    """Build system prompt context string from recent history. Returns None if empty."""
    if not context:
        return None

    MAX_CONTEXT_CHARS = 12000  # larger recent-thread window for continuity

    # Ensure stable chronological ordering even if history was appended out of order.
    context = sorted(context, key=lambda e: e.get("timestamp", ""))

    # Keep the most recent entries under the size budget.
    selected_reversed = []
    total = 0
    for entry in reversed(context):
        ts = datetime.fromisoformat(entry["timestamp"])
        ts_str = ts.strftime("%Y-%m-%d %H:%M")
        user = entry["user"][:450]
        claude = entry["claude"][:450]
        block = f"[{ts_str}] Jared: {user}\n[{ts_str}] Response: {claude}"
        if total + len(block) > MAX_CONTEXT_CHARS and selected_reversed:
            break
        selected_reversed.append(entry)
        total += len(block)

    selected = list(reversed(selected_reversed))

    # Format chronologically so gap markers appear between the correct turns.
    context_lines = []
    prev_ts = None
    for entry in selected:
        ts = datetime.fromisoformat(entry["timestamp"])
        ts_str = ts.strftime("%Y-%m-%d %H:%M")
        user = entry["user"][:450]
        claude = entry["claude"][:450]
        if prev_ts is not None:
            gap_secs = (ts - prev_ts).total_seconds()
            if gap_secs >= _GAP_THRESHOLD_SECS:
                context_lines.append(f"\n--- {_format_gap(int(gap_secs))} later ---\n")
        context_lines.append(f"[{ts_str}] Jared: {user}\n[{ts_str}] Response: {claude}")
        prev_ts = ts

    parts = [_CONTEXT_FRAMING]
    parts.extend(context_lines)
    parts.append("---")
    return "\n".join(parts)


def _build_prompt(message: str, context: list) -> str:
    """Legacy: combined prompt string. New callers use _build_system_context."""
    system_ctx = _build_system_context(context)
    if not system_ctx:
        return message
    return system_ctx + "\n\nJared's message: " + message


def build_prompt(message: str, context: list) -> str:
    """Public wrapper for consistent prompt formatting across runners."""
    return _build_prompt(message, context)


# ---------------------------------------------------------------------------
# Trace parsing helpers
# ---------------------------------------------------------------------------

def _parse_trace(raw_json: str) -> tuple[str, list, bool]:
    """
    Parse the JSON output from `claude -p --output-format json`.
    Returns (response_text, trace, has_tool_use).
    """
    try:
        data = json.loads(raw_json)
    except (json.JSONDecodeError, TypeError):
        return raw_json.strip(), [], False

    # Single-object format (no --verbose)
    if isinstance(data, dict):
        return data.get("result", raw_json.strip()), [], False

    # Array format (--verbose): list of message objects
    if isinstance(data, list):
        response = ""
        has_tool_use = False
        trace = []
        for item in data:
            typ = item.get("type", "")
            if typ == "result":
                response = item.get("result", "")
            elif typ == "assistant":
                content = item.get("content", [])
                if isinstance(content, list):
                    for block in content:
                        if block.get("type") == "tool_use":
                            has_tool_use = True
                trace.append(item)
            elif typ == "user":
                trace.append(item)
        return response, trace, has_tool_use

    return raw_json.strip(), [], False



# ---------------------------------------------------------------------------
# Claude invocation
# ---------------------------------------------------------------------------

def run_claude(message: str, source: str = "unknown", model: str = "sonnet") -> str:
    """
    Run claude -p with recent history as context, save the exchange, return response.

    Args:
        message: The user's message.
        source:  Where it came from — "claude-telegram", "claude-http", etc.
        model:   Claude model — "sonnet", "opus", "haiku".
    """
    channel = _source_channel(source)
    if source in _ALL_CONTEXT_SOURCES:
        context = load_recent_context(hours=24, channel=None)
    else:
        context = load_recent_context(hours=24, channel=channel)
    system_ctx = _build_system_context(context)

    log.info(f"Running claude (source={source}, channel={channel}, model={model}, context_entries={len(context)})")

    env = os.environ.copy()
    env["CLAUDE_SOURCE"] = source

    try:
        cmd = ["claude", "-p", "--dangerously-skip-permissions", "--model", model,
               "--output-format", "json", "--verbose", "-"]
        if system_ctx:
            cmd = ["claude", "-p", "--dangerously-skip-permissions", "--model", model,
                   "--append-system-prompt", system_ctx,
                   "--output-format", "json", "--verbose", "-"]
        result = subprocess.run(
            cmd,
            input=message,
            capture_output=True,
            text=True,
            timeout=300,
            cwd="/home/jaredgantt",
            env=env,
        )
        raw = (result.stdout or "").strip()
        if result.returncode != 0 and not raw:
            stderr = (result.stderr or "").strip()
            log.error(f"Claude subprocess failed (rc={result.returncode}): {stderr}")
            # Ask Claude what went wrong rather than returning a generic error
            error_context = f"A previous Claude subprocess just failed with exit code {result.returncode}."
            if stderr:
                error_context += f" The stderr output was:\n{stderr[:2000]}"
            error_context += f"\n\nThe original user message was: {message}\n\nBriefly explain what went wrong and what the user can do."
            try:
                err_result = subprocess.run(
                    ["claude", "-p", "--dangerously-skip-permissions"],
                    input=error_context,
                    capture_output=True,
                    text=True,
                    timeout=60,
                    cwd="/home/jaredgantt",
                    env=env,
                )
                response = (err_result.stdout or "").strip() or stderr or "Something went wrong."
            except Exception:
                response = stderr or "Something went wrong."
            # Log as system-error so it doesn't pollute future context
            append_exchange("system-error", message, response)
            return response

        response, trace, has_tool_use = _parse_trace(raw)
        response = response or "(No response)"
    except subprocess.TimeoutExpired:
        response = "Timed out processing that request."
        trace = []
        has_tool_use = False
        log.error("Claude timed out")

    append_exchange(source, message, response, trace=trace, has_tool_use=has_tool_use)
    return response
