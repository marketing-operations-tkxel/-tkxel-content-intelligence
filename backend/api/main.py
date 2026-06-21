"""FastAPI app — reads from Postgres only. No BigQuery/Gmail/Sheets calls here.

Sync workers populate the tables; this layer just serves them.
"""
import os
import subprocess
import sys
import pathlib
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, Query, BackgroundTasks   # noqa: E402
from fastapi.middleware.cors import CORSMiddleware     # noqa: E402

from db.connection import get_cursor                   # noqa: E402

app = FastAPI(title="Tkxel Content Intelligence API", version="1.0.0")

origins = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Workers older than this many hours are flagged 'stale' on /api/status.
STALE_HOURS = 30


def _q(sql: str, params: tuple = ()):
    with get_cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def _region_clause(region: str | None, col: str = "region"):
    if region and region.lower() != "all":
        return f" AND {col} = %s", (region,)
    return "", ()


# ---------------------------------------------------------------------------
@app.get("/health")
def health():
    try:
        _q("SELECT 1")
        return {"status": "ok", "db": "up"}
    except Exception as e:
        return {"status": "degraded", "db": "down", "error": str(e)}


@app.get("/api/status")
def status():
    rows = _q("SELECT worker, last_run_at, last_ok_at, rows_written, status, message FROM sync_status")
    now = datetime.now(timezone.utc)
    out = []
    for r in rows:
        last_ok = r["last_ok_at"]
        stale = True
        if last_ok:
            stale = (now - last_ok) > timedelta(hours=STALE_HOURS)
        out.append({**r, "stale": stale})
    return {"workers": out, "as_of": now.isoformat()}


@app.post("/api/sync")
def sync(background_tasks: BackgroundTasks):
    """Trigger a manual full sync in the background (runs all three workers)."""
    def _run():
        base = pathlib.Path(__file__).resolve().parent.parent
        # inbound + mql first so the dashboard worker sees fresh lead/MQL data
        for w in ("sync_traffic", "sync_inbound", "sync_mql", "sync_dashboard"):
            subprocess.run([sys.executable, "-m", f"workers.{w}"], cwd=base, check=False)

    background_tasks.add_task(_run)
    return {"status": "started", "workers": ["traffic", "inbound", "mql", "dashboard"]}


@app.get("/api/v2/all")
def dashboard_all():
    """The full rich-dashboard payload, precomputed by sync_dashboard."""
    rows = _q("SELECT payload, to_char(updated_at,'DD Mon YYYY, HH24:MI') AS updated FROM dashboard_cache WHERE section='all'")
    if not rows:
        return {"ready": False}
    payload = rows[0]["payload"]
    payload["_updated"] = rows[0]["updated"]
    payload["ready"] = True
    return payload


@app.get("/api/regional")
def regional(
    region: str | None = Query(None),
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
):
    where, params = "WHERE 1=1", []
    rc, rp = _region_clause(region)
    where += rc
    params += list(rp)
    if from_:
        where += " AND month >= %s"
        params.append(f"{from_}-01")
    if to:
        where += " AND month <= %s"
        params.append(f"{to}-01")
    rows = _q(
        f"""SELECT region, to_char(month,'YYYY-MM') AS month,
                   sessions, users, engaged_sessions, conversions,
                   impressions, clicks, avg_position
            FROM regional_traffic {where}
            ORDER BY month, region""",
        tuple(params),
    )
    return {"rows": rows}


@app.get("/api/categories")
def categories(region: str | None = Query(None)):
    rc, rp = _region_clause(region)
    rows = _q(
        f"""SELECT region, category, sessions, users, conversions, pages
            FROM categories WHERE 1=1 {rc}
            ORDER BY sessions DESC""",
        rp,
    )
    return {"rows": rows}


@app.get("/api/top-pages")
def top_pages(
    category: str | None = Query(None),
    region: str | None = Query(None),
    limit: int = Query(50, le=200),
):
    where, params = "WHERE 1=1", []
    rc, rp = _region_clause(region)
    where += rc
    params += list(rp)
    if category and category.lower() != "all":
        where += " AND category = %s"
        params.append(category)
    params.append(limit)
    rows = _q(
        f"""SELECT region, category, page_path, page_title,
                   sessions, users, clicks, impressions, avg_position
            FROM top_pages {where}
            ORDER BY sessions DESC LIMIT %s""",
        tuple(params),
    )
    return {"rows": rows}


