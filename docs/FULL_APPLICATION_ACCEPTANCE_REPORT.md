# Full application acceptance report

Ledgerline's promise: **resolve unclear incoming payments using verified evidence, with every decision explained and every cent accounted for.**

| | |
|---|---|
| Live | https://35-207-220-110.sslip.io (Google Cloud VM `ledgerline`, asia-south1-a, e2-small) |
| Branch | `deploy/vercel-render` (not merged to `main`) |
| Release commit, CI, smoke and persistence | see [Release record](#release-record) at the end |
| Report date | 30 Oct 2026 |

Status key: **PASS** verified with the evidence named · **FAIL** · **BLOCKED** needs something outside the code (smallest action named) · **NOT TESTED** · **N/A**. No finite test set proves the absence of defects; this report claims coverage of the agreed checklist, not zero defects.

Environments: **Unit/API** = pytest, in-process, temp data (`backend/tests`, 297 tests incl. one POSIX-only; plus 13 PostgreSQL tests in CI). **E2E** = Playwright on Microsoft Edge against a real local server (`frontend/e2e`, 13 tests). **Local UI** = Claude driving the built app on localhost. **Live** = the Google Cloud deployment, owner's organization or synthetic requests. **Hist.** = earlier Vercel/Render/Neon host, same sandbox account (kept separate).

## 1. Core story

| Item | Criterion | Method / environment | Evidence | Status |
|---|---|---|---|---|
| Apparent duplicate → advance credit | Refund proposed, signed agent claim passes 3 checks, plan revised to credit, no money moves | Unit, E2E path, Local UI, evaluation | `test_valid_advance_claim_passes_all_three`, DEP-1005 decision path "3/3 passed … refund dropped", EVALUATION | PASS |
| Signed but false claim rejected | Signature valid, records disagree, escalated with reason, no money | Unit, Local UI, evaluation | `test_foreign_invoice_claim_fails_records_check`, DEP-1004 "Failed: Our records agree" | PASS |
| Genuine refund under independent approval | Second person approves exact scope; one transfer; SENT keeps liability; PAID releases | Unit; Hist. live; VM live | `test_payouts.py`; VM APR-FC97829A / OP-46BAA6D1; independent member approved; SENT 04:20:43 → PAID 04:20:56 UTC on 30 Oct; provider GET and request-id lookup confirm one PAID EUR 1.23 transfer | PASS |
| Every decision explained | Each payment shows received → plan → evidence → checks → decision → approval → settlement → accounting | E2E, Local UI | `payment detail shows the decision path…`; DEP-1001/1004/1005/1006 checked | PASS |
| Every cent accounted for | Applied + credit + refund + unapplied = received, per deposit; per-currency conservation | Unit, evaluation | `test_partial_allocation_conserves…`, scorecard `ledger_balanced: true`, 2,127 random payments 0 disagreements | PASS |

## 2. Pages and journeys

| Page / journey | Success | Invalid / empty | Permission | Failure / recovery | Evidence | Status |
|---|---|---|---|---|---|---|
| Landing, navigation, architecture page | ✓ | — | public | — | E2E `home page explains…`; Local UI; 375px no overflow; 3D canvas with reduced-motion and mobile fallback | PASS |
| Sign-up (email/password) | ✓ | missing field named, weak password, duplicate account (generic) | — | — | E2E `sign-up says which field is missing`; `test_password_policy`, `test_duplicate_signup_and_generic_login_error` | PASS |
| Sign-in, wrong password, throttling | ✓ | generic error | — | 429 + Retry-After | E2E; `test_login_throttling` | PASS |
| Google sign-in | ✓ live (identity created on the VM 29 Oct 14:46) | state/nonce/PKCE, expired attempt, cancel | password account never auto-linked | — | `test_oauth.py` (15); live callback URI saved and verified | PASS |
| Apple absent | — | — | — | — | E2E `…Apple is absent from the login form`; live `/auth/providers` apple not configured | PASS |
| Logout, reload, expiry | ✓ | — | old session refused after logout | idle 2 h / absolute 12 h | E2E sign out/in; `test_session_idle_and_absolute_expiry`; smoke "logged-out session cannot be replayed" | PASS |
| Empty and sample organization | ✓ | — | — | — | E2E empty workspace manual payment; sample signup | PASS |
| Organization switching | ✓ | — | cannot switch into a foreign org | — | `test_user_in_two_orgs_switches_context`; smoke "another organization cannot switch in" | PASS (API) |
| Team: invite, accept, expiry, reuse, roles, removal | ✓ | single use, expiry | owner only; last owner protected | removal effective immediately | E2E invited viewer; `test_invitation_single_use_and_expiry`, `test_role_changes_and_removal_take_effect_immediately`, `test_invitation_token_not_in_application_request_log` | PASS |
| Inbox | ✓ | empty org | viewer read-only | Retry on load failure | Local UI all pages, no console errors | PASS |
| Payments: list, search, filter, paging, detail | ✓ | 422 reasons | viewer read-only | Retry | `test_validation_errors_are_422_with_reasons`; E2E manual payment; Local UI | PASS |
| Record payment / import CSV | ✓ | bad header, bad rows, too large, too many rows; re-import idempotent | operator+ | per-row errors reported | `test_csv_import_is_idempotent_per_row`, accuracy harness malformed rows | PASS |
| Resolve escalation, propose return | ✓ | other customer's invoice refused; unidentified payer: return disabled ("Identify the payer first") | operator+ | concurrent operators: one wins | `test_operator_cannot_allocate…`, `test_two_operators_resolving…`; live button state | PASS |
| Read remittance (text, PDF) | ✓ live | <10 chars, >5,000 chars, non-PDF, >3 MB, both text+PDF, bad base64 | operator+ | provider failure 502, budget counted | Live EV-…-3/4; `test_bad_pdf_uploads_are_refused`, `test_pdf_over_the_size_limit…`, `test_failed_claude_calls_consume_the_budget` | PASS |
| Customers & invoices, adjustments, void | ✓ | void invoices never paid; amounts change only by adjustment | operator+ | — | `test_voided_invoice_can_never_be_paid`, `test_workspace.py` | PASS |
| Approvals | ✓ | stale scope refused | proposer cannot approve (button disabled + API 409) | scope change invalidates | `test_approval_requires_the_exact_scope_seen`, `test_proposer_cannot_approve_own_refund`, `test_customer_edit_invalidates_bound_approval` | PASS |
| Evidence | ✓ | — | viewer read-only | — | Local UI | PASS |
| Treasury: position, obligations, quotes, conversions, rates | ✓ | expired/used quote refused; reserve breach refused | operator+; opening balance owner | rates error shows Retry | `test_treasury_ledger.py`; live rates | PASS |
| Ledger | ✓ | — | — | Retry verified (simulated network failure, then recovery) | Local UI | PASS |
| Activity and evidence export | ✓ | — | viewer may export | — | `test_viewer_is_read_only`; Local UI | PASS |
| Settings: pause, policy, bank mode, Airwallex, beneficiaries, discovery, password, sign-in methods | ✓ live | policy validation | owner-only governance; sandbox tools allow-listed | — | `test_pause_endpoint…`, `test_policy_and_pause_persist_across_restart`, `test_sandbox_tools_are_reserved…`, live beneficiary and discovery | PASS |
| Guided walkthrough | ✓ all 8 steps in the UI | reset confirmation | owner reset | — | Local UI; `test_guided_demo_over_api_with_stale_view_protection` | PASS |
| Judge guides | ✓ | — | — | — | JUDGE_QUICKSTART, DEMO_SCRIPT checked against a fresh sample org | PASS |

## 3. Financial correctness

| Rule | Evidence | Status |
|---|---|---|
| Exact, split reference | `test_split_reference_exact_match_allocates_both` | PASS |
| Partial (970 of 1,000 stays partial; exact balance requested) | `test_970_of_1000_is_partial_not_a_fee`, `test_short_beyond_tolerance_is_partial_with_exact_link` | PASS |
| Fee tolerance: at limit written off, 1 cent more is partial; relative cap | `test_fee_tolerance_boundary_is_inclusive…`, `test_small_fee_on_large_invoice…` | PASS |
| Overpayment → excess held as credit | `test_overpayment_allocates_remaining_and_holds_excess`, `test_overpayment_evidence_credits_only_the_excess` | PASS |
| Apparent vs genuine duplicate | DEP-1005 / DEP-1006; `test_paid_invoice_reference_is_apparent_duplicate_pending_evidence` | PASS |
| Unknown payer / reference; never amount-only | `test_no_reference_never_matches_on_amount_alone`, `test_unknown_payer_without_agent_escalates` | PASS |
| Wrong currency or customer; ambiguous payer names | `test_wrong_currency_held_without_fx`, `test_reference_to_other_customers_invoice_is_escalated`; payer names must be unambiguous across customers (`workspace._payer_names`) | PASS |
| Integer minor units; bad precision, negative, boolean, non-finite refused | `test_money_conversion_is_exact`, `test_to_minor_rejects_bad_input…`, `test_api_rejects_bad_amounts_without_500`, `test_wrong_field_types_are_422…` | PASS |
| No double allocation; concurrent operators | `test_invoice_cannot_be_overallocated_or_allocated_twice`, `test_two_operators_resolving…` | PASS |
| No edited history (adjustments, opening balance once) | `test_workspace.py`, accuracy harness | PASS |
| Credit and unapplied cash are not spendable | Inbox/Treasury show "Held for customers" separately from "Free to use"; `test_deficit_accounts_for_cash_reserve_held_funds…` | PASS |
| Conservation and balanced journal per currency | scorecard; evaluation 0 disagreements over 2,127 payments | PASS |

## 4. Money-out controls

| Control | Evidence | Status |
|---|---|---|
| Exact scope; change of amount, destination, evidence or deposit version invalidates | `test_mutation_after_approval_invalidates_it`, `test_new_evidence_invalidates_pending_approval`, `test_customer_edit_invalidates_bound_approval` | PASS |
| Self-approval refused | `test_proposer_cannot_approve_own_refund`; smoke check 23 | PASS |
| Role and membership changes take effect immediately | `test_role_changes_and_removal_take_effect_immediately` | PASS |
| Pause blocks money-out, matching continues | `test_pause_blocks_execution_and_pending_retries`, `test_paused_operator_resolution_still_works…` | PASS |
| Exactly one transfer, duplicate lock, stable request id | `test_concurrent_execution_sends_exactly_one_transfer`, `test_second_live_refund_for_same_deposit_blocked_by_lock`, `test_timeout_before_accept_retries_once_with_same_request_id` | PASS |
| Timeout → lookup before any resubmission | `test_timeout_after_accept_is_reconciled_not_resent`, `test_transfer_timeout_is_ambiguous_and_lookup_uses_request_id` | PASS |
| SENT keeps liability; only PAID releases; failure/cancel restore | `test_sent_is_not_final…`, `test_failed_after_send_returns_funds_to_unapplied`, `test_rejected_by_provider_releases_reservation`; Hist. live | PASS |
| Live refund on the VM | 30 Oct: DEP-A5F71B22E4 → APR-FC97829A → OP-46BAA6D1; different member approved and executed; one provider transfer `a6c5d55a-…`, one attempt. Journal reconstructed at SENT: payable 123 minor units; at PAID: 0. All five EUR accounting checks pass | PASS |

## 5. Claude and payer-agent evidence

| Item | Evidence | Status |
|---|---|---|
| Live browser text read: model, validated output, stored evidence | `claude-opus-5-5`, EV-DEP-7CDAEF2A79-3, `escalate` | PASS |
| Live PDF read | EV-…-4, `propose_refund`, hash only stored | PASS |
| Prompt injection | Live: embedded instruction ignored and flagged; no approval or operation created | PASS |
| No supporting invoice information / no invented match | Live EV-…-1 and -3 escalate; malformed ids rejected (`test_model_output_is_validated…`) | PASS |
| Contradictory evidence | Live EV-…-4 (asks for return) vs EV-…-3 (verification transfer): both advisory, a person decides | PASS |
| Malformed tool output, length limits | `test_model_output_is_validated_against_the_tool_schema`, `test_long_but_valid_reasons_pass…` | PASS |
| Missing credentials / offline | Labelled offline rules; PDFs refused offline (`test_pdf_needs_claude…`) | PASS |
| Insufficient credit / provider failure / timeout | Hist. live 400 insufficient credit → 502, nothing stored; `test_failed_claude_calls_consume_the_budget` (any exception, including timeout, takes the same path) | PASS |
| Daily budgets, concurrency | `test_claude_reads_are_capped…`, `test_simultaneous_claude_reads_cannot_exceed…`, `test_server_wide_claude_budget…` | PASS |
| Advisory only; API keys never sent to the model | Unsigned check always fails by design; prompt contains only the remittance text/PDF (`claude_reader._claude_read`) | PASS |
| Measured cost | Token usage recorded per call from release `98ca048`; earlier calls predate recording | PASS (from 98ca048) |
| MCP: correct signature, wrong signer, tampered, expired, replayed, wrong deposit / amount / currency / customer / invoice, signed but false | `test_evidence.py` (11), `test_validly_signed_claim_in_another_currency…`, `test_explain_payment_over_stdio_mcp` | PASS |

## 6. Airwallex and webhooks

| Item | Evidence | Status |
|---|---|---|
| Authentication, accounts, balances | Live readiness from the VM | PASS |
| Deposit simulation and settlement | Live DEP-7CDAEF2A79 | PASS |
| Beneficiary schema, validation, creation | Live 4f5abe34-… | PASS |
| Current FX rates and orientation | Live; defect D-03 fixed | PASS |
| Quote expiry, single use, conversion settlement, reserves | Tests; Hist. live OP-CBAA2582 | PASS (not repeated on the VM: no obligation in the operator org, and a repeat adds no new evidence) |
| Payment-link creation | Live HTTP 400 `configuration_error`; labelled draft | **BLOCKED** (Airwallex account configuration) |
| Signature on raw body; missing / malformed / wrong; timestamp tolerance; unknown org | Live synthetic 401/401/401/401/404; `test_bad_signature_stale_timestamp_and_malformed_rejected` | PASS |
| Duplicate event ids, same deposit under new id, concurrent deliveries | `test_duplicate_event_id_is_ignored`, `test_same_deposit_under_new_event_id…`, `test_concurrent_duplicate_deliveries_apply_once` | PASS |
| Out-of-order delivery | Only `deposit.settled` is ingested and it is idempotent per deposit; transfer states advance through guarded transitions (`test_simulation_cannot_skip_sent_or_repeat_final_state`) | PASS |
| Webhook vs polling race | `test_webhook_and_discovery_racing_for_one_deposit_book_it_once` | PASS |
| Real provider redelivery | Live: four 28–29 Oct events delivered to the VM, each booked once | PASS (observed; not a duplicate-rejection proof) |
| Discovery / known-receipt sync described accurately | INTEGRATION_EVIDENCE, README | PASS |

## 7. Tenancy and security

| Item | Evidence | Status |
|---|---|---|
| Every mutation enforces role server-side | `test_viewer_is_read_only`, `test_operator_works_but_cannot_govern`, E2E viewer refused by API | PASS |
| Another organization's ids | `test_organizations_cannot_see_or_touch_each_other`, E2E, smoke 24–25, harness isolation checks | PASS |
| Judge organizations never reach sandbox credentials | `test_judge_organization_cannot_use_the_shared_sandbox_account`, `test_withdrawn_sandbox_access_applies_to_cached_contexts` | PASS |
| Cookies Secure/HttpOnly/SameSite=Strict/Path=/api | smoke 5–6; `test_secure_cookie_when_configured` | PASS |
| CSRF and origin | Live cross-site 403; `test_mutations_need_csrf_token_and_allowed_origin` | PASS |
| Forged X-Forwarded-For | Live: forged header ignored, real address used | PASS |
| Upload limits | PDF 3 MB / request field limit; CSV 200 KB / 500 rows | PASS |
| Sensitive errors | Unhandled errors logged without bodies; provider errors shortened; webhook secret never returned | PASS |
| Secrets not in bundle, Git, logs, exports, screenshots | Bundle scan for key names and old hosts: none; env file 640 root:ledgerline; screenshots synthetic | PASS |
| Payer key file permissions | Defect D-06 fixed (0600) | PASS |
| Security headers, HTTPS | Live HSTS, CSP, XFO, nosniff, Referrer, Permissions; HTTP→HTTPS 308 | PASS |

## 8. Operations and recovery

| Item | Evidence | Status |
|---|---|---|
| Google Cloud only, same origin | Browser resources and API from one origin; no `DATABASE_URL`; ports 22/80/443 only | PASS |
| Service hardening and startup | systemd: user `ledgerline`, ProtectSystem=strict, ReadWritePaths=data dir, NoNewPrivileges, PrivateTmp, Restart=always, enabled at boot | PASS |
| Disk and logs | 29% of 19 GB used; data 2.8 MB; journald 98 MB under default cap | PASS |
| Scheduled backup | Timer ran automatically 30 Oct 03:15 UTC; 7 kept | PASS |
| Isolated restore | 29 Oct: integrity ok on 7 databases, row counts equal, key file restored, second instance served | PASS |
| Restart / reboot / redeploy persistence | Release record | see below |
| Response time | Live 160–220 ms per request from India (network-bound); payment detail 21.6 ms median server-side (evaluation) | PASS |
| Errors | No 5xx or ERROR lines in the service log over the previous 24 h (30 Oct) | PASS |
| Old stack retired | 30 Oct, owner approved: Vercel project, Render service and Neon project deleted; old URLs 404; Vercel entries removed from Google OAuth; only Airwallex webhook points at the VM; live health checked before and after | PASS |

## 9. Experience

| Item | Evidence | Status |
|---|---|---|
| Desktop and 375px | E2E phone-width test; Local UI 12 pages, no page-level overflow | PASS |
| Keyboard, focus, dialogs | E2E dialogs keep focus; skip-to-content control; arrow keys rotate the 3D view | PASS |
| Contrast | All 11 app pages ≥ WCAG AA after D-07 | PASS |
| Simulated vs sandbox vs real labelled | Top-bar badge, source labels, "advisory only", "draft, not sent" | PASS |
| No dead controls / false success | Disabled controls carry a reason (e.g. "Identify the payer first"); payment link never shows an invented URL | PASS |

## Defect register

| ID | Severity | Found by | Root cause | Fix | Verification |
|---|---|---|---|---|---|
| D-01 | Medium | Proposal review | Webhook fallback, beneficiary creation, current rates and PDF reading promised but missing | Implemented (bf3b65a) | `test_proposal_gaps.py`; live |
| D-02 | Medium | Code review | Sandbox Treasury labelled "Airwallex sandbox quotes" while showing synthetic constants | `/treasury/rates` with real source labels | `test_local_workspace_rates_are_labelled_synthetic`; live |
| D-03 | High (displayed rates wrong) | Live probe | Airwallex rates are quoted for the market pair; GBP→EUR showed 0.84 | Normalise by `currency_pair`; quote rate from booked amounts (10e07d0) | `test_airwallex_rate_parsing`, `test_quote_rate_is_buy_per_sell…`; live 1.1858 |
| D-04 | Low | Local QA | No skip-to-content control | Added (bf3b65a) | Local UI |
| D-05 | Medium | Live Claude run | 500-character limit rejected valid reasons and hid the model's proposal | 1,200 limit, short-reason instruction, rejected tool recorded (718660e) | `test_long_but_valid_reasons_pass…`; live EV-…-3 |
| D-06 | Low | VM inspection | Payer key file written 0644 (parent dir 0700 limited exposure) | 0600 on write, repaired on load (98ca048) | POSIX test on Linux CI; VM file mode in release record |
| D-07 | Low | Contrast scan | Muted text 4.41–4.48:1 | Darker muted colour (98ca048) | Contrast scan 0 below AA |
| D-08 | Low | Live Claude run | Model cost not measurable | Token usage recorded per call (98ca048) | `test_claude_token_usage_is_recorded…` |
| D-09 | Low | Local QA | Decision spread across sections | Decision path in payment detail (98ca048) | E2E |
| D-10 | Low | Live refund review | First-plan text said "Ask the payer's agent" when the payer had no agent and the action was escalation to a person (also for apparent duplicates) | Plan text follows the action (`matching.py`) | `test_plan_text_matches_its_action_when_the_payer_has_no_agent`; accuracy harness |

No FAIL items remain open.

## Remaining blockers and limitations

1. **VM refund lifecycle completed** (30 Oct): independent second-member approval, provider SENT → PAID, one transfer, liability released only at PAID, balanced journal. Evidence below and in INTEGRATION_EVIDENCE. The SENT state was also sampled live through the API at 04:20:43–04:20:56 UTC: deposit `refund_in_flight`, `refund_pending` 123, `refund_paid` 0, one attempt; after PAID: `refund_pending` 0, `refund_paid` 123, deposit `refunded`, EUR refund-liability check payable 0.00. The approver is a separate member account (Operator role); Ledgerline enforces proposer ≠ approver between accounts but cannot verify that two accounts belong to two different people.
2. **Hosted payment link** (BLOCKED): Airwallex sandbox returns `configuration_error`; needs Airwallex to enable the capability. The labelled draft is the fallback, not the original capability.
3. **Submission, video, judge repository access** (BLOCKED, owner).
4. Old stack retired on 30 Oct (done).
5. Limitations: single VM without redundancy; backups on the same disk; trial ends 28 Jan 2027; payer agents are simulations; scheduled polling is not implemented (owner-triggered discovery only); no email delivery; Airwallex credentials server-wide.
6. Not measured: real customers' payment mix, time saved, adoption or willingness to pay.

## Pilot readiness (CEO view)

| Question | What the evidence supports | What it does not |
|---|---|---|
| Clear user and recurring problem? | A small multi-currency finance team matching incoming payments weekly; the proposal's pain points (messy references, fees, short and duplicate payments, wrong currency) are each a tested rule | That any specific company has this volume; no customer interviews yet |
| Removes manual work? | In the reference company 4 of 6 payments close without a person; across 2,127 randomized payments 45.8% closed automatically, 8.1% were closed by an operator in one recorded decision, 46.1% wait with a stated reason (the random mix is deliberately exception-heavy) | Real-world automation share or hours saved |
| Exceptions manageable? | Every escalation carries a reason, the payer's identity when known and the evidence tried; operators resolve in one form; nothing is applied to another customer's invoice | Throughput at real volumes |
| Trustworthy decisions? | Decision path per payment, signed evidence with three checks, Claude output advisory only, four-eyes on money-out, 0 allocation disagreements against an independent model | External audit or certification |
| Beyond reference matching? | Verifying the payer's own agent's signed explanation, turning an apparent duplicate into credit before a refund goes out, and refusing a correctly signed but false claim | Availability of real payer agents (simulated today) |
| Sustainable to run? | One e2-small VM, SQLite per organization, nightly backups with a tested restore, Claude cost now recorded per call ($4 / $20 per million input/output tokens for `claude-opus-5-5`) | Multi-instance scaling, off-disk backups, support process |

A controlled pilot would need: a pilot customer's real statement export to measure their automation share, off-VM backups, email for invitations, and Airwallex enabling payment links.

## Release record

| Item | Result (30 Oct 2026, UTC) |
|---|---|
| Release commit | `6ef43c5` (code; later commits only update this record) |
| CI | [run 41002935918](https://github.com/Lingu17/ledgerline/actions/runs/41002935918): **Success**, all five jobs (backend Linux, backend Windows, frontend, e2e, PostgreSQL 17) |
| Local suites at release | backend 297 passed + 1 POSIX-only skipped on Windows (runs in CI); browser E2E 13 passed; frontend build ok; evaluation 50 seeds, 0 disagreements |
| Deployed SHA | `6ef43c5` via `update.sh` (git bundle) |
| Public smoke | **32/32** |
| Service restart | PID 4145 → 4256, then `--verify` **8/8** |
| VM reboot | boot id `6eacbf54…` → `01608371…` (back in ~54 s; service, Caddy and backup timer active), then `--verify` **8/8** |
| Redeploy | `update.sh 6ef43c5` again, then `--verify` **8/8** |
| Live refund after redeploy | DEP-A5F71B22E4 still `refunded`, OP-46BAA6D1 `paid`, ledger balanced |
| Key files | all `private_keys.json` mode 600 |
| Update 2 Nov | `c9615c1` deployed (wording only: backend unchanged from `6ef43c5`), [CI 41401760092](https://github.com/Lingu17/ledgerline/actions/runs/41401760092) green, browser E2E 13 passed. Verified live: health, new text served, refund still `refunded`/`paid`, 3-day uptime and nightly backups before deploy. Fresh clone of `main` set up, ran and tested on Windows. Claude live read $0.0067, 14.6 s. The 32-check smoke was not rerun for this wording change |
| Previous release | `3ce6c32`: CI 40999390871, smoke 32/32, restart / reboot / redeploy 8/8 each |
