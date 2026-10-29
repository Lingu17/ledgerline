# Submission draft (not submitted)

Do not save or submit on HackerEarth from this file automatically; the user submits.

**Title:** Ledgerline: incoming-payment reconciliation with verified payer-agent evidence

**Track:** Treasury & Ops (closest: Adaptive Treasury Controller)

**Parent submission:** the shortlisted idea "Ledgerline: when a payment doesn't match, my agent asks the payer's agent" (Registration & Idea Phase).

**Live app:** https://ledgerline-black-iota.vercel.app
**Repository:** https://github.com/Lingu17/ledgerline (private; owner must arrange judge access or explicitly approve public visibility before submission)

**Description (draft):**
Ledgerline matches incoming payments to invoices across USD, EUR and GBP. When a payment is unclear (no reference, a short payment, an apparent duplicate) it asks the payer's own accounts-payable agent over MCP. The answer is a signed claim, accepted only after three checks: the signature matches the customer's registered key, the claim is bound to this exact payment and not expired, and our own records agree. Only then does it act: post the invoice, hold advance credit, draft a balance-due request, convert only the FX shortfall above reserve, or propose a refund that a person must approve. Money rules live in code; approvals are bound to the exact scope; refunds use stable request ids, a per-deposit duplicate lock and track SENT vs PAID; a pause switch stops all money-out. Every deposit reconciles to the cent: deposits = matched + credits + refunds + unapplied.

It is a working multi-tenant SaaS: sign-up, organizations with owner/operator/viewer roles, four-eyes approvals, CSV import, audit export, and isolated workspaces per organization.

**Honest scope:** this deployment runs on free tiers (Vercel, Render Free, Neon Free PostgreSQL; the first request after idle may fail while waking) with a built-in simulated bank and synthetic data for judge workspaces. Google login and operator-only Airwallex authentication/accounts/balances were exercised. Operator-only sandbox deposits settled and reconciled and a EUR→GBP FX conversion settled on 28 Oct 2026 (`a4c9f2c`); reserves and per-currency ledger balance were preserved. EUR5 refund APR-B40BC448 needs a second real approver; no completed live transfer lifecycle is claimed. The webhook and secret are configured, but signed external delivery remains unverified. Payment-link creation is not yet verified with the scoped key. A real Claude request reached Anthropic and was refused for insufficient account credit; successful extraction remains unverified. Owner-triggered receipt sync polls GET /deposits/{id} for receipts previously created by Ledgerline; this is a bounded polling fallback, not a general GET /deposits discovery feed or background poller. Direct PDF ingestion, beneficiary schema/creation and a GET /fx/rates/current display are not implemented. Refund destinations use existing sandbox beneficiary ids; executable FX quotes remain available. These gaps must be closed or explicitly disclosed before final submission; this draft is not a completion certificate.

29Oct live-state correction: the earlier EUR5 approval APR-B40BC448 is invalidated after an operator credit decision (28Oct18:31UTC); it is no longer pending. A completed live refund needs a new valid case and independent real-member approval. Signed webhook delivery, successful credit-backed Claude extraction and scoped payment-link creation are still not verified at this checkpoint.
