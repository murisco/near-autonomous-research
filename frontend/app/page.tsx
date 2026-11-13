"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

type DashboardData = {
  orders: number;
  reports_generated: number;
  quoted_sales_usd: number;
  revenue_received_usd: number;
  simulated_inference_spend_usd: number;
  projected_profit_usd: number;
  today_inference_budget_usd: number;
  today_inference_spend_usd: number;
  payments_enabled: boolean;
  mainnet_execution_enabled: boolean;
  data_mode: string;
  research_mode: string;
};

type Order = {
  id: string;
  topic: string;
  price_usd: number;
  inference_cost_usd: number;
  projected_profit_usd: number;
  status: string;
  data_mode: string;
  created_at: string;
};

type Report = { id: string; title: string; markdown: string; data_mode: string };
type LedgerEvent = {
  id: number;
  order_id: string | null;
  event_type: string;
  details: Record<string, unknown>;
  created_at: string;
  record_type: string;
};

type Rules = {
  limits: { max_inference_spend_per_day: number; minimum_report_price: number };
  revenue_split: { operator_percent: number; contributors_percent: number };
  safety: {
    kill_switch: boolean;
    payments_enabled: boolean;
    mainnet_execution_enabled: boolean;
    require_human_approval_for_payouts: boolean;
  };
};

const money = (value: number) =>
  "$" + Number(value || 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const prettyDate = (value: string) =>
  new Date(value).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch("/api/" + path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options?.headers || {}) },
    cache: "no-store",
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || "The request could not be completed.");
  }
  return payload as T;
}

