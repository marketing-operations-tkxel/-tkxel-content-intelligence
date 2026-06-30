-- Tkxel Content Intelligence — Postgres schema
-- Run once to initialize. Safe to re-run (IF NOT EXISTS everywhere).

-- ---------------------------------------------------------------------------
-- Sync bookkeeping: one row per worker, updated at the end of every run.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sync_status (
    worker        TEXT PRIMARY KEY,          -- 'traffic' | 'inbound' | 'mql'
    last_run_at   TIMESTAMPTZ,
    last_ok_at    TIMESTAMPTZ,
    rows_written  INTEGER DEFAULT 0,
    status        TEXT DEFAULT 'pending',     -- 'ok' | 'error' | 'running' | 'pending'
    message       TEXT
);

-- ---------------------------------------------------------------------------
-- GA4 + GSC, aggregated by region x month.
-- Region is derived from GA4 geo.country (see workers/regions.py).
-- GSC has no region in our property, so impressions/clicks are joined on month
-- and country where available, else attributed to 'Global'.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS regional_traffic (
    region        TEXT NOT NULL,
    month         DATE NOT NULL,             -- first day of month
    sessions      BIGINT DEFAULT 0,
    users         BIGINT DEFAULT 0,
    engaged_sessions BIGINT DEFAULT 0,
    conversions   BIGINT DEFAULT 0,
    impressions   BIGINT DEFAULT 0,          -- GSC
    clicks        BIGINT DEFAULT 0,          -- GSC
    avg_position  NUMERIC(6,2) DEFAULT 0,    -- GSC
    PRIMARY KEY (region, month)
);

-- ---------------------------------------------------------------------------
-- Content categories (Blogs, Services, Solutions, Case Studies, ...)
-- Derived from URL path prefix. Aggregated per region.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS categories (
    region        TEXT NOT NULL,
    category      TEXT NOT NULL,
    sessions      BIGINT DEFAULT 0,
    users         BIGINT DEFAULT 0,
    conversions   BIGINT DEFAULT 0,
    pages         INTEGER DEFAULT 0,         -- distinct page count
    PRIMARY KEY (region, category)
);

-- ---------------------------------------------------------------------------
-- Top pages, per category x region.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS top_pages (
    region        TEXT NOT NULL,
    category      TEXT NOT NULL,
    page_path     TEXT NOT NULL,
    page_title    TEXT,
    sessions      BIGINT DEFAULT 0,
    users         BIGINT DEFAULT 0,
    clicks        BIGINT DEFAULT 0,
    impressions   BIGINT DEFAULT 0,
    avg_position  NUMERIC(6,2) DEFAULT 0,
    PRIMARY KEY (region, category, page_path)
);

-- ---------------------------------------------------------------------------
-- LLM / AI referral traffic (ChatGPT, Perplexity, Gemini, Claude, ...)
-- Page-level, global only (per-region too sparse — see README).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS llm_referrals (
    source        TEXT NOT NULL,             -- 'ChatGPT', 'Perplexity', ...
    page_path     TEXT NOT NULL,
    sessions      BIGINT DEFAULT 0,
    users         BIGINT DEFAULT 0,
    month         DATE NOT NULL,
    PRIMARY KEY (source, page_path, month)
);

-- ---------------------------------------------------------------------------
-- Content gap opportunities: GSC queries with high impressions but low CTR
-- or poor position — pages worth optimizing.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS content_gap (
    region        TEXT NOT NULL,
    query         TEXT NOT NULL,
    page_path     TEXT,
    impressions   BIGINT DEFAULT 0,
    clicks        BIGINT DEFAULT 0,
    ctr           NUMERIC(6,4) DEFAULT 0,
    avg_position  NUMERIC(6,2) DEFAULT 0,
    opportunity   NUMERIC(12,2) DEFAULT 0,   -- scored: impressions * (1 - ctr) weighted by position
    PRIMARY KEY (region, query)
);

-- ---------------------------------------------------------------------------
-- Pardot inbound leads (from Gmail Form Handler emails).
-- Idempotent on gmail_message_id.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS inbound_leads (
    gmail_message_id TEXT PRIMARY KEY,
    email         TEXT NOT NULL,
    description   TEXT,
    segment       TEXT DEFAULT 'Genuine',    -- 'Genuine' | 'Internal' | 'Spam'
    domain        TEXT,
    received_at   TIMESTAMPTZ,
    raw_subject   TEXT
);

-- ---------------------------------------------------------------------------
-- MQL records matched from the SDR Google Sheet against inbound leads.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mql_records (
    email         TEXT PRIMARY KEY,
    name          TEXT,
    company       TEXT,
    status        TEXT,                       -- SDR-assigned status / stage
    owner         TEXT,
    matched_lead  BOOLEAN DEFAULT FALSE,      -- true if email exists in inbound_leads
    created_at    TIMESTAMPTZ,
    raw           JSONB
);

-- ---------------------------------------------------------------------------
-- Rich dashboard cache: the sync_dashboard worker computes every breakdown the
-- frontend needs and stores it as one JSON blob under section='all'.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dashboard_cache (
    section     TEXT PRIMARY KEY,
    payload     JSONB NOT NULL,
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- SEO keyword-research jobs (content gap + KD + competitor backlinks).
-- Run async (external SERP/backlink APIs + LLM are slow); poll by id.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS seo_jobs (
    id          TEXT PRIMARY KEY,
    brand       TEXT,
    keyword     TEXT,
    target_url  TEXT,
    status      TEXT DEFAULT 'running',   -- 'running' | 'done' | 'error'
    result      JSONB,
    error       TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_inbound_received ON inbound_leads (received_at);
CREATE INDEX IF NOT EXISTS idx_inbound_segment  ON inbound_leads (segment);
CREATE INDEX IF NOT EXISTS idx_regional_month   ON regional_traffic (month);
