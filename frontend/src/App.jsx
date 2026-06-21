import { useMemo, useState } from "react";
import {
  ResponsiveContainer, LineChart, Line, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, Tooltip, CartesianGrid, Legend,
} from "recharts";
import {
  Activity, RefreshCw, Globe, FileText, TrendingUp, Search, Bot, Filter,
} from "lucide-react";
import { api } from "./api.js";
import { useData } from "./useData.js";

const REGIONS = ["All", "USA", "UK", "Canada", "Australia", "Middle East",
  "South Asia", "Europe", "APAC", "Other"];
const MONTHS = ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"];
const COLORS = ["#5b8cff", "#22d3ee", "#34d399", "#fbbf24", "#f87171", "#a78bfa", "#f472b6", "#60a5fa"];

const TABS = [
  { id: "overview", label: "Overview", icon: Activity },
  { id: "content", label: "Content", icon: FileText },
  { id: "pages", label: "Top Pages", icon: Globe },
  { id: "gap", label: "Opportunities", icon: Search },
  { id: "llm", label: "LLM Traffic", icon: Bot },
  { id: "funnel", label: "Inbound Funnel", icon: TrendingUp },
];

const nf = new Intl.NumberFormat("en-US");
const fmt = (n) => (n == null ? "—" : nf.format(Math.round(n)));
const pct = (n) => (n == null ? "—" : `${(n * 100).toFixed(1)}%`);

function Loading() {
  return <div className="state"><span className="spinner" /> Loading…</div>;
}
function ErrorState({ error }) {
  return <div className="state error">Failed to load: {error}</div>;
}
function Empty({ msg = "No data yet — run a sync." }) {
  return <div className="state">{msg}</div>;
}

function Card({ label, value, sub }) {
  return (
    <div className="card">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  );
}

