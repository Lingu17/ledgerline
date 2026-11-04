# Payer agent protocol: `explain_payment` v1

How a payer's own accounts-payable agent answers Ledgerline. It is one MCP tool. Ledgerline asks what a payment was for; the agent returns a signed claim or says it does not know. The answer is evidence, never an instruction: Ledgerline checks it three ways, and rules in code decide what happens next. An agent cannot move money, approve anything or change a limit.

- Machine-readable shapes: [schemas/explain_payment.v1.schema.json](schemas/explain_payment.v1.schema.json) (JSON Schema 2020-12)
- Test vector, a real signed answer: [schemas/explain_payment.v1.example.json](schemas/explain_payment.v1.example.json)
- Reference agent, about 120 lines that import nothing from Ledgerline: [tools/payer_agent/agent.py](../tools/payer_agent/agent.py)
- The checks in code: [backend/ledgerline/evidence.py](../backend/ledgerline/evidence.py); the call: [payer_agents/remote.py](../backend/ledgerline/payer_agents/remote.py)

`backend/tests/test_payer_agent_spec.py` keeps this page honest: the schema must list exactly the fields the verifier requires, the test vector must verify, and the reference agent's real answers must fit the schema.

## 1. When Ledgerline asks

Only about a payment the rules could not settle alone and whose plan says *ask the payer's agent* (for example an amount that looks like a second payment of an invoice already paid). Only the customer the payment was matched to is asked, and an answer from anyone else is refused. In a real company the question goes out by itself as soon as the payment arrives; anyone with the operator role can also press **Ask payer's agent**. Practice companies wait for the button so you can watch the plan change.

## 2. Transport

| Item | Rule |
|---|---|
| Protocol | MCP over streamable HTTP. The agent offers a tool named `explain_payment`; Ledgerline lists tools first and stops if it is missing |
| URL | `https://` only, at most 300 characters, no user name, password or fragment. Plain `http://` works only for loopback on a development machine with `LEDGERLINE_PAYER_AGENT_ALLOW_LOOPBACK=1`; the hosted app never sets it |
| Address | Resolved when connecting; every address must be public (no private, loopback, link-local or metadata addresses, including IPv4 hidden in IPv6 forms such as mapped, NAT64, 6to4 and Teredo). Ledgerline connects to the address it checked |
| What is sent | The six question fields below and nothing else: no cookies, no authorization header, no proxy settings, no balances or notes |
| Limits | 5 s to connect, 10 s per read, 25 s per call, 256 KB per response, redirects to another origin not followed. Each company gets 30 s per round for all its customers' agents; the rest wait for the next round |
| Failures | A timeout, refusal or bad response leaves the payment waiting, untouched. After 3 failures in a row an agent is left alone for 10 minutes |

## 3. The question (tool arguments)

| Field | Type | Meaning |
|---|---|---|
| `customer_id` | string | The payer as Ledgerline knows it |
| `deposit_id` | string | The incoming payment |
| `currency` | string | ISO 4217, three capital letters |
| `amount_minor` | integer | Amount in the minor unit (cents for USD) |
| `received_at` | string | When it arrived, ISO 8601 UTC |
| `reference` | string | The bank reference as received; may be empty |

## 4. The answer (tool result)

Return a JSON object, either as MCP structured content or as one text block holding the JSON.

- **Answered:** `{"status": "answered", "envelope": {...}}` with the envelope below.
- **Unknown:** `{"status": "unknown", "customer_id": "...", "detail": "no matching payment in our books"}`.

Anything else (another status, a tool error, a missing envelope) is recorded as a rejected answer with its status quoted, and the payment goes to a person.

The envelope:

| Field | Value |
|---|---|
| `claim` | The object below. Every field is required and no other field is accepted |
| `signature` | Standard base64 of the 64-byte Ed25519 signature over the canonical claim |
| `key_id` | `ed25519:` plus the first 16 hex characters of SHA-256 of the raw 32-byte public key |
| `alg` | `"Ed25519"` (optional) |

The claim:

