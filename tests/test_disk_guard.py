import fcntl
import importlib.util
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("disk_guard", ROOT / "scripts/disk_guard.py")
disk_guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(disk_guard)


class FakeApp:
    def __init__(self, interval=15, fail=False):
        self.config = {"id": 1, "rssSyncInterval": interval}
        self.fail = fail

    def request(self, method, path, payload=None):
        if self.fail and method == "PUT":
            raise disk_guard.GuardError("simulated API failure")
        if method == "GET":
            return dict(self.config)
        self.config = dict(payload)
        return dict(self.config)


class FakeQbit:
    def __init__(self, torrents):
        self.items = {item["hash"]: dict(item) for item in torrents}
        self.started = []

    def torrents(self):
        return [dict(item) for item in self.items.values()]

    def stop(self, hashes):
        for value in hashes:
            self.items[value]["state"] = "stoppedDL"

    def start(self, hashes):
        self.started.extend(hashes)
        for value in hashes:
            self.items[value]["state"] = "downloading"


class DiskGuardTest(unittest.TestCase):
    def make_guard(self, directory, torrents):
        guard = object.__new__(disk_guard.Guard)
        guard.args = type("Args", (), {"warn_gib": 40})()
        guard.state_path = pathlib.Path(directory) / "state.json"
        guard.state = {"latched": False, "apps": {}, "torrents": [], "torrentPending": []}
        guard.apps = {"radarr": FakeApp(), "sonarr": FakeApp()}
        guard.qbit = FakeQbit(torrents)
        return guard

    def test_latch_stops_only_incomplete_active_and_catches_new_torrents(self):
        with tempfile.TemporaryDirectory() as directory:
            guard = self.make_guard(directory, [
                {"hash": "active", "progress": 0.5, "state": "downloading"},
                {"hash": "complete", "progress": 1, "state": "uploading"},
                {"hash": "prior", "progress": 0.2, "state": "stoppedDL"},
            ])
            guard.latch()
            self.assertEqual(guard.state["torrents"], ["active"])
            self.assertEqual(guard.qbit.items["complete"]["state"], "uploading")
            self.assertEqual(guard.apps["radarr"].config["rssSyncInterval"], 0)
            guard.qbit.items["new"] = {"hash": "new", "progress": 0.1, "state": "downloading"}
            guard.latch()
            self.assertEqual(guard.state["torrents"], ["active", "new"])

    def test_reset_restores_only_guard_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            guard = self.make_guard(directory, [
                {"hash": "active", "progress": 0.5, "state": "downloading"},
                {"hash": "prior", "progress": 0.2, "state": "stoppedDL"},
            ])
            guard.latch()
            guard.reset(40 * disk_guard.GIB)
            self.assertEqual(guard.qbit.started, ["active"])
            self.assertEqual(guard.apps["radarr"].config["rssSyncInterval"], 15)
            self.assertFalse(guard.state["latched"])

    def test_latch_is_persisted_before_remote_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            guard = self.make_guard(directory, [])
            guard.apps["radarr"].fail = True
            with self.assertRaises(disk_guard.GuardError):
                guard.latch()
            state = disk_guard.load_state(guard.state_path)
            self.assertTrue(state["latched"])

    def test_concurrent_process_exits_before_accessing_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            state = pathlib.Path(directory) / "guard.json"
            lock_path = state.with_suffix(".lock")
            with lock_path.open("w") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                result = subprocess.run(
                    [sys.executable, ROOT / "scripts/disk_guard.py", "check", "--lan-ip", "127.0.0.1", "--state-file", state],
                    text=True, capture_output=True, check=False,
                )
            self.assertEqual(result.returncode, 0)
            self.assertIn("owns the lock", result.stdout)


if __name__ == "__main__":
    unittest.main()
