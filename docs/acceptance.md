# Acceptance checklist

Run `./scripts/verify.sh static` from a fresh clone first. It validates Compose,
shell/Python syntax, and isolated bootstrap/guard tests without using sudo or
starting containers. After operator deployment, `make verify` additionally
checks running services, unauthenticated API rejection, hardlink identity,
Jellyfin's read-only mount, IPv6 listeners, and Docker firewall presence.

Complete these physical/LAN checks manually and record date, client, and result:

- From a second LAN computer, sign in to each web UI. Confirm anonymous access
  fails and access from a guest VLAN or address outside `LAN_CIDR` times out.
- Run the same probes after a reboot to confirm `DOCKER-USER` persistence. Check
  the host and another IPv6-capable LAN device for all service ports.
- Open the authenticated `smb://LAN_IP/library` share in VLC. Direct-play a
  representative H.264 file, then confirm creating, renaming, and deleting a
  file through SMB all fail.
- Direct-play through Jellyfin on two clients concurrently. Confirm the server
  dashboard says Direct Play for both; transcoding is not accepted as a pass.
- Close the lid on AC and confirm the server stays reachable and the screen
  locks. Remove AC and confirm the idle inhibitor disappears and lid closure
  suspends. Reconnect AC and confirm inhibition returns. Inspect critical
  battery policy configuration without intentionally draining the battery.
- Reboot, manually unlock the encrypted filesystem, and confirm the stack starts
  before any desktop login only after `/srv/arr/data` is mounted.
- Restore the newest backup into an isolated empty directory and inspect its
  manifest, databases, configs, and root-only secret modes.
- With a deliberately selected authorized torrent, exercise search, Prowlarr
  sync, two-download queueing, completion, import, and continued seeding. Check
  source and library files with `stat -c '%d:%i %n'` and inspect codecs with
  `ffprobe`. Do not use copyrighted material without authorization.

Low-disk behavior is covered with simulated thresholds in the test suite. A
live threshold test is optional and should use the test override only in an
isolated test state/API environment; never fill the production disk on purpose.

