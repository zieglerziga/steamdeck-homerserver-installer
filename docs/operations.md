# Operations and recovery

## Storage and seeding

The only managed data subvolume is `/srv/arr/data`. Its paths are:

```text
/srv/arr/data/
├── downloads/
│   ├── incomplete/
│   └── complete/
└── library/
    ├── movies/
    └── tv/
```

Radarr, Sonarr, and qBittorrent see the whole tree at `/data`. Successful
imports should share device and inode numbers with completed source files.
Never delete a completed download merely because it appears in the library;
remove its torrent manually only after its seeding obligation is satisfied.
The installer intentionally does not guess a tracker-specific minimum.

The managed quality profile permits 720p and 1080p, disables upgrades, rejects
release-title markers for HEVC/x265, AV1, 2160p/4K, and remux, prefers H.264,
and prefers the provider's `Original` language option when that schema exposes
one. Global quality maxima are 68.27 MiB/minute (approximately 4 GiB/hour), so
movie, episode, and season-pack limits scale with runtime. Titles and metadata
can lie: inspect imported streams and flag mismatches; do not auto-delete them.

## Disk guard

`arr-disk-guard.service` checks the actual `/srv/arr/data` filesystem every 15
seconds. Below 30 GiB it persists a latch before API changes, sets managed ARR
RSS intervals to zero, stops every incomplete torrent, and verifies the stop.
It continues catching newly added incomplete torrents while leaving completed
seeders alone.

After manual cleanup, reset only when at least 40 GiB is free:

```bash
make guard-reset
```

Only settings and incomplete torrents recorded as changed by the guard are
restored. Inspect state with `sudo ./scripts/disk_guard.py status`.

## Backups and restore

The persistent nightly timer runs around 03:30, stops the services that were
running, archives configs, databases, credentials, deployment environment, and
a version manifest, then restarts those same services even if capture fails.
Logs, cache, downloads, and media are excluded. Seven successful archives are
retained under `/srv/arr/backups`, mode 0600.

Local backups do not protect against SSD failure. Regularly copy encrypted
archives to a trusted off-device destination and verify them there. Do not
commit or upload an unencrypted archive to GitHub.

To exercise restore without touching live state:

```bash
sudo ./scripts/restore.sh /srv/arr/backups/arr-backup-TIMESTAMP.tar.zst /tmp/arr-restore-test
sudo find /tmp/arr-restore-test -maxdepth 3 -type f
```

For a fresh Omarchy installation, clone the same revision, install dependencies,
mount/unlock the target Btrfs filesystem at `/srv`, run preflight and prepare,
stop the enabled stack, move the empty generated `config` and `secrets`
directories aside, restore into `/srv/arr`, rerun prepare to install the pinned
deployment files, and start services. Reauthenticate nCore if its session or
credentials changed, then rerun `make configure`.

For a failed image upgrade, stop the stack, move its current config aside,
restore the last archive into an empty `/srv/arr`, check out the recorded source
revision from `manifest.json`, rerun prepare, and start. Never downgrade an app
database in place.

## External-disk migration

Stop the stack and backup first. Create one Btrfs subvolume on the external
filesystem, copy `/srv/arr/data` while preserving owners, modes, xattrs, and
hardlinks (`cp -a --reflink=auto` is suitable on Btrfs), mount that subvolume at
`/srv/arr/data`, and run `make verify`. Do not split downloads and libraries
across filesystems or nested subvolumes; that breaks hardlinks. Update the
system's crypttab/fstab so boot waits for manual unlock, then verify
`RequiresMountsFor=/srv/arr/data` prevents an early start.

## Network operation

Keep the router DHCP reservation aligned with `LAN_IP`. Do not forward web UI
ports. Passive torrent connectivity is the default. If an operator deliberately
wants inbound peers, forward only `QBITTORRENT_PEER_PORT` and replace its
generated `DOCKER-USER` drop rule with a narrowly reviewed peer rule; never
forward 445, 7878, 8080, 8096, 8989, or 9696.

The implementation supports Docker's iptables legacy and iptables-nft
compatibility backends. Preflight refuses an unrecognized backend or inactive
UFW instead of silently deploying without the extra forwarding restriction.
Preparation adds named UFW rules for SMB and backs up the prior UFW rule files.
To remove the integration, stop `arr-smb.service`, then run the exact inverse
commands: `sudo ufw delete allow proto tcp from LAN_CIDR to LAN_IP port 445` and
`sudo ufw delete deny proto tcp from any to LAN_IP port 445`.
