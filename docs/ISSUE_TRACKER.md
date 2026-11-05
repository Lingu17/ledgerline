# Issue tracker (November 2026)

Every issue found by the reviews and cloud checks, in one place, with its status. Each report is kept on its own
branch (`origin/<name>-report`) and is not merged into `main`. Status was checked against the code on
`deploy/vercel-render` at `da83451` (live: `b3ba221`) on 5 Nov 2026.

**Status:** FIXED (in code and tested) · OPEN (still to do) · OWNER (only the owner can do it) · DEFERRED (stated in the
docs, not built) · WONTFIX (decided, with the reason).

## Open now, in the order to fix

| # | Issue | Source | Fix (checked against the code) |
|:--|:--|:--|:--|
| 1 | PostgreSQL CI job fails: a fault in our in-process simulated agent was recorded as the payer's "rejected" answer (test_postgres line 328) | CI run 41959776624 | **FIXED** in `b9dba60` (CI to confirm on PostgreSQL). `SimulatedAgentFailed` then 503, nothing recorded; regression test |
| 2 | Plan v1 text "…references INV-2244, which every referenced invoice is already settled" (`matching.py:170`) | Judge review | **FIXED** in `c959804`: the plan card now runs the ask step through plainReason; `test_stored_rule_wording_is_kept_so_plans_made_before_a_display_fix_still_replay`. **Display-side only.** `replay.py:75-77` compares stored summary and actions, so changing the rule text would make Replay say "different plan" for every stored plan. Add a test that an old plan still replays the same |
| 3 | "Asking payer" shown on a practice payment nobody has asked yet (`format.ts:68`) | Judge review | **FIXED** in `c959804`: by organization, the fact that decides it. A real company asks on arrival and on retry, so a payment still waiting there is being asked ("Asking payer"); a practice company waits for the button ("Ready to ask payer"). Label from the data: "Ready to ask payer" until an ask exists, then "Asking payer" (true for real companies, which ask on arrival) |
| 4 | README L123 and L457 say a customer's own agent cannot connect / "would register" keys | Judge review | **FIXED** in `ea5fff5`. Correct both; the feature exists and is tested |
| 5 | SUBMISSION_DRAFT says "four" Claude tools | Judge review | **FIXED**: five, and none can state an amount or an account (SUBMISSION_DRAFT commit). Five (`claude_reader.py`: invoice match, customer credit, refund, conversion, escalate) |
| 6 | SUBMISSION_DRAFT says missed deposits are checked every two minutes | Judge review | **FIXED**: links every two minutes, missed deposits about every ten (SUBMISSION_DRAFT commit). Links every 2 min, deposits every 5th round, about 10 min (`watcher.py:24`) |
| 7 | Time saved: CEO view assumes 15 min a payment (`ceo.py:13`), docs assume 5 | Judge review | **FIXED** in `7f25ec1`: `MINUTES_PER_PAYMENT = 5`, pinned by test_ceo. Use 5 everywhere (the conservative figure, already in three places) |
| 8 | No answer to "what can a stolen payer key do?" | Judge review | **FIXED**: new JUDGE_QA entry, checked against `payouts.py`; the refund account needs an Operator to change (not an Owner, as first suggested), and that change voids bound approvals. From the code: only under the auto-limit with verified evidence, never more than the deposit's unapplied amount, only to the customer's registered refund destination, one live approval per deposit, stopped by pause (`payouts.py:74-130`) |
| 9 | Test counts differ between README and JUDGE_QA | Judge review | **PARTLY**: JUDGE_QA now points to the README's one table; the README row is updated once CI is green on the fix. One set of numbers from the latest run, with where each comes from |
| 10 | JUDGE_QA "about 30 judges" has no backing on `main` | Judge review | **FIXED**: the load report is in `docs/archive/LOAD_TEST_2026-11.md` with a note on what was fixed since, and JUDGE_QA quotes its 30 (separate process) and 100 judges (in-process) figures. Add the load report to `docs/archive`, update with the final-verify figures, or drop the number |
| 11 | Quickstart: scorecard is on the Inbox (not Practice steps), "3 fully closed" is not shown, "Explain this decision" and "Receive an unclear payment" are hidden | Judge review | Rewrite steps 2 and 7; add both as their own steps |
| 12 | SUBMISSION_DRAFT L12 (private, grant access) contradicts step 10 (keep public) | Judge review | **FIXED**: SUBMISSION_DRAFT says public from submission until results; OWNER_CHECKLIST step 10 matches. One rule: public at submission until results |
| 13 | The limits text appears three times, nearly verbatim | Judge review | **PARTLY**: one table in the README; SUBMISSION_DRAFT and JUDGE_QA link to it; owner steps in OWNER_CHECKLIST. The quickstart's own table goes next. One table on the README first screen; short summary and a link elsewhere; owner checklist in its own file |
| 14 | No line on why the LLM does not decide, or what the payer gains | Judge review | **FIXED**: README first screen and two JUDGE_QA entries. One sentence each, README first screen and JUDGE_QA |
| 15 | Screenshots date from 3 Nov; the UI changed on 5 Nov | Judge review | Regenerate and check each by eye |
| 16 | Safari: evidence download revokes the object URL immediately (`api.ts:97`) | Browser matrix #9 | Attach the anchor to the page and revoke after a short delay |
| 17 | Safari: dialog focus can escape (`ui.tsx`) | Browser matrix #10 | focusout-based trap |
| 18 | iOS before 16: the page behind a drawer scrolls | Browser matrix #11 | Lock body scroll with `position: fixed` while open |
| 19 | Date-time separator can differ by browser (`format.ts:34`) | Browser matrix #12 | Build the string with `formatToParts` |
| 20 | Hover colours stick after a tap on iOS | Browser matrix #13 | Wrap hover rules in `@media (hover: hover)` |
| 21 | `harden.sh status` prints a journalctl error without the Ops Agent; empty drop-in folder prints nothing | systemd check (cosmetic) | `2>/dev/null` on the Ops Agent lines; print "none" when the folder is empty |
| 22 | `/ceo`, `/overview` and `/ledger` are the heaviest reads under load | Load test #6 | Only if final-verify shows them slow at 50 judges |
| 23 | Firefox and WebKit never tested (cloud downloads blocked) | Browser matrix | Final-verify retries; otherwise one manual pass in Safari on an iPhone or Mac |