| Field | Type | Rule |
|---|---|---|
| `schema` | string | `ledgerline.explain_payment.v1` |
| `deposit_id`, `customer_id`, `currency`, `amount_minor` | as in the question | Copied from the question |
| `invoice_id` | string | The seller's invoice the payment relates to |
| `reason` | string | `invoice_payment`, `advance_payment` or `duplicate_payment` |
| `note` | string | Free text for a person. Ledgerline never acts on it and never passes it to Claude |
| `issued_at`, `expires_at` | string | ISO 8601 UTC; `expires_at` after `issued_at` |
| `nonce` | string | Random per answer |

## 5. Signing

The signed bytes are the claim encoded as canonical JSON: keys sorted, no spaces, UTF-8, non-ASCII characters written as themselves, no floats. In Python that is exactly:

```python
json.dumps(claim, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
```

Sign those bytes with the agent's Ed25519 private key. The key is the agent's own: it is created and kept on the payer's side and never sent anywhere. The payer gives the company the public key (base64 of the raw 32 bytes) once, out of band; the company's owner registers it in Ledgerline together with the URL (**Customers →** the customer **→ Payer agent…**). The test vector's `canonical` field shows the exact text signed for its claim, so you can check your encoder byte for byte.

## 6. The three checks

Every answer is checked; all three must pass. Each result, with its reason, is stored with the answer and shown on the payment.

| Check | Passes when | Example failures |
|---|---|---|
| **1. Signature** | The claim speaks for the customer that was asked, `key_id` is that customer's registered key, and the Ed25519 signature verifies over the canonical claim | a claim for another customer; an unregistered or replaced key; one changed character |
| **2. Freshness and binding** | `schema` is v1; `deposit_id`, `currency` and `amount_minor` equal this payment's; not issued more than 60 s in the future; not expired; the validity window is at most 900 s | an answer about another payment; an expired or long-lived answer |
| **3. Our records agree** | The invoice exists, belongs to that customer and is in the payment's currency, something is still unapplied, and the reason fits the books (below) | an invoice of another customer; an "advance" larger than what is left to pay |

What check 3 requires for each reason:

| `reason` | The invoice must be | And |
|---|---|---|
| `invoice_payment` | open | its remaining balance covers the unapplied amount |
| `advance_payment` | scheduled or open | the unapplied amount is at most its remaining balance |
| `duplicate_payment` | fully paid | the unapplied amount is at most the invoice amount |

A verified answer whose exact signed bytes were already used is rejected as a replay. The window (900 s) and skew (60 s) are company policy, adjustable within 60 to 3,600 s and 0 to 300 s.

Check 3 tests plausibility against the company's own books. It cannot tell a true advance from a false one that happens to fit; that is why a refund still needs the limits below.

## 7. What a verified answer can change

| `reason` | New plan |
|---|---|
| `invoice_payment` | Apply the unapplied amount to that invoice |
| `advance_payment` | Drop the proposed refund before any money moves, and hold the amount as customer credit for that invoice |
| `duplicate_payment` | Propose a refund of the unapplied amount, bound to the amount, the destination and this evidence. It goes out automatically only under the company's refund limit; above it one person approves and a different person sends |
| any failed check | Escalate with the failed check's reason, and hold the money as unapplied |

The plan is chosen by code from `reason` and the numbers. The answer's text never reaches a rule, and the *Why this plan* explanation is written only from code-owned fields.

## 8. Running your own agent

```bash
pip install -r tools/payer_agent/requirements.txt
python tools/payer_agent/agent.py --port 8790
```

It prints its public key and URL, creates its key file on first run (readable by its user only), and answers from `answers.json`, which it re-reads on every call. To reach it from the hosted app, put it behind an HTTPS tunnel and pass the tunnel's host name with `--public-host`; [JUDGE_QUICKSTART](JUDGE_QUICKSTART.md) has the steps. An owner can register at most 20 own agents per company; who set or changed a key, and when, is shown on every answer that key signs.

## 9. Versions

The `schema` string names the version. Ledgerline accepts only `ledgerline.explain_payment.v1` and rejects any other value in check 2. A later version would get a new string and live alongside v1.
