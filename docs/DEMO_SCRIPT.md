# Demo script (about 4 minutes)

Updated 29 October 2026: verified runtime `98d6ad4653aa3701b38a81577650377f2ad30792`, CI 40839628066 all five jobs passed. Actual signed Airwallex deposit delivery and fresh EUR5 refund processing→SENT→PAID completed; liability/conservation verified. Payment-link request refused HTTP 401 (honest draft); provider external replay returned success:false. Successful Claude extraction waits for credit (user expects it in one day). Fresh isolated Neon 13/13 passed in 1,629.50s at baseline 6c43626; final-code CI PostgreSQL 17 is primary evidence. Final main-branch deployed SHAs/smoke/restart will be recorded separately after release.


Use a fresh **Sample data** organization at https://35-207-220-110.sslip.io. Every figure on screen is computed from the organization's own state.

| Time | Screen | Say / do |
|---|---|---|
| 0:00 | Home → Get started | "Ledgerline reconciles incoming payments for a multi-currency business. When a payment doesn't add up, it asks the payer's own agent, verifies the answer, then acts, and never pays twice." Create the sample organization. |
| 0:25 | Inbox | Six payments arrived in USD, EUR, GBP. "Rules in code made the first plan: two clean matches (one with a 15 EUR bank fee written off), a partial payment, an unknown payment and two apparent duplicates." |
| 0:50 | Payments → DEP-1003 | GBP 2,400 against the 3,600 invoice INV-2260 is far more than a bank fee: partial payment, 1,200 still due, balance-due email drafted for a person to send (labelled draft: no fake payment URL). |
| 1:15 | Payments → DEP-1005 → Ask payer agent | Original plan: refund a duplicate. The payer's agent answers over MCP with a signed claim: "advance for the March invoice". Checks: signature ✓, bound to this deposit and fresh ✓, our records ✓. Revised plan: hold as customer credit; no money leaves. |
| 1:55 | Payments → DEP-1004 → Ask payer agent | The agent claims another customer's invoice. Signature ✓ but records ✗: rejected, escalated to a person with the reason. "Nothing an agent says moves money until all three checks pass." |
| 2:25 | Walkthrough → Treasury step | A EUR bill is due; the agent quotes and converts only the shortfall above the EUR reserve. Pending FX proceeds are never spendable until settled. |
| 2:50 | Approvals | DEP-1006 really was paid twice. The refund is over the auto limit, so a person approves it; the approval is bound to amount, currency, destination and evidence. Execute: one refund under the duplicate lock. |
| 3:20 | Walkthrough → Bank SENT, then PAID | SENT keeps the liability; only PAID is final. |
| 3:40 | Ledger / scorecard | Deposits = matched + credits + refunds + unapplied, to the cent, per currency. Scorecard: 6 deposits, 4 settled without a person, 1 approval, 1 escalation with a reason, 0 double payments. |

Close with the honesty line: "Judge workspaces use a simulated bank and simulated payer agents over real MCP. Operator-only Airwallex sandbox deposits and one EUR→GBP conversion settled on 28 Oct 2026 (`a4c9f2c`); settlements reached Ledgerline by polling. On29 Oct, signed deposit delivery and an independently approved EUR5 refund through SENT then PAID were verified. External replay was refused by Airwallex. The Claude key is configured, but its first actual call was refused for insufficient credit. Judge workspaces without a key use labelled offline rules."

Figures checked on 28 Oct 2026 against a fresh sample organization (local run of the same code): DEP-1005 verified → advance credit; DEP-1004 rejected on the records check (INV-2253 belongs to Brightwave); DEP-1006 refunded after one approval; scorecard 6 deposits, 4 settled without a person, 1 approval, 1 escalation, 0 double payments, ledger balanced.
