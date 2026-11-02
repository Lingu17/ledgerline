# Ledgerline: judge quickstart

**Live app: https://35-207-220-110.sslip.io** (always on; website, API and database on one Google Cloud server). Architecture in 3D: https://35-207-220-110.sslip.io/#/architecture

## Five-minute path

1. Open the link and click **Get started**.
2. Enter any name, organization and email (nothing is emailed) and a password of 12+ characters with upper- and lower-case letters and a digit. Choose **Practice company**. It waits for you to press **Ask payer's agent** so you can watch; **Payments → Receive an unclear payment** shows the agent acting with no click, as it does in a real company. That payment is built to match the simulated agent's table. You get your own isolated organization; other judges cannot see it.
3. **Inbox**: cash by currency and the payments that need a decision.
4. **Payments → DEP-1005** (Dunmore, looks like a duplicate) → **Ask payer's agent**. The payer's agent answers over MCP with an Ed25519-signed claim; all three checks pass (signature, bound to this deposit and fresh, our records agree) and the plan is revised: the money becomes **advance credit** instead of a refund. No money moved.
5. **Payments → DEP-1004** (Fjord) → **Ask payer's agent**. The agent claims another customer's invoice; the signature verifies but the records check fails, so the claim is **rejected** and the case goes to a person with the reason.
6. Optional: on DEP-1004 click **Read remittance…** and paste any remittance email (or upload a PDF). Claude reads it and must answer through a typed tool; the result is stored as **advisory evidence** and checked against the records, never applied by itself. Each organization has a small daily Claude budget.
7. **Practice steps** runs the rest of the story: balance request for the short payment, FX for the EUR bill, the over-limit refund: one person approves it (Approvals → Approve…) and a different member sends it (**Execute refund**), so invite a second member under Team and use a private window, bank SENT (liability kept) then PAID (released), and the scorecard: 6 deposits, 4 decided without a person and 3 of those fully closed, 1 approval, 1 escalation with its reason, 0 double payments, ledger balanced.
8. **Ledger**: deposits = applied + credits + refunds + not yet placed, per currency, to the cent.

9. **CEO view**: the whole company on one screen.

Day-to-day work without the practice steps: create an organization with **My company**, add customers and invoices, record or import payments (CSV), resolve escalations, invite teammates with roles (Team). A refund you propose must be approved by someone else.

## What is real and what is simulated

| Part | Status |
|---|---|
| Matching rules, ledger, approvals, locks, roles, tenant isolation | Real application code |
| Storage | SQLite files per organization on the VM's persistent disk, backed up nightly; survives restarts, reboots and redeploys |
| Sign-in | Email/password, or Google. Apple is not offered |
| Payer agents | Simulated customer agents, real MCP protocol and real Ed25519 signatures |
| Bank in your organization | Built-in **simulated bank**, labelled in the top bar. No real money |
| Airwallex sandbox | A company connects its own sandbox keys under Settings; the server's shared credentials are reserved by an allow-list, so judges never touch them. On this host: signed `deposit.settled` webhooks (HTTP 200, each booked once), current rates, beneficiary validation and creation, and a refund approved by a second member and completed SENT→PAID as exactly one Airwallex transfer (30 Oct). Earlier, on the previous host with the same sandbox account: deposits and an FX conversion. See [INTEGRATION_EVIDENCE](INTEGRATION_EVIDENCE.md) |
| Claude remittance reading | Real Claude API (`claude-opus-5-5`) through strict typed tools; advisory only; per-organization daily budget |

Exact evidence, dates and remaining limitations: [INTEGRATION_EVIDENCE](INTEGRATION_EVIDENCE.md) and [FULL_APPLICATION_ACCEPTANCE_REPORT](FULL_APPLICATION_ACCEPTANCE_REPORT.md).
