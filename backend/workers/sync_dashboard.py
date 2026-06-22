"""sync_dashboard — compute every breakdown the rich dashboard needs and cache
it as a single JSON blob in dashboard_cache('all').

Sources: GA4 + GSC (BigQuery) and inbound_leads / mql_records (Postgres).
Runs all queries best-effort: a failing section logs and leaves a safe default
so the rest of the dashboard still renders.
"""
import json
import os
import sys
import pathlib
import traceback
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from workers.bq_client import get_client, PROJECT, GA4_DATASET, GSC_DATASET, WINDOW_START  # noqa: E402
from workers.regions_v2 import (  # noqa: E402
    GA4_REGION_CASE, GSC_REGION_CASE, CATEGORY_CASE, LLM_SOURCE_CASE,
    REGIONS, LLM_SOURCES, MONTHS,
)
from db.connection import get_cursor, mark_sync  # noqa: E402

SUFFIX = WINDOW_START.replace("-", "")
CONV_EVENT = "form_submit"

# Reusable GA4 per-event projection (region, month, session key, page path, category, source, engaged)
GA4_EV = f"""
  SELECT
    {GA4_REGION_CASE} AS region,
    FORMAT_DATE('%b', PARSE_DATE('%Y%m%d', event_date)) AS mon,
    DATE_TRUNC(PARSE_DATE('%Y%m%d', event_date), MONTH) AS month,
    CONCAT(user_pseudo_id, '_', CAST((SELECT value.int_value FROM UNNEST(event_params) WHERE key='ga_session_id') AS STRING)) AS sess,
    user_pseudo_id AS uid,
    event_name,
    REGEXP_REPLACE(REGEXP_REPLACE((SELECT value.string_value FROM UNNEST(event_params) WHERE key='page_location'), r'^https?://[^/]+', ''), r'[?#].*$', '') AS p,
    (SELECT value.string_value FROM UNNEST(event_params) WHERE key='page_title') AS title,
    ((SELECT value.string_value FROM UNNEST(event_params) WHERE key='session_engaged') = '1') AS engaged,
    LOWER(COALESCE((SELECT value.string_value FROM UNNEST(event_params) WHERE key='source'), collected_traffic_source.manual_source, '')) AS h
  FROM `{PROJECT}.{GA4_DATASET}.events_*`
  WHERE _TABLE_SUFFIX >= '{SUFFIX}'
"""

GSC_URL = f"""
  SELECT {GSC_REGION_CASE} AS region,
    REGEXP_REPLACE(REGEXP_REPLACE(url, r'^https?://[^/]+', ''), r'[?#].*$', '') AS p,
    impressions, clicks, sum_position
  FROM `{PROJECT}.{GSC_DATASET}.searchdata_url_impression`
  WHERE data_date >= '{WINDOW_START}'
"""

# Same as GSC_URL but carries the month label so sections can be date-sliced.
GSC_URL_M = f"""
  SELECT {GSC_REGION_CASE} AS region,
    FORMAT_DATE('%b', data_date) AS mon,
    REGEXP_REPLACE(REGEXP_REPLACE(url, r'^https?://[^/]+', ''), r'[?#].*$', '') AS p,
    impressions, clicks, sum_position
  FROM `{PROJECT}.{GSC_DATASET}.searchdata_url_impression`
  WHERE data_date >= '{WINDOW_START}'
"""


def _months(client):
    """Canonical ordered list of month labels present in GA4 (Jan, Feb, ...)."""
    rows = run(client, f"""
      SELECT DISTINCT FORMAT_DATE('%b', PARSE_DATE('%Y%m%d', event_date)) AS mon,
             DATE_TRUNC(PARSE_DATE('%Y%m%d', event_date), MONTH) AS month
      FROM `{PROJECT}.{GA4_DATASET}.events_*` WHERE _TABLE_SUFFIX >= '{SUFFIX}'
      ORDER BY month
    """)
    return [r["mon"] for r in rows]


def run(client, sql):
    return [dict(r) for r in client.query(sql).result()]


