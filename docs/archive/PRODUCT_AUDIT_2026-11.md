# Product audit: does Ledgerline feel like a product a company would pay for? (4 Nov 2026)

**Build audited:** `deploy/vercel-render` at `1668374b310194d451c9964315e4cc1390f4b0dc` ("Review fixes: practice-only undo in restore_check; sender steps safe to fail", 4 Nov 2026).
**How it was run:** locally in a cloud container, following README "Run it yourself": `pip install --require-hashes -r backend/requirements-lock.txt` (Python 3.13), `npm ci && npm run build` (Node 22), `python -m ledgerline`. The server reported `bank=local claude=offline-fixture`. No Airwallex or Anthropic keys were set, and the live site was not touched.
**How it was driven:** Playwright in Chromium at 1440×900 and 375×812. About 100 screenshots are kept in the container only; none are committed.
**Scope:** this is an audit only. Nothing was fixed.

## What was exercised

**A. As a real small company ("Harbour Lane Studio Ltd", started with *My company*):**
- Signed up.
- Added a customer by form and two more by CSV, including one bad row.
- Added an invoice by form and four more by CSV.
- Imported seven statement lines by CSV: exact, partial, bank fee, duplicate, unknown payer, overpaid, and one bad date.
- Recorded one payment by hand.
- Invited an Operator and accepted the invite in a second browser context (phone size), then reused the link.
- Set the refund limit to 500 in each currency, then tried to set approval expiry.
- Looked at the Connect Airwallex card and stopped before entering keys.
- Read a remittance and resolved the unknown payer as credit.
- Proposed a return of the duplicate. The owner was blocked from approving it, the Operator approved it, the owner executed it, and it went to SENT and then PAID.
- Checked the Ledger, the CEO view, Verify log integrity and the evidence export, and paused and resumed money-out.
- Signed out, tried a wrong password, and signed back in.
- Checked every page at 375 px, keyboard Tab order, labels and contrast.

**B. As a judge (*Practice company*):**
- The Show me tour, all 7 stops, at both sizes.
- DEP-1005: Ask payer's agent, Why this plan, and Replay on both plans.
- DEP-1004: Ask payer's agent and Read remittance.
- Try to tamper, then Restore.
- Practice steps run to the end, including Send as practice teammate and SENT → PAID.
- The CEO scorecard.

**What already works well (keep it):**
- No server tracebacks, and every API call answered in under 80 ms.
- No page scrolls sideways at 375 px except Settings (P2-9).
- Every form input has a label.
- Text in the app shell passes WCAG AA contrast on every page checked.
- There is a skip link and a visible focus ring.
- The two-person rule held: Approve is disabled for the person who proposed it.
- The ledger stayed balanced throughout, and the tamper check caught the exact row.
- Wording about the sandbox and simulated agents is honest and consistent almost everywhere.

---

## P1: a real company or a judge would hit these

### P1-1. Saving the Policy form quietly resets approval expiry (and other settings the form does not show) to their defaults
- **Page:** Settings → Policy.
- **Steps:**
  1. Set `approval_ttl_hours` to 24 through `PUT /api/settings/policy`. The UI has no field for it (see P1-2). `GET /api/status` then returns 24.
  2. Open Settings and press **Save policy** without changing anything.
  3. `GET /api/status` now returns **72**.
- **What happened:** the form sends only the four money rows and `fee_tolerance_bps`. `validate_policy` starts from `DEFAULT_POLICY` instead of the stored policy, so every key the form leaves out goes back to its default. That includes `approval_ttl_hours`, `obligation_lookahead_days`, `early_pay_max_bps`, `evidence_max_ttl_seconds` and `webhook_tolerance_seconds`. The audit log records `policy.updated` but does not show which values changed.
- **Fix:** in `put_policy`, merge the body over the stored policy, for example `validate_policy({**ctx.policy(conn), **body})`. Also record the old → new values in the audit detail.
- **Where:** `backend/ledgerline/api/routes.py:847`, `backend/ledgerline/context.py:38` (`out = dict(DEFAULT_POLICY)`), `frontend/src/views/Settings.tsx:351-363`.

