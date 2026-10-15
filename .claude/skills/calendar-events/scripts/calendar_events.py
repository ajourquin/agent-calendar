#!/usr/bin/env python3
"""The family calendar: one dedicated Google Calendar, written only by this script.

  calendar_events.py check
        Verify the credentials and the access to the calendar.
  calendar_events.py apply '<json>'
        Apply one event request sent by another agent (the JSON block between
        --- BEGIN EVENT --- and --- END EVENT ---). See EVENT REQUEST below.
  calendar_events.py upsert --key KEY --title TITLE --date YYYY-MM-DD [--end-date YYYY-MM-DD]
                            [--description TEXT] [--source NAME]
  calendar_events.py upsert --key KEY --title TITLE --start "YYYY-MM-DD HH:MM" --end "YYYY-MM-DD HH:MM" ...
        Create the event, or update the one with the same key.
  calendar_events.py delete --key KEY
  calendar_events.py list [--days N]
        Upcoming events of the calendar (default 60 days).

EVENT REQUEST (JSON):
  {"action": "upsert", "key": "school:e6d53d39b3:emma", "title": "...",
   "date": "2026-11-19", "description": "...", "source": "school"}
  {"action": "upsert", "key": "...", "title": "...", "start": "2026-11-19 14:00", "end": "2026-11-19 15:00",
   "location": "...", ...}
  {"action": "delete", "key": "...", "source": "school"}

Safety:
- Only the calendar named by GOOGLE_CALENDAR_ID, through a service account that
  was given access to that calendar only.
- Every event carries its KEY in a private extended property: sending the same
  key again updates the event, never duplicates it. A key must start with its
  source ("school:..."), so a source can only touch its own events.
- Never deletes or edits an event this script did not create (no key = untouched).

Credentials (~/.env, injected by Trinity):
  GOOGLE_CALENDAR_ID               the calendar's ID (Google Calendar → settings → "Calendar ID")
  GOOGLE_SERVICE_ACCOUNT_JSON_B64  the service account JSON key, base64-encoded
"""

import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

HOME = Path.home()
DATA_DIR = HOME / "calendar"
CACHE_FILE = DATA_DIR / "upcoming.json"
LOG_FILE = DATA_DIR / "log.jsonl"
TZ_NAME = "America/Toronto"
LOCAL_TZ = ZoneInfo(TZ_NAME)
SCOPE = "https://www.googleapis.com/auth/calendar.events"
API = "https://www.googleapis.com/calendar/v3"
KEY_PROPERTY = "agentKey"
SOURCES = {"school", "mail", "user"}
KEY_RE = re.compile(r"^[a-z]+:[A-Za-z0-9:._-]{1,120}$")
MAX_TITLE, MAX_DESCRIPTION, MAX_LOCATION = 200, 2000, 300


