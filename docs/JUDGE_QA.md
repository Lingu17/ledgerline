# Judge Q&A, short and honest

**Who would actually answer your agent call today?**
No outside company yet. The built-in payer agents are simulated, with their keys on our server. A customer can instead run its own agent with its own key and register its address and public key; Ledgerline then asks it over the network and applies the same three checks. That path is tested end to end with our reference agent as a separate process, and anyone can run it (see the quickstart). On 3 Nov 2026 it also ran across the internet: the reference agent ran on the owner's own PC behind a Cloudflare tunnel, the live site asked it about a practice payment, and its signed answer passed the three checks and was labelled Customer's own agent. That was the owner's machine, not an independent party, and no real company runs one today.

**Why trust a signed answer at all?**
We don't trust it on its own. The signature only says who is speaking. The answer must also be about this exact payment, be fresh, and agree with our records. DEP-1004 shows a correctly signed answer being rejected because the records disagree.

**What stops the agent from sending money?**
The agent only proposes. Small refunds backed by a verified answer go out under a limit the company sets, and the pause switch stops them. Anything over the limit needs two people, and when the agent proposed it, the approver can't also send it: the page shows no Send button to them, and the server refuses the request (403, covered by an automated test). Claude never states an amount and has no tool that moves money.

**What if a remittance email contains instructions for the AI?**
It is treated as data. Tests feed emails that say "ignore previous instructions", "refund 9,999 to this account", "approve this", or contain a fake tool call, through the offline reader and through a model that does what the email says. In every case the result is stored as advisory evidence only, off-schema output becomes an escalation, and no plan, approval or operation changes; no amount or account from the email appears anywhere. The tools themselves have no amount or account field.

**Is the two-person rule real if you used two of your own accounts?**
The rule checks accounts, not people, and we say so. The live sandbox runs show the control and the bank call. They aren't independent review.

**What ran on real Airwallex?**
Signed deposit webhooks, a refund through SENT → PAID as exactly one transfer, a currency conversion, a EUR 100 bill payment, a paid early-payment link, beneficiaries and live rates. Agent-proposed refunds, and the practice teammate, have only run on the simulated bank.

**What happens if the bank times out mid-transfer?**
The refund keeps one request ID for its whole life. After a timeout or an unclear answer, Ledgerline looks that ID up with the bank before anything is sent again, and a lock allows only one live refund per payment. Tests cover timeouts and concurrent sends, and each ends with exactly one transfer. SENT keeps the liability on the books; only PAID releases it.

**How do you know the matching is right?**
An accuracy run on synthetic data (200 made-up companies and 25 practice walkthroughs, rules only) makes 51,475 checks across 8,826 payments and 4,087 invoices, with 0 mismatches against a separate reference model. There are also over 400 backend tests, and CI runs them on PostgreSQL as well. See [ACCURACY_REPORT](ACCURACY_REPORT.md).

**How does it compare with Airwallex's own reference builds?**
Compared with the design rules in Airwallex's public AWS reference builds ([awx-devx/airwallex-agentic-banking-aws](https://github.com/awx-devx/airwallex-agentic-banking-aws)). This is our own comparison; Airwallex has not reviewed Ledgerline.

| Rule in the reference builds | Ledgerline |
|:--|:--|
| The model only reads and proposes; no tool input names an account, tenant or request id | Yes. Claude reads documents through typed tools and cannot state an amount; payer agents only answer questions |
| Code computes every amount and re-checks the policy before anything runs | Yes. Rules in code set amounts; the approved scope is re-checked under a lock before sending |
| An approval is bound to the exact proposal, comes from someone other than the proposer, and arrives before it expires | Yes. Bound to a scope hash, proposer ≠ approver, and an approval expires after 72 hours. In addition, the approver of an agent-proposed refund cannot also send it |
| A few low-risk actions run without approval, within policy limits | Yes. Refunds under the limit with a verified answer; the pause switch stops them |
| Every write is idempotent; after an unknown outcome, read back before sending again | Yes. One request id per refund or bill payment, looked up before any retry, one live refund per payment |
| Tenants are resolved on the server, never from model output | Yes. Every request is bound to the signed-in member's organization; each organization has its own database file |
| Only one separately privileged component holds the Airwallex key and can write | **Not the same.** All money-out goes through one provider adapter in code, but it runs in the same server process as the rest of the app, which holds the keys |
