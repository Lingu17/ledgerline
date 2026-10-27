#!/usr/bin/env bash
# Check out an exact ref (commit id, tag or branch) without discarding local changes.
#   checkout.sh <repo-dir> <ref>
set -euo pipefail
DIR="$1"; REF="$2"
git -C "$DIR" diff --quiet && git -C "$DIR" diff --cached --quiet \
  || { echo "refusing: $DIR has local changes" >&2; exit 2; }
git -C "$DIR" fetch -q origin
if git -C "$DIR" rev-parse -q --verify "origin/$REF^{commit}" >/dev/null; then
  COMMIT=$(git -C "$DIR" rev-parse "origin/$REF^{commit}")      # branch name
elif git -C "$DIR" rev-parse -q --verify "$REF^{commit}" >/dev/null; then
  COMMIT=$(git -C "$DIR" rev-parse "$REF^{commit}")             # commit id or tag
else
  echo "unknown ref: $REF" >&2; exit 2
fi
git -C "$DIR" checkout -q --detach "$COMMIT"
git -C "$DIR" log --oneline -1
