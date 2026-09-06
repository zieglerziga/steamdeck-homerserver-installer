#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
ENV_FILE=${ENV_FILE:-"$PROJECT_ROOT/.env"}

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

info() {
  printf '%s\n' "$*"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

load_env() {
  [[ -f "$ENV_FILE" ]] || die "missing $ENV_FILE; copy .env.example and edit it"
  # Values are restricted before sourcing to avoid treating .env as a shell script.
  if grep -Ev '^(#|$|[A-Z][A-Z0-9_]*=[A-Za-z0-9_./:+-]+)$' "$ENV_FILE" | grep -q .; then
    die "$ENV_FILE contains unsupported syntax"
  fi
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
}

require_root() {
  [[ ${EUID:-$(id -u)} -eq 0 ]] || die "run this command through sudo"
}