# ───────────────────────── GA4 / GSC sections ─────────────────────────
def traffic_sections(client):
    """REGION_MONTHLY, MONTHLY, VIEWS_BY_REGION from GA4 + GSC."""
    ga = run(client, f"""
      SELECT region, mon, month,
        COUNT(DISTINCT sess) AS sessions,
        COUNT(DISTINCT uid) AS users,
        COUNTIF(event_name='page_view') AS views,
        COUNTIF(event_name='{CONV_EVENT}') AS conv,
        COUNT(DISTINCT IF(engaged, sess, NULL)) AS engaged
      FROM ({GA4_EV})
      GROUP BY region, mon, month
    """)
    gsc = run(client, f"""
      SELECT {GSC_REGION_CASE} AS region,
        FORMAT_DATE('%b', data_date) AS mon, DATE_TRUNC(data_date, MONTH) AS month,
        SUM(impressions) AS impr, SUM(clicks) AS clicks,
        SAFE_DIVIDE(SUM(sum_top_position), SUM(impressions)) + 1 AS pos
      FROM `{PROJECT}.{GSC_DATASET}.searchdata_site_impression`
      WHERE data_date >= '{WINDOW_START}'
      GROUP BY region, mon, month
    """)
    months = sorted({r["month"] for r in ga}, key=lambda d: d)
    mlabels = [m.strftime("%b") for m in months]
    gsc_map = {(r["region"], r["mon"]): r for r in gsc}
    ga_map = {(r["region"], r["mon"]): r for r in ga}

    region_monthly = {}
    for reg in REGIONS:
        rows = []
        for m, ml in zip(months, mlabels):
            g = ga_map.get((reg, ml), {})
            s = gsc_map.get((reg, ml), {})
            rows.append({
                "s": int(g.get("sessions") or 0), "u": int(g.get("users") or 0),
                "v": int(g.get("views") or 0), "e": int(g.get("engaged") or 0),
                "c": int(g.get("conv") or 0), "im": int(s.get("impr") or 0),
                "ck": int(s.get("clicks") or 0), "p": round(float(s.get("pos") or 0), 1),
            })
        region_monthly[reg] = rows

    monthly, views_by_region = [], []
    for i, ml in enumerate(mlabels):
        agg = {"sessions": 0, "views": 0, "clicks": 0, "impr": 0, "conv": 0}
        vbr = {"m": ml}
        for reg in REGIONS:
            r = region_monthly[reg][i]
            agg["sessions"] += r["s"]; agg["views"] += r["v"]; agg["clicks"] += r["ck"]
            agg["impr"] += r["im"]; agg["conv"] += r["c"]
            vbr[reg] = r["v"]
        monthly.append({"m": ml, **agg, "llm": 0})  # llm filled later
        views_by_region.append(vbr)
    return region_monthly, monthly, views_by_region, mlabels


def _blank(n):
    return [{"v": 0, "s": 0, "e": 0, "im": 0, "ck": 0, "sp": 0} for _ in range(n)]


def categories_section(client, mlabels):
    """CATEGORIES_MONTHLY: {region: {cat: [per-month raw metrics]}} — frontend sums
    selected months and derives ctr/pos/eng. Region 'All' is summed client-side."""
    idx = {m: i for i, m in enumerate(mlabels)}
    n = len(mlabels)
    ga = run(client, f"""
      SELECT region, category, mon,
        COUNTIF(event_name='page_view') AS views,
        COUNT(DISTINCT sess) AS sessions,
        COUNT(DISTINCT IF(engaged, sess, NULL)) AS eng_sess
      FROM (SELECT region, mon, sess, event_name, engaged, {CATEGORY_CASE} AS category FROM ({GA4_EV}))
      GROUP BY region, category, mon
    """)
    gsc = run(client, f"""
      SELECT region, category, mon, SUM(impressions) AS impr, SUM(clicks) AS clicks, SUM(sum_position) AS sp
      FROM (SELECT region, mon, {CATEGORY_CASE} AS category, impressions, clicks, sum_position FROM ({GSC_URL_M}))
      GROUP BY region, category, mon
    """)
    out = {r: {} for r in REGIONS}

    def slot(region, cat):
        return out[region].setdefault(cat, _blank(n))

    for r in ga:
        if r["region"] not in out or r["mon"] not in idx:
            continue
        c = slot(r["region"], r["category"])[idx[r["mon"]]]
        c["v"] += int(r["views"] or 0); c["s"] += int(r["sessions"] or 0); c["e"] += int(r["eng_sess"] or 0)
    for r in gsc:
        if r["region"] not in out or r["mon"] not in idx:
            continue
        c = slot(r["region"], r["category"])[idx[r["mon"]]]
        c["im"] += int(r["impr"] or 0); c["ck"] += int(r["clicks"] or 0); c["sp"] += float(r["sp"] or 0)
    return out


