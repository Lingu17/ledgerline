# Demo script (about 4 minutes)

Use a fresh **Sample data** organization at https://ledgerline-black-iota.vercel.app. Every figure on screen is computed from the organization's own state.

| Time | Screen | Say / do |
|---|---|---|
| 0:00 | Home → Get started | "Ledgerline reconciles incoming payments for a multi-currency business. When a payment doesn't add up, it asks the payer's own agent, verifies the answer, then acts, and never pays twice." Create the sample organization. |
| 0:25 | Inbox | Six payments arrived in USD, EUR, GBP. "Rules in code made the first plan: two clean matches, a fee-sized short payment, a partial payment, an unknown payment and two apparent duplicates." |
| 0:50 | Payments → DEP-1003 | 970 against 1,000 is more than a bank fee: partial payment, 30 still due, balance-due request drafted (labelled draft: no fake payment URL). |
| 1:15 | Payments → DEP-1005 → Ask payer agent | Original plan: refund a duplicate. The payer's agent answers over MCP with a signed claim: "advance for the March invoice". Checks: signature ✓, bound to this deposit and fresh ✓, our records ✓. Revised plan: hold as customer credit; no money leaves. |
| 1:55 | Payments → DEP-1004 → Ask payer agent | The agent claims another customer's invoice. Signature ✓ but records ✗: rejected, escalated to a person with the reason. "Nothing an agent says moves money until all three checks pass." |
| 2:25 | Walkthrough → Treasury step | A EUR bill is due; the agent quotes and converts only the shortfall above the EUR reserve. Pending FX proceeds are never spendable until settled. |
| 2:50 | Approvals | DEP-1006 really was paid twice. The refund is over the auto limit, so a person approves it; the approval is bound to amount, currency, destination and evidence. Execute: one refund under the duplicate lock. |
| 3:20 | Walkthrough → Bank SENT, then PAID | SENT keeps the liability; only PAID is final. |
| 3:40 | Ledger / scorecard | Deposits = matched + credits + refunds + unapplied, to the cent, per currency. Scorecard: 6 deposits, 4 settled without a person, 1 approval, 1 escalation with a reason, 0 double payments. |

Close with the honesty line: "This deployment uses a simulated bank; the Airwallex sandbox adapter and Claude reader are built but not connected here."
