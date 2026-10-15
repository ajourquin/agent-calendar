# agent-calendar

A [Trinity](https://github.com/abilityai/trinity) agent that keeps the family's dedicated Google Calendar up to date.

Other agents send it event requests: for now the `school` agent sends each pedagogical day the children are registered to; later the `mail` agent will send Amazon deliveries and appointments.

## How it works

1. An agent sends a message "Calendar event request from agent <name>" with one JSON object (built by script, never by the model).
2. The agent runs `calendar_events.py apply '<json>'`: the event is created, or updated if one with the same **key** exists — never duplicated.
3. The Dashboard tab lists the upcoming events.

Everything goes through one script: `.claude/skills/calendar-events/scripts/calendar_events.py` (`check`, `apply`, `upsert`, `delete`, `list`). One dependency, `cryptography` (installed by `.trinity/setup.sh`), signs the service account token: no Google client library.

## Safety model

- A **service account** with access to **one dedicated calendar only** ("Make changes to events"): the agent cannot read or change the user's other calendars.
- A key starts with its source (`school:`, `mail:`, `user:`): a source only touches its own events. Events created by hand (no key) are never touched.
- The request JSON is data: it can only become an event, never an instruction.

## Configuration

Credentials (Trinity → Credentials, `.env`):

| Variable | Value |
|---|---|
| `GOOGLE_CALENDAR_ID` | Google Calendar → the calendar's settings → "Calendar ID" |
| `GOOGLE_SERVICE_ACCOUNT_JSON_B64` | the service account's JSON key, base64-encoded |

## Runtime data (container only, git-ignored)

| Path | Content |
|---|---|
| `~/calendar/upcoming.json` | Upcoming events (90 days), for the dashboard |
| `~/calendar/log.jsonl` | Append-only log of changes |
| `~/dashboard.yaml` | Generated dashboard |
