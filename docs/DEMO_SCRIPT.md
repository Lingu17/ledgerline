# Demo script (under 5 minutes)

Organizers review **the video, the code and the writeup**, and the walkthrough must stay under five minutes (the official site's limit). Record at 1080p with the browser zoomed for legibility.

**The one story:** a finance person gets a payment that looks like a duplicate. Refunding it would be a mistake. The agent asks the payer's agent, verifies the answer, and changes its decision before any money moves. Everything else in the video supports that.

Prepare two windows: a fresh **Practice company** at https://35-207-220-110.sslip.io, and **Ledgerline Singapore** (connected to the Airwallex sandbox). Do not show the setup. The structure follows the builder guide: goal, initial plan, new information, revised decision, resulting balance or escalation.

| Time | Screen | Say / do |
|---|---|---|
| 0:00 | Practice company → Payments → DEP-1005 | "This USD 1,200 looks like a duplicate, so the first plan is to refund it. If that's wrong, I've just annoyed a good customer." |
| 0:20 | **Ask payer's agent** | **New information:** a signed answer over MCP, "advance for the March invoice". Show the three checks: signature ✓, bound to this deposit and fresh ✓, our records ✓. **Revised decision:** hold as credit; the refund is dropped before any money moved. |
| 0:50 | Home screen or a sentence over Inbox | "Goal: reconcile every incoming payment for a 12-person company billing in three currencies, never pay twice, and keep a person in control of money that leaves." Six payments; rules in code settled the clean ones. |
| 1:05 | Payments → DEP-1004 → **Ask payer's agent** | The same agent mechanism, but it lies: correctly signed, claiming another customer's invoice. Signature ✓, records ✗. Rejected and escalated with the reason. "A signature proves who said it, not that it's true." |
| 1:25 | Payments → **Receive an unclear payment** | "In a real company nobody presses that button. This practice payment is built to match the simulated agent's records, and the agent asks by itself." Open it: first plan, agent's answer, revised decision, no click. |
| 1:35 | Payments → DEP-1003 | GBP 2,400 against 3,600 is more than a bank fee: partial, 1,200 still due, and a balance request for exactly that amount. |
| 1:50 | DEP-1003 → **Open email draft** | The ready-to-send message with the exact balance. Five seconds; do not dwell. |
| 1:55 | Practice steps, or Approvals | DEP-1006 really was paid twice and is over the auto-limit. One member approves the exact amount, destination and evidence hash; the Approvals page tells them they can't also send it, so a second member, in another window, sends it. Invite that member before recording. SENT keeps the liability; only PAID releases it. |
| 2:30 | Ledger and scorecard | Deposits = applied + credits + refunds + not yet placed, per currency, to the cent. 6 deposits, 4 decided without a person and 3 of those fully closed, 1 approval, 1 escalation with a reason, 0 double payments. |
| 2:50 | Treasury → Add a cash squeeze | Cash runs short: fund, convert only the shortfall, defer, escalate, each with a reason. New cash reopens only the decisions it changes. Keep this to 20 seconds. |
| 3:10 | **Switch to Ledgerline Singapore** | "That was a simulated bank. This is my Airwallex sandbox." Treasury → Bring cash in early: the paid EUR 197 link. Then Bill payments: EUR 100 to the beneficiary, SENT then PAID. |
| 3:40 | Airwallex sandbox dashboard → Transfers | The transfer on Airwallex's own screen, one only. |
| 4:00 | Activity → **Verify log integrity**, Treasury → **Replay** | Every decision can be replayed to the identical answer, and editing the log is detected. |
| 4:15 | **CEO view** | One screen: are we safe, what the agent handled, what needs you, can I trust the numbers. Say the time-saved figure is an estimate. |
| 4:30 | Architecture page | "Claude reads messy documents through typed tools, and rules in code decide the money. It can never move any." End on: "every decision explained, every cent accounted for." |

**Say these limits on camera:**

- "Payer agents here are simulations using real MCP and real signatures; I run them myself, and one lies on purpose. Customers mostly don't have agents yet, so today rules, the document reader and a person handle those cases, and the same checks are ready when they do."
- "PAID on the sandbox comes from Airwallex's simulation call. No real money moves."
- For the EUR 100 payment, if both accounts are yours: "Both accounts here are mine, so this shows the control, not independent review." Drop this line if a real second person approved it.

Do not click through every page. If you run long, cut the cash squeeze first. To show a wrong-currency payment, use **Payments → Add a wrong-currency payment** after the scorecard: it adds a seventh payment, so the scorecard no longer reads 6.

Figures checked on 29 Oct 2026 against a fresh sample organization: DEP-1005 → advance credit; DEP-1004 rejected on the records check (INV-2253 belongs to Brightwave); DEP-1006 refunded after one approval; scorecard 6 / 4 / 1 / 1 / 0, ledger balanced. Singapore figures from the 2 Nov live runs.
