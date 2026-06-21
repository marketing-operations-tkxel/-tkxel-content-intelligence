"""sync_traffic.py — BigQuery GA4 + GSC -> Postgres.

Populates: regional_traffic, categories, top_pages, llm_referrals, content_gap.
Cron: 04:00 UTC daily (GA4 export lands by ~03:00).

All queries are floored at WINDOW_START (2026-01-01). Each table is fully
replaced on every run (DELETE + INSERT) so the dashboard always reflects the
latest aggregation — the volumes here are small enough that a full refresh is
simpler and safer than incremental upserts.
"""
import sys
import pathlib

# Allow running as `python workers/sync_traffic.py` from backend/.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from db.connection import get_cursor, mark_sync   # noqa: E402
from workers.bq_client import (                    # noqa: E402
    get_client, GA4_DATASET, GSC_DATASET, GSC_SITE, WINDOW_START, PROJECT,
)
from workers.regions import region_for             # noqa: E402
from workers.categories import categorize          # noqa: E402

# LLM/AI referrers we care about, matched against traffic_source.source / referrer host.
LLM_SOURCES = {
    "chatgpt.com": "ChatGPT",
    "chat.openai.com": "ChatGPT",
    "openai.com": "ChatGPT",
    "perplexity.ai": "Perplexity",
    "gemini.google.com": "Gemini",
    "bard.google.com": "Gemini",
    "claude.ai": "Claude",
    "copilot.microsoft.com": "Copilot",
}


def _ga4_events_filter() -> str:
    # events_YYYYMMDD suffix >= window start (strip dashes for table suffix compare)
    return f"_TABLE_SUFFIX >= '{WINDOW_START.replace('-', '')}'"


def fetch_regional(client):
    """GA4 sessions/users/conversions by country x month."""
    sql = f"""
    WITH base AS (
      SELECT
        geo.country AS country,
        DATE_TRUNC(PARSE_DATE('%Y%m%d', event_date), MONTH) AS month,
        (SELECT value.int_value FROM UNNEST(event_params)
           WHERE key = 'ga_session_id') AS session_id,
        user_pseudo_id,
        event_name
      FROM `{PROJECT}.{GA4_DATASET}.events_*`
      WHERE {_ga4_events_filter()}
    )
    SELECT
      country,
      month,
      COUNT(DISTINCT CONCAT(user_pseudo_id, CAST(session_id AS STRING))) AS sessions,
      COUNT(DISTINCT user_pseudo_id) AS users,
      COUNTIF(event_name IN ('generate_lead', 'form_submit', 'contact')) AS conversions
    FROM base
    GROUP BY country, month
    """
    return list(client.query(sql).result())


def fetch_gsc_by_month(client):
    """GSC impressions/clicks/position by month (property-level -> Global)."""
    sql = f"""
    SELECT
      DATE_TRUNC(data_date, MONTH) AS month,
      SUM(impressions) AS impressions,
      SUM(clicks) AS clicks,
      SAFE_DIVIDE(SUM(sum_top_position), SUM(impressions)) + 1 AS avg_position
    FROM `{PROJECT}.{GSC_DATASET}.searchdata_site_impression`
    WHERE data_date >= '{WINDOW_START}'
    GROUP BY month
    """
    return {r["month"]: r for r in client.query(sql).result()}


def fetch_pages(client):
    """GA4 page-level sessions/users by country, joined to GSC url-level metrics."""
    sql = f"""
    WITH ga AS (
      SELECT
        geo.country AS country,
        REGEXP_REPLACE(
          (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'page_location'),
          r'^https?://[^/]+', '') AS page_path,
        (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'page_title') AS page_title,
        user_pseudo_id,
        (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_id') AS session_id
      FROM `{PROJECT}.{GA4_DATASET}.events_*`
      WHERE {_ga4_events_filter()} AND event_name = 'page_view'
    )
    SELECT
      country,
      REGEXP_REPLACE(page_path, r'[?#].*$', '') AS page_path,
      ANY_VALUE(page_title) AS page_title,
      COUNT(DISTINCT CONCAT(user_pseudo_id, CAST(session_id AS STRING))) AS sessions,
      COUNT(DISTINCT user_pseudo_id) AS users
    FROM ga
    WHERE page_path IS NOT NULL AND page_path != ''
    GROUP BY country, page_path
    """
    return list(client.query(sql).result())


