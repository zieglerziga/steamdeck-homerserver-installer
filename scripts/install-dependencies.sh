#!/usr/bin/env bash
set -Eeuo pipefail

if [[ ${EUID:-$(id -u)} -eq 0 ]]; then
  echo 'run this command as the desktop user; Omarchy will request sudo when needed' >&2
  exit 1
fi

command -v omarchy >/dev/null 2>&1 || {
  echo 'this installer supports Omarchy and requires the omarchy command' >&2
  exit 1
}

omarchy pkg add docker docker-compose samba btrfs-progs zstd curl jq python

