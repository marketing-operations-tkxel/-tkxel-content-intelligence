import React, { useState, useMemo, useEffect, useCallback } from "react";
import {
  ResponsiveContainer, AreaChart, Area, LineChart, Line, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip
} from "recharts";
import {
  LayoutDashboard, Globe2, FileText, ListOrdered, Sparkles, Target,
  RefreshCw, Users, MousePointerClick, Search, Filter, CircleCheck, Eye, Calendar, ArrowRight
} from "lucide-react";

/* ───────── live data source ───────── */
const API = (import.meta.env.VITE_API_URL || "").replace(/\/$/, "");

/* ───────── theme ───────── */
const C = {
  paper: "#F6F5F1", ink: "#15171C", card: "#FFFFFF", border: "#E6E2D8", text: "#1B1E24",
  muted: "#777B82", faint: "#A6A299", sage: "#2E6B57", sageHi: "#3E8E72", sageSoft: "#E5EDE8",
  ochre: "#B0823A", slate: "#4A6585", rust: "#B5462F", grey: "#A8A296",
};
const SERIES = { USA: C.sage, MENA: C.ochre, Europe: C.slate, RoW: C.grey };
const MONO = "'IBM Plex Mono','JetBrains Mono',ui-monospace,SFMono-Regular,Menlo,monospace";
const SANS = "'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DAYS_2026 = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
const LLM_SRC = ["ChatGPT", "Gemini", "Claude", "Perplexity", "Copilot"];
const ICONS = { Users, MousePointerClick, FileText, Target, CircleCheck, Eye, Search };

/* ───────── live data (populated from /api/v2/all) ───────── */
let MONTHLY = [], VIEWS_BY_REGION = [], REGION_MONTHLY = { USA: [], MENA: [], Europe: [], RoW: [] };
let CATEGORIES_BY_REGION = { All: [] }, TOPPAGES = [], GAP_BY_REGION = { All: [] };
let LLM_MONTHLY_ALL = [], LLM_REGION_MONTHLY = { USA: [], MENA: [], Europe: [], RoW: [] };
let LLM_SOURCE_BY_REGION = {}, LLM_CATEGORY_BY_REGION = { All: [] }, LLM_BY_PAGE = [];
let LLM_LEAD_SIGNAL = { events: 0, dates: [] }, LLM_FUNNEL = { sessions: 0, convEvents: 0, signalEvents: 0 };
let FUNNEL = [], GENUINE_BY_TYPE = [], LEAD_PAGES = [], INBOUND_SEGMENTS = [];
let INBOUND_TOTALS = { submissions: 0, genuine: 0, mqls: 0, converted: 0 };
let MONTH_INFO = [], DAILY = [], DATE_MIN = "2026-01-01", DATE_MAX = "2026-06-30";

function applyPayload(d) {
  MONTHLY = d.MONTHLY || [];
  VIEWS_BY_REGION = d.VIEWS_BY_REGION || [];
  REGION_MONTHLY = d.REGION_MONTHLY || REGION_MONTHLY;
  CATEGORIES_BY_REGION = d.CATEGORIES_BY_REGION || { All: [] };
  TOPPAGES = d.TOPPAGES || [];
  GAP_BY_REGION = d.GAP_BY_REGION || { All: [] };
  LLM_MONTHLY_ALL = d.LLM_MONTHLY_ALL || [];
  LLM_REGION_MONTHLY = d.LLM_REGION_MONTHLY || LLM_REGION_MONTHLY;
  LLM_SOURCE_BY_REGION = d.LLM_SOURCE_BY_REGION || {};
  LLM_CATEGORY_BY_REGION = d.LLM_CATEGORY_BY_REGION || { All: [] };
  LLM_BY_PAGE = d.LLM_BY_PAGE || [];
  LLM_LEAD_SIGNAL = { events: 0, dates: [], ...(d.LLM_LEAD_SIGNAL || {}) };
  if (!LLM_LEAD_SIGNAL.dates) LLM_LEAD_SIGNAL.dates = [];
  LLM_FUNNEL = d.LLM_FUNNEL || LLM_FUNNEL;
  FUNNEL = (d.FUNNEL || []).map(f => ({ ...f, icon: ICONS[f.icon] || Users }));
  GENUINE_BY_TYPE = d.GENUINE_BY_TYPE || [];
  LEAD_PAGES = d.LEAD_PAGES || [];
  INBOUND_SEGMENTS = d.INBOUND_SEGMENTS || [];
  const fmap = Object.fromEntries((d.FUNNEL || []).map(f => [f.label, f.value]));
  INBOUND_TOTALS = {
    submissions: fmap["Pardot Submissions"] || 0, genuine: fmap["Genuine Leads"] || 0,
    mqls: fmap["MQLs"] || 0, converted: fmap["Converted"] || 0,
  };
  MONTH_INFO = MONTHLY.map(r => { const i = MONTHS.indexOf(r.m); return { y: 2026, m: i + 1, days: DAYS_2026[i] || 30 }; });
  DAILY = buildDaily();
  DATE_MIN = DAILY.length ? DAILY[0].date : "2026-01-01";
  DATE_MAX = DAILY.length ? DAILY[DAILY.length - 1].date : "2026-06-30";
}

/* ───────── helpers ───────── */
const pad2 = (n) => String(n).padStart(2, "0");
const isoDate = (mi, day) => `${MONTH_INFO[mi].y}-${pad2(MONTH_INFO[mi].m)}-${pad2(day)}`;
const fmtDate = (iso) => { const [y, m, d] = iso.split("-").map(Number); return `${d} ${MONTHS[m - 1]} ${y}`; };

/* Daily series interpolated evenly across each month's real total (BigQuery is monthly grain here). */
function buildDaily() {
  const days = [];
  MONTH_INFO.forEach((info, mi) => {
    const mo = MONTHLY[mi]; if (!mo) return;
    const f = 1 / info.days;
    // additive region fields are spread evenly across the month's days so summing
    // a date range reconstructs the real total; avg position (p) is left as-is.
    const reg = ["USA", "MENA", "Europe", "RoW"].map(r => {
      const m = (REGION_MONTHLY[r] || [])[mi] || { s: 0, u: 0, v: 0, e: 0, c: 0, im: 0, ck: 0, p: 0 };
      return { s: m.s * f, u: m.u * f, v: m.v * f, e: m.e * f, c: m.c * f, im: m.im * f, ck: m.ck * f, p: m.p };
    });
    for (let d = 1; d <= info.days; d++) {
      days.push({
        date: isoDate(mi, d), mi,
        sessions: mo.sessions * f, views: mo.views * f, clicks: mo.clicks * f, impr: mo.impr * f, conv: mo.conv * f, llm: (mo.llm || 0) * f,
        region: { USA: reg[0], MENA: reg[1], Europe: reg[2], RoW: reg[3] },
      });
    }
  });
  return days;
}
const dayIndex = (iso) => DAILY.findIndex(d => d.date === iso);

const nf = (n) => n == null ? "–" : Math.round(n).toLocaleString("en-US");
const pct = (n) => n == null ? "–" : (n * 100).toFixed(1) + "%";
const k = (n) => n == null ? "–" : n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e3 ? (n / 1e3).toFixed(1) + "K" : Math.round(n);
const sum = (a) => a.reduce((x, y) => x + y, 0);

