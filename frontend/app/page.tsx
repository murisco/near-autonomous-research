"use client";

import { FormEvent, ReactNode, useCallback, useEffect, useRef, useState } from "react";

type DashboardData = {
  orders: number;
  reports_generated: number;
  quoted_sales_usd: number;
  revenue_received_usd: number;
  estimated_inference_spend_usd: number;
  projected_profit_usd: number;
  today_inference_budget_usd: number;
  today_estimated_inference_spend_usd: number;
  payments_enabled: boolean;
  mainnet_execution_enabled: boolean;
  data_mode: string;
  research_mode: string;
  near_ai_cloud_configured: boolean;
};

type AuthUser = { account_id: string; role: "admin" | "customer" };
type NearLoginChallenge = { challenge_id: string; nonce: string; message: string; recipient: string };

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
type PaymentQuote = {
  status: string;
  provider?: string;
  network?: string;
  reason?: string;
  note?: string;
  no_deposit_address: boolean;
  settlement: boolean;
  quote?: {
    amount_in_formatted?: string;
    amount_in_usd?: string;
    amount_out_formatted?: string;
    amount_out_usd?: string;
    time_estimate_seconds?: number;
  };
};
type LedgerEvent = {
  id: number;
  order_id: string | null;
  event_type: string;
  details: Record<string, unknown>;
  created_at: string;
  record_type: string;
};

type PublicMetric = {
  status: string;
  latest_day?: string;
  latest_day_value?: number;
  last_7d_total?: number;
  last_7d_days?: number;
  last_7d_vs_previous_7d_percent?: number | null;
  reason?: string;
};
type PublicProject = {
  name: string;
  description?: string | null;
  url?: string | null;
  language?: string | null;
  stars?: number | null;
  forks?: number | null;
  last_pushed_at?: string | null;
  classification?: string;
  readme_status?: string;
  recent_commits?: Array<{ date?: string | null; message?: string; url?: string }>;
};
type PublicIntelligence = {
  retrieved_at: string;
  network: {
    chain: string;
    tvl_usd: number | null;
    change_7d_percent: number | null;
    change_30d_percent: number | null;
    tvl_history: Array<{ date: string; tvl_usd: number }>;
    history_age_hours: number | null;
    top_protocols: Array<{ name: string; category: string; chain_tvl_usd: number }>;
    quality_warnings: string[];
    sources: string[];
  };
  activity: {
    status: string;
    transaction_stats: PublicMetric;
    address_stats: PublicMetric;
    sources: string[];
    attribution?: string;
  };
  stablecoins: {
    status: string;
    total_supply_usd: number | null;
    change_7d_percent: number | null;
    change_30d_percent: number | null;
    as_of?: string | null;
    asset_count?: number;
    sources: string[];
    reason?: string;
  };
  developers: {
    status: string;
    projects: PublicProject[];
    source?: string;
    limitations?: string;
  };
  thesis: {
    label: string;
    summary: string;
    signals: Array<{ name: string; period: string; change_percent: number | null; status: string; detail: string }>;
    method: string;
  };
  disclaimer: string;
};

const compactUsd = (value: number | null | undefined) => {
  if (value == null || !Number.isFinite(value)) return "Unavailable";
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", notation: "compact", maximumFractionDigits: 2 }).format(value);
};
const compactNumber = (value: number | null | undefined) =>
  value == null || !Number.isFinite(value) ? "Unavailable" : new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 2 }).format(value);
const signedPercent = (value: number | null | undefined) =>
  value == null || !Number.isFinite(value) ? "Unavailable" : (value > 0 ? "+" : "") + value.toFixed(2) + "%";

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

function downloadReport(report: Report) {
  const blob = new Blob([report.markdown], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  const safeTitle = report.title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 64) || "meridian-report";
  link.href = url;
  link.download = safeTitle + ".md";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const method = (options?.method || "GET").toUpperCase();
  const response = await fetch("/api/" + path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(method !== "GET" && method !== "HEAD" ? { "X-Meridian-Requested": "1" } : {}),
      ...(options?.headers || {}),
    },
    cache: "no-store",
    credentials: "same-origin",
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(payload.detail || "The request could not be completed.") as Error & { status?: number };
    error.status = response.status;
    throw error;
  }
  return payload as T;
}

