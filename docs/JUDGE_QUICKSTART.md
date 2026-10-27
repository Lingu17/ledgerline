# Ledgerline: judge quickstart

**Live app:** https://ledgerline-black-iota.vercel.app

Free hosting: the backend sleeps when idle, so the **first request can take about a minute**. If you see "server is not reachable", wait a moment and retry.

## Five-minute path

1. Open the link and click **Get started**.
2. Enter any name, organization and email (it does not need to be real; nothing is emailed) and a password of 12+ characters with upper- and lower-case letters and a digit. Choose **Sample data** and create the organization. You get your own isolated workspace; other judges cannot see it.
3. **Inbox**: cash by currency, and the payments that need a decision.
4. **Payments → DEP-1005** (Dunmore, looks like a duplicate): click **Ask payer agent** (about 9 seconds: it starts the payer's real MCP agent process on a small free server). The payer's agent answers over MCP with a signed claim; all three checks pass (signature, freshness and binding, our records) and the plan is revised: the money becomes **advance credit** instead of a refund.
5. **Payments → DEP-1004** (Fjord): **Ask payer agent**. The agent claims another customer's invoice; the signature verifies but the records check fails, so the claim is **rejected** and the case goes to a person.
6. **Walkthrough** (left menu) runs the full six-payment story step by step: payment link draft for the short payment, FX for the EUR bill, a refund that needs a person's approval, bank SENT (not final) then PAID, and the closing scorecard.
7. **Ledger**: deposits = allocated + credits + refunds + unapplied, per currency, to the cent.

Ordinary work without the walkthrough: create an organization with **An empty workspace**, then add customers and invoices (Customers & invoices), record or import payments (Payments → Record payment / Import CSV), resolve escalations, and invite teammates with roles (Team).

## What is real and what is simulated

| Part | Status |
|---|---|
| Matching rules, ledger, approvals, locks, roles, tenant isolation | Real application code |
| Storage | Real PostgreSQL (Neon free tier); your organization survives backend restarts and redeploys |
| Sign in with Google / Apple | Buttons shown but disabled: not configured on this server |
| Payer agents | Simulated customer agents, real MCP protocol and real Ed25519 signatures |
| Bank | Built-in **simulated bank** (labelled in the top bar). No real money |
| Airwallex sandbox | Adapter implemented; **not connected** on this deployment (no credentials) |
| Claude remittance reading | Implemented; **not connected** (no API key); a labelled deterministic reader is used |

See `docs/INTEGRATION_EVIDENCE.md` for exactly what has and has not been verified.
