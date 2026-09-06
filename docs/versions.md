# Supported versions

The Compose file pins the multi-architecture manifest digest as resolved on
2026-09-06. Versions are LinuxServer.io image versions, not floating tags.

| Service | Image version | Supported API |
| --- | --- | --- |
| Radarr | 6.3.0.10514-ls315 | v3 |
| Sonarr | 4.0.19.2979-ls323 | v3 |
| Prowlarr | 2.5.2.5491-ls158 | v1 |
| qBittorrent | 5.2.3_v2.0.14-ls475 | Web API v2; qBittorrent 5 `start`/`stop` operations |
| Jellyfin | 10.11.11ubu2604-ls47 | setup is manual in v1 |

Image upgrades are explicit. Update both the version tag and digest, review
upstream release notes, run the isolated checks, take a backup, and only then
run `make upgrade`.