## Owner

| # | Item | Why it matters |
|:--|:--|:--|
| O1 | Record the video and put its link in the README top line | The judge review calls a missing video the biggest single risk |
| O2 | `docs/SERVER_STEPS.md` steps 0–7 (backups off the server, hardening, alerts, recovery drill, sending service) | Step 7 turns the one "Partly" in the Airwallex comparison into "Yes" |
| O3 | A security or support contact (`LEDGERLINE_SECURITY_CONTACT`) | Optional; security.txt says none is published until then |
| O4 | Repository visibility: public now for CI; owner asked to make it private again | Copies made while public cannot be taken back; the checklist says keep it public from submission until results |
| O5 | Judges behind one office address: sign-up limit is 10 an hour per address | Raise `LEDGERLINE_SIGNUP_PER_IP_HOUR` on the server for judging week if needed (load test #5) |
| O6 | Submit on HackerEarth by 13 Nov 23:59 IST | |

## Deferred or won't fix

| Item | Status | Reason |
|:--|:--|:--|
| Own invoice numbers from another system (audit P2-6) | DEFERRED | Touches matching, reader checks, Replay inputs and the harness; stated in README and SUBMISSION_DRAFT |
| CSP on the Vercel/edge path (security M2) | WONTFIX | That topology is not used live; DEPLOYMENT.md says what it needs |
| Reserve against the IP key too in the sign-in throttle | WONTFIX | Prevents a many-email spray from one address; a rare brief 429 is the lesser cost |

## Fixed (for the record)

| Area | Fixed |
|:--|:--|
| Two-person rule | Agent-proposed refunds: approver cannot also send (a80f07c); practice teammate (e02062f) |
| Linux check | Sender-off file ownership, `files` refusal, PG test fixture, empty dir, PostgreSQL refusal (f5a3b8e) |
| systemd check | P1 settings read from the environment, P2 ping, P3 start reaches the trap (ceb5058) |
| Product audit | All P1, P2 and P3 except P2-6 (9418445 to fce6deb) |
| Load test | Practice agents in-process (aab8d3e), scrypt outside the lock (6c4475c), keep-alive 75 s |
| Security scan | M1 one hop without an edge secret, L1 real 404s, I1 numeric hosts (c2edadc); throttle race caught in review and fixed (fcadcb9) |
| Browser matrix | #1–8: 16 px inputs, tour overlap, Treasury buttons, touch targets, inert menu, copy feedback, 100dvh (f13d6d7) |
| Recovery drill | Step 6 rewritten as one script; plain refusals; drill VM local only, no cloud identity (8d76391, 5359e17) |
| Judge review | First Recent activity row of a new practice company read "Payment link draft fallback": plain labels for every link outcome (`c959804`) |
| Reviewer finds | Why-card free text, backoff per organization, restore_check forged setting, update rollback, delete-company race, cache headers |
