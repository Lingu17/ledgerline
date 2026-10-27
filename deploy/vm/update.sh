#!/usr/bin/env bash
# Deploy a new version: sudo bash /opt/ledgerline/src/deploy/vm/update.sh [git-ref]
set -euo pipefail
REF="${1:-main}"
sudo -u ledgerline git -C /opt/ledgerline/src fetch -q origin
sudo -u ledgerline git -C /opt/ledgerline/src checkout -q "$REF"
sudo -u ledgerline git -C /opt/ledgerline/src reset -q --hard "origin/$REF"
sudo -u ledgerline env VIRTUAL_ENV=/opt/ledgerline/venv uv pip install -q -r /opt/ledgerline/src/backend/requirements-lock.txt
systemctl restart ledgerline
sleep 3 && curl -fsS http://127.0.0.1:8000/api/health && echo && git -C /opt/ledgerline/src log --oneline -1