function ChartTip({ active, payload, label }) {
  if (!active || !payload || !payload.length) return null;
  return (
    <div style={{ background: C.ink, color: "#fff", padding: "8px 11px", borderRadius: 6, fontFamily: SANS, fontSize: 12, boxShadow: "0 6px 20px rgba(0,0,0,.18)" }}>
      <div style={{ fontWeight: 600, marginBottom: 4, opacity: .85 }}>{label}</div>
      {payload.map((p, i) => (
        <div key={i} style={{ display: "flex", alignItems: "center", gap: 6, fontFamily: MONO }}>
          <span style={{ width: 8, height: 8, borderRadius: 2, background: p.color || p.fill }} />
          <span style={{ opacity: .8 }}>{p.name}</span><span style={{ marginLeft: "auto", fontWeight: 600 }}>{nf(p.value)}</span>
        </div>
      ))}
    </div>
  );
}
function Card({ title, sub, children, right, pad = 18 }) {
  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 10, overflow: "hidden" }}>
      {(title || right) && (
        <div style={{ display: "flex", alignItems: "baseline", gap: 10, padding: `14px ${pad}px 0` }}>
          <div><div style={{ fontFamily: SANS, fontSize: 13, fontWeight: 600, color: C.text }}>{title}</div>
            {sub && <div style={{ fontFamily: SANS, fontSize: 11.5, color: C.muted, marginTop: 2 }}>{sub}</div>}</div>
          {right && <div style={{ marginLeft: "auto" }}>{right}</div>}
        </div>
      )}
      <div style={{ padding: pad }}>{children}</div>
    </div>
  );
}
function Kpi({ label, value, fmt = nf, accent = C.sage, note, Icon }) {
  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 10, padding: "15px 16px", position: "relative", overflow: "hidden" }}>
      <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 3, background: accent }} />
      <div style={{ display: "flex", alignItems: "center", gap: 7, color: C.muted, fontFamily: SANS, fontSize: 11.5, fontWeight: 500, textTransform: "uppercase", letterSpacing: .6 }}>
        {Icon && <Icon size={13} strokeWidth={2} />}{label}</div>
      <div style={{ fontFamily: MONO, fontSize: 27, fontWeight: 600, color: C.text, marginTop: 8, lineHeight: 1 }}>{fmt(value)}</div>
      {note && <div style={{ fontFamily: SANS, fontSize: 11.5, color: C.faint, marginTop: 6 }}>{note}</div>}
    </div>
  );
}
const Pill = ({ children, color = C.sage, bg = C.sageSoft }) => (
  <span style={{ fontFamily: MONO, fontSize: 10.5, fontWeight: 600, color, background: bg, padding: "2px 7px", borderRadius: 5, whiteSpace: "nowrap" }}>{children}</span>
);
const FullWindow = () => (
  <span style={{ fontFamily: SANS, fontSize: 10.5, color: C.faint, border: `1px solid ${C.border}`, borderRadius: 5, padding: "2px 7px" }}>full window · not date-sliced</span>
);

