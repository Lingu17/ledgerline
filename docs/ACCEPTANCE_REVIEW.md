# Independent acceptance checks

Status: planned, not yet executed. Codex will replace this with observed results after Claude implementation.

## Critical financial checks
1. Replay the same reconciliation request and webhook; invoice allocations and deposit totals must remain unchanged after the first successful application.
2. Submit the same refund approval concurrently; exactly one durable provider operation and debit must exist.
3. Pause before approval execution; money-out must be blocked while exact-reference matching continues. Restart and verify pause persists.
4. Change evidence or recipient after approval; old approval must fail rather than authorize changed instructions.
5. Tamper a signed claim; use expired claim; cross-customer invoice; mismatched currency/amount/deposit. Every case must fail closed with a visible reason and no financial mutation.
6. A short payment of 970 against an invoice of 1000 must allocate 970 and leave 30 due. Fee writeoff is a separate accounting adjustment, not extra deposit money.
7. Two deposits cannot each pay the same outstanding invoice in full. Credit or escalation must preserve conservation.
8. A SENT refund must remain pending/reserved, not completed. Provider timeout must not release a lock for a new duplicate payment.
9. Balance equations must work per currency before/after all six demo cases, pending refunds, final refunds and FX.
10. FX quote must expire, be single-use, preserve source reserve, and convert only the target obligation shortfall.

## Product checks
- Fresh install and repeatable launch on Windows; frontend build and backend tests.
- Refresh and restart preserve reconciliation state.
- Full user journey from guided run to credit correction, malicious evidence escalation, exact approval and final ledger.
- Search and filters work; all navigation routes show relevant content; exports contain actual backend state.
- Evidence detail shows initial/revised decision and checks, not merely a status badge.
- Missing keys and network failures show honest integration state, no fake connected/API badges.
- Desktop and narrow browser layouts; keyboard focus, tables and drawer/dialog accessibility; contrast and understandable error states.
- No API keys, local database, private signing keys, .env, node_modules or virtualenv committed.
- README accurately separates tested demo functionality, implemented but unverified external adapters and missing setup.

## Delivery
GitHub repository content and default branch must match tested local commit. Record actual test commands/results and unresolved limitations. Keep HackerEarth submission untouched until separately requested.
