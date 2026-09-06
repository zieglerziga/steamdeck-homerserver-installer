#!/usr/bin/env bash
set -Eeuo pipefail

inhibitor_pid=
cleanup() { [[ -z ${inhibitor_pid:-} ]] || kill "$inhibitor_pid" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

on_ac() {
  grep -qs '^1$' /sys/class/power_supply/{AC,ACAD,ADP,ADP0,Mains}*/online 2>/dev/null
}

while sleep 5; do
  if on_ac; then
    if [[ -z ${inhibitor_pid:-} ]] || ! kill -0 "$inhibitor_pid" 2>/dev/null; then
      systemd-inhibit --what=idle:sleep --who=arr-server --why='media server active on AC' sleep infinity &
      inhibitor_pid=$!
    fi
  elif [[ -n ${inhibitor_pid:-} ]]; then
    kill "$inhibitor_pid" 2>/dev/null || true
    wait "$inhibitor_pid" 2>/dev/null || true
    inhibitor_pid=
  fi
done

