# Omarchy ARR home-server installer

Reproducible, operator-run configuration for a small Omarchy laptop media
server. It deploys Radarr, Sonarr, Prowlarr, qBittorrent, and Jellyfin with
rootful Docker Compose, plus a read-only authenticated Samba library for VLC.
The repository name and URL remain `steamdeck-homerserver-installer` for
existing links.

The v1 target is one or two direct-play streams. Transcoding is not an
acceptance target. Nothing in this repository starts a torrent automatically;
the end-to-end download test requires an explicitly chosen, authorized torrent.

## Safety model

- Web ports bind only to the configured Ethernet IPv4 address. Docker's
  `DOCKER-USER` chain restricts routed access to the configured LAN, including
  the passive peer port; no service is published on IPv6.
- Every web UI must have authentication. Samba is authenticated and exports
  only `/srv/arr/data/library`, read-only.
- Secrets live under `/srv/arr/secrets` with root-only permissions and are
  ignored by Git. Scripts deliberately omit request bodies and responses from
  API error output.
- qBittorrent has UPnP/NAT-PMP disabled and no router forwarding by default.
  Media and downloads share one Btrfs subvolume so imports can hardlink while
  source files remain available for seeding.
- The disk guard warns below 40 GiB and latches below 30 GiB. This is a
  best-effort reserve: in-flight writes and unrelated processes can still use
  space.

## Installation

Reserve the intended Ethernet address in the router's DHCP settings first.
Then clone this repository on the Omarchy machine and run:

```bash
cp .env.example .env
chmod 600 .env
$EDITOR .env
make dependencies
make preflight
make prepare
make deploy
```

`make dependencies` uses Omarchy's package command. `make prepare` is the
explicit privileged step: it creates `arrsvc:media`, `/srv/arr`, the single
`/srv/arr/data` subvolume, and managed systemd/Samba/firewall files. It backs up
files it replaces under `/srv/arr/managed-backups`, enables boot services, but
does not start the stack or restart logind.

On first qBittorrent start, read its temporary password locally from
`sudo docker logs qbittorrent`, configure a permanent password in its Web UI,
and do not paste either password into an issue or shell history. Then run:

```bash
make configure
sudo smbpasswd -a arrsvc
sudo systemctl start arr-smb arr-ac-inhibit arr-disk-guard
```

The bootstrap prompts without echo for passwords, discovers the installed API
schemas, tests nCore and application connections, and reconciles only stable
`managed-*` records. A collision it cannot safely interpret stops with a
conflict instead of creating duplicates. Authentication failure is resumable.

Complete Jellyfin's local setup wizard at `http://LAN_IP:8096`: create a strong
administrator account, disable remote connections outside the LAN, and add
`/data/library/movies` and `/data/library/tv`. Hardware transcoding is outside
v1; clients should select direct play.

Apply the managed AC lid policy during a maintenance window:

```bash
sudo systemctl restart systemd-logind
```

It ignores lid closure only on external power. Battery lid suspend, screen
locking, Omarchy's unrelated settings, and critical-battery handling remain in
place. An AC-aware inhibitor prevents idle suspension only while external
power is present.

## Day-two commands

```bash
make verify                       # static tests plus local live checks
make backup                       # consistent root-only state backup
make guard-reset                  # requires at least 40 GiB free
make upgrade                      # preflight, backup, install pins, pull, start
make restore ARCHIVE=/path/file   # stack must be stopped; target must be empty
```

See [operations](docs/operations.md) for recovery, migration, cleanup, and
networking, and [acceptance](docs/acceptance.md) for checks requiring the real
machine or another device. Pinned images and API versions are recorded in
[supported versions](docs/versions.md).

## Upstream interface references

The layout follows LinuxServer's guidance to use a single shared mount for
[Radarr hardlinks and atomic moves](https://docs.linuxserver.io/images/docker-radarr/).
The guard uses qBittorrent 5's current `stop` and `start` Web API operations from
the [official qBittorrent wiki source](https://github.com/qbittorrent/wiki/blob/master/WebUI-API-%28qBittorrent-5.0%29.md).
Docker filtering is placed in `DOCKER-USER`, as described by
[Docker's firewall documentation](https://docs.docker.com/engine/network/firewall-iptables/),
because ordinary UFW input rules do not see published-container traffic soon
enough.
