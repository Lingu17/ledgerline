# Submission draft (not submitted)

Do not save or submit on HackerEarth from this file automatically; the user submits.

**Title:** Ledgerline: incoming-payment reconciliation with verified payer-agent evidence

**Track:** Treasury & Ops (closest: Adaptive Treasury Controller)

**Parent submission:** the shortlisted idea "Ledgerline: when a payment doesn't match, my agent asks the payer's agent" (Registration & Idea Phase).

**Live app:** https://ledgerline-black-iota.vercel.app
**Repository:** https://github.com/Lingu17/ledgerline

**Description (draft):**
Ledgerline matches incoming payments to invoices across USD, EUR and GBP. When a payment is unclear (no reference, a short payment, an apparent duplicate) it asks the payer's own accounts-payable agent over MCP. The answer is a signed claim, accepted only after three checks: the signature matches the customer's registered key, the claim is bound to this exact payment and not expired, and our own records agree. Only then does it act: post the invoice, hold advance credit, draft a balance-due request, convert only the FX shortfall above reserve, or propose a refund that a person must approve. Money rules live in code; approvals are bound to the exact scope; refunds use stable request ids, a per-deposit duplicate lock and track SENT vs PAID; a pause switch stops all money-out. Every deposit reconciles to the cent: deposits = matched + credits + refunds + unapplied.

It is a working multi-tenant SaaS: sign-up, organizations with owner/operator/viewer roles, four-eyes approvals, CSV import, audit export, and isolated workspaces per organization.

**Honest scope:** this deployment runs on free tiers (Vercel, Render Free, Neon Free PostgreSQL; the first request after idle can take about a minute) with a built-in simulated bank and synthetic data. The Airwallex sandbox adapter (auth, global accounts, balances, deposits, FX quotes/conversions, transfers, payment links, signed webhooks) is implemented and checked against the official API reference, but has not been run against a live sandbox account. The Claude remittance reader is implemented with strict tools and validated output but has not been called with a live key.
