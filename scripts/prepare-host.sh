#!/usr/bin/env bash
set -Eeuo pipefail
# shellcheck source=lib/common.sh
source "$(dirname -- "$0")/lib/common.sh"

require_root
load_env
for command in docker btrfs install systemctl getent useradd groupadd ufw; do
  require_command "$command"
done

backup_dir=/srv/arr/managed-backups/host-$(date -u +%Y%m%dT%H%M%SZ)
install -d -m 0700 "$backup_dir"
for ufw_rules in /etc/ufw/user.rules /etc/ufw/user6.rules; do
  [[ ! -e $ufw_rules ]] || cp -a -- "$ufw_rules" "$backup_dir/$(basename -- "$ufw_rules")"
done

if getent group media >/dev/null; then
  [[ $(getent group media | cut -d: -f3) == "$MEDIA_GID" ]] || die "group media exists with a different GID"
elif getent group "$MEDIA_GID" >/dev/null; then
  die "MEDIA_GID $MEDIA_GID is already assigned to another group"
else
  groupadd --system --gid "$MEDIA_GID" media
fi

if getent passwd arrsvc >/dev/null; then
  [[ $(id -u arrsvc) == "$ARR_UID" ]] || die "user arrsvc exists with a different UID"
elif getent passwd "$ARR_UID" >/dev/null; then
  die "ARR_UID $ARR_UID is already assigned to another user"
else
  useradd --system --uid "$ARR_UID" --gid media --home-dir /srv/arr --shell /usr/bin/nologin arrsvc
fi

install -d -m 0750 -o arrsvc -g media /srv/arr /srv/arr/config /srv/arr/managed-backups
if [[ ! -e /srv/arr/data ]]; then
  [[ $(findmnt -n -o FSTYPE -T /srv) == btrfs ]] || die "/srv must be on Btrfs"
  btrfs subvolume create /srv/arr/data
fi
btrfs subvolume show /srv/arr/data >/dev/null || die "/srv/arr/data must be a Btrfs subvolume"
install -d -m 2775 -o arrsvc -g media \
  /srv/arr/data/downloads/incomplete /srv/arr/data/downloads/complete \
  /srv/arr/data/library/movies /srv/arr/data/library/tv
for app in radarr sonarr prowlarr qbittorrent jellyfin; do
  install -d -m 2770 -o arrsvc -g media "/srv/arr/config/$app"
done
install -m 0600 -o root -g root "$ENV_FILE" /srv/arr/deployment.env

install_managed() {
  local source=$1 destination=$2 mode=${3:-0644}
  if [[ -e $destination ]]; then
    cp -a -- "$destination" "$backup_dir/$(basename -- "$destination")"
  fi
  install -D -m "$mode" "$source" "$destination"
}

work_dir=$(mktemp -d)
trap 'rm -rf -- "$work_dir"' EXIT
cp "$PROJECT_ROOT/systemd/arr-server.service.in" "$work_dir/arr-server.service"
sed -e "s|@LAN_IP@|$LAN_IP|g" -e "s|@LAN_CIDR@|$LAN_CIDR|g" \
  -e "s|@PEER_PORT@|$QBITTORRENT_PEER_PORT|g" \
  "$PROJECT_ROOT/systemd/arr-firewall.service.in" > "$work_dir/arr-firewall.service"
sed -e "s|@LAN_IP@|$LAN_IP|g" "$PROJECT_ROOT/samba/arr-server.conf.in" > "$work_dir/arr-server.conf"

install_managed "$work_dir/arr-server.service" /etc/systemd/system/arr-server.service
install_managed "$work_dir/arr-firewall.service" /etc/systemd/system/arr-firewall.service
install_managed "$PROJECT_ROOT/systemd/arr-ac-inhibit.service" /etc/systemd/system/arr-ac-inhibit.service
install_managed "$PROJECT_ROOT/systemd/arr-disk-guard.service" /etc/systemd/system/arr-disk-guard.service
install_managed "$PROJECT_ROOT/systemd/arr-backup.service" /etc/systemd/system/arr-backup.service
install_managed "$PROJECT_ROOT/systemd/arr-backup.timer" /etc/systemd/system/arr-backup.timer
install_managed "$PROJECT_ROOT/systemd/logind-arr.conf" /etc/systemd/logind.conf.d/70-arr-server.conf
install_managed "$PROJECT_ROOT/scripts/arr-firewall.sh" /usr/local/libexec/arr-firewall 0755
install_managed "$PROJECT_ROOT/scripts/ac-inhibit.sh" /usr/local/libexec/arr-ac-inhibit 0755
install_managed "$PROJECT_ROOT/scripts/disk_guard.py" /usr/local/libexec/arr-disk-guard 0755
install_managed "$PROJECT_ROOT/scripts/backup.sh" /usr/local/libexec/arr-backup 0755
install_managed "$PROJECT_ROOT/scripts/lib/common.sh" /usr/local/libexec/lib/common.sh 0755
install_managed "$work_dir/arr-server.conf" /etc/samba/arr-server.conf 0600
install_managed "$PROJECT_ROOT/systemd/arr-smb.service" /etc/systemd/system/arr-smb.service
install_managed "$PROJECT_ROOT/compose.yaml" /usr/local/share/arr-server/compose.yaml

ufw allow proto tcp from "$LAN_CIDR" to "$LAN_IP" port 445 comment 'arr-smb-lan'
ufw deny proto tcp from any to "$LAN_IP" port 445 comment 'arr-smb-non-lan'

systemctl daemon-reload
systemctl enable docker.service arr-firewall.service arr-server.service arr-smb.service arr-ac-inhibit.service arr-disk-guard.service
systemctl enable arr-backup.timer
info "host prepared; previous managed files (if any) are in $backup_dir"
info "set the Samba password with: sudo smbpasswd -a arrsvc"
info "start services explicitly with: sudo systemctl start arr-server arr-smb arr-ac-inhibit"
info "apply the lid policy at a maintenance window with: sudo systemctl restart systemd-logind"