/* ───────── tabs ───────── */
function Overview({ monthly, viewsRegion, totals, range, region, regions }) {
  const max = Math.max(...FUNNEL.map(f => f.value), 1);
  return (
    <div style={{ display: "grid", gap: 16 }}>
      <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 12, padding: "20px 22px" }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 4 }}>
          <div style={{ fontFamily: SANS, fontSize: 15, fontWeight: 700, color: C.text }}>Traffic → Pipeline</div>
          <div style={{ fontFamily: SANS, fontSize: 12, color: C.muted }}>where attention becomes qualified demand</div>
          <div style={{ marginLeft: "auto" }}><FullWindow /></div>
        </div>
        <div style={{ fontFamily: SANS, fontSize: 11.5, color: C.faint, marginBottom: 18 }}>
          Stages span GA4 · Pardot · SDR tracker — the drop-off is the signal, not a reconciliation.
        </div>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          {FUNNEL.map((f, i) => {
            const w = 0.34 + 0.66 * (f.value / max); const Icon = f.icon;
            const drop = i > 0 ? f.value / FUNNEL[i - 1].value : null;
            return (
              <div key={f.label} style={{ flex: "1 1 150px", minWidth: 140 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6, color: C.muted, fontFamily: SANS, fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: .5, marginBottom: 7 }}><Icon size={13} /> {f.label}</div>
                <div style={{ height: 56, borderRadius: 8, background: `linear-gradient(135deg, ${C.sage}, ${C.sageHi})`, opacity: 0.55 + 0.45 * (f.value / max), display: "flex", alignItems: "center", paddingLeft: 14, width: `${w * 100}%`, minWidth: 80 }}>
                  <span style={{ fontFamily: MONO, fontSize: 19, fontWeight: 700, color: "#fff" }}>{k(f.value)}</span></div>
                <div style={{ fontFamily: SANS, fontSize: 11, color: C.faint, marginTop: 6 }}>{f.sub}</div>
                {drop != null && <div style={{ marginTop: 4 }}><Pill color={C.rust} bg="#F6E5E0">{(drop * 100).toFixed(drop < 0.02 ? 2 : 1)}% pass-through</Pill></div>}
              </div>
            );
          })}
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))", gap: 12 }}>
        <Kpi label="Sessions" value={totals.sessions} Icon={Users} />
        <Kpi label="Page Views" value={totals.views} Icon={Eye} accent={C.slate} />
        <Kpi label="Organic Clicks" value={totals.clicks} Icon={MousePointerClick} accent={C.ochre} />
        <Kpi label="Impressions" value={totals.impr} fmt={k} Icon={Search} accent={C.slate} />
        <Kpi label="Conversions" value={totals.conv} Icon={CircleCheck} />
        <Kpi label="LLM Sessions" value={totals.llm} Icon={Sparkles} accent={C.ochre} />
      </div>
      <div style={{ display: "grid", gridTemplateColumns: region === "All" ? "1.4fr 1fr" : "1fr", gap: 16 }} className="grid-2">
        <Card title="Monthly trend" sub={`Sessions · views · clicks — ${range}${region !== "All" ? ` · ${region}` : ""}`}>
          <div style={{ height: 230 }}>
            <ResponsiveContainer>
              <AreaChart data={monthly} margin={{ left: -18, right: 6, top: 6 }}>
                <defs><linearGradient id="g1" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={C.sage} stopOpacity={0.25} /><stop offset="100%" stopColor={C.sage} stopOpacity={0} /></linearGradient></defs>
                <CartesianGrid stroke={C.border} vertical={false} />
                <XAxis dataKey="m" tick={{ fontSize: 11, fill: C.muted, fontFamily: MONO }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 10, fill: C.faint, fontFamily: MONO }} axisLine={false} tickLine={false} tickFormatter={k} />
                <Tooltip content={<ChartTip />} />
                <Area type="monotone" dataKey="views" name="Views" stroke={C.sage} fill="url(#g1)" strokeWidth={2} />
                <Line type="monotone" dataKey="sessions" name="Sessions" stroke={C.slate} strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="clicks" name="Clicks" stroke={C.ochre} strokeWidth={2} dot={false} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Card>
        {region === "All" && (
          <Card title="Views by region" sub="Rest of World carries the home market">
            <div style={{ height: 230 }}>
              <ResponsiveContainer>
                <BarChart data={viewsRegion} margin={{ left: -18, right: 6, top: 6 }} barCategoryGap="22%">
                  <CartesianGrid stroke={C.border} vertical={false} />
                  <XAxis dataKey="m" tick={{ fontSize: 11, fill: C.muted, fontFamily: MONO }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fontSize: 10, fill: C.faint, fontFamily: MONO }} axisLine={false} tickLine={false} tickFormatter={k} />
                  <Tooltip content={<ChartTip />} cursor={{ fill: "rgba(0,0,0,.03)" }} />
                  {["USA", "MENA", "Europe", "RoW"].map(r => <Bar key={r} dataKey={r} name={r} stackId="a" fill={SERIES[r]} radius={r === "RoW" ? [3, 3, 0, 0] : 0} />)}
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Card>
        )}
      </div>
      {region === "All" && (
        <Card title="Region breakdown" sub={`${range} · GA4 + GSC · USA / MENA / Europe / RoW (RoW carries the home market) · use the region filter to drill in`}>
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: SANS, fontSize: 12.5 }}>
              <thead><tr style={{ color: C.muted, fontSize: 11, textTransform: "uppercase", letterSpacing: .5 }}>
                {["Region", "Sessions", "Users", "Views", "Impr.", "Clicks", "CTR", "Avg Pos", "Engaged", "Conv."].map((h, i) =>
                  <th key={h} style={{ padding: "8px 10px", textAlign: i === 0 ? "left" : "right", borderBottom: `1px solid ${C.border}` }}>{h}</th>)}
              </tr></thead>
              <tbody style={{ fontFamily: MONO }}>
                {regions.map(r => (
                  <tr key={r.region}>
                    <td style={{ padding: "9px 10px", borderBottom: `1px solid ${C.border}`, fontFamily: SANS }}><span style={{ display: "inline-flex", alignItems: "center", gap: 7 }}><span style={{ width: 9, height: 9, borderRadius: 3, background: SERIES[r.region] }} />{r.region}</span></td>
                    {[nf(r.sessions), nf(r.users), nf(r.views), k(r.impr), nf(r.clicks), pct(r.impr ? r.clicks / r.impr : 0), r.pos.toFixed(1), pct(r.eng), nf(r.conv)].map((v, i) =>
                      <td key={i} style={{ padding: "9px 10px", borderBottom: `1px solid ${C.border}`, textAlign: "right", color: i === 5 && r.impr && (r.clicks / r.impr) < 0.003 ? C.rust : C.text }}>{v}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}

function Content({ region }) {
  const CATEGORIES = CATEGORIES_BY_REGION[region] || CATEGORIES_BY_REGION.All || [];
  const maxV = Math.max(...CATEGORIES.map(c => c.views), 1);
  return (
    <Card title="Content categories" sub={`${region === "All" ? "Global" : region} · GA4 views + GSC search · sorted by views`} right={<FullWindow />}>
      <div style={{ display: "grid", gap: 2 }}>
        <div style={{ display: "grid", gridTemplateColumns: "1.7fr 1fr 0.8fr 0.8fr 0.7fr 0.8fr 0.8fr", gap: 8, padding: "6px 8px", fontFamily: SANS, fontSize: 10.5, color: C.muted, textTransform: "uppercase", letterSpacing: .5 }}>
          <div>Category</div><div>Views</div><div style={{ textAlign: "right" }}>Impr.</div><div style={{ textAlign: "right" }}>Clicks</div><div style={{ textAlign: "right" }}>CTR</div><div style={{ textAlign: "right" }}>Pos</div><div style={{ textAlign: "right" }}>Engage</div>
        </div>
        {CATEGORIES.map(c => (
          <div key={c.cat} style={{ display: "grid", gridTemplateColumns: "1.7fr 1fr 0.8fr 0.8fr 0.7fr 0.8fr 0.8fr", gap: 8, padding: "9px 8px", alignItems: "center", borderBottom: `1px solid ${C.border}`, fontFamily: MONO, fontSize: 12.5 }}>
            <div style={{ fontFamily: SANS, fontWeight: 500 }}>{c.cat}</div>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}><div style={{ height: 7, borderRadius: 4, background: C.sage, width: `${Math.max(6, (c.views / maxV) * 100)}%`, minWidth: 6, opacity: .85 }} /><span>{nf(c.views)}</span></div>
            <div style={{ textAlign: "right", color: C.muted }}>{k(c.impr)}</div><div style={{ textAlign: "right" }}>{nf(c.clicks)}</div>
            <div style={{ textAlign: "right" }}>{(c.impr ? c.clicks / c.impr * 100 : 0).toFixed(2)}%</div><div style={{ textAlign: "right" }}>{c.pos.toFixed(1)}</div>
            <div style={{ textAlign: "right", color: c.eng > 0.6 ? C.sage : C.muted }}>{pct(c.eng)}</div>
          </div>
        ))}
      </div>
    </Card>
  );
}

function TopPages({ region: globalRegion }) {
  const cats = [...new Set(TOPPAGES.map(p => p.cat))]; const regionOpts = ["All", "USA", "MENA", "Europe", "RoW"];
  const [cat, setCat] = useState(cats[0]);
  const [localRegion, setLocalRegion] = useState(globalRegion);
  const region = globalRegion === "All" ? localRegion : globalRegion;
  const rows = TOPPAGES.filter(p => p.cat === cat && (region === "All" || p.region === region)).sort((a, b) => b.views - a.views);
  const Sel = ({ value, set, opts }) => (<select value={value} onChange={e => set(e.target.value)} style={{ fontFamily: SANS, fontSize: 12, color: C.text, background: C.card, border: `1px solid ${C.border}`, borderRadius: 7, padding: "6px 10px", cursor: "pointer" }}>{opts.map(o => <option key={o} value={o}>{o}</option>)}</select>);
  return (
    <Card title="Top pages" sub={`Ranked by views · GA4 joined to GSC at URL level${globalRegion !== "All" ? ` · scoped to ${globalRegion}` : ""}`} right={<div style={{ display: "flex", gap: 8, alignItems: "center" }}><Filter size={14} color={C.muted} /><Sel value={cat} set={setCat} opts={cats} />{globalRegion === "All" && <Sel value={localRegion} set={setLocalRegion} opts={regionOpts} />}</div>}>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: SANS, fontSize: 12.5 }}>
          <thead><tr style={{ color: C.muted, fontSize: 11, textTransform: "uppercase", letterSpacing: .5 }}>
            {["#", "URL", "Region", "Views", "Clicks", "Impr.", "CTR", "Pos", "Engage"].map((h, i) => <th key={h} style={{ padding: "8px 9px", textAlign: i > 2 ? "right" : "left", borderBottom: `1px solid ${C.border}`, whiteSpace: "nowrap" }}>{h}</th>)}
          </tr></thead>
          <tbody style={{ fontFamily: MONO }}>
            {rows.map((p, i) => (
              <tr key={i}>
                <td style={{ padding: "8px 9px", borderBottom: `1px solid ${C.border}`, color: C.faint }}>{i + 1}</td>
                <td style={{ padding: "8px 9px", borderBottom: `1px solid ${C.border}`, maxWidth: 360, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: C.sage }}>{p.url}</td>
                <td style={{ padding: "8px 9px", borderBottom: `1px solid ${C.border}`, fontFamily: SANS }}><Pill color={SERIES[p.region]} bg="#F1EFEA">{p.region}</Pill></td>
                <td style={{ padding: "8px 9px", borderBottom: `1px solid ${C.border}`, textAlign: "right", fontWeight: 600 }}>{nf(p.views)}</td>
                <td style={{ padding: "8px 9px", borderBottom: `1px solid ${C.border}`, textAlign: "right" }}>{nf(p.clicks)}</td>
                <td style={{ padding: "8px 9px", borderBottom: `1px solid ${C.border}`, textAlign: "right", color: C.muted }}>{k(p.impr)}</td>
                <td style={{ padding: "8px 9px", borderBottom: `1px solid ${C.border}`, textAlign: "right" }}>{p.ctr.toFixed(2)}%</td>
                <td style={{ padding: "8px 9px", borderBottom: `1px solid ${C.border}`, textAlign: "right" }}>{p.pos == null ? "–" : p.pos.toFixed(1)}</td>
                <td style={{ padding: "8px 9px", borderBottom: `1px solid ${C.border}`, textAlign: "right", color: C.sage }}>{p.eng.toFixed(0)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function LLM({ llmMonthly, llmTotals, total, region }) {
  const catData = LLM_CATEGORY_BY_REGION[region] || LLM_CATEGORY_BY_REGION.All || [];
  const maxCat = Math.max(...catData.map(d => d.sessions), 1);
  return (
    <div style={{ display: "grid", gap: 16 }}>
      {region !== "All" && (
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span style={{ fontFamily: SANS, fontSize: 11, color: C.sage, border: `1px solid #CFE0D7`, background: C.sageSoft, borderRadius: 5, padding: "2px 7px" }}>scoped to {region}</span>
          <span style={{ fontFamily: SANS, fontSize: 11, color: C.faint }}>· page-level table below stays global (sparse per-region counts)</span>
        </div>
      )}
      <div style={{ display: "grid", gridTemplateColumns: "1.5fr 1fr", gap: 16 }} className="grid-2">
        <Card title="LLM referral sessions" sub={`From GA4 source · all regions${region !== "All" ? " — see Share card for " + region : ""}`}>
          <div style={{ height: 240 }}>
            <ResponsiveContainer>
              <LineChart data={llmMonthly} margin={{ left: -18, right: 6, top: 6 }}>
                <CartesianGrid stroke={C.border} vertical={false} />
                <XAxis dataKey="m" tick={{ fontSize: 11, fill: C.muted, fontFamily: MONO }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 10, fill: C.faint, fontFamily: MONO }} axisLine={false} tickLine={false} />
                <Tooltip content={<ChartTip />} />
                {[["ChatGPT", C.sage], ["Gemini", C.ochre], ["Claude", C.slate], ["Perplexity", C.rust], ["Copilot", C.grey]].map(([s, col]) => <Line key={s} type="monotone" dataKey={s} name={s} stroke={col} strokeWidth={2} dot={{ r: 2 }} />)}
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Card>
        <Card title="Share of LLM traffic" sub={region === "All" ? "selected range, all regions" : `${region} · full window`}>
          <div style={{ display: "grid", gap: 9, marginTop: 4 }}>
            {llmTotals.map(l => {
              const share = total ? l.sessions / total : 0;
              return (
                <div key={l.src}>
                  <div style={{ display: "flex", justifyContent: "space-between", fontFamily: SANS, fontSize: 12.5, marginBottom: 4 }}><span style={{ fontWeight: 500 }}>{l.src}</span><span style={{ fontFamily: MONO, color: C.muted }}>{nf(l.sessions)} · {pct(share)}</span></div>
                  <div style={{ height: 8, background: "#EFEDE7", borderRadius: 5 }}><div style={{ height: "100%", width: `${share * 100}%`, background: C.sage, borderRadius: 5 }} /></div>
                </div>
              );
            })}
          </div>
        </Card>
      </div>

      <Card title="LLM traffic by content type" sub={`${region === "All" ? "Full window" : region} · which content AI assistants actually surface`} right={region === "All" ? <FullWindow /> : null}>
        <div style={{ display: "grid", gap: 9, marginTop: 4 }}>
          {catData.map(d => (
            <div key={d.cat} style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span style={{ fontFamily: SANS, fontSize: 12.5, width: 150, flexShrink: 0 }}>{d.cat}</span>
              <div style={{ flex: 1, height: 16, background: "#F1EFEA", borderRadius: 4 }}>
                <div style={{ height: "100%", width: `${(d.sessions / maxCat) * 100}%`, background: C.sage, borderRadius: 4, minWidth: 4 }} />
              </div>
              <span style={{ fontFamily: MONO, fontSize: 12.5, fontWeight: 600, width: 40, textAlign: "right" }}>{d.sessions}</span>
              <span style={{ fontFamily: MONO, fontSize: 11, width: 64, textAlign: "right", color: d.conv > 0 ? C.sage : C.faint }}>{d.conv} conv.</span>
            </div>
          ))}
        </div>
      </Card>

      <Card title="LLM traffic by page" sub="top pages receiving AI-assistant referrals · full window, all regions" right={<FullWindow />}>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: SANS, fontSize: 12.5 }}>
            <thead><tr style={{ color: C.muted, fontSize: 11, textTransform: "uppercase", letterSpacing: .5 }}>
              {["URL", "Sessions", "Conv. events", "Top source"].map((h, i) => <th key={h} style={{ padding: "8px 9px", textAlign: i === 0 ? "left" : "right", borderBottom: `1px solid ${C.border}` }}>{h}</th>)}
            </tr></thead>
            <tbody style={{ fontFamily: MONO }}>
              {LLM_BY_PAGE.map((p, i) => (
                <tr key={i}>
                  <td style={{ padding: "8px 9px", borderBottom: `1px solid ${C.border}`, color: C.sage, maxWidth: 320, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{p.url}</td>
                  <td style={{ padding: "8px 9px", borderBottom: `1px solid ${C.border}`, textAlign: "right", fontWeight: 600 }}>{nf(p.sessions)}</td>
                  <td style={{ padding: "8px 9px", borderBottom: `1px solid ${C.border}`, textAlign: "right", color: p.conv > 0 ? C.sage : C.faint }}>{p.conv}</td>
                  <td style={{ padding: "8px 9px", borderBottom: `1px solid ${C.border}`, textAlign: "right", fontFamily: SANS }}>{p.top ? <Pill>{p.top}</Pill> : "–"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div style={{ display: "flex", gap: 9, alignItems: "flex-start", background: C.sageSoft, border: "1px solid #CFE0D7", borderRadius: 8, padding: "10px 13px", marginTop: 12 }}>
          <Sparkles size={14} color={C.sage} style={{ marginTop: 1, flexShrink: 0 }} />
          <div style={{ fontFamily: SANS, fontSize: 11.5, color: "#22503F", lineHeight: 1.5 }}>
            Conversion events on AI-referred sessions are GA4 events on anonymized sessions — a directional signal that AI assistants send people who convert, not a hard identity join to a named Pardot lead. Shown as such on the Inbound tab.
          </div>
        </div>
      </Card>
    </div>
  );
}

function Opportunities({ region }) {
  const GAP = GAP_BY_REGION[region] || GAP_BY_REGION.All || [];
  const color = (t) => t.includes("Striking") ? { c: C.sage, b: C.sageSoft } : t.includes("Weak CTR") ? { c: C.rust, b: "#F6E5E0" } : { c: C.ochre, b: "#F5ECDB" };
  const maxS = Math.max(...GAP.map(g => g.score), 1);
  return (
    <Card title="Content gap & opportunities" sub={`GSC${region !== "All" ? ` · ${region}` : ""} · priority = impressions ÷ avg position · striking-distance = fastest wins`} right={<FullWindow />}>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: SANS, fontSize: 12.5 }}>
          <thead><tr style={{ color: C.muted, fontSize: 11, textTransform: "uppercase", letterSpacing: .5 }}>
            {["URL", "Impr.", "CTR", "Pos", "Opportunity", "Priority"].map((h, i) => <th key={h} style={{ padding: "8px 9px", textAlign: i === 0 || i === 4 ? "left" : "right", borderBottom: `1px solid ${C.border}` }}>{h}</th>)}
          </tr></thead>
          <tbody style={{ fontFamily: MONO }}>
            {GAP.map((g, i) => {
              const cl = color(g.type);
              return (
                <tr key={i}>
                  <td style={{ padding: "8px 9px", borderBottom: `1px solid ${C.border}`, maxWidth: 330, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: C.sage }}>{g.url}</td>
                  <td style={{ padding: "8px 9px", borderBottom: `1px solid ${C.border}`, textAlign: "right" }}>{k(g.impr)}</td>
                  <td style={{ padding: "8px 9px", borderBottom: `1px solid ${C.border}`, textAlign: "right", color: g.ctr < 0.3 ? C.rust : C.text }}>{g.ctr.toFixed(2)}%</td>
                  <td style={{ padding: "8px 9px", borderBottom: `1px solid ${C.border}`, textAlign: "right" }}>{g.pos.toFixed(1)}</td>
                  <td style={{ padding: "8px 9px", borderBottom: `1px solid ${C.border}`, fontFamily: SANS }}><Pill color={cl.c} bg={cl.b}>{g.type}</Pill></td>
                  <td style={{ padding: "8px 9px", borderBottom: `1px solid ${C.border}`, textAlign: "right" }}><div style={{ display: "flex", alignItems: "center", gap: 7, justifyContent: "flex-end" }}><div style={{ height: 6, borderRadius: 3, background: C.ochre, width: `${Math.max(8, (g.score / maxS) * 70)}px`, opacity: .8 }} /><span>{k(g.score)}</span></div></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function AssetFunnel({ p }) {
  const stages = [
    { label: "Views", v: p.views, c: C.slate },
    { label: "Leads", v: p.leads, c: C.sage },
    { label: "MQL", v: p.mql, c: p.mql > 0 ? C.sage : C.rust },
  ];
  const base = p.views != null ? p.views : p.leads;
  const conv = (i) => i === 0 ? null : stages[i - 1].v ? stages[i].v / stages[i - 1].v : 0;
  return (
    <div style={{ border: `1px solid ${C.border}`, borderRadius: 9, padding: "13px 14px", background: C.card }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
        <span style={{ fontFamily: SANS, fontSize: 12.5, fontWeight: 600, color: C.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{p.asset}</span>
        <span style={{ marginLeft: "auto" }}><Pill>{p.type}</Pill></span>
      </div>
      <div style={{ display: "grid", gap: 7 }}>
        {stages.map((s, i) => (
          <div key={s.label} style={{ display: "flex", alignItems: "center", gap: 9 }}>
            <span style={{ fontFamily: SANS, fontSize: 11, color: C.muted, width: 40 }}>{s.label}</span>
            <div style={{ flex: 1, height: 18, background: "#F1EFEA", borderRadius: 4, position: "relative", overflow: "hidden" }}>
              <div style={{ height: "100%", width: `${s.v == null ? 0 : Math.max(3, (s.v / (base || 1)) * 100)}%`, background: s.c, borderRadius: 4, opacity: s.label === "MQL" && s.v === 0 ? 0.25 : 0.9 }} />
            </div>
            <span style={{ fontFamily: MONO, fontSize: 12, fontWeight: 600, width: 42, textAlign: "right", color: s.label === "MQL" && s.v === 0 ? C.rust : C.text }}>{s.v == null ? "–" : nf(s.v)}</span>
            <span style={{ fontFamily: MONO, fontSize: 10.5, color: C.faint, width: 52, textAlign: "right" }}>{conv(i) == null ? "" : (conv(i) * 100).toFixed(conv(i) < 0.02 ? 1 : 0) + "%"}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function Inbound() {
  const seg = INBOUND_SEGMENTS; const tot = Math.max(1, sum(seg.map(s => s.v)));
  const maxT = Math.max(...GENUINE_BY_TYPE.map(d => d.leads), 1); const maxLP = Math.max(...LEAD_PAGES.map(d => d.leads), 1);
  const funnelAssets = LEAD_PAGES.filter(p => p.leads >= 2 || p.mql > 0);
  const genPct = INBOUND_TOTALS.submissions ? Math.round(INBOUND_TOTALS.genuine / INBOUND_TOTALS.submissions * 100) : 0;
  return (
    <div style={{ display: "grid", gap: 16 }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <span style={{ fontFamily: SANS, fontSize: 11, color: C.faint, border: `1px solid ${C.border}`, borderRadius: 5, padding: "2px 7px" }}>global only · Pardot has no region field, region filter not applied here</span>
      </div>
      <div style={{ display: "flex", gap: 10, alignItems: "center", background: C.sageSoft, border: `1px solid #CFE0D7`, borderRadius: 10, padding: "11px 15px" }}>
        <Sparkles size={15} color={C.sage} />
        <div style={{ fontFamily: SANS, fontSize: 12.5, color: "#22503F" }}>Genuine leads parsed live from {nf(INBOUND_TOTALS.submissions)} Pardot Form Handler emails, segmented from internal/test &amp; spam. Refreshes on the daily sync.</div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))", gap: 12 }}>
        <Kpi label="Submissions" value={INBOUND_TOTALS.submissions} Icon={FileText} accent={C.slate} />
        <Kpi label="Genuine Leads" value={INBOUND_TOTALS.genuine} Icon={Users} note={`${genPct}% of submissions`} />
        <Kpi label="MQLs" value={INBOUND_TOTALS.mqls} Icon={Target} accent={C.ochre} />
        <Kpi label="Converted" value={INBOUND_TOTALS.converted} Icon={CircleCheck} note="qualified / won" />
        <Kpi label="LLM Sessions" value={LLM_FUNNEL.sessions} Icon={Sparkles} accent={C.sage} note={`${LLM_FUNNEL.convEvents} conv. events`} />
        <Kpi label="LLM Lead Signal" value={LLM_FUNNEL.signalEvents} Icon={Target} accent={C.rust} note="directional, unconfirmed" />
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }} className="grid-2">
        <Card title="Lead quality split" sub="of all form submissions">
          <div style={{ display: "grid", gap: 12, marginTop: 4 }}>
            {seg.map(s => (<div key={s.k}><div style={{ display: "flex", justifyContent: "space-between", fontFamily: SANS, fontSize: 12.5, marginBottom: 4 }}><span>{s.k}</span><span style={{ fontFamily: MONO, color: C.muted }}>{s.v} · {(s.v / tot * 100).toFixed(0)}%</span></div><div style={{ height: 9, background: "#EFEDE7", borderRadius: 5 }}><div style={{ height: "100%", width: `${s.v / tot * 100}%`, background: s.c, borderRadius: 5 }} /></div></div>))}
          </div>
        </Card>
        <Card title="Genuine leads by content type" sub="which formats capture demand">
          <div style={{ display: "grid", gap: 9, marginTop: 4 }}>
            {GENUINE_BY_TYPE.map(d => (<div key={d.type} style={{ display: "flex", alignItems: "center", gap: 10 }}><span style={{ fontFamily: SANS, fontSize: 12.5, width: 96, flexShrink: 0 }}>{d.type}</span><div style={{ flex: 1, height: 16, background: "#F1EFEA", borderRadius: 4 }}><div style={{ height: "100%", width: `${(d.leads / maxT) * 100}%`, background: d.color, borderRadius: 4, minWidth: 4 }} /></div><span style={{ fontFamily: MONO, fontSize: 12.5, fontWeight: 600, width: 24, textAlign: "right" }}>{d.leads}</span></div>))}
          </div>
        </Card>
      </div>

      <Card title="Per-asset funnel" sub="views → leads → MQL for each gated asset, plus the LLM-origin lens · the gated-asset leak, made visible">
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(300px,1fr))", gap: 12 }}>
          {funnelAssets.map((p, i) => <AssetFunnel key={i} p={p} />)}
          <div style={{ border: `1px dashed ${C.faint}`, borderRadius: 9, padding: "13px 14px", background: "#FBFAF7" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
              <span style={{ fontFamily: SANS, fontSize: 12.5, fontWeight: 600, color: C.text }}>LLM-origin (all assets)</span>
              <span style={{ marginLeft: "auto" }}><Pill color={C.ochre} bg="#F5ECDB">AI referral</Pill></span>
            </div>
            <div style={{ display: "grid", gap: 7 }}>
              {[["Sessions", LLM_FUNNEL.sessions, C.slate, 1], ["Conv. events", LLM_FUNNEL.convEvents, C.sage, LLM_FUNNEL.sessions ? LLM_FUNNEL.convEvents / LLM_FUNNEL.sessions : 0], ["Lead signal", LLM_FUNNEL.signalEvents, C.rust, LLM_FUNNEL.sessions ? LLM_FUNNEL.signalEvents / LLM_FUNNEL.sessions : 0]].map(([label, v, col, frac]) => (
                <div key={label} style={{ display: "flex", alignItems: "center", gap: 9 }}>
                  <span style={{ fontFamily: SANS, fontSize: 11, color: C.muted, width: 78 }}>{label}</span>
                  <div style={{ flex: 1, height: 18, background: "#F1EFEA", borderRadius: 4, overflow: "hidden" }}><div style={{ height: "100%", width: `${Math.max(3, frac * 100)}%`, background: col, borderRadius: 4, opacity: .9 }} /></div>
                  <span style={{ fontFamily: MONO, fontSize: 12, fontWeight: 600, width: 38, textAlign: "right" }}>{nf(v)}</span>
                </div>
              ))}
            </div>
            <div style={{ fontFamily: SANS, fontSize: 10.5, color: C.faint, marginTop: 8 }}>No confirmed MQL match yet — see LLM Traffic tab for page detail.</div>
          </div>
        </div>
        <div style={{ fontFamily: SANS, fontSize: 11.5, color: C.faint, marginTop: 12, lineHeight: 1.5 }}>
          % = step conversion. Only <b>Contact Us</b> reliably reaches pipeline (it carries the matched MQLs); gated assets capture leads but stall before MQL. LLM-origin traffic is smaller but punches above its weight on conversion rate — worth watching as a channel.
        </div>
      </Card>

      <Card title="Genuine leads by asset" sub="parsed from Pardot Form Handler descriptions · matched MQLs flagged">
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: SANS, fontSize: 12.5 }}>
            <thead><tr style={{ color: C.muted, fontSize: 11, textTransform: "uppercase", letterSpacing: .5 }}>
              {["Asset / Form", "Type", "Leads", "MQL"].map((h, i) => <th key={h} style={{ padding: "8px 9px", textAlign: i >= 2 ? "right" : "left", borderBottom: `1px solid ${C.border}`, whiteSpace: "nowrap" }}>{h}</th>)}
            </tr></thead>
            <tbody style={{ fontFamily: MONO }}>
              {LEAD_PAGES.map((p, i) => (
                <tr key={i}>
                  <td style={{ padding: "9px 9px", borderBottom: `1px solid ${C.border}`, fontFamily: SANS, fontWeight: 500, maxWidth: 320, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{p.asset}</td>
                  <td style={{ padding: "9px 9px", borderBottom: `1px solid ${C.border}`, fontFamily: SANS }}><Pill>{p.type}</Pill></td>
                  <td style={{ padding: "9px 9px", borderBottom: `1px solid ${C.border}`, textAlign: "right", fontWeight: 600 }}><span style={{ display: "inline-flex", alignItems: "center", gap: 7, justifyContent: "flex-end" }}><span style={{ height: 6, borderRadius: 3, background: C.sage, width: `${Math.max(6, (p.leads / maxLP) * 40)}px`, opacity: .85 }} />{p.leads}</span></td>
                  <td style={{ padding: "9px 9px", borderBottom: `1px solid ${C.border}`, textAlign: "right", color: p.mql > 0 ? C.sage : C.faint, fontWeight: 600 }}>{p.mql}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

/* ───────── app ───────── */
const NAV = [
  { id: "overview", label: "Overview", Icon: LayoutDashboard },
  { id: "content", label: "Content", Icon: FileText },
  { id: "top", label: "Top Pages", Icon: ListOrdered },
  { id: "llm", label: "LLM Traffic", Icon: Sparkles },
  { id: "gap", label: "Opportunities", Icon: Target },
  { id: "inbound", label: "Inbound Funnel", Icon: Users },
];

function Loader({ msg }) {
  return (
    <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: C.paper, fontFamily: SANS, color: C.muted, flexDirection: "column", gap: 14 }}>
      <style>{`@keyframes sp{to{transform:rotate(360deg)}}`}</style>
      <RefreshCw size={26} color={C.sage} style={{ animation: "sp 1s linear infinite" }} />
      <div style={{ fontSize: 13 }}>{msg || "Loading live data from BigQuery…"}</div>
    </div>
  );
}

export default function App() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [tab, setTab] = useState("overview");
  const [region, setRegion] = useState("All");
  const [syncing, setSyncing] = useState(false);
  const [asOf, setAsOf] = useState("");
  const [fromDate, setFromDate] = useState(null);
  const [toDate, setToDate] = useState(null);

  const load = useCallback(async () => {
    const r = await fetch(`${API}/api/v2/all`);
    const d = await r.json();
    if (!d.ready) { setErr("Dashboard data is still computing — the first sync may be running. Try Refresh in a minute."); return false; }
    applyPayload(d);
    setAsOf(d.asOf || d._updated || "");
    setFromDate(prev => prev || DATE_MIN);
    setToDate(prev => prev || DATE_MAX);
    setData(d); setErr(null);
    return true;
  }, []);

  useEffect(() => { load().catch(e => setErr(String(e))); }, [load]);

  const loIdx = data ? Math.min(dayIndex(fromDate), dayIndex(toDate)) : 0;
  const hiIdx = data ? Math.max(dayIndex(fromDate), dayIndex(toDate)) : 0;
  const spanDays = hiIdx - loIdx + 1;
  const rangeLabel = !data ? "" : fromDate === toDate ? fmtDate(fromDate) : `${fmtDate(DAILY[loIdx].date)} – ${fmtDate(DAILY[hiIdx].date)}`;
  const REGION_OPTS = ["All", "USA", "MENA", "Europe", "RoW"];

  const D = useMemo(() => {
    if (!data) return null;
    const slice = DAILY.slice(loIdx, hiIdx + 1);
    const byMonth = {};
    slice.forEach(d => { (byMonth[d.mi] = byMonth[d.mi] || []).push(d); });
    const monthIdxs = Object.keys(byMonth).map(Number).sort((a, b) => a - b);
    const regKey = region === "All" ? null : region;
    const monthly = monthIdxs.map(mi => {
      const rows = byMonth[mi];
      if (regKey) {
        const llmRows = byMonth[mi].map(d => {
          const dayFrac = 1 / MONTH_INFO[d.mi].days;
          const monthLlm = (LLM_REGION_MONTHLY[regKey] || [])[d.mi] || { s: 0, c: 0 };
          return { s: monthLlm.s * dayFrac, c: monthLlm.c * dayFrac };
        });
        return {
          m: MONTHS[mi], sessions: sum(rows.map(r => r.region[regKey].s)), views: sum(rows.map(r => r.region[regKey].v)),
          clicks: sum(rows.map(r => r.region[regKey].ck)), impr: sum(rows.map(r => r.region[regKey].im)),
          conv: sum(rows.map(r => r.region[regKey].c)), llm: sum(llmRows.map(x => x.s)),
        };
      }
      return { m: MONTHS[mi], sessions: sum(rows.map(r => r.sessions)), views: sum(rows.map(r => r.views)), clicks: sum(rows.map(r => r.clicks)), impr: sum(rows.map(r => r.impr)), conv: sum(rows.map(r => r.conv)), llm: sum(rows.map(r => r.llm)) };
    });
    const viewsRegion = monthIdxs.map(mi => {
      const rows = byMonth[mi];
      return { m: MONTHS[mi], USA: sum(rows.map(r => r.region.USA.v)), MENA: sum(rows.map(r => r.region.MENA.v)), Europe: sum(rows.map(r => r.region.Europe.v)), RoW: sum(rows.map(r => r.region.RoW.v)) };
    });
    const llmMonthly = monthIdxs.map(mi => {
      const f = byMonth[mi].length / MONTH_INFO[mi].days;
      const src = LLM_MONTHLY_ALL[mi] || {};
      return { m: MONTHS[mi], ChatGPT: (src.ChatGPT || 0) * f, Gemini: (src.Gemini || 0) * f, Claude: (src.Claude || 0) * f, Perplexity: (src.Perplexity || 0) * f, Copilot: (src.Copilot || 0) * f };
    });
    const totals = regKey
      ? (() => {
          const rows = slice.map(d => d.region[regKey]); const im = sum(rows.map(x => x.im));
          const llmRows = slice.map(d => {
            const dayFrac = 1 / MONTH_INFO[d.mi].days;
            const monthLlm = (LLM_REGION_MONTHLY[regKey] || [])[d.mi] || { s: 0 };
            return monthLlm.s * dayFrac;
          });
          return { sessions: sum(rows.map(x => x.s)), views: sum(rows.map(x => x.v)), clicks: sum(rows.map(x => x.ck)), impr: im, conv: sum(rows.map(x => x.c)), llm: sum(llmRows) };
        })()
      : { sessions: sum(slice.map(r => r.sessions)), views: sum(slice.map(r => r.views)), clicks: sum(slice.map(r => r.clicks)), impr: sum(slice.map(r => r.impr)), conv: sum(slice.map(r => r.conv)), llm: sum(slice.map(r => r.llm)) };
    const regions = ["USA", "MENA", "Europe", "RoW"].map(r => {
      const rows = slice.map(d => d.region[r]); const im = sum(rows.map(x => x.im));
      const sess = sum(rows.map(x => x.s));
      return { region: r, sessions: sess, users: sum(rows.map(x => x.u)), views: sum(rows.map(x => x.v)), impr: im, clicks: sum(rows.map(x => x.ck)), conv: sum(rows.map(x => x.c)), eng: sess ? sum(rows.map(x => x.e)) / sess : 0, pos: im ? sum(rows.map(x => x.im * x.p)) / im : 0 };
    });
    const llmTotals = regKey
      ? (LLM_SOURCE_BY_REGION[regKey] || [])
      : LLM_SRC.map(src => ({ src, sessions: sum(llmMonthly.map(x => x[src])) }));
    const llmTotal = sum(llmTotals.map(x => x.sessions));
    return { monthly, viewsRegion, llmMonthly, totals, regions, llmTotals, llmTotal };
  }, [data, loIdx, hiIdx, region]);

  const refresh = async () => {
    if (syncing) return; setSyncing(true);
    try { await fetch(`${API}/api/sync`, { method: "POST" }); } catch { /* ignore */ }
    try { await load(); } catch { /* ignore */ }
    setSyncing(false);
  };

  if (!data) {
    return err
      ? <div style={{ minHeight: "100vh", display: "grid", placeItems: "center", background: C.paper, fontFamily: SANS, color: C.rust, padding: 30, textAlign: "center" }}>{err}</div>
      : <Loader />;
  }

  const setRange = (a, b) => { setFromDate(a); setToDate(b); };
  const lastN = (n) => DAILY[Math.max(0, DAILY.length - n)].date;
  const PRESETS = [
    { label: "Full window", a: DATE_MIN, b: DATE_MAX },
    { label: "Last 30 days", a: lastN(30), b: DATE_MAX },
    { label: "Last 7 days", a: lastN(7), b: DATE_MAX },
    { label: "This month", a: isoDate(MONTH_INFO.length - 1, 1), b: DATE_MAX },
  ];

  const tabProps = {
    overview: { monthly: D.monthly, viewsRegion: D.viewsRegion, totals: D.totals, range: rangeLabel, region, regions: D.regions },
    content: { region },
    top: { region },
    gap: { region },
    llm: { llmMonthly: D.llmMonthly, llmTotals: D.llmTotals, total: D.llmTotal, region },
  };
  const TABS = { overview: Overview, content: Content, top: TopPages, llm: LLM, gap: Opportunities, inbound: Inbound };
  const Active = TABS[tab];

  return (
    <div style={{ display: "flex", minHeight: "100vh", background: C.paper, color: C.text, fontFamily: SANS }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600;700&display=swap');
        *{box-sizing:border-box} body{margin:0}
        ::-webkit-scrollbar{height:8px;width:8px}::-webkit-scrollbar-thumb{background:#cfcabe;border-radius:8px}
        .navbtn{transition:background .15s,color .15s} .navbtn:hover{background:rgba(255,255,255,.06)}
        .spin{animation:sp 1s linear infinite}@keyframes sp{to{transform:rotate(360deg)}}
        .fade{animation:fd .35s ease}@keyframes fd{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
        input[type=date]{font-family:'IBM Plex Mono',monospace;font-size:12px;color:#1B1E24;background:#FFFFFF;border:1px solid #E6E2D8;border-radius:6px;padding:5px 7px;cursor:pointer}
        @media(max-width:880px){.grid-2{grid-template-columns:1fr !important}.sidebar{display:none}}
      `}</style>

      <aside className="sidebar" style={{ width: 220, background: C.ink, color: "#E8E6E0", display: "flex", flexDirection: "column", position: "sticky", top: 0, height: "100vh" }}>
        <div style={{ padding: "22px 20px 18px" }}>
          <div style={{ fontFamily: MONO, fontWeight: 700, fontSize: 17, letterSpacing: 1, color: "#fff" }}>tkxel<span style={{ color: C.sageHi }}>.</span></div>
          <div style={{ fontFamily: SANS, fontSize: 10.5, color: "#8A8B86", letterSpacing: 1.5, textTransform: "uppercase", marginTop: 3 }}>Content Intelligence</div>
        </div>
        <nav style={{ display: "flex", flexDirection: "column", gap: 2, padding: "4px 12px" }}>
          {NAV.map(n => {
            const on = tab === n.id;
            return (<button key={n.id} className="navbtn" onClick={() => setTab(n.id)} style={{ display: "flex", alignItems: "center", gap: 11, padding: "10px 12px", borderRadius: 8, border: "none", cursor: "pointer", textAlign: "left", background: on ? C.sage : "transparent", color: on ? "#fff" : "#C7C6C0", fontFamily: SANS, fontSize: 13, fontWeight: on ? 600 : 500 }}><n.Icon size={16} strokeWidth={2} />{n.label}</button>);
          })}
        </nav>
        <div style={{ marginTop: "auto", padding: 16, borderTop: "1px solid rgba(255,255,255,.08)", fontFamily: SANS, fontSize: 11, color: "#8A8B86" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 6, height: 6, borderRadius: 6, background: C.sageHi }} className={syncing ? "spin" : ""} />Live · BigQuery</div>
          <div style={{ marginTop: 4, fontFamily: MONO }}>data as of {asOf}</div>
        </div>
      </aside>

      <main style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
        <header style={{ display: "flex", flexDirection: "column", gap: 10, padding: "14px 26px", borderBottom: `1px solid ${C.border}`, background: "rgba(246,245,241,.85)", backdropFilter: "blur(6px)", position: "sticky", top: 0, zIndex: 5 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
            <div>
              <div style={{ fontSize: 16, fontWeight: 700 }}>{NAV.find(n => n.id === tab).label}</div>
              <div style={{ fontSize: 11.5, color: C.muted }}>tkxel.com · {rangeLabel} <span style={{ color: C.faint }}>({spanDays} day{spanDays !== 1 ? "s" : ""})</span>{region !== "All" && <span style={{ color: C.sage, fontWeight: 600 }}> · {region}</span>}</div>
            </div>
            <div style={{ marginLeft: "auto" }}>
              <button onClick={refresh} style={{ display: "flex", alignItems: "center", gap: 7, padding: "9px 14px", borderRadius: 8, border: `1px solid ${C.sage}`, background: syncing ? C.sageSoft : C.sage, color: syncing ? C.sage : "#fff", fontFamily: SANS, fontSize: 12.5, fontWeight: 600, cursor: "pointer" }}><RefreshCw size={14} className={syncing ? "spin" : ""} />{syncing ? "Syncing…" : "Refresh"}</button>
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 4, padding: "4px", border: `1px solid ${C.border}`, borderRadius: 8, background: C.card }}>
              <Globe2 size={13} color={C.sage} style={{ marginLeft: 6 }} />
              {REGION_OPTS.map(r => {
                const on = region === r;
                return <button key={r} onClick={() => setRegion(r)} style={{ fontFamily: SANS, fontSize: 11.5, padding: "6px 9px", borderRadius: 6, border: "none", background: on ? (r === "All" ? C.sage : SERIES[r]) : "transparent", color: on ? "#fff" : C.muted, cursor: "pointer", fontWeight: on ? 600 : 500 }}>{r}</button>;
              })}
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 10px", border: `1px solid ${C.border}`, borderRadius: 8, background: C.card }}>
              <Calendar size={14} color={C.sage} />
              <input type="date" value={fromDate} min={DATE_MIN} max={DATE_MAX} onChange={e => setFromDate(e.target.value)} />
              <ArrowRight size={12} color={C.faint} />
              <input type="date" value={toDate} min={DATE_MIN} max={DATE_MAX} onChange={e => setToDate(e.target.value)} />
            </div>
            <div style={{ display: "flex", gap: 6 }}>
              {PRESETS.map(p => {
                const on = fromDate === p.a && toDate === p.b;
                return <button key={p.label} onClick={() => setRange(p.a, p.b)} style={{ fontFamily: SANS, fontSize: 11.5, padding: "6px 10px", borderRadius: 7, border: `1px solid ${on ? C.sage : C.border}`, background: on ? C.sage : C.card, color: on ? "#fff" : C.muted, cursor: "pointer", fontWeight: on ? 600 : 500 }}>{p.label}</button>;
              })}
            </div>
          </div>
        </header>
        <div key={tab + fromDate + toDate + region} className="fade" style={{ padding: 24, maxWidth: 1180, width: "100%" }}><Active {...(tabProps[tab] || {})} /></div>
        <div style={{ padding: "0 24px 26px", fontFamily: SANS, fontSize: 11, color: C.faint }}>
          Live from BigQuery (mkt-data-wh) · GA4 + GSC + Pardot + SDR tracker. Monthly grain interpolated to days for the range demo. Date range and region drive Overview, Content, Top Pages, Opportunities &amp; LLM Traffic (category/source level; the by-source monthly trend and page-level LLM table stay global — per-region-per-source counts are too sparse to split honestly). Inbound Funnel is global-only (Pardot has no region field). "Refresh" triggers the real sync. Funnel stages span GA4 · Pardot · SDR tracker and are not expected to reconcile.
        </div>
      </main>
    </div>
  );
}
