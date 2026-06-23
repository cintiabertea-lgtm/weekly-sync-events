"""
Weekly Sync — Events Team
=========================
A small hosted web app where the team inputs topics for the weekly sync,
and the forecast (from daily_tasks.py) + extra notes get assembled for
Monday's meeting.

Storage:
  - If DATABASE_URL is set (e.g. on Render), uses PostgreSQL — data persists.
  - Otherwise falls back to a local SQLite file (good for running via the .bat).

Run locally:
    pip install -r requirements.txt
    python app.py
    -> open http://localhost:5000

The app organizes everything by "week" (Monday-based, in CET).
"""

import os
from datetime import datetime, timedelta, date

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
    TZ = ZoneInfo("Europe/Berlin")  # Central European (CET/CEST)
except Exception:  # pragma: no cover
    TZ = None

import secrets
from flask import Flask, Response, g, jsonify, render_template, request

# ---------------------------------------------------------------------------
# Config / storage backend selection
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("WEEKLY_SYNC_DB", os.path.join(BASE_DIR, "weekly_sync.db"))
PRIORITY_ORDER = {"High": 0, "Medium": 1, "Low": 2, "": 3}

# Render hands us a postgres URL; normalize the old postgres:// scheme.
DATABASE_URL = os.environ.get("DATABASE_URL", "")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
IS_PG = bool(DATABASE_URL)

if IS_PG:
    import psycopg
    from psycopg.rows import dict_row
    PH = "%s"                         # Postgres parameter placeholder
    AUTO_ID = "id SERIAL PRIMARY KEY"
else:
    import sqlite3
    PH = "?"                          # SQLite parameter placeholder
    AUTO_ID = "id INTEGER PRIMARY KEY AUTOINCREMENT"

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Access control (shared login via HTTP Basic Auth)
# ---------------------------------------------------------------------------
# Auth is enforced only when BOTH SYNC_USER and SYNC_PASSWORD are set (they are
# on Render). Locally (e.g. via the .bat) they're unset, so no prompt appears.
SYNC_USER = os.environ.get("SYNC_USER")
SYNC_PASSWORD = os.environ.get("SYNC_PASSWORD")
AUTH_ENABLED = bool(SYNC_USER and SYNC_PASSWORD)


@app.before_request
def _require_login():
    if not AUTH_ENABLED:
        return None
    a = request.authorization
    if a and secrets.compare_digest(a.username or "", SYNC_USER) \
            and secrets.compare_digest(a.password or "", SYNC_PASSWORD):
        return None
    return Response("Login required.", 401,
                    {"WWW-Authenticate": 'Basic realm="Weekly Sync - Events Team"'})


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
# Database (works against Postgres or SQLite)
# ---------------------------------------------------------------------------
def connect():
    if IS_PG:
        return psycopg.connect(DATABASE_URL, row_factory=dict_row)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def get_db():
    if "db" not in g:
        g.db = connect()
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


SCHEMA = [
    f"""CREATE TABLE IF NOT EXISTS topics (
            {AUTO_ID},
            week_start  TEXT NOT NULL,
            who         TEXT NOT NULL,
            topic       TEXT NOT NULL,
            context     TEXT DEFAULT '',
            priority    TEXT DEFAULT '',
            created_at  TEXT NOT NULL
        )""",
    """CREATE TABLE IF NOT EXISTS weeks (
            week_start   TEXT PRIMARY KEY,
            forecast     TEXT DEFAULT '',
            extra_notes  TEXT DEFAULT '',
            finalized_at TEXT
        )""",
    f"""CREATE TABLE IF NOT EXISTS action_items (
            {AUTO_ID},
            week_start  TEXT NOT NULL,
            text        TEXT NOT NULL,
            done        INTEGER DEFAULT 0,
            created_at  TEXT NOT NULL
        )""",
]


def init_db():
    con = connect()
    try:
        for stmt in SCHEMA:
            con.execute(stmt)
        con.commit()
    finally:
        con.close()


def ensure_week(db, week_start):
    if IS_PG:
        cur = db.execute(
            f"INSERT INTO weeks (week_start) VALUES ({PH}) ON CONFLICT (week_start) DO NOTHING",
            (week_start,),
        )
    else:
        cur = db.execute(
            f"INSERT OR IGNORE INTO weeks (week_start) VALUES ({PH})", (week_start,)
        )
    # When this is the first time the *current* week is created, roll any
    # still-unchecked action items forward from the most recent prior week.
    if cur.rowcount == 1 and week_start == current_week_start():
        carry_over_action_items(db, week_start)
    db.commit()


def carry_over_action_items(db, new_week):
    prev = query(
        db,
        f"SELECT week_start FROM action_items WHERE week_start < {PH} "
        f"ORDER BY week_start DESC LIMIT 1",
        (new_week,),
    )
    if not prev:
        return
    pending = query(
        db,
        f"SELECT text FROM action_items WHERE week_start = {PH} AND done = 0 "
        f"ORDER BY created_at",
        (prev[0]["week_start"],),
    )
    for item in pending:
        db.execute(
            f"INSERT INTO action_items (week_start, text, done, created_at) "
            f"VALUES ({PH}, {PH}, 0, {PH})",
            (new_week, item["text"], now_local().isoformat()),
        )


