# Reproducible Omarchy ARR media server

## Summary

Use the repository to recreate a media server on this Omarchy laptop: 8 GB RAM, i5-3320M, and approximately 213 GB free on its encrypted SSD.

Deploy Radarr, Sonarr, Prowlarr, qBittorrent, and Jellyfin through Docker Compose, plus host Samba for VLC. Support 1–2 simultaneous direct-play streams. Transcoding is outside v1 acceptance.

## Git workflow and incremental remote backup

- Before implementation, create `feat/omarchy-arr-server` from the current default branch and commit this plan as the first checkpoint. Reuse that branch when resuming implementation.
- Use descriptive lowercase, kebab-case branch names with a purpose prefix such as `feat/`, `fix/`, or `docs/`. Use Conventional Commits: `<type>(<scope>): <short imperative description>`, for example `docs(plan): record ARR deployment plan`, `feat(compose): add media service stack`, and `fix(storage): preserve seeding hardlinks`.
- Commit and push every meaningful, coherent state immediately: the plan, deployment scaffold, host preparation, application bootstrap, storage guard, networking and power configuration, backup and restore, and verification/documentation. Split these further whenever an independently reviewable change is ready; do not defer all commits until implementation is complete.
- Before each commit, inspect the staged diff, stage only intended files, check for credentials and generated application data, and run checks appropriate to the change. Record relevant validation and any remaining limitations in the commit body. A checkpoint may be a completed component of the larger unfinished system; do not present failing or untested behavior as verified.
- Push the first checkpoint with upstream tracking to `origin/feat/omarchy-arr-server`, then push each subsequent checkpoint. Verify that the remote branch points to the local commit before reporting the checkpoint as backed up. If a push fails, retain the local commit, report the backup gap, and retry without discarding work.
- Preserve published checkpoint history: use follow-up commits instead of amending, rebasing, squashing, or force-pushing the implementation branch. Do not merge into the default branch as part of checkpoint backups.
- GitHub checkpoints back up source and documentation only. Credentials, media, runtime state, and application backups remain outside Git and follow the separate recovery procedure below.

## Deployment and application setup

- Provide commands for preflight, host preparation, configuration, deployment, verification, backup, restore, and explicit upgrades.
- Use rootful system Docker. Privileged host operations run through `sudo`; do not require adding the desktop user to the Docker group.
- Create a dedicated media service account and shared group. Configure compatible container identities, group-write permissions, and umask `002`; grant Jellyfin and Samba read-only media access.
- Pin tested image versions and digests during implementation. Commit the supported API versions and use qBittorrent’s matching API operations.
- Keep credentials and generated API keys in permission-restricted local files outside Git. Prompt locally for nCore credentials; redact secrets from logs and diagnostics.
- Bootstrap through application APIs with bounded readiness polling. Discover provider schemas, identify managed records by stable names, and update them without duplication. Preserve unrelated settings; stop with a clear conflict report when existing records cannot safely be reconciled.
- Configure nCore through Prowlarr, synchronize it with Radarr/Sonarr, and connect their download clients and library roots. Failed authentication must leave setup safely resumable.

## Storage and download behavior

- Put state under `/srv/arr` and downloads plus libraries in one Btrfs subvolume under `/srv/arr/data`. Do not create nested subvolumes for these directories.
- Mount the common data tree at `/data` in download/import containers. Use hardlink imports and retain torrent source files for seeding.
- Default to 720p/1080p releases, preferring original audio and H.264. Reject known HEVC, x265, AV1, 4K, and remux markers. Missing or misleading metadata remains possible; inspect imported streams and flag mismatches without automatically deleting files.
- Disable automatic quality upgrades. Set quality-size maxima to approximately 4 GiB/hour, converting into each pinned application’s documented units. Test movie, episode, and season-pack handling rather than applying a fixed total-size cap.
- Allow two active downloads. Keep completed torrents seeding until manually removed; do not encode unverified tracker-specific minimums.
- Implement a serialized disk guard checking the actual data filesystem every 15 seconds. Warn below 40 GiB and latch download blocking below 30 GiB.
- While latched, disable managed automatic grabs, stop incomplete torrents, and repeatedly stop newly added incomplete torrents. Preserve completed seeders and verify stop requests succeeded.
- Require explicit reset with at least 40 GiB free. Restore only settings and torrents changed by the guard. Describe this as a best-effort reserve, since other applications and in-flight writes can still consume disk space.

## Networking and laptop operation

- Bind published web interfaces and SMB to the configured Ethernet IPv4 address; require authentication throughout. SMB exposes only the library, read-only.
- Document a router DHCP reservation. Preflight validates the configured address and checks port conflicts.
- Preserve UFW and add persistent Docker-aware forwarding restrictions for the detected firewall backend. Refuse deployment on an unsupported backend rather than silently omitting restrictions.
- Do not publish services over IPv6 in v1. Test both IPv4 and IPv6 exposure, including access from outside the allowed LAN.
- Default to passive torrent connectivity: no VPN, UPnP, NAT-PMP, or router forwarding. Document optional manual peer-port forwarding separately from administrative interfaces.
- Install a reversible logind drop-in that ignores lid closure on AC. Retain battery lid-suspend behavior, screen locking, and critical-battery protection.
- Prevent idle suspension on AC through an AC-aware service, releasing its inhibition on battery. Preserve unrelated Omarchy settings and back up managed configuration.
- Start services after boot and manual disk unlock, independently of desktop login.

## Recovery and documentation

- Provide consistent nightly backups by stopping application writers during capture and restarting them afterward, including on backup failure. Retain seven successful daily backups.
- Include application databases, configuration, credentials, and deployment version information; exclude downloaded media and rebuildable caches.
- Protect backups and document off-device export. Local backups alone do not cover SSD failure.
- Document restoration on a fresh Omarchy installation, external-disk migration, failed upgrade recovery, tracker reauthentication, and manual cleanup that respects seeding.
- Correct the README title while retaining the existing GitHub repository name and URL.

## Verification and acceptance

- Validate Compose and scripts; test repeatable bootstrap, conflicts, unavailable APIs, authentication errors, and secret redaction.
- Confirm service identities can download and import, while Jellyfin and SMB cannot modify media. Verify imported files share device and inode numbers with seeded originals.
- Test the disk guard’s latch, newly added torrents, concurrent runs, API failures, restart persistence, and explicit reset using simulated thresholds.
- Verify LAN authentication, Docker firewall persistence after reboot, and absence of unintended IPv6 exposure.
- Verify VLC/SMB and Jellyfin direct playback from another computer, including two concurrent streams.
- Exercise lid closure on AC, AC removal, idle behavior, and boot after manual unlock; validate battery-critical handling without deliberately exhausting the battery.
- Restore a backup into isolated application state.
- Test the full download/import path only with an explicitly selected authorized torrent.

Completion means a fresh clone and local configuration reproduce the suite, with manual steps documented for credentials, router reservation, boot unlocking, and checks requiring another device.
