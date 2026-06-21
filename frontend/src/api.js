// All fetch calls in one place.
const BASE = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/$/, "");

function qs(params = {}) {
  const clean = Object.fromEntries(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "" && v !== "All")
  );
  const s = new URLSearchParams(clean).toString();
  return s ? `?${s}` : "";
}

async function get(path, params) {
  const res = await fetch(`${BASE}${path}${qs(params)}`);
  if (!res.ok) throw new Error(`${path} -> ${res.status} ${res.statusText}`);
  return res.json();
}

export const api = {
  base: BASE,
  health: () => get("/health"),
  status: () => get("/api/status"),
  sync: () => fetch(`${BASE}/api/sync`, { method: "POST" }).then((r) => r.json()),
  regional: (p) => get("/api/regional", p),
  categories: (p) => get("/api/categories", p),
  topPages: (p) => get("/api/top-pages", p),
  llm: (p) => get("/api/llm", p),
  gap: (p) => get("/api/gap", p),
  inbound: () => get("/api/inbound"),
  mql: () => get("/api/mql"),
  funnel: (p) => get("/api/funnel", p),
};
