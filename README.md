# Autonomous Research Business

An autonomous onchain intelligence business built for the NEAR Hackathon 2026 (Autonomous Business track).

The product is designed to research blockchain projects, produce paid intelligence reports, account for operating costs, and distribute revenue according to human-defined rules.

## Current status

Early scaffold. The repository currently documents the product and its safety constraints. Payment execution, live research integrations, and automated payouts are not yet implemented.

## Product workflow

1. A customer requests an onchain research report.
2. The business validates the request and checks pricing and budget rules.
3. A research agent gathers source-backed onchain and ecosystem information.
4. The report engine produces a report and records its provenance.
5. The customer receives a payment quote. Payment execution is only enabled after the relevant integration and explicit operator approval.
6. The treasury engine records revenue, inference costs, contributor allocations, and net operating balance.
7. Every business event is recorded in an auditable ledger.

## Architecture

- **Web app:** customer order flow and business operations dashboard.
- **Business API:** order lifecycle, orchestration, policy checks, and report delivery.
- **Research worker:** source collection, analysis, citations, and report generation.
- **Treasury service:** budget enforcement, cost accounting, and revenue-split calculations.
- **NEAR adapter:** NEAR AI Cloud integration and NEAR Intents payment quotes/settlement.
- **PostgreSQL:** orders, reports, policy configuration, accounting entries, and audit events.

## Human-defined operating rules

The business must enforce these rules before any paid or irreversible action:

- Maximum inference spend per day.
- Minimum price per report.
- Revenue split percentages that total 100%.
- A kill switch that stops new work and all payment execution.
- Explicit human approval for mainnet transfers, payouts, or other irreversible actions.

Secrets belong in environment variables and must never be committed to the repository. Use `.env.example` for variable names and placeholders only.

## NEAR integration and demo safety

NEAR Intents does not provide a testnet. The initial demo should use dry-run payment quotes and clearly labelled simulated accounting events. Never present simulated transfers as completed onchain transactions. Any mainnet payment path must remain disabled until configured and explicitly approved by the operator.

NEAR account keys must not be stored in plaintext in this repository. Use an appropriate scoped key or custody integration, and verify current contract addresses, endpoints, and SDK versions against official documentation rather than guessing.

## Local development

Setup instructions will be added alongside the application code. Do not assume a live payment integration exists until it is implemented and tested.

## Judge walkthrough

The completed README will provide numbered **“do X, see Y”** instructions. Each step will identify the expected result and distinguish simulated demo events from verifiable onchain transactions.

## Hackathon

- Event: NEAR Hackathon 2026 — Build Beyond Boundaries
- Track: Autonomous Business (`business`)
- Submission requirements: public repository, public X demo post, and final submission form.
