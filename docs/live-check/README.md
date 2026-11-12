# Live judge-path check

Run on 12 Nov 2026 against https://35-207-220-110.sslip.io, live commit `2dc7082`, by
`frontend/e2e-live/judge-path.live.spec.ts` (headless Microsoft Edge):

```bash
cd frontend && LIVE_URL=https://35-207-220-110.sslip.io npx playwright test -c playwright.live.config.ts
```

It pressed **Judge demo — one click** once (one practice company on the simulated bank, deleted after 48 hours) and
walked: DEP-1005 refund → credit (verified), DEP-1004 rejected with its reason, the over-limit refund approved by Judge A
and sent by Teammate B, SENT → PAID on the simulated bank, the CEO view, `/attacks` and `/evidence`. Every screen was
then checked again at 375 px in the same company. The run failed on any console error, failed request, response of 400
or more, or sideways scroll; it passed with none.

Screenshots: `desktop-*.png` at 1280 px wide, `375-*.png` at 375 px.