def toppages_section(client, mlabels):
    """TOPPAGES_MONTHLY: [{cat, region, url, title, m:[per-month raw metrics]}]."""
    idx = {m: i for i, m in enumerate(mlabels)}
    n = len(mlabels)
    ga = run(client, f"""
      SELECT region, category, url, mon, ANY_VALUE(title) AS title,
        COUNTIF(event_name='page_view') AS views,
        COUNT(DISTINCT sess) AS sessions,
        COUNT(DISTINCT IF(engaged, sess, NULL)) AS eng_sess
      FROM (SELECT region, mon, sess, event_name, engaged, p AS url, title, {CATEGORY_CASE} AS category FROM ({GA4_EV}) WHERE p != '' AND p != '/')
      GROUP BY region, category, url, mon
    """)
    gsc = run(client, f"""
      SELECT region, p AS url, mon, SUM(impressions) AS impr, SUM(clicks) AS clicks, SUM(sum_position) AS sp
      FROM ({GSC_URL_M})
      GROUP BY region, url, mon
    """)
    pages = {}

    def slot(region, cat, url):
        key = (region, cat, url)
        if key not in pages:
            pages[key] = {"cat": cat, "region": region, "url": url, "title": None, "m": _blank(n)}
        return pages[key]

    for r in ga:
        if r["mon"] not in idx:
            continue
        p = slot(r["region"], r["category"], r["url"])
        if r.get("title"):
            p["title"] = r["title"]
        c = p["m"][idx[r["mon"]]]
        c["v"] += int(r["views"] or 0); c["s"] += int(r["sessions"] or 0); c["e"] += int(r["eng_sess"] or 0)
    # GSC has no category; attach to any matching (region,url) page rows
    gsc_by = {}
    for r in gsc:
        if r["mon"] not in idx:
            continue
        gsc_by.setdefault((r["region"], r["url"]), []).append(r)
    for (region, cat, url), p in pages.items():
        for r in gsc_by.get((region, url), []):
            c = p["m"][idx[r["mon"]]]
            c["im"] += int(r["impr"] or 0); c["ck"] += int(r["clicks"] or 0); c["sp"] += float(r["sp"] or 0)
    # keep top 8 per (category, region) by total views
    rows = list(pages.values())
    for p in rows:
        p["_tv"] = sum(c["v"] for c in p["m"])
    seen, out = {}, []
    for p in sorted(rows, key=lambda x: -x["_tv"]):
        key = (p["cat"], p["region"])
        if seen.get(key, 0) < 8:
            seen[key] = seen.get(key, 0) + 1
            out.append({kk: vv for kk, vv in p.items() if kk != "_tv"})
    return out


def gap_section(client, mlabels):
    """GAP_MONTHLY: {region: {url: [per-month {im,ck,sp}]}} incl 'All' (global)."""
    idx = {m: i for i, m in enumerate(mlabels)}
    n = len(mlabels)
    rows = run(client, f"""
      SELECT region, p AS url, mon, SUM(impressions) AS impr, SUM(clicks) AS clicks, SUM(sum_position) AS sp
      FROM ({GSC_URL_M}) WHERE p != ''
      GROUP BY region, url, mon
    """)
    buckets = {"All": {}, **{r: {} for r in REGIONS}}

    def slot(scope, url):
        return buckets[scope].setdefault(url, _blank(n))

    for r in rows:
        if r["mon"] not in idx:
            continue
        im = int(r["impr"] or 0); ck = int(r["clicks"] or 0); sp = float(r["sp"] or 0)
        for scope in ("All", r["region"]):
            if scope not in buckets:
                continue
            c = slot(scope, r["url"])[idx[r["mon"]]]
            c["im"] += im; c["ck"] += ck; c["sp"] += sp
    # cap each scope to the top ~25 urls by total impressions to bound payload
    out = {}
    for scope, urls in buckets.items():
        ranked = sorted(urls.items(), key=lambda kv: -sum(c["im"] for c in kv[1]))[:25]
        out[scope] = {u: arr for u, arr in ranked if sum(c["im"] for c in arr) >= 300}
    return out


