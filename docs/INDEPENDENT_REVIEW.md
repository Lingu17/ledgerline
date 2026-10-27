# Independent review — 27 October 2026

Claude implemented the SaaS application; Codex independently inspected the handoff and core authorization, tenancy, financial and session code, ran tests, exercised the browser, and made the corrections below.

## Observed verification

- Final backend, including later OIDC and randomized accuracy tests: `backend/.venv/Scripts/python -m pytest -q` — **174 passed in 178.12 seconds** on Windows/Python 3.14.
- Final browser suite: `npm run e2e` — **9 passed in 33 seconds** using system Edge, including signup/logout/login, viewer permissions, tenant isolation, operational forms, landing page, honest unavailable OAuth providers and phone-width layouts.
- Frontend: `npm run build` — strict TypeScript and Vite production build passed.
- `npm audit --audit-level=moderate` — **zero vulnerabilities**, including development dependencies.
- `scripts/smoke_live.py` against the running HTTP server — **18/18 checks passed**: sessions, viewer/operator/owner restrictions, four-eyes approval, CSRF/origin, organization isolation, real MCP evidence, accounting and logout replay prevention.
- Independent browser: created a new account/sample organization, navigated the operational inbox, opened a payment detail drawer, called the payer agent over MCP, observed the verified revised credit decision, created a customer through its form and returned to the inbox. The screenshot is from this actual running application.
- Earlier independent financial probes reproduced and verified corrections for scheduled FX finality, immediately failed refund accounting, unavailable FX proceeds, ambiguous provider lookups, exact money parsing and signed-claim validity. Concurrent calls created only one bank refund. Full SaaS tests retain these regressions.

## Corrections made during final review

- Updated Vite/plugin-react from vulnerable development tooling to exact versions 7.3.7/5.2.0 and regenerated the lockfile. Node prerequisites updated.
- Updated the subsequently added Playwright dependency to exact version 1.64.1; reran the complete browser suite and dependency audit successfully.
- Stopped raw invitation bearer tokens from entering application/access logs; added a regression.
- Existing-account invitation acceptance now shares the sign-in failure budget, preventing that alternate password-check endpoint from bypassing login throttling; added a regression.
- Fixed desktop grid/card overflow, made long definition labels wrap and allowed the navigation panel to scroll independently.

## Limits

Airwallex sandbox and Anthropic API calls remain unverified without credentials. Google/Apple sign-in was tested against mocked provider responses and unavailable-provider UI, not live accounts. Payer-agent endpoints and default bank are local simulations; UI labels disclose this. This is a functional hackathon SaaS build, not a production banking service. Email delivery, password reset, MFA and per-organization credential vault are not implemented. The final independent E2E pass also checks 375px layouts. CI results are available in GitHub Actions after publication.

No HackerEarth build submission was saved or submitted. No live money was moved. Runtime databases, local test accounts, generated signing keys, environment secrets and dependency directories are excluded from Git.
