#!/usr/bin/env python3
"""Latch ARR downloads when the shared data filesystem reaches its reserve."""

from __future__ import annotations

import argparse
import fcntl
import http.cookiejar
import json
import os
import pathlib
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

GIB = 1024**3
INCOMPLETE_STOPPED_STATES = {"stoppedDL", "pausedDL"}


class GuardError(RuntimeError):
    pass


def atomic_json(path: pathlib.Path, value: dict) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(value, stream, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def load_state(path: pathlib.Path) -> dict:
    if not path.exists():
        return {"latched": False, "apps": {}, "torrents": [], "torrentPending": []}
    try:
        state = json.loads(path.read_text())
        state.setdefault("torrentPending", [])
        return state
    except (OSError, json.JSONDecodeError) as error:
        raise GuardError("disk guard state is unreadable") from error


class JsonApi:
    def __init__(self, base: str, version: str, api_key: str):
        self.base, self.version, self.api_key = base.rstrip("/"), version, api_key

    def request(self, method: str, path: str, payload=None):
        body = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(
            f"{self.base}/api/{self.version}/{path}", body, method=method,
            headers={"X-Api-Key": self.api_key, "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                data = response.read()
                return json.loads(data) if data else None
        except (urllib.error.URLError, json.JSONDecodeError) as error:
            raise GuardError(f"{method} {path} failed") from error


class QbitApi:
    def __init__(self, base: str, username: str, password: str):
        self.base = base.rstrip("/")
        jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        result = self._form("auth/login", {"username": username, "password": password}, raw=True)
        if result.strip() != b"Ok.":
            raise GuardError("qBittorrent authentication failed")

    def _form(self, path: str, fields: dict | None = None, raw: bool = False):
        request = urllib.request.Request(
            f"{self.base}/api/v2/{path}",
            data=None if fields is None else urllib.parse.urlencode(fields).encode(),
            headers={"Referer": self.base},
        )
        try:
            with self.opener.open(request, timeout=10) as response:
                body = response.read()
                return body if raw else (json.loads(body) if body else None)
        except (urllib.error.URLError, json.JSONDecodeError) as error:
            raise GuardError(f"qBittorrent {path} failed") from error

    def torrents(self) -> list[dict]:
        return self._form("torrents/info")

    def stop(self, hashes: list[str]) -> None:
        if hashes:
            self._form("torrents/stop", {"hashes": "|".join(hashes)})

    def start(self, hashes: list[str]) -> None:
        if hashes:
            self._form("torrents/start", {"hashes": "|".join(hashes)})


def read_line(path: pathlib.Path) -> str:
    try:
        return path.read_text().strip()
    except OSError as error:
        raise GuardError(f"required credential file is unavailable: {path.name}") from error


def read_api_key(config_root: pathlib.Path, app: str) -> str:
    try:
        value = ET.parse(config_root / app / "config.xml").findtext("ApiKey")
    except (OSError, ET.ParseError) as error:
        raise GuardError(f"cannot read {app} API key") from error
    if not value:
        raise GuardError(f"{app} API key is empty")
    return value


class Guard:
    def __init__(self, args):
        self.args = args
        self.state_path = pathlib.Path(args.state_file)
        self.state = load_state(self.state_path)
        secret_root = pathlib.Path(args.secret_root)
        self.qbit = QbitApi(
            f"http://{args.lan_ip}:8080",
            read_line(secret_root / "qbittorrent-user"),
            read_line(secret_root / "qbittorrent-password"),
        )
        config_root = pathlib.Path(args.config_root)
        self.apps = {
            "radarr": JsonApi(f"http://{args.lan_ip}:7878", "v3", read_api_key(config_root, "radarr")),
            "sonarr": JsonApi(f"http://{args.lan_ip}:8989", "v3", read_api_key(config_root, "sonarr")),
        }

    def save(self) -> None:
        atomic_json(self.state_path, self.state)

    def latch(self) -> None:
        if not self.state["latched"]:
            self.state["latched"] = True
            self.save()  # Persistence precedes remote changes.
        for name, api in self.apps.items():
            config = api.request("GET", "config/indexer")
            if name not in self.state["apps"] and int(config.get("rssSyncInterval", 0)) != 0:
                self.state["apps"][name] = {"rssSyncInterval": config["rssSyncInterval"], "applied": False}
                self.save()
            if name in self.state["apps"] and not self.state["apps"][name].get("applied", False):
                # A zero value after a restart means the prior guarded PUT reached the app.
                if int(config.get("rssSyncInterval", 0)) != 0:
                    config["rssSyncInterval"] = 0
                    api.request("PUT", "config/indexer", config)
                self.state["apps"][name]["applied"] = True
                self.save()

        torrents = self.qbit.torrents()
        changed = set(self.state["torrents"])
        pending = set(self.state["torrentPending"])
        to_stop = [
            item["hash"] for item in torrents
            if float(item.get("progress", 0)) < 1 and item.get("state") not in INCOMPLETE_STOPPED_STATES
        ]
        pending.update(to_stop)
        self.state["torrentPending"] = sorted(pending)
        self.save()
        self.qbit.stop(to_stop)
        if pending:
            verification = {item["hash"]: item for item in self.qbit.torrents()}
            failed = [
                h for h in pending
                if h in verification and verification[h].get("state") not in INCOMPLETE_STOPPED_STATES
            ]
            if failed:
                raise GuardError(f"qBittorrent did not stop {len(failed)} incomplete torrent(s)")
            changed.update(h for h in pending if h in verification)
            self.state["torrents"] = sorted(changed)
            self.state["torrentPending"] = []
            self.save()

    def reset(self, free_bytes: int) -> None:
        if not self.state["latched"]:
            print("disk guard is not latched")
            return
        if free_bytes < self.args.warn_gib * GIB:
            raise GuardError(f"reset requires at least {self.args.warn_gib} GiB free")
        for name, saved in list(self.state["apps"].items()):
            config = self.apps[name].request("GET", "config/indexer")
            if saved.get("applied", False) and int(config.get("rssSyncInterval", 0)) == 0:
                config["rssSyncInterval"] = saved["rssSyncInterval"]
                self.apps[name].request("PUT", "config/indexer", config)
            del self.state["apps"][name]
            self.save()

        torrents = {item["hash"]: item for item in self.qbit.torrents()}
        to_start = [
            hash_value for hash_value in self.state["torrents"]
            if hash_value in torrents
            and float(torrents[hash_value].get("progress", 0)) < 1
            and torrents[hash_value].get("state") in INCOMPLETE_STOPPED_STATES
        ]
        self.qbit.start(to_start)
        self.state = {"latched": False, "apps": {}, "torrents": [], "torrentPending": []}
        self.save()
        print("disk guard reset; only guard-managed settings and torrents were restored")


def free_bytes(args) -> int:
    override = os.environ.get("ARR_GUARD_TEST_FREE_BYTES")
    if override is not None:
        if os.environ.get("ARR_GUARD_TEST_MODE") != "1":
            raise GuardError("free-space override requires ARR_GUARD_TEST_MODE=1")
        return int(override)
    return shutil.disk_usage(args.data_path).free


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("check", "daemon", "reset", "status"))
    parser.add_argument("--lan-ip", default=os.environ.get("LAN_IP"))
    parser.add_argument("--data-path", default="/srv/arr/data")
    parser.add_argument("--state-file", default="/srv/arr/state/disk-guard.json")
    parser.add_argument("--secret-root", default="/srv/arr/secrets")
    parser.add_argument("--config-root", default="/srv/arr/config")
    parser.add_argument("--warn-gib", type=int, default=40)
    parser.add_argument("--block-gib", type=int, default=30)
    parser.add_argument("--interval", type=int, default=15)
    args = parser.parse_args()
    if args.command not in ("status",) and not args.lan_ip:
        parser.error("--lan-ip or LAN_IP is required")
    if args.block_gib >= args.warn_gib:
        parser.error("block threshold must be lower than warning threshold")
    return args


def run() -> int:
    args = parse_args()
    state_path = pathlib.Path(args.state_file)
    if args.command == "status":
        print(json.dumps(load_state(state_path), indent=2, sort_keys=True))
        return 0
    lock_path = state_path.with_suffix(".lock")
    lock_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with lock_path.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("another disk guard process owns the lock")
            return 0
        guard = Guard(args)
        while True:
            available = free_bytes(args)
            if args.command == "reset":
                guard.reset(available)
                return 0
            if available < args.warn_gib * GIB:
                print(f"warning: data filesystem has {available / GIB:.1f} GiB free", file=sys.stderr)
            if available < args.block_gib * GIB or guard.state["latched"]:
                guard.latch()
            if args.command == "check":
                return 0
            time.sleep(args.interval)


if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except GuardError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
