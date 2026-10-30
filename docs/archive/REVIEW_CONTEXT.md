# Independently checked context (Codex)

27 October 2026: live HackerEarth dashboard shows Ledgerline Published and Shortlisted. Build Phase has zero submissions. Its Create submission form exposes Title, Description, Parent Submission selection and Repository URL, plus Submit / Save as Draft. No submission has been saved or submitted by this build session. User asked for implementation and GitHub update; final hackathon submission remains separate.

Build deadline displayed on challenge: 13 November 2026, 23:59 IST.

Useful official documentation checked:
- https://www.airwallex.com/docs/developer-tools/webhooks/listen-for-webhook-events : x-timestamp is Unix milliseconds. Sign exact timestamp string followed by raw request bytes with HMAC SHA256. Check skew before processing. Dedupe event id.
- https://www.airwallex.com/docs/developer-tools/webhooks/webhooks-overview : duplicates and out-of-order events are possible; retries require HTTP 200 acknowledgement.
- https://www.airwallex.com/docs/api/payments/payment_links : required fields reusable and title; fixed links use amount and currency. Do not claim links are sent merely because created.
- https://www.airwallex.com/docs/api/transactional_fx/conversion : set buy_currency and sell_currency and only one dealt amount, quote details must match. Conversion SCHEDULED is not SETTLED.

Linked builder guide https://airwallexdev.com/guide supports reconciliation under Treasury & Ops and requires changing decisions when evidence changes. It is a guide linked by the event, not official Airwallex API documentation.

GitHub authenticated connector account: Lingu17. Local git credential manager configured. No existing project repo in initial empty target folder.
