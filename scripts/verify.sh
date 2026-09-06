#!/usr/bin/env bash
set -Eeuo pipefail
# shellcheck source=lib/common.sh
source "$(dirname -- "$0")/lib/common.sh"

mode=${1:-live}
[[ $mode == live || $mode == static ]] || die "usage: $0 [static|live]"
require_command docker

temporary_env=
if [[ -f $ENV_FILE ]]; then
  load_env
else
  temporary_env=$(mktemp)
  trap 'rm -f -- "$temporary_env"' EXIT
  cp "$PROJECT_ROOT/.env.example" "$temporary_env"
  ENV_FILE=$temporary_env
  load_env
fi

docker compose --env-file "$ENV_FILE" -f "$PROJECT_ROOT/compose.yaml" config --quiet
bash -n "$PROJECT_ROOT"/scripts/*.sh "$PROJECT_ROOT"/scripts/lib/*.sh
python3 -m unittest discover -s "$PROJECT_ROOT/tests" -v
info 'static validation passed'
[[ $mode == static ]] && exit 0

for command in curl stat; do require_command "$command"; done
compose=(sudo docker compose --env-file /srv/arr/deployment.env -f /usr/local/share/arr-server/compose.yaml)
expected=(radarr sonarr prowlarr qbittorrent jellyfin)
mapfile -t running < <("${compose[@]}" ps --status running --services)
for service in "${expected[@]}"; do
  printf '%s\n' "${running[@]}" | grep -Fxq "$service" || die "$service is not running"
done

for endpoint in 7878/v3 8989/v3 9696/v1; do
  port=${endpoint%/*}
  api_version=${endpoint#*/}
  status=$(curl -sS -o /dev/null -w '%{http_code}' "http://$LAN_IP:$port/api/$api_version/system/status" || true)
  [[ $status == 401 || $status == 403 ]] || die "ARR API on port $port does not require authentication (HTTP $status)"
done
status=$(curl -sS -o /dev/null -w '%{http_code}' "http://$LAN_IP:8080/api/v2/app/preferences" || true)
[[ $status == 403 ]] || die "qBittorrent API does not require authentication (HTTP $status)"
status=$(curl -sS -o /dev/null -w '%{http_code}' "http://$LAN_IP:8096/System/Info" || true)
[[ $status == 401 ]] || die "Jellyfin API does not require authentication (HTTP $status)"

probe=".arr-hardlink-probe-$$"
cleanup_probe() {
  "${compose[@]}" exec -T qbittorrent rm -f "/data/downloads/complete/$probe" "/data/library/movies/$probe" >/dev/null 2>&1 || true
}
trap cleanup_probe EXIT INT TERM
"${compose[@]}" exec -T qbittorrent sh -c "umask 002; : > /data/downloads/complete/$probe"
"${compose[@]}" exec -T radarr ln "/data/downloads/complete/$probe" "/data/library/movies/$probe"
source_inode=$(stat -c '%d:%i' "/srv/arr/data/downloads/complete/$probe")
library_inode=$(stat -c '%d:%i' "/srv/arr/data/library/movies/$probe")
[[ $source_inode == "$library_inode" ]] || die "download and import paths do not hardlink"
if "${compose[@]}" exec -T jellyfin touch "/data/library/$probe" 2>/dev/null; then
  die "Jellyfin unexpectedly modified its read-only media mount"
fi
cleanup_probe
trap - EXIT INT TERM

for port in 7878 8080 8096 8989 9696; do
  ss -H -lnt6 "sport = :$port" | grep -q . && die "port $port is unexpectedly listening on IPv6"
done
sudo iptables -S DOCKER-USER | grep -Fq "$LAN_CIDR" || die "LAN Docker firewall rules are absent"
info 'local live verification passed; complete the documented second-device checks'