def fetch_gsc_urls(client):
    """GSC per-URL clicks/impressions/position (Global)."""
    sql = f"""
    SELECT
      REGEXP_REPLACE(url, r'^https?://[^/]+', '') AS page_path,
      SUM(impressions) AS impressions,
      SUM(clicks) AS clicks,
      SAFE_DIVIDE(SUM(sum_position), SUM(impressions)) + 1 AS avg_position
    FROM `{PROJECT}.{GSC_DATASET}.searchdata_url_impression`
    WHERE data_date >= '{WINDOW_START}'
    GROUP BY page_path
    """
    out = {}
    for r in client.query(sql).result():
        out[r["page_path"]] = r
    return out


def fetch_llm(client):
    """GA4 sessions/users by AI referrer source x page x month (global)."""
    hosts = "', '".join(LLM_SOURCES.keys())
    sql = f"""
    WITH base AS (
      SELECT
        LOWER((SELECT value.string_value FROM UNNEST(event_params)
                 WHERE key = 'source')) AS src,
        LOWER(collected_traffic_source.manual_source) AS manual_src,
        REGEXP_REPLACE(
          REGEXP_REPLACE(
            (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'page_location'),
            r'^https?://[^/]+', ''),
          r'[?#].*$', '') AS page_path,
        DATE_TRUNC(PARSE_DATE('%Y%m%d', event_date), MONTH) AS month,
        user_pseudo_id,
        (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_id') AS session_id
      FROM `{PROJECT}.{GA4_DATASET}.events_*`
      WHERE {_ga4_events_filter()}
    )
    SELECT
      COALESCE(src, manual_src) AS source_host,
      page_path,
      month,
      COUNT(DISTINCT CONCAT(user_pseudo_id, CAST(session_id AS STRING))) AS sessions,
      COUNT(DISTINCT user_pseudo_id) AS users
    FROM base
    WHERE COALESCE(src, manual_src) IN ('{hosts}')
      AND page_path IS NOT NULL AND page_path != ''
    GROUP BY source_host, page_path, month
    """
    return list(client.query(sql).result())


def fetch_gap(client):
    """GSC queries with high impressions but weak CTR/position = opportunities."""
    sql = f"""
    SELECT
      query,
      ANY_VALUE(REGEXP_REPLACE(url, r'^https?://[^/]+', '')) AS page_path,
      SUM(impressions) AS impressions,
      SUM(clicks) AS clicks,
      SAFE_DIVIDE(SUM(clicks), SUM(impressions)) AS ctr,
      SAFE_DIVIDE(SUM(sum_position), SUM(impressions)) + 1 AS avg_position
    FROM `{PROJECT}.{GSC_DATASET}.searchdata_url_impression`
    WHERE data_date >= '{WINDOW_START}' AND query IS NOT NULL AND query != ''
    GROUP BY query
    HAVING impressions >= 50
    ORDER BY impressions DESC
    LIMIT 500
    """
    return list(client.query(sql).result())


