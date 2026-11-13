# MERIDIAN architecture

## Services

1. **Dashboard** — Next.js customer research desk, order history and operator control room.
2. **Business API** — FastAPI order lifecycle, server-side policy checks, report orchestration and accounting.
3. **Research provider** — DefiLlama public chain and protocol endpoints for live TVL snapshots; optional NEAR AI Cloud analysis of collected source data.
4. **Treasury/accounting module** — estimated inference reserves, report pricing, projected profit, operator/contributor allocation and daily budget enforcement.
5. **Audit ledger** — off-chain PostgreSQL records for orders, decisions, source metadata, quote previews and accounting entries.
6. **NEAR payment/custody adapters** — planned; payments, transfers and payouts remain disabled until a wallet, test environment and owner-approved policy are configured.

## Current order lifecycle

`requested → policy_approved → researching → report_ready_unpaid`

The customer research-order path uses live source-backed data by default. The separate `POST /api/demo/run` route deliberately remains synthetic and deterministic for CI and judge walkthroughs.

## Data provenance

Each report stores a data mode and audit metadata. `defillama_live` means public DefiLlama chain/protocol data was retrieved; it does not mean NEAR AI Cloud ran. `near_ai_live` means the configured NEAR AI Cloud model generated an analysis over the retrieved data. `synthetic_demo` is generated sample content and must never be described as live research.

Every report states its source URLs, retrieval timestamp and methodology caveats. TVL is not a proxy for users, transactions, fees or protocol revenue.

## Business controls

- Enforce the minimum report price before research starts.
- Check daily estimated inference reserve against the configured cap.
- Stop new jobs when the kill switch is enabled.
- Validate that operator and contributor revenue shares total 100%.
- Keep payment collection, wallet signing, contributor payout and mainnet execution disabled by default.
- Treat unpaid order values as quotes, not collected revenue.
- Require explicit owner approval for irreversible transfers and payouts.
- Keep wallet/API keys outside source control and plaintext application data.

## NEAR integrations and boundaries

NEAR AI Cloud uses an OpenAI-compatible API. The current adapter is optional and runs only when `NEAR_AI_API_KEY` is configured. Without a key, MERIDIAN produces a source-backed deterministic report and records that no NEAR AI model inference ran.

NEAR Intents production 1Click is mainnet-only according to its official documentation. Tidepool provides a community-operated, 1Click-compatible NEAR testnet sandbox using valueless test tokens; it is not affiliated with NEAR, Defuse or 1Click. It may be used for isolated testnet experiments, but must not be represented as the official NEAR Intents testnet. OutLayer's testnet wallet APIs support account and direct NEAR operations, but its documentation says its Intents-dependent endpoints return HTTP 503 on testnet. These products therefore do not yet provide MERIDIAN with a single official end-to-end testnet path for Intents payments and payouts.

Live research orders may request a Tidepool dry quote for a WNEAR-to-USDC route. The response is labelled as a community sandbox quote, its signature is not treated as verified, and the dry flag prevents a deposit address from being returned. No transfer is initiated. If the sandbox is unavailable, the system records a simulation fallback. This does not represent official NEAR Intents testnet or production settlement.

## Persistence and auditability

PostgreSQL persists orders, reports, estimated costs and audit events. The ledger is currently off-chain. A future public/onchain ledger anchor must omit customer email and private data, and only use verified transaction references after actual settlement.
