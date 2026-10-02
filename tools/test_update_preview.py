"""Offline update review regressions; candidate skill programs remain inert."""
import contextlib
import copy
import hashlib
import io
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

import sync
import update_preview as preview
from static_io import AuditBoundaryError
from trust_common import ValidationError


def write_catalog(root, sha="1", services=(), program=b"raise RuntimeError('must not execute')\n"):
    entry = {"name": "toy-plugin", "repo": "example/science", "ref": "v1", "sha": sha * 40,
             "path": "skills", "skills": ["toy-skill"], "description": "Synthetic fixture",
             "maintainer": "Test", "license": "MIT", "hosted_services": list(services)}
    registry = {"name": "toy-index", "owner": {"name": "Test"}, "description": "Fixture only",
                "version": "1", "plugins": [entry]}
    files = {"LICENSE": b"MIT fixture", "skills/toy-skill/SKILL.md": b"---\nname: toy-skill\n---\n",
             "skills/toy-skill/scripts/run.py": program}
    plugin = root / "plugins/toy-plugin"
    for name, raw in files.items():
        destination = plugin / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
    source = {key: entry[key] for key in ("repo", "ref", "sha", "path")}
    source["files_sha256"] = {name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()}
    (plugin / "SOURCE.json").write_text(json.dumps(source), encoding="utf-8")
    (root / "registry.json").write_text(json.dumps(registry), encoding="utf-8")
    return registry


class UpdatePreviewTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)
        self.before, self.after = self.root / "before", self.root / "after"
        write_catalog(self.before)
        write_catalog(self.after)

    def compare(self, occupied=()):
        return preview.compare(preview.load_catalog(self.before), preview.load_catalog(self.after), occupied)

    def test_same_catalog_is_no_change_and_never_executes_or_updates(self):
        with patch.object(sync, "fetch", side_effect=AssertionError("network forbidden")):
            report = self.compare()
        self.assertEqual(report["status"], "NO_CHANGE")
        self.assertFalse(report["installable"])
        self.assertFalse(report["automatic_update"])
        self.assertFalse(report["skill_code_executed"])
        self.assertEqual(report, self.compare())

    def test_source_code_and_new_network_disclosure_require_review(self):
        write_catalog(self.after, sha="2", services=["api.example.org - sends chosen rows; needs your own key"], program=b"changed\n")
        report = self.compare()
        change = report["changes"][0]
        self.assertEqual(report["status"], "REVIEW_REQUIRED")
        self.assertEqual(change["hosts_added"], ["api.example.org"])
        self.assertTrue(change["declared_service_change_requires_review"])
        self.assertEqual(change["files"][0]["path"], "skills/toy-skill/scripts/run.py")
        self.assertIn("UNSTRUCTURED", report["credentials"])

    def test_same_host_new_data_or_credential_declaration_is_visible(self):
        write_catalog(self.before, services=["api.example.org - public lookup without credentials"])
        write_catalog(self.after, services=["api.example.org - sends chosen rows with your own key"])
        change = self.compare()["changes"][0]
        self.assertEqual(change["hosts_added"], [])
        self.assertEqual(len(change["services_added"]), 1)
        self.assertTrue(change["declared_service_change_requires_review"])

    def test_personal_collision_preserves_both_names_and_qualified_identity(self):
        report = self.compare(["toy-skill"])
        self.assertEqual(report["status"], "REVIEW_REQUIRED")
        row = report["name_collisions"][0]
        self.assertTrue(row["occupied_by_caller"])
        self.assertEqual(row["candidate_identities"][0]["publisher_qualified_id"], "example/science/skills/toy-skill")
        self.assertEqual(row["candidate_identities"][0]["name"], "toy-skill")
        self.assertEqual(json.loads((self.after / "registry.json").read_text())["plugins"][0]["skills"], ["toy-skill"])

    def test_different_publishers_same_name_remain_distinct_collision(self):
        catalog = preview.load_catalog(self.after)
        second = copy.deepcopy(catalog["plugins"]["toy-plugin"])
        second["entry"]["repo"] = "another/science"
        catalog["plugins"]["another-plugin"] = second
        report = preview.compare(preview.load_catalog(self.before), catalog)
        identities = report["name_collisions"][0]["candidate_identities"]
        self.assertEqual(len({row["publisher_qualified_id"] for row in identities}), 2)

    def test_tampered_or_extra_file_is_blocked(self):
        for filename in ("skills/toy-skill/scripts/run.py", "extra.py"):
            with self.subTest(filename=filename):
                target = self.after / "plugins/toy-plugin" / filename
                target.write_bytes(b"unmanifested\n")
                with self.assertRaises(ValidationError):
                    preview.load_catalog(self.after)
                target.unlink()
                write_catalog(self.after)

    def test_identity_mismatch_duplicate_json_and_traversal_are_blocked(self):
        manifest = self.after / "plugins/toy-plugin/SOURCE.json"
        for value in ({"repo": "other/science"}, {"files_sha256": {"../escape": "a" * 64}}):
            with self.subTest(value=value):
                source = json.loads(manifest.read_text())
                source.update(value)
                manifest.write_text(json.dumps(source))
                with self.assertRaises(ValidationError):
                    preview.load_catalog(self.after)
                write_catalog(self.after)
        (self.after / "registry.json").write_bytes(b'{"name":"one","name":"two"}')
        with self.assertRaises(ValidationError):
            preview.load_catalog(self.after)

    def test_file_budget_is_enforced_before_reading_payload(self):
        target = self.after / "plugins/toy-plugin/large.bin"
        with target.open("wb") as handle:
            handle.truncate(sync.MAX_PLUGIN + 1)
        with self.assertRaises(AuditBoundaryError):
            preview.load_catalog(self.after)

    def test_reparse_or_link_capture_failure_is_blocked(self):
        with patch.object(preview, "inventory", side_effect=AuditBoundaryError("link-or-reparse-point")):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = preview.main(["--before", str(self.before), "--after", str(self.after)])
        self.assertEqual(result, 2)
        self.assertEqual(json.loads(output.getvalue())["status"], "BLOCKED")
        self.assertNotIn(str(self.root), output.getvalue())

    def test_secret_shaped_declaration_is_withheld(self):
        secret = "hf_" + "a" * 32
        write_catalog(self.after, services=["api.example.org - token " + secret])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = preview.main(["--before", str(self.before), "--after", str(self.after)])
        self.assertEqual(result, 2)
        self.assertNotIn(secret, output.getvalue())

    def test_version_only_change_is_review_required(self):
        registry = json.loads((self.after / "registry.json").read_text())
        registry["version"] = "2"
        (self.after / "registry.json").write_text(json.dumps(registry))
        report = self.compare()
        self.assertEqual(report["status"], "REVIEW_REQUIRED")
        self.assertEqual(report["registry_metadata_changed"], ["version"])

    def test_extra_plugin_and_control_characters_are_blocked(self):
        unexpected = self.after / "plugins/unlisted/SKILL.md"
        unexpected.parent.mkdir()
        unexpected.write_bytes(b"unlisted")
        with self.assertRaises(ValidationError):
            preview.load_catalog(self.after)
        unexpected.unlink()
        for service in ("api.example.org - tab\there", "api.example.org - invisible\x1bcode"):
            with self.subTest(service=service):
                write_catalog(self.after, services=[service])
                with self.assertRaises(ValidationError):
                    preview.load_catalog(self.after)


if __name__ == "__main__":
    unittest.main()