@app.get("/api/llm")
def llm(region: str | None = Query(None)):
    # LLM data is global only — region param accepted but ignored (documented).
    rows = _q(
        """SELECT source, page_path, to_char(month,'YYYY-MM') AS month,
                  sessions, users
           FROM llm_referrals ORDER BY sessions DESC"""
    )
    by_source = _q(
        """SELECT source, SUM(sessions) AS sessions, SUM(users) AS users
           FROM llm_referrals GROUP BY source ORDER BY sessions DESC"""
    )
    return {"rows": rows, "by_source": by_source, "scope": "global"}


@app.get("/api/gap")
def gap(region: str | None = Query(None), limit: int = Query(100, le=500)):
    rows = _q(
        """SELECT region, query, page_path, impressions, clicks, ctr,
                  avg_position, opportunity
           FROM content_gap ORDER BY opportunity DESC LIMIT %s""",
        (limit,),
    )
    return {"rows": rows}


@app.get("/api/inbound")
def inbound():
    summary = _q(
        """SELECT segment, COUNT(*) AS count
           FROM inbound_leads GROUP BY segment ORDER BY count DESC"""
    )
    genuine = _q(
        """SELECT email, description, domain, received_at
           FROM inbound_leads WHERE segment = 'Genuine'
           ORDER BY received_at DESC LIMIT 200"""
    )
    by_month = _q(
        """SELECT to_char(date_trunc('month', received_at),'YYYY-MM') AS month,
                  COUNT(*) FILTER (WHERE segment='Genuine') AS genuine,
                  COUNT(*) AS total
           FROM inbound_leads
           WHERE received_at IS NOT NULL
           GROUP BY 1 ORDER BY 1"""
    )
    return {"summary": summary, "genuine": genuine, "by_month": by_month}


@app.get("/api/mql")
def mql():
    rows = _q(
        """SELECT email, name, company, status, owner, matched_lead
           FROM mql_records ORDER BY matched_lead DESC, company NULLS LAST"""
    )
    matched = sum(1 for r in rows if r["matched_lead"])
    return {"rows": rows, "total": len(rows), "matched": matched}


@app.get("/api/funnel")
def funnel(
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
):
    # Global only — Pardot has no region field.
    iwhere, iparams = "WHERE received_at IS NOT NULL", []
    if from_:
        iwhere += " AND received_at >= %s"
        iparams.append(f"{from_}-01")
    if to:
        iwhere += " AND received_at < (%s::date + interval '1 month')"
        iparams.append(f"{to}-01")

    inbound_total = _q(f"SELECT COUNT(*) AS c FROM inbound_leads {iwhere}", tuple(iparams))[0]["c"]
    genuine = _q(
        f"SELECT COUNT(*) AS c FROM inbound_leads {iwhere} AND segment='Genuine'",
        tuple(iparams),
    )[0]["c"]
    mql_total = _q("SELECT COUNT(*) AS c FROM mql_records")[0]["c"]
    mql_matched = _q("SELECT COUNT(*) AS c FROM mql_records WHERE matched_lead = TRUE")[0]["c"]

    # Sessions (top of funnel) from regional_traffic over the same window.
    swhere, sparams = "WHERE 1=1", []
    if from_:
        swhere += " AND month >= %s"
        sparams.append(f"{from_}-01")
    if to:
        swhere += " AND month <= %s"
        sparams.append(f"{to}-01")
    sessions = _q(
        f"SELECT COALESCE(SUM(sessions),0) AS s FROM regional_traffic {swhere}",
        tuple(sparams),
    )[0]["s"]

    stages = [
        {"stage": "Sessions", "count": int(sessions)},
        {"stage": "Inbound Leads", "count": int(inbound_total)},
        {"stage": "Genuine Leads", "count": int(genuine)},
        {"stage": "MQLs", "count": int(mql_total)},
        {"stage": "Matched MQLs", "count": int(mql_matched)},
    ]
    return {"stages": stages, "scope": "global"}
