# MERIDIAN — Autonomous Onchain Research Business

MERIDIAN is an AI-native research business built for the **NEAR Hackathon 2026 — Autonomous Business track**.

A customer submits a blockchain research question. MERIDIAN gathers public data, checks source methodology, produces an evidence-led report, estimates delivery costs, and records the order and business decisions in an audit ledger.

## What the current build does

- Accepts a priced research order and applies minimum-price, daily-budget, kill-switch and revenue-split rules.
- Retrieves chain TVL and historical TVL from DefiLlama.
- Filters protocol rows using DefiLlama's chain-TVL methodology: bridge and liquid-staking rows, CEX categories, flagged double-counts, and protocol values inconsistent with total chain TVL are excluded and listed in the report.
- Calculates historical percentage changes using timestamp windows rather than assuming every data row is exactly one day apart.
- Retrieves NEAR stablecoin supply, history and token-level chain circulation through DefiLlama. It validates that each response contains usable NEAR data and falls back to `stablecoins.llama.fi` when the primary API host does not serve those routes.
- Retrieves daily NEAR transaction and address statistics from the NearBlocks API when the public endpoints return a recognised response. NearBlocks is credited in the report.
- Reads NEAR's official Research & Analytics hub, NEAR AI Cloud documentation, and NEAR Intents documentation. Publisher-displayed metrics are explicitly separated from independently queried data.
- Reports the official NEAR Intents homepage's volume headline as publisher-reported, not independently reconstructed. Transaction-level Intents Explorer data is marked unavailable unless a partner JWT is configured.
- Optionally analyses the complete source context through NEAR AI Cloud when `NEAR_AI_API_KEY` is configured. Without the key, MERIDIAN creates a deterministic source summary and clearly says AI Cloud inference did not run.
- Tracks estimated inference costs, quoted sales, projected profit and operator/contributor shares.
- Records research source metadata, exclusions, payment previews and accounting decisions in an off-chain audit ledger.
- Persists records in Railway PostgreSQL; SQLite is available for local development.
- Uses passwordless email sign-in with short-lived one-time codes and HTTP-only sessions.
- Restricts each customer to their own research orders and reports; only allowlisted admin emails can access business metrics and the full audit ledger.

## Data-quality rules

- Chain TVL is not a measure of users, transactions, fees, or protocol revenue.
- DefiLlama excludes bridge TVL and liquid-staking TVL from chain TVL by default. CEX assets are not chain DeFi TVL.
- Protocol-level figures may overlap. MERIDIAN never adds protocol rows together as though they were a verified chain total.
- A protocol row is excluded if its reported chain-specific TVL exceeds chain TVL by more than 5%, or if DefiLlama marks it double-counted.
- Historical deltas use timestamp windows and the actual latest historical observation date.
- NearBlocks, NEAR's own analytics hub and NEAR Intents homepage are clearly attributed. Publisher headlines are not silently treated as independent measurements.
- Missing or unrecognised metrics are labelled unavailable; the app does not fill gaps with invented data.
- Stablecoin source checks validate response shape and exact chain coverage. CI also runs a live smoke check against the primary and compatibility hosts, so an HTTP 200 with empty or wrong-chain data cannot silently pass.

## Identity and account access

- Visitors connect a NEAR wallet and sign a one-time NEP-413 message to prove control of their account.
- The message is bound to the MERIDIAN dashboard recipient and a random 32-byte nonce that expires after five minutes and can be used once.
- The backend verifies the NEP-413 signature and checks NEAR RPC to confirm the signing public key is currently a full-access key on the claimed account.
- Login never calls `signAndSendTransaction`, never adds an access key, and never asks for a seed phrase or private key.
- Login signatures cannot transfer funds, approve tokens, grant allowances, or authorize payments. Payment and mainnet execution remain disabled.
- Sessions use random opaque tokens stored as hashes and delivered in HTTP-only, same-site cookies.
- Customer API responses are filtered by their verified NEAR account ID. Supplying another customer's order ID returns not found.
- Business totals, projected margins, customer-wide order search, and the complete audit ledger are admin-only.
- Admin access is granted only to account IDs listed in `MERIDIAN_ADMIN_ACCOUNT_IDS`; it is never selected by the browser.
- Only NEP-413 Ed25519 signatures from current full-access keys are accepted. Limited-access keys are rejected.

Set `MERIDIAN_ADMIN_ACCOUNT_IDS` to a comma-separated list of owner NEAR account IDs on the API service in Railway. The default signing recipient is `meridian-dashboard.up.railway.app`; set `MERIDIAN_NEAR_AUTH_RECIPIENT` if the public dashboard hostname changes. Optional RPC overrides are `NEAR_MAINNET_RPC_URL` and `NEAR_TESTNET_RPC_URL`.

