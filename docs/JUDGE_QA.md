# Judge Q&A, short and honest

**Who would actually answer your agent call today?**
No outside company yet. The built-in payer agents are simulated, with their keys on our server. A customer can instead run its own agent with its own key and register its address and public key; Ledgerline then asks it over the network and applies the same three checks. That path is tested end to end with our reference agent as a separate process; anyone can run it (see the quickstart), but no real company does today.

**Why trust a signed answer at all?**
We don't trust it on its own. The signature only says who is speaking. The answer must also be about this exact payment, be fresh, and agree with our records. DEP-1004 shows a correctly signed answer being rejected because the records disagree.

**What stops the agent from sending money?**
The agent only proposes. Small refunds backed by a verified answer go out under a limit the company sets, and the pause switch stops them. Anything over the limit needs two people, and when the agent proposed it, the approver can't also send it: the page shows no Send button to them, and the server refuses the request (403, covered by an automated test). Claude never states an amount and has no tool that moves money.

**Is the two-person rule real if you used two of your own accounts?**
The rule checks accounts, not people, and we say so. The live sandbox runs show the control and the bank call. They aren't independent review.

**What ran on real Airwallex?**
Signed deposit webhooks, a refund through SENT → PAID as exactly one transfer, a currency conversion, a EUR 100 bill payment, a paid early-payment link, beneficiaries and live rates. Agent-proposed refunds, and the practice teammate, have only run on the simulated bank.

**What happens if the bank times out mid-transfer?**
The refund keeps one request ID for its whole life. After a timeout or an unclear answer, Ledgerline looks that ID up with the bank before anything is sent again, and a lock allows only one live refund per payment. Tests cover timeouts and concurrent sends, and each ends with exactly one transfer. SENT keeps the liability on the books; only PAID releases it.

**How do you know the matching is right?**
An accuracy run on synthetic data (200 made-up companies and 25 practice walkthroughs, rules only) makes 51,475 checks across 8,826 payments and 4,087 invoices, with 0 mismatches against a separate reference model. There are also over 400 backend tests, and CI runs them on PostgreSQL as well. See [ACCURACY_REPORT](ACCURACY_REPORT.md).
