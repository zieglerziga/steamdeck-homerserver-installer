#!/usr/bin/env python3
"""Idempotently bootstrap the managed ARR records without logging secrets."""

from __future__ import annotations

import getpass
import http.cookiejar
import copy
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


class BootstrapError(RuntimeError):
    pass


class Api:
    def __init__(self, base: str, api_key: str, version: str):
        self.base = base.rstrip("/")
        self.api_key = api_key
        self.version = version

    def request(self, method: str, path: str, payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(
            f"{self.base}/api/{self.version}/{path.lstrip('/')}",
            data=data,
            method=method,
            headers={"X-Api-Key": self.api_key, "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                body = response.read()
                return json.loads(body) if body else None
        except (urllib.error.URLError, json.JSONDecodeError) as error:
            # Deliberately omit request bodies, URLs with query strings, and responses.
            raise BootstrapError(f"{method} {path.split('?')[0]} failed") from error


def wait_ready(url: str, attempts: int = 30) -> None:
    for _ in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                if response.status < 500:
                    return
        except urllib.error.URLError:
            pass
        time.sleep(2)
    raise BootstrapError(f"service unavailable after {attempts * 2}s: {url}")


def read_api_key(app: str) -> str:
    path = pathlib.Path(f"/srv/arr/config/{app}/config.xml")
    try:
        value = ET.parse(path).findtext("ApiKey")
    except (OSError, ET.ParseError) as error:
        raise BootstrapError(f"cannot read generated API key for {app}") from error
    if not value:
        raise BootstrapError(f"generated API key missing for {app}")
    return value


def set_field(record: dict, name: str, value) -> None:
    for field in record.get("fields", []):
        if field.get("name", "").casefold() == name.casefold():
            field["value"] = value
            return
    raise BootstrapError(f"provider schema does not contain expected field {name}")


def find_schema(schemas: list[dict], needle: str) -> dict:
    matches = [s for s in schemas if needle.casefold() in str(s.get("implementation", "")).casefold()]
    if len(matches) != 1:
        raise BootstrapError(f"expected one {needle} provider schema, found {len(matches)}")
    return matches[0]


def upsert_named(api: Api, collection: str, desired: dict, name: str) -> None:
    records = [item for item in api.request("GET", collection) if item.get("name") == name]
    if len(records) > 1:
        raise BootstrapError(f"conflict: multiple records named {name}")
    if records:
        current = records[0]
        if current.get("implementation") != desired.get("implementation"):
            raise BootstrapError(f"conflict: {name} uses a different implementation")
        desired["id"] = current["id"]
        api.request("PUT", f"{collection}/{current['id']}", desired)
    else:
        api.request("POST", collection, desired)


def configure_host(api: Api, username: str, password: str) -> None:
    host = api.request("GET", "config/host")
    host.update(
        authenticationMethod="forms",
        authenticationRequired="enabled",
        username=username,
        password=password,
    )
    api.request("PUT", "config/host", host)


def configure_arr(api: Api, kind: str, qbit_user: str, qbit_password: str) -> None:
    root_path = "/data/library/movies" if kind == "radarr" else "/data/library/tv"
    roots = api.request("GET", "rootfolder")
    if not any(root.get("path") == root_path for root in roots):
        api.request("POST", "rootfolder", {"path": root_path})

    media = api.request("GET", "config/mediamanagement")
    media["copyUsingHardlinks"] = True
    api.request("PUT", "config/mediamanagement", media)

    indexer = api.request("GET", "config/indexer")
    indexer["rssSyncInterval"] = 15
    api.request("PUT", "config/indexer", indexer)

    schema = find_schema(api.request("GET", "downloadclient/schema"), "qbittorrent")
    schema.update(name="managed-qbittorrent", enable=True, removeCompletedDownloads=False)
    for key, value in {
        "host": "qbittorrent",
        "port": 8080,
        "useSsl": False,
        "username": qbit_user,
        "password": qbit_password,
        "category": kind,
    }.items():
        set_field(schema, key, value)
    api.request("POST", "downloadclient/test", schema)
    upsert_named(api, "downloadclient", schema, "managed-qbittorrent")

    definitions = api.request("GET", "qualitydefinition")
    for definition in definitions:
        # Servarr expresses limits as MiB per minute: 4096 MiB / 60 min.
        definition["maxSize"] = 68.27
        definition["preferredSize"] = min(float(definition.get("preferredSize", 68.27)), 68.27)
    api.request("PUT", "qualitydefinition/update", definitions)
    format_scores = configure_formats(api)
    profiles = api.request("GET", "qualityprofile")
    managed = [profile for profile in profiles if profile.get("name") == "managed-720p-1080p"]
    if len(managed) > 1:
        raise BootstrapError("conflict: multiple quality profiles named managed-720p-1080p")
    if not profiles:
        raise BootstrapError("no source quality profile is available")
    profile = copy.deepcopy(managed[0] if managed else profiles[0])
    profile["name"] = "managed-720p-1080p"
    profile["upgradeAllowed"] = False
    set_allowed_resolutions(profile.get("items", []))
    current = {item["format"]: item for item in profile.get("formatItems", [])}
    for format_id, score in format_scores.items():
        current[format_id] = {"format": format_id, "score": score}
    profile["formatItems"] = list(current.values())
    profile["minFormatScore"] = max(0, int(profile.get("minFormatScore", 0)))
    if managed:
        api.request("PUT", f"qualityprofile/{profile['id']}", profile)
    else:
        profile.pop("id", None)
        api.request("POST", "qualityprofile", profile)


def set_allowed_resolutions(items: list[dict]) -> None:
    for item in items:
        children = item.get("items", [])
        if children:
            set_allowed_resolutions(children)
            item["allowed"] = any(child.get("allowed", False) for child in children)
            continue
        resolution = int(item.get("quality", {}).get("resolution", 0))
        item["allowed"] = resolution in (720, 1080)


def configure_formats(api: Api) -> dict[int, int]:
    schemas = api.request("GET", "customformat/schema")
    specification = find_schema(schemas, "releasetitle")
    formats = {
        "managed-reject-unsupported-video": (specification, r"(?i)(?:\b(?:x|h)[ ._-]?265\b|\bhevc\b|\bav1\b|\b2160p\b|\b4k\b|\bremux\b)", -10000),
        "managed-prefer-h264": (specification, r"(?i)\b(?:x264|h[ ._-]?264|avc)\b", 100),
    }
    language_schemas = [schema for schema in schemas if "language" in str(schema.get("implementation", "")).casefold()]
    if language_schemas:
        language = language_schemas[0]
        value_field = next((field for field in language.get("fields", []) if field.get("name") == "value"), None)
        original = next(
            (option.get("value") for option in (value_field or {}).get("selectOptions", []) if option.get("name", "").casefold() == "original"),
            None,
        )
        if original is not None:
            formats["managed-prefer-original-audio"] = (language, original, 200)
    scores = {}
    existing = api.request("GET", "customformat")
    for name, (source_schema, pattern, score) in formats.items():
        spec = copy.deepcopy(source_schema)
        spec["name"] = name
        set_field(spec, "value", pattern)
        desired = {
            "name": name,
            "includeCustomFormatWhenRenaming": False,
            "specifications": [spec],
        }
        matches = [item for item in existing if item.get("name") == name]
        if len(matches) > 1:
            raise BootstrapError(f"conflict: multiple custom formats named {name}")
        if matches:
            desired["id"] = matches[0]["id"]
            saved = api.request("PUT", f"customformat/{matches[0]['id']}", desired)
        else:
            saved = api.request("POST", "customformat", desired)
        scores[int(saved["id"])] = score
    return scores


def qbit_login(base: str, username: str, password: str):
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    request = urllib.request.Request(
        f"{base}/api/v2/auth/login",
        data=urllib.parse.urlencode({"username": username, "password": password}).encode(),
        headers={"Referer": base},
    )
    try:
        with opener.open(request, timeout=10) as response:
            if response.read().strip() != b"Ok.":
                raise BootstrapError("qBittorrent authentication failed")
    except urllib.error.URLError as error:
        raise BootstrapError("qBittorrent authentication failed") from error
    return opener


def configure_qbit(base: str, username: str, password: str) -> None:
    opener = qbit_login(base, username, password)
    preferences = {
        "max_active_downloads": 2,
        "queueing_enabled": True,
        "upnp": False,
        "random_port": False,
        "save_path": "/data/downloads/complete",
        "temp_path": "/data/downloads/incomplete",
        "temp_path_enabled": True,
    }
    request = urllib.request.Request(
        f"{base}/api/v2/app/setPreferences",
        data=urllib.parse.urlencode({"json": json.dumps(preferences)}).encode(),
        headers={"Referer": base},
    )
    try:
        opener.open(request, timeout=10).close()
    except urllib.error.URLError as error:
        raise BootstrapError("qBittorrent preference update failed") from error


def configure_prowlarr(api: Api, username: str, password: str, arr_apis: dict[str, Api]) -> None:
    candidates = [
        item for item in api.request("GET", "indexer/schema")
        if str(item.get("definitionName", item.get("name", ""))).casefold() == "ncore"
    ]
    if len(candidates) != 1:
        raise BootstrapError(f"expected one nCore provider schema, found {len(candidates)}")
    schema = candidates[0]
    schema.update(name="managed-ncore", enable=True)
    set_field(schema, "definitionFile", "ncore")
    set_field(schema, "username", username)
    set_field(schema, "password", password)
    api.request("POST", "indexer/test", schema)
    upsert_named(api, "indexer", schema, "managed-ncore")

    schemas = api.request("GET", "applications/schema")
    for kind, port in (("radarr", 7878), ("sonarr", 8989)):
        app_schema = find_schema(schemas, kind)
        app_schema.update(name=f"managed-{kind}", syncLevel="fullSync", enable=True)
        set_field(app_schema, "prowlarrUrl", "http://prowlarr:9696")
        set_field(app_schema, "baseUrl", f"http://{kind}:{port}")
        set_field(app_schema, "apiKey", arr_apis[kind].api_key)
        api.request("POST", "applications/test", app_schema)
        upsert_named(api, "applications", app_schema, f"managed-{kind}")


def save_secret(name: str, value: str) -> None:
    directory = pathlib.Path("/srv/arr/secrets")
    directory.mkdir(mode=0o700, exist_ok=True)
    path = directory / name
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write(value + "\n")


def main() -> None:
    if os.geteuid() != 0:
        raise BootstrapError("bootstrap must run through sudo")
    lan_ip = os.environ["LAN_IP"]
    urls = {
        "radarr": f"http://{lan_ip}:7878",
        "sonarr": f"http://{lan_ip}:8989",
        "prowlarr": f"http://{lan_ip}:9696",
        "qbittorrent": f"http://{lan_ip}:8080",
    }
    for url in urls.values():
        wait_ready(url)

    admin_user = input("ARR administrator username: ").strip()
    admin_password = getpass.getpass("ARR administrator password: ")
    qbit_user = input("Current qBittorrent username [admin]: ").strip() or "admin"
    qbit_password = getpass.getpass("Current qBittorrent password: ")
    ncore_user = input("nCore username: ").strip()
    ncore_password = getpass.getpass("nCore password: ")
    if not all((admin_user, admin_password, qbit_password, ncore_user, ncore_password)):
        raise BootstrapError("empty credentials are not accepted")

    apis = {
        "radarr": Api(urls["radarr"], read_api_key("radarr"), "v3"),
        "sonarr": Api(urls["sonarr"], read_api_key("sonarr"), "v3"),
        "prowlarr": Api(urls["prowlarr"], read_api_key("prowlarr"), "v1"),
    }
    configure_qbit(urls["qbittorrent"], qbit_user, qbit_password)
    for kind in ("radarr", "sonarr"):
        configure_arr(apis[kind], kind, qbit_user, qbit_password)
        configure_host(apis[kind], admin_user, admin_password)
    configure_prowlarr(apis["prowlarr"], ncore_user, ncore_password, apis)
    configure_host(apis["prowlarr"], admin_user, admin_password)
    for name, value in {
        "arr-admin-user": admin_user,
        "arr-admin-password": admin_password,
        "qbittorrent-user": qbit_user,
        "qbittorrent-password": qbit_password,
        "ncore-user": ncore_user,
        "ncore-password": ncore_password,
    }.items():
        save_secret(name, value)
    print("managed application configuration completed")


if __name__ == "__main__":
    try:
        main()
    except (BootstrapError, KeyError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
