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


def categories_section(client):
    ga = run(client, f"""
      SELECT region, category,
        COUNTIF(event_name='page_view') AS views,
        COUNT(DISTINCT sess) AS sessions,
        COUNT(DISTINCT IF(engaged, sess, NULL)) AS eng_sess
      FROM (SELECT region, sess, event_name, engaged, {CATEGORY_CASE} AS category FROM ({GA4_EV}))
      GROUP BY region, category
    """)
    gsc = run(client, f"""
      SELECT region, category, SUM(impressions) AS impr, SUM(clicks) AS clicks,
        SAFE_DIVIDE(SUM(sum_position), SUM(impressions)) + 1 AS pos
      FROM (SELECT region, {CATEGORY_CASE} AS category, impressions, clicks, sum_position FROM ({GSC_URL}))
      GROUP BY region, category
    """)
    gmap = {(r["region"], r["category"]): r for r in gsc}

    def build(region_filter):
        agg = {}
        for r in ga:
            if region_filter and r["region"] != region_filter:
                continue
            c = agg.setdefault(r["category"], {"views": 0, "sessions": 0, "eng_sess": 0, "impr": 0, "clicks": 0, "pos_num": 0, "pos_den": 0})
            c["views"] += int(r["views"] or 0); c["sessions"] += int(r["sessions"] or 0); c["eng_sess"] += int(r["eng_sess"] or 0)
        for (reg, cat), s in gmap.items():
            if region_filter and reg != region_filter:
                continue
            c = agg.setdefault(cat, {"views": 0, "sessions": 0, "eng_sess": 0, "impr": 0, "clicks": 0, "pos_num": 0, "pos_den": 0})
            im = int(s["impr"] or 0)
            c["impr"] += im; c["clicks"] += int(s["clicks"] or 0)
            c["pos_num"] += float(s["pos"] or 0) * im; c["pos_den"] += im
        out = []
        for cat, c in agg.items():
            out.append({
                "cat": cat, "views": c["views"], "impr": c["impr"], "clicks": c["clicks"],
                "pos": round(c["pos_num"] / c["pos_den"], 1) if c["pos_den"] else 0,
                "eng": round(c["eng_sess"] / c["sessions"], 3) if c["sessions"] else 0,
            })
        return sorted(out, key=lambda x: -x["views"])

    return {"All": build(None), **{reg: build(reg) for reg in REGIONS}}


def toppages_section(client):
    ga = run(client, f"""
      SELECT region, category, url, ANY_VALUE(title) AS title,
        COUNTIF(event_name='page_view') AS views,
        COUNT(DISTINCT sess) AS sessions,
        COUNT(DISTINCT IF(engaged, sess, NULL)) AS eng_sess
      FROM (SELECT region, sess, event_name, engaged, p AS url, title, {CATEGORY_CASE} AS category FROM ({GA4_EV}) WHERE p != '' AND p != '/')
      GROUP BY region, category, url
    """)
    gsc = run(client, f"""
      SELECT region, p AS url, SUM(impressions) AS impr, SUM(clicks) AS clicks,
        SAFE_DIVIDE(SUM(sum_position), SUM(impressions)) + 1 AS pos
      FROM ({GSC_URL})
      GROUP BY region, url
    """)
    gmap = {(r["region"], r["url"]): r for r in gsc}
    rows = []
    for r in ga:
        s = gmap.get((r["region"], r["url"]), {})
        im = int(s.get("impr") or 0)
        rows.append({
            "cat": r["category"], "region": r["region"], "url": r["url"],
            "views": int(r["views"] or 0), "clicks": int(s.get("clicks") or 0), "impr": im,
            "ctr": round((int(s.get("clicks") or 0) / im * 100), 2) if im else 0,
            "pos": round(float(s["pos"]), 1) if s.get("pos") else None,
            "eng": round((int(r["eng_sess"] or 0) / int(r["sessions"]) * 100), 1) if r["sessions"] else 0,
        })
    # keep top 6 per (category, region) so every region populates, not just RoW
    seen, out = {}, []
    for r in sorted(rows, key=lambda x: -x["views"]):
        key = (r["cat"], r["region"])
        if seen.get(key, 0) < 6:
            seen[key] = seen.get(key, 0) + 1
            out.append(r)
    return sorted(out, key=lambda x: -x["views"])


def gap_section(client):
    rows = run(client, f"""
      SELECT region, url, SUM(impressions) AS impr, SUM(clicks) AS clicks,
        SAFE_DIVIDE(SUM(sum_position), SUM(impressions)) + 1 AS pos
      FROM (SELECT region, p AS url, impressions, clicks, sum_position FROM ({GSC_URL}) WHERE p != '')
      GROUP BY region, url
      HAVING impr >= 400
    """)

    def classify(ctr, pos):
        if pos < 4 and ctr < 2:
            return "Top Rank / Weak CTR"
        if 4 <= pos <= 15:
            return "Striking Distance"
        if 15 < pos <= 25:
            return "Page 2-3 Push"
        return "Deep / Low Priority"

    def build(region_filter):
        agg = {}
        for r in rows:
            if region_filter and r["region"] != region_filter:
                continue
            a = agg.setdefault(r["url"], {"impr": 0, "clicks": 0, "pos_num": 0})
            im = int(r["impr"] or 0)
            a["impr"] += im; a["clicks"] += int(r["clicks"] or 0); a["pos_num"] += float(r["pos"] or 0) * im
        out = []
        for url, a in agg.items():
            if a["impr"] < 400:
                continue
            pos = a["pos_num"] / a["impr"] if a["impr"] else 0
            ctr = (a["clicks"] / a["impr"] * 100) if a["impr"] else 0
            out.append({"url": url, "impr": a["impr"], "ctr": round(ctr, 2), "pos": round(pos, 1),
                        "type": classify(ctr, pos), "score": round(a["impr"] / pos) if pos else 0})
        return sorted(out, key=lambda x: -x["score"])[:15]

    return {"All": build(None), **{reg: build(reg) for reg in REGIONS}}


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

    tr = safe("traffic", lambda: traffic_sections(client))
    if tr:
        region_monthly, monthly, views_by_region, _ = tr
        out["REGION_MONTHLY"] = region_monthly
        out["MONTHLY"] = monthly
        out["VIEWS_BY_REGION"] = views_by_region

    out["CATEGORIES_BY_REGION"] = safe("categories", lambda: categories_section(client)) or {}
    out["TOPPAGES"] = safe("toppages", lambda: toppages_section(client)) or []
    out["GAP_BY_REGION"] = safe("gap", lambda: gap_section(client)) or {}

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
