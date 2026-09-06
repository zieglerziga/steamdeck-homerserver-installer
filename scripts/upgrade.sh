#!/usr/bin/env bash
set -Eeuo pipefail
# shellcheck source=lib/common.sh
source "$(dirname -- "$0")/lib/common.sh"

load_env
"$PROJECT_ROOT/scripts/preflight.sh"
sudo "$PROJECT_ROOT/scripts/backup.sh"
sudo "$PROJECT_ROOT/scripts/prepare-host.sh"
sudo docker compose --env-file /srv/arr/deployment.env -f /usr/local/share/arr-server/compose.yaml pull
sudo docker compose --env-file /srv/arr/deployment.env -f /usr/local/share/arr-server/compose.yaml up -d
info 'upgrade deployed; run make verify before removing the prior application state backup'

