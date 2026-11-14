# NEAR Hackathon 2026 submission pack

## Project

**MERIDIAN — Autonomous Onchain Research Business**

**Track:** Autonomous Business

**Live demo:** https://meridian-dashboard.up.railway.app  
**Source code:** https://github.com/murisco/near-autonomous-research

## Project description

MERIDIAN turns a customer’s blockchain research question into a governed research order. It applies human-defined pricing, daily inference budgets and a kill switch before collecting public ecosystem data and producing an evidence-led report. Its research pipeline combines chain TVL and protocol data, historical changes, daily network activity, stablecoin supply and official NEAR ecosystem sources. It flags excluded or inconsistent data, labels publisher-reported metrics, and leaves unavailable values blank rather than inventing evidence.

Each order records its research sources, policy decisions, estimated inference cost, projected profit and proposed operator/contributor allocation in a PostgreSQL audit ledger. A dashboard exposes the order lifecycle, report output, operating budget and business activity.

The system is built with Next.js, FastAPI and PostgreSQL, deployed on Railway. It uses NEAR AI Cloud's OpenAI-compatible chat-completions API as the primary question-specific analysis provider, with Gemini as a fallback. The report records which provider generated the analysis and shows a sanitized diagnostic if neither provider succeeds. It also includes a Tidepool community-sandbox dry-quote adapter. Tidepool is only a valueless quote preview, not an official NEAR/Defuse testnet. Customer payments, contributor payouts, wallet custody and mainnet execution are not enabled; revenue received remains zero until verified settlement exists.

MERIDIAN focuses on making an autonomous business inspectable: every order is subject to explicit operating limits, missing data is visible, and financial projections are not misrepresented as completed transactions.

## Suggested judge demo

1. Open the live dashboard and point out the research mode, NEAR AI Cloud configuration state, payment and mainnet safety controls.
2. Submit two clearly different research questions and confirm that the reports answer each question rather than repeating a generic summary. Check the AI provider/model label at the top of each report.
3. Submit one focused research question at the configured minimum quote. Use a question that asks for NEAR TVL, activity and stablecoin supply.
4. Walk through the generated report: current and historical TVL, protocol exclusions, activity windows, stablecoin supply/token breakdown, official-source claims, source timestamps and data-quality warnings.
5. Explain that the stablecoin collector validates NEAR-specific payloads and has primary/compatibility-host fallback. The backend CI runs a live smoke test for the three stablecoin endpoints.
6. Show the returned Tidepool dry quote if the sandbox provides one. Explicitly point out that it creates no deposit address and sends no funds.
7. Open the audit ledger and show the order, research, source-recording and projected-accounting events.
8. Finish on the business metrics: quoted sales and projected allocations are not collected revenue; revenue received is zero; payments and mainnet execution are disabled.

## Verification evidence

- Backend CI compiles the backend and runs the automated test suite.
- Backend CI smoke-tests the NEAR stablecoin history, catalogue and chain-aggregate endpoints, validating that responses contain usable NEAR data.
- Frontend CI builds the Next.js dashboard.
- Railway hosts the API, dashboard and PostgreSQL services.

Check the GitHub Actions runs and Railway deployments immediately before recording or submitting, because these statuses can change.

## Current limitations to disclose

- Hosted AI output still depends on a successful NEAR AI Cloud or Gemini provider response; confirm the provider label on the final live demo report.
- Transaction-level NEAR Intents Explorer analytics require a partner JWT.
- Tidepool is a community sandbox and the integration is quote-only.
- No customer payment, settlement, payout, wallet custody or onchain audit anchoring is performed.
- Stablecoin supply is not DEX liquidity, trading volume or user adoption.
