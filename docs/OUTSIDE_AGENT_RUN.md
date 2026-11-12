# Running a payer agent outside Ledgerline, and recording the proof

The built-in payer agents in a practice company are simulated: they answer from a fixed table and their keys sit on the
Ledgerline server. This guide runs the reference agent (`tools/payer_agent`) on a **different machine**, with a key
created there, registers it on the live site, and records the exchange as evidence. The private key never touches the
Ledgerline server; Ledgerline only receives the public key.

What you need: a second machine (your own PC, or a small cloud VM), Python 3.12+, and a browser signed in to the live
site as the Owner of a practice company.

## 1. Start the agent on the second machine

```bash
git clone https://github.com/Lingu17/ledgerline.git
cd ledgerline/tools/payer_agent
python3 -m venv .venv && . .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python agent.py --print-key                             # creates agent_key.json here and prints the public key
```

Keep the printed **public key** and **key id**. `agent_key.json` stays on this machine.

## 2. Give it a public https address (pick one)

**A. Quick test, any machine (free, no account): a Cloudflare quick tunnel**

```bash
cloudflared tunnel --url http://localhost:8790          # prints https://<words>.trycloudflare.com
```

In a second terminal, in `tools/payer_agent`:

```bash
python agent.py --port 8790 --public-host <words>.trycloudflare.com
```

**B. A small cloud VM with its own address (lasts beyond one session)**

On a Linux VM with a public IP (open ports 80 and 443), using Caddy for HTTPS and sslip.io for a name:

```bash
sudo apt-get update && sudo apt-get install -y python3-venv caddy
# after step 1 on the VM:
echo "<VM-IP-with-dashes>.sslip.io {
  reverse_proxy 127.0.0.1:8790
}" | sudo tee /etc/caddy/Caddyfile
sudo systemctl restart caddy
python agent.py --port 8790 --public-host <VM-IP-with-dashes>.sslip.io
```

For example, a VM at 203.0.113.7 is `203-0-113-7.sslip.io`. The agent URL is then `https://203-0-113-7.sslip.io/mcp`.

## 3. Register it on the live site

1. Open https://35-207-220-110.sslip.io, sign in, and switch to a **practice company** you own (or create one:
   your company name at the top left, then **New organization…**, then **Practice company**).
2. **Customers & invoices**, then **Dunmore Analytics LLC**, then **Payer agent…**
3. Agent URL: `https://<your-address>/mcp`. Public key: the one from step 1. **Save.**

The site checks the address is public https and stores only the URL and the public key.

## 4. Trigger a real exchange

1. **Payments**, then **DEP-1005**, then **Ask payer's agent**.
2. Expect: the answer is labelled **Customer's own agent**, all three checks pass, and the plan changes from a held
   refund to **credit**. The agent's terminal shows the request.
3. Optional: edit `answers.json` to claim something false (for example `INV-2253`), ask again on a fresh practice company,
   and watch the records check reject it.

## 5. Record the proof

1. **Customers & invoices**, then **Dunmore Analytics LLC**, then **Payer agent…**, then **Download proof**. This saves
   `outside-agent-run.json` from the audit log: time, payment, agent host, key id, signature result, the three checks,
   and the plan before and after.
2. Replace `docs/evidence/outside-agent-run.json` in the repository with that file and commit it (or send it to the
   maintainer to commit). Check it holds no personal data before committing; it contains only ids, the host name and the
   key id.
3. When it is committed, the evidence page and the "What is real" table are updated to say an outside agent answered.

## Stopping

Stop the agent with Ctrl+C and the tunnel or Caddy. To return Dunmore to the built-in simulated agent: **Payer agent…**,
then **Stop using its own agent**.
