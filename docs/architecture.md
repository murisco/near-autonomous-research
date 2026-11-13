# MERIDIAN architecture

## Services

1. **Dashboard** — Next.js customer research desk, order history and business control room.
2. **Business API** — FastAPI order lifecycle, policy checks, report orchestration, accounting and ledger API.
3. **Research source layer** — DefiLlama chain TVL and protocol data; NearBlocks daily transaction/address statistics; NEAR official Research & Analytics hub; NEAR AI Cloud docs; NEAR Intents docs and publisher homepage.
4. **AI synthesis** — Optional NEAR AI Cloud OpenAI-compatible API call over collected evidence. A model's privacy tier is reported as model-dependent.
5. **Treasury/accounting module** — estimated inference reserve, report quote, projected profit and operator/contributor allocation.
6. **Audit ledger** — off-chain PostgreSQL records for orders, policy decisions, sources, quote previews, and accounting entries.
7. **Payment adapter** — Tidepool community sandbox dry quote only. No deposit address, transaction, or settlement.

## Current order lifecycle

`requested → policy_approved → researching → report_ready_unpaid`

The customer research-order path uses live source-backed research by default. The separate `POST /api/demo/run` route remains synthetic and deterministic for CI and judge walkthroughs.

## Research pipeline

### DefiLlama

- Query the chain catalogue first and resolve the chain from the request.
- Fetch historical TVL for that exact selected chain, not a hard-coded default chain.
- Compute 7-day and 30-day deltas using timestamp windows, not array offsets.
- Apply category filters consistent with DefiLlama's methodology. Bridge and liquid-staking TVL are not attributed to chain TVL by default. CEX categories and double-counted rows are excluded.
- Exclude a protocol when its reported chain-specific value exceeds chain-wide TVL by more than 5%.
- Report excluded rows and warnings transparently. Individual protocol values are not added to create a chain total because they may overlap.

### NearBlocks

The research layer requests the daily transaction-statistics and address-statistics endpoints, recognises documented data fields, and summarises the returned dates. If the API fails or its response shape is not recognised, the relevant metric is labelled unavailable. Reports attribute NearBlocks.

### Official NEAR sources

MERIDIAN retrieves official NEAR research hub and product documentation. Publisher-reported headline metrics remain labelled as such. NEAR Intents transaction-level Explorer data requires a partner JWT; no transaction-level volume or swap counts are claimed without querying the authenticated endpoint.

### NEAR AI Cloud

AI synthesis runs only when `NEAR_AI_API_KEY` is configured. The default model is the model shown in the current NEAR AI Cloud quickstart. Without a key or on API failure, MERIDIAN uses a limited deterministic summary and records that AI analysis did not run.

## Data provenance

- `defillama_live` means DefiLlama chain/protocol data was retrieved.
- `near_ai_live` means a configured NEAR AI Cloud model generated the analysis over the gathered research context.
- `synthetic_demo` is generated sample content and must never be described as live research.
- Publisher-displayed statistics are explicitly distinguished from independently queried data.
- Every report includes source URLs, retrieval time and methodology caveats.

TVL is not a proxy for users, transactions, fees or protocol revenue.

## Business controls

- Enforce minimum report price before research starts.
- Check estimated daily inference reserve against the configured cap.
- Stop new jobs when the kill switch is enabled.
- Validate that operator and contributor revenue shares total 100%.
- Keep payment collection, wallet signing, payouts and mainnet execution disabled by default.
- Treat unpaid order values as quotes, not collected revenue.
- Require explicit owner approval for irreversible transfers and payouts.
- Keep wallet/API keys outside source control and plaintext application data.

## NEAR integration boundaries

NEAR AI Cloud provides an OpenAI-compatible inference API. Its published model catalogue distinguishes Confidential TEE, third-party Confidential TEE, and Incognito model classes; privacy and verification guarantees depend on the chosen model.

The official NEAR Intents 1Click quickstart states there is no testnet version. Tidepool is a community-operated sandbox and must not be represented as official NEAR or Defuse infrastructure. MERIDIAN's Tidepool adapter uses dry mode only; it does not create a deposit address or transfer funds.

Production NEAR Intents settlement, wallet custody, refund handling, contributor payouts and onchain audit anchoring remain unimplemented and disabled.

## Persistence and auditability

PostgreSQL persists orders, reports, estimated costs and audit events. The ledger is currently off-chain. A future public/onchain ledger anchor must omit customer email and other private data, and must only use verified transaction references after actual settlement.
