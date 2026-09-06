import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("bootstrap", ROOT / "scripts/bootstrap.py")
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)


class FakeApi:
    def __init__(self, records):
        self.records = records
        self.calls = []

    def request(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        if method == "GET":
            return self.records
        return payload


class BootstrapTest(unittest.TestCase):
    def test_quality_filter_keeps_only_720p_and_1080p(self):
        items = [
            {"quality": {"resolution": 2160}, "allowed": True},
            {"quality": {"resolution": 1080}, "allowed": False},
            {"items": [
                {"quality": {"resolution": 720}, "allowed": False},
                {"quality": {"resolution": 480}, "allowed": True},
            ], "allowed": False},
        ]
        bootstrap.set_allowed_resolutions(items)
        self.assertFalse(items[0]["allowed"])
        self.assertTrue(items[1]["allowed"])
        self.assertTrue(items[2]["allowed"])
        self.assertTrue(items[2]["items"][0]["allowed"])
        self.assertFalse(items[2]["items"][1]["allowed"])

    def test_upsert_updates_one_stable_record(self):
        api = FakeApi([{"id": 7, "name": "managed", "implementation": "Thing"}])
        bootstrap.upsert_named(api, "items", {"name": "managed", "implementation": "Thing"}, "managed")
        self.assertEqual(api.calls[-1][0:2], ("PUT", "items/7"))

    def test_upsert_refuses_ambiguous_records(self):
        records = [
            {"id": 1, "name": "managed", "implementation": "Thing"},
            {"id": 2, "name": "managed", "implementation": "Thing"},
        ]
        with self.assertRaisesRegex(bootstrap.BootstrapError, "conflict"):
            bootstrap.upsert_named(FakeApi(records), "items", {}, "managed")

    def test_upsert_refuses_implementation_conflict(self):
        records = [{"id": 1, "name": "managed", "implementation": "Other"}]
        with self.assertRaisesRegex(bootstrap.BootstrapError, "conflict"):
            bootstrap.upsert_named(FakeApi(records), "items", {"implementation": "Thing"}, "managed")


if __name__ == "__main__":
    unittest.main()
