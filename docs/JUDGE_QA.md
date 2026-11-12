# Judge Q&A, short and honest

What is real and what is simulated is one table on the README's first screen: [what is real](../README.md#what-is-real-and-what-is-simulated). The answers below do not repeat it.

**Didn't your server sign both sides?**
For the built-in payer agents in practice companies, yes: their keys are held on this server, and we label them simulated. A customer's own agent signs with its own key, which the server never holds. That path has run twice outside the server: on 3 Nov from the owner's own PC, and in a run recorded on the [evidence page](https://35-207-220-110.sslip.io/evidence) when one is committed in `docs/evidence/outside-agent-run.json`. Both were operated by the Ledgerline author, so they show the mechanism across the internet with a separate key, not an independent party.

**Who approved the live payments?**
The owner, using two of their own accounts: one proposed and the other approved, for the sandbox refund (APR-FC97829A, SENT → PAID) and the EUR 100 bill payment (PAY-6C76DB78). That shows the control and the bank call, not independent review. The two-person rule checks accounts, not people.

**Is /attacks live?**
No. It shows the committed report from the last run of `backend/tests/test_attacks.py` (25 hostile attempts on the simulated bank), with its date and the commit of the code it ran on. The same suite runs in CI on every push; the page links the CI run on the commit the live server runs, read from GitHub. A test fails if the report is older than the code it describes. Running attacks on every page load was left out on purpose: it would put load on the live server for every visitor.

**What happens before any payer runs an agent?**
Ledgerline is useful without one. Rules in code settle the clear payments, write off fees within tolerance and prepare balance requests. For an unclear payment, the remittance email or PDF can be read (as advice only), and the payment goes to one queue with the reason and the next step. Asking the payer's agent is an extra path for the payments rules alone cannot settle.

**How does Airwallex gain?** (our view, not Airwallex's)
Reconciliation is where a finance team spends its time after the money arrives. Ledgerline works on an Airwallex account: deposit webhooks, transfers booked at PAID, conversions at Airwallex's own quotes, beneficiary validation and payment links. Fewer unexplained payments make it easier for a small company to receive cross-border payments there, and an open payer-agent protocol could let Airwallex customers answer each other's questions directly.

**What breaks at scale, and what's next?**
Today it runs on one server with one SQLite file per company; PostgreSQL is supported and runs the whole test suite in CI, but is not used live. Payer agents are asked in rounds with a time budget, and a failing agent is left alone for a while, so one slow payer cannot stall others. Claude reads have daily budgets per company and per server. In a [load test](archive/LOAD_TEST_2026-11.md) with simulated users, 100 judges at once finished the walkthrough with no errors (slowest p95 0.74 s) once practice companies asked their agents in-process; before that fix, 100 judges caused errors. Next: move live data to PostgreSQL, turn on the separate sending service that holds the bank keys, and run a pilot with a small number of SMEs that receive cross-border payments on Airwallex.

**Who would actually answer your agent call today?**
No outside company yet. The built-in payer agents are simulated, with their keys on our server. A customer can run its own agent with its own key and register its address and public key (Customers → Payer agent…, Owner only); Ledgerline then asks it over the network with the same three checks. Anyone can run the reference agent ([quickstart](JUDGE_QUICKSTART.md)); on 3 Nov it answered the live site across the internet from the owner's own PC, which shows the path, not an independent party. The protocol, with a JSON schema and a signed test vector, is in [PAYER_AGENT_SPEC](PAYER_AGENT_SPEC.md). Practice companies ask the simulated agents in-process over the same MCP protocol: in a [load test](archive/LOAD_TEST_2026-11.md), starting a separate process per question kept p95 under 2 s on every endpoint only up to 30 judges at once, while in-process 100 judges finished the walkthrough with no errors and the slowest endpoint at p95 0.74 s.

**Why would a payer run an agent for you?**
For its own sake: fewer "what was this payment for?" emails from its suppliers, its payment placed on the right invoice the same day, and no wrong refund it then has to send back. The agent answers one narrow question about its own payment, from its own accounts-payable records, and signs the answer.

**Why doesn't the AI decide?**
On purpose. Every money decision is made by rules in code, so the same inputs always give the same plan and **Replay this decision** can prove it; the model only reads documents (as advisory evidence) and explains. That is the line Airwallex's own agentic-banking reference builds draw too (the table at the end).

**Why trust a signed answer at all?**
We don't trust it on its own. The signature only says who is speaking. The answer must also be about this exact payment, be fresh, and agree with our records. DEP-1004 shows a correctly signed answer being rejected because the records disagree.

**What stops the agent from sending money?**
The agent only proposes. Small refunds backed by a verified answer go out under a limit the company sets, and the pause switch stops them. Anything over the limit needs two people, and when the agent proposed it, the approver can't also send it: the page shows no Send button to them, and the server refuses the request (403, covered by an automated test). Claude never states an amount and has no tool that moves money.

**What can a stolen payer key do?**
At most return part of that payer's own money to that payer's own registered account. A claim signed with a stolen key still has to pass the other two checks: it must be about this exact payment (its id, amount and currency) and still fresh, and our records must agree. If it does, the most it can set off without a person is a refund, and only when all of these hold: the amount is within the company's auto-limit and backed by that verified answer; it is no more than the part of the payment not yet placed; it goes to the refund account registered on the customer, never to an address in the claim; and only one live refund per payment can exist. Anything over the limit waits for two people, and the pause switch stops it. Changing a customer's refund account needs a signed-in Operator, is recorded in the audit log, and voids any approval bound to the old account; connecting or changing a payer agent's key needs an Owner. An insider Operator who changes a customer's refund account still cannot send money alone: an automatic refund also needs the payer's verified answer, and a return they propose needs a second person, who sees the destination in the scope they approve. (`payouts.py`: `create_refund_approval`, `current_scope`.)

**What if a remittance email contains instructions for the AI?**
It is treated as data. Tests feed emails that say "ignore previous instructions", "refund 9,999 to this account", "approve this", or contain a fake tool call, through the offline reader and through a model that does what the email says. In every case the result is stored as advisory evidence only, off-schema output becomes an escalation, and no plan, approval or operation changes; no amount or account from the email appears anywhere. The tools themselves have no amount or account field.

**Does the AI explain its decisions?**
The rules in code decide. On request, each payment gets a short "why this plan", written from structured facts only: ids, amounts, categories and check results. No free text goes in, not the email, not the payer name the bank reports, not a payer agent's own words, so an instruction hidden in any of them cannot reach it; tests try both a payer name and an agent's answer. It must cite ids that exist and use only numbers from the facts, or it is dropped and shown as unavailable. It is labelled as advice and nothing that decides reads it; tests show the plan is identical with or without it. Practice companies use a fixed template, so judges' clicks cost nothing.

**What if someone edits the database?**
Each audit event's hash covers the event and the previous hash, so editing, removing or reordering one breaks every later link; checking the log names the first bad event. Try it: in a practice company, **Activity → Try to tamper** changes one amount directly in the table and the check stops at that row. Rewriting the whole chain is possible for someone with full database access; it is caught by comparing the head hash with a copy kept elsewhere, such as a downloaded evidence export or an off-server backup.

**Can I check a decision was made the way you say?**
Yes: **Replay this decision** on any plan in a payment's history. Each plan keeps the exact inputs the rules read (the payment, the payer's customer record, the invoices it names, the policy limits; for an agent's answer, the signed envelope, the registered key and the time), and the audit log keeps their hash. A replay checks the hash, runs the same rules again and shows *Same plan* or each difference. Every accuracy run replays every decision of every synthetic company; the last one replayed all 8,826 rules decisions to the same plan. A person's own decision is shown as such; there are no rules to re-run.

**Is the two-person rule real if you used two of your own accounts?**
The rule checks accounts, not people, and we say so. The live sandbox runs show the control and the bank call. They aren't independent review.

**What ran on real Airwallex?**
Webhooks, a refund SENT → PAID as one transfer, a conversion, a EUR 100 bill payment, a paid early-payment link, beneficiaries and live rates; the agent-proposed refund path has only run on the simulated bank. Details: [what is real](../README.md#what-is-real-and-what-is-simulated) and [INTEGRATION_EVIDENCE](INTEGRATION_EVIDENCE.md).

**What happens if the bank times out mid-transfer?**
The refund keeps one request ID for its whole life. After a timeout or an unclear answer, Ledgerline looks that ID up with the bank before anything is sent again, and a lock allows only one live refund per payment. Tests cover timeouts and concurrent sends, and each ends with exactly one transfer. SENT keeps the liability on the books; only PAID releases it.

**How do you know the matching is right?**
An accuracy run on synthetic data (200 made-up companies and 25 practice walkthroughs, rules only) makes 61,063 checks across 8,826 payments and 4,087 invoices, with 0 mismatches against a separate reference model, and replays every decision; a separate evaluation of 50 companies, with payer agents answering, compares every allocation with an independent reference model. See [ACCURACY_REPORT](ACCURACY_REPORT.md) and [EVALUATION](EVALUATION.md). The test counts, CI status and where each number comes from are kept in one place: the README's [Measured, not claimed](../README.md#-measured-not-claimed) table.

**How does it compare with Airwallex's own reference builds?**
Compared with the design rules in Airwallex's public AWS reference builds ([awx-devx/airwallex-agentic-banking-aws](https://github.com/awx-devx/airwallex-agentic-banking-aws)). This is our own comparison; Airwallex has not reviewed Ledgerline.

| Rule in the reference builds | Ledgerline |
|:--|:--|
| The model only reads and proposes; no tool input names an account, tenant or request id | Yes. Claude reads documents through typed tools and cannot state an amount; payer agents only answer questions |
| Code computes every amount and re-checks the policy before anything runs | Yes. Rules in code set amounts; the approved scope is re-checked under a lock before sending |
| An approval is bound to the exact proposal, comes from someone other than the proposer, and arrives before it expires | Yes. Bound to a scope hash, proposer ≠ approver, and an approval expires after 72 hours by default (an owner can set 1 to 720 hours in Settings → Policy). In addition, the approver of an agent-proposed refund cannot also send it |
| A few low-risk actions run without approval, within policy limits | Yes. Refunds under the limit with a verified answer; the pause switch stops them |
| Every write is idempotent; after an unknown outcome, read back before sending again | Yes. One request id per refund or bill payment, looked up before any retry, one live refund per payment |
| Tenants are resolved on the server, never from model output | Yes. Every request is bound to the signed-in member's organization; each organization has its own database file |
| Only one separately privileged component holds the Airwallex key and can write | **Partly.** With the sending service on ([SERVER_STEPS](SERVER_STEPS.md) step 7, owner-run), the Airwallex keys live only in a separate process; the app cannot read them. The app asks it for a refund, bill payment or conversion by id only, and the service re-runs the approval, expiry, pause, two-person and duplicate checks against the database before it calls Airwallex. But a compromised app could still request a send that its own database says was approved, or add a payout beneficiary (paying it still needs an approved send). Until the owner runs step 7, the live server keeps the keys in the app process |