def llm_sections(client):
    """All LLM breakdowns from one windowed base (session-tagged by LLM source)."""
    base = f"""
      WITH tagged AS (
        SELECT region, mon, sess, event_name, p,
          {CATEGORY_CASE} AS category, ({LLM_SOURCE_CASE}) AS src
        FROM ({GA4_EV})
      ),
      sess_src AS (
        SELECT region, mon, sess, event_name, p, category,
          MAX(src) OVER (PARTITION BY sess) AS ssrc
        FROM tagged
      )
      SELECT * FROM sess_src WHERE ssrc IS NOT NULL
    """
    # region x month (sessions + conv)
    rm = run(client, f"""
      WITH t AS ({base})
      SELECT region, mon, COUNT(DISTINCT sess) AS s, COUNTIF(event_name='{CONV_EVENT}') AS c
      FROM t GROUP BY region, mon
    """)
    # source x region x month (sessions)
    srm = run(client, f"""
      WITH t AS ({base})
      SELECT ssrc AS src, region, mon, COUNT(DISTINCT sess) AS s
      FROM t GROUP BY src, region, mon
    """)
    # category x region (sessions + conv)
    cr = run(client, f"""
      WITH t AS ({base})
      SELECT region, category, COUNT(DISTINCT sess) AS s, COUNTIF(event_name='{CONV_EVENT}') AS c
      FROM t GROUP BY region, category
    """)
    # by page (sessions + conv + top source)
    pg = run(client, f"""
      WITH t AS ({base})
      SELECT p AS url, COUNT(DISTINCT sess) AS s, COUNTIF(event_name='{CONV_EVENT}') AS c,
        ANY_VALUE(ssrc) AS top
      FROM t GROUP BY p ORDER BY s DESC LIMIT 15
    """)

    months = sorted({r["mon"] for r in srm}, key=lambda m: MONTHS.index(m) if m in MONTHS else 99)

    # LLM_MONTHLY_ALL [{m, ChatGPT,...}]
    monthly_all = []
    for m in months:
        row = {"m": m}
        for src in LLM_SOURCES:
            row[src] = sum(int(r["s"] or 0) for r in srm if r["mon"] == m and r["src"] == src)
        monthly_all.append(row)

    # LLM_REGION_MONTHLY {region: [{s,c}...]}
    region_monthly = {}
    rm_map = {(r["region"], r["mon"]): r for r in rm}
    for reg in REGIONS:
        region_monthly[reg] = [{"s": int(rm_map.get((reg, m), {}).get("s") or 0),
                                "c": int(rm_map.get((reg, m), {}).get("c") or 0)} for m in months]

    # LLM_SOURCE_BY_REGION {region: [{src, sessions}...]}
    source_by_region = {}
    for reg in REGIONS:
        lst = [{"src": src, "sessions": sum(int(r["s"] or 0) for r in srm if r["region"] == reg and r["src"] == src)}
               for src in LLM_SOURCES]
        source_by_region[reg] = sorted([x for x in lst if x["sessions"] > 0], key=lambda x: -x["sessions"]) or lst

    # LLM_CATEGORY_BY_REGION {All/region: [{cat, sessions, conv}]}
    def cat_build(region_filter):
        agg = {}
        for r in cr:
            if region_filter and r["region"] != region_filter:
                continue
            a = agg.setdefault(r["category"], {"sessions": 0, "conv": 0})
            a["sessions"] += int(r["s"] or 0); a["conv"] += int(r["c"] or 0)
        return sorted([{"cat": k, **v} for k, v in agg.items()], key=lambda x: -x["sessions"])
    category_by_region = {"All": cat_build(None), **{reg: cat_build(reg) for reg in REGIONS}}

    by_page = [{"url": r["url"] or "/", "sessions": int(r["s"] or 0), "conv": int(r["c"] or 0), "top": r["top"]} for r in pg]

    totals = {"sessions": sum(int(r["s"] or 0) for r in rm), "conv": sum(int(r["c"] or 0) for r in rm)}
    contact = next((p for p in by_page if "contact" in (p["url"] or "")), None)
    lead_signal = {"events": contact["conv"] if contact else 0, "matchedToPardotLead": 0}

    return {
        "LLM_MONTHLY_ALL": monthly_all, "LLM_REGION_MONTHLY": region_monthly,
        "LLM_SOURCE_BY_REGION": source_by_region, "LLM_CATEGORY_BY_REGION": category_by_region,
        "LLM_BY_PAGE": by_page, "LLM_LEAD_SIGNAL": lead_signal, "_totals": totals,
    }, months


