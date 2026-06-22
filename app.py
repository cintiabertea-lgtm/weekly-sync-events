"""
Weekly Sync — Events Team
=========================
A small hosted web app where the team inputs topics for the weekly sync,
and the forecast (from daily_tasks.py) + extra notes get assembled for
Monday's meeting.

Run locally:
    pip install -r requirements.txt
    python app.py
    -> open http://localhost:5000

The app organizes everything by "week" (Monday-based, in CET).
"""

import os
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, date

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
    TZ = ZoneInfo("Europe/Berlin")  # Central European (CET/CEST)
except Exception:  # pragma: no cover
    TZ = None

from flask import Flask, g, jsonify, render_template, request

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("WEEKLY_SYNC_DB", os.path.join(BASE_DIR, "weekly_sync.db"))
PRIORITY_ORDER = {"High": 0, "Medium": 1, "Low": 2, "": 3}

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Week helpers (Monday-based, CET)
# ---------------------------------------------------------------------------
def now_local():
    return datetime.now(TZ) if TZ else datetime.now()


def current_week_start(d=None):
    """Return the Monday (ISO date string) of the week containing `d`."""
    d = d or now_local().date()
    monday = d - timedelta(days=d.weekday())
    return monday.isoformat()


def week_label(week_start_iso):
    start = date.fromisoformat(week_start_iso)
    end = start + timedelta(days=6)
    return f"Week of {start.strftime('%b %d')} – {end.strftime('%b %d, %Y')}"


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    with closing(sqlite3.connect(DB_PATH)) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS topics (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                week_start  TEXT NOT NULL,
                who         TEXT NOT NULL,
                topic       TEXT NOT NULL,
                context     TEXT DEFAULT '',
                priority    TEXT DEFAULT '',
                created_at  TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS weeks (
                week_start   TEXT PRIMARY KEY,
                forecast     TEXT DEFAULT '',
                extra_notes  TEXT DEFAULT '',
                finalized_at TEXT
            );
            CREATE TABLE IF NOT EXISTS action_items (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                week_start  TEXT NOT NULL,
                text        TEXT NOT NULL,
                done        INTEGER DEFAULT 0,
                created_at  TEXT NOT NULL
            );
            """
        )
        db.commit()


def ensure_week(db, week_start):
    db.execute(
        "INSERT OR IGNORE INTO weeks (week_start) VALUES (?)", (week_start,)
    )
    db.commit()


# ---------------------------------------------------------------------------
# State assembly
# ---------------------------------------------------------------------------
def build_state(week_start):
    db = get_db()
    ensure_week(db, week_start)

    topics = [dict(r) for r in db.execute(
        "SELECT * FROM topics WHERE week_start = ? ORDER BY created_at", (week_start,)
    )]
    topics.sort(key=lambda t: (PRIORITY_ORDER.get(t["priority"], 3), t["created_at"]))

    week_row = db.execute(
        "SELECT * FROM weeks WHERE week_start = ?", (week_start,)
    ).fetchone()

    items = [dict(r) for r in db.execute(
        "SELECT * FROM action_items WHERE week_start = ? ORDER BY done, created_at",
        (week_start,),
    )]

    # list of recent weeks for the archive dropdown
    weeks = [r["week_start"] for r in db.execute(
        "SELECT DISTINCT week_start FROM "
        "(SELECT week_start FROM topics UNION SELECT week_start FROM weeks "
        " UNION SELECT week_start FROM action_items) ORDER BY week_start DESC"
    )]

    return {
        "week_start": week_start,
        "week_label": week_label(week_start),
        "is_current": week_start == current_week_start(),
        "topics": topics,
        "forecast": week_row["forecast"] if week_row else "",
        "extra_notes": week_row["extra_notes"] if week_row else "",
        "finalized_at": week_row["finalized_at"] if week_row else None,
        "action_items": items,
        "weeks": weeks,
        "now": now_local().strftime("%A, %b %d %Y %H:%M") + " CET",
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/state")
def api_state():
    week = request.args.get("week") or current_week_start()
    return jsonify(build_state(week))


@app.route("/api/topics", methods=["POST"])
def add_topic():
    data = request.get_json(force=True)
    who = (data.get("who") or "").strip()
    topic = (data.get("topic") or "").strip()
    if not who or not topic:
        return jsonify({"error": "Name and topic are required."}), 400
    priority = data.get("priority", "")
    if priority not in PRIORITY_ORDER:
        priority = ""
    week = current_week_start()
    db = get_db()
    ensure_week(db, week)
    db.execute(
        "INSERT INTO topics (week_start, who, topic, context, priority, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (week, who, topic, (data.get("context") or "").strip(), priority,
         now_local().isoformat()),
    )
    db.commit()
    return jsonify(build_state(week))


@app.route("/api/topics/<int:topic_id>", methods=["DELETE"])
def delete_topic(topic_id):
    db = get_db()
    db.execute("DELETE FROM topics WHERE id = ?", (topic_id,))
    db.commit()
    return jsonify(build_state(current_week_start()))


@app.route("/api/week", methods=["POST"])
def update_week():
    """Update forecast and/or extra_notes for the current week."""
    data = request.get_json(force=True)
    week = current_week_start()
    db = get_db()
    ensure_week(db, week)
    fields, values = [], []
    if "forecast" in data:
        fields.append("forecast = ?")
        values.append(data["forecast"])
    if "extra_notes" in data:
        fields.append("extra_notes = ?")
        values.append(data["extra_notes"])
    if fields:
        values.append(week)
        db.execute(f"UPDATE weeks SET {', '.join(fields)} WHERE week_start = ?", values)
        db.commit()
    return jsonify(build_state(week))


@app.route("/api/action-items", methods=["POST"])
def add_action_item():
    data = request.get_json(force=True)
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "Text required."}), 400
    week = current_week_start()
    db = get_db()
    ensure_week(db, week)
    db.execute(
        "INSERT INTO action_items (week_start, text, done, created_at) VALUES (?, ?, 0, ?)",
        (week, text, now_local().isoformat()),
    )
    db.commit()
    return jsonify(build_state(week))


@app.route("/api/action-items/<int:item_id>", methods=["POST"])
def toggle_action_item(item_id):
    data = request.get_json(force=True)
    db = get_db()
    if data.get("delete"):
        db.execute("DELETE FROM action_items WHERE id = ?", (item_id,))
    else:
        db.execute("UPDATE action_items SET done = ? WHERE id = ?",
                   (1 if data.get("done") else 0, item_id))
    db.commit()
    return jsonify(build_state(current_week_start()))


@app.route("/api/finalize", methods=["POST"])
def finalize():
    """Mark the current week's agenda as organized/ready (used by the Monday job)."""
    week = current_week_start()
    db = get_db()
    ensure_week(db, week)
    db.execute("UPDATE weeks SET finalized_at = ? WHERE week_start = ?",
               (now_local().isoformat(), week))
    db.commit()
    state = build_state(week)
    return jsonify({"ok": True, "week": week, "topic_count": len(state["topics"])})


# Ensure tables exist on import, so it works under gunicorn (Render) too —
# not only when run directly via `python app.py`.
init_db()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