### P1-2. Approval expiry cannot be set anywhere in the app
- **Page:** Settings → Policy.
- **Steps:** look for a way to change how long an approval stays valid.
- **What happened:** there isn't one. The value is fixed at 72 h (allowed range 1-720), and the Approvals page shows "Expires in 71 h if not sent". JUDGE_QA states "an approval expires after 72 hours" and the product brief says "approvals that expire", but the owner cannot tune it. Combined with P1-1, even a value set through the API does not last.
- **Fix:** add an "Approval expires after (hours)" field to the Policy card. Consider adding the planning window (`obligation_lookahead_days`) as well, since the CEO view and Treasury say "next 14 days".
- **Where:** `frontend/src/views/Settings.tsx:337` (the `fields` list), `backend/ledgerline/context.py:31,50`.

### P1-3. A real company with no bank connected can "Execute refund" and then press **Simulate: sent / paid / failed**
- **Page:** Approvals → Money-out operations, in *My company* with "No bank connected".
- **Steps:** propose a return of the duplicate (DEP-…E8), have a second member approve it, then press **Execute refund**.
- **What happened:**
  - The refund was "sent" to the built-in simulated bank (`bank tr_5400df532038`).
  - The real company then sees **Simulate: sent**, **Simulate: paid** and **Simulate: failed** buttons.
  - Pressing them books "Refund cash sent GBP 1,250.00" in the Ledger and "refund.paid" by actor `provider` in Activity, even though no money moved anywhere.
  - For a real company this is a fake bank inside its books. It is the most demo-like thing in the "My company" path.
- **Fix:** when a non-practice company has no bank connected, replace **Execute refund** with **Record refund made outside Ledgerline**: ask for the date and the bank reference, and book it as manual, like "Manually recorded" payments. Hide every **Simulate** button outside practice companies.
- **Where:** `frontend/src/views/Approvals.tsx:18` (`canSimulate = localMode || …`), `:62-68`, `:100-109`; `frontend/src/views/Treasury.tsx:230-231` (the same "Test bank: sent/paid" buttons for bill payments).

### P1-4. A brand-new real company is "Short by USD 5,000" on day one, while the CEO view says "All clear"
- **Page:** Inbox, CEO view and Treasury, right after sign-up with *My company*.
- **Steps:** sign up and look at the Inbox.
- **What happened:**
  - The default reserves (USD 5,000, EUR 2,000, GBP 1,500) are applied before the company has entered anything.
  - Every wallet card shows **Short by USD 5,000.00 / EUR 2,000.00 / GBP 1,500.00**, styled as a warning.
  - The CEO view shows "Free to spend USD −5,000.00" right next to "Nothing needs you today. All clear".
  - Treasury shows −5,000 forecasts.
  - The company never chose these reserves, the amounts are in currencies it may not use, and nothing explains them.
- **Fix:**
  - Start real companies with zero reserves, or ask for reserves and opening balances in the setup checklist. "Set opening balance" exists but is not a checklist step.
  - Until an opening balance is set, show "Opening balance not set" instead of "Short by".
  - Make the CEO headline agree with the table.
- **Where:** `backend/ledgerline/context.py:23`, `frontend/src/views/Inbox.tsx:100-103`, `backend/ledgerline/ceo.py:51` (headline).

### P1-5. Daily screens show developer reasons: "no registered payer agent; route remittance text to evidence reader / operator"
- **Page:** Inbox → Needs a decision, the CEO view → What needs you, and the payment panel ("Why this needs review", and Decision → "With a person: …").
- **Steps:** import any payment with no reference, or an over/duplicate payment, for a customer with no payer agent.
- **What happened:** this string appears on every escalated row a real company sees. Most customers will have no agent, so this is the line they read most often.
- **Fix:** use plain wording such as "This customer has no payer agent. Read their remittance email or decide yourself." Keep the routing detail in the audit log only.
- **Where:** `backend/ledgerline/matching.py:92`. A related sentence is broken: "references INV-2244, which every referenced invoice is already settled." comes from `backend/ledgerline/matching.py:164,170`.

