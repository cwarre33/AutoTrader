"""AutoTrader Dashboard — Web UI for monitoring and controlling the trading bot."""

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

BASE_DIR = Path(__file__).parent
DECISIONS_LOG = BASE_DIR / "workspace" / "logs" / "decisions.jsonl"
TRADES_CSV = BASE_DIR / "logs" / "trades.csv"
SESSIONS_DIR = BASE_DIR / "openclaw-config" / "agents" / "main" / "sessions"
CRON_RUNS_DIR = BASE_DIR / "openclaw-config" / "cron" / "runs"
GATEWAY_CONTAINER = "autotrader-gateway"


@app.route("/")
def index():
    return render_template("dashboard.html")


@app.route("/api/decisions")
def api_decisions():
    """Return recent trading decisions from decisions.jsonl."""
    decisions = []
    if DECISIONS_LOG.exists():
        lines = DECISIONS_LOG.read_text(encoding="utf-8").strip().splitlines()
        for line in reversed(lines[-100:]):
            try:
                decisions.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return jsonify(decisions)


@app.route("/api/cycles")
def api_cycles():
    """Return recent heartbeat/cron cycle results from session files."""
    cycles = []

    # Read session files
    if SESSIONS_DIR.exists():
        for f in sorted(SESSIONS_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:5]:
            entries = []
            for line in f.read_text(encoding="utf-8").strip().splitlines():
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

            session_id = f.stem
            messages = [e for e in entries if e.get("type") == "message"]
            for msg in messages:
                m = msg.get("message", {})
                role = m.get("role")
                content_parts = m.get("content", [])
                text = ""
                thinking = ""
                if isinstance(content_parts, list):
                    for part in content_parts:
                        if isinstance(part, dict):
                            if part.get("type") == "text":
                                text += part.get("text", "")
                            elif part.get("type") == "thinking":
                                thinking += part.get("thinking", "")
                elif isinstance(content_parts, str):
                    text = content_parts

                cycles.append({
                    "session_id": session_id,
                    "timestamp": msg.get("timestamp"),
                    "role": role,
                    "text": text[:2000],
                    "thinking": thinking[:1000],
                    "model": m.get("model", ""),
                    "stop_reason": m.get("stopReason", ""),
                    "error": m.get("errorMessage", ""),
                    "usage": m.get("usage", {}),
                })

    # Sort by timestamp descending
    cycles.sort(key=lambda c: c.get("timestamp", ""), reverse=True)
    return jsonify(cycles[:50])


@app.route("/api/cron-runs")
def api_cron_runs():
    """Return cron execution history."""
    runs = []
    if CRON_RUNS_DIR.exists():
        for f in sorted(CRON_RUNS_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:10]:
            for line in f.read_text(encoding="utf-8").strip().splitlines():
                try:
                    entry = json.loads(line)
                    runs.append(entry)
                except json.JSONDecodeError:
                    pass
    runs.sort(key=lambda r: r.get("timestamp", r.get("ts", "")), reverse=True)
    return jsonify(runs[:50])


