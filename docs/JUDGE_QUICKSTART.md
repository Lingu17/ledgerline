# Ledgerline: judge quickstart

**Live app: https://35-207-220-110.sslip.io** (always on; website, API and database on one Google Cloud server). Architecture in 3D: https://35-207-220-110.sslip.io/#/architecture

## Five-minute path

1. Open the link and click **Get started**.
2. Enter any name, organization and email (nothing is emailed) and a password of 12+ characters with upper- and lower-case letters and a digit. Choose **Practice company**. It waits for you to press **Ask payer's agent** so you can watch; **Payments → Receive an unclear payment** shows the agent acting with no click, as it does in a real company. That payment is built to match the simulated agent's table. You get your own isolated organization; other judges cannot see it.
   Short on time? Press **Show me** at the top right: a seven-stop tour that runs the practice story and explains each screen. It runs practice steps only and never approves or sends money.
3. **Inbox**: cash by currency and the payments that need a decision.
4. **Payments → DEP-1005** (Dunmore, looks like a duplicate) → **Ask payer's agent**. The payer's agent answers over MCP with an Ed25519-signed claim; all three checks pass (signature, bound to this deposit and fresh, our records agree) and the plan is revised: the money becomes **advance credit** instead of a refund. No money moved. Press **Replay this decision** on any plan in its history: the same rules run again on the inputs stored with that plan and give the same plan.
5. **Payments → DEP-1004** (Fjord) → **Ask payer's agent**. The agent claims another customer's invoice; the signature verifies but the records check fails, so the claim is **rejected** and the case goes to a person with the reason.
6. Optional: on DEP-1004 click **Read remittance…** and paste any remittance email (or upload a PDF). Claude reads it and must answer through a typed tool; the result is stored as **advisory evidence** and checked against the records, never applied by itself. Each organization has a small daily Claude budget.
7. **Practice steps** runs the rest of the story: balance request for the short payment, FX for the EUR bill, the over-limit refund: you approve it (Approvals → Approve…) and a different member sends it. Alone, press **Send as practice teammate**: a labelled stand-in that exists only in practice companies and is refused by the server anywhere else; a real company needs a second real member. Then bank SENT (liability kept) then PAID (released), and the scorecard: 6 deposits, 4 decided without a person and 3 of those fully closed, 1 approval, 1 escalation with its reason, 0 double payments, ledger balanced.
8. **Ledger**: deposits = applied + credits + refunds + not yet placed, per currency, to the cent.
   **Activity → Try to tamper** (practice companies only): it changes one recorded amount directly in the database, as an insider could; the hash chain catches it at exactly that row. **Restore the original** puts it back and records that the tamper test was tried.

9. **CEO view**: the whole company on one screen.

**Bring your own payer agent (optional, about 5 minutes).** The agent runs on your machine with its own key; the live site needs a public https address, so a free Cloudflare quick tunnel provides one. From a copy of the repository:

```bash
pip install -r tools/payer_agent/requirements.txt
cloudflared tunnel --url http://localhost:8790        # second window; prints https://<words>.trycloudflare.com
python tools/payer_agent/agent.py --port 8790 --public-host <words>.trycloudflare.com   # prints its public key
```

The agent creates its private key on first run and keeps it in `tools/payer_agent/agent_key.json`; only the public key goes to the site. In your practice company, **Customers → Dunmore → Payer agent…**, enter `https://<words>.trycloudflare.com/mcp` and the printed public key, then **Payments → DEP-1005 → Ask payer's agent**: the answer is labelled **Customer's own agent**. Edit `tools/payer_agent/answers.json` to make it claim something else and watch the checks reject it. Stop the tunnel when you are done. To write your own agent in another language, [PAYER_AGENT_SPEC](PAYER_AGENT_SPEC.md) has the exact question, answer, signing rule and a test vector.

Day-to-day work without the practice steps: create an organization with **My company**, add customers and invoices, record or import payments (CSV), resolve escalations, invite teammates with roles (Team). A refund you propose must be approved by someone else.

## What is real and what is simulated

| Part | Status |
|---|---|
| Matching rules, ledger, approvals, locks, roles, tenant isolation | Real application code |
| Storage | SQLite files per organization on the VM's persistent disk, backed up nightly; survives restarts, reboots and redeploys |
| Sign-in | Email/password, or Google. Apple is not offered |
| Payer agents | Simulated customer agents, real MCP protocol and real Ed25519 signatures |
| Bank in your organization | Built-in **simulated bank**, labelled in the top bar. No real money |
| Airwallex sandbox | A company connects its own sandbox keys under Settings; the server's shared credentials are reserved by an allow-list, so judges never touch them. On this host: signed `deposit.settled` webhooks (HTTP 200, each booked once), current rates, beneficiary validation and creation, and a refund completed SENT→PAID as exactly one Airwallex transfer (30 Oct); it was proposed and approved with two accounts that both belong to the owner, so it shows the control, not independent review. Agent-proposed refunds, and the practice teammate, have run only on the simulated bank. The two-person rule checks accounts, not people: one person with two emails would pass it. Earlier, on the previous host with the same sandbox account: deposits and an FX conversion. See [INTEGRATION_EVIDENCE](INTEGRATION_EVIDENCE.md) |
| Claude remittance reading | Real Claude API (`claude-opus-5-5`) through strict typed tools; advisory only; per-organization daily budget |

Exact evidence, dates and remaining limitations: [INTEGRATION_EVIDENCE](INTEGRATION_EVIDENCE.md) and [FULL_APPLICATION_ACCEPTANCE_REPORT](FULL_APPLICATION_ACCEPTANCE_REPORT.md).