## What is not live

- Customer payment collection or settlement through NEAR Intents.
- Automated contributor payouts.
- OutLayer custody wallet creation and policy configuration.
- On-chain audit anchoring.

The payment preview is a **Tidepool community-sandbox dry quote** only. It is not an official NEAR or Defuse testnet, does not create a deposit address, does not move funds, and does not mean customer payment was received. The official NEAR Intents 1Click API has no testnet version. Mainnet execution and payment collection remain disabled.

Revenue received stays at zero until a verified payment status is connected. Payout shares are projections, not transfers.

## Environment variables

Set these only in Railway's service variables or a local untracked `.env` file. Never commit secrets.

- `NEAR_AI_API_KEY`: enables NEAR AI Cloud evidence synthesis.
- `NEAR_AI_BASE_URL`: defaults to `https://cloud-api.near.ai/v1`.
- `NEAR_AI_MODEL`: defaults to `zai-org/GLM-5.1-FP8`, following the current NEAR AI Cloud quickstart example.
- `NEARBLOCKS_API_KEY`: optional bearer key for higher NearBlocks API limits.
- `NEAR_INTENTS_EXPLORER_JWT`: partner JWT needed for transaction-level 1Click Explorer analytics. The current code does not claim explorer metrics without querying the API.

See `.env.example` for the full list. Do not paste keys into GitHub issues or chat.

## Business rules

Edit `config/business-rules.yaml`:

- `limits.max_inference_spend_per_day`: maximum estimated inference budget per day.
- `limits.minimum_report_price`: lowest accepted report price.
- `revenue_split.operator_percent` and `contributors_percent`: percentages that must total 100.
- `safety.kill_switch`: pauses new orders when true.
- `safety.payments_enabled`: remains false.
- `safety.mainnet_execution_enabled`: remains false.
- `safety.require_human_approval_for_payouts`: requires operator oversight before payouts.

## Architecture

- **Dashboard:** Next.js research desk and business control room.
- **Business API:** FastAPI order lifecycle, policy checks, research orchestration, accounting and ledger API.
- **Research sources:** DefiLlama, NearBlocks, NEAR official research hub, NEAR AI Cloud documentation and NEAR Intents documentation.
- **AI analysis:** optional NEAR AI Cloud OpenAI-compatible inference over the gathered source context.
- **Treasury logic:** estimates inference cost, report price, projected profit and revenue shares.
- **Database:** SQLAlchemy with PostgreSQL on Railway.
- **Payments:** Tidepool community dry-quote adapter only; real NEAR Intents payment settlement and custody are not active.

## Run locally

### Backend

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.app.main:app --reload --port 8000
```

### Dashboard

```bash
cd frontend
npm install
BACKEND_URL=http://localhost:8000 npm run dev
```

Open `http://localhost:3000`.

## Tests

```bash
python -m compileall -q backend
pytest -q
```

The backend CI compiles the application, runs the backend tests, and smoke-checks the live DefiLlama NEAR stablecoin endpoints. Tests cover deterministic demo orders, policy enforcement, audit events, quote-preview safety, DefiLlama category exclusions, protocol outliers, stablecoin host fallback and payload validation, date-based historical change calculations, and publisher-metric labelling. Frontend CI builds the Next.js dashboard.

## Judge walkthrough

1. Open the Railway dashboard.
2. Submit a research question with a quote at or above the configured minimum.
3. Review the chain TVL snapshot, filtered protocol table, excluded rows and data-quality warnings.
4. Review NEAR activity metrics where NearBlocks returns a recognised daily series.
5. Review official NEAR AI and NEAR Intents documentation facts, and distinguish them from publisher-displayed headline metrics.
6. Inspect the Tidepool dry-quote preview (when available) and the audit ledger. The dashboard displays the returned quote preview alongside the report; it never creates a deposit address or marks the order paid.
7. Confirm that revenue received remains zero and no transfer or payout is shown as completed.

## Hackathon submission

- Event: NEAR Hackathon 2026 — Build Beyond Boundaries.
- Track: Autonomous Business (`business`).
- Public repository: https://github.com/murisco/near-autonomous-research
- Demo hosting: https://meridian-dashboard.up.railway.app
- Submission description and judge demo script: `docs/hackathon-submission.md`.

MERIDIAN is explicit about the difference between live public data, publisher-reported metrics, AI analysis, quote previews, and actual onchain settlement.
