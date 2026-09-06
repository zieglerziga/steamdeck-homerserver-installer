#!/usr/bin/env bash
set -Eeuo pipefail

action=${1:-apply}
lan_ip=${2:?LAN IPv4 required}
lan_cidr=${3:?LAN CIDR required}
peer_port=${4:?qBittorrent peer port required}
tcp_ports=(7878 8080 8096 8989 9696 "$peer_port")

command -v iptables >/dev/null || { echo 'iptables is required' >&2; exit 1; }
iptables -nL DOCKER-USER >/dev/null 2>&1 || { echo 'DOCKER-USER is unavailable; Docker must be running' >&2; exit 1; }

docker_rule() {
  local operation=$1 protocol=$2 port=$3
  iptables "$operation" DOCKER-USER -p "$protocol" -m conntrack --ctorigdst "$lan_ip" --ctorigdstport "$port" ! -s "$lan_cidr" -j DROP
}

smb_rule() {
  local operation=$1
  iptables "$operation" INPUT -p tcp -d "$lan_ip" --dport 445 ! -s "$lan_cidr" -j DROP
}

case "$action" in
  apply)
    for port in "${tcp_ports[@]}"; do
      docker_rule -C tcp "$port" 2>/dev/null || docker_rule -I tcp "$port"
    done
    docker_rule -C udp "$peer_port" 2>/dev/null || docker_rule -I udp "$peer_port"
    smb_rule -C 2>/dev/null || smb_rule -I
    ;;
  remove)
    for port in "${tcp_ports[@]}"; do
      while docker_rule -C tcp "$port" 2>/dev/null; do docker_rule -D tcp "$port"; done
    done
    while docker_rule -C udp "$peer_port" 2>/dev/null; do docker_rule -D udp "$peer_port"; done
    while smb_rule -C 2>/dev/null; do smb_rule -D; done
    ;;
  *) echo 'usage: arr-firewall {apply|remove} LAN_IP LAN_CIDR' >&2; exit 2 ;;
esac
