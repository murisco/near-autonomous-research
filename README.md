# MERIDIAN — NEAR Ecosystem Intelligence

MERIDIAN is a public, read-only NEAR ecosystem intelligence dashboard built for the **NEAR Hackathon 2026 — Investment Thesis track**.

It helps a researcher inspect three connected areas: NEAR network fundamentals, developer activity across selected NEAR-related repositories, and a transparent evidence-based ecosystem assessment. The public dashboard is usable without a wallet, account, payment, or AI-provider credit.

**Live dashboard:** https://meridian-dashboard.up.railway.app  
**Public data endpoint:** https://meridian-dashboard.up.railway.app/api/public/intelligence  
**Repository:** https://github.com/murisco/near-autonomous-research

## Public product features

1. **NEAR Network Monitor** — live chain TVL and historical observations from DefiLlama, daily transaction and address statistics from NearBlocks where available, and NEAR stablecoin supply from DefiLlama.
2. **Ecosystem Development Tracker** — GitHub repository discovery, README screening, repository metadata, latest push dates and recent commit messages for a small set of NEAR-related candidates.
3. **NEAR Investment Thesis** — a deterministic scorecard built from available 7-day and 30-day changes. Each signal is labelled positive, negative, stable or inconclusive. The dashboard exposes its calculation method, source registry and data-quality limitations.

The public data endpoint gathers the source data independently of any model. It caches the latest snapshot for five minutes; the dashboard's refresh control requests a fresh snapshot. Missing source measurements remain unavailable instead of being fabricated. Wallet sign-in is retained only for the optional private/admin workspace.

## What else remains in the repository

The earlier private research-order and autonomous-business prototype remains in the codebase as a separate, authenticated workspace. It includes order-policy checks, report records, projected accounting, an off-chain audit ledger and a quote-only sandbox adapter. These are not required to use the public ecosystem dashboard and must not be presented as live customer payments or on-chain settlement.

- Accepts a priced research order and applies minimum-price, daily-budget, kill-switch and revenue-split rules.
- Retrieves chain TVL and historical TVL from DefiLlama.
- Filters protocol rows using DefiLlama's chain-TVL methodology: bridge and liquid-staking rows, CEX categories, flagged double-counts, and protocol values inconsistent with total chain TVL are excluded and listed in the report.
- Calculates historical percentage changes using timestamp windows rather than assuming every data row is exactly one day apart.
- Retrieves NEAR stablecoin supply, history and token-level chain circulation through DefiLlama. It validates that each response contains usable NEAR data and falls back to `stablecoins.llama.fi` when the primary API host does not serve those routes.
- Retrieves daily NEAR transaction and address statistics from the NearBlocks API when the public endpoints return a recognised response. NearBlocks is credited in the report.
- Reads NEAR's official Research & Analytics hub, NEAR AI Cloud documentation, and NEAR Intents documentation. Publisher-displayed metrics are explicitly separated from independently queried data.
- Reports the official NEAR Intents homepage's volume headline as publisher-reported, not independently reconstructed. Transaction-level Intents Explorer data is marked unavailable unless a partner JWT is configured.
- Sends the complete source context and the customer's exact question to NEAR AI Cloud through its OpenAI-compatible chat-completions API. Gemini is the provider fallback if NEAR AI Cloud is unavailable. The report records the provider/model used and surfaces sanitized failure diagnostics when both providers fail.
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

- The public NEAR intelligence dashboard does not require sign-in or wallet connection.
- The optional private/admin workspace retains NEAR wallet authentication. Visitors who choose that route connect a NEAR wallet and sign a one-time NEP-413 message to prove control of their account.
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
- `GEMINI_API_KEY`: enables the Gemini fallback when NEAR AI Cloud is unavailable.
- `GEMINI_MODEL`: defaults to `gemini-3.8-flash`.
- `NEAR_AI_MODEL`: defaults to `z-ai/glm-5.3-flash`.
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

- **Public dashboard:** Next.js interface for network monitoring, developer activity and a deterministic evidence-based thesis.
- **Public API:** FastAPI `/api/public/intelligence` endpoint; no wallet or session required.
- **Research sources:** DefiLlama, NearBlocks and GitHub's public repository, README and commit APIs.
- **Thesis calculation:** explicit percentage-change thresholds; no model inference is needed to calculate or display the public assessment.
- **Private workspace:** legacy order lifecycle, business policy, research orchestration, accounting and audit-ledger API.
- **Database:** SQLAlchemy with PostgreSQL on Railway for the private workspace.
- **Payments:** disabled; the older Tidepool adapter is quote-only and not part of the public dashboard.

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

1. Open https://meridian-dashboard.up.railway.app. The public dashboard should load without requiring a wallet.
2. Inspect the chain TVL, 7-day and 30-day changes, latest completed daily transactions and active/unique address counts, and stablecoin supply. Unavailable source fields must remain clearly labelled.
3. Inspect the 30-observation TVL chart and check its retrieval timestamp and data-age note.
4. Review the three investment-thesis signals. Explain the explicit threshold method: greater than +1% is positive, less than -1% is negative, and between those values is stable. Missing comparisons remain inconclusive.
5. Inspect the NEAR-related GitHub project cards, latest repository pushes and commit messages. Open a repository to verify the evidence.
6. Open the source registry and quality warnings. Explain that TVL is not user adoption, GitHub activity is not proof of production usage, and the rule-based thesis is not investment advice.
7. Use Refresh data to request a fresh public snapshot.

The optional wallet login is for the separate private/admin workspace only. The public product does not call NEAR AI Cloud or Gemini. Payment collection and mainnet execution remain disabled.

## Hackathon submission

- Event: NEAR Hackathon 2026 — Build Beyond Boundaries.
- Track: Investment Thesis.
- Public repository: https://github.com/murisco/near-autonomous-research
- Demo hosting: https://meridian-dashboard.up.railway.app
- Public API: https://meridian-dashboard.up.railway.app/api/public/intelligence
- Submission description and judge demo script: `docs/hackathon-submission.md`.

MERIDIAN separates independently queried metrics, repository metadata, deterministic assessment rules, unavailable fields and source limitations. It does not present a model-generated answer as evidence.
