#!/usr/bin/env bash
# Deploy an exact version: sudo bash /opt/ledgerline/src/deploy/vm/update.sh <commit|tag|branch>
#
# If the checkout, the dependency install or the build fails, the previous commit and its dependencies are put back
# before anything restarts. If the new version is not healthy after the restart, the previous one is put back and
# restarted. Either way the script exits non-zero and says whether the old version came back healthy.
# Rolling back relies on older code starting against a newer database; migrations only ever add, so it does. A
# migration that older code cannot run against must say so in its commit.
#
# The body is one function, read in full before it runs, because the checkout rewrites this file; the rollback uses
# a copy of checkout.sh taken before the checkout, in case the new one is broken. Paths can be overridden only for a
# local test of this script.
set -Eeuo pipefail

as_app() { sudo -u ledgerline "$@"; }

install_and_build() {
  local hashes=""
  if grep -q -e "--hash=" "$SRC/backend/requirements-lock.txt"; then hashes="--require-hashes"; fi
  as_app env VIRTUAL_ENV="$VENV" uv pip install -q $hashes -r "$SRC/backend/requirements-lock.txt"
  if [[ $(cat "$MODE_FILE" 2>/dev/null) == single ]]; then
    (cd "$SRC/frontend" && as_app env HOME="$APP_HOME" npm ci --no-audit --no-fund --loglevel=error && as_app env HOME="$APP_HOME" npm run build)
  fi
}

restore() { as_app bash "$CHECKOUT" "$SRC" "$PREV" && install_and_build; }

healthy() {  # the health route answers, and a signed-out request to a real route is refused (so routing and auth work)
  for _ in $(seq 1 "$HEALTH_TRIES"); do
    if curl -fsS "$HEALTH_URL" && [[ $(curl -s -o /dev/null -w '%{http_code}' "${HEALTH_URL%/health}/deposits") == 401 ]]; then echo; return 0; fi
    sleep 2
  done
  return 1
}

rollback() {
  if (( BASH_SUBSHELL > 0 )); then exit 1; fi  # let the main shell do the one rollback
  trap - ERR
  echo "update to $REF failed before the restart; restoring $PREV (the running service was not restarted)" >&2
  if restore; then echo "restored $PREV" >&2; else echo "ROLLBACK FAILED: $SRC may not match $PREV; fix it by hand before any restart" >&2; fi
  rm -f "$CHECKOUT"
  exit 1
}

main() {
  cd / # neutral working directory: tools run as the service user must not read the caller's home
  REF="${1:?commit id, tag or branch}"
  SRC="${LEDGERLINE_SRC:-/opt/ledgerline/src}"
  VENV="${LEDGERLINE_VENV:-/opt/ledgerline/venv}"
  APP_HOME="${LEDGERLINE_HOME:-/opt/ledgerline}"
  MODE_FILE="${LEDGERLINE_MODE_FILE:-/etc/ledgerline/mode}"
  HEALTH_URL="${LEDGERLINE_HEALTH_URL:-http://127.0.0.1:8000/api/health}"
  HEALTH_TRIES="${LEDGERLINE_HEALTH_TRIES:-30}"
  CHECKOUT=$(mktemp)
  cp "$SRC/deploy/vm/checkout.sh" "$CHECKOUT"
  chmod 644 "$CHECKOUT"  # the service user runs it
  PREV=$(as_app git -C "$SRC" rev-parse HEAD)

  trap rollback ERR
  as_app bash "$CHECKOUT" "$SRC" "$REF"
  install_and_build
  trap - ERR

  systemctl restart ledgerline
  if healthy; then
    rm -f "$CHECKOUT"
    exit 0
  fi
  echo "FAILED: $REF is not healthy after the restart; putting $PREV back" >&2
  journalctl -u ledgerline -n 40 --no-pager >&2 || true
  if restore && systemctl restart ledgerline && healthy; then
    echo "restored $PREV, and it is healthy" >&2
  else
    echo "ROLLBACK FAILED: $PREV is not healthy either; fix it by hand" >&2
  fi
  rm -f "$CHECKOUT"
  exit 1
}

main "$@"; exit
