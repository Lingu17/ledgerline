<p align="center">
  <a href="https://35-207-220-110.sslip.io"><img src="docs/assets/banner.svg" alt="Ledgerline: when a payment doesn't match, my agent asks the payer's agent and verifies the answer before any money moves" width="100%"></a>
</p>

<p align="center">
  <a href="https://35-207-220-110.sslip.io"><img alt="Live app" src="https://img.shields.io/badge/live-35--207--220--110.sslip.io-5ec4b6?style=for-the-badge&logo=googlecloud&logoColor=white"></a>
  <a href="https://35-207-220-110.sslip.io/#/architecture"><img alt="3D architecture" src="https://img.shields.io/badge/architecture-interactive%203D-0d2038?style=for-the-badge"></a>
  <a href="docs/JUDGE_QUICKSTART.md"><img alt="Judge quickstart" src="https://img.shields.io/badge/judges-5--minute%20path-ffd68c?style=for-the-badge"></a>
</p>

<p align="center">
  <img alt="Track" src="https://img.shields.io/badge/track-Treasury%20%26%20Ops-1f6feb">
  <img alt="Airwallex" src="https://img.shields.io/badge/Airwallex-sandbox%20verified-612fff">
  <img alt="Claude" src="https://img.shields.io/badge/Claude-opus--5--5%20·%20advisory%20only-d97757">
  <img alt="MCP" src="https://img.shields.io/badge/MCP-signed%20payer%20agents-444">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.14%20·%20FastAPI-3776ab?logo=python&logoColor=white">
  <img alt="React" src="https://img.shields.io/badge/React-18%20·%20TypeScript-149eca?logo=react&logoColor=white">
  <img alt="CI" src="https://github.com/Lingu17/ledgerline/actions/workflows/ci.yml/badge.svg">
</p>

<h3 align="center">Ledgerline works out what every incoming payment was for, checks the answer,<br>and keeps a person in control of any money that leaves.</h3>

<p align="center"><b>Built for small companies that bill in several currencies.</b> Sandbox and made-up data only: no real money moves.</p>

---

## ⚡ What it does, in plain English

A 12-person company bills customers in the US, Europe and the UK. Money arrives with a missing reference, a bank fee taken off, or in the wrong currency, and sometimes a customer pays twice. One finance person chases each case by email, for days, while bills fall due in another currency.

**Ledgerline does that chasing.** It settles the clear payments by itself. When one is unclear, it asks the customer's own finance agent what the money was for, and it **checks the answer before believing it**. It does this by itself as soon as the payment arrives. Then it settles the invoice, holds a credit, requests the exact balance, or proposes a refund. Small refunds backed by verified evidence go through under your limit; anything larger, and every bill payment, needs a second person.

> **The moment that shows it.** A payment looks like a duplicate, so the first plan is to refund it. The customer's agent answers, with a signature, that it was an advance. Ledgerline checks that answer, changes its decision, and **no wrong refund ever leaves the bank**. Another agent gives a signed but false answer: it is rejected, and a person gets the reason.

<p align="center"><img src="docs/screenshots/11-ceo.png" alt="The CEO view: cash, what needs a person, what the agent handled, and whether the numbers can be trusted" width="85%"></p>

### Why a CEO would care

| You want | What you get |
|:--|:--|
| **Less manual chasing** | In the reference company, 4 of 6 payments settle with no person, including one the agent resolved by asking by itself, and the rest arrive with the reason and the next step |
| **No costly mistakes** | No double payments, no refund of money that was really an advance, and no money out on one person's say-so |
| **To know where you stand** | The **CEO view** answers four questions on one screen: are we safe, what happened, what needs me, can I trust these numbers |
| **Cash in the right place** | Each bill gets one answer: pay it, convert only what is short, delay it, or ask a person. It can also bring cash in early |
| **Proof for an audit** | Every decision shows its reason, can be replayed to the same answer, and sits in a tamper-evident log |

### Why a judge should look closer