export default function Home() {
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [orders, setOrders] = useState<Order[]>([]);
  const [events, setEvents] = useState<LedgerEvent[]>([]);
  const [rules, setRules] = useState<Rules | null>(null);
  const [topic, setTopic] = useState("Assess NEAR's autonomous business infrastructure and ecosystem activity");
  const [price, setPrice] = useState("10");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [activeTab, setActiveTab] = useState<"orders" | "ledger">("orders");
  const [selectedReport, setSelectedReport] = useState<Report | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [summary, orderData, ledgerData, policy] = await Promise.all([
        api<DashboardData>("dashboard"),
        api<{ items: Order[] }>("orders?limit=8"),
        api<{ items: LedgerEvent[] }>("ledger?limit=10"),
        api<Rules>("rules"),
      ]);
      setDashboard(summary);
      setOrders(orderData.items || []);
      setEvents(ledgerData.items || []);
      setRules(policy);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to connect to the backend.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function submitOrder(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    setSelectedReport(null);
    try {
      const result = await api<Order & { report: Report }>("orders", {
        method: "POST",
        body: JSON.stringify({ topic, price_usd: Number(price) }),
      });
      setSelectedReport(result.report);
      setNotice(result.data_mode === "synthetic_demo" ? "Demo report generated. No payment was taken and no blockchain transaction was sent." : "Live-source research report generated. No payment was taken and no blockchain transaction was sent.");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create this research order.");
    } finally {
      setBusy(false);
    }
  }

  async function openReport(orderId: string) {
    setError("");
    try {
      const result = await api<Order & { report?: Report }>("orders/" + orderId);
      if (result.report) setSelectedReport(result.report);
      else setError("This order does not have a report attached.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the report.");
    }
  }

  const budgetUsed = dashboard
    ? Math.min(100, (dashboard.today_inference_spend_usd / Math.max(0.01, dashboard.today_inference_budget_usd)) * 100)
    : 0;

  return (
    <main className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">M</div>
          <div>
            <div className="brand-name">MERIDIAN</div>
            <div className="brand-caption">AUTONOMOUS BUSINESS</div>
          </div>
        </div>
        <div className="workspace-label">WORKSPACE</div>
        <div className="side-link active"><span className="side-icon">◫</span> Overview</div>
        <button className="side-link" onClick={() => setActiveTab("orders")}><span className="side-icon">▤</span> Research orders</button>
        <button className="side-link" onClick={() => setActiveTab("ledger")}><span className="side-icon">◎</span> Audit ledger</button>
        <div className="sidebar-bottom">
          <div className="near-chip"><span className="near-dot" /> BUILT FOR NEAR</div>
          <div className="sidebar-note">An AI-native research business with human-defined limits.</div>
          <div className="version">HACKATHON MVP · v0.1</div>
        </div>
      </aside>

      <section className="main-area">
        <header className="topbar">
          <div>
            <div className="eyebrow">AUTONOMOUS BUSINESS / CONTROL ROOM</div>
            <h1>Business overview</h1>
          </div>
          <div className="top-actions">
            <span className="demo-pill"><span /> {dashboard?.research_mode === "live" ? "LIVE RESEARCH" : "DEMO MODE"}</span>
            <button className="refresh-button" onClick={() => void refresh()} aria-label="Refresh dashboard">↻</button>
          </div>
        </header>

        {error && <div className="alert error-alert">{error}</div>}
        {notice && <div className="alert notice-alert">{notice}</div>}

        <div className="status-strip">
          <div className="status-title"><span className="status-dot" /> SYSTEM STATUS</div>
          <div className="status-item">Research engine <strong>{dashboard?.research_mode === "live" ? "Live data" : "Synthetic demo"}</strong></div>
          <div className="status-item">Payments <strong className="off">Disabled</strong></div>
          <div className="status-item">Mainnet execution <strong className="off">Disabled</strong></div>
          <div className="status-item">Safety gate <strong className="on">Active</strong></div>
        </div>

        <section className="metrics-grid">
          <Metric label="Research orders" value={dashboard ? String(dashboard.orders) : "—"} helper="All time" icon="▤" />
          <Metric label="Reports generated" value={dashboard ? String(dashboard.reports_generated) : "—"} helper="Demo reports" icon="▧" />
          <Metric label="Quoted sales" value={dashboard ? money(dashboard.quoted_sales_usd) : "—"} helper="Not collected revenue" icon="$" />
          <Metric label="Revenue received" value={dashboard ? money(dashboard.revenue_received_usd) : "—"} helper="No real payments" icon="↗" />
        </section>

        <div className="content-grid">
          <section className="panel order-panel">
            <div className="panel-heading">
              <div>
                <div className="eyebrow">RESEARCH DESK</div>
                <h2>Create a report</h2>
              </div>
              <span className="mini-tag">NEW ORDER</span>
            </div>
            <p className="panel-subtitle">Turn a research question into a structured onchain intelligence brief.</p>
            <form onSubmit={submitOrder} className="order-form">
              <label htmlFor="topic">Research question</label>
              <textarea id="topic" value={topic} onChange={(event) => setTopic(event.target.value)} minLength={8} maxLength={500} required />
              <div className="form-row">
                <div className="price-field">
                  <label htmlFor="price">Report quote (USD)</label>
                  <div className="input-wrap"><span>$</span><input id="price" type="number" min={rules?.limits.minimum_report_price ?? 10} step="0.5" value={price} onChange={(event) => setPrice(event.target.value)} required /></div>
                </div>
                <div className="price-hint">Minimum quote<br /><strong>{money(rules?.limits.minimum_report_price ?? 10)}</strong></div>
              </div>
              <button type="submit" className="primary-button" disabled={busy || loading}>
                {busy ? <><span className="spinner" /> Generating report...</> : <>Generate research report <span>↗</span></>}
              </button>
              <p className="form-footnote">{dashboard?.research_mode === "live" ? "Uses live public chain TVL data. NEAR AI Cloud analysis is added when its API key is configured. No customer payment is collected." : "Uses clearly labelled synthetic demo data. No customer payment or blockchain transaction is made."}</p>
            </form>
          </section>

          <section className="panel economics-panel">
            <div className="panel-heading">
              <div>
                <div className="eyebrow">UNIT ECONOMICS</div>
                <h2>Business performance</h2>
              </div>
              <span className="chart-icon">⌁</span>
            </div>
            <div className="economics-list">
              <Economics label="Simulated inference spend" value={dashboard ? money(dashboard.simulated_inference_spend_usd) : "—"} />
              <Economics label="Projected profit" value={dashboard ? money(dashboard.projected_profit_usd) : "—"} />
              <Economics label="Operator share" value={rules ? rules.revenue_split.operator_percent + "%" : "—"} />
              <Economics label="Contributor share" value={rules ? rules.revenue_split.contributors_percent + "%" : "—"} />
            </div>
            <div className="budget-block">
              <div className="budget-head"><span>Daily inference budget</span><strong>{dashboard ? money(dashboard.today_inference_spend_usd) + " / " + money(dashboard.today_inference_budget_usd) : "—"}</strong></div>
              <div className="budget-track"><div className="budget-fill" style={{ width: budgetUsed + "%" }} /></div>
              <div className="budget-caption">Spend is estimated for demo runs and blocked at the configured daily limit.</div>
            </div>
          </section>
        </div>

        {selectedReport && (
          <section className="panel report-panel">
            <div className="panel-heading">
              <div>
                <div className="eyebrow">GENERATED OUTPUT · {selectedReport.data_mode.toUpperCase().replaceAll("_", " ")}</div>
                <h2>{selectedReport.title}</h2>
              </div>
              <button className="close-button" onClick={() => setSelectedReport(null)}>Close ×</button>
            </div>
            <pre className="report-content">{selectedReport.markdown}</pre>
          </section>
        )}

        <section className="panel activity-panel">
          <div className="panel-heading activity-heading">
            <div>
              <div className="eyebrow">BUSINESS ACTIVITY</div>
              <h2>Orders &amp; audit trail</h2>
            </div>
            <div className="tabs">
              <button className={activeTab === "orders" ? "tab active-tab" : "tab"} onClick={() => setActiveTab("orders")}>Orders</button>
              <button className={activeTab === "ledger" ? "tab active-tab" : "tab"} onClick={() => setActiveTab("ledger")}>Audit ledger</button>
            </div>
          </div>

          {activeTab === "orders" ? (
            <div className="table-wrap">
              <table>
                <thead><tr><th>RESEARCH TOPIC</th><th>QUOTE</th><th>STATUS</th><th>CREATED</th><th /></tr></thead>
                <tbody>
                  {orders.length === 0 ? <tr><td colSpan={5} className="empty-cell">{loading ? "Loading orders..." : "No research orders yet. Create your first demo report above."}</td></tr> :
                    orders.map((order) => (
                      <tr key={order.id}>
                        <td className="topic-cell">{order.topic}</td>
                        <td>{money(order.price_usd)}</td>
                        <td><span className="order-status">{order.status.replaceAll("_", " ")}</span></td>
                        <td className="date-cell">{prettyDate(order.created_at)}</td>
                        <td><button className="view-button" onClick={() => void openReport(order.id)}>View report</button></td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="ledger-list">
              {events.length === 0 ? <div className="empty-cell">{loading ? "Loading audit events..." : "No business events have been recorded yet."}</div> :
                events.map((event) => (
                  <div className="ledger-row" key={event.id}>
                    <div className="ledger-marker" />
                    <div className="ledger-main"><strong>{event.event_type.replaceAll("_", " ")}</strong><span>{event.order_id ? "Order " + event.order_id.slice(0, 8) : "System event"}</span></div>
                    <time>{prettyDate(event.created_at)}</time>
                  </div>
                ))}
            </div>
          )}
        </section>

        <footer className="footer">
          <span>MERIDIAN · AUTONOMOUS RESEARCH BUSINESS</span>
          <span>DEMO MODE ONLY · NOT CONNECTED TO LIVE FUNDS</span>
        </footer>
      </section>
    </main>
  );
}

function Metric({ label, value, helper, icon }: { label: string; value: string; helper: string; icon: string }) {
  return (
    <div className="metric-card">
      <div className="metric-top"><span>{label}</span><div className="metric-icon">{icon}</div></div>
      <div className="metric-value">{value}</div>
      <div className="metric-helper">{helper}</div>
    </div>
  );
}

function Economics({ label, value }: { label: string; value: string }) {
  return <div className="economics-row"><span>{label}</span><strong>{value}</strong></div>;
}
