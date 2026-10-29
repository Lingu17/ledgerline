# Submission draft (not submitted)

The owner submits on HackerEarth. Nothing in this repository saves or submits anything there. The Build Phase submission fields were not visible without starting a new submission, so this draft covers the usual items (title, track, description, links, video) and should be pasted into whatever fields the form shows.

**Title:** Ledgerline: incoming-payment reconciliation with verified payer-agent evidence

**Track:** Treasury & Ops (reconciliation and cash placement; closest kit: Adaptive Treasury Controller)

**Parent submission:** the shortlisted idea "Ledgerline: when a payment doesn't match, my agent asks the payer's agent" (Registration & Idea Phase).

**Live app:** https://35-207-220-110.sslip.io (always on). **Architecture:** https://35-207-220-110.sslip.io/#/architecture
**Repository:** https://github.com/Lingu17/ledgerline (private: the owner must grant judges access or decide on visibility before submitting)
**Demo video:** to be recorded by the owner (script: `docs/DEMO_SCRIPT.md`)

**Description**

Small companies that bill in several currencies lose hours every week matching incoming payments by hand: missing or messy references, bank fees, short payments, duplicates and wrong currencies. Ledgerline listens for Airwallex `deposit.settled` webhooks and lets rules in code make the first plan for each deposit. When a payment is unclear it asks the payer's own accounts-payable agent over MCP. The answer is a signed claim, accepted only if the signature matches the customer's registered key, the claim is bound to this exact deposit and still fresh, and our own records agree. If there is no agent, Claude reads the remittance email or PDF through four strictly typed tools; its output is advisory evidence, never an instruction. Then Ledgerline acts: settle the invoice, write off a bank fee within tolerance, request the exact balance, hold an advance as credit, convert only the FX shortfall above the reserve, or propose a refund that a second person must approve.

Money rules live in code. Approvals are bound to the exact scope; refunds use stable request ids, a per-deposit duplicate lock and treat SENT as not final (only PAID releases the liability); a pause switch stops all money-out. Every currency reconciles to the cent: deposits = applied + credits + refunds + unapplied.

It is a working multi-tenant SaaS: sign-up (email or Google), organizations with owner/operator/viewer roles, four-eyes approvals, CSV import, audit export, isolated data per organization. In the reference scenario 4 of 6 deposits settle without a person, one refund needs an approval, one bad agent claim is escalated with its reason, and there are 0 double payments; a randomized harness ran 64,215 checks across 250 synthetic companies with 0 mismatches.

**Honest scope**

- Runs on one Google Cloud VM (SQLite per organization, nightly backups on the same disk), Free Trial credit until 28 Jan 2027.
- Judge organizations use a built-in simulated bank and simulated payer agents (real MCP and Ed25519). The Airwallex sandbox is reserved for the operator's organization.
- Verified against the Airwallex sandbox: signed deposit webhooks, deposits, an EUR→GBP conversion with single-use quotes, an independently approved refund through SENT→PAID, current rates, beneficiary schema and validation, deposit listing as a webhook fallback. Hosted payment links were refused by the sandbox (HTTP 401); Ledgerline keeps a labelled draft instead of inventing a URL. Airwallex's dashboard replay did not produce a second delivery, so replay protection is shown by tests.
- Claude (`claude-opus-5-5`) was exercised live and returned a schema-valid proposal stored as advisory evidence.
- Full evidence: `docs/INTEGRATION_EVIDENCE.md`; acceptance matrix: `docs/FULL_APPLICATION_ACCEPTANCE_REPORT.md`.