def run():
    client = get_client()
    rows_total = 0

    # ----- regional_traffic ---------------------------------------------------
    regional = fetch_regional(client)
    gsc_month = fetch_gsc_by_month(client)
    # Aggregate GA4 country->region per month.
    reg_acc: dict[tuple[str, object], dict] = {}
    for r in regional:
        key = (region_for(r["country"]), r["month"])
        acc = reg_acc.setdefault(key, {"sessions": 0, "users": 0, "conversions": 0})
        acc["sessions"] += r["sessions"] or 0
        acc["users"] += r["users"] or 0
        acc["conversions"] += r["conversions"] or 0

    with get_cursor(dict_rows=False) as cur:
        cur.execute("DELETE FROM regional_traffic")
        for (region, month), acc in reg_acc.items():
            g = gsc_month.get(month)
            cur.execute(
                """INSERT INTO regional_traffic
                   (region, month, sessions, users, conversions,
                    impressions, clicks, avg_position)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (region, month, acc["sessions"], acc["users"], acc["conversions"],
                 int(g["impressions"]) if g else 0,
                 int(g["clicks"]) if g else 0,
                 round(float(g["avg_position"]), 2) if g and g["avg_position"] else 0),
            )
            rows_total += 1

    # ----- pages, categories, top_pages --------------------------------------
    pages = fetch_pages(client)
    gsc_urls = fetch_gsc_urls(client)

    cat_acc: dict[tuple[str, str], dict] = {}
    page_rows = []
    for r in pages:
        region = region_for(r["country"])
        cat = categorize(r["page_path"])
        g = gsc_urls.get(r["page_path"])
        page_rows.append((region, cat, r["page_path"], r["page_title"],
                          r["sessions"] or 0, r["users"] or 0,
                          int(g["clicks"]) if g else 0,
                          int(g["impressions"]) if g else 0,
                          round(float(g["avg_position"]), 2) if g and g["avg_position"] else 0))
        c = cat_acc.setdefault((region, cat), {"sessions": 0, "users": 0, "pages": set()})
        c["sessions"] += r["sessions"] or 0
        c["users"] += r["users"] or 0
        c["pages"].add(r["page_path"])

    with get_cursor(dict_rows=False) as cur:
        cur.execute("DELETE FROM categories")
        for (region, cat), c in cat_acc.items():
            cur.execute(
                """INSERT INTO categories (region, category, sessions, users, conversions, pages)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                (region, cat, c["sessions"], c["users"], 0, len(c["pages"])),
            )
            rows_total += 1

        cur.execute("DELETE FROM top_pages")
        # Keep top 50 pages per (region, category) by sessions.
        page_rows.sort(key=lambda x: x[4], reverse=True)
        seen: dict[tuple[str, str], int] = {}
        for row in page_rows:
            k = (row[0], row[1])
            if seen.get(k, 0) >= 50:
                continue
            seen[k] = seen.get(k, 0) + 1
            cur.execute(
                """INSERT INTO top_pages
                   (region, category, page_path, page_title, sessions, users,
                    clicks, impressions, avg_position)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (region, category, page_path) DO NOTHING""",
                row,
            )
            rows_total += 1

    # ----- llm_referrals ------------------------------------------------------
    llm = fetch_llm(client)
    with get_cursor(dict_rows=False) as cur:
        cur.execute("DELETE FROM llm_referrals")
        for r in llm:
            source = LLM_SOURCES.get(r["source_host"], r["source_host"])
            cur.execute(
                """INSERT INTO llm_referrals (source, page_path, sessions, users, month)
                   VALUES (%s,%s,%s,%s,%s)
                   ON CONFLICT (source, page_path, month) DO UPDATE SET
                     sessions = EXCLUDED.sessions, users = EXCLUDED.users""",
                (source, r["page_path"], r["sessions"] or 0, r["users"] or 0, r["month"]),
            )
            rows_total += 1

    # ----- content_gap --------------------------------------------------------
    gap = fetch_gap(client)
    with get_cursor(dict_rows=False) as cur:
        cur.execute("DELETE FROM content_gap")
        for r in gap:
            imp = int(r["impressions"] or 0)
            ctr = float(r["ctr"] or 0)
            pos = float(r["avg_position"] or 0)
            # Opportunity: lots of impressions, low CTR, and rankable position (4-20).
            pos_weight = 1.0 if 4 <= pos <= 20 else 0.4
            opportunity = round(imp * (1 - ctr) * pos_weight, 2)
            cur.execute(
                """INSERT INTO content_gap
                   (region, query, page_path, impressions, clicks, ctr, avg_position, opportunity)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (region, query) DO UPDATE SET
                     impressions=EXCLUDED.impressions, clicks=EXCLUDED.clicks,
                     ctr=EXCLUDED.ctr, avg_position=EXCLUDED.avg_position,
                     opportunity=EXCLUDED.opportunity""",
                ("Global", r["query"], r["page_path"], imp, int(r["clicks"] or 0),
                 round(ctr, 4), round(pos, 2), opportunity),
            )
            rows_total += 1

    return rows_total


def main():
    try:
        mark_sync("traffic", "running")
        n = run()
        mark_sync("traffic", "ok", rows=n, message="sync_traffic complete")
        print(f"sync_traffic: wrote {n} rows")
    except Exception as e:
        mark_sync("traffic", "error", message=str(e)[:500])
        print(f"sync_traffic FAILED: {e}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
