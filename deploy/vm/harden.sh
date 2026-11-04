#!/usr/bin/env bash
# Server hardening, one step at a time, run by the owner:  sudo bash /opt/ledgerline/src/deploy/vm/harden.sh <step>
#
#   status          read only: hardening score, file modes, journald use, Ops Agent log rate, SSH settings
#   files           owner-only files: UMask=0077 for the app and the backup, existing databases 600, folders 700
#   systemd         sandbox the app one group of settings at a time; a group that breaks a check is taken back out
#   journald        cap the system journal at 300 MB
#   opsagent-why    read only: the Google Ops Agent's most common log lines in the last hour
#   opsagent-off    stop and disable the Google Ops Agent   (undo: opsagent-on)
#   ssh             PermitRootLogin no, then fail2ban guarding sshd
#   backup BUCKET   encrypted nightly copy to that Cloud Storage bucket, then one run now
#   sender          move the Airwallex keys into a separate sending service the app's user cannot read (undo: sender-off)
#   undo-systemd | undo-files | undo-journald | undo-ssh
#
# After every change to the app's unit: daemon-reload, restart, then checks: active, /api/health answers, a signed-out
# /api/deposits answers 401, and, in the same sandbox, the stdio payer-agent call, Ed25519 and AES-GCM, and an outbound
# HTTPS request. Nothing here prints a secret.
set -Eeuo pipefail

main() {
  [[ $EUID -eq 0 ]] || { echo "run with sudo" >&2; exit 2; }
  SRC=/opt/ledgerline/src
  DROPIN=/etc/systemd/system/ledgerline.service.d
  case "${1:-}" in
    status) status ;;
    files) files ;;
    undo-files) rm -f "$DROPIN/umask.conf"; reload_restart && check_app && echo "umask drop-in removed (file modes left as they are)" ;;
    systemd) harden_systemd ;;
    undo-systemd) rm -f "$DROPIN/hardening.conf"; reload_restart && check_app && echo "hardening drop-in removed" ;;
    journald) journald ;;
    undo-journald) rm -f /etc/systemd/journald.conf.d/ledgerline.conf; systemctl restart systemd-journald; journalctl --disk-usage ;;
    opsagent-why) opsagent_why ;;
    opsagent-off) systemctl disable --now google-cloud-ops-agent.service google-cloud-ops-agent-fluent-bit.service \
                    google-cloud-ops-agent-opentelemetry-collector.service || true
                  systemctl --no-pager --plain list-units --all 'google-cloud-ops-agent*' | head -5 ;;
    opsagent-on) systemctl enable --now google-cloud-ops-agent ;;
    ssh) ssh_step ;;
    undo-ssh) rm -f /etc/ssh/sshd_config.d/10-ledgerline.conf; sshd -t && systemctl reload-or-restart ssh; echo "PermitRootLogin back to the default (fail2ban left running; 'systemctl disable --now fail2ban' to stop it)" ;;
    backup) backup_step "${2:?bucket name}" ;;
    sender) sender_step ;;
    sender-off) sender_off ;;
    *) sed -n '2,16p' "$0"; exit 2 ;;
  esac
}

reload_restart() { systemctl daemon-reload; systemctl restart ledgerline; }

check_app() {
  local ok=1 i
  for i in $(seq 1 30); do curl -fsS -o /dev/null http://127.0.0.1:8000/api/health && break; sleep 2; done
  systemctl is-active --quiet ledgerline || { echo "  CHECK FAILED: service not active"; ok=0; }
  curl -fsS -o /dev/null http://127.0.0.1:8000/api/health || { echo "  CHECK FAILED: /api/health"; ok=0; }
  [[ $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/api/deposits) == 401 ]] || { echo "  CHECK FAILED: signed-out /api/deposits is not 401"; ok=0; }
  sandbox_check || { echo "  CHECK FAILED: payer agent, crypto or outbound HTTPS inside the sandbox"; ok=0; }
  (( ok ))
}