// ---------------------------------------------------------------------------
function Overview({ region, from, to }) {
  const { data, loading, error } = useData(
    () => api.regional({ region, from, to }),
    [region, from, to]
  );
  if (loading) return <Loading />;
  if (error) return <ErrorState error={error} />;
  const rows = data?.rows || [];
  if (!rows.length) return <Empty />;

  const totals = rows.reduce(
    (a, r) => ({
      sessions: a.sessions + Number(r.sessions || 0),
      users: a.users + Number(r.users || 0),
      conversions: a.conversions + Number(r.conversions || 0),
      clicks: a.clicks + Number(r.clicks || 0),
      impressions: a.impressions + Number(r.impressions || 0),
    }),
    { sessions: 0, users: 0, conversions: 0, clicks: 0, impressions: 0 }
  );

  // sessions by month (sum across regions)
  const byMonth = {};
  rows.forEach((r) => {
    byMonth[r.month] = byMonth[r.month] || { month: r.month, sessions: 0, clicks: 0 };
    byMonth[r.month].sessions += Number(r.sessions || 0);
    byMonth[r.month].clicks += Number(r.clicks || 0);
  });
  const trend = Object.values(byMonth).sort((a, b) => a.month.localeCompare(b.month));

  // sessions by region
  const byRegion = {};
  rows.forEach((r) => {
    byRegion[r.region] = (byRegion[r.region] || 0) + Number(r.sessions || 0);
  });
  const regionData = Object.entries(byRegion)
    .map(([name, value]) => ({ name, value }))
    .sort((a, b) => b.value - a.value);

  const ctr = totals.impressions ? totals.clicks / totals.impressions : null;

  return (
    <>
      <div className="grid cards">
        <Card label="Sessions" value={fmt(totals.sessions)} />
        <Card label="Users" value={fmt(totals.users)} />
        <Card label="Conversions" value={fmt(totals.conversions)} />
        <Card label="GSC Clicks" value={fmt(totals.clicks)} sub={`${fmt(totals.impressions)} impressions`} />
        <Card label="Search CTR" value={pct(ctr)} />
      </div>

      <div className="panel">
        <h3>Sessions & Search Clicks by Month</h3>
        <ResponsiveContainer width="100%" height={280}>
          <LineChart data={trend} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="#28304a" strokeDasharray="3 3" />
            <XAxis dataKey="month" stroke="#93a0bd" />
            <YAxis stroke="#93a0bd" />
            <Tooltip contentStyle={{ background: "#151b2e", border: "1px solid #28304a" }} />
            <Legend />
            <Line type="monotone" dataKey="sessions" stroke="#5b8cff" strokeWidth={2} dot={false} />
            <Line type="monotone" dataKey="clicks" stroke="#22d3ee" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="panel">
        <h3>Sessions by Region</h3>
        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={regionData} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="#28304a" strokeDasharray="3 3" />
            <XAxis dataKey="name" stroke="#93a0bd" />
            <YAxis stroke="#93a0bd" />
            <Tooltip contentStyle={{ background: "#151b2e", border: "1px solid #28304a" }} />
            <Bar dataKey="value" radius={[6, 6, 0, 0]}>
              {regionData.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
function Content({ region }) {
  const { data, loading, error } = useData(() => api.categories({ region }), [region]);
  if (loading) return <Loading />;
  if (error) return <ErrorState error={error} />;
  const rows = (data?.rows || []).slice().sort((a, b) => Number(b.sessions) - Number(a.sessions));
  if (!rows.length) return <Empty />;

  const pieData = rows.map((r) => ({ name: r.category, value: Number(r.sessions || 0) }));

  return (
    <>
      <div className="panel">
        <h3>Sessions by Content Category</h3>
        <ResponsiveContainer width="100%" height={300}>
          <PieChart>
            <Pie data={pieData} dataKey="value" nameKey="name" outerRadius={110} label>
              {pieData.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
            </Pie>
            <Tooltip contentStyle={{ background: "#151b2e", border: "1px solid #28304a" }} />
            <Legend />
          </PieChart>
        </ResponsiveContainer>
      </div>
      <div className="panel">
        <h3>Category Breakdown</h3>
        <table>
          <thead>
            <tr><th>Category</th><th className="num">Sessions</th><th className="num">Users</th><th className="num">Pages</th></tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.category}>
                <td>{r.category}</td>
                <td className="num">{fmt(r.sessions)}</td>
                <td className="num">{fmt(r.users)}</td>
                <td className="num">{fmt(r.pages)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
function TopPages({ region }) {
  const [category, setCategory] = useState("All");
  const cats = useData(() => api.categories({ region }), [region]);
  const { data, loading, error } = useData(
    () => api.topPages({ region, category, limit: 100 }),
    [region, category]
  );
  const catOptions = ["All", ...new Set((cats.data?.rows || []).map((r) => r.category))];

  return (
    <>
      <div className="controls" style={{ marginBottom: 12 }}>
        <Filter size={16} className="muted" />
        <select value={category} onChange={(e) => setCategory(e.target.value)}>
          {catOptions.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </div>
      {loading ? <Loading /> : error ? <ErrorState error={error} /> : (
        <div className="panel">
          <h3>Top Pages {category !== "All" && `· ${category}`}</h3>
          {!(data?.rows || []).length ? <Empty /> : (
            <table>
              <thead>
                <tr>
                  <th>Page</th><th>Category</th>
                  <th className="num">Sessions</th><th className="num">Clicks</th>
                  <th className="num">Impr.</th><th className="num">Avg Pos.</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r) => (
                  <tr key={`${r.region}-${r.category}-${r.page_path}`}>
                    <td title={r.page_title || ""}>{r.page_path}</td>
                    <td>{r.category}</td>
                    <td className="num">{fmt(r.sessions)}</td>
                    <td className="num">{fmt(r.clicks)}</td>
                    <td className="num">{fmt(r.impressions)}</td>
                    <td className="num">{Number(r.avg_position || 0).toFixed(1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
function Opportunities({ region }) {
  const { data, loading, error } = useData(() => api.gap({ region, limit: 100 }), [region]);
  if (loading) return <Loading />;
  if (error) return <ErrorState error={error} />;
  const rows = data?.rows || [];
  if (!rows.length) return <Empty />;
  return (
    <div className="panel">
      <h3>Content Gap Opportunities</h3>
      <div className="scope-note">High-impression queries with weak CTR or rankable position (4–20). Sorted by opportunity score.</div>
      <table>
        <thead>
          <tr>
            <th>Query</th><th>Page</th>
            <th className="num">Impr.</th><th className="num">Clicks</th>
            <th className="num">CTR</th><th className="num">Avg Pos.</th><th className="num">Score</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.query}>
              <td>{r.query}</td>
              <td className="muted">{r.page_path}</td>
              <td className="num">{fmt(r.impressions)}</td>
              <td className="num">{fmt(r.clicks)}</td>
              <td className="num">{pct(Number(r.ctr))}</td>
              <td className="num">{Number(r.avg_position || 0).toFixed(1)}</td>
              <td className="num"><strong>{fmt(r.opportunity)}</strong></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
function LLMTraffic() {
  const { data, loading, error } = useData(() => api.llm(), []);
  if (loading) return <Loading />;
  if (error) return <ErrorState error={error} />;
  const bySource = data?.by_source || [];
  const rows = data?.rows || [];
  if (!bySource.length) return <Empty msg="No AI/LLM referral traffic recorded yet." />;

  const barData = bySource.map((s) => ({ name: s.source, sessions: Number(s.sessions || 0) }));

  return (
    <>
      <div className="scope-note">LLM traffic is global only — per-region counts are too sparse to split honestly.</div>
      <div className="panel">
        <h3>Sessions by AI Source</h3>
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={barData} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="#28304a" strokeDasharray="3 3" />
            <XAxis dataKey="name" stroke="#93a0bd" />
            <YAxis stroke="#93a0bd" />
            <Tooltip contentStyle={{ background: "#151b2e", border: "1px solid #28304a" }} />
            <Bar dataKey="sessions" radius={[6, 6, 0, 0]}>
              {barData.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="panel">
        <h3>Top Pages from AI Referrals</h3>
        <table>
          <thead>
            <tr><th>Source</th><th>Page</th><th>Month</th><th className="num">Sessions</th><th className="num">Users</th></tr>
          </thead>
          <tbody>
            {rows.slice(0, 100).map((r, i) => (
              <tr key={i}>
                <td>{r.source}</td>
                <td className="muted">{r.page_path}</td>
                <td>{r.month}</td>
                <td className="num">{fmt(r.sessions)}</td>
                <td className="num">{fmt(r.users)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
function InboundFunnel({ from, to }) {
  const funnel = useData(() => api.funnel({ from, to }), [from, to]);
  const inbound = useData(() => api.inbound(), []);
  const mql = useData(() => api.mql(), []);

  if (funnel.loading || inbound.loading || mql.loading) return <Loading />;
  if (funnel.error) return <ErrorState error={funnel.error} />;

  const stages = funnel.data?.stages || [];
  const genuine = inbound.data?.genuine || [];
  const summary = inbound.data?.summary || [];
  const mqlRows = mql.data?.rows || [];

  return (
    <>
      <div className="scope-note">Inbound funnel is global only — Pardot has no region field.</div>
      <div className="grid cards">
        {stages.map((s) => <Card key={s.stage} label={s.stage} value={fmt(s.count)} />)}
      </div>

      <div className="panel">
        <h3>Funnel</h3>
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={stages} layout="vertical" margin={{ top: 8, right: 24, bottom: 0, left: 90 }}>
            <CartesianGrid stroke="#28304a" strokeDasharray="3 3" />
            <XAxis type="number" stroke="#93a0bd" />
            <YAxis type="category" dataKey="stage" stroke="#93a0bd" width={90} />
            <Tooltip contentStyle={{ background: "#151b2e", border: "1px solid #28304a" }} />
            <Bar dataKey="count" radius={[0, 6, 6, 0]}>
              {stages.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
        <div className="scope-note">
          Lead segments: {summary.map((s) => `${s.segment} ${s.count}`).join(" · ") || "none"}
        </div>
      </div>

      <div className="panel">
        <h3>Matched MQLs ({mql.data?.matched || 0} of {mql.data?.total || 0})</h3>
        {!mqlRows.length ? <Empty /> : (
          <table>
            <thead>
              <tr><th>Email</th><th>Name</th><th>Company</th><th>Status</th><th>Owner</th><th>Matched</th></tr>
            </thead>
            <tbody>
              {mqlRows.slice(0, 100).map((r) => (
                <tr key={r.email}>
                  <td>{r.email}</td>
                  <td>{r.name || "—"}</td>
                  <td>{r.company || "—"}</td>
                  <td>{r.status || "—"}</td>
                  <td>{r.owner || "—"}</td>
                  <td>{r.matched_lead
                    ? <span className="badge good">matched</span>
                    : <span className="badge warn">unmatched</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="panel">
        <h3>Recent Genuine Leads</h3>
        {!genuine.length ? <Empty /> : (
          <table>
            <thead>
              <tr><th>Email</th><th>Description</th><th>Domain</th><th>Received</th></tr>
            </thead>
            <tbody>
              {genuine.slice(0, 100).map((r, i) => (
                <tr key={i}>
                  <td>{r.email}</td>
                  <td className="muted">{r.description}</td>
                  <td>{r.domain}</td>
                  <td>{r.received_at ? new Date(r.received_at).toLocaleDateString() : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
export default function App() {
  const [tab, setTab] = useState("overview");
  const [region, setRegion] = useState("All");
  const [from, setFrom] = useState(MONTHS[0]);
  const [to, setTo] = useState(MONTHS[MONTHS.length - 1]);
  const [syncing, setSyncing] = useState(false);

  const status = useData(() => api.status(), []);
  const asOf = useMemo(() => {
    const workers = status.data?.workers || [];
    const times = workers.map((w) => w.last_ok_at).filter(Boolean).sort();
    return times.length ? new Date(times[times.length - 1]).toLocaleString() : "never";
  }, [status.data]);

  const anyStale = (status.data?.workers || []).some((w) => w.stale);

  async function doSync() {
    setSyncing(true);
    try {
      await api.sync();
      // Poll status a few times so "data as of" updates once workers finish.
      setTimeout(() => status.refetch(), 8000);
    } finally {
      setTimeout(() => setSyncing(false), 8000);
    }
  }

  const showFilters = tab !== "llm"; // LLM tab is global, no region/date
  const showRegion = !["llm", "funnel"].includes(tab);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand"><span className="dot" /> Tkxel Content Intelligence</div>
        <div className="controls">
          {showRegion && (
            <select value={region} onChange={(e) => setRegion(e.target.value)} title="Region">
              {REGIONS.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          )}
          {showFilters && (
            <>
              <select value={from} onChange={(e) => setFrom(e.target.value)} title="From">
                {MONTHS.map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
              <span className="muted">→</span>
              <select value={to} onChange={(e) => setTo(e.target.value)} title="To">
                {MONTHS.map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
            </>
          )}
          <button className="primary" onClick={doSync} disabled={syncing}>
            <RefreshCw size={14} style={{ verticalAlign: "middle", marginRight: 6,
              animation: syncing ? "spin 0.8s linear infinite" : "none" }} />
            {syncing ? "Syncing…" : "Refresh"}
          </button>
        </div>
      </header>

      <div className="as-of">
        Data as of: <strong>{asOf}</strong>
        {anyStale && <span className="badge warn" style={{ marginLeft: 8 }}>some data stale</span>}
      </div>

      <div className="tabs">
        {TABS.map((t) => {
          const Icon = t.icon;
          return (
            <div key={t.id} className={`tab ${tab === t.id ? "active" : ""}`} onClick={() => setTab(t.id)}>
              <Icon size={14} style={{ verticalAlign: "middle", marginRight: 6 }} />
              {t.label}
            </div>
          );
        })}
      </div>

      {tab === "overview" && <Overview region={region} from={from} to={to} />}
      {tab === "content" && <Content region={region} />}
      {tab === "pages" && <TopPages region={region} />}
      {tab === "gap" && <Opportunities region={region} />}
      {tab === "llm" && <LLMTraffic />}
      {tab === "funnel" && <InboundFunnel from={from} to={to} />}
    </div>
  );
}
