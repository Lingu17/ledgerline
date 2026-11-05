# Issue tracker (November 2026)

Every issue found by the reviews and cloud checks, in one place, with its status. Each report is kept on its own
branch (`origin/<name>-report`) and is not merged into `main`. Status was checked against the code on
`deploy/vercel-render` at `da83451` (live: `b3ba221`) on 5 Nov 2026, and updated with the final verification report the same day.

**Status:** FIXED (in code and tested) · OPEN (still to do) · OWNER (only the owner can do it) · DEFERRED (stated in the
docs, not built) · WONTFIX (decided, with the reason).

## Open now, in the order to fix

| # | Issue | Source | Fix (checked against the code) |
|:--|:--|:--|:--|
| 1 | PostgreSQL CI job fails: a fault in our in-process simulated agent was recorded as the payer's "rejected" answer (test_postgres line 328) | CI run 41959776624 | **FIXED** in `b9dba60` (CI to confirm on PostgreSQL). `SimulatedAgentFailed` then 503, nothing recorded; regression test |
| 2 | Plan v1 text "…references INV-2244, which every referenced invoice is already settled" (`matching.py:170`) | Judge review | **FIXED** in `c959804`: the plan card runs the ask step through plainReason; `test_stored_rule_wording_is_kept_so_plans_made_before_a_display_fix_still_replay`. **Display-side only.** `replay.py:75-77` compares stored summary and actions, so changing the rule text would make Replay say "different plan" for every stored plan. Add a test that an old plan still replays the same |
| 3 | "Asking payer" shown on a practice payment nobody has asked yet (`format.ts:68`) | Judge review | **FIXED** in `c959804`, by organization: a real company asks on arrival and on retry ("Asking payer"); a practice company waits for the button ("Ready to ask payer"). Label from the data: "Ready to ask payer" until an ask exists, then "Asking payer" (true for real companies, which ask on arrival) |
| 4 | README L123 and L457 say a customer's own agent cannot connect / "would register" keys | Judge review | **FIXED** in `ea5fff5`. Correct both; the feature exists and is tested |
| 5 | SUBMISSION_DRAFT says "four" Claude tools | Judge review | **FIXED** in `fdf271e`. Five (`claude_reader.py`: invoice match, customer credit, refund, conversion, escalate) |
| 6 | SUBMISSION_DRAFT says missed deposits are checked every two minutes | Judge review | **FIXED** in `fdf271e`. Links every 2 min, deposits every 5th round, about 10 min (`watcher.py:24`) |
| 7 | Time saved: CEO view assumes 15 min a payment (`ceo.py:13`), docs assume 5 | Judge review | **FIXED** in `7f25ec1`, pinned by test_ceo. Use 5 everywhere (the conservative figure, already in three places) |
| 8 | No answer to "what can a stolen payer key do?" | Judge review | **FIXED** in `265707e`. Correction: changing a refund account needs an Operator (`PATCH /customers` is `require_operator`), is audited and voids bound approvals; only a payer agent's key or address needs an Owner. From the code: only under the auto-limit with verified evidence, never more than the deposit's unapplied amount, only to the customer's registered refund destination, one live approval per deposit, stopped by pause (`payouts.py:74-130`) |
| 9 | Test counts differ between README and JUDGE_QA | Judge review | **PARTLY**: JUDGE_QA points to the README (`265707e`); the README row is updated once CI is green. One set of numbers from the latest run, with where each comes from |
| 10 | JUDGE_QA "about 30 judges" has no backing on `main` | Judge review | **FIXED** in `265707e`: report in `docs/archive`; JUDGE_QA quotes 30 (separate process) and 100 judges (in-process). Add the load report to `docs/archive`, update with the final-verify figures, or drop the number |
| 11 | Quickstart: scorecard is on the Inbox (not Practice steps), "3 fully closed" is not shown, "Explain this decision" and "Receive an unclear payment" are hidden | Judge review | **FIXED** in `f2705ed` (scorecard 6/4/1/1/0 checked by running the steps; the no-click payment then gives 7 and 5). Rewrite steps 2 and 7; add both as their own steps |
| 12 | SUBMISSION_DRAFT L12 (private, grant access) contradicts step 10 (keep public) | Judge review | **FIXED** in `fdf271e`. One rule: public at submission until results |
| 13 | The limits text appears three times, nearly verbatim | Judge review | **FIXED** in `ea5fff5`, `fdf271e`, `265707e`, `f2705ed`. One table on the README first screen; short summary and a link elsewhere; owner checklist in its own file |
| 14 | No line on why the LLM does not decide, or what the payer gains | Judge review | **FIXED** in `ea5fff5` and `265707e`. One sentence each, README first screen and JUDGE_QA |
| 15 | Screenshots date from 3 Nov; the UI changed on 5 Nov | Judge review | Regenerate and check each by eye |
| 16 | Safari: evidence download revokes the object URL immediately (`api.ts:97`) | Browser matrix #9 | **FIXED**: the link is added to the page, clicked, and removed with its object URL 30 s later. Attach the anchor to the page and revoke after a short delay |
| 17 | Safari: dialog focus can escape (`ui.tsx`) | Browser matrix #10 | **FIXED**: a `focusin` guard brings focus back into the top-most open drawer or dialog (a stack handles a dialog over a drawer). focusout-based trap |
| 18 | iOS before 16: the page behind a drawer scrolls | Browser matrix #11 | **FIXED**: the body is pinned with `position: fixed` at its scroll position while a drawer or dialog is open, and put back after the last one closes. Lock body scroll with `position: fixed` while open |
| 19 | Date-time separator can differ by browser (`format.ts:34`) | Browser matrix #12 | Build the string with `formatToParts` |
| 20 | Hover colours stick after a tap on iOS (measured again 5 Nov: still open) | Browser matrix #13, final verify | Wrap hover rules in `@media (hover: hover)` |
| 21 | `harden.sh status` prints a journalctl error without the Ops Agent; empty drop-in folder prints nothing | systemd check (cosmetic) | `2>/dev/null` on the Ops Agent lines; print "none" when the folder is empty |
| 22 | Settings and `/api/status` say `mcp/stdio` for a practice company, whose answers are `mcp/in-memory` (`routes.py:68` reports the server setting) | Final verify N1 | **FIXED**: one rule, `simulated_transport(ctx)` in client.py, used for asking and for /api/status; requirements matrix B5 says both; test in test_agent_server_fault. Report `mcp/in-memory` when the org is a practice company, the same rule as `client.py:96`; fix the requirements-matrix line |
| 23 | Firefox and WebKit never tested (cloud downloads blocked twice) | Browser matrix, final verify | One manual pass in Safari on an iPhone or Mac (owner), covering items 16 to 19 |
| 24 | `DEPLOYMENT.md:88` says the app sends its own CSP; it does not (the live `Caddyfile.single` does) | Final verify N3 | **FIXED**: DEPLOYMENT.md now says Caddy (`Caddyfile.single`) sends them and an edge must copy them; no second CSP in the app. Change the doc to say `Caddyfile.single` sends it. Lower risk than adding a second CSP in the app |
| 25 | Treasury Bills and Conversions tables scroll sideways at 390 px with no hint; the earlier fix covered only two tables | Final verify N5, browser #4 partly | **FIXED**: the same phone-only "Swipe the table sideways" hint as Wallet position, above Bills and Conversions (stacking would lose the column headers the numbers need). `stack-sm` on both, or the swipe hint Wallet position already has |
| 26 | Toast × Dismiss is 21 px tall on phones | Final verify N4 | **FIXED**: under `pointer: coarse` the toast's × is 44 × 44 px (negative margin keeps the toast compact). 44 px minimum under `pointer: coarse` |
| 27 | Phone tests create their own context and drop the device settings (`saas.spec.ts:150, 321, 359, 552`) | Final verify N6 | **FIXED**: `phoneContext()` in saas.spec.ts copies the project's touch, mobile, user-agent and pixel-ratio settings and keeps 375 px; the four phone tests use it. Spread `test.info().project.use` into `newContext` |
| 28 | Trailing-dot numeric hosts (`https://2130706433./`) pass registration; nothing is called (glibc does not resolve them, and the connect guard refuses) | Final verify N2 | **FIXED**: the host is lower-cased and loses a trailing dot before every check; three trailing-dot cases added to the refused-URL test. `host.rstrip(".")` before the numeric and localhost checks |

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
| Load test | Practice agents in-process (aab8d3e), scrypt outside the lock (6c4475c), keep-alive 75 s. Final verify, 5 Nov: 100 judges with 0 errors, 0 locked, 0 resets; slowest p95 0.51 s (was 34 s). The heaviest reads (`/ceo` 1.38 s p95) only show at about 75 requests a second, far above judges clicking, so they are left as they are |
| Security scan | M1 one hop without an edge secret, L1 real 404s, I1 numeric hosts (c2edadc); throttle race caught in review and fixed (fcadcb9). Final verify, 5 Nov: M1, L1, I1 and the login burst (exactly 5 of 20 or 50 reach the check) confirmed fixed; isolation held |
| Browser matrix | #1–3 and #5–8: 16 px inputs, tour overlap, toasts, touch targets, inert menu, copy feedback, 100dvh (f13d6d7), confirmed by final verify. #4 partly (see item 25) |
| Recovery drill | Step 6 rewritten as one script; plain refusals; drill VM local only, no cloud identity (8d76391, 5359e17) |
| Judge review | First Recent activity row of a new practice company read "Payment link draft fallback": plain labels for every link outcome (`c959804`) |
| Reviewer finds | Why-card free text, backoff per organization, restore_check forged setting, update rollback, delete-company race, cache headers |