export default function Home() {
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [orders, setOrders] = useState<Order[]>([]);
  const [events, setEvents] = useState<LedgerEvent[]>([]);
  const [rules, setRules] = useState<Rules | null>(null);
  const [topic, setTopic] = useState("");
  const [price, setPrice] = useState("10");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [activeTab, setActiveTab] = useState<"orders" | "ledger">("orders");
  const [selectedReport, setSelectedReport] = useState<Report | null>(null);
  const reportRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (selectedReport) {
      reportRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [selectedReport?.id]);
  const [paymentQuote, setPaymentQuote] = useState<PaymentQuote | null>(null);
  const [authUser, setAuthUser] = useState<AuthUser | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [authBusy, setAuthBusy] = useState(false);
  const [authMessage, setAuthMessage] = useState("");
  const [showAdminLogin, setShowAdminLogin] = useState(false);
  const [publicData, setPublicData] = useState<PublicIntelligence | null>(null);
  const [publicLoading, setPublicLoading] = useState(true);
  const [publicError, setPublicError] = useState("");

  const refresh = useCallback(async () => {
    try {
      const me = await api<AuthUser>("auth/me");
      setAuthUser(me);
      if (me.role === "admin") {
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
      } else {
        const [orderData, policy] = await Promise.all([
          api<{ items: Order[] }>("orders?limit=30"),
          api<Rules>("rules"),
        ]);
        setDashboard(null);
        setOrders(orderData.items || []);
        setEvents([]);
        setRules(policy);
      }
      setError("");
    } catch (err) {
      const status = (err as Error & { status?: number }).status;
      setAuthUser(null);
      setDashboard(null);
      setOrders([]);
      setEvents([]);
      if (status === 401) {
        setError("");
      } else {
        setError(err instanceof Error ? err.message : "Unable to connect to the backend.");
      }
    } finally {
      setLoading(false);
      setAuthLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const loadPublicIntelligence = useCallback(async (force = false) => {
    setPublicLoading(true);
    try {
      const query = force ? "?refresh=true" : "";
      const result = await api<PublicIntelligence>("public/intelligence" + query);
      setPublicData(result);
      setPublicError("");
    } catch (err) {
      setPublicError(err instanceof Error ? err.message : "Could not load live NEAR ecosystem data.");
    } finally {
      setPublicLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadPublicIntelligence();
  }, [loadPublicIntelligence]);

  async function submitOrder(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    setSelectedReport(null);
    try {
      const result = await api<Order & { report: Report; payment_quote?: PaymentQuote }>("orders", {
        method: "POST",
        body: JSON.stringify({ topic, price_usd: Number(price) }),
      });
      setSelectedReport(result.report);
      setPaymentQuote(result.payment_quote ?? null);
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
      const result = await api<Order & { report?: Report; payment_quote?: PaymentQuote }>("orders/" + orderId);
      if (result.report) {
        setSelectedReport(result.report);
        setPaymentQuote(result.payment_quote ?? null);
      }
      else setError("This order does not have a report attached.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the report.");
    }
  }

  async function signInWithNear() {
    setAuthBusy(true);
    let finishTimer: ReturnType<typeof setTimeout> | undefined;
    setError("");
    setAuthMessage("Preparing a one-time NEAR sign-in request...");
    try {
      const challenge = await api<NearLoginChallenge>("auth/nonce", {
        method: "POST",
        body: JSON.stringify({}),
      });
      const { NearConnector } = await import("@hot-labs/near-connect");
      const connector = new NearConnector({ features: { signMessage: true } });
      const signedEventPromise = new Promise<any>((resolve, reject) => {
        connector.on("wallet:signInAndSignMessage", (event: any) => resolve(event));
        finishTimer = setTimeout(() => reject(new Error("Wallet sign-in timed out. Please try again.")), 120000);
      });
      setAuthMessage("Choose your NEAR wallet and review the identity-only message.");
      await connector.connect({
        signMessageParams: {
          message: challenge.message,
          recipient: challenge.recipient,
          nonce: Uint8Array.from(atob(challenge.nonce), (character) => character.charCodeAt(0)),
        },
      });
      const signInEvent = await signedEventPromise;
      if (finishTimer) clearTimeout(finishTimer);
      const selectedAccount = signInEvent?.accounts?.[0];
      const signedMessage = selectedAccount?.signedMessage ?? signInEvent?.signedMessage;
      const accountId = selectedAccount?.accountId ?? signedMessage?.accountId;
      const rawPublicKey = signedMessage?.publicKey;
      const rawSignature = signedMessage?.signature;
      const publicKey = typeof rawPublicKey === "string" ? rawPublicKey : rawPublicKey?.toString?.();
      const signature = typeof rawSignature === "string"
        ? rawSignature
        : rawSignature instanceof Uint8Array
          ? btoa(Array.from(rawSignature, (byte) => String.fromCharCode(byte)).join(""))
          : "";
      if (!accountId || !publicKey || !signature) {
        throw new Error("Your wallet did not return a complete NEP-413 signature. Try another NEAR wallet.");
      }
      await api<AuthUser>("auth/verify", {
        method: "POST",
        body: JSON.stringify({
          challenge_id: challenge.challenge_id,
          account_id: accountId,
          public_key: publicKey,
          signature,
        }),
      });
      setAuthMessage("");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "NEAR wallet sign-in failed. Please try again.");
      setAuthMessage("");
    } finally {
      if (finishTimer) clearTimeout(finishTimer);
      setAuthBusy(false);
    }
  }

  async function signOut() {
    try {
      await api<{ ok: boolean }>("auth/logout", { method: "POST" });
    } finally {
      setAuthUser(null);
      setDashboard(null);
      setOrders([]);
      setEvents([]);
      setSelectedReport(null);
      setPaymentQuote(null);
      setAuthMessage("");
      setError("");
    }
  }

  const budgetUsed = dashboard
    ? Math.min(100, (dashboard.today_estimated_inference_spend_usd / Math.max(0.01, dashboard.today_inference_budget_usd)) * 100)
    : 0;
  const evidenceMarker = "## Research evidence & methodology";
  const evidenceIndex = selectedReport ? selectedReport.markdown.indexOf(evidenceMarker) : -1;
  const customerMarkdown = selectedReport
    ? (evidenceIndex >= 0 ? selectedReport.markdown.slice(0, evidenceIndex) : selectedReport.markdown)
    : "";
  const evidenceMarkdown = selectedReport && evidenceIndex >= 0
    ? selectedReport.markdown.slice(evidenceIndex)
    : "";

  const tvlHistory = publicData?.network.tvl_history ?? [];
  const tvlValues = tvlHistory.map((item) => item.tvl_usd);
  const tvlMin = tvlValues.length ? Math.min(...tvlValues) : 0;
  const tvlMax = tvlValues.length ? Math.max(...tvlValues) : 0;
  const tvlPolyline = tvlHistory.map((item, index) => {
    const x = tvlHistory.length <= 1 ? 0 : (index / (tvlHistory.length - 1)) * 600;
    const y = 104 - ((item.tvl_usd - tvlMin) / Math.max(1, tvlMax - tvlMin)) * 84;
    return x.toFixed(1) + "," + y.toFixed(1);
  }).join(" ");

  if (authLoading) {
    return <main className="auth-screen"><div className="auth-card"><div className="brand-mark">M</div><h1>Loading MERIDIAN</h1><p>Checking your private workspace...</p></div></main>;
  }

  if (!authUser && !showAdminLogin) {
    const tx = publicData?.activity.transaction_stats;
    const addresses = publicData?.activity.address_stats;
    const stablecoins = publicData?.stablecoins;
    const sourceUrls = publicData ? [...publicData.network.sources, ...publicData.activity.sources, ...publicData.stablecoins.sources, ...(publicData.developers.source ? [publicData.developers.source] : [])].filter((url, index, all) => all.indexOf(url) === index) : [];
    const positiveSignals = publicData?.thesis.signals.filter((item) => item.status === "positive").length ?? 0;
    const negativeSignals = publicData?.thesis.signals.filter((item) => item.status === "negative").length ?? 0;
    return (
      <main className="public-shell">
        <header className="public-header">
          <div className="public-brand">
            <div className="brand-mark">M</div>
            <div><div className="brand-name">MERIDIAN</div><div className="brand-caption">NEAR ECOSYSTEM INTELLIGENCE</div></div>
          </div>
          <div className="public-actions">
            <span className="public-live-pill"><span /> LIVE PUBLIC DATA</span>
            <button className="public-button secondary" onClick={() => void loadPublicIntelligence(true)} disabled={publicLoading}>
              {publicLoading ? "Refreshing…" : "Refresh data ↻"}
            </button>
            <button className="public-button" onClick={() => setShowAdminLogin(true)}>Admin sign in</button>
          </div>
        </header>

        <section className="public-hero">
          <div className="public-kicker">OPEN DATA · VERIFIABLE SIGNALS · NO AI-GENERATED CLAIMS</div>
          <h1>Understand what is happening across NEAR.</h1>
          <p>Explore network activity, developer momentum and an evidence-based ecosystem thesis. Every signal links back to its source.</p>
          <div className="public-meta">
            <span>Read-only intelligence dashboard</span>
            <span>Wallet connection not required</span>
            <span>{publicData ? "Updated " + new Date(publicData.retrieved_at).toLocaleString() : "Waiting for first data refresh"}</span>
          </div>
        </section>

        {publicError && <div className="alert error-alert">{publicError}</div>}
        <section className="public-section-heading">
          <div><div className="eyebrow">01 / NETWORK MONITOR</div><h2>On-chain fundamentals</h2></div>
          <span>{publicData?.network.chain ?? "NEAR"} · public sources</span>
        </section>
        <section className="public-stats-grid">
          <article className="public-stat"><span>Chain TVL</span><strong>{compactUsd(publicData?.network.tvl_usd)}</strong><small>DefiLlama · current snapshot</small></article>
          <article className="public-stat"><span>TVL change · 7 days</span><strong>{signedPercent(publicData?.network.change_7d_percent)}</strong><small>Historical chain TVL</small></article>
          <article className="public-stat"><span>TVL change · 30 days</span><strong>{signedPercent(publicData?.network.change_30d_percent)}</strong><small>Historical chain TVL</small></article>
          <article className="public-stat"><span>Daily transactions</span><strong>{tx?.status === "available" ? compactNumber(tx.latest_day_value) : "Unavailable"}</strong><small>{tx?.latest_day ?? "NearBlocks data unavailable"}</small></article>
          <article className="public-stat"><span>Daily active / unique addresses</span><strong>{addresses?.status === "available" ? compactNumber(addresses.latest_day_value) : "Unavailable"}</strong><small>{addresses?.latest_day ?? "NearBlocks data unavailable"}</small></article>
          <article className="public-stat"><span>Stablecoin supply</span><strong>{stablecoins?.status === "available" ? compactUsd(stablecoins.total_supply_usd) : "Unavailable"}</strong><small>{stablecoins?.asset_count ?? 0} assets · DefiLlama</small></article>
        </section>

        <section className="public-two-col">
          <article className="public-panel">
            <div className="public-panel-heading"><div><div className="eyebrow">CAPITAL TREND</div><h3>NEAR chain TVL · 30 observations</h3></div><span className="public-source-tag">DefiLlama</span></div>
            {tvlHistory.length > 1 ? (
              <div className="public-chart-wrap">
                <svg viewBox="0 0 600 125" role="img" aria-label="NEAR historical chain TVL trend">
                  <line x1="0" y1="104" x2="600" y2="104" stroke="#e6edf0" strokeWidth="1" />
                  <line x1="0" y1="62" x2="600" y2="62" stroke="#edf1f3" strokeWidth="1" strokeDasharray="4 5" />
                  <line x1="0" y1="20" x2="600" y2="20" stroke="#edf1f3" strokeWidth="1" strokeDasharray="4 5" />
                  <polyline points={tvlPolyline} fill="none" stroke="#078b7c" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                <div className="public-chart-labels"><span>{tvlHistory[0]?.date}</span><span>{tvlHistory[tvlHistory.length - 1]?.date}</span></div>
              </div>
            ) : <p className="public-muted">{publicLoading ? "Loading historical observations…" : "Historical TVL series is unavailable."}</p>}
            <div className="public-note">Latest historical observation age: {publicData?.network.history_age_hours != null ? publicData.network.history_age_hours.toFixed(1) + " hours" : "not available"}. The chart shows chain TVL, not users, fees or protocol revenue.</div>
          </article>

          <article className="public-panel thesis-panel">
            <div className="eyebrow">02 / EVIDENCE-BASED ASSESSMENT</div>
            <h3>NEAR ecosystem thesis</h3>
            <div className={"thesis-label " + (publicData?.thesis.label === "Expansion signals" ? "positive" : publicData?.thesis.label === "Contraction signals" ? "negative" : "")}>
              {publicData?.thesis.label ?? (publicLoading ? "Collecting evidence…" : "Insufficient evidence")}
            </div>
            <p>{publicData?.thesis.summary ?? "The assessment will appear when the source snapshot is ready."}</p>
            <div className="thesis-counts"><span>{positiveSignals} positive signals</span><span>{negativeSignals} negative signals</span></div>
            <div className="public-method">{publicData?.thesis.method ?? "No assessment method available yet."}</div>
          </article>
        </section>

        <section className="public-panel public-signals">
          <div className="public-panel-heading"><div><div className="eyebrow">SIGNAL BREAKDOWN</div><h3>What the evidence says</h3></div></div>
          <div className="public-signal-list">
            {(publicData?.thesis.signals ?? []).map((signal) => (
              <div className="public-signal-row" key={signal.name}>
                <div><strong>{signal.name}</strong><small>{signal.period}</small></div>
                <span className={"signal-status " + signal.status}>{signal.status}</span>
                <b>{signedPercent(signal.change_percent)}</b>
                <p>{signal.detail}</p>
              </div>
            ))}
            {!publicData?.thesis.signals.length && <p className="public-muted">{publicLoading ? "Calculating signals from live source data…" : "No comparable signals were returned."}</p>}
          </div>
        </section>

        <section className="public-section-heading">
          <div><div className="eyebrow">03 / DEVELOPER MOMENTUM</div><h2>Projects building around NEAR</h2></div>
          <span>{publicData?.developers.projects.length ?? 0} repositories inspected</span>
        </section>
        <section className="public-panel">
          <div className="public-project-grid">
            {(publicData?.developers.projects ?? []).map((project) => {
              const latest = project.recent_commits?.[0];
              return (
                <article className="public-project-card" key={project.name}>
                  <div className="project-topline"><span>{project.classification?.replaceAll("_", " ") ?? "Unclassified"}</span><span>{project.language ?? "Repository"}</span></div>
                  <h3>{project.name}</h3>
                  <p>{project.description || "No repository description supplied."}</p>
                  <div className="project-stats"><span>★ {compactNumber(project.stars)}</span><span>⑂ {compactNumber(project.forks)}</span><span>Last push {project.last_pushed_at ? new Date(project.last_pushed_at).toLocaleDateString() : "n/a"}</span></div>
                  <div className="project-commit"><strong>Latest commit</strong><span>{latest?.message ?? "Commit message unavailable"}</span><small>{latest?.date ? new Date(latest.date).toLocaleDateString() : "No recent commit date"}</small></div>
                  {project.url && <a href={project.url} target="_blank" rel="noreferrer">View repository ↗</a>}
                </article>
              );
            })}
            {!publicData?.developers.projects.length && <p className="public-muted">{publicLoading ? "Inspecting public GitHub repositories…" : "No project candidates returned by GitHub search."}</p>}
          </div>
          {publicData?.developers.limitations && <p className="public-note">{publicData.developers.limitations}</p>}
        </section>

        <section className="public-section-heading">
          <div><div className="eyebrow">DATA TRANSPARENCY</div><h2>Sources and limitations</h2></div>
        </section>
        <section className="public-two-col">
          <article className="public-panel">
            <h3>Source registry</h3>
            <ul className="public-source-list">
              {sourceUrls.map((url)=><li key={url}><a href={url} target="_blank" rel="noreferrer">{new URL(url).hostname}</a></li>)}
            </ul>
            <p className="public-note">Retrieved {publicData ? new Date(publicData.retrieved_at).toLocaleString() : "—"}. Data is cached for five minutes to avoid unnecessary provider requests.</p>
          </article>
          <article className="public-panel">
            <h3>Quality warnings</h3>
            {(publicData?.network.quality_warnings ?? []).length ? <ul>{publicData?.network.quality_warnings.map((warning,index)=><li key={index}>{warning}</li>)}</ul> : <p className="public-muted">No chain TVL quality warnings returned. This does not mean the dataset is complete.</p>}
            <p className="public-note">{publicData?.disclaimer ?? "Metrics are not investment advice. Repository activity does not prove production adoption."}</p>
          </article>
        </section>

        <footer className="public-footer">MERIDIAN · BUILT FOR THE NEAR ECOSYSTEM · READ-ONLY · NO WALLETS OR PAYMENTS REQUIRED</footer>
      </main>
    );
  }

  if (!authUser) {
    return (
      <main className="auth-screen">
        <section className="auth-card">
          <div className="auth-brand"><div className="brand-mark">M</div><div><div className="brand-name">MERIDIAN</div><div className="brand-caption">PRIVATE RESEARCH WORKSPACE</div></div></div>
          <div className="eyebrow">NEAR IDENTITY</div>
          <h1>Sign in with NEAR</h1>
          <button className="public-back-link" type="button" onClick={() => setShowAdminLogin(false)}>← Back to public dashboard</button>
          <p className="auth-description">Connect your NEAR wallet and sign one short message to prove account ownership. Your wallet keeps your keys.</p>
          <div className="auth-form">
            <button className="primary-button" type="button" onClick={() => void signInWithNear()} disabled={authBusy}>
              {authBusy ? "Waiting for wallet..." : "Connect NEAR wallet"}
            </button>
          </div>
          {authMessage && <div className="auth-message">{authMessage}</div>}
          {error && <div className="alert error-alert">{error}</div>}
          <div className="auth-footnote">Identity verification only. No transaction, transfer, token approval, access-key addition or payment is requested. Never share your seed phrase or private key.</div>
        </section>
      </main>
    );
  }

  if (authUser.role === "customer") {
    return (
      <main className="customer-shell">
        <header className="customer-topbar">
          <div className="auth-brand"><div className="brand-mark">M</div><div><div className="brand-name">MERIDIAN</div><div className="brand-caption">PRIVATE RESEARCH WORKSPACE</div></div></div>
          <div className="customer-account"><span>{authUser.account_id}</span><button className="signout-button" onClick={() => void signOut()}>Sign out</button></div>
        </header>
        {error && <div className="alert error-alert">{error}</div>}
        {notice && <div className="alert notice-alert">{notice}</div>}
        <section className="customer-intro"><div className="eyebrow">YOUR WORKSPACE</div><h1>Your research</h1><p>Your questions and reports are private to this account. Only you can access this research history.</p></section>
        <div className="customer-grid">
          <div className="customer-primary-column">
          <section className="panel order-panel">
            <div className="panel-heading"><div><div className="eyebrow">RESEARCH DESK</div><h2>Create a report</h2></div><span className="mini-tag">NEW ORDER</span></div>
            <p className="panel-subtitle">What would you like MERIDIAN to investigate?</p>
            <form onSubmit={submitOrder} className="order-form">
              <label htmlFor="topic">Research question</label>
              <textarea id="topic" value={topic} onChange={(event) => setTopic(event.target.value)} placeholder="Ask anything here or type your research question..." minLength={8} maxLength={500} required />
              <div className="form-row"><div className="price-field"><label htmlFor="price">Report quote (USD)</label><div className="input-wrap"><span>$</span><input id="price" type="number" min={rules?.limits.minimum_report_price ?? 10} step="0.5" value={price} onChange={(event) => setPrice(event.target.value)} required /></div></div><div className="price-hint">Minimum quote<br /><strong>{money(rules?.limits.minimum_report_price ?? 10)}</strong></div></div>
              <button type="submit" className="primary-button" disabled={busy || loading}>{busy ? <><span className="spinner" /> Generating report...</> : <>Generate research report <span>↗</span></>}</button>
              <p className="form-footnote">Your report will be saved to this private account. No customer payment is collected.</p>
            </form>
          </section>

          {selectedReport && (
            <section ref={reportRef} className="panel report-panel customer-report-panel">
              <div className="panel-heading"><div><div className="eyebrow">YOUR REPORT · {selectedReport.data_mode.toUpperCase().replaceAll("_", " ")}</div><h2>{selectedReport.title}</h2></div><div className="report-actions"><button className="download-button" onClick={() => downloadReport(selectedReport)}>Download .md</button><button className="close-button" onClick={() => { setSelectedReport(null); setPaymentQuote(null); }}>Close ×</button></div></div>
              <div className="report-content"><MarkdownView markdown={customerMarkdown} />{evidenceMarkdown && <details className="evidence-details"><summary>View full source data and methodology</summary><div className="evidence-content"><MarkdownView markdown={evidenceMarkdown} /></div></details>}</div>
            </section>
          )}
          </div>
          <section className="panel customer-orders">
            <div className="panel-heading"><div><div className="eyebrow">PRIVATE HISTORY</div><h2>Your research orders</h2></div><button className="refresh-button" onClick={() => void refresh()} aria-label="Refresh orders">↻</button></div>
            {orders.length === 0 ? <p className="empty-cell">{loading ? "Loading your orders..." : "Your research history will appear here after your first order."}</p> : (
              <div className="customer-order-list">
                {orders.map((order) => (
                  <div className="customer-order-row" key={order.id}>
                    <div className="customer-order-main"><strong>{order.topic}</strong><span>{prettyDate(order.created_at)} · {order.status.replaceAll("_", " ")}</span></div>
                    <div className="customer-order-action"><strong>{money(order.price_usd)}</strong><button className="view-button" onClick={() => void openReport(order.id)}>View report</button></div>
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>
        <footer className="customer-footer">MERIDIAN · PRIVATE RESEARCH · PAYMENTS DISABLED</footer>
      </main>
    );
  }

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
            <span className="admin-email">{authUser.account_id}</span><button className="signout-button" onClick={() => void signOut()}>Sign out</button>
            <span className="demo-pill"><span /> {dashboard?.research_mode === "live" ? "LIVE RESEARCH" : "DEMO MODE"}</span>
            <button className="refresh-button" onClick={() => void refresh()} aria-label="Refresh dashboard">↻</button>
          </div>
        </header>

        {error && <div className="alert error-alert">{error}</div>}
        {notice && <div className="alert notice-alert">{notice}</div>}

        <div className="status-strip">
          <div className="status-title"><span className="status-dot" /> SYSTEM STATUS</div>
          <div className="status-item">Research engine <strong>{dashboard?.research_mode === "live" ? "Live data" : "Synthetic demo"}</strong></div>
          <div className="status-item">NEAR AI Cloud <strong className={dashboard?.near_ai_cloud_configured ? "on" : "off"}>{dashboard?.near_ai_cloud_configured ? "Configured" : "API key needed"}</strong></div>
          <div className="status-item">Payments <strong className="off">Disabled</strong></div>
          <div className="status-item">Mainnet execution <strong className="off">Disabled</strong></div>
          <div className="status-item">Safety gate <strong className="on">Active</strong></div>
        </div>

        <section className="metrics-grid">
          <Metric label="Research orders" value={dashboard ? String(dashboard.orders) : "—"} helper="All time" icon="▤" />
          <Metric label="Reports generated" value={dashboard ? String(dashboard.reports_generated) : "—"} helper="Generated reports" icon="▧" />
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
              <textarea id="topic" value={topic} onChange={(event) => setTopic(event.target.value)} placeholder="Ask anything here or type your research question..." minLength={8} maxLength={500} required />
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
              <Economics label="Estimated inference spend" value={dashboard ? money(dashboard.estimated_inference_spend_usd) : "—"} />
              <Economics label="Projected profit" value={dashboard ? money(dashboard.projected_profit_usd) : "—"} />
              <Economics label="Operator share" value={rules ? rules.revenue_split.operator_percent + "%" : "—"} />
              <Economics label="Contributor share" value={rules ? rules.revenue_split.contributors_percent + "%" : "—"} />
            </div>
            <div className="budget-block">
              <div className="budget-head"><span>Daily inference budget</span><strong>{dashboard ? money(dashboard.today_estimated_inference_spend_usd) + " / " + money(dashboard.today_inference_budget_usd) : "—"}</strong></div>
              <div className="budget-track"><div className="budget-fill" style={{ width: budgetUsed + "%" }} /></div>
              <div className="budget-caption">Inference costs are estimates and new orders are blocked at the configured daily limit.</div>
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
              <div className="report-actions"><button className="download-button" onClick={() => downloadReport(selectedReport)}>Download .md</button><button className="close-button" onClick={() => { setSelectedReport(null); setPaymentQuote(null); }}>Close ×</button></div>
            </div>
            <div className="report-content">
              <MarkdownView markdown={customerMarkdown} />
              {evidenceMarkdown && (
                <details className="evidence-details">
                  <summary>View full source data and methodology</summary>
                  <div className="evidence-content"><MarkdownView markdown={evidenceMarkdown} /></div>
                </details>
              )}
            </div>
          </section>
        )}

        {paymentQuote && (
          <section className="panel payment-panel">
            <div className="panel-heading">
              <div>
                <div className="eyebrow">PAYMENT ROUTE · TESTNET PREVIEW</div>
                <h2>Tidepool swap quote</h2>
              </div>
              <span className="mini-tag">{paymentQuote.status === "dry_quote_returned" ? "DRY QUOTE" : "FALLBACK"}</span>
            </div>
            {paymentQuote.quote ? (
              <div className="quote-metrics">
                <div><span>WNEAR input estimate</span><strong>{paymentQuote.quote.amount_in_formatted ?? "—"} WNEAR</strong><small>{paymentQuote.quote.amount_in_usd ? "$" + paymentQuote.quote.amount_in_usd : ""}</small></div>
                <div><span>USDC output target</span><strong>{paymentQuote.quote.amount_out_formatted ?? "—"} USDC</strong><small>{paymentQuote.quote.amount_out_usd ? "$" + paymentQuote.quote.amount_out_usd : ""}</small></div>
                <div><span>Estimated route time</span><strong>{paymentQuote.quote.time_estimate_seconds ?? "—"} sec</strong></div>
              </div>
            ) : (
              <p className="panel-subtitle">{paymentQuote.reason || "The sandbox did not return a quote. The order remains unpaid."}</p>
            )}
            <p className="form-footnote">{paymentQuote.note || "Community sandbox quote only. No deposit address, transaction, or settlement was created. This is not the official NEAR Intents testnet."}</p>
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
                  {orders.length === 0 ? <tr><td colSpan={5} className="empty-cell">{loading ? "Loading orders..." : "No research orders yet. Create your first research report above."}</td></tr> :
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
                    <div className="ledger-main"><strong>{event.event_type.replaceAll("_", " ")}</strong><span>{event.order_id ? "Order " + event.order_id.slice(0, 8) : "System event"}</span><details className="ledger-event-details"><summary>Inspect event data</summary><pre>{JSON.stringify(event.details, null, 2)}</pre></details></div>
                    <time>{prettyDate(event.created_at)}</time>
                  </div>
                ))}
            </div>
          )}
        </section>

        <footer className="footer">
          <span>MERIDIAN · AUTONOMOUS RESEARCH BUSINESS</span>
          <span>PAYMENTS DISABLED · MAINNET EXECUTION DISABLED</span>
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

function inlineMarkdown(value: string): ReactNode[] {
  const parts = value.split(/(\*\*[^*]+\*\*|\[[^\]]+\]\([^)]+\))/g);
  return parts.map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    }
    const linkOpen = part.indexOf("](");
    if (part.startsWith("[") && linkOpen > 1 && part.endsWith(")")) {
      const label = part.slice(1, linkOpen);
      const href = part.slice(linkOpen + 2, -1);
      if (href.startsWith("https://") || href.startsWith("http://")) {
        return <a key={index} href={href} target="_blank" rel="noreferrer">{label}</a>;
      }
    }
    return part;
  });
}

