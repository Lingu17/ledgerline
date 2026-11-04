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

<h3 align="center">When a payment doesn't match, Ledgerline's agent asks the payer's agent,<br>checks the answer, and only then decides. A person stays in control of any money that leaves.</h3>

<p align="center"><b>For small companies that bill in several currencies.</b> Sandbox and made-up data only: no real money moves.</p>

<p align="center">
  <a href="https://35-207-220-110.sslip.io"><b>▶ Try it live</b></a> ·
  <!-- Owner: replace the next line with <a href="(video URL)"><b>🎬 Watch the 3-minute video</b></a> once it is recorded. -->
  <b>🎬 3-minute video: coming before 13 Nov</b> ·
  <a href="docs/JUDGE_QUICKSTART.md"><b>Judge quickstart</b></a> ·
  <a href="docs/JUDGE_QA.md"><b>Judge Q&amp;A</b></a>
</p>

---

## The problem, in one line

Money arrives with a missing reference, a fee taken off, in the wrong currency, or twice. Someone chases each case by email for days, and one wrong refund is real money gone.

## Try it alone in 3 steps (about 5 minutes)

1. Open **[the live app](https://35-207-220-110.sslip.io)** → **Get started** → choose **Practice company**. Any name and email work, with a password of 12+ characters. Nothing is emailed.
2. **Payments → DEP-1005 → Ask payer's agent.** The payment looks like a duplicate, so the first plan proposes a refund and holds it. The payer's agent answers with a signed claim that it was an advance. Three checks pass and the plan changes to **advance credit**. No wrong refund leaves. Then try **DEP-1004**: its signature is valid but the claim is false, so it is **rejected** and sent to a person with the reason.
3. **Practice steps → run to the end.** Approve the over-limit refund under **Approvals**, then press **Send as practice teammate**, because the person who approves a refund the agent proposed can't also send it. Watch the bank go **SENT → PAID** and the ledger balance to the cent.

## What it decides by itself, and what it never does

| By itself | Never by itself |
|:--|:--|
| Settles clear payments, writes off bank fees within tolerance, holds credits, and prepares the exact-balance request (a person sends it) | Sends a refund over your limit without two people |
| In a real company, asks the payer's agent the moment an unclear payment arrives | Believes an answer that fails any of the three checks |
| Sends small refunds backed by a verified answer, under the limit you set | Lets Claude state an amount or move money. Claude only reads documents, as advice |

**The three checks on every agent answer:** who signed it · that it is about this payment and still fresh · that your own records agree.

> **Limits, stated up front**
> - **Payer agents.** The built-in payer agents are simulated: they answer from a fixed table with keys held on this server, so their signature proves the mechanism, not that an outside party said anything. A customer can now run its own agent instead, holding its own key, and Ledgerline asks it over the network with the same three checks; that path is tested end to end with the reference agent (`tools/payer_agent`) as a separate process on the same machine. On 3 Nov 2026 it also ran across the internet: the reference agent ran on the owner's own PC behind a Cloudflare tunnel, the live site asked it about a practice payment, and its signed answer passed the three checks and was labelled Customer's own agent. That was the owner's machine, not an independent party, and no real company runs one today. The protocol is written down in [PAYER_AGENT_SPEC](docs/PAYER_AGENT_SPEC.md), with a JSON schema and a signed test vector.
> - **Run on the real Airwallex sandbox:** signed deposit webhooks, a refund of an unmatched deposit (SENT → PAID, one transfer), a currency conversion, a EUR 100 bill payment (SENT → PAID), a paid early-payment link, beneficiaries and live rates. **Tested only on the simulated bank:** refunds the agent proposes, including the rule that a different member sends them and the practice teammate; automatic refunds under the limit; a refund returned to a person after the limit is lowered; failed and timed-out transfers; the pause switch; a paid exact-balance link; and wrong-currency conversion.
> - **One person with two emails would pass the two-person rule.** It checks accounts, not people. Both live payments out, the refund and the bill payment, were proposed and approved with two accounts that belong to the owner, so they show the control and the bank call, not independent review.

<p align="center"><img src="docs/screenshots/11-ceo.png" alt="The CEO view: cash, what needs a person, what the agent handled, and whether the numbers can be trusted" width="85%"></p>

### Why a CEO would care

| You want | What you get |
|:--|:--|
| **Less manual chasing** | In the reference company, 4 of 6 payments are decided with no person, and 3 of those are fully closed. A part payment still needs someone to send the balance request. The rest arrive with the reason and the next step |
| **No costly mistakes** | No double payments, no refund of money that was really an advance, and no money out on one person's say-so |
| **To know where you stand** | The **CEO view** answers four questions on one screen: are we safe, what happened, what needs me, can I trust these numbers |
| **Cash in the right place** | Each bill gets one answer: pay it, convert only what is short, delay it, or ask a person. It can also bring cash in early |
| **Proof for an audit** | Every decision shows its reason, can be replayed to the same answer, and sits in a tamper-evident log; a practice company can try to tamper with it and watch the chain catch the row |

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
| **Why this plan** | A plain-language explanation of each payment's plan, written from structured facts only (ids, amounts, categories, check results; never free text such as the email, the payer name or an agent's own words) and checked: it must cite real ids and use only the facts' numbers, or it is not shown. Advice only; nothing that decides reads it | Tested |
| **Show me** | In a practice company, a seven-stop guided tour that runs the practice story and explains each screen. It never approves or sends money | Tested |
| **Try to tamper** | In a practice company, change one recorded amount straight in the database and watch the hash chain catch that exact row; restore it and the demo is recorded. The server refuses it in a real company. Nightly backup checks put an open demo's change back in their temporary copy and still verify | Tested |
| **Replay this decision** | Any plan the rules made can be re-run: Ledgerline keeps the exact inputs the rules read (and their hash in the audit log), runs the same rules on them again and shows **Same plan** or the difference. A person's decision has no rules to re-run. Read-only | Tested |
| **Two people for money out** | Every bill payment, and refunds above your limit. A person proposes and another approves; if the agent proposed it, one person approves and another sends. The approver sees the exact amount and destination; if anything changes, the approval is void | Live; agent-proposed refunds tested on the simulated bank only |
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
2. The **Inbox** has a short guide. **Payments → DEP-1005 → Ask payer's agent**: the duplicate turns out to be an advance, and the refund is dropped. A practice company waits for you to press this so you can watch; **Receive an unclear payment** shows a payment handled with no click, which is how a real company works. That payment is built to match the simulated agent's table, and it works once per company.
3. **Payments → DEP-1004 → Ask payer's agent**: a correctly signed but false answer is rejected.
4. **Practice steps**: a currency conversion, a refund you approve, and the bank moving from SENT to PAID. Alone, press **Send as practice teammate** to send the refund you approved. That labelled stand-in exists only in practice companies, the server refuses it anywhere else, and a real company needs a second real member.
5. **CEO view**: the whole company on one screen.

