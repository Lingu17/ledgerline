#!/usr/bin/env bash
# Deploy an exact version: sudo bash /opt/ledgerline/src/deploy/vm/update.sh <commit|tag|branch>
# If the checkout, the dependency install or the build fails, the previous commit and its dependencies are put back
# before anything restarts, so a later restart (a crash, a reboot) never runs new code on old dependencies. The
# running service is not touched in that case. Paths can be overridden for a local test of this script.
set -Eeuo pipefail
cd / # neutral working directory: tools run as the service user must not read the caller's home
REF="${1:?commit id, tag or branch}"
SRC="${LEDGERLINE_SRC:-/opt/ledgerline/src}"
VENV="${LEDGERLINE_VENV:-/opt/ledgerline/venv}"
APP_HOME="${LEDGERLINE_HOME:-/opt/ledgerline}"
MODE_FILE="${LEDGERLINE_MODE_FILE:-/etc/ledgerline/mode}"
as_app() { sudo -u ledgerline "$@"; }

install_and_build() {
  local hashes=""
  if grep -q -e "--hash=" "$SRC/backend/requirements-lock.txt"; then hashes="--require-hashes"; fi
  as_app env VIRTUAL_ENV="$VENV" uv pip install -q $hashes -r "$SRC/backend/requirements-lock.txt"
  if [[ $(cat "$MODE_FILE" 2>/dev/null) == single ]]; then
    (cd "$SRC/frontend" && as_app env HOME="$APP_HOME" npm ci --no-audit --no-fund --loglevel=error && as_app env HOME="$APP_HOME" npm run build)
  fi
}

PREV=$(as_app git -C "$SRC" rev-parse HEAD)
rollback() {
  if (( BASH_SUBSHELL > 0 )); then exit 1; fi  # let the main shell do the one rollback
  trap - ERR
  echo "update to $REF failed; restoring $PREV (the running service was not restarted)" >&2
  if as_app bash "$SRC/deploy/vm/checkout.sh" "$SRC" "$PREV" && install_and_build; then
    echo "restored $PREV" >&2
  else
    echo "ROLLBACK FAILED: $SRC may not match $PREV; fix it by hand before any restart" >&2
  fi
  exit 1
}
trap rollback ERR

as_app bash "$SRC/deploy/vm/checkout.sh" "$SRC" "$REF"
install_and_build
trap - ERR

systemctl restart ledgerline
for i in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8000/api/health; then echo; exit 0; fi; sleep 2
done
echo "FAILED: not healthy after restart" >&2; journalctl -u ledgerline -n 40 --no-pager >&2; exit 1
