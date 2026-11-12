# Submission

Text to paste into the submission form. The owner submits; nothing in this repository submits anything.

**Name:** Ledgerline

**Subtitle:** Agent-to-agent payment reconciliation

**Track:** Treasury & Ops · **Closest kit:** Adaptive Treasury Controller

## Pitch (under 50 words)

When a payment matches no invoice, Ledgerline's agent asks the payer's own agent what it was for. The answer is signed, and Ledgerline checks who signed it, that it is about this payment, and that its records agree, before deciding to apply, credit, convert or refund.

## Description (under 300 words)

Small companies that bill in several currencies spend hours matching incoming payments: missing references, bank fees, short payments, duplicates and wrong currencies. Guessing wrong is costly, for example refunding money that was really an advance.

Ledgerline receives Airwallex deposit webhooks and matches what is clear with rules in code. When a payment is unclear, its agent asks the payer's accounts-payable agent over MCP, as soon as the payment arrives. The answer is an Ed25519-signed claim, accepted only if three checks pass: the signature matches the customer's registered key; the claim is about this payment and still fresh; and the company's own records agree. A correctly signed but false claim is rejected and sent to a person with the reason.

Then Ledgerline acts: settle the invoice, write off a fee within tolerance, hold an advance as credit, convert only the FX shortfall, or propose a refund. Small verified refunds go out under the company's limit. Anything larger needs two people, and when the agent proposed it, the approver cannot also send it.

Money rules are in code: approvals bound to the exact amount and destination, one live refund per payment, stable request ids, a pause switch, and SENT is not final; only PAID releases the liability. Claude reads remittance emails and PDFs through typed tools that cannot state an amount or an account; its output is advice only. Every decision can be replayed to the same answer, and the audit log is hash-chained.

It is a working multi-company web app with roles, CSV import and export, a ledger that balances to the cent, a treasury plan and a CEO view. Twenty-five hostile attempts run in CI against the simulated bank; all are refused and none moves money.

## What is real and what is simulated

- **Real Airwallex sandbox (test money):** signed deposit webhooks, a refund SENT → PAID as one transfer, a currency conversion, a EUR 100 bill payment, a paid early-payment link, beneficiary validation and live rates. Dates and ids: https://35-207-220-110.sslip.io/evidence
- **Real mechanism:** MCP, Ed25519 signatures and the three checks. The reference payer agent answered the live site across the internet twice, with a key the server never held: on 3 Nov from the owner's own PC, and on 12 Nov from a separate cloud VM whose key was generated on that VM (recorded in `docs/evidence/outside-agent-run.json` and checked by `scripts/validate_outside_run.py`). Separate machine, separate key, operated by the Ledgerline author: not an independent party.
- **Simulated:** the built-in payer agents in practice companies (fixed answers, keys on the server); agent-proposed refunds, automatic refunds under the limit, failed and timed-out transfers, the pause switch and wrong-currency conversion are tested on the simulated bank only.
- **Limits:** no live money; no outside company runs a payer agent yet; the two-person rule checks accounts, not people (both live payments out used two of the owner's accounts).

## Business model

A monthly subscription per company, priced by payments reconciled, for finance teams of small companies that bill in several currencies; the payer-agent protocol stays open and free to implement. This is a proposal; the next step is a pilot with a small number of SMEs that receive cross-border payments on Airwallex.

## Links

- Live app: https://35-207-220-110.sslip.io
- Repository: https://github.com/Lingu17/ledgerline
- Video: VIDEO_LINK
- Sandbox evidence: https://35-207-220-110.sslip.io/evidence
- Attacks: https://35-207-220-110.sslip.io/attacks
- Judge Q&A: https://github.com/Lingu17/ledgerline/blob/main/docs/JUDGE_QA.md
- Judge quickstart: https://github.com/Lingu17/ledgerline/blob/main/docs/JUDGE_QUICKSTART.md
- Payer agent spec: https://github.com/Lingu17/ledgerline/blob/main/docs/PAYER_AGENT_SPEC.md

## Stack

Python 3.13+, FastAPI, SQLite per company (PostgreSQL supported), MCP, Ed25519, Claude (`claude-opus-5-5`, typed tools only), Airwallex sandbox API and webhooks, React 18 with TypeScript and Vite, pytest and Playwright in GitHub Actions, a Google Cloud VM with Caddy and systemd.

## How to judge it in 3 minutes

1. Open https://35-207-220-110.sslip.io and press **Judge demo — one click**: a practice company of your own (simulated bank, deleted after 48 hours), signed in as Judge A, with Teammate B one click away.
2. **Payments → DEP-1005 → Ask payer's agent:** the first plan holds a refund; the signed answer says it was an advance, the three checks pass, and the plan changes to credit.
3. **Payments → DEP-1004 → Ask payer's agent:** correctly signed but false; it is rejected and goes to a person with the reason.
4. **/attacks:** 25 hostile attempts, each refused, with what stopped it.
5. **/evidence:** each real sandbox run, with dates, ids and what it proves.
6. **CEO view:** the whole company on one screen, including what the agent did by itself.
