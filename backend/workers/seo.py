"""Keyword research: content-gap analysis + Keyword Difficulty + competitor
backlinks. Uses DataForSEO (SERP, KD, backlinks) + Anthropic Claude (content diff).

Credentials (Railway env on tkxel-api):
  DATAFORSEO_LOGIN, DATAFORSEO_PASSWORD   — DataForSEO API basic auth
  ANTHROPIC_API_KEY                        — Claude (content gap analysis)
  ANTHROPIC_MODEL  (optional)              — defaults to claude-sonnet-4-6
"""
import os
import re
import json
import html
import traceback

import requests

DFS_BASE = "https://api.dataforseo.com/v3"
USA_LOCATION = 2840          # DataForSEO location_code for United States
LANG = "en"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
UA = "Mozilla/5.0 (compatible; TkxelContentIntel/1.0; +https://tkxel.com)"


def _dfs_auth():
    login = os.environ.get("DATAFORSEO_LOGIN")
    pw = os.environ.get("DATAFORSEO_PASSWORD")
    if not login or not pw:
        raise RuntimeError("DATAFORSEO_LOGIN / DATAFORSEO_PASSWORD not set")
    return (login, pw)


def _dfs_post(path, payload):
    r = requests.post(f"{DFS_BASE}/{path}", auth=_dfs_auth(),
                      json=payload if isinstance(payload, list) else [payload], timeout=60)
    r.raise_for_status()
    data = r.json()
    tasks = data.get("tasks") or []
    if not tasks:
        return []
    return tasks[0].get("result") or []


# ───────────────────────── DataForSEO ─────────────────────────
def serp_top10(keyword):
    res = _dfs_post("serp/google/organic/live/advanced",
                    {"keyword": keyword, "location_code": USA_LOCATION, "language_code": LANG, "depth": 20})
    items = (res[0].get("items") if res else []) or []
    out = []
    for it in items:
        if it.get("type") != "organic":
            continue
        out.append({"rank": it.get("rank_group"), "title": it.get("title"),
                    "url": it.get("url"), "domain": it.get("domain"),
                    "description": it.get("description")})
        if len(out) >= 10:
            break
    return out


def keyword_difficulty(keyword):
    try:
        res = _dfs_post("dataforseo_labs/google/bulk_keyword_difficulty/live",
                        {"keywords": [keyword], "location_code": USA_LOCATION, "language_code": LANG})
        items = (res[0].get("items") if res else []) or []
        if items:
            return items[0].get("keyword_difficulty")
    except Exception:  # noqa: BLE001
        traceback.print_exc()
    return None


def search_volume(keyword):
    try:
        res = _dfs_post("dataforseo_labs/google/search_volume/live",
                        {"keywords": [keyword], "location_code": USA_LOCATION, "language_code": LANG})
        items = (res[0].get("items") if res else []) or []
        if items:
            return items[0].get("keyword_info", {}).get("search_volume")
    except Exception:  # noqa: BLE001
        traceback.print_exc()
    return None


def bulk_referring_domains(urls):
    """Referring-domain + backlink counts for a list of target URLs."""
    if not urls:
        return {}
    try:
        res = _dfs_post("backlinks/bulk_referring_domains/live", {"targets": urls})
        items = (res[0].get("items") if res else []) or []
        rd = {}
        for it in items:
            rd[it.get("target")] = it.get("referring_domains")
        # also pull backlinks count
        res2 = _dfs_post("backlinks/bulk_backlinks/live", {"targets": urls})
        items2 = (res2[0].get("items") if res2 else []) or []
        bl = {it.get("target"): it.get("backlinks") for it in items2}
        return {u: {"referring_domains": rd.get(u), "backlinks": bl.get(u)} for u in urls}
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return {}


def referring_domains(target, limit=40):
    """Top referring domains pointing at a competitor — link opportunities."""
    try:
        res = _dfs_post("backlinks/referring_domains/live",
                        {"target": target, "limit": limit, "order_by": ["rank,desc"],
                         "backlinks_status_type": "live"})
        items = (res[0].get("items") if res else []) or []
        return [{"domain": it.get("domain"), "rank": it.get("rank"),
                 "backlinks": it.get("backlinks"), "first_seen": it.get("first_seen")}
                for it in items]
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return []


