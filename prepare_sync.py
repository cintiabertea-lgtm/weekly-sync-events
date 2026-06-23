"""
Prepare Weekly Sync — manual "get the page ready" runner.
=========================================================
Does the same thing the (optional) Monday automation would do, but on demand:
  1. Marks the current week's page "Organized & ready" (/api/finalize)
  2. Prints a summary: topic count + priorities, and reminders if the
     forecast or extra-notes sections are still empty
  3. Opens the page in your browser

Double-click "Prepare Weekly Sync.bat" to run it.
The site URL can be overridden with the WEEKLY_SYNC_URL environment variable.
"""

import json
import os
import sys
import time
import urllib.request
import webbrowser

# Make UTF-8 output (en dashes, etc.) render cleanly in the Windows console.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = os.environ.get("WEEKLY_SYNC_URL", "https://weekly-sync-events.onrender.com").rstrip("/")
PRIORITY_ORDER = {"High": 0, "Medium": 1, "Low": 2, "": 3}


def _auth_headers():
    """Read 'user:password' from auth.txt (next to this script) for Basic Auth."""
    import base64
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "auth.txt")
    if os.path.exists(p):
        cred = open(p, encoding="utf-8").read().strip()
        if cred:
            return {"Authorization": "Basic " + base64.b64encode(cred.encode()).decode()}
    return {}


def call(path, method="GET"):
    req = urllib.request.Request(BASE + path, method=method, headers=_auth_headers())
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    print("=" * 56)
    print("  PREPARE WEEKLY SYNC")
    print("=" * 56)
    print(f"  Site: {BASE}")
    print("\n  Waking the site and organizing the page...")
    print("  (free hosting can take ~30-60s to wake — please wait)\n")

    # Finalize, retrying through Render's cold start.
    state = None
    for attempt in range(1, 6):
        try:
            call("/api/finalize", method="POST")
            state = call("/api/state")
            break
        except Exception as e:
            print(f"  ...still waking (try {attempt}/5): {e}")
            time.sleep(15)

    if state is None:
        print("\n  Could not reach the site. Check your internet and try again.")
        return

    topics = sorted(state["topics"],
                    key=lambda t: PRIORITY_ORDER.get(t.get("priority", ""), 3))
    counts = {"High": 0, "Medium": 0, "Low": 0, "": 0}
    for t in topics:
        counts[t.get("priority", "")] = counts.get(t.get("priority", ""), 0) + 1

    print("-" * 56)
    print(f"  {state['week_label']}  —  PAGE IS ORGANIZED & READY")
    print("-" * 56)
    print(f"  Discussion topics: {len(topics)}"
          f"   (High {counts['High']} / Medium {counts['Medium']} / Low {counts['Low']}"
          + (f" / unset {counts['']}" if counts[''] else "") + ")")
    for t in topics:
        pri = f"[{t['priority']}]" if t.get("priority") else "[ - ]"
        print(f"    {pri:9s} {t['who']}: {t['topic']}")

    print()
    if not (state.get("forecast") or "").strip():
        print("  ! Forecast is EMPTY — run daily_tasks.py and paste its output into")
        print("    the 'This week's forecast' section before the meeting.")
    else:
        print("  + Forecast: filled in.")
    if not (state.get("extra_notes") or "").strip():
        print("  ! Extra notes are EMPTY — add anything worth mentioning.")
    else:
        print("  + Extra notes: filled in.")

    print("\n  Opening the page in your browser...")
    webbrowser.open(BASE + "/")
    print("=" * 56)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
    finally:
        input("\nPress Enter to close...")
