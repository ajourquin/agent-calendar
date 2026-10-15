#!/usr/bin/env python3
"""Generate ~/dashboard.yaml (the agent's Trinity Dashboard tab) from local state.

Reads only ~/calendar/upcoming.json, the cache calendar_events.py rewrites after
every change — no network, never wakes Claude. The file is generated, hence
git-ignored. The output is JSON, which is valid YAML.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

HOME = Path.home()
CACHE_FILE = HOME / "calendar" / "upcoming.json"
OUT = HOME / "dashboard.yaml"
DISPLAY_TZ = ZoneInfo("America/Toronto")


def start_utc(value: str) -> str:
    """ISO UTC instant for the "in 3 days" hint: an all-day event starts at local midnight."""
    try:
        if len(value) == 10:
            dt = datetime.fromisoformat(value).replace(tzinfo=DISPLAY_TZ)
        else:
            dt = datetime.fromisoformat(value)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return ""


def main() -> int:
    try:
        cache = json.loads(CACHE_FILE.read_text())
    except (OSError, ValueError):
        cache = {"events": []}
    events = cache.get("events", [])
    today = datetime.now(DISPLAY_TZ).date().isoformat()
    upcoming = [e for e in events if (e.get("start") or "")[:10] >= today]

    widgets = [
        {"type": "metric", "id": "upcoming_90d", "label": "Upcoming events (90 days)", "value": len(upcoming)},
        {"type": "status", "label": "Next event",
         "value": f"{upcoming[0]['when']} — {upcoming[0]['title']}" if upcoming else "Nothing planned",
         "color": "blue" if upcoming else "gray"},
    ]
    details = [{
        "type": "table",
        "columns": [{"key": "when", "label": "When", "relative_key": "start"},
                    {"key": "title", "label": "Event"}, {"key": "source", "label": "From"}],
        "rows": [{"when": e["when"], "start": start_utc(e.get("start") or ""), "title": e["title"], "source": e["source"]}
                 for e in upcoming],
        "max_rows": 30,
    }] if upcoming else [{"type": "text", "content": "No upcoming event."}]

    dashboard = {
        "title": "Calendar",
        "refresh": 60,
        "sections": [{"title": "Family calendar", "layout": "grid", "columns": 2, "widgets": widgets},
                     {"layout": "list", "widgets": details}],
    }
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(dashboard, ensure_ascii=False, indent=2))
    os.replace(tmp, OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