# ───────────────────────── scraping ─────────────────────────
def scrape_text(url, max_chars=7000):
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=20)
        if r.status_code != 200 or not r.text:
            return ""
        t = r.text
        t = re.sub(r"(?is)<(script|style|noscript|svg|head)[^>]*>.*?</\1>", " ", t)
        t = re.sub(r"(?is)<!--.*?-->", " ", t)
        t = re.sub(r"(?s)<[^>]+>", " ", t)
        t = html.unescape(t)
        t = re.sub(r"\s+", " ", t).strip()
        return t[:max_chars]
    except Exception:  # noqa: BLE001
        return ""


# ───────────────────────── Claude content gap ─────────────────────────
def claude_gap(keyword, our_url, our_text, competitors):
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key or key.startswith("placeholder") or len(key) < 20:
        return {"_note": "ANTHROPIC_API_KEY not set — content gap analysis skipped."}
    comp_blocks = []
    for i, c in enumerate(competitors, 1):
        if c.get("text"):
            comp_blocks.append(f"### Competitor {i} (rank {c.get('rank')}): {c.get('url')}\n{c['text'][:6000]}")
    prompt = f"""You are an SEO content strategist. Target keyword: "{keyword}".

OUR PAGE ({our_url or 'not provided'}):
{(our_text or '(no content retrieved)')[:6000]}

TOP-RANKING COMPETITOR PAGES:
{chr(10).join(comp_blocks) if comp_blocks else '(none retrieved)'}

Do a content-gap analysis: what do the competitors cover that OUR page is missing or weak on?
Return STRICT JSON only, no prose, with this shape:
{{
  "summary": "2-3 sentence verdict on why competitors out-rank us and the biggest gaps",
  "missing_topics": ["specific subtopics/sections competitors cover that we don't"],
  "missing_entities": ["named tools, concepts, brands, technologies competitors mention that we omit"],
  "missing_faqs": ["question-form queries competitors answer that we should add"],
  "structure_recommendations": ["concrete on-page changes: headings, tables, schema, intro answer, etc."],
  "priority_actions": ["the 3-5 highest-impact edits, ordered"]
}}"""
    try:
        r = requests.post(ANTHROPIC_URL, timeout=90,
                          headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                          json={"model": DEFAULT_MODEL, "max_tokens": 1500,
                                "messages": [{"role": "user", "content": prompt}]})
        r.raise_for_status()
        txt = "".join(b.get("text", "") for b in r.json().get("content", []))
        m = re.search(r"\{.*\}", txt, re.S)
        return json.loads(m.group(0)) if m else {"_note": "Could not parse model output", "raw": txt[:500]}
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        return {"_note": f"Claude analysis failed: {str(e)[:150]}"}


# ───────────────────────── orchestration ─────────────────────────
def run_analysis(brand, keyword, target_url):
    # 1. SERP
    serp = serp_top10(keyword)
    urls = [s["url"] for s in serp if s.get("url")]

    # 2. KD + volume
    kd = keyword_difficulty(keyword)
    vol = search_volume(keyword)

    # 3. backlinks per ranking page
    rd = bulk_referring_domains(urls)
    for s in serp:
        info = rd.get(s["url"], {})
        s["referring_domains"] = info.get("referring_domains")
        s["backlinks"] = info.get("backlinks")

    # KD-via-backlinks: median referring domains of the top 10 ≈ links needed to compete
    rds = sorted([s["referring_domains"] for s in serp if s.get("referring_domains") is not None])
    median_rd = rds[len(rds) // 2] if rds else None

    # 4. scrape competitors + our page
    our_text = scrape_text(target_url) if target_url else ""
    competitors = []
    for s in serp[:8]:
        competitors.append({"rank": s["rank"], "url": s["url"], "text": scrape_text(s["url"])})

    # 5. content gap (Claude)
    gap = claude_gap(keyword, target_url, our_text, competitors)

    # 6. competitor backlink opportunities (top 2 competitors)
    opp = []
    for s in serp[:2]:
        if s.get("url"):
            opp.append({"competitor": s["url"], "domain": s.get("domain"),
                        "referring_domains_list": referring_domains(s["url"], limit=30)})

    return {
        "keyword": keyword, "target_url": target_url, "brand": brand,
        "keyword_difficulty": kd, "search_volume": vol,
        "median_referring_domains": median_rd,
        "backlinks_needed_estimate": median_rd,
        "serp": serp,
        "content_gap": gap,
        "backlink_opportunities": opp,
        "our_content_chars": len(our_text),
    }
