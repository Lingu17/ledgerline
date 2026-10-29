#!/usr/bin/env bash
# Deploy an exact version: sudo bash /opt/ledgerline/src/deploy/vm/update.sh <commit|tag|branch>
set -euo pipefail
cd / # neutral working directory: tools run as the service user must not read the caller's home
REF="${1:?commit id, tag or branch}"
sudo -u ledgerline bash /opt/ledgerline/src/deploy/vm/checkout.sh /opt/ledgerline/src "$REF"
sudo -u ledgerline env VIRTUAL_ENV=/opt/ledgerline/venv uv pip install -q -r /opt/ledgerline/src/backend/requirements-lock.txt
if [[ $(cat /etc/ledgerline/mode 2>/dev/null) == single ]]; then
  (cd /opt/ledgerline/src/frontend && sudo -u ledgerline env HOME=/opt/ledgerline npm ci --no-audit --no-fund --loglevel=error && sudo -u ledgerline env HOME=/opt/ledgerline npm run build)
fi
systemctl restart ledgerline
for i in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8000/api/health; then echo; exit 0; fi; sleep 2
done
echo "FAILED: not healthy after restart" >&2; journalctl -u ledgerline -n 40 --no-pager >&2; exit 1
