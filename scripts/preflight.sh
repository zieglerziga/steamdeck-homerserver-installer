#!/usr/bin/env bash
set -Eeuo pipefail
# shellcheck source=lib/common.sh
source "$(dirname -- "$0")/lib/common.sh"

load_env
for command in docker ip ss findmnt stat btrfs jq curl python3 iptables ufw; do
  require_command "$command"
done

python3 - "$LAN_IP" "$LAN_CIDR" <<'PY'
import ipaddress, sys
address = ipaddress.IPv4Address(sys.argv[1])
network = ipaddress.IPv4Network(sys.argv[2], strict=False)
if address not in network:
    raise SystemExit(f"error: LAN_IP {address} is not in LAN_CIDR {network}")
PY

if ! ip -4 -o address show scope global | awk '{print $4}' | cut -d/ -f1 | grep -Fxq "$LAN_IP"; then
  die "LAN_IP $LAN_IP is not assigned to a global IPv4 interface"
fi

interface=$(ip -4 -o address show scope global | awk -v address="$LAN_IP/" 'index($4,address)==1 {print $2; exit}')
[[ -n "$interface" && "$interface" != lo ]] || die "LAN_IP must belong to a non-loopback interface"
[[ -e "/sys/class/net/$interface/device" ]] || die "$interface does not appear to be a physical Ethernet interface"

if ! iptables --version | grep -Eq '(nf_tables|legacy)'; then
  die "unsupported Docker firewall backend: $(iptables --version)"
fi
sudo ufw status | grep -q '^Status: active$' || die "UFW must be active before deployment"

if [[ -e /srv/arr/data ]]; then
  [[ $(findmnt -n -o FSTYPE -T /srv/arr/data) == btrfs ]] || die "/srv/arr/data is not on Btrfs"
  btrfs subvolume show /srv/arr/data >/dev/null 2>&1 || die "/srv/arr/data is not a Btrfs subvolume"
else
  probe=/srv
  [[ -e $probe ]] || probe=/
  [[ $(findmnt -n -o FSTYPE -T "$probe") == btrfs ]] || die "$probe is not on Btrfs; mount the intended Btrfs filesystem first"
fi

free_gib=$(stat -f -c '%a %S' "${probe:-/srv/arr/data}" | awk '{printf "%d", ($1*$2)/(1024^3)}')
(( free_gib >= 80 )) || die "only ${free_gib} GiB free; at least 80 GiB is required for initial deployment"

ports=(445 7878 8080 8096 8989 9696 "$QBITTORRENT_PEER_PORT")
for port in "${ports[@]}"; do
  if ss -H -lntup "sport = :$port" | grep -q .; then
    die "port $port is already in use"
  fi
done

if ! sudo docker info --format '{{.ServerVersion}}' >/dev/null; then
  die "rootful Docker is unavailable; enable docker.service first"
fi

info "preflight passed for $interface ($LAN_IP, $LAN_CIDR), ${free_gib} GiB free"
