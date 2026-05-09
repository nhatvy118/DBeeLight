# Google Sheets MCP Server

Per-user Google Sheets / Drive **read** access for the agent.

## Architecture

```
                                  ┌────────────────────┐
   App user (logged in via        │  api-server        │
   Google OAuth in the app)  ───► │  /api/chat         │
                                  │                    │
                                  │  spawns per user:  │
                                  │  ┌──────────────┐  │
                                  │  │ gsheets-server│ │  env: USER_GOOGLE_SUB={sub}
                                  │  │ (this MCP)   │  │       DATABASE_URL=...
                                  │  └──────┬───────┘  │       GOOGLE_CLIENT_*
                                  └─────────┼──────────┘       TOKEN_ENCRYPTION_KEY
                                            │
                                            ▼
                                   ┌────────────────┐
                                   │  Postgres      │
                                   │  users.google_*│  (encrypted refresh_token)
                                   └────┬───────────┘
                                        │
                                        ▼
                                   Google Sheets API
```

The server is **per-user-aware**: every spawn is tagged with `USER_GOOGLE_SUB`
(passed by `base_agent.connect_to_server`'s env injection). Tools look up that
user's tokens in Postgres on every call, refresh if expired, and call the
Sheets/Drive APIs on the user's behalf.

## Install

```bash
cd gsheets-server
uv sync
```

## Required env vars (set in `api-server/.env`)

| Var | Why |
|---|---|
| `USER_GOOGLE_SUB` | Identifies which app user this spawn speaks for. Set by parent at spawn time, not in `.env`. |
| `DATABASE_URL` (or `DB_URL`) | Read encrypted tokens from `users` table |
| `GOOGLE_CLIENT_ID` | Refresh access tokens (matches what login uses) |
| `GOOGLE_CLIENT_SECRET` | Refresh access tokens |
| `TOKEN_ENCRYPTION_KEY` | Fernet key — same value the api-server uses |

## Tools (2)

| Tool | Description |
|---|---|
| `get_spreadsheet_info(spreadsheet_id)` | List sheet tabs + dimensions |
| `read_google_sheet(spreadsheet_id, range)` | Read cell values (default range `A1:Z1000`) |

Read-only. The user must paste a sheet URL or ID — there's intentionally
no Drive search tool.

## Required Google scopes

User must grant these at OAuth login (configured in
`api-server/internal/repositories/google_oauth_repository.py`):

- `https://www.googleapis.com/auth/spreadsheets.readonly`

We deliberately don't request `drive.readonly` because it's a Google
**restricted** scope — adding it would require a CASA security audit
to publish. With only `spreadsheets.readonly` (sensitive, not
restricted) the path to "Production" is much lighter.

If a user logged in **before** this scope was added, they need to
re-login (Google will show a fresh consent screen).