# ───────────────────────── Velocity model (GA4 + GSC) ─────────────────────────
def velocity_section(client):
    """Real inputs for the Content Performance & Velocity model:
    baseline organic sessions, avg organic sessions per matured article (a),
    optimization inventory + per-page uplift, and the ranked action list."""
    om = run(client, f"""
      SELECT FORMAT_DATE('%b', PARSE_DATE('%Y%m%d', event_date)) AS mon,
        MIN(PARSE_DATE('%Y%m%d', event_date)) AS ord,
        COUNT(DISTINCT IF(LOWER(collected_traffic_source.manual_medium)='organic',
          CONCAT(user_pseudo_id,'_',CAST((SELECT value.int_value FROM UNNEST(event_params) WHERE key='ga_session_id') AS STRING)), NULL)) AS organic
      FROM `{PROJECT}.{GA4_DATASET}.events_*` WHERE _TABLE_SUFFIX >= '{SUFFIX}'
      GROUP BY mon ORDER BY ord
    """)
    organic_monthly = [{"m": r["mon"], "organic": int(r["organic"] or 0)} for r in om]
    recent = [x["organic"] for x in organic_monthly[-3:]] or [0]
    baseline = round(sum(recent) / max(1, len(recent)))

    arow = run(client, f"""
      WITH pv AS (
        SELECT REGEXP_REPLACE(REGEXP_REPLACE((SELECT value.string_value FROM UNNEST(event_params) WHERE key='page_location'),r'^https?://[^/]+',''),r'[?#].*$','') AS p,
          DATE_TRUNC(PARSE_DATE('%Y%m%d',event_date),MONTH) AS month,
          CONCAT(user_pseudo_id,'_',CAST((SELECT value.int_value FROM UNNEST(event_params) WHERE key='ga_session_id') AS STRING)) AS sess
        FROM `{PROJECT}.{GA4_DATASET}.events_*`
        WHERE _TABLE_SUFFIX>='{SUFFIX}' AND event_name='page_view' AND LOWER(collected_traffic_source.manual_medium)='organic'
      ),
      blog AS (SELECT * FROM pv WHERE REGEXP_CONTAINS(p, r'^/blog/[a-z]')),
      pam AS (SELECT p, month, COUNT(DISTINCT sess) s FROM blog GROUP BY p, month),
      pa AS (SELECT p, AVG(s) avg_monthly FROM pam GROUP BY p HAVING SUM(s) >= 6)
      SELECT COUNT(*) n, ROUND(APPROX_QUANTILES(avg_monthly,100)[OFFSET(50)],1) med, ROUND(AVG(avg_monthly),1) mean FROM pa
    """)[0]

    # optimization opportunity: pages below page 1 / weak CTR, monthly click uplift at 4% target CTR
    opp = f"""
      SELECT p, pos, m_impr, m_clicks, GREATEST(0, m_impr*0.04 - m_clicks) AS uplift,
        CASE WHEN pos < 4 THEN 'CTR fix' WHEN pos <= 15 THEN 'Striking distance' ELSE 'Page 2-3 push' END AS play
      FROM (
        SELECT REGEXP_REPLACE(REGEXP_REPLACE(url,r'^https?://[^/]+',''),r'[?#].*$','') AS p,
          SUM(impressions)/6.0 AS m_impr, SUM(clicks)/6.0 AS m_clicks,
          SAFE_DIVIDE(SUM(sum_position),SUM(impressions))+1 AS pos
        FROM `{PROJECT}.{GSC_DATASET}.searchdata_url_impression` WHERE data_date>='{WINDOW_START}' GROUP BY p
      )
      WHERE pos < 20 AND m_impr >= 100 AND (m_clicks/NULLIF(m_impr,0)) < 0.03
    """
    inv = run(client, f"SELECT COUNT(*) n, ROUND(SUM(uplift),0) total FROM ({opp})")[0]
    acts = run(client, f"""
      SELECT p AS url, ROUND(pos,1) AS pos, ROUND(m_impr,0) AS monthly_impr,
        ROUND(m_clicks/NULLIF(m_impr,0)*100,2) AS ctr, ROUND(uplift,0) AS uplift, play
      FROM ({opp}) ORDER BY uplift DESC LIMIT 15
    """)
    top10 = run(client, f"""
      SELECT ROUND(SUM(IF(rn<=10,uplift,0)),0) t10, ROUND(SUM(IF(rn<=20,uplift,0)),0) t20
      FROM (SELECT uplift, ROW_NUMBER() OVER (ORDER BY uplift DESC) rn FROM ({opp}))
    """)[0]

    return {
        "baseline": baseline,
        "organic_monthly": organic_monthly,
        "a_median": float(arow["med"] or 0), "a_mean": float(arow["mean"] or 0), "a_articles": int(arow["n"] or 0),
        "inventory": int(inv["n"] or 0), "inventory_uplift": float(inv["total"] or 0),
        "engineA_top10": float(top10["t10"] or 0), "engineA_top20": float(top10["t20"] or 0),
        "actions": [{"url": a["url"], "pos": float(a["pos"] or 0), "monthly_impr": int(a["monthly_impr"] or 0),
                     "ctr": float(a["ctr"] or 0), "uplift": int(a["uplift"] or 0), "play": a["play"]} for a in acts],
    }


