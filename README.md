# Weekly Sync — Events Team

A small web app where the team drops in topics for the weekly sync, and the
forecast (from `daily_tasks.py`) + extra notes get assembled for Monday's meeting.

## What it does
- **🗣️ Topics** — anyone enters Who / Topic / Context / Priority; the list auto-sorts by priority.
- **📊 Forecast** — paste the `daily_tasks.py` weekly output; it's shown formatted.
- **📝 Extra notes** — Cintia's manual heads-ups.
- **✅ Action items** — checklist captured live in the meeting.
- Everything is grouped by **week** (Monday-based, CET). Old weeks stay viewable via the week picker.

## Run locally
```bash
pip install -r requirements.txt
python app.py
# open http://localhost:5000
```
Data is stored in `weekly_sync.db` (SQLite, created automatically). To start fresh, delete that file.

## Deploy so the whole team can reach it
The app reads `PORT` from the environment and listens on `0.0.0.0`, so it runs on any host as-is.

**Render / Railway / Fly.io (free tiers):**
- Start command: `gunicorn app:app`  (gunicorn is in requirements.txt)
- For persistent data across restarts, attach a disk and set `WEEKLY_SYNC_DB` to a path on it
  (e.g. `/data/weekly_sync.db`). Without a persistent disk, SQLite resets on redeploy.

**Internal server / always-on machine:**
```bash
gunicorn -b 0.0.0.0:5000 app:app
```
Put it behind your reverse proxy / VPN as needed.

## Monday-noon automation
A scheduled task (`weekly-sync-monday`, runs `0 12 * * 1` CET) marks the week
"Organized & ready" and notifies Cintia, reminding her to paste the forecast and
add notes. If the app is hosted, set the env var `WEEKLY_SYNC_URL` to its public URL
so the task talks to the live site instead of localhost.
