---
name: calendar-events
description: Read and change the family's dedicated Google Calendar — apply event requests sent by other agents (school, mail), list upcoming events, add/move/delete an event for the user.
---

# calendar-events

Everything goes through one script. Never call the Google Calendar API any other way.

```bash
C=.claude/skills/calendar-events/scripts/calendar_events.py

python3 $C check                    # credentials + access to the calendar
python3 $C apply '<json>'           # an event request from another agent, JSON copied exactly
python3 $C list [--days 60]         # upcoming events

# For the user (source "user", key "user:<short-id>")
python3 $C upsert --source user --key user:dentiste-emma --title "Dentiste — Emma" --start "2026-11-03 15:30" --end "2026-11-03 16:30"
python3 $C upsert --source user --key user:conge --title "Congé" --date 2026-12-24 [--end-date 2026-12-26]
python3 $C delete --source user --key user:dentiste-emma
```

## Results

- `CREATED` / `UPDATED` / `UNCHANGED` / `DELETED` / `NOTHING TO DELETE`: done.
- `REFUSED`: the request is malformed or a source tried to use another source's key. Nothing changed.
- `ERROR`: Google refused or could not be reached. Nothing changed (or check with `list`).

## How it works

- Each event carries its **key** (private extended property `agentKey`): the same key updates the event instead of duplicating it. A key starts with its source (`school:`, `mail:`, `user:`), so a source only touches its own events.
- All-day events with `date` (and `end_date`, inclusive); timed events with `start`/`end` in local time (America/Toronto); optional `location` (`--location`).
- Credentials (`~/.env`): `GOOGLE_CALENDAR_ID`, `GOOGLE_SERVICE_ACCOUNT_JSON_B64` (service account shared on that calendar only, "Make changes to events").
