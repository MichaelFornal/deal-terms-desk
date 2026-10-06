#!/usr/bin/env bash
# Free disk on the box: keep the release `current` points to, the two most recently completed other releases (the
# rollback targets push.sh may swap back to), and every bundle a kept release links to; remove the rest, including
# partial uploads. Safe to rerun. Runs on the box as root after a good push: bash prune.sh [root=/srv/dtd].
set -euo pipefail
shopt -s nullglob
ROOT="$(cd "${1:-/srv/dtd}" && pwd -P)"
KEEP_OLDER=2

CUR="$(readlink -f "$ROOT/current" 2>/dev/null || true)"
if [ -z "$CUR" ] || [ ! -d "$CUR" ]; then
  echo "refusing to prune: $ROOT/current does not point at a release" >&2
  exit 1
fi

in_list() {  # in_list <path> [list...]: is the path one of the list
  local want="$1" have
  shift
  for have in "$@"; do
    if [ "$have" = "$want" ]; then return 0; fi
  done
  return 1
}

keep=("$CUR")
markers=("$ROOT"/releases/*/.complete)
if [ "${#markers[@]}" -gt 0 ]; then
  for marker in $(ls -1t "${markers[@]}"); do  # newest first; release names are shas, so no spaces
    rel="${marker%/.complete}"
    if [ "$rel" = "$CUR" ]; then continue; fi
    if [ "${#keep[@]}" -gt "$KEEP_OLDER" ]; then break; fi
    keep+=("$rel")
  done
fi

for rel in "$ROOT"/releases/*/; do
  rel="${rel%/}"
  if ! in_list "$rel" "${keep[@]}"; then
    rm -rf "$rel"
    echo "removed release ${rel##*/}"
  fi
done

used=()
for rel in "${keep[@]}"; do
  db="$(readlink -f "$rel/live.db" 2>/dev/null || true)"
  if [ -n "$db" ]; then used+=("$(dirname "$db")"); fi
done
for bun in "$ROOT"/bundles/*/; do
  bun="${bun%/}"
  if ! in_list "$bun" ${used[@]+"${used[@]}"}; then
    rm -rf "$bun"
    echo "removed bundle ${bun##*/}"
  fi
done
