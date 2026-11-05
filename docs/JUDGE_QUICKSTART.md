# Ledgerline: judge quickstart

**Live app: https://35-207-220-110.sslip.io** (always on; website, API and database on one Google Cloud server). Architecture in 3D: https://35-207-220-110.sslip.io/#/architecture

## Five-minute path

1. Open the link and click **Get started**.
2. Enter any name, organization and email (nothing is emailed) and a password of 12+ characters with upper- and lower-case letters and a digit.
3. Choose **Practice company**. You get your own isolated organization with made-up data; other judges cannot see it.
   Short on time? Press **Show me** at the top right: a seven-stop tour that runs the practice story and explains each screen. It never approves or sends money.
4. **Inbox**: cash by currency and the payments that need a decision. A practice company waits for you, so its unclear payments read **Ready to ask payer**.
5. **Payments → DEP-1005** (Dunmore, looks like a duplicate) → **Ask payer's agent**. The payer's agent answers over MCP with an Ed25519-signed claim; all three checks pass (signature, bound to this deposit and fresh, our records agree) and the plan is revised: the money becomes **advance credit** instead of a refund. No money moved. Press **Replay this decision** on any plan in its history: the same rules run again on the inputs stored with that plan and give the same plan.
6. Still on DEP-1005, press **Explain this decision** under **Why this plan**: a short explanation written only from the plan's facts, citing the payment, the plan and the evidence by id. It is labelled advice; the rules decided.
7. **Payments → DEP-1004** (Fjord) → **Ask payer's agent**. The agent claims another customer's invoice; the signature verifies but the records check fails, so the claim is **rejected** and the case goes to a person with the reason.
8. Optional: on DEP-1004 click **Read remittance…** and paste any remittance email (or upload a PDF). Claude reads it and must answer through a typed tool; the result is stored as **advisory evidence**, checked against the records and used only to fill in **Resolve** for a person to confirm. Each organization has a small daily Claude budget.
9. **Practice steps** runs the rest of the story: the balance request for the short payment, FX for the EUR bill, and the over-limit refund: you approve it (Approvals → Approve…) and a different member sends it. Alone, press **Send as practice teammate**: a labelled stand-in that exists only in practice companies and is refused by the server anywhere else; a real company needs a second real member. The bank then reports SENT (liability kept) and PAID (released).
10. Back on the **Inbox**, **Reconciliation status** shows the scorecard: 6 deposits received, 4 decided with no person, 1 decided by a person, 1 waiting for a person, 0 duplicate payouts.
11. **The agent on its own: Payments → Receive an unclear payment.** A new payment arrives, and the agent asks the payer's agent, checks the signed answer and places the money, with no click. This is how a real company works: it asks the moment a payment arrives (a practice company only waits on DEP-1004 to DEP-1006 so you can watch). The payment is built to match the simulated agent's answers and works once per company; the scorecard then reads 7 received and 5 decided with no person.
12. **Ledger**: deposits = applied + credits + refunds + not yet placed, per currency, to the cent.
    **Activity → Try to tamper** (practice companies only): it changes one recorded amount directly in the database, as an insider could; the hash chain catches it at exactly that row. **Restore the original** puts it back and records that the tamper test was tried.
13. **CEO view**: the whole company on one screen.

**Bring your own payer agent (optional, about 5 minutes).** The agent runs on your machine with its own key; the live site needs a public https address, so a free Cloudflare quick tunnel provides one. From a copy of the repository:

```bash
pip install -r tools/payer_agent/requirements.txt
cloudflared tunnel --url http://localhost:8790        # second window; prints https://<words>.trycloudflare.com
python tools/payer_agent/agent.py --port 8790 --public-host <words>.trycloudflare.com   # prints its public key
```

The agent creates its private key on first run and keeps it in `tools/payer_agent/agent_key.json`; only the public key goes to the site. In your practice company, **Customers → Dunmore → Payer agent…**, enter `https://<words>.trycloudflare.com/mcp` and the printed public key, then **Payments → DEP-1005 → Ask payer's agent**: the answer is labelled **Customer's own agent**. Edit `tools/payer_agent/answers.json` to make it claim something else and watch the checks reject it. Stop the tunnel when you are done. To write your own agent in another language, [PAYER_AGENT_SPEC](PAYER_AGENT_SPEC.md) has the exact question, answer, signing rule and a test vector.

Day-to-day work without the practice steps: create an organization with **My company**, add customers and invoices, record or import payments (CSV), resolve escalations, invite teammates with roles (Team). A refund you propose must be approved by someone else.

## What is real and what is simulated

One table on the README's first screen: [what is real](../README.md#what-is-real-and-what-is-simulated). Also: each organization's data is a SQLite file on the server's persistent disk, backed up nightly, and survives restarts, reboots and redeploys; sign-in is email and password, or Google.

Exact evidence, dates and remaining limitations: [INTEGRATION_EVIDENCE](INTEGRATION_EVIDENCE.md) and [FULL_APPLICATION_ACCEPTANCE_REPORT](FULL_APPLICATION_ACCEPTANCE_REPORT.md).
