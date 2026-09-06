#!/usr/bin/env bash
set -Eeuo pipefail
# shellcheck source=lib/common.sh
source "$(dirname -- "$0")/lib/common.sh"

require_root
archive=${1:-}
target_root=${2:-/srv/arr}
[[ -f $archive ]] || die "backup archive not found: $archive"
for command in tar zstd; do require_command "$command"; done

while IFS= read -r member; do
  [[ $member != /* && $member != *'../'* && $member != '..' ]] || die "unsafe archive member: $member"
done < <(tar --zstd -tf "$archive")
tar --zstd -tf "$archive" | grep -Fxq manifest.json || die "backup manifest is missing"
tar --zstd -tf "$archive" | grep -Eq '^config/[^/]+/' || die "application configuration is missing"

if [[ $target_root == /srv/arr ]]; then
  running=$(docker compose --env-file /srv/arr/deployment.env -f /usr/local/share/arr-server/compose.yaml ps --status running -q 2>/dev/null || true)
  [[ -z $running ]] || die "stop the stack before restoring into /srv/arr"
fi
if [[ -e $target_root/config || -e $target_root/secrets ]]; then
  die "target already contains state; restore to an empty directory or move it aside first"
fi

install -d -m 0700 "$target_root"
tar --zstd -xf "$archive" -C "$target_root"
chmod 0700 "$target_root/secrets"
find "$target_root/secrets" -type f -exec chmod 0600 {} +
printf 'restored state into %s; review manifest.json before starting services\n' "$target_root"

