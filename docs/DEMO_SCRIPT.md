# Demo script (about 4 minutes)

Use a fresh **Sample data** organization at https://35-207-220-110.sslip.io. Every figure on screen is computed from that organization's own state. The structure follows the builder guide: the user's goal, the agent's initial plan, new information, the revised decision, and the resulting balance or escalation.

| Time | Screen | Say / do |
|---|---|---|
| 0:00 | Home → Get started | "Goal: reconcile every incoming payment for a multi-currency business, never pay twice, and keep a person in control of money that leaves." Create the sample organization. |
| 0:25 | Inbox | Six payments in USD, EUR and GBP. "Rules in code made the first plans: two clean matches (one with a 15 EUR bank fee written off), a partial payment, an unknown payment and two apparent duplicates." |
| 0:50 | Payments → DEP-1003 | GBP 2,400 against the 3,600 invoice is far more than a fee: partial, 1,200 still due, a balance request is drafted (labelled draft, no invented payment URL). |
| 1:10 | Payments → DEP-1005 → Ask payer's agent | **Initial plan:** refund a duplicate. **New information:** the payer's agent answers over MCP with a signed claim, "advance for the March invoice". Checks: signature ✓, bound to this deposit and fresh ✓, our records ✓. **Revised decision:** hold as customer credit; the refund is dropped before any money moves. |
| 1:50 | Payments → DEP-1004 → Ask payer's agent | The agent claims another customer's invoice. Signature ✓, records ✗: rejected and escalated with the reason. Optionally **Read remittance…**: Claude proposes through a typed tool; the proposal is evidence, checked against our records, never an action. |
| 2:25 | Walkthrough → Cover the EUR bill, then Treasury | A EUR bill is due. The agent books a single-use quote and converts only the shortfall above the EUR reserve; pending proceeds are not spendable until settled. |
| 2:50 | Approvals | DEP-1006 really was paid twice and the refund is over the auto-limit, so a person approves the exact scope (amount, currency, destination, evidence hash) and executes it under the duplicate lock. |
| 3:15 | Walkthrough → Bank SENT, then PAID | SENT keeps the liability on the books; only PAID releases it. |
| 3:35 | Ledger and scorecard | Deposits = applied + credits + refunds + unapplied, per currency, to the cent. Scorecard: 6 deposits, 4 settled without a person, 1 approval, 1 escalation with a reason, 0 double payments. |
| 3:50 | Architecture page | One Google Cloud VM; Airwallex sandbox for the operator organization; Claude and payer agents only supply evidence. |

Honesty line: "Judge organizations use a simulated bank and simulated payer agents over real MCP. The operator's own organization runs against the Airwallex sandbox: signed deposit webhooks, FX and an independently approved refund were verified live. Hosted payment links were refused by the sandbox (HTTP 401), so Ledgerline keeps an honest draft."

Figures checked on 29 Oct 2026 against a fresh sample organization (local run of the deployed code, and the README screenshots): DEP-1005 → advance credit; DEP-1004 rejected on the records check (INV-2253 belongs to Brightwave); DEP-1006 refunded after one approval; scorecard 6 / 4 / 1 / 1 / 0, ledger balanced.
