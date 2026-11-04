# Changelog

What changed for the people using Ledgerline, newest first. The version and commit the server runs are shown at the
foot of every page.

## 4 November 2026 — 1.0.0

- Privacy, Terms and Security pages, linked from every page, and a `security.txt` for reporting problems.
- Account basics: change your name, a one-hour reset link an Owner can hand to a member who forgot their password,
  leave an organization, delete an organization (type its name), delete your account (type your email).
- Export a company's records as CSV files in one zip, ready for a spreadsheet.
- Replay this decision: any plan the rules made can be run again on its stored inputs to show it gives the same plan.
- Practice companies: a guided "Show me" tour, and "Try to tamper", which edits one audit entry and shows the log
  catching it.
- The payer-agent protocol is written down, with a JSON schema and a signed test vector.
- Measured on 200 synthetic companies: what the rules decide with no person, and what waits for one.
- An optional separate sending service that holds the Airwallex keys, off until the operator turns it on.
- Every page checked at phone width; error messages read as plain sentences.

## 3 November 2026

- A customer can run its own payer agent with its own key; Ledgerline asks it over the network with the same three
  checks.
- An approval not sent within 72 hours goes back to the approvers.
- "Why this plan": a short explanation of each payment's plan, written only from checked facts. Advice only.
- A practice teammate lets one person finish the practice walkthrough. Real companies need a second real member.
- Limits on new accounts per network address; dependencies pinned by hash; server updates that roll back by themselves.
- Encrypted off-server backups, email alerts and a timed recovery drill, run by the operator.
- Tests that instructions hidden in a remittance email change nothing.

## 2 November 2026

- Pay bills through the bank, with a second approver and PAID as the only final state.
- When the agent proposes a refund, the person who approves it cannot also send it.
- The agent asks the payer's agent by itself as soon as an unclear payment arrives.
- A CEO view; bills ranked by the cash they release; bring cash in early with a capped discount link.
- Wrong-currency payments: convert only what the invoice needs, or hold.
- Connect your own Airwallex sandbox account; import customers, invoices and payments from CSV.
- A hash-chained audit log that can be verified, and bill plans that can be replayed from their stored inputs.
- Plainer wording, a next step on every payment, and helpful empty screens.

## 30 October 2026

- First release on the always-on server, with an acceptance pass: the decision path on each payment, a measured
  evaluation, and Claude usage and cost recorded.

## 29 October 2026

- Remittance PDFs, current exchange rates, beneficiaries and deposit discovery on the Airwallex sandbox, and the
  architecture page.

## 27 October 2026

- Ledgerline began: organizations and roles, payment matching by reference and payer, signed payer-agent answers with
  three checks, approvals bound to the exact amount and destination, and a double-entry ledger.
