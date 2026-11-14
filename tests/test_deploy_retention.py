"""Retention must preserve live containers and complete rollback chains."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "retention", Path(__file__).parents[1] / "scripts/deploy/retention.py"
)
retention = importlib.util.module_from_spec(spec)
spec.loader.exec_module(retention)


def release(number, status="verified"):
    return {
        "id": f"{number}-1",
        "state": {"status": status, "new_image_id": f"sha256:image{number}"},
        "upload": {"image_ref": f"insurance-broker:{number:040x}-{number}-1"},
        "snapshot": {"images": {"web": f"sha256:image{number - 1}"}},
    }


class RetentionTests(unittest.TestCase):
    def test_six_releases_and_full_rollback_chain_are_kept(self):
        releases = [release(n) for n in range(1, 10)]
        images = [
            {"tag": r["upload"]["image_ref"], "id": r["state"]["new_image_id"]}
            for r in releases
        ]
        obsolete, tags, protected, _ = retention.plan(releases, [], images)
        self.assertEqual(obsolete, ["1-1", "2-1", "3-1"])
        # Release 4's rollback still needs image 3, even though release 3 expires.
        self.assertIn("sha256:image3", protected)
        self.assertEqual(tags, [r["upload"]["image_ref"] for r in releases[:2]])

    def test_stopped_container_and_incomplete_release_are_preserved(self):
        releases = [release(n) for n in range(1, 11)]
        releases[1]["state"]["status"] = "activating"
        obsolete, _, protected, _ = retention.plan(
            releases, [{"Image": "sha256:image1"}], []
        )
        self.assertEqual(obsolete, ["3-1", "4-1"])
        self.assertIn("sha256:image1", protected)
        self.assertIn("sha256:image2", protected)

    def test_unrelated_tags_and_required_rollback_tags_are_preserved(self):
        releases = [release(n) for n in range(1, 10)]
        tags = [
            {"tag": "other-project:old", "id": "sha256:other"},
            {"tag": "onlinepolis-rollback:1-1-web", "id": "sha256:obsolete"},
            {"tag": "onlinepolis-rollback:2-1-web", "id": "sha256:image3"},
            {"tag": "insurance-broker:custom", "id": "sha256:custom"},
        ]
        _, removed, _, _ = retention.plan(releases, [], tags)
        self.assertEqual(removed, ["onlinepolis-rollback:1-1-web"])

    def test_retention_floor(self):
        with self.assertRaises(ValueError):
            retention.plan([], [], [], keep=5)

    def test_expired_tags_are_collected_after_last_snapshot_expires(self):
        releases = [release(n) for n in range(5, 11)]
        tags = [
            {"tag": f"insurance-broker:{3:040x}-3-1", "id": "sha256:image3"},
            {"tag": "onlinepolis-rollback:3-1-web", "id": "sha256:image2"},
            {"tag": f"insurance-broker:{11:040x}-11-1", "id": "sha256:future"},
        ]
        _, removed, _, _ = retention.plan(releases, [], tags)
        self.assertEqual(removed, sorted(t["tag"] for t in tags[:2]))


if __name__ == "__main__":
    unittest.main()