# The app's own sandbox settings (unit file plus drop-ins), applied to a one-off process, so the checks run under
# exactly the restrictions the app has.
sandbox_props() {
  local d
  for d in NoNewPrivileges ProtectSystem ProtectHome PrivateTmp ReadWritePaths ReadOnlyPaths UMask CapabilityBoundingSet \
           AmbientCapabilities PrivateDevices ProtectKernelTunables ProtectKernelModules ProtectKernelLogs ProtectControlGroups \
           ProtectClock ProtectHostname RestrictAddressFamilies RestrictNamespaces LockPersonality RestrictRealtime \
           RestrictSUIDSGID SystemCallArchitectures SystemCallFilter; do
    { grep -h "^$d=" /etc/systemd/system/ledgerline.service "$DROPIN"/*.conf 2>/dev/null || true; } | tail -1 | sed 's/^/-p\n/'
  done
}

sandbox_check() {
  local -a props; mapfile -t props < <(sandbox_props)
  local out
  out=$(systemd-run --quiet --wait --collect --pipe --uid=ledgerline --gid=ledgerline -p WorkingDirectory="$SRC/backend" "${props[@]}" \
    /opt/ledgerline/venv/bin/python - 2>&1 <<'PY'
import os, sys, urllib.request, anyio
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from mcp import Client, StdioServerParameters
from mcp.client.stdio import get_default_environment
k = Ed25519PrivateKey.generate(); k.public_key().verify(k.sign(b"x"), b"x")
AESGCM(os.urandom(32)).encrypt(os.urandom(12), b"x", None)
p = StdioServerParameters(command=sys.executable, args=["-m", "ledgerline.payer_agents.server"], cwd=os.getcwd(),
                          env={**get_default_environment(), "LEDGERLINE_AGENT_KEYS": "{}"})
async def ask():
    async with Client(p) as c:
        r = await c.call_tool("explain_payment", {"customer_id": "X", "deposit_id": "D", "currency": "USD", "amount_minor": 1,
                                                  "received_at": "2026-01-01T00:00:00Z"})
        return str(r.structured_content)
assert "no_agent" in anyio.run(ask)
assert urllib.request.urlopen("https://www.googleapis.com/generate_204", timeout=10).status == 204
print("SANDBOX OK")
PY
) || true
  grep -q "SANDBOX OK" <<<"$out" && return 0
  echo "  sandbox check output:"; tail -5 <<<"$out" | sed 's/^/    /'
  return 1
}

status() {
  echo "== hardening score"; systemd-analyze security ledgerline 2>/dev/null | tail -1
  echo "== drop-ins"; ls "$DROPIN" 2>/dev/null || echo "none"
  echo "== files readable by others under /var/lib/ledgerline: $(find /var/lib/ledgerline -type f -perm /004 | wc -l); by group: $(find /var/lib/ledgerline -type f -perm /040 | wc -l) (expected only while the sending service is on)"
  echo "== sending service: $(systemctl is-active ledgerline-send 2>/dev/null || true)"
  echo "== journald"; journalctl --disk-usage; cat /etc/systemd/journald.conf.d/ledgerline.conf 2>/dev/null || echo "no cap set"
  echo "== Ops Agent log lines in the last hour: $(journalctl -u 'google-cloud-ops-agent*' --since -1h -q --no-pager | wc -l)"
  echo "== ssh"; sshd -T 2>/dev/null | grep -E "^(permitrootlogin|passwordauthentication) "; systemctl is-active fail2ban 2>/dev/null || true
  echo "== backup"; [[ -f /etc/ledgerline/backup.env ]] && grep -o "^LEDGERLINE_BACKUP_BUCKET=.*" /etc/ledgerline/backup.env || echo "no off-server copy configured"
  local last=/var/lib/ledgerline/backups/last_offsite
  if [[ -f $last ]]; then
    local age=$(( ($(date +%s) - $(date -d "$(cut -d' ' -f1 "$last")" +%s)) / 3600 ))
    echo "last off-server copy: $(cat "$last") (${age} h ago)"; (( age <= 36 )) || echo "WARNING: no off-server copy for over 36 hours"
  else
    echo "no off-server copy has been made yet"
  fi
  systemctl is-failed --quiet ledgerline-backup.service && echo "WARNING: the last backup run failed: journalctl -u ledgerline-backup -n 20"
  return 0
}

files() {
  if systemctl is-active --quiet ledgerline-send; then
    echo "the sending service is on; owner-only files would lock it out of the databases. Run harden.sh sender-off first" >&2; exit 1
  fi
  mkdir -p "$DROPIN"
  printf '[Service]\nUMask=0077\n' > "$DROPIN/umask.conf"
  install -m 644 "$SRC/deploy/vm/ledgerline-backup.service" /etc/systemd/system/ledgerline-backup.service
  reload_restart
  if ! check_app; then rm -f "$DROPIN/umask.conf"; reload_restart; check_app || true; echo "files: reverted, app checks failed with UMask"; exit 1; fi
  find /var/lib/ledgerline -type f -exec chmod 600 {} +
  find /var/lib/ledgerline -type d -exec chmod 700 {} +
  check_app && echo "files: done. Readable by group or others now: $(find /var/lib/ledgerline -perm /044 | wc -l). Undo: harden.sh undo-files"
}

harden_systemd() {
  local before; before=$(systemd-analyze security ledgerline 2>/dev/null | tail -1)
  mkdir -p "$DROPIN"
  local -a groups=(
    "CapabilityBoundingSet=|AmbientCapabilities="
    "PrivateDevices=yes|ProtectKernelTunables=yes|ProtectKernelModules=yes|ProtectKernelLogs=yes|ProtectControlGroups=yes|ProtectClock=yes|ProtectHostname=yes"
    "RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX"
    "RestrictNamespaces=yes|LockPersonality=yes|RestrictRealtime=yes|RestrictSUIDSGID=yes"
    "SystemCallArchitectures=native|SystemCallFilter=@system-service"
  )
  local kept="" g
  for g in "${groups[@]}"; do
    printf '[Service]\n%s%s\n' "$kept" "${g//|/$'\n'}" > "$DROPIN/hardening.conf"
    reload_restart
    if check_app; then kept+="${g//|/$'\n'}"$'\n'; echo "kept:     ${g//|/, }"
    else echo "REMOVED:  ${g//|/, } (a check failed with it)"; fi
  done
  printf '[Service]\n%s' "$kept" > "$DROPIN/hardening.conf"
  reload_restart
  check_app || { echo "the kept settings failed together; run: harden.sh undo-systemd"; exit 1; }
  echo "waiting 130 s for a background check round..."; local since; since=$(date '+%Y-%m-%d %H:%M:%S'); sleep 130
  echo "service errors since the last restart: $(journalctl -u ledgerline --since "$since" -q --no-pager | grep -cE 'Traceback|ERROR|watcher')"
  echo "score before: $before"; echo "score after:  $(systemd-analyze security ledgerline 2>/dev/null | tail -1)"
  echo "MemoryDenyWriteExecute is deliberately not set. Undo: harden.sh undo-systemd"
}

journald() {
  mkdir -p /etc/systemd/journald.conf.d
  printf '[Journal]\nSystemMaxUse=300M\n' > /etc/systemd/journald.conf.d/ledgerline.conf
  systemctl restart systemd-journald
  journalctl --disk-usage; echo "Undo: harden.sh undo-journald"
}

opsagent_why() {
  echo "lines in the last hour: $(journalctl -u 'google-cloud-ops-agent*' --since -1h -q --no-pager | wc -l)"
  journalctl -u 'google-cloud-ops-agent*' --since -1h -q --no-pager -o cat | cut -c1-150 | sed -E 's/[0-9]{2,}/N/g' | sort | uniq -c | sort -rn | head -5
}

ssh_step() {
  printf 'PermitRootLogin no\n' > /etc/ssh/sshd_config.d/10-ledgerline.conf
  if ! sshd -t; then rm -f /etc/ssh/sshd_config.d/10-ledgerline.conf; echo "sshd config test failed; nothing changed"; exit 1; fi
  systemctl reload-or-restart ssh  # existing sessions stay open
  sshd -T | grep -E "^permitrootlogin "
  DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=180 install -y -q fail2ban >/dev/null
  printf '[sshd]\nenabled = true\nbackend = systemd\nmaxretry = 5\nfindtime = 10m\nbantime = 1h\n' > /etc/fail2ban/jail.d/ledgerline-sshd.local
  systemctl enable --now fail2ban; sleep 2; fail2ban-client status sshd | head -4
  echo "Keep this window open. Open a NEW SSH connection now; close this one only after that works. Undo: harden.sh undo-ssh"
}

backup_step() {
  local bucket="$1"
  [[ "$bucket" =~ ^[a-z0-9][a-z0-9._-]{1,61}[a-z0-9]$ ]] || { echo "not a bucket name: $bucket" >&2; exit 2; }
  if [[ ! -f /etc/ledgerline/backup.key ]]; then
    (umask 077; head -c 32 /dev/urandom | base64 > /etc/ledgerline/backup.key)
    echo "created /etc/ledgerline/backup.key"
  fi
  chown ledgerline:ledgerline /etc/ledgerline/backup.key; chmod 600 /etc/ledgerline/backup.key
  printf 'LEDGERLINE_BACKUP_BUCKET=%s\nLEDGERLINE_BACKUP_KEY_FILE=/etc/ledgerline/backup.key\n' "$bucket" > /etc/ledgerline/backup.env
  chown root:ledgerline /etc/ledgerline/backup.env; chmod 640 /etc/ledgerline/backup.env
  install -m 644 "$SRC/deploy/vm/ledgerline-backup.service" /etc/systemd/system/ledgerline-backup.service
  systemctl daemon-reload
  local started; started=$(date '+%Y-%m-%d %H:%M:%S')
  if ! systemctl start ledgerline-backup.service; then
    journalctl -u ledgerline-backup --since "$started" -q --no-pager -o cat | tail -8
    echo "FAILED: the backup or its upload did not complete (see above). The bucket name, the VM service account and"
    echo "its role on the bucket are the usual causes. Undo: sudo rm /etc/ledgerline/backup.env"
    exit 1
  fi
  journalctl -u ledgerline-backup --since "$started" -q --no-pager -o cat | tail -3
  echo "Store two keys in your password manager now, from your own SSH window (never paste them into a chat):"
  echo "  sudo cat /etc/ledgerline/backup.key        # decrypts the off-server copies"
  echo "  sudo cat /var/lib/ledgerline/connections.key   # decrypts saved Airwallex keys"
  echo "Undo: sudo rm /etc/ledgerline/backup.env (the next backup is local only again)"
}

ENVF=/etc/ledgerline/ledgerline.env
SENV=/etc/ledgerline/sender.env
KEY_APP=/var/lib/ledgerline/connections.key
KEY_SEND=/var/lib/ledgerline-send/connections.key

# The sending service (python -m ledgerline.sender) runs as its own user. It alone reads the server's Airwallex keys
# (root-only sender.env, read by systemd) and the key that seals companies' own credentials. The app asks it over a
# Unix socket that only the app's group can open, by id only. The two share the companies' databases through group
# ledgerline, so files become 660 and folders 770 (nobody else, as before); the backups folder stays the app's alone.
sender_step() {
  if systemctl is-active --quiet ledgerline-send; then echo "the sending service is already on"; check_sender; return; fi
  if grep -qE '^LEDGERLINE_DATABASE_URL=.+' "$ENVF"; then
    echo "the sending service separates keys only with local storage (SQLite); this server uses PostgreSQL, so nothing was changed" >&2; exit 2
  fi
  # Any failure part-way turns it back off (sender_off), so the app never restarts without its keys.
  trap 'trap - ERR; echo "sender: a step failed; turning it back off" >&2; sender_off; exit 1' ERR
  id ledgerline-send >/dev/null 2>&1 || useradd --system --gid ledgerline --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin ledgerline-send
  install -d -o ledgerline-send -g ledgerline -m 700 /var/lib/ledgerline-send
  local keys
  keys=$(grep -E '^(AIRWALLEX_CLIENT_ID|AIRWALLEX_API_KEY)=' "$ENVF" || true)
  if [[ -z $keys && -f $SENV ]]; then keys=$(grep -E '^(AIRWALLEX_CLIENT_ID|AIRWALLEX_API_KEY)=' "$SENV" || true); fi  # an earlier half-done run
  (umask 077
   { if [[ -n $keys ]]; then printf '%s\n' "$keys"; fi
     echo "LEDGERLINE_CONNECTIONS_KEY_PATH=$KEY_SEND"
     echo "LEDGERLINE_SENDER_PEER_UID=$(id -u ledgerline)"; } > "$SENV.new")
  chown root:root "$SENV.new"; chmod 600 "$SENV.new"; mv "$SENV.new" "$SENV"
  sed -i -E '/^(AIRWALLEX_CLIENT_ID|AIRWALLEX_API_KEY|LEDGERLINE_SENDER_SOCKET)=/d' "$ENVF"
  echo "LEDGERLINE_SENDER_SOCKET=unix:/run/ledgerline-send/send.sock" >> "$ENVF"
  chown root:ledgerline "$ENVF"; chmod 640 "$ENVF"
  if [[ -f $KEY_APP && ! -f $KEY_SEND ]]; then mv "$KEY_APP" "$KEY_SEND"; fi
  if [[ -f $KEY_SEND ]]; then chown ledgerline-send:ledgerline "$KEY_SEND"; chmod 600 "$KEY_SEND"; fi
  mkdir -p "$DROPIN"; printf '[Service]\nUMask=0007\n' > "$DROPIN/umask.conf"
  find /var/lib/ledgerline -path /var/lib/ledgerline/backups -prune -o -type d -exec chmod 770 {} +
  find /var/lib/ledgerline -path /var/lib/ledgerline/backups -prune -o -type f -exec chmod 660 {} +
  install -m 644 "$SRC/deploy/vm/ledgerline-send.service" /etc/systemd/system/ledgerline-send.service
  systemctl daemon-reload
  systemctl enable --now ledgerline-send
  systemctl restart ledgerline
  trap - ERR
  if ! check_app || ! check_sender; then echo "sender: a check failed; turning it back off"; sender_off; exit 1; fi
  echo "sender: on. The Airwallex keys and connections.key are readable only by the sending service and root."
  echo "Store the moved key in your password manager if you have not: sudo cat $KEY_SEND   (never paste it into a chat)"
  echo "Before deploying a commit older than the sending service, run: harden.sh sender-off. Undo: harden.sh sender-off"
}

check_sender() {
  local ok=1 out
  for _ in $(seq 1 15); do [[ -S /run/ledgerline-send/send.sock ]] && break; sleep 1; done
  systemctl is-active --quiet ledgerline-send || { echo "  CHECK FAILED: ledgerline-send is not active"; ok=0; }
  if sudo -u ledgerline test -r "$SENV"; then echo "  CHECK FAILED: the app's user can read $SENV"; ok=0; fi
  if sudo -u ledgerline test -r "$KEY_SEND"; then echo "  CHECK FAILED: the app's user can read $KEY_SEND"; ok=0; fi
  if grep -qE '^AIRWALLEX_API_KEY=' "$ENVF"; then echo "  CHECK FAILED: the app's settings still hold an Airwallex key"; ok=0; fi
  out=$(cd "$SRC/backend" && sudo -u ledgerline /opt/ledgerline/venv/bin/python -c 'from ledgerline.sender import SenderClient
r = SenderClient("unix:/run/ledgerline-send/send.sock", timeout=20).call("server_readiness", "")
print("SENDER OK" if isinstance(r, dict) else "SENDER BAD")' 2>&1) || true
  grep -q "SENDER OK" <<<"$out" || { echo "  CHECK FAILED: the app's user could not ask the sending service: $(tail -1 <<<"$out" | cut -c1-200)"; ok=0; }
  (( ok ))
}

# Safe from any half-done state: never duplicates a key line, never overwrites a key file, never prints a secret.
sender_off() {
  systemctl disable --now ledgerline-send 2>/dev/null || true
  sed -i -E '/^LEDGERLINE_SENDER_SOCKET=/d' "$ENVF" || true
  if [[ -f $SENV ]]; then
    local line
    while IFS= read -r line; do
      grep -q "^${line%%=*}=" "$ENVF" || printf '%s\n' "$line" >> "$ENVF"
    done < <(grep -E '^(AIRWALLEX_CLIENT_ID|AIRWALLEX_API_KEY)=' "$SENV" || true)
    rm -f "$SENV"
  fi
  chown root:ledgerline "$ENVF" || true; chmod 640 "$ENVF" || true
  if [[ -f $KEY_SEND && ! -f $KEY_APP ]]; then mv "$KEY_SEND" "$KEY_APP"
  elif [[ -f $KEY_SEND ]]; then echo "WARNING: both $KEY_SEND and $KEY_APP exist; left both in place, compare them by hand" >&2; fi
  if [[ -f $KEY_APP ]]; then chown ledgerline:ledgerline "$KEY_APP" || true; chmod 600 "$KEY_APP" || true; fi
  rmdir /var/lib/ledgerline-send 2>/dev/null || true  # only if empty: a key left there (the WARNING above) stays
  mkdir -p "$DROPIN"; printf '[Service]\nUMask=0077\n' > "$DROPIN/umask.conf"
  chown -R ledgerline:ledgerline /var/lib/ledgerline || true  # files the sending service created (a journal, a database)
  find /var/lib/ledgerline -type f -exec chmod 600 {} + || true
  find /var/lib/ledgerline -type d -exec chmod 700 {} + || true
  rm -f /etc/systemd/system/ledgerline-send.service
  reload_restart || true
  check_app && echo "sender: off. The app holds the Airwallex keys again, as before. (The ledgerline-send user is left in place.)"
}

main "$@"; exit