@app.route("/api/account")
def api_account():
    """Get current account info from Alpaca."""
    try:
        result = subprocess.run(
            ["docker", "exec", GATEWAY_CONTAINER, "python3",
             "/home/node/.openclaw/workspace/tools/alpaca_tool.py", "account"],
            capture_output=True, text=True, timeout=15,
            env={**os.environ, "MSYS_NO_PATHCONV": "1"},
        )
        if result.returncode == 0:
            return jsonify(json.loads(result.stdout))
        return jsonify({"error": result.stderr}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/positions")
def api_positions():
    """Get current positions from Alpaca."""
    try:
        result = subprocess.run(
            ["docker", "exec", GATEWAY_CONTAINER, "python3",
             "/home/node/.openclaw/workspace/tools/alpaca_tool.py", "positions"],
            capture_output=True, text=True, timeout=15,
            env={**os.environ, "MSYS_NO_PATHCONV": "1"},
        )
        if result.returncode == 0:
            return jsonify(json.loads(result.stdout))
        return jsonify({"error": result.stderr}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/chat", methods=["POST"])
def api_chat():
    """Send a message to the OpenClaw agent and return the response."""
    data = request.get_json()
    message = data.get("message", "").strip()
    if not message:
        return jsonify({"error": "Empty message"}), 400

    try:
        result = subprocess.run(
            ["docker", "exec", GATEWAY_CONTAINER, "node", "dist/index.js",
             "agent", "--agent", "main", "--message", message],
            capture_output=True, text=True, timeout=120,
            env={**os.environ, "MSYS_NO_PATHCONV": "1"},
        )

        # After sending, read the latest session to get the response
        time.sleep(2)
        response_text = _get_latest_assistant_response()
        return jsonify({
            "response": response_text or "Message sent. Check cycles tab for response.",
            "stdout": result.stdout[:500] if result.stdout else "",
            "stderr": result.stderr[:500] if result.stderr else "",
        })
    except subprocess.TimeoutExpired:
        return jsonify({"response": "Message sent (async). Check cycles tab for response."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/health")
def api_health():
    """Trading pipeline health: Alpaca connectivity."""
    try:
        result = subprocess.run(
            ["docker", "exec", GATEWAY_CONTAINER, "python", "/home/node/.openclaw/workspace/tools/alpaca_tool.py", "account"],
            capture_output=True, text=True, timeout=15,
            env={**os.environ, "MSYS_NO_PATHCONV": "1"},
        )
        if result.returncode != 0:
            return jsonify({"alpaca": "error", "message": (result.stderr or result.stdout or "non-zero exit")[:500]}), 503
        data = json.loads(result.stdout)
        if "equity" not in data:
            return jsonify({"alpaca": "error", "message": "invalid response"}), 503
        return jsonify({"alpaca": "ok", "equity": data.get("equity")})
    except subprocess.TimeoutExpired:
        return jsonify({"alpaca": "error", "message": "timeout"}), 503
    except Exception as e:
        return jsonify({"alpaca": "error", "message": str(e)}), 503


@app.route("/api/status")
def api_status():
    """Get bot status: gateway running, cron jobs, last heartbeat."""
    status = {"gateway": False, "cron_jobs": [], "last_heartbeat": None}

    # Check gateway
    try:
        result = subprocess.run(
            ["docker", "ps", "--filter", f"name={GATEWAY_CONTAINER}", "--format", "{{.Status}}"],
            capture_output=True, text=True, timeout=5,
        )
        status["gateway"] = "Up" in result.stdout
        status["gateway_status"] = result.stdout.strip()
    except Exception:
        pass

    # Check cron
    try:
        result = subprocess.run(
            ["docker", "exec", GATEWAY_CONTAINER, "node", "dist/index.js", "cron", "list"],
            capture_output=True, text=True, timeout=10,
            env={**os.environ, "MSYS_NO_PATHCONV": "1"},
        )
        status["cron_output"] = result.stdout.strip()
    except Exception:
        pass

    # Last heartbeat session
    if SESSIONS_DIR.exists():
        sessions = sorted(SESSIONS_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        if sessions:
            status["last_session_file"] = sessions[0].name
            status["last_session_time"] = datetime.fromtimestamp(
                sessions[0].stat().st_mtime, tz=timezone.utc
            ).isoformat()

    return jsonify(status)


def _get_latest_assistant_response():
    """Read the latest assistant response from session files."""
    if not SESSIONS_DIR.exists():
        return None
    sessions = sorted(SESSIONS_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not sessions:
        return None

    lines = sessions[0].read_text(encoding="utf-8").strip().splitlines()
    for line in reversed(lines):
        try:
            entry = json.loads(line)
            if entry.get("type") == "message":
                msg = entry.get("message", {})
                if msg.get("role") == "assistant":
                    content = msg.get("content", [])
                    if isinstance(content, list):
                        texts = [p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"]
                        return " ".join(texts)
                    elif isinstance(content, str):
                        return content
        except json.JSONDecodeError:
            pass
    return None


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=True)