### P1-6. No password reset, and no way to change your name or email
- **Page:** Sign in; Settings → Your account.
- **Steps:** look for "Forgot password?" on Sign in, then look for a way to edit your name or email in Settings.
- **What happened:**
  - There is no reset link and no API route for one.
  - Settings → Your account shows Name and Email as read-only text. Only the password can be changed, and only if you remember it.
  - A locked-out owner has no way back in, which is a support ticket on day one for any paying company.
- **Fix:**
  - Add "Forgot password?". With no email delivery, at minimum have an owner of the same organization issue a one-time reset link, the same way invite links already work.
  - Make Name editable.
  - Make email changeable after re-entering the password.
- **Where:** `frontend/src/views/Auth.tsx:94-128`, `frontend/src/views/Settings.tsx:411`; there is no route in `backend/ledgerline/api/auth_routes.py`.

### P1-7. No Privacy, Terms, Security, Contact/Support, status or changelog anywhere, and no 404
- **Page:** the landing footer, sign-up, the app sidebar, and the routes `/privacy`, `/terms`, `/security` and `#/anything`.
- **Steps:** open each of those routes.
- **What happened:**
  - Every unknown path returns HTTP 200 with the landing page: `/privacy`, `/terms`, `/security`, `/does/not/exist`, even `/robots.txt` and `/favicon.ico`.
  - Inside the app, an unknown hash such as `#/nope` silently shows the Inbox, titled "Inbox".
  - The footer links only to How it works, FAQ, Architecture and Sign in.
  - Sign-up has no "By creating an account you agree to…" line.
  - There is no help or support link on any app page, and no version or changelog.
  - A company asked to trust this tool with receivables, and to paste bank keys into it, will look for all of these first.
- **Fix:**
  - Add short Privacy, Terms and Security pages. Security can summarise README "Security" and say "sandbox only, not independently audited".
  - Add a contact address.
  - Add a "Help" link in the sidebar footer, pointing to the docs or the quickstart.
  - Show the version or commit in Settings.
  - Add a real "Page not found" for unknown hashes and paths.
  - Serve real `robots.txt` and `favicon.ico`.
- **Where:** `frontend/src/views/Landing.tsx:297-306`, `frontend/src/App.tsx:241-253` (`Gate`) and `:155` (`TITLES[route.page] ? … : "inbox"`), `backend/ledgerline/api/app.py:174-180` (SPA catch-all).

### P1-8. The app calls the payer agent connection "not available yet", and so does the submission, but the Customers page offers it
- **Page:** Settings → Integrations → Payer agents.
- **Steps:** open Settings, then open Customers → Payer agent….
- **What happened:**
  - Settings says "a customer's own hosted agent cannot be connected yet."
  - Customers → **Payer agent…** lets an owner connect one by URL and key.
  - README, JUDGE_QA and the "Limits" section of SUBMISSION_DRAFT all say a customer *can* now run its own agent, and the 3 Nov tunnel run proved it.
  - SUBMISSION_DRAFT "Honest scope" still says "A customer's own hosted agent cannot be connected yet." A judge comparing the doc with the app will see a contradiction that undersells the strongest feature.
- **Fix:** in both places, replace it with the README wording: built-in agents are simulated; a customer can connect its own agent under Customers → Payer agent…; no outside company runs one yet.
- **Where:** `frontend/src/views/Settings.tsx:189`, `docs/SUBMISSION_DRAFT.md:49`.

