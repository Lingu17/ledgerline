#!/usr/bin/env bash
# Recovery drill on a FRESH, TEMPORARY VM (never the live one), run by the owner:
#   sudo bash restore_drill.sh <ledgerline.bundle> <backup .tar.gz.enc> <backup key file> [ref]
# Installs Ledgerline from the git bundle exactly as setup.sh does, restores the off-server backup into its data
# directory, starts it, checks health and that every organization's books balance and audit chain verifies, and
# prints the minutes taken. docs/SERVER_STEPS.md step 6 creates and deletes the VM around it.
set -euo pipefail
BUNDLE="$(realpath "${1:?git bundle}")"; BLOB="$(realpath "${2:?backup .tar.gz.enc}")"; KEY="$(realpath "${3:?backup key file}")"; REF="${4:-main}"
[[ $EUID -eq 0 ]] || { echo "run with sudo" >&2; exit 2; }
[[ -d /var/lib/ledgerline/orgs ]] && { echo "STOP: this machine already has Ledgerline data; use a fresh VM" >&2; exit 2; }
START=$(date +%s)
IP=$(curl -s -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip)
HOST="${IP//./-}.sslip.io"
cp "$BUNDLE" /srv/ledgerline.bundle
SETUP=$(mktemp -d); git clone -q /srv/ledgerline.bundle "$SETUP/src" && git -C "$SETUP/src" checkout -q "$REF"
echo "== install from the bundle as $HOST (local only)"
LEDGERLINE_LOCAL_ONLY=1 LEDGERLINE_REPO=/srv/ledgerline.bundle bash "$SETUP/src/deploy/vm/setup.sh" "$HOST" self "$REF"
rm -rf "$SETUP"
systemctl is-enabled ledgerline-backup.timer >/dev/null 2>&1 && { echo "STOP: backups are enabled on the drill VM" >&2; exit 1; }
grep -q "^LEDGERLINE_WATCH_SECONDS=0" /etc/ledgerline/ledgerline.env || { echo "STOP: background checks are on in the drill VM" >&2; exit 1; }
echo "== restore the backup"
systemctl stop ledgerline
NAME="ledgerline/$(basename "$BLOB")"
WORK=$(mktemp -d); cp "$BLOB" "$KEY" "$WORK/"; chown -R ledgerline "$WORK"; chmod 700 "$WORK"   # the service user cannot read a home folder
BLOB="$WORK/$(basename "$BLOB")"; KEY="$WORK/$(basename "$KEY")"
sudo -u ledgerline /opt/ledgerline/venv/bin/python - "$BLOB" "$KEY" "$NAME" <<'PY'
import io, shutil, sys, tarfile, tempfile
from pathlib import Path
sys.path.insert(0, "/opt/ledgerline/src/deploy/vm")
from backup import decrypt, read_key
blob, key, name = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
plain = decrypt(blob.read_bytes(), read_key(key), name)
data = Path("/var/lib/ledgerline")
with tempfile.TemporaryDirectory(dir=data) as tmp:
    with tarfile.open(fileobj=io.BytesIO(plain), mode="r:gz") as tar:
        tar.extractall(tmp, filter="data")
    snap = next(Path(tmp).iterdir())
    for item in snap.iterdir():
        dest = data / item.name
        if dest.exists():
            shutil.rmtree(dest) if dest.is_dir() else dest.unlink()
        shutil.move(str(item), dest)
print("restored", sorted(p.name for p in data.iterdir()))
PY
systemctl start ledgerline
for _ in $(seq 1 30); do curl -fsS -o /dev/null http://127.0.0.1:8000/api/health && break; sleep 2; done
curl -fsS http://127.0.0.1:8000/api/health; echo
echo "== verify the restored books"
sudo -u ledgerline env PYTHONPATH=/opt/ledgerline/src/backend /opt/ledgerline/venv/bin/python /opt/ledgerline/src/deploy/vm/restore_check.py "$BLOB" "$KEY" "$NAME"
rm -rf "$WORK"
echo "RECOVERY TIME: $(( ($(date +%s) - START + 59) / 60 )) minutes from a fresh VM to a healthy, verified Ledgerline"
