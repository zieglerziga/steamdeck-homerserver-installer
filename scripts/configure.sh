#!/usr/bin/env bash
set -Eeuo pipefail
# shellcheck source=lib/common.sh
source "$(dirname -- "$0")/lib/common.sh"

load_env
require_command python3
sudo --preserve-env=LAN_IP,LAN_CIDR,TZ python3 "$PROJECT_ROOT/scripts/bootstrap.py"