| What stands out | Where to check it |
|:--|:--|
| **Agents on both sides of a payment.** The customer's agent answers over MCP with a signed claim, treated as a claim and not a fact | Payments → DEP-1005 and DEP-1004 |
| **The decision changes when evidence arrives,** before any money moves, and the whole path is on screen | Payments → any payment → Decision path |
| **Money rules live in code.** Claude reads messy emails and PDFs through typed tools, cannot state an amount, and can never move money | [Money rules](#%EF%B8%8F-money-rules-the-code-enforces) |
| **Real Airwallex sandbox runs,** with honest labels on everything that is simulated | [Measured, not claimed](#-measured-not-claimed) |

---

## ✨ Features

**Live** means it has run against the real Airwallex sandbox. **Tested** means automated tests on the simulated bank, not yet run on the sandbox.

| Feature | What it does | Status |
|:--|:--|:--:|
| **Payment matching** | Clean matches, bank fees written off, part payments, duplicates and missing references | Live |
| **The agent asks by itself** | An unclear payment gets its question asked on arrival, with no click. A signed answer must pass three checks: who signed it, that it is about this payment and still fresh, and that your records agree | Tested, simulated agents |
| **AI document reader** | Claude reads remittance emails and PDFs and suggests; a person decides | Live |
| **Second-person approval** | Every bill payment, and refunds above your limit. The approver sees the exact amount and destination; if anything changes, the approval is void | Live |
| **Refunds and bill payments** | One transfer under a duplicate lock. SENT is not final; only PAID closes it | Live |
| **What to pay first** | Ranks bills and decides: fund, convert, defer or escalate. A bill that releases more cash than it costs goes first | Tested |
| **Convert only the shortfall** | Keeps a reserve per currency and buys only what a bill needs | Live |
| **Bring cash in early** | A capped discount through a hosted Airwallex link, booked once it is paid | Live |
| **Exact-balance request** | A payment link and a ready email draft for what is still owed | Link created live; paid link tested |
| **Wrong-currency payments** | Recommends converting only what the invoice needs, or holding; a person clicks | Tested |
| **CEO view** | One screen for whoever runs the company | Tested |
| **Live rates** | Airwallex sandbox rates, refreshed every minute on a connected account | Live |
| **Background checks** | Finds paid links and missed deposits by itself | Tested |
| **Ledger to the cent** | Double entry, balanced per currency, and currencies are never added together | Live |
| **Tamper-evident log and replay** | Detects an edited or removed event, and reruns any plan on its stored inputs | Live |
| **Pause switch** | Stops all money leaving at once while matching keeps running | Tested |
| **Real company accounts** | Sign-up, isolated data per company, Owner, Operator and Viewer roles, CSV import, and each company's own encrypted Airwallex keys | Live |

---

## 🚀 Try it (five minutes)

1. Open **https://35-207-220-110.sslip.io** → **Get started** → any name and email (nothing is emailed) → **Practice company**.
2. The **Inbox** has a short guide. **Payments → DEP-1005 → Ask payer's agent**: the duplicate turns out to be an advance, and the refund is dropped. A practice company waits for you to press this so you can watch; **Receive an unclear payment** shows a new payment handled with no click, which is how a real company works.
3. **Payments → DEP-1004 → Ask payer's agent**: a correctly signed but false answer is rejected.
4. **Practice steps**: a currency conversion, a refund a person approves, and the bank moving from SENT to PAID.
5. **CEO view**: the whole company on one screen.

Each company's data is isolated. A practice company uses made-up data and a simulated bank. For your own company, choose **My company** and connect your Airwallex sandbox keys under Settings.

**What it does not do yet:** handle live money, send email from the server (balance requests open as a draft in your own mail), or connect a customer's own hosted agent. **The payer agents are simulations:** they use real MCP and real signatures, but answer from a fixed table with keys held on this server, so today the signature proves the mechanism, not that an outside party said anything. Without an agent, a person or the document reader handles the case, so it is useful today. Time saved has not been measured with a real customer.

---

## 🎬 How the decision works

```mermaid
sequenceDiagram
    autonumber
    participant Bank as Airwallex (sandbox)
    participant L as Ledgerline
    participant Agent as Customer's finance agent (MCP)
    participant Op as Finance team
    Bank->>L: Payment received (signed webhook)
    L->>L: First plan from rules: "looks like a duplicate, propose refund"
    L->>Agent: What was this payment for?
    Agent-->>L: Signed answer: "advance for INV-2291"
    L->>L: Check 1 signer ✓ · Check 2 this payment and fresh ✓ · Check 3 our records agree ✓
    L->>L: New plan: hold as customer credit. Refund dropped before any money moved
    Note over L,Op: Another payer claims a different customer's invoice → signature ✓, records ✗ → rejected, a person gets the reason
    L->>Op: A real duplicate over the limit → approval tied to amount, destination, evidence
    Op->>L: Second person approves
    L->>Bank: One transfer, stable request id
    Bank-->>L: SENT (still owed) → PAID (closed)
    L->>L: Ledger balances to the cent, per currency
```

Every payment shows this as a **decision path**: received → first plan → evidence → checks → decision → approval → settlement → accounting.

| Apparent duplicate becomes credit | Signed but false claim is rejected | Approval tied to the exact amount |
|:--:|:--:|:--:|
| ![Evidence](docs/screenshots/05-evidence.png) | ![Escalated](docs/screenshots/04-payment-escalated.png) | ![Approval](docs/screenshots/07-approval.png) |

---

## 👩‍💼 Using it at work

Everything an employee needs to act on is in the **Inbox**, so start there each day. Treasury's *What to pay first* decides each bill; deciding moves no money. Each item opens the page where it can be resolved.

### Your daily routine

| When | Go to | What you do |
|:--|:--|:--|
| Start of day, if you run the company | **CEO view** | See in one screen whether anything needs you |
| Start of day | **Inbox** | Work through what is waiting: unclear payments, approvals and payments whose bank outcome is unknown |
| A payment is unclear | **Payments** → open it | Read the decision path, then **Ask payer's agent** or **Read remittance…**. Ledgerline checks the answer against your records |
| Someone needs a second person | **Approvals** | Check the amount and destination, then approve or reject. You cannot approve your own proposal |
| Bills are due | **Treasury** → *What to pay first* | Each bill shows one answer: fund, convert, defer or escalate, with the reason |
| Cash is short | **Treasury** → *Bring cash in early* | Offer a capped discount on an invoice not yet due, and share the link with the customer yourself |
| End of day or audit | **Ledger** and **Activity** | Confirm every currency balances, **Verify log integrity**, **Download evidence** |

### How to run each feature

<details>
<summary><b>Set up your company (Owner, about 10 minutes)</b></summary>

1. **Get started** → **My company**. For a safe trial with made-up data, choose **Practice company**.
2. **Settings → Connect your Airwallex**: paste your sandbox keys. They are checked first and stored encrypted.
3. **Team → Invite member**: add at least one more **Operator**, because money-out needs a second person. Nothing is emailed, so send the invitation link yourself.
4. **Settings → Policy**: set reserves, the refund auto-limit, the fee tolerance and the maximum early-payment discount.
5. **Customers & invoices → Import CSV**, or **New customer** and **New invoice**. **Treasury → Bills → Import CSV** or **Add bill**.

CSV columns:

| File | Columns |
|:--|:--|
| Customers | `name,country,payer_names,refund_beneficiary` |
| Invoices | `customer,currency,amount,due_date,description` |
| Bills | `payee,currency,amount,due_date,priority,defer_until,description` |
</details>

<details>
<summary><b>Handle an incoming payment</b></summary>

1. Connected accounts receive payments by signed webhook, and missed ones are found automatically about every ten minutes (**Settings → Find missed deposits** does it at once). Otherwise use **Payments → Record payment** or **Import CSV**.
2. Clean matches settle on their own, and a bank fee within tolerance is written off.
3. For anything else, open the payment and use **Ask payer's agent** or **Read remittance…** (paste an email or upload a PDF). The AI reader only suggests, and a person decides.
4. The result is one of: invoice settled, exact balance requested, credit held, refund proposed, or escalated with the reason.
5. For a part payment, open the balance request, create the link, and use **Open email draft** or **Copy message** to send it to the customer.
6. For a payment in the wrong currency, read the recommendation and click **Convert and apply**, or leave it held.
7. When a balance link is paid, the balance settles the same way, within about two minutes.
</details>

<details>
<summary><b>Pay a bill</b></summary>

1. **Treasury** → the bill must show **Fund**. Click **Pay** and choose the beneficiary. Who can receive it comes from your Airwallex account.
2. A **different** team member approves it under **Approvals** (or **Treasury → Bill payments**).
3. Click **Send payment**. The plan is checked again before anything reaches the bank.
4. **Check status** until it shows paid. SENT is not final: the bill stays open and its cash stays committed until PAID.
5. On a sandbox account, an Owner moves the transfer on with **Test bank: sent**, then **Test bank: paid**.
</details>

<details>
<summary><b>Bring cash in early</b></summary>

1. When a bill shows **Defer** or **Escalate**, **Treasury → Bring cash in early** lists invoices not yet due, with the discount cost and the cash each one brings in.
2. **Create offer** makes a hosted Airwallex link. Send it to the customer yourself.
3. After they pay, Ledgerline books the discount and the cash and re-plans the bills within about two minutes. **Check payment** does it at once.

In a practice company, **Practice: customer pays** runs the same path without a card.
</details>

<details>
<summary><b>When cash is tight or something looks wrong</b></summary>

- **Stop all money-out:** **Settings → Pause all money-out**. Any Operator can pause, and only an Owner can resume. Matching keeps running.
- **"Outcome unknown":** click **Check status**. Do not pay again, because Ledgerline looks the request up before any retry.
- **Keep cash out of planning:** **Settings → Policy → Set aside from planning**.
- **Check a past decision:** **Treasury → Plan history → Replay** runs the planner again on the stored inputs. **Activity → Verify log integrity** detects an edited or removed event; someone with database write access could rewrite the whole chain, so keep the head hash from a downloaded evidence export to rule that out.
</details>

### Who can do what

| Job | Role |
|:--|:--|
| Auditor or manager who only needs to look | **Viewer** |
| Finance staff doing the daily work and approving each other's payments | **Operator** |
| Finance lead: team, policy, Airwallex connection, resuming money-out, sandbox test buttons | **Owner** |

### What saves the team time

- **One queue:** the Inbox replaces checking the bank, email and spreadsheets separately.
- **Clean payments need no one:** in the reference company, 4 of 6 payments settled without a person.
- **Reasons on screen:** each decision shows why it was made, so a colleague can pick it up without asking.
- **Bulk import:** bring customers, invoices, bills and payments in by CSV.
- **Hard to make costly mistakes:** a second approver, a duplicate lock and a pause switch are enforced by the system, not by memory.
- **Audit in one click:** **Download evidence** exports the record, and **Verify log integrity** checks it.

---

## 📊 Measured, not claimed

| What | Result | Where |
|:--|:--|:--|
| Reference company (6 payments) | **4** settled with no person · **1** approval · **1** escalation with its reason · **0** double payments · ledger balanced | [EVALUATION](docs/EVALUATION.md) |
| Randomized companies | **50** companies · **2,127** payments · **0** allocations disagreeing with an independent reference model | [EVALUATION](docs/EVALUATION.md) |
| Accuracy harness | **200** companies and 25 sample walkthroughs · **51,475** checks · **0** mismatches | [ACCURACY_REPORT](docs/ACCURACY_REPORT.md) |
| Live Airwallex sandbox (Google Cloud host) | signed webhooks booked once · beneficiary validated and created · current FX rates · refund approved by a second member, **one** transfer, SENT → PAID, liability released only at PAID | [INTEGRATION_EVIDENCE](docs/INTEGRATION_EVIDENCE.md) |
| Live hosted link (2 Nov) | a test-card payment of EUR 197 on a Singapore sandbox account was reported paid by Airwallex and booked once; the invoice settled and the bill moved from Escalate to Fund | Live app |
| Live bill payment (2 Nov) | Airwallex accepted a EUR 100 transfer, moved by its sandbox simulation through SENT to PAID; the bill closed and one journal entry reduced cash only at PAID. Proposer and approver were two accounts of the same owner, so this tests the control and the bank call, not independent review | Live app |
| Live Claude | text and PDF remittances read by `claude-opus-5-5`; a planted prompt injection was ignored and flagged; nothing applied | [INTEGRATION_EVIDENCE](docs/INTEGRATION_EVIDENCE.md) |
| Release | CI 5/5 jobs · public smoke 32/32 · data survives restart, VM reboot and redeploy (8/8 each) | [Acceptance report](docs/FULL_APPLICATION_ACCEPTANCE_REPORT.md) |

What is **not** measured yet: real customers' payment mix, hours saved, adoption. Those need a pilot.

---

## 🏗️ Architecture

```mermaid
flowchart TB
  subgraph VM["☁️ Google Cloud VM · e2-small · asia-south1"]
    direction LR
    C["Caddy<br/>HTTPS · HSTS · CSP"] --> A["FastAPI<br/>rules · approvals · ledger"]
    A --> D[("SQLite per organization<br/>/var/lib/ledgerline")]
    A --> K[("Payer-agent keys<br/>0600, per organization")]
    D -. nightly consistent copy .-> BK[("Backups · 7 kept")]
  end
  B["🌐 Browser<br/>React + TypeScript"] -->|one origin| C
  AW["🏦 Airwallex sandbox"] -->|signed deposit.settled| C
  A -->|quotes · conversions · transfers · beneficiaries| AW
  A -->|typed tools only| CL["🤖 Claude API"]
  A -->|explain_payment| PA["🔏 Payer agents (MCP)"]
```

One VM serves the website, the API and the data. Explore it in 3D at [`#/architecture`](https://35-207-220-110.sslip.io/#/architecture) (drag or use the arrow keys).

<details>
<summary><b>Code map</b></summary>

```
backend/ledgerline/
  api/              security (session → membership → role → organization), routes, auth, OAuth
  control.py        users, organizations, memberships, sessions, invitations, throttling
  tenancy.py        one isolated context per organization; sandbox allow-list checked on every use
  webhooks.py       HMAC over x-timestamp + raw body, skew limit, event-id dedupe
  matching.py       deterministic first plan        reconcile.py   plans, buckets, revisions
  evidence.py       the three checks on claims       claude_reader.py  typed proposals, budgets, PDF, usage
  payouts.py        scoped approvals, four-eyes      treasury.py    reserves, single-use quotes
  ledger.py         double entry, conservation       providers/     local simulated bank, Airwallex sandbox
  payer_agents/     MCP server + Ed25519 keys        beneficiaries.py, sandbox_receipts.py
frontend/src/       React views: Inbox, Payments, Approvals, Evidence, Treasury, Ledger, Customers, Activity, Team, Settings, CEO view, Practice steps, Architecture
deploy/vm/          setup.sh, update.sh, Caddyfile, systemd units, backup.py
scripts/            smoke_deploy.py, evaluate.py, accuracy_run.py
```
</details>

---

## 🛡️ Money rules the code enforces

| Rule | What it prevents |
|:--|:--|
| Rules, limits, reserves and conservation live in Python and per-organization policy | a prompt deciding amounts |
| Integer minor units; bad precision, negative, boolean, non-finite amounts refused | rounding drift and malformed input |
| Reference + identified payer + currency, never amount alone | allocating money to the wrong customer |
| A signed answer is a claim: registered key of the *asked* customer, bound to this deposit and amount, fresh, records agree | forged, replayed or false agent answers |
| Approvals bind deposit version, amount, currency, destination and evidence hash; any change invalidates | approving one thing and paying another |
| Proposer ≠ approver | one person moving money alone |
| One live refund per deposit, stable request ids, lookup before any retry | paying twice after a timeout |
| SENT keeps the liability; only PAID releases it | treating an unsettled transfer as done |
| Pause stops every money-out action; matching continues | runaway actions during an incident |
| Claude output is advisory and schema-validated; it can never authorise money | AI moving money |

<details>
<summary><b>Roles</b></summary>

| | Viewer | Operator | Owner |
|:--|:--:|:--:|:--:|
| Read everything, export evidence | ✓ | ✓ | ✓ |
| Record/import payments, customers, invoices, resolve, ask agents, read remittances, propose returns | | ✓ | ✓ |
| Approve/reject (not own proposals), execute, quotes, conversions, pause | | ✓ | ✓ |
| Resume, policy, team, settings, sandbox tools, opening balances | | | ✓ |

Every rule is enforced by the API; the UI only hides what you cannot do.
</details>

<details>
<summary><b>Security posture</b></summary>

- scrypt password hashes; 12+ characters with upper, lower and a digit; login errors never reveal whether an account exists; 5 failures per email or IP in 15 minutes → 429.
- Session cookie HttpOnly, Secure, SameSite=Strict, Path=/api; only its SHA-256 is stored; 2 h idle and 12 h absolute expiry; logout and password change revoke server-side.
- CSRF token on every mutation plus Origin allow-list; forged `X-Forwarded-For` cannot change the throttling identity.
- HSTS, strict CSP, `X-Frame-Options: DENY`, `nosniff`; only ports 22/80/443 reachable.
- Airwallex, Anthropic and Google secrets are server environment variables only; webhook secrets are write-only; nothing secret in the browser bundle, Git, logs or exports.
- Sign in with Google (OIDC + PKCE, never auto-linked to a password account by email). Apple is intentionally not offered.
</details>

---

## 🖼️ Screens

| | |
|:--:|:--:|
| ![Landing](docs/screenshots/01-landing.png) | ![Architecture](docs/screenshots/02-architecture.png) |
| ![Inbox](docs/screenshots/03-inbox.png) | ![Approval](docs/screenshots/07-approval.png) |
| ![CEO view](docs/screenshots/11-ceo.png) | ![Ledger](docs/screenshots/09-ledger.png) |
| ![Walkthrough](docs/screenshots/08-walkthrough-done.png) | ![Treasury](docs/screenshots/06-treasury.png) |

<sub>Captured from a real run on a synthetic company (`frontend/e2e/screenshots.spec.ts`). Desktop and 375 px layouts; every page meets WCAG AA contrast.</sub>

---

## 🧪 Run it yourself

<details>
<summary><b>Locally (Python 3.12+, Node 22.12+)</b></summary>

Linux or macOS:

```bash
python3 -m venv backend/.venv && backend/.venv/bin/pip install -r backend/requirements-lock.txt
```

```bash
(cd frontend && npm ci && npm run build)
```

```bash
cd backend && .venv/bin/python -m ledgerline
```

Windows:

```bash
powershell -ExecutionPolicy Bypass -File scripts/setup.ps1
```

```bash
powershell -ExecutionPolicy Bypass -File scripts/start.ps1
```

Open http://127.0.0.1:8000 → **Create an organization**. No default accounts. Data lives in `backend/var/`.

```bash
powershell -ExecutionPolicy Bypass -File scripts/test.ps1
```

```bash
backend\.venv\Scripts\python scripts\evaluate.py --seeds 50
```
</details>

<details>
<summary><b>Configuration (all optional)</b></summary>

| Variable | Purpose |
|:--|:--|
| `AIRWALLEX_CLIENT_ID`, `AIRWALLEX_API_KEY` | Airwallex sandbox (server-wide). Companies can instead connect their own keys under Settings |
| `LEDGERLINE_SANDBOX_ORGS` | the only organizations allowed to use them |
| `ANTHROPIC_API_KEY` | Claude reader (`claude-opus-5-5`, daily budgets per organization and server) |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Sign in with Google |
| `LEDGERLINE_PUBLIC_URL`, `LEDGERLINE_ALLOWED_ORIGINS`, `LEDGERLINE_COOKIE_SECURE`, `LEDGERLINE_TRUSTED_PROXY_HOPS` | public origin, CSRF allow-list, secure cookie, proxy hops |
| `LEDGERLINE_WATCH_SECONDS` | how often connected accounts are checked for paid links (default 120, 0 turns it off) |
| `LEDGERLINE_DATA_DIR`, `LEDGERLINE_REQUIRE_PERSISTENT_MOUNT` | data location and a guard against ephemeral storage |

Without keys the app runs fully on the simulated bank and labelled offline rules.
</details>

<details>
<summary><b>Deploy, back up, troubleshoot</b></summary>

```bash
sudo bash deploy/vm/setup.sh <host> self <commit>
```

```bash
sudo bash /opt/ledgerline/src/deploy/vm/update.sh <commit>
```

Caddy (automatic HTTPS) → systemd service as an unprivileged user → SQLite on the persistent disk. A nightly timer makes consistent backups (7 kept); an isolated restore test passed. `scripts/smoke_deploy.py <url> --save/--verify` checks 32 behaviours and proves persistence across restart, reboot and redeploy. Full guide, backup/restore and troubleshooting table: [DEPLOYMENT](docs/DEPLOYMENT.md).
</details>

---

## 📚 Documents

| For | Read |
|:--|:--|
| Judges | [JUDGE_QUICKSTART](docs/JUDGE_QUICKSTART.md) · [DEMO_SCRIPT](docs/DEMO_SCRIPT.md) |
| Evidence | [INTEGRATION_EVIDENCE](docs/INTEGRATION_EVIDENCE.md) · [EVALUATION](docs/EVALUATION.md) · [ACCURACY_REPORT](docs/ACCURACY_REPORT.md) |
| Acceptance | [FULL_APPLICATION_ACCEPTANCE_REPORT](docs/FULL_APPLICATION_ACCEPTANCE_REPORT.md) · [HACKATHON_REQUIREMENTS_MATRIX](docs/HACKATHON_REQUIREMENTS_MATRIX.md) |
| Operations | [DEPLOYMENT](docs/DEPLOYMENT.md) · [DEPLOYMENT_HANDOFF](docs/DEPLOYMENT_HANDOFF.md) |
| Origin | [Accepted proposal](docs/original-proposal.txt) · [SUBMISSION_DRAFT](docs/SUBMISSION_DRAFT.md) |

## ⚠️ Honest limits

- Payer agents are simulations: real MCP and signatures, but answers come from a fixed table and keys sit on this server. Real customers' agents would register their own keys at onboarding. Check 3 tests plausibility against your records; it cannot tell a real advance from a false one that fits.
- Airwallex hosted payment links depend on the account's region. A Singapore sandbox account created a real hosted link on 2 Nov and it was paid with a test card; Ledgerline asks Airwallex every two minutes rather than using link webhooks, and settlement timing is not tracked. The earlier account was refused with `configuration_error`, and there Ledgerline keeps a labelled draft and never invents a URL.
- Airwallex's dashboard replay did not produce a second delivery, so duplicate rejection is proven by tests.
- One VM, backups on the same disk, Free Trial credit until 28 Jan 2027; no email delivery, password reset, SSO/MFA or billing.

<p align="center"><sub>Built for the Airwallex Agentic Banking Hackathon · sandbox and synthetic data only · no real money</sub></p>
