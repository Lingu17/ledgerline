# Submission draft (not submitted)

Updated 29 October 2026: verified runtime `98d6ad4653aa3701b38a81577650377f2ad30792`, CI 40839628066 all five jobs passed. Actual signed Airwallex deposit delivery and fresh EUR5 refund processing→SENT→PAID completed; liability/conservation verified. Payment-link request refused HTTP 401 (honest draft); provider external replay returned success:false. Successful Claude extraction waits for credit (user expects it in one day). Fresh isolated Neon 13/13 passed in 1,629.50s at baseline 6c43626; final-code CI PostgreSQL 17 is primary evidence. Final main-branch deployed SHAs/smoke/restart will be recorded separately after release.


Do not save or submit on HackerEarth from this file automatically; the user submits.

**Title:** Ledgerline: incoming-payment reconciliation with verified payer-agent evidence

**Track:** Treasury & Ops (closest: Adaptive Treasury Controller)

**Parent submission:** the shortlisted idea "Ledgerline: when a payment doesn't match, my agent asks the payer's agent" (Registration & Idea Phase).

**Live app:** https://35-207-220-110.sslip.io
**Repository:** https://github.com/Lingu17/ledgerline (private; owner must arrange judge access or explicitly approve public visibility before submission)

**Description (draft):**
Ledgerline matches incoming payments to invoices across USD, EUR and GBP. When a payment is unclear (no reference, a short payment, an apparent duplicate) it asks the payer's own accounts-payable agent over MCP. The answer is a signed claim, accepted only after three checks: the signature matches the customer's registered key, the claim is bound to this exact payment and not expired, and our own records agree. Only then does it act: post the invoice, hold advance credit, draft a balance-due request, convert only the FX shortfall above reserve, or propose a refund that a person must approve. Money rules live in code; approvals are bound to the exact scope; refunds use stable request ids, a per-deposit duplicate lock and track SENT vs PAID; a pause switch stops all money-out. Every deposit reconciles to the cent: deposits = matched + credits + refunds + unapplied.

It is a working multi-tenant SaaS: sign-up, organizations with owner/operator/viewer roles, four-eyes approvals, CSV import, audit export, and isolated workspaces per organization.

**Honest scope:** this deployment runs on free tiers (Vercel, Render Free, Neon Free PostgreSQL; the first request after idle may fail while waking) with a built-in simulated bank and synthetic data for judge workspaces. Google login and operator-only Airwallex authentication/accounts/balances were exercised. Operator-only sandbox deposits settled and reconciled and a EUR→GBP FX conversion settled on 28 Oct 2026 (`a4c9f2c`); reserves and per-currency ledger balance were preserved. On29 Oct, a fresh independently approved EUR5 refund completed processing→SENT→PAID, with liability retained at SENT and released only at PAID; the old invalidated approval was left untouched. Signed external deposit delivery is verified with a Render HTTP 200 log and a persisted event row; Airwallex refused external replay. The scoped payment-link attempt returned HTTP 401 unauthorized and retained a labelled draft. A real Claude request reached Anthropic and was refused for insufficient account credit; successful extraction remains unverified. Owner-triggered receipt sync polls GET /deposits/{id} for receipts previously created by Ledgerline; this is a bounded polling fallback, not a general GET /deposits discovery feed or background poller. Direct PDF ingestion, beneficiary schema/creation and a GET /fx/rates/current display are not implemented. Refund destinations use existing sandbox beneficiary ids; executable FX quotes remain available. These gaps must be closed or explicitly disclosed before final submission; this draft is not a completion certificate.
