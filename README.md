# MERIDIAN — Autonomous Onchain Research Business

MERIDIAN is an AI-native research business built for the **NEAR Hackathon 2026 — Autonomous Business track**.

It turns a customer's blockchain research question into a priced research report, applies human-defined operating rules, tracks the cost and projected economics of fulfilling the order, and records the business activity in an auditable ledger.

The product is designed around the hackathon's one-agent research-shop brief: sell reports, purchase its own inference, obey configurable limits, and distribute a fixed share of revenue to contributors. The current deployed prototype implements the research and business-control loop; payment settlement and automated token payouts remain disabled until their testnet flow and wallet custody are configured.

## What works in this build

- Customer research order intake with a report price.
- Server-side policy checks for minimum report price, daily inference budget, kill switch, and revenue split.
- **Live NEAR chain TVL and protocol research** from DefiLlama by default. The report includes source URLs, retrieval time, chain TVL, historical movement, protocol-level data when available, and explicit methodology caveats.
- Optional **NEAR AI Cloud** analysis of the collected source data when `NEAR_AI_API_KEY` is configured. Without the key, MERIDIAN still produces a source-backed deterministic report and does not pretend AI Cloud inference ran.
- Projected inference cost, profit, and operator/contributor allocation.
- An off-chain audit ledger covering orders, policy approval, research, source records, payment-quote status, and projected accounting.
- A dashboard showing orders, reports, business metrics, operating rules, and the audit trail.
- PostgreSQL persistence in the Railway deployment; SQLite for local development.

## What is not live yet

- Customer payment collection or settlement through NEAR Intents (only the community Tidepool dry-quote endpoint is called).
- Automated contributor payouts.
- OutLayer custody wallet creation and policy configuration.
- On-chain audit anchoring.

The current payment event is labelled **simulation only**. It is not a payment, deposit address, settlement, or completed transfer. Revenue received stays at zero until a verified payment status is connected. Payout shares are projections, not transfers. Mainnet execution remains disabled.

NEAR Intents' production 1Click API is mainnet-only. A community-operated NEAR testnet sandbox named Tidepool offers a 1Click-compatible test environment, but it is **not affiliated with NEAR or Defuse** and its deposit-address keys are operated by its maker. It is suitable only for valueless test tokens and must never receive real assets. MERIDIAN does not yet claim Tidepool or OutLayer integration.

## Business rules

Edit `config/business-rules.yaml`:

- `limits.max_inference_spend_per_day`: maximum inference budget per day.
- `limits.minimum_report_price`: lowest accepted report price.
- `revenue_split.operator_percent` and `contributors_percent`: percentages that must total 100.
- `safety.kill_switch`: pauses new orders when true.
- `safety.payments_enabled`: remains false in this build.
- `safety.mainnet_execution_enabled`: remains false in this build.
- `safety.require_human_approval_for_payouts`: requires operator oversight before payouts.

The current demo policy is illustrative. Review it before any real operation.

## Architecture

- **Dashboard:** Next.js customer research desk and business control room.
- **Business API:** FastAPI order lifecycle, policy checks, report orchestration, accounting, and ledger API.
- **Research provider:** DefiLlama public chain and protocol data; optional NEAR AI Cloud analysis.
- **Treasury logic:** tracks spend estimates, report price, projected profit, and revenue splits.
- **Database:** SQLAlchemy with PostgreSQL on Railway.
- **Payment and custody adapters:** planned for a testnet-only NEAR Intents/Tidepool and OutLayer flow; not yet active.

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

Open `http://localhost:3000`. The Next.js API proxy forwards requests to the backend using the server-side `BACKEND_URL`.

### Optional NEAR AI Cloud analysis

Set these in the backend environment (never commit secrets):

```bash
NEAR_AI_API_KEY=your_key
NEAR_AI_BASE_URL=https://cloud-api.near.ai/v1
NEAR_AI_MODEL=Qwen/Qwen3.8-27B
```

NEAR AI Cloud is OpenAI-compatible. The application sends source data to the selected model for analysis. Do not claim that the call occurred unless the report's metadata says `near_ai_live`.

## Tests

```bash
python -m compileall -q backend
pytest -q
```

## Judge walkthrough

1. Open the deployed Railway dashboard.
2. Submit a specific NEAR ecosystem research question with a quote of at least the configured minimum.
3. Open the generated report and inspect the live-source label, source links, retrieval time, and methodology notes.
4. Review the business performance panel for the report quote, estimated compute cost, projected profit, and configured revenue split.
5. Inspect the Tidepool dry quote preview, then open the audit ledger to review the order, policy, research, source, quote and accounting events.
6. Confirm that revenue received is still zero and that payment collection, payouts, and mainnet execution are not falsely presented as complete.

## Hackathon submission

- Event: NEAR Hackathon 2026 — Build Beyond Boundaries.
- Track: Autonomous Business (`business`).
- Public repository: https://github.com/murisco/near-autonomous-research
- Demo hosting: https://meridian-dashboard.up.railway.app

A working public prototype and an honest explanation of the currently disabled payment/payout steps are intentional. The project does not claim unimplemented on-chain behavior.
