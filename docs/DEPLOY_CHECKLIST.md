# Deploy and verify (15 Nov)

Five steps, in order, on the server (`ssh` into the VM). `<commit>` is the full commit hash being deployed.

1. **Deploy:** `sudo bash /opt/ledgerline/src/deploy/vm/update.sh <commit>`
2. **Health:** `curl -s https://35-207-220-110.sslip.io/api/health` shows `"status": "ok"`, the same `commit`, and after a few seconds `"payer_agents_mcp": {"status": "ok", ...}`.
3. **Survives a crash and a reboot:** run the restart checks below; health is `ok` again after each.
4. **Cold start, judge path:** in a private browser window open the site, press **Judge demo — one click**, ask DEP-1005 (becomes credit) and DEP-1004 (rejected), then open `/attacks` (25/25 blocked · $0 moved) and `/evidence`.
5. **Data kept:** before step 1, from a copy of the repository on your computer, run `python scripts/smoke_deploy.py https://35-207-220-110.sslip.io --save state.json` (it creates one test company); after step 3 run it again with `--verify state.json` and it passes.

## Restart checks (the owner runs these)

Crash: kill the process and check systemd brings it back (`Restart=always` in `deploy/vm/ledgerline.service`).

```bash
sudo systemctl kill -s KILL ledgerline
```

```bash
sleep 5 && systemctl is-active ledgerline && curl -s https://35-207-220-110.sslip.io/api/health
```

Reboot: the app and Caddy are enabled, so they start with the machine (the separate sending service is installed only if you turned it on; then add ledgerline-send).

```bash
systemctl is-enabled ledgerline caddy
```

```bash
sudo reboot
```

After about a minute, from your own computer:

```bash
curl -s https://35-207-220-110.sslip.io/api/health
```

Expected each time: `"status": "ok"`, the deployed `commit`, and `payer_agents_mcp` `ok` (it reads `checking` for the first few seconds after a start).
