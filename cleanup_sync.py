"""
Cleanup Weekly Sync — post-meeting reset.
=========================================
Resets the current week so it's ready to collect next week's topics:
clears topics, forecast, and extra notes; removes COMPLETED action items;
keeps unchecked ones. Past weeks stay archived.

Run by the Windows scheduled task "Weekly Sync Cleanup" (Mondays 14:30),
and can be run manually anytime. URL overridable via WEEKLY_SYNC_URL.
"""

import json
import os
import time
import urllib.request

BASE = os.environ.get("WEEKLY_SYNC_URL", "https://weekly-sync-events.onrender.com").rstrip("/")
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cleanup.log")


def log(msg):
    print(msg)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


def main():
    for attempt in range(1, 6):
        try:
            req = urllib.request.Request(BASE + "/api/cleanup", method="POST")
            with urllib.request.urlopen(req, timeout=90) as r:
                res = json.loads(r.read().decode("utf-8"))
            log(f"[{time.strftime('%Y-%m-%d %H:%M')}] Cleanup OK: "
                  f"{res.get('topics_removed')} topic(s) cleared, "
                  f"{res.get('open_action_items_kept')} open action item(s) kept "
                  f"(week {res.get('week')}).")
            return
        except Exception as e:
            log(f"[try {attempt}/5] site waking / unreachable: {e}")
            time.sleep(15)
    log("Cleanup FAILED after retries — the site could not be reached.")


if __name__ == "__main__":
    main()
