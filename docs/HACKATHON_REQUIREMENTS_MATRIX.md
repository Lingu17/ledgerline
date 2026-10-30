# Hackathon requirements matrix

Updated 30 Oct 2026. Status: **PASS** (verified, evidence named) · **BLOCKED** (needs something outside the code, smallest action named) · **NOT TESTED** · **N/A**. Detailed per-feature evidence: [FULL_APPLICATION_ACCEPTANCE_REPORT](FULL_APPLICATION_ACCEPTANCE_REPORT.md).

## A. Explicit competition requirements

Sources read on 29 Oct (read-only): the HackerEarth event page and team dashboard, and the builder guide it links (airwallexdev.com/guide). The event page's Tracks, Key Dates, Prizes and judging sections render empty; no scoring weights are published, and the Build Phase submission fields appear only after "New Submission" (not opened, to avoid creating a draft). Nothing below is invented beyond those sources.

| # | Requirement (source) | Status | Evidence / gap |
|---|---|---|---|
| A1 | Build Phase submission by 13 Nov 2026, 23:59 IST; team of 1–4 (event page) | BLOCKED (owner) | Shortlisted from the idea phase. The owner submits; Claude never saves or submits |
| A2 | Sandbox only, no real money (guide) | PASS | Airwallex adapter has a fixed sandbox base URL (`test_sandbox_host_is_fixed`); judge organizations use the simulated bank |
| A3 | Synthetic data (guide) | PASS | Sample company, customers and payers are fictional |
| A4 | Amounts, limits, reserves, validation, duplicate protection and state transitions in code, not prompts (guide) | PASS | `matching.py`, `payouts.py`, `treasury.py`; Claude only proposes typed tools, validated by `typed_proposal` |
| A5 | Demo shows goal, initial plan, new information, revised decision and resulting balance/status; ends with a financial action or escalation (guide) | PASS | Decision path per payment; DEMO_SCRIPT; EVALUATION reference cases |
| A6 | State which actions need human approval (guide) | PASS | Approvals page; four-eyes above the refund auto-limit; operator-initiated returns always need approval |
| A7 | Amounts in major units at the API; reuse `request_id` only for the same operation (guide) | PASS | `test_token_cached_and_amounts_sent_as_exact_major_units`, `test_timeout_before_accept_retries_once_with_same_request_id` |
| A8 | Re-read balances after a pending simulation; respect rate limits (guide) | PASS | Pending simulations never become settled funds (`test_pending_simulations_never_invent_settled_funds…`); calls are user-paced, rates cached 60 s |
| A9 | Submission contents (video, description, links) | BLOCKED (owner) | Fields not visible without starting a submission. SUBMISSION_DRAFT and DEMO_SCRIPT are ready; the owner records the video and grants judges repository access |

Starter kits in the guide are examples ("take one as written, change it, or apply the criteria"), so they are not treated as mandatory. Ledgerline is the reconciliation and cash-placement job the guide names as Treasury & Ops without a kit.

## B. Commitments in our accepted proposal

| # | Commitment | Status | Evidence / gap |
|---|---|---|---|
| B1 | Listen for `deposit.settled` webhooks | PASS (live) | VM: signed delivery HTTP 200, one processed event (DEP-7CDAEF2A79), plus four provider redeliveries each booked once |
| B2 | Poll deposits if webhooks are unreliable | PASS (live) | *Find missed deposits* (`GET /deposits`, own accounts only, idempotent) run by the owner; known-receipt sync for Ledgerline-created simulations. Owner-triggered, not scheduled |
| B3 | Clean match, fee write-off, partial with exact balance, duplicate (refund or credit), no reference, wrong currency | PASS | `test_matching.py`, fee boundary test, 50-seed evaluation with 0 disagreements |
| B4 | Payment link for the exact balance; draft if unavailable | PASS (fallback) / BLOCKED (hosted link) | Draft verified; the sandbox refuses link creation (HTTP 400 `configuration_error`, "contact your account manager"). Smallest action: Airwallex enables payment links on the sandbox account |
| B5 | Payer agent over MCP, signed `explain_payment`, three checks | PASS | Real stdio MCP; signature, binding/freshness, records; wrong signer, tampering, expiry, replay, wrong deposit/amount/currency rejected |
| B6 | Claude reads emails and PDFs when there is no agent | PASS (live) | Browser text and PDF reads on the VM with `claude-opus-5-5`; advisory evidence; prompt injection ignored and flagged |
| B7 | Apparent duplicate becomes credit after evidence | PASS | DEP-1005 → verified advance credit, refund dropped before money moved |
| B8 | FX: quote and convert only the shortfall above reserve | PASS | Tests; live conversion settled on the historical host (28 Oct), quote reuse refused |
| B9 | Refund approval bound to scope, duplicate lock, request id, SENT not final | PASS (tests, historical live) / BLOCKED (VM live) | Live SENT→PAID with a second real approver on the historical host; on the VM it waits for the owner's deposit and a second real member |
| B10 | One pause switch for all money-out | PASS | `test_pause_blocks_execution_and_pending_retries`, `test_pause_blocks_conversion` |
| B11 | Ledger balances to the cent; scorecard | PASS | Per-currency conservation; scorecard 6 / 4 / 1 / 1 / 0 |
| B12 | Beneficiary schema and creation | PASS (live) | Schema, validate, create on the VM (beneficiary 4f5abe34-…) |
| B13 | `GET /fx/rates/current` | PASS (live) | Treasury rates on the VM, orientation fixed |
| B14 | About 4-minute demo video | BLOCKED (owner) | Script ready |

## C. Our own product and engineering improvements (not competition rules)

Multi-tenant SaaS with roles and four-eyes; Google sign-in (Apple intentionally absent); per-payment decision path; interactive 3D architecture page; Google Cloud single-host deployment with backups and restore test; randomized evaluation harness; 5-job CI. Status of each is in the acceptance report.
