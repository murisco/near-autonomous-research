# NOVA — Autonomous Onchain Intelligence Business

An AI-native onchain research business built for the NEAR Hackathon 2026 (Autonomous Business track).

NOVA is designed to turn customer research requests into structured blockchain intelligence reports, manage the cost of producing them, calculate revenue shares, and maintain an auditable record of business activity.

## Current build status

The first end-to-end **demo workflow** is implemented:

- A customer submits a research question and report quote.
- Human-defined rules validate the minimum price, daily inference budget, kill switch, and revenue split.
- A clearly labelled synthetic demo provider generates a report preview.
- The accounting logic calculates estimated inference cost, projected profit, and the 80/20 split.
- Every workflow step is written to an off-chain audit ledger.
- The web dashboard displays orders, reports, business metrics, and audit events.

**Not yet implemented:** live blockchain data retrieval, NEAR AI Cloud inference, NEAR Intents execution, actual payment collection, onchain treasury operations, and real payouts. The current demo does not claim to perform any of those actions.

## Product workflow

1. A customer requests an onchain intelligence report.
2. The business checks pricing, spending limits, and the kill switch.
3. The research provider generates a report. The current provider is synthetic demo data; live source adapters are a future integration.
4. A payment quote is represented as a simulation-only event.
5. The accounting engine calculates projected costs and revenue shares. Unpaid quotes are not counted as collected revenue.
6. The business records each step in its off-chain audit ledger.

## Architecture

- **Dashboard:** Next.js operator control room and research order interface.
- **Business API:** FastAPI order lifecycle, orchestration, business policy, and report delivery.
- **Database:** SQLAlchemy models, SQLite for local development, and PostgreSQL support for deployment.
- **Policy engine:** YAML business rules with daily inference budget, report price floor, revenue split, and kill switch.
- **Research provider:** synthetic demo provider today; source-backed chain research and NEAR AI Cloud adapter are planned.
- **NEAR adapter:** NEAR AI Cloud and NEAR Intents integration are planned; no live calls are made by this demo build.

## Human-defined operating rules

The business enforces:

- Maximum inference spend per day.
- Minimum price per report.
- Revenue split percentages that total 100%.
- A kill switch to pause new orders.
- Human approval for payouts and irreversible actions.

The current example values in `config/business-rules.yaml` are for the hackathon demo only. Review them before any real operation. Payments and mainnet execution remain disabled.

## Local development

### 1. Start the API

From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.app.main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`. Interactive API documentation is at `http://localhost:8000/docs`.

The default database is a local SQLite file named `data.db`. Set `DATABASE_URL` to a PostgreSQL URL to use PostgreSQL instead.

### 2. Start the dashboard

In a second terminal:

```bash
cd frontend
npm install
BACKEND_URL=http://localhost:8000 npm run dev
```

Open `http://localhost:3000`. The Next.js API proxy forwards dashboard requests to the backend using the server-side `BACKEND_URL` variable.

### 3. Run the automated tests

From the repository root:

```bash
python -m compileall -q backend
pytest -q
```

GitHub Actions also runs the backend test suite on pushes and pull requests to `main`.

## Demo safety and accounting

- Research output is labelled `synthetic_demo`; it is not live chain analysis.
- Payment quotes are simulations only. No payment provider or NEAR Intents endpoint is called.
- Unpaid orders count toward quoted sales, not collected revenue.
- Inference costs and revenue shares are projections, not real transfers.
- The audit ledger is currently off-chain and stored in the application database.
- Payments, mainnet execution, and payouts remain disabled.

NEAR account keys must never be stored in plaintext in this repository. Verify current contract addresses, endpoints, and SDK versions against official NEAR documentation before integrating them.

## Judge walkthrough

1. Start the backend and dashboard using the commands above.
2. Submit a research question from the Research Desk.
3. Open the generated report and confirm its synthetic-demo notice.
4. Review the quoted sale, estimated inference cost, projected profit, and configured revenue split.
5. Open the audit ledger and inspect the order, research, report, quote, and accounting events.
6. Confirm that collected revenue remains zero and payments/mainnet execution remain disabled.

## Hackathon

- Event: NEAR Hackathon 2026 — Build Beyond Boundaries
- Track: Autonomous Business (`business`)
- Submission requirements: public repository, public X demo post, and final submission form.