function MarkdownView({ markdown }: { markdown: string }) {
  const lines = markdown.split(/\r?\n/);
  const blocks: ReactNode[] = [];
  let index = 0;
  while (index < lines.length) {
    const line = lines[index].trim();
    if (!line) { index += 1; continue; }
    if (line.startsWith("# ")) { index += 1; continue; }
    if (/^---+$/.test(line)) { blocks.push(<hr key={index} />); index += 1; continue; }
    const heading = line.match(/^(#{2,4})\s+(.+)$/);
    if (heading) {
      const level = heading[1].length;
      const content = inlineMarkdown(heading[2]);
      blocks.push(level === 2 ? <h3 key={index}>{content}</h3> : level === 3 ? <h4 key={index}>{content}</h4> : <h5 key={index}>{content}</h5>);
      index += 1;
      continue;
    }
    if (line.startsWith("> ")) {
      const quote: string[] = [];
      while (index < lines.length && lines[index].trim().startsWith("> ")) {
        quote.push(lines[index].trim().slice(2));
        index += 1;
      }
      blocks.push(<blockquote key={index}>{quote.map((item, i) => <p key={i}>{inlineMarkdown(item)}</p>)}</blockquote>);
      continue;
    }
    if (line.startsWith("|") && index + 1 < lines.length && /^\|?\s*:?-{3,}/.test(lines[index + 1].trim())) {
      const cells = (value: string) => value.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
      const header = cells(lines[index]);
      index += 2;
      const rows: string[][] = [];
      while (index < lines.length && lines[index].trim().startsWith("|")) {
        rows.push(cells(lines[index]));
        index += 1;
      }
      blocks.push(
        <div className="report-table-wrap" key={index}>
          <table className="report-table">
            <thead><tr>{header.map((cell, i) => <th key={i}>{inlineMarkdown(cell)}</th>)}</tr></thead>
            <tbody>{rows.map((row, i) => <tr key={i}>{header.map((_, j) => <td key={j}>{inlineMarkdown(row[j] || "")}</td>)}</tr>)}</tbody>
          </table>
        </div>
      );
      continue;
    }
    if (/^[-*]\s+/.test(line)) {
      const items: string[] = [];
      while (index < lines.length && /^\s*[-*]\s+/.test(lines[index])) {
        items.push(lines[index].trim().replace(/^[-*]\s+/, ""));
        index += 1;
      }
      blocks.push(<ul key={index}>{items.map((item, i) => <li key={i}>{inlineMarkdown(item)}</li>)}</ul>);
      continue;
    }
    if (/^\d+\.\s+/.test(line)) {
      const items: string[] = [];
      while (index < lines.length && /^\s*\d+\.\s+/.test(lines[index])) {
        items.push(lines[index].trim().replace(/^\d+\.\s+/, ""));
        index += 1;
      }
      blocks.push(<ol key={index}>{items.map((item, i) => <li key={i}>{inlineMarkdown(item)}</li>)}</ol>);
      continue;
    }
    const paragraph = [line];
    index += 1;
    while (index < lines.length && lines[index].trim() && !/^(#{1,4}\s|>|[-*]\s|\d+\.\s|\|)/.test(lines[index].trim()) && !/^---+$/.test(lines[index].trim())) {
      paragraph.push(lines[index].trim());
      index += 1;
    }
    blocks.push(<p key={index}>{inlineMarkdown(paragraph.join(" "))}</p>);
  }
  return <div className="markdown-view">{blocks}</div>;
}