def query(db, sql, params=()):
    """Run a SELECT and return a list of dict rows (dialect-agnostic)."""
    cur = db.execute(sql, params)
    return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# State assembly
# ---------------------------------------------------------------------------
def build_state(week_start):
    db = get_db()
    ensure_week(db, week_start)

    topics = query(
        db, f"SELECT * FROM topics WHERE week_start = {PH} ORDER BY created_at",
        (week_start,),
    )
    topics.sort(key=lambda t: (PRIORITY_ORDER.get(t["priority"], 3), t["created_at"]))

    week_rows = query(db, f"SELECT * FROM weeks WHERE week_start = {PH}", (week_start,))
    week_row = week_rows[0] if week_rows else None

    items = query(
        db,
        f"SELECT * FROM action_items WHERE week_start = {PH} ORDER BY done, created_at",
        (week_start,),
    )

    weeks = [r["week_start"] for r in query(
        db,
        "SELECT DISTINCT week_start FROM "
        "(SELECT week_start FROM topics UNION SELECT week_start FROM weeks "
        " UNION SELECT week_start FROM action_items) AS w ORDER BY week_start DESC",
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


@app.route("/api/health")
def health():
    """Reports which storage backend is active (no secrets exposed)."""
    return jsonify({"ok": True, "backend": "postgres" if IS_PG else "sqlite"})


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
        f"INSERT INTO topics (week_start, who, topic, context, priority, created_at) "
        f"VALUES ({PH}, {PH}, {PH}, {PH}, {PH}, {PH})",
        (week, who, topic, (data.get("context") or "").strip(), priority,
         now_local().isoformat()),
    )
    db.commit()
    return jsonify(build_state(week))


@app.route("/api/topics/<int:topic_id>", methods=["DELETE"])
def delete_topic(topic_id):
    db = get_db()
    db.execute(f"DELETE FROM topics WHERE id = {PH}", (topic_id,))
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
        fields.append(f"forecast = {PH}")
        values.append(data["forecast"])
    if "extra_notes" in data:
        fields.append(f"extra_notes = {PH}")
        values.append(data["extra_notes"])
    if fields:
        values.append(week)
        db.execute(f"UPDATE weeks SET {', '.join(fields)} WHERE week_start = {PH}", values)
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
        f"INSERT INTO action_items (week_start, text, done, created_at) "
        f"VALUES ({PH}, {PH}, 0, {PH})",
        (week, text, now_local().isoformat()),
    )
    db.commit()
    return jsonify(build_state(week))


@app.route("/api/action-items/<int:item_id>", methods=["POST"])
def toggle_action_item(item_id):
    data = request.get_json(force=True)
    db = get_db()
    if data.get("delete"):
        db.execute(f"DELETE FROM action_items WHERE id = {PH}", (item_id,))
    else:
        db.execute(f"UPDATE action_items SET done = {PH} WHERE id = {PH}",
                   (1 if data.get("done") else 0, item_id))
    db.commit()
    return jsonify(build_state(current_week_start()))


@app.route("/api/cleanup", methods=["POST"])
def cleanup():
    """Reset the current week for fresh topic collection (post-meeting).
    Clears topics, forecast, and extra notes; deletes COMPLETED action items
    but keeps unchecked ones. Past weeks are untouched (still archived)."""
    week = current_week_start()
    db = get_db()
    ensure_week(db, week)
    topics_removed = query(
        db, f"SELECT COUNT(*) AS n FROM topics WHERE week_start = {PH}", (week,)
    )[0]["n"]
    db.execute(f"DELETE FROM topics WHERE week_start = {PH}", (week,))
    db.execute(f"DELETE FROM action_items WHERE week_start = {PH} AND done = 1", (week,))
    db.execute(
        f"UPDATE weeks SET forecast = '', extra_notes = '', finalized_at = NULL "
        f"WHERE week_start = {PH}",
        (week,),
    )
    db.commit()
    kept = query(
        db, f"SELECT COUNT(*) AS n FROM action_items WHERE week_start = {PH}", (week,)
    )[0]["n"]
    return jsonify({"ok": True, "week": week,
                    "topics_removed": topics_removed,
                    "open_action_items_kept": kept})


@app.route("/api/finalize", methods=["POST"])
def finalize():
    """Mark the current week's agenda as organized/ready (used by the Monday job)."""
    week = current_week_start()
    db = get_db()
    ensure_week(db, week)
    db.execute(f"UPDATE weeks SET finalized_at = {PH} WHERE week_start = {PH}",
               (now_local().isoformat(), week))
    db.commit()
    state = build_state(week)
    return jsonify({"ok": True, "week": week, "topic_count": len(state["topics"])})


# Ensure tables exist on import, so it works under gunicorn (Render) too —
# not only when run directly via `python app.py`.
init_db()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