# ───────────────────────── Inbound (Postgres) ─────────────────────────
TYPE_RULES = [
    ("webinar", "Webinar"), ("contact", "Contact Us"), ("white paper", "White Paper"),
    ("whitepaper", "White Paper"), ("e-book", "eBook"), ("ebook", "eBook"), ("playbook", "eBook"),
    ("guide", "eBook"), ("report", "Report"), ("case study", "Case Study"),
    ("panel", "Panel Talk"), ("newsletter", "Newsletter"), ("subscribe", "Newsletter"),
]


def classify_type(desc):
    d = (desc or "").lower()
    for kw, label in TYPE_RULES:
        if kw in d:
            return label
    return "Other"


def inbound_sections():
    with get_cursor() as cur:
        cur.execute("SELECT segment, COUNT(*) n FROM inbound_leads GROUP BY segment")
        segs = {r["segment"]: int(r["n"]) for r in cur.fetchall()}
        cur.execute("SELECT description FROM inbound_leads WHERE segment='Genuine'")
        genuine = [r["description"] for r in cur.fetchall()]
        cur.execute("SELECT COUNT(*) total, COUNT(*) FILTER (WHERE matched_lead) matched FROM mql_records")
        mq = cur.fetchone()
        cur.execute("SELECT COUNT(*) c FROM mql_records WHERE status ILIKE ANY(ARRAY['%qualif%','%won%','%convert%','%closed%'])")
        converted = int(cur.fetchone()["c"])

    total_sub = sum(segs.values())
    genuine_n = segs.get("Genuine", 0)

    by_type = {}
    asset_count = {}
    for desc in genuine:
        t = classify_type(desc)
        by_type[t] = by_type.get(t, 0) + 1
        key = (desc or "").strip()[:60] or "(blank)"
        asset_count[key] = asset_count.get(key, 0) + 1
    palette = {"Webinar": "#2E6B57", "Contact Us": "#4A6585", "White Paper": "#B0823A",
               "eBook": "#B0823A", "Report": "#B0823A", "Case Study": "#4A6585",
               "Panel Talk": "#A8A296", "Newsletter": "#A8A296", "Other": "#A8A296"}
    genuine_by_type = sorted(
        [{"type": t, "leads": n, "color": palette.get(t, "#A8A296")} for t, n in by_type.items()],
        key=lambda x: -x["leads"])

    lead_pages = []
    for asset, n in sorted(asset_count.items(), key=lambda kv: -kv[1])[:12]:
        t = classify_type(asset)
        lead_pages.append({"asset": asset, "type": t, "leads": n,
                           "url": None, "views": None, "clicks": 0,
                           "mql": int(mq["matched"]) if t == "Contact Us" else 0})

    segments = [
        {"k": "Genuine", "v": genuine_n, "c": "#2E6B57"},
        {"k": "Internal / test", "v": segs.get("Internal", 0), "c": "#4A6585"},
        {"k": "Spam", "v": segs.get("Spam", 0), "c": "#B5462F"},
    ]
    return {
        "total_sub": total_sub, "genuine": genuine_n,
        "mqls": int(mq["total"]), "converted": converted,
        "GENUINE_BY_TYPE": genuine_by_type, "LEAD_PAGES": lead_pages,
        "INBOUND_SEGMENTS": segments,
    }


