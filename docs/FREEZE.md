# Freeze (from 12 Nov 2026 until results)

**Frozen commit:** code frozen at `51195a3`; later commits are video link + one mobile CSS fix + MIT license only. The live server
runs the latest commit on `main`; check with
`curl -s https://35-207-220-110.sslip.io/api/health` (its `commit` is the first 12 characters) or run the morning check
below, which compares the two.

## Allowed until 16 Nov 2026, 1:29 pm IST

- Only fixes to the judge path (landing page, judge demo, DEP-1005, DEP-1004, approve and send, SENT → PAID, CEO view,
  `/attacks`, `/evidence`) that the reviewer session approves, with CI green on all 5 jobs before deploying.
- Replacing `VIDEO_LINK` in `README.md` and `docs/SUBMISSION.md` with the video's address (docs only).
- Nothing else: no new features, no changes to money rules, no dependency upgrades, no server changes beyond a reviewed
  deploy through `deploy/vm/update.sh`.

After any allowed change: CI green, deploy, read the commit back, move `main`, run the morning check.

## Morning check (each day until results)

```bash
python scripts/presubmit_check.py
```

Every line must be PASS. WARN is fine only for `VIDEO_LINK` until the video is in, or for CI still running on a commit
pushed minutes earlier. Any FAIL: stop and fix it before anything else. The check is read only; it presses nothing.

Optional, uses one judge-demo company (deleted after 48 hours):

```bash
cd frontend && LIVE_URL=https://35-207-220-110.sslip.io npx playwright test -c playwright.live.config.ts
```
