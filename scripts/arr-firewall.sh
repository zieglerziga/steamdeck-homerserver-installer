#!/usr/bin/env bash
set -Eeuo pipefail

action=${1:-apply}
lan_ip=${2:?LAN IPv4 required}
lan_cidr=${3:?LAN CIDR required}
peer_port=${4:?qBittorrent peer port required}
ports=(445 7878 8080 8096 8989 9696 "$peer_port")

command -v iptables >/dev/null || { echo 'iptables is required' >&2; exit 1; }
iptables -nL DOCKER-USER >/dev/null 2>&1 || { echo 'DOCKER-USER is unavailable; Docker must be running' >&2; exit 1; }

rule() {
  local operation=$1 port=$2
  iptables "$operation" DOCKER-USER -p tcp -m conntrack --ctorigdst "$lan_ip" --ctorigdstport "$port" ! -s "$lan_cidr" -j DROP
}

case "$action" in
  apply)
    for port in "${ports[@]}"; do
      rule -C "$port" 2>/dev/null || rule -I "$port"
    done
    ;;
  remove)
    for port in "${ports[@]}"; do
      while rule -C "$port" 2>/dev/null; do rule -D "$port"; done
    done
    ;;
  *) echo 'usage: arr-firewall {apply|remove} LAN_IP LAN_CIDR' >&2; exit 2 ;;
esac