# ───────────────────────── assemble ─────────────────────────
def run_all():
    client = get_client()
    out = {}
    errors = []

    def safe(name, fn):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {e}")
            traceback.print_exc()
            return None

    mlabels = safe("months", lambda: _months(client)) or []
    out["MONTHS"] = mlabels

    tr = safe("traffic", lambda: traffic_sections(client))
    if tr:
        region_monthly, monthly, views_by_region, _ = tr
        out["REGION_MONTHLY"] = region_monthly
        out["MONTHLY"] = monthly
        out["VIEWS_BY_REGION"] = views_by_region

    out["CATEGORIES_MONTHLY"] = safe("categories", lambda: categories_section(client, mlabels)) or {}
    out["TOPPAGES_MONTHLY"] = safe("toppages", lambda: toppages_section(client, mlabels)) or []
    out["GAP_MONTHLY"] = safe("gap", lambda: gap_section(client, mlabels)) or {}

    llm = safe("llm", lambda: llm_sections(client))
    if llm:
        llm_data, months = llm
        totals = llm_data.pop("_totals")
        out.update(llm_data)
        # backfill MONTHLY.llm from LLM_MONTHLY_ALL
        if "MONTHLY" in out:
            lmap = {r["m"]: sum(r.get(s, 0) for s in LLM_SOURCES) for r in llm_data["LLM_MONTHLY_ALL"]}
            for r in out["MONTHLY"]:
                r["llm"] = lmap.get(r["m"], 0)
        llm_funnel = {"sessions": totals["sessions"], "convEvents": totals["conv"],
                      "signalEvents": llm_data["LLM_LEAD_SIGNAL"]["events"]}
        out["LLM_FUNNEL"] = llm_funnel

    inb = safe("inbound", inbound_sections) or {}
    out["GENUINE_BY_TYPE"] = inb.get("GENUINE_BY_TYPE", [])
    out["LEAD_PAGES"] = inb.get("LEAD_PAGES", [])
    out["INBOUND_SEGMENTS"] = inb.get("INBOUND_SEGMENTS", [])

    # FUNNEL (Overview + Inbound headline)
    sess_total = sum(r["sessions"] for r in out.get("MONTHLY", [])) or 0
    conv_total = sum(r["conv"] for r in out.get("MONTHLY", [])) or 0
    out["FUNNEL"] = [
        {"label": "Sessions", "value": sess_total, "sub": "GA4 · all markets", "icon": "Users"},
        {"label": "Form Submits", "value": conv_total, "sub": "GA4 conversion events", "icon": "MousePointerClick"},
        {"label": "Pardot Submissions", "value": inb.get("total_sub", 0), "sub": "Form Handler emails", "icon": "FileText"},
        {"label": "Genuine Leads", "value": inb.get("genuine", 0), "sub": "external · non-spam", "icon": "Users"},
        {"label": "MQLs", "value": inb.get("mqls", 0), "sub": "matched to SDR tracker", "icon": "Target"},
        {"label": "Converted", "value": inb.get("converted", 0), "sub": "qualified / won", "icon": "CircleCheck"},
    ]

    # Velocity model inputs (real GA4/GSC + conversion/leads)
    vel = safe("velocity", lambda: velocity_section(client))
    if vel:
        cr = (conv_total / sess_total) if sess_total else 0
        # genuine leads per month over the window
        n_months = max(1, len(out.get("MONTHLY", [])) or 1)
        leads_pm = round(inb.get("genuine", 0) / n_months, 1)
        vel["conversion_rate"] = round(cr, 4)
        vel["leads_per_month"] = leads_pm
        vel["mqls_total"] = inb.get("mqls", 0)
        out["VELOCITY"] = vel

    out["asOf"] = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")
    out["_errors"] = errors
    return out


def main():
    mark_sync("dashboard", "running")
    try:
        payload = run_all()
        with get_cursor(dict_rows=False) as cur:
            cur.execute("""
                INSERT INTO dashboard_cache (section, payload, updated_at)
                VALUES ('all', %s, NOW())
                ON CONFLICT (section) DO UPDATE SET payload=EXCLUDED.payload, updated_at=NOW()
            """, (json.dumps(payload),))
        n_err = len(payload.get("_errors", []))
        msg = "dashboard complete" + (f" ({n_err} section errors)" if n_err else "")
        mark_sync("dashboard", "ok", rows=1, message=msg)
        print(msg, "| errors:", payload.get("_errors"))
    except Exception as e:  # noqa: BLE001
        mark_sync("dashboard", "error", message=str(e)[:200])
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
