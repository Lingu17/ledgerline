# User-authorized SaaS scope

Build Ledgerline as a complete SaaS application in this project folder, continuing the published proposal and existing BUILD_BRIEF, PRODUCT_POLISH and CODEX_REVIEW_FINDINGS. This is the user's explicit instruction, not optional advice.

- Sign-in, organization onboarding, owner/operator/viewer roles, logout and secure sessions.
- Backend authorization and organization isolation on every data query, mutation, export and background operation. Do not merely hide UI controls. Tests must prove cross-organization access is refused.
- Persistent customer/invoice/payment CRUD, search/filter/pagination, detail views, evidence, approvals, treasury, audit and settings. Normal workflows must work without the six-deposit walkthrough.
- Validated customer/invoice creation and edits, payment import, partial payments, credits, exception resolution and scoped refunds; avoid editable posted money history (use explicit audited adjustments instead).
- Secure password hashing, HttpOnly session cookies and appropriate SameSite/CSRF protections, session expiry/logout invalidation, login throttling, no default production credentials. Provide a documented local test setup without publishing secrets.
- Database migrations, repeatable setup, environment configuration, useful logs and explicit errors. Preserve exact-money accounting, signatures, locks, idempotency, approval binding, pause, FX reserves/finality and ambiguous-operation holds.
- Integration setup/readiness checks; secrets backend only. No false claim of live API verification. Local sample workspace/walkthrough optional and separate from ordinary operations.
- Polished financial operations UI: strong typography, consistent spacing, compact tables, useful detail panels, restrained navy/teal, responsive/accessibility. Working forms/buttons, meaningful loading/empty/error states, data surviving refresh/restart. No fake activity, decorative metrics or oversized demo instructions.
- Do not add subscription billing. No production banking or real money. No HackerEarth submission. Do not publish GitHub until Codex review.

Complete the implementation, test all roles and tenant boundaries, backend and frontend builds plus user workflows. Document startup/deployment, actual test results, integration requirements and limitations; write docs/CLAUDE_HANDOFF.md. Do not stop at a plan or claim production readiness without evidence. Codex will independently review and publish to authenticated Lingu17 GitHub after verification.

The user requests minimal ChatGPT token usage and progress checks only every 25 minutes. Continue autonomously; avoid asking for routine implementation choices. Report any real blocker explicitly.
