# Tkxel Content Intelligence

Full-stack marketing analytics dashboard for tkxel.com. Pulls live data from
**BigQuery** (GA4 + GSC), **Gmail** (Pardot Form Handler emails), and a
**Google Sheet** (SDR/MQL tracker), aggregates into **Postgres**, and serves it
through a **FastAPI** API to a **React** dashboard.

```
backend/   FastAPI API + 3 sync workers + Postgres schema   → Railway
frontend/  React + Vite + Recharts dashboard                → Vercel
```

## Architecture

- The API (`api/main.py`) **only reads Postgres** — fast, no external calls on request.
- Three cron workers populate Postgres on a daily schedule:
  - `sync_traffic.py` — BigQuery GA4 + GSC → `regional_traffic`, `categories`, `top_pages`, `llm_referrals`, `content_gap` (04:00 UTC)
  - `sync_inbound.py` — Gmail Pardot emails → `inbound_leads` (05:00 UTC)
  - `sync_mql.py` — Google Sheet SDR tracker → `mql_records`, matched against inbound (06:00 UTC)
- `POST /api/sync` runs all three on demand (the dashboard's Refresh button).

## Data sources

| Source     | Detail |
|------------|--------|
| BigQuery   | project `mkt-data-wh`, GA4 `analytics_407787656`, GSC `searchconsole_data`, property `https://tkxel.com/`, window floor `2026-01-01` |
| Google Sheet | ID `1kxfdC3yatbHCPe7TrZsKz3j8ErmBVqKQgtmFRFReTAg`, first tab, header row auto-detected (scans first 6 rows for `email`) |
| Gmail      | `from:info@pardot.com subject:"Pardot Form Handler"`, subject split on **last** ` - `, internal domains tagged, idempotent on `gmail_message_id` |

## Environment variables

**Railway** (backend) — Variables tab:

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | Auto-set by the Railway Postgres plugin |
| `GOOGLE_CREDENTIALS_JSON` | Service-account JSON (BigQuery + Sheets), one line |
| `GMAIL_CREDENTIALS_JSON` | OAuth2 token JSON (see `gmail_auth.py`) |
| `MQL_SHEET_ID` | `1kxfdC3yatbHCPe7TrZsKz3j8ErmBVqKQgtmFRFReTAg` |
| `ALLOWED_ORIGINS` | Vercel frontend URL, e.g. `https://tkxel-dashboard.vercel.app` |
| `INBOUND_WINDOW_DAYS` | Optional, default `180`. Lower on re-runs to speed up. |

**Vercel** (frontend) — Environment Variables:

| Variable | Description |
|----------|-------------|
| `VITE_API_URL` | Railway API URL, e.g. `https://tkxel-api.up.railway.app` |

> The API URL is read from `VITE_API_URL` at build time — there is **no
> placeholder to edit in `vercel.json`**. Just set the env var and redeploy.

## Credentials setup

### Service account (BigQuery + Sheets)
1. GCP Console → IAM → Service Accounts → Create.
2. Roles: **BigQuery Data Viewer**, **BigQuery Job User**.
3. Download the JSON key.
4. Share the MQL Sheet with the service-account email (Viewer).
5. Paste the whole JSON as `GOOGLE_CREDENTIALS_JSON` in Railway (one line).

### Gmail OAuth2 token
Run `backend/gmail_auth.py` locally once (needs `oauth_client.json` from a
GCP OAuth Desktop client) and paste the output as `GMAIL_CREDENTIALS_JSON`.

## Deploy

### 1. Railway (backend)
```bash
cd backend
railway login
railway init
railway add --database postgres
railway variables --set GOOGLE_CREDENTIALS_JSON="..."
railway variables --set GMAIL_CREDENTIALS_JSON="..."
railway variables --set MQL_SHEET_ID="1kxfdC3yatbHCPe7TrZsKz3j8ErmBVqKQgtmFRFReTAg"
railway variables --set ALLOWED_ORIGINS="https://YOUR-APP.vercel.app"
railway up
```

Init the DB once:
```bash
railway run python -c "from db.connection import execute_schema; execute_schema()"
```

First sync (don't wait for cron):
```bash
railway run python -m workers.sync_traffic
railway run python -m workers.sync_inbound
railway run python -m workers.sync_mql
```

**Cron workers** — create three more Railway services in the same project,
each with the shared variables and a custom Start Command + Cron Schedule:

| Service | Start Command | Cron |
|---------|---------------|------|
| sync-traffic | `python -m workers.sync_traffic` | `0 4 * * *` |
| sync-inbound | `python -m workers.sync_inbound` | `0 5 * * *` |
| sync-mql | `python -m workers.sync_mql` | `0 6 * * *` |

### 2. Vercel (frontend)
```bash
cd frontend
npm install
vercel --prod
# then in the Vercel dashboard set:
#   VITE_API_URL = https://your-railway-url.up.railway.app
vercel --prod   # redeploy so the env var is baked in
```

## Local development
```bash
# backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL=postgresql://localhost/tkxel
python -c "from db.connection import execute_schema; execute_schema()"
uvicorn api.main:app --reload   # http://localhost:8000

# frontend (new terminal)
cd frontend
npm install
npm run dev                      # http://localhost:5173  (defaults API to :8000)
```

## API endpoints

| Method | Path | Notes |
|--------|------|-------|
| GET  | `/health` | DB health check |
| GET  | `/api/status` | sync timestamps + stale flags |
| POST | `/api/sync` | trigger full sync (background) |
| GET  | `/api/regional` | `?region=&from=2026-01&to=2026-06` |
| GET  | `/api/categories` | `?region=` |
| GET  | `/api/top-pages` | `?category=&region=&limit=` |
| GET  | `/api/llm` | global only |
| GET  | `/api/gap` | `?limit=` |
| GET  | `/api/inbound` | summary + genuine leads + by-month |
| GET  | `/api/mql` | matched MQL records |
| GET  | `/api/funnel` | `?from=&to=` global only |

## Notes / known constraints
- LLM traffic and the inbound funnel are **global only** (region is too sparse / Pardot has no region field).
- `sync_mql.py` re-reads and re-matches the sheet every run — tracker edits propagate automatically.
- Workers older than 30h are flagged `stale` on `/api/status` and surfaced in the dashboard header.
