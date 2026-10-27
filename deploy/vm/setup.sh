#!/usr/bin/env bash
# One-time (and re-runnable) setup of the Ledgerline API on a free Ubuntu VM, e.g. Oracle Cloud Always Free.
#
#   sudo bash setup.sh <public-hostname> <frontend-origin> [git-ref]
#   sudo bash setup.sh 203-0-113-7.sslip.io https://ledgerline.vercel.app main
#
# Result: Ledgerline runs as a systemd service on 127.0.0.1:8000 as an unprivileged user, Caddy serves it on
# https://<public-hostname> with an automatic Let's Encrypt certificate, and all data (control database,
# organization databases, payer-agent signing keys) lives in /var/lib/ledgerline on the VM's persistent boot volume.
# No secrets are written by this script; optional API keys go into /etc/ledgerline/ledgerline.env by hand.
set -euo pipefail

HOST="${1:?public hostname, e.g. 203-0-113-7.sslip.io}"
FRONTEND_ORIGIN="${2:?frontend origin, e.g. https://ledgerline.vercel.app}"
REF="${3:-main}"
REPO="https://github.com/Lingu17/ledgerline.git"
APP=/opt/ledgerline
DATA=/var/lib/ledgerline
ENV_FILE=/etc/ledgerline/ledgerline.env
PY=3.14.8

[[ $EUID -eq 0 ]] || { echo "run with sudo"; exit 1; }
export DEBIAN_FRONTEND=noninteractive

echo "== packages"
apt-get update -q
apt-get install -y -q git curl ca-certificates debian-keyring debian-archive-keyring apt-transport-https gnupg sqlite3 iptables-persistent
if ! command -v caddy >/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -q && apt-get install -y -q caddy
fi

echo "== swap (1 GB VMs need it while installing wheels)"
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 1G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  grep -q /swapfile /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "== firewall: allow HTTP/HTTPS (Oracle images reject them by default)"
for port in 80 443; do
  iptables -C INPUT -p tcp --dport $port -j ACCEPT 2>/dev/null || iptables -I INPUT 5 -p tcp --dport $port -j ACCEPT
done
netfilter-persistent save >/dev/null

echo "== user, code, Python $PY"
id ledgerline >/dev/null 2>&1 || useradd --system --home "$APP" --shell /usr/sbin/nologin ledgerline
install -d -o ledgerline -g ledgerline -m 700 "$DATA"
install -d -o ledgerline -g ledgerline "$APP"
if [[ -d $APP/src/.git ]]; then
  sudo -u ledgerline git -C "$APP/src" fetch -q origin && sudo -u ledgerline git -C "$APP/src" checkout -q "$REF" && sudo -u ledgerline git -C "$APP/src" reset -q --hard "origin/$REF" 2>/dev/null || sudo -u ledgerline git -C "$APP/src" reset -q --hard "$REF"
else
  sudo -u ledgerline git clone -q "$REPO" "$APP/src" && sudo -u ledgerline git -C "$APP/src" checkout -q "$REF"
fi
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh
sudo -u ledgerline env UV_PYTHON_INSTALL_DIR="$APP/python" uv python install "$PY"
sudo -u ledgerline env UV_PYTHON_INSTALL_DIR="$APP/python" uv venv -q --allow-existing --python "$PY" "$APP/venv"
sudo -u ledgerline env VIRTUAL_ENV="$APP/venv" uv pip install -q -r "$APP/src/backend/requirements-lock.txt"

echo "== configuration ($ENV_FILE)"
install -d -m 750 -o root -g ledgerline /etc/ledgerline
if [[ ! -f $ENV_FILE ]]; then
  cat > "$ENV_FILE" <<EOF
LEDGERLINE_HOST=127.0.0.1
LEDGERLINE_PORT=8000
LEDGERLINE_DATA_DIR=$DATA
# The boot volume of a VM is persistent block storage; the guard checks the data dir is on it.
LEDGERLINE_REQUIRE_PERSISTENT_MOUNT=/
LEDGERLINE_COOKIE_SECURE=1
# Browser -> Vercel edge -> Caddy -> app
LEDGERLINE_TRUSTED_PROXY_HOPS=2
LEDGERLINE_ALLOWED_ORIGINS=$FRONTEND_ORIGIN,https://$HOST
LEDGERLINE_PUBLIC_URL=$FRONTEND_ORIGIN
LEDGERLINE_LOG_LEVEL=INFO
LEDGERLINE_ALLOW_SIGNUP=1
# Optional, server-side only. Leave empty until you have real credentials.
AIRWALLEX_CLIENT_ID=
AIRWALLEX_API_KEY=
ANTHROPIC_API_KEY=
EOF
fi
chown root:ledgerline "$ENV_FILE" && chmod 640 "$ENV_FILE"

echo "== services"
install -m 644 "$APP/src/deploy/vm/ledgerline.service" /etc/systemd/system/ledgerline.service
install -m 644 "$APP/src/deploy/vm/ledgerline-backup.service" /etc/systemd/system/ledgerline-backup.service
install -m 644 "$APP/src/deploy/vm/ledgerline-backup.timer" /etc/systemd/system/ledgerline-backup.timer
sed "s/__HOST__/$HOST/" "$APP/src/deploy/vm/Caddyfile" > /etc/caddy/Caddyfile
systemctl daemon-reload
systemctl enable --now ledgerline.service ledgerline-backup.timer
systemctl restart ledgerline.service
systemctl reload caddy || systemctl restart caddy

echo "== health"
for i in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8000/api/health; then echo; break; fi; sleep 2
done
echo "Done. Public API: https://$HOST/api/health (the certificate is issued on first request)."