### P1-9. A real company sees developer internals in Settings → Integrations
- **Page:** Settings.
- **Steps:** sign up with *My company* and open Settings.
- **What happened:**
  - **Evidence reader** reads "Deterministic fixture - Claude not invoked (no ANTHROPIC_API_KEY)". The Evidence page repeats it and shows a raw JSON proposal: `propose_invoice_match {"invoice_id":"INV-2304","paid_on_behalf_of":"another party",…}`.
  - **Payer agents** reads "mcp/stdio" and "Customer agents hosted on this server".
  - **Webhooks** reads "HMAC-SHA256 over x-timestamp + raw body, 300s skew limit… Signing secret: organization local secret."
  - The org card shows "Workspace · org_ce75803c4d1e".
  - Global account ids are labelled "Used for sandbox deposit simulation" while no bank is connected.
  - The page has two separate Airwallex forms: *Connect your Airwallex account* (with its own webhook secret), and below it "Airwallex webhook secret" and three global account ids under Integrations. It is unclear which one to fill in.
  - The OAuth note on sign-in, sign-up and invite says "Disabled options have not been set up by this server's administrator", which reads as self-hosted dev software.
- **Fix:**
  - Show plain status lines ("Remittance reading: built-in rules (AI reading not enabled on this server)", "Payer agents: simulated for practice; connect a customer's own under Customers").
  - Move the protocol details behind a "Technical details" disclosure.
  - Fold the second Airwallex form into the Connect card, or hide it until connected.
  - Hide a disabled Google button instead of explaining it.
- **Where:** `backend/ledgerline/claude_reader.py:213`, `backend/ledgerline/api/routes.py:67-68`, `frontend/src/views/Settings.tsx:93,189,195,209`, `frontend/src/components/OAuthButtons.tsx:97`.

### P1-10. Proposing a refund takes one click, with no confirmation, and the payment's status does not change
- **Page:** a payment panel → **Propose return to sender**.
- **Steps:** on the duplicate deposit, press the button once.
- **What happened:**
  - A GBP 1,250 approval request is created at once, with no amount check, no note and no "are you sure".
  - The payment still reads **Needs review**, and Decision still says "WAITING – With a person…", while the Approval step now says "APR-… pending".
  - The approval card is titled "Operator: return unidentified funds to sender", although the payer *was* identified (Orchard Tea Co, a suspected duplicate).
- **Fix:**
  - Open a confirmation showing the amount, the destination and a required note.
  - Move the status to "Refund for approval".
  - Title the card from the plan category, e.g. "Return suspected duplicate to Orchard Tea Co".
- **Where:** `frontend/src/views/Payments.tsx:428`, `backend/ledgerline/payouts.py:142`.

---

## P2: polish

