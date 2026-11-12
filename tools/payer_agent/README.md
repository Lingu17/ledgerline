# Reference payer agent

A payer's own accounts-payable agent. It is run by the payer, on the payer's machine, not by Ledgerline. It answers one
question over MCP, "what was this payment for?", with a claim signed by its own Ed25519 key.

- **Its own key.** On first run it creates `agent_key.json` (readable by this user only). The private key never leaves
  this machine; Ledgerline only ever receives the public key, which you paste in when you register the agent.
- **Its own data.** Answers come from `answers.json`, which the payer edits. Nothing is read from Ledgerline.
- **Standalone.** This folder imports nothing from Ledgerline. Copy it anywhere and run it.
- **Only a claim.** Ledgerline still checks the signature against the registered key, that the claim names this exact
  payment (id, amount, currency) and is fresh, and that its own records agree, before any plan changes. It never moves
  money.

## Run it

```bash
python -m venv .venv && . .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python agent.py --port 8790                          # prints the public key and key id, then serves /mcp
```

Other options: `--answers <file>`, `--key-file <file>`, `--host 0.0.0.0` (listen beyond this machine),
`--public-host <name>` (the public host name callers use; repeat for several), `--print-key` (print and exit).

Ledgerline only calls agents at a public **https** address, so put the agent behind HTTPS: a Cloudflare quick tunnel
for a test, or Caddy on a small VM. Step by step: [docs/OUTSIDE_AGENT_RUN.md](../../docs/OUTSIDE_AGENT_RUN.md).

## answers.json

A list of answers. Each one is matched to the question by currency and amount (in minor units: 120000 is 1,200.00):

```json
[{ "currency": "USD", "amount_minor": 120000, "invoice_id": "INV-2291", "reason": "advance_payment",
   "note": "Advance for the March platform subscription (our PO 7781)." }]
```

`reason` is one of `invoice_payment`, `advance_payment` or `duplicate_payment`. Change an
answer to claim something false and watch Ledgerline's records check reject it.

The protocol, with a JSON schema and a signed test vector for writing your own agent in any language:
[docs/PAYER_AGENT_SPEC.md](../../docs/PAYER_AGENT_SPEC.md).