# --- helpers ------------------------------------------------------------------


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(event: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a") as f:
        f.write(json.dumps({"at": now_iso(), **event}, ensure_ascii=False) + "\n")


def env(name: str) -> str:
    """From the environment, else from ~/.env (scripts run outside a Claude turn too)."""
    value = os.environ.get(name)
    if value:
        return value
    env_file = HOME / ".env"
    if env_file.is_file():
        for line in env_file.read_text().splitlines():
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit(f"ERROR: {name} is not set (inject it in Trinity → Credentials).")


# --- Google auth (service account, JWT bearer flow) ---------------------------


_token: dict = {}


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def access_token() -> str:
    if _token.get("value") and _token["expires"] > time.time() + 60:
        return _token["value"]
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    try:
        info = json.loads(base64.b64decode(env("GOOGLE_SERVICE_ACCOUNT_JSON_B64")))
    except ValueError as e:
        raise SystemExit(f"ERROR: GOOGLE_SERVICE_ACCOUNT_JSON_B64 is not a base64 JSON key ({e}).")
    now = int(time.time())
    header = b64url(json.dumps({"alg": "RS256", "typ": "JWT", "kid": info.get("private_key_id")}).encode())
    claims = b64url(json.dumps({"iss": info["client_email"], "scope": SCOPE, "aud": info["token_uri"],
                                "iat": now, "exp": now + 3600}).encode())
    key = serialization.load_pem_private_key(info["private_key"].encode(), password=None)
    signature = key.sign(f"{header}.{claims}".encode(), padding.PKCS1v15(), hashes.SHA256())
    body = urllib.parse.urlencode({"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                                   "assertion": f"{header}.{claims}.{b64url(signature)}"}).encode()
    with urllib.request.urlopen(urllib.request.Request(info["token_uri"], data=body), timeout=20) as resp:
        data = json.loads(resp.read())
    _token.update(value=data["access_token"], expires=now + int(data.get("expires_in", 3600)))
    return _token["value"]


def api(method: str, path: str, params: dict | None = None, body: dict | None = None):
    url = f"{API}{path}" + (f"?{urllib.parse.urlencode(params)}" if params else "")
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {access_token()}",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"Google Calendar API {method} {path}: HTTP {e.code} {detail}") from None
    return json.loads(raw) if raw else None


def events_path() -> str:
    return f"/calendars/{urllib.parse.quote(env('GOOGLE_CALENDAR_ID'), safe='')}/events"


# --- events -------------------------------------------------------------------


def find(key: str) -> dict | None:
    found = api("GET", events_path(), {"privateExtendedProperty": f"{KEY_PROPERTY}={key}",
                                       "showDeleted": "false", "maxResults": 5})
    items = found.get("items", []) if found else []
    return items[0] if items else None


def parse_day(value: str) -> date:
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise SystemExit(f"ERROR: '{value}' is not a date (YYYY-MM-DD).")


def parse_local(value: str) -> datetime:
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d %H:%M").replace(tzinfo=LOCAL_TZ)
    except ValueError:
        raise SystemExit(f"ERROR: '{value}' is not a local time (YYYY-MM-DD HH:MM).")


def build_event(req: dict) -> dict:
    key, source = req["key"], req.get("source", "user")
    if source not in SOURCES:
        raise SystemExit(f"REFUSED: unknown source '{source}' (known: {', '.join(sorted(SOURCES))}).")
    if not KEY_RE.match(key) or not key.startswith(f"{source}:"):
        raise SystemExit(f"REFUSED: key '{key}' must look like '{source}:<id>' (letters, digits, : . _ -).")
    title = " ".join(str(req.get("title", "")).split())[:MAX_TITLE]
    if not title:
        raise SystemExit("REFUSED: an event needs a title.")
    event = {
        "summary": title,
        "description": str(req.get("description") or "")[:MAX_DESCRIPTION],
        "location": " ".join(str(req.get("location") or "").split())[:MAX_LOCATION],
        "extendedProperties": {"private": {KEY_PROPERTY: key, "source": source}},
    }
    if req.get("date"):
        first = parse_day(req["date"])
        last = parse_day(req["end_date"]) if req.get("end_date") else first
        if last < first:
            raise SystemExit("REFUSED: end_date is before date.")
        # All-day events: the end date is exclusive in Google Calendar
        event["start"] = {"date": first.isoformat()}
        event["end"] = {"date": (last + timedelta(days=1)).isoformat()}
    elif req.get("start") and req.get("end"):
        start, end = parse_local(req["start"]), parse_local(req["end"])
        if end <= start:
            raise SystemExit("REFUSED: end is not after start.")
        event["start"] = {"dateTime": start.isoformat(), "timeZone": TZ_NAME}
        event["end"] = {"dateTime": end.isoformat(), "timeZone": TZ_NAME}
    else:
        raise SystemExit("REFUSED: give either date (all-day) or start and end.")
    return event


def when(event: dict) -> str:
    start = event.get("start", {})
    if "date" in start:
        last = date.fromisoformat(event["end"]["date"]) - timedelta(days=1)
        first = start["date"]
        return first if last.isoformat() == first else f"{first} → {last.isoformat()}"
    begin = datetime.fromisoformat(start["dateTime"]).astimezone(LOCAL_TZ)
    end = datetime.fromisoformat(event["end"]["dateTime"]).astimezone(LOCAL_TZ)
    return f"{begin:%Y-%m-%d %H:%M}–{end:%H:%M}"


def instant(value: dict) -> str | None:
    """An all-day date, or a date-time as UTC — Google echoes times in its own offset."""
    if value.get("date"):
        return value["date"]
    if value.get("dateTime"):
        return datetime.fromisoformat(value["dateTime"]).astimezone(timezone.utc).isoformat()
    return None


def same(existing: dict, wanted: dict) -> bool:
    return (existing.get("summary", "") == wanted["summary"]
            and existing.get("description", "") == wanted["description"]
            and existing.get("location", "") == wanted["location"]
            and instant(existing.get("start", {})) == instant(wanted["start"])
            and instant(existing.get("end", {})) == instant(wanted["end"]))


def upsert(req: dict) -> str:
    wanted = build_event(req)
    key = req["key"]
    existing = find(key)
    if existing and same(existing, wanted):
        result = f"UNCHANGED: {wanted['summary']} ({when(existing)}) [{key}]"
    elif existing:
        saved = api("PATCH", f"{events_path()}/{existing['id']}", body=wanted)
        result = f"UPDATED: {saved['summary']} ({when(saved)}) [{key}]"
    else:
        saved = api("POST", events_path(), body=wanted)
        result = f"CREATED: {saved['summary']} ({when(saved)}) [{key}]"
    log({"action": "upsert", "key": key, "result": result.split(":")[0]})
    return result


def delete(req: dict) -> str:
    key, source = req["key"], req.get("source", "user")
    if not KEY_RE.match(key) or not key.startswith(f"{source}:"):
        raise SystemExit(f"REFUSED: key '{key}' does not belong to source '{source}'.")
    existing = find(key)
    if not existing:
        return f"NOTHING TO DELETE: no event with key [{key}]"
    api("DELETE", f"{events_path()}/{existing['id']}")
    log({"action": "delete", "key": key})
    return f"DELETED: {existing.get('summary')} ({when(existing)}) [{key}]"


def upcoming(days: int) -> list[dict]:
    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    found = api("GET", events_path(), {"timeMin": start.isoformat(), "timeMax": (start + timedelta(days=days + 1)).isoformat(),
                                       "singleEvents": "true", "orderBy": "startTime", "maxResults": 250})
    return found.get("items", []) if found else []


def refresh_cache() -> None:
    """Upcoming events for the Dashboard tab (best-effort, never fails a command)."""
    try:
        items = [{"when": when(e), "start": e["start"].get("date") or e["start"].get("dateTime"),
                  "title": e.get("summary", ""),
                  "source": e.get("extendedProperties", {}).get("private", {}).get("source", "—")}
                 for e in upcoming(90)]
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps({"updated_at": now_iso(), "events": items}, ensure_ascii=False, indent=2))
        import subprocess
        script = HOME / "scripts" / "update_dashboard.py"
        if script.is_file():
            subprocess.run([sys.executable, str(script)], capture_output=True, timeout=20, check=False)
    except Exception:  # noqa: BLE001 — the dashboard is a convenience
        pass


# --- commands -----------------------------------------------------------------


def cmd_check(args) -> int:
    items = upcoming(30)
    print(f"OK: calendar reachable, {len(items)} event(s) in the next 30 days.")
    return 0


def cmd_apply(args) -> int:
    try:
        req = json.loads(args.json)
    except ValueError as e:
        print(f"REFUSED: the event request is not valid JSON ({e}).")
        return 1
    if not isinstance(req, dict) or req.get("action") not in ("upsert", "delete") or not req.get("key"):
        print("REFUSED: expected {\"action\": \"upsert\"|\"delete\", \"key\": ..., ...}.")
        return 1
    print(upsert(req) if req["action"] == "upsert" else delete(req))
    return 0


def cmd_upsert(args) -> int:
    req = {k: v for k, v in vars(args).items() if k in ("key", "title", "date", "end_date", "start", "end",
                                                          "description", "location", "source") and v}
    print(upsert(req))
    return 0


def cmd_delete(args) -> int:
    print(delete({"key": args.key, "source": args.source}))
    return 0


def cmd_list(args) -> int:
    items = upcoming(args.days)
    if not items:
        print(f"No event in the next {args.days} days.")
    for e in items:
        source = e.get("extendedProperties", {}).get("private", {}).get("source", "—")
        print(f"{when(e)} | {e.get('summary', '')} | source: {source}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check")
    p = sub.add_parser("apply")
    p.add_argument("json")
    p = sub.add_parser("upsert")
    p.add_argument("--key", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--date")
    p.add_argument("--end-date")
    p.add_argument("--start")
    p.add_argument("--end")
    p.add_argument("--description")
    p.add_argument("--location")
    p.add_argument("--source", default="user")
    p = sub.add_parser("delete")
    p.add_argument("--key", required=True)
    p.add_argument("--source", default="user")
    p = sub.add_parser("list")
    p.add_argument("--days", type=int, default=60)
    args = parser.parse_args()
    try:
        code = {"check": cmd_check, "apply": cmd_apply, "upsert": cmd_upsert, "delete": cmd_delete,
                "list": cmd_list}[args.command](args)
    except RuntimeError as e:
        print(f"ERROR: {e}")
        return 1
    if args.command in ("apply", "upsert", "delete"):
        refresh_cache()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