Each company's data is isolated. A practice company uses made-up data and a simulated bank. For your own company, choose **My company** and connect your Airwallex sandbox keys under Settings.

**What it does not do yet:** handle live money, send email from the server (balance requests open as a draft in your own mail), or connect a customer's own hosted agent; the payer agents are simulations (see the limits above). Without an agent, a person or the document reader handles the case, so it is useful today. Time saved has not been measured with a real customer.

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
- **Clear cases need no one:** in the reference company, 4 of 6 payments are decided without a person, and 3 are fully closed.
- **Reasons on screen:** each decision shows why it was made, so a colleague can pick it up without asking.
- **Bulk import:** bring customers, invoices, bills and payments in by CSV.
- **Hard to make costly mistakes:** a second approver, a duplicate lock and a pause switch are enforced by the system, not by memory.
- **Audit in one click:** **Download evidence** exports the record, and **Verify log integrity** checks it.

---

## 📊 Measured, not claimed

| What | Result | Where |
|:--|:--|:--|
| Reference company (6 payments) | **4** decided with no person, **3** fully closed · **1** approval · **1** escalation with its reason · **0** double payments · ledger balanced | [EVALUATION](docs/EVALUATION.md) |
| Randomized companies | **50** companies · **2,127** payments · **0** allocations disagreeing with an independent reference model | [EVALUATION](docs/EVALUATION.md) |
| Value on synthetic companies (first plan per payment) | **8,826** payments in 200 made-up companies built to be hard, with no payer agent answering: **30.4%** decided with no person (the reference company's 4 of 6 is once its payer agents answer), **50.5%** escalated with a reason, **19.2%** waiting for the payer's agent · **0** refunds sent without verified evidence or a person · about **223 hours** of matching saved *if* a payment takes 5 minutes by hand (an assumption) | [MEASURED_VALUE](docs/MEASURED_VALUE.md) |
| Accuracy harness (rules only, automatic asking switched off) | **200** companies and 25 sample walkthroughs · **61,063** checks · **0** mismatches · all **8,826** rules decisions replayed to the same plan | [ACCURACY_REPORT](docs/ACCURACY_REPORT.md) |
| Live Airwallex sandbox (Google Cloud host) | signed webhooks booked once · beneficiary validated and created · current FX rates · refund approved with the owner's second account (not independent review), **one** transfer, SENT → PAID, liability released only at PAID | [INTEGRATION_EVIDENCE](docs/INTEGRATION_EVIDENCE.md) |
| Live hosted link (2 Nov) | a test-card payment of EUR 197 on a Singapore sandbox account was reported paid by Airwallex and booked once; the invoice settled and the bill moved from Escalate to Fund | Live app |
| Live bill payment (2 Nov) | Airwallex accepted a EUR 100 transfer, moved by its sandbox simulation through SENT to PAID; the bill closed and one journal entry reduced cash only at PAID. Proposer and approver were two accounts of the same owner, so this tests the control and the bank call, not independent review | Live app |
| Live Claude | text and PDF remittances read by `claude-opus-5-5`; a planted prompt injection was ignored and flagged; nothing applied | [INTEGRATION_EVIDENCE](docs/INTEGRATION_EVIDENCE.md) |
| Release (30 Oct) | CI 5/5 jobs · public smoke 32/32 · data survives restart, VM reboot and redeploy (8/8 each) | [Acceptance report](docs/FULL_APPLICATION_ACCEPTANCE_REPORT.md) |
| Tests (4 Nov) | backend **544** passed, 2 skipped on Windows (a POSIX-only test and the Unix-socket test, which run on Linux) · browser **27/27** on Microsoft Edge, including the whole judge path and the Show me tour at phone width (375 px). GitHub Actions has been blocked by an account billing hold since 3 Nov, so these deploys were checked by two separate local runs, not CI, and the PostgreSQL suite has not run since CI run #163 | [Acceptance report](docs/FULL_APPLICATION_ACCEPTANCE_REPORT.md) |

What is **not** measured yet: real customers' payment mix, real time saved (the hours above rest on an assumed 5 minutes per payment), how often real payer agents answer, adoption. Those need a pilot.

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
| Proposer ≠ approver, and when the agent proposed a refund, approver ≠ sender | one person moving money alone |
| One live refund per deposit, stable request ids, lookup before any retry | paying twice after a timeout |
| SENT keeps the liability; only PAID releases it | treating an unsettled transfer as done |
| Pause stops every money-out action; matching continues | runaway actions during an incident |
| Claude output is advisory and schema-validated; it can never authorise money | AI moving money |
| Remittance text is data: emails that say "ignore your instructions", "refund 9,999 to this account" or contain a fake tool call change no plan, approval or operation (tested offline and with a model that obeys the email) | prompt injection |
| An approval not sent within 72 hours goes back to the approvers | stale approvals sent later |
| Optional separate sending service: the Airwallex keys live only in a separate process; the app cannot read them. The app asks it by id only, and it re-checks the approval, expiry, pause, two people and the duplicate lock itself. A compromised app could still request a send that its own database says was approved, or add a payout beneficiary. Owner-run switch: `harden.sh sender` ([SERVER_STEPS](docs/SERVER_STEPS.md) step 7) | an app bug or a leaked app process reading the bank keys |

<details>
<summary><b>Roles</b></summary>

| | Viewer | Operator | Owner |
|:--|:--:|:--:|:--:|
| Read everything, export evidence | ✓ | ✓ | ✓ |
| Record/import payments, customers, invoices, resolve, ask agents, read remittances, propose returns | | ✓ | ✓ |
| Approve/reject (not own proposals), send (not an agent-proposed refund you approved), quotes, conversions, pause | | ✓ | ✓ |
| Resume, policy, team, settings, sandbox tools, opening balances | | | ✓ |

Every rule is enforced by the API; the UI only hides what you cannot do.
</details>

<details>
<summary><b>Security posture</b></summary>

- scrypt password hashes; 12+ characters with upper, lower and a digit; login errors never reveal whether an account exists; 5 failures per email or IP in 15 minutes → 429.
- Session cookie HttpOnly, Secure, SameSite=Strict, Path=/api; only its SHA-256 is stored; 2 h idle and 12 h absolute expiry; logout and password change revoke server-side.
- CSRF token on every mutation plus Origin allow-list; forged `X-Forwarded-For` cannot change the throttling identity.
- HSTS, strict CSP, `X-Frame-Options: DENY`, `nosniff`; only ports 22/80/443 reachable.
- Airwallex, Anthropic and Google secrets are server environment variables only (with the sending service on, the Airwallex keys are in a root-only file that only that service's process receives); webhook secrets are write-only; nothing secret in the browser bundle, Git, logs or exports.
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
python3 -m venv backend/.venv && backend/.venv/bin/pip install --require-hashes -r backend/requirements-lock.txt
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
| Judges | [JUDGE_QUICKSTART](docs/JUDGE_QUICKSTART.md) · [JUDGE_QA](docs/JUDGE_QA.md) · [DEMO_SCRIPT](docs/DEMO_SCRIPT.md) |
| Evidence | [INTEGRATION_EVIDENCE](docs/INTEGRATION_EVIDENCE.md) · [EVALUATION](docs/EVALUATION.md) · [ACCURACY_REPORT](docs/ACCURACY_REPORT.md) · [MEASURED_VALUE](docs/MEASURED_VALUE.md) |
| Payer agents | [PAYER_AGENT_SPEC](docs/PAYER_AGENT_SPEC.md) · [JSON schema](docs/schemas/explain_payment.v1.schema.json) · [test vector](docs/schemas/explain_payment.v1.example.json) · [reference agent](tools/payer_agent/agent.py) |
| Acceptance | [FULL_APPLICATION_ACCEPTANCE_REPORT](docs/FULL_APPLICATION_ACCEPTANCE_REPORT.md) · [HACKATHON_REQUIREMENTS_MATRIX](docs/HACKATHON_REQUIREMENTS_MATRIX.md) |
| Operations | [DEPLOYMENT](docs/DEPLOYMENT.md) · [DEPLOYMENT_HANDOFF](docs/DEPLOYMENT_HANDOFF.md) |
| Origin | [Accepted proposal](docs/original-proposal.txt) · [SUBMISSION_DRAFT](docs/SUBMISSION_DRAFT.md) |

## ⚠️ Honest limits

- Payer agents are simulations: real MCP and signatures, but answers come from a fixed table and keys sit on this server. Real customers' agents would register their own keys at onboarding. Check 3 tests plausibility against your records; it cannot tell a real advance from a false one that fits.
- Airwallex hosted payment links depend on the account's region. A Singapore sandbox account created a real hosted link on 2 Nov and it was paid with a test card; Ledgerline asks Airwallex every two minutes rather than using link webhooks, and settlement timing is not tracked. The earlier account was refused with `configuration_error`, and there Ledgerline keeps a labelled draft and never invents a URL.
- Airwallex's dashboard replay did not produce a second delivery, so duplicate rejection is proven by tests.
- One VM, backups on the same disk, Free Trial credit until 28 Jan 2027; no email delivery, password reset, SSO/MFA or billing.
- The separate sending service ships switched off; the owner turns it on with server step 7. A compromised app could still request a send that its own database says was approved. Its Unix-socket test runs on Linux only and has not run while CI is blocked; on Windows it is tested over a loopback connection.

<p align="center"><sub>Built for the Airwallex Agentic Banking Hackathon · sandbox and synthetic data only · no real money</sub></p>