| # | Page | Steps | What happened | Suggested fix | Where |
|:--|:--|:--|:--|:--|:--|
| P2-1 | Activity, Inbox → Recent activity, payment → Audit, Settings → Organization changes | Open any of them | Raw event codes and actors everywhere: `deposit.received`, `plan.initial`, `payment.recorded_manually`, `practice.tamper_tried`, `user.signup`; actors `rules`, `manual_import`, `provider`, `payer_agent:CUST-FJORD`, `system` | Map codes to sentences ("Payment received", "Matched by rules"); keep the code in a tooltip or in the export | `frontend/src/views/Activity.tsx`, `frontend/src/views/Inbox.tsx`, `frontend/src/views/Settings.tsx:40` |
| P2-2 | Ledger → Journal | Open the Ledger | Account names in snake_case: `cash_in_transit`, `unapplied_cash`, `refund_payable`, `accounts_receivable`, `cash:GBP` | Show account labels ("Cash – GBP", "Refunds payable") | `frontend/src/views/Ledger.tsx` |
| P2-3 | Activity → Download evidence JSON | Press it | The only export is one JSON file named `ledgerline-evidence-export.json` (52 KB), with no date or company name in the filename. No CSV of payments, invoices, the journal or the audit log for an accountant, and no "export everything / delete my company" | Add CSV exports (payments, invoices, journal, audit). Put the org and date in the filename. Add "Delete organization" (owner, typed confirmation) and "Leave organization" | `frontend/src/views/Activity.tsx:81`; no delete route in `backend/ledgerline/api/routes.py` |
| P2-4 | Inbox wallet cards | After imports | "Reconciled USD 4,180.00" while USD 100 is not yet placed and USD 800 came from an unidentified payer: "Reconciled" here means "balanced in the ledger", not "matched". A finance user will read it as matched | Rename to "Received (settled)" or "Cash in ledger", and keep "Reconciled" for the conservation pill only | `frontend/src/views/Inbox.tsx:90` (pill label) |
| P2-5 | Payment CSV import | Import a line dated `04/11/2026` | "received_at must be an ISO date or timestamp". Most bank exports use DD/MM/YYYY. Import is paste-only, with no file picker. CSV-imported lines are labelled "Manually recorded", the same as the form | Accept common date formats or say "use YYYY-MM-DD". Add a file picker. Label imported lines "Imported from CSV" | `backend/ledgerline/workspace.py:161`, `frontend/src/views/Payments.tsx:617-645`, `frontend/src/components/ui.tsx:256-280` |
| P2-6 | Invoices | New invoice / CSV import | You cannot enter your own invoice number: numbers are assigned (INV-2301, INV-2302…), and matching and the explainer only understand `INV-####` (`_INV = ^INV-\d{3,6}$`). A company with "HL-2026-014" invoices will never match by reference | Allow an external invoice number column and match on it | `frontend/src/views/Customers.tsx:347-360`, `backend/ledgerline/matching.py:23-28`, `backend/ledgerline/claude_reader.py:124` |
| P2-7 | Whole app | Sign up | Only USD, EUR and GBP. The Policy table, wallets, the CEO view and the invoice currency list are fixed to these three. An Airwallex customer billing in SGD, AUD or HKD cannot use it | Let the company choose its currencies, or at least say "USD, EUR and GBP only" on the landing page and at sign-up | `frontend/src/views/Settings.tsx:8`, `frontend/src/views/Customers.tsx:357`, `backend/ledgerline/context.py:17-25` |
| P2-8 | Payment panel → Decision path | DEP-1005 in practice, before asking | Shows "Decision DONE – First plan stands" while the status is "Asking payer" and Evidence is "WAITING". A partial payment shows "Evidence NOT NEEDED – None yet". A refund-proposed duplicate shows "Approval NOT NEEDED – No money leaves" | Show "Waiting for evidence" when the plan is waiting; drop "None yet" under NOT NEEDED; mention a held refund under Approval | `frontend/src/views/Payments.tsx:300-312` |
| P2-9 | Settings at 375 px | Open Settings on a phone | The page scrolls sideways (scrollWidth 399 px): the Policy table (548 px wide) pushes past its wrapper. Every other page fits | Make the Policy table scroll inside `.table-wrap`, or stack it by currency on small screens | `frontend/src/views/Settings.tsx:370-385` |
| P2-10 | Payment → Read remittance… | Read an email that names an invoice | Toast reads "Proposal: propose invoice match" (raw tool name). The proposal is stored as evidence but not offered as a one-click "Apply to INV-2304" in Resolve; the user has to redo it by hand | Use plain toast text, and pre-fill Resolve from the advisory proposal (still a person's click) | `frontend/src/views/Payments.tsx:517` |
| P2-11 | Why this plan | DEP-1005 → Explain this decision | "DEP-1005 is 1200.00 USD; under DEP-1005 plan v2 it is verified advance credit, so the plan is: cancel proposed refund, credit 1200.00 USD." It reads robotically, and the format "1200.00 USD" differs from "USD 1,200.00" everywhere else | Use the app's money formatter and a friendlier template | `backend/ledgerline/explain.py:122` |
| P2-12 | Activity → Try to tamper | Change one audit row | "amount changed from 175000 to 275000 (in cents)" | Show "EUR 1,750.00 → EUR 2,750.00" | `frontend/src/views/Activity.tsx:42` |
| P2-13 | Show me tour, stop 1 | Practice company → Show me | "Six payments are about to arrive", but the six are already in the Inbox when the company is created (Reconciliation status: Deposits received 6) | "Six payments have just arrived" | `frontend/src/components/ShowMe.tsx:19` |
| P2-14 | Practice steps | Open Practice steps | Step 1 is "Reset demo data". The intro says "reference scenario… six synthetic deposits" and "Bank: No bank connected (simulated records, no real money)", while the top bar says "Practice company · made-up data". Two names for the same thing | "Start the practice company again"; use one phrase, "made-up data / practice bank" | `backend/ledgerline/demo.py:19`, `frontend/src/views/Walkthrough.tsx` |
| P2-15 | Team → Invite | Create an invitation | "Ledgerline does not send email in this build." The accept page shows "Invited as **operator**" (lower case), and a used link says "this invitation is invalid, used or expired" (lower case, no full stop) | "Copy this link and send it to Sam; it works once and expires in 3 days." Show the role label. Run errors through `friendly()` | `frontend/src/views/Team.tsx:103`, `frontend/src/views/Auth.tsx:163,171,176`, `backend/ledgerline/control.py:400` |
| P2-16 | Approvals | Any approval | Shows a 64-character "Scope hash" and "Deposit … · version 2" to every approver. Pills read lower case: "pending", "processing", "paid", "executed" | Put the hash behind "Details"; capitalise the status labels | `frontend/src/views/Approvals.tsx:83-95,148,181-183` |
| P2-17 | Pause switch | Settings → Pause all money-out | One click pauses with an empty reason, and the reason field is optional. The top-bar badge then has no tooltip text | Require a short reason (it is "recorded"); show who paused it and why in the badge | `frontend/src/views/Settings.tsx` (PauseCard) |
| P2-18 | Settings → Your account | Look at Session ends | "05 Nov, 04:52 UTC at the latest". Every time in the app is UTC with no option for local time | Show times in the browser's time zone with UTC in a tooltip, or add an org time zone setting | `frontend/src/format.ts` (`when`) |
| P2-19 | Treasury / Settings in a real company | Open Treasury with no bank | "Synthetic rates · Fixed synthetic rates (local simulated bank)" and a "Reference rates" card in Settings, for a real company that has no simulated bank, only manual records. The same thing is called "No bank connected", "manual records", "local simulated bank", "simulated records" and "local workspace" in different places | Pick one name for the no-bank state ("Manual records, no bank connected"). Hide synthetic conversion quotes in real companies, or label them "for planning only" | `frontend/src/views/Treasury.tsx:131`, `frontend/src/views/Settings.tsx:34-36` |
| P2-20 | Every anonymous page | Open the landing page or sign-in | Each load logs a console error, "Failed to load resource: 401 (Unauthorized)" for `/api/auth/me`. This is harmless, but it is the first thing a technical judge sees in DevTools | Have `/auth/me` return `200 {"user": null}` when signed out, or call a no-error session probe | `frontend/src/auth.tsx:26-35` |

## P3: nice to have

- **Sign-up** (`frontend/src/views/Auth.tsx:116-123`): no "I agree to the Terms" line, and no hint of what happens next, such as "We'll take you to a setup checklist".
- **Customer form** (`frontend/src/views/Customers.tsx:253-262`):
  - "Refund account" is free text, so it is unclear what to enter for a real bank account.
  - "Payer agent public key (Base64 raw Ed25519…)" sits in the main form a bookkeeper fills in. Move it under "Advanced".
- **Invoices** have no delete; void exists through adjustments, which is right for accounting, but say so. There is no PDF or "send invoice"; that is fine for a reconciliation tool, but the landing page could say "bring invoices from your accounting system".
- **Setup checklist:** "Invite a second approver" ticks as soon as an invitation exists. Ticking it on accept would be more accurate. Add "Set opening balances and reserves" (see P1-4).
- **The Inbox in a practice company** shows both the **Show me** button and a "See what it does in three minutes" guide card. Two parallel tours is one too many.
- **`/favicon.ico` and `/robots.txt`** return the HTML page. Browsers use the SVG favicon from `<link rel="icon">`, so the tab is fine.
- **Keyboard:** payment rows are focusable (`tabindex=0`) but have no role or label. Add `role="button"` and `aria-label="Open DEP-…"`, or put a link in the first cell.
- **Sign out** lands on `#/inbox`, which shows Sign in. `#/signin` (or the landing page) would be cleaner.
- **README badge** says "Python-3.14" while the setup section says "Python 3.12+". It ran fine on 3.13 here (`README.md:16`).

---

## Docs check (README, JUDGE_QUICKSTART, SUBMISSION_DRAFT, JUDGE_QA)

The honest limits (sandbox only, simulated payer agents, two-person rule checks accounts not people, live sends done with the owner's two accounts) are consistent across all four docs and should stay as they are. Items to fix:

1. **Contradiction about customers' own agents:** `docs/SUBMISSION_DRAFT.md:49` ("Honest scope") says "A customer's own hosted agent cannot be connected yet." The same file's "Limits" section, README, JUDGE_QA and the quickstart's "Bring your own payer agent" all say it can be connected. The app repeats the old wording at `frontend/src/views/Settings.tsx:189` (P1-8). This undersells the product and looks careless.
2. **Approval expiry:** JUDGE_QA's comparison table says "an approval expires after 72 hours". That is true, but the doc should say it is fixed (not configurable) until P1-2 lands. Also, saving the Policy form resets it today (P1-1).
3. **JUDGE_QUICKSTART step 8:** "records that the demo was tried". Say "records that the tamper test was tried", to match the in-app wording (`practice.tamper_tried`).
4. **JUDGE_QUICKSTART step 2 / README step 1:** "Choose Practice company". Correct, and the app matches it. But a real company signing up sees "Disabled options have not been set up by this server's administrator" under a greyed-out Google button (P1-9). On the live site Google is configured, so this is a local-only issue unless the keys go missing.
5. **SUBMISSION_DRAFT description:** "It is a working multi-tenant SaaS: sign-up (email or Google), organizations with … roles, … CSV import, audit export". These claims hold. But a buyer reading "SaaS" will expect password reset, profile editing, data export and deleting a company, and none of them exist (P1-6, P2-3). Either add the basics or say "multi-tenant web app" and list what is missing under "Honest scope".
6. **SUBMISSION_DRAFT description:** "Claude reads the remittance email or PDF through four strictly typed tools". This checks out: `backend/ledgerline/claude_reader.py:25-46` defines four tools.
7. **JUDGE_QUICKSTART step 7 scorecard** ("6 deposits, 4 decided without a person and 3 of those fully closed, 1 approval, 1 escalation, 0 double payments, ledger balanced") matched the CEO view exactly in this run: 6 / 4 / wrong refunds avoided 1 / false claims caught 1 / 0 double payments / balanced.
8. **"Show me … never approves or sends money"** checks out: stop 5 leaves APR-… pending.
9. **README line 367** says "every page meets WCAG AA contrast". The app shell passed a computed-contrast check on Inbox, Payments, Approvals, Ledger, Settings, Activity, CEO and Sign in. The landing page was not measurable automatically because of its gradient backgrounds, and was not checked by eye at small sizes. Its fine print "Connect your Airwallex test account…" (`rgb(129,147,171)`) is worth a manual look against the hero background.
10. **The README top line** still reads "3-minute video: coming before 13 Nov" (owner task, already tracked in SUBMISSION_DRAFT step 2).
11. **Wording that reads as a demo where it could read as a product:** the README tagline "Sandbox and made-up data only: no real money moves" is accurate for judges. On the product side (landing page, FAQ), "Not yet. It runs against the Airwallex test environment… There is no billing today" is honest and good. The demo feel comes from the app, not the docs: the Simulate buttons in a real company (P1-3), the default "Short by" reserves (P1-4) and the developer strings (P1-5, P1-9).

---

## Suggested order of work (about one day)

1. P1-1 and P1-2 together: merge the policy on save, and add an expiry field.
2. P1-3: no simulated sends in real companies; add "Record refund made outside Ledgerline".
3. P1-4: zero default reserves for *My company*, plus an opening-balance step in the checklist.
4. P1-5, P1-9 and P2-1: a wording pass on reasons, Integrations and audit codes.
5. P1-8: correct the agent wording in the app and in SUBMISSION_DRAFT.
6. P1-7: Privacy, Terms, Security and Help links, plus a real 404.
7. P1-6: an owner-issued password reset link, and editable name.
8. P1-10, then the P2 items in table order.
