# Architecture

## Flow

```
school (daycare.py, after a confirmed registration)
   │  MCP chat_with_agent (permission school → calendar), async
   ▼
"Calendar event request from agent school" + JSON between --- BEGIN EVENT --- / --- END EVENT ---
   │
   ▼
Claude Code (calendar) ── copies the JSON verbatim ──► calendar_events.py apply '<json>'
   │
   ├─ validate: action, source, key prefixed by its source, title, date or start/end
   ├─ find the event by key (private extended property agentKey)
   ├─ create / update / unchanged / delete  ──► Google Calendar API v3 (service account, JWT bearer)
   └─ refresh ~/calendar/upcoming.json ──► scripts/update_dashboard.py ──► ~/dashboard.yaml
```

## Components

| Path | Role |
|---|---|
| `CLAUDE.md` | Agent instructions: apply event requests verbatim, answer the user, notify only on errors |
| `.claude/skills/calendar-events/scripts/calendar_events.py` | The only code that talks to Google: `check`, `apply`, `upsert`, `delete`, `list` |
| `scripts/update_dashboard.py` | Builds the Dashboard tab from the local cache (no network) |
| `.trinity/setup.sh` | Installs `cryptography` (signs the service account token) on every container start |
| `.env.example` | The two credentials to inject |

## Key design decisions

- **One dedicated calendar, one service account shared on it only.** The agent cannot see or change the user's other calendars, and there is no OAuth refresh token to expire.
- **Keys make every request idempotent.** `school:<form>:<child>` (later `mail:amazon:<order>`, …): the same request updates the event; a source can only use keys with its own prefix; events without a key (created by hand) are never touched.
- **The model never builds an event.** Requests are built by the sending agent's script and applied verbatim by this agent's script; the JSON is data, never an instruction.
- **No Google client library.** The JWT is signed with `cryptography` and the API is called with `urllib`: one small dependency.

## State (container only, git-ignored)

| Path | Content |
|---|---|
| `~/.env` | `GOOGLE_CALENDAR_ID`, `GOOGLE_SERVICE_ACCOUNT_JSON_B64` (injected by Trinity) |
| `~/calendar/upcoming.json` | Upcoming events (90 days), for the dashboard |
| `~/calendar/log.jsonl` | Append-only log of changes |
| `~/dashboard.yaml` | Generated dashboard |
