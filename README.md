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

<h3 align="center">Resolve unclear incoming payments using verified evidence,<br>with every decision explained and every cent accounted for.</h3>

---

## ⚡ In thirty seconds

A finance team receives money in USD, EUR and GBP. Some payments match an invoice cleanly; many don't: no reference, a bank fee shaved off, a customer who paid twice, the wrong currency. Today one person chases each of those by email, for days.

**Ledgerline turns that into a decision engine.** Rules in code settle the clean cases. For the unclear ones it asks **the payer's own accounts-payable agent** what the money was for, over MCP, and treats the signed answer as **a claim to verify, not a fact**. Only after three checks pass does it act: settle an invoice, hold credit, request the exact balance, convert only the FX shortfall, or propose a refund, which above your limit **a second person must approve**. Claude reads emails and PDFs when there is no agent, but it can only *suggest*. It never moves money.

| | |
|:--|:--|
| 🎯 **For** | small multi-currency companies on Airwallex Global Accounts |
| 🧠 **Agentic part** | agent-to-agent evidence over MCP, verified before trust; Claude as a typed, advisory reader |
| 🛡️ **Safety** | money rules in code · four-eyes · duplicate lock · stable request ids · pause switch · SENT ≠ PAID |
| ✅ **Proof** | 388 backend tests · 18 browser tests · 5-job CI · 2,127 random payments with 0 allocation disagreements · live Airwallex refund SENT → PAID · live hosted link paid and booked |

---

## 🎬 The story the demo tells

```mermaid
sequenceDiagram
    autonumber
    participant Bank as Airwallex (sandbox)
    participant L as Ledgerline
    participant Agent as Payer's AP agent (MCP)
    participant Op as Finance team
    Bank->>L: deposit.settled (signed webhook)
    L->>L: First plan from rules: "looks like a duplicate, propose refund"
    L->>Agent: explain_payment(deposit, amount, currency)
    Agent-->>L: Ed25519-signed claim: "advance for INV-2291"
    L->>L: Check 1 signer ✓ · Check 2 bound to this deposit & fresh ✓ · Check 3 our records agree ✓
    L->>L: Revised plan: hold as customer credit, refund dropped before any money moved
    Note over L,Op: A different payer claims another customer's invoice → signature ✓, records ✗ → rejected, escalated with the reason
    L->>Op: Genuine duplicate over the auto-limit → approval bound to amount, destination, evidence
    Op->>L: Second person approves
    L->>Bank: One transfer, stable request id
    Bank-->>L: SENT (liability kept) → PAID (liability released)
    L->>L: Ledger: deposits = applied + credits + refunds + unapplied, per currency, to the cent
```

Every payment shows this as a **decision path**: received → first plan → evidence → checks → decision → approval → settlement → accounting.

| Apparent duplicate becomes credit | Signed but false claim is rejected | Approval bound to the exact scope |
|:--:|:--:|:--:|
| ![Evidence](docs/screenshots/05-evidence.png) | ![Escalated](docs/screenshots/04-payment-escalated.png) | ![Approval](docs/screenshots/07-approval.png) |

---

## 🚀 Try it (five minutes)

1. Open **https://35-207-220-110.sslip.io** → **Get started** → any name and email (nothing is emailed) → **Practice company**.
2. **Payments → DEP-1005 → Ask payer's agent**: the duplicate becomes verified advance credit.
3. **Payments → DEP-1004 → Ask payer's agent**: a correctly signed claim for another customer's invoice is rejected.
4. **Read remittance…** on DEP-1004: paste an email or upload a PDF; Claude proposes, a person decides.
5. **Practice steps**: FX for the EUR bill, the refund a person approves, bank SENT then PAID, and the scorecard.

Your organization is isolated from every other one. A practice company uses made-up data and a simulated bank. To use your own company instead, choose **My company**, then connect your Airwallex sandbox keys under Settings: they are checked with Airwallex first, stored encrypted per organization, and can only reach the Airwallex test environment.

**When cash is short:** Treasury → *What to pay first* ranks bills due soon by priority, then due date, and decides each one: fund, convert only the shortfall, defer to a date you allowed, or escalate. New cash reopens only the decisions it changes, and each change is audited. Deciding moves no money. A funded bill can then be paid through the bank: a second person approves the exact amount and destination, the plan is rechecked before sending, and the bill closes only on PAID. **Add a cash squeeze** shows all four decisions in a practice company, and **Set aside from planning** (Settings → Policy) creates a real shortfall on a pre-funded sandbox wallet.

**Bring cash in early:** when bills are short, Treasury prices a discount on invoices not yet due (capped by policy, 2% by default) and creates a hosted Airwallex link. Nothing is emailed. Once Airwallex reports the link paid, the discount and cash are booked and the bills re-planned, within about two minutes or at once with **Check payment**. Link payment webhooks are not used yet.

**Proof you can check:** Treasury → *Plan history* → **Replay** runs the planner again on a decision's stored inputs and compares the result. Activity → **Verify log integrity** recomputes the audit hash chain, which detects an edited or removed event. Someone with database write access could rewrite the whole chain, so keep the head hash from a downloaded evidence export to rule that out.

**CEO view:** one screen says whether the company is safe, what the agent handled, what needs a person, and whether the numbers can be trusted. It only reads; any time-saved figure is labelled as an estimate with its assumption.

**Bills that release cash:** a bill can name the invoice its payment releases. Within a priority, a bill that releases more than it costs goes first, and the reason says so. Critical bills still come first.

**Paid in the wrong currency:** the payment is held and Ledgerline recommends converting only what the invoice needs, or holding it if a bill in that currency is short. A person clicks **Convert and apply**; the invoice settles when the bank reports the conversion settled.

**Not done yet:** live-money Airwallex access, sending email from the server (balance requests open as a draft in your own mail), and connecting a customer's own hosted payer agent (payer agents currently run on this server).

---

## 👩‍💼 Using it at work

Everything an employee needs to act on is in the **Inbox**, so start there each day. Each item opens the page where it can be resolved.

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
- **Check a past decision:** **Treasury → Plan history → Replay**.
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
| Accuracy harness | **250** companies · **64,215** checks · **0** mismatches | [ACCURACY_REPORT](docs/ACCURACY_REPORT.md) |
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
frontend/src/       React views: Inbox, Payments, Approvals, Evidence, Treasury, Ledger, Customers, Activity, Team, Settings, Walkthrough, Architecture
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
| ![Inbox](docs/screenshots/03-inbox.png) | ![Treasury](docs/screenshots/06-treasury.png) |
| ![Walkthrough](docs/screenshots/08-walkthrough-done.png) | ![Ledger](docs/screenshots/09-ledger.png) |

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

- Payer agents are simulations (real MCP and signatures); real customers' agents would be discovered at onboarding.
- Airwallex hosted payment links depend on the account's region. A Singapore sandbox account created a real hosted link on 2 Nov and it was paid with a test card; Ledgerline asks Airwallex every two minutes rather than using link webhooks, and settlement timing is not tracked. The earlier account was refused with `configuration_error`, and there Ledgerline keeps a labelled draft and never invents a URL.
- Airwallex's dashboard replay did not produce a second delivery, so duplicate rejection is proven by tests.
- One VM, backups on the same disk, Free Trial credit until 28 Jan 2027; no email delivery, password reset, SSO/MFA or billing.

<p align="center"><sub>Built for the Airwallex Agentic Banking Hackathon · sandbox and synthetic data only · no real money</sub></p>
