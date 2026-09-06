#!/usr/bin/env bash
set -Eeuo pipefail
# shellcheck source=lib/common.sh
source "$(dirname -- "$0")/lib/common.sh"

require_root
for command in docker tar zstd jq; do require_command "$command"; done
[[ -f /srv/arr/deployment.env ]] || die "host is not prepared"

backup_root=${BACKUP_ROOT:-/srv/arr/backups}
install -d -m 0700 -o root -g root "$backup_root"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
archive="$backup_root/arr-backup-$stamp.tar.zst"
work_dir=$(mktemp -d)
running=()
mapfile -t running < <(docker compose --env-file /srv/arr/deployment.env -f /usr/local/share/arr-server/compose.yaml ps --status running --services)

restart_writers() {
  local status=$?
  trap - EXIT INT TERM
  if ((${#running[@]})); then
    docker compose --env-file /srv/arr/deployment.env -f /usr/local/share/arr-server/compose.yaml up -d "${running[@]}" >/dev/null || status=1
  fi
  rm -rf -- "$work_dir"
  exit "$status"
}
trap restart_writers EXIT
trap 'exit 130' INT TERM

if ((${#running[@]})); then
  docker compose --env-file /srv/arr/deployment.env -f /usr/local/share/arr-server/compose.yaml stop "${running[@]}"
fi

jq -n \
  --arg created "$stamp" \
  --arg compose_sha256 "$(sha256sum /usr/local/share/arr-server/compose.yaml | cut -d' ' -f1)" \
  --arg source_revision "$(git -C "$PROJECT_ROOT" rev-parse HEAD 2>/dev/null || printf unknown)" \
  '{format: 1, createdUtc: $created, composeSha256: $compose_sha256, sourceRevision: $source_revision}' \
  > "$work_dir/manifest.json"

tar --zstd -cf "$archive" \
  --exclude='config/*/logs' --exclude='config/*/logs/*' \
  --exclude='config/jellyfin/cache' --exclude='config/jellyfin/cache/*' \
  -C /srv/arr config secrets deployment.env \
  -C "$work_dir" manifest.json
chmod 0600 "$archive"
mapfile -t old_backups < <(find "$backup_root" -maxdepth 1 -type f -name 'arr-backup-*.tar.zst' -printf '%f\n' | sort | head -n -7)
for old_backup in "${old_backups[@]}"; do rm -f -- "$backup_root/$old_backup"; done
printf 'backup created: %s\n' "$archive"
