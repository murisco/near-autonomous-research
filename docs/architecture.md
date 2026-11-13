# Architecture

## Services

1. **Web application** — customer order intake and operator dashboard.
2. **Business API** — validates orders, applies policy, and coordinates work.
3. **Research worker** — gathers source-backed information and creates reports.
4. **Treasury module** — calculates spend, price floors, revenue splits, and ledger entries.
5. **NEAR adapter** — wraps NEAR AI Cloud and NEAR Intents integrations behind explicit feature flags.
6. **PostgreSQL** — persists orders, reports, usage, ledger entries, and audit events.

## Order lifecycle

`requested → validated → researching → report_ready → awaiting_payment → paid → delivered`

Failed or cancelled orders must have explicit terminal states and audit events.

## Safety boundaries

- Validate policy before starting paid inference.
- Stop new jobs when the kill switch is active.
- Enforce daily inference budgets and minimum report price server-side.
- Keep payment execution disabled by default.
- Use NEAR Intents dry-run quotes for the initial demo; do not label quotes or simulated ledger entries as completed transfers.
- Require explicit operator approval for mainnet transfers and payouts.
- Never store full-access account keys in source control or plaintext configuration.

## Auditability

Record each order transition, quote, payment status, inference cost, revenue allocation, and payout status with timestamps and references. A public ledger view must omit secrets and private customer information.
