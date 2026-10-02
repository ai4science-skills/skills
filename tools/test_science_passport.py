"""Offline tests for the static skill passport; no skill execution or network."""

import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import science_passport as passport


ROOT = pathlib.Path(__file__).resolve().parents[1]
PLUGIN = "szl-science-skills"
SKILL = "szl-research-anatomy"


class SciencePassportTests(unittest.TestCase):
    def test_source_and_fixture_are_exactly_bound_but_not_evaluated(self):
        report = passport.generate(ROOT, PLUGIN, SKILL)
        self.assertEqual(report["decision"], "STATIC_PREVIEW_ONLY")
        registry = json.loads((ROOT / "registry.json").read_bytes())
        indexed = next(entry for entry in registry["plugins"] if entry["name"] == PLUGIN)
        self.assertEqual(report["source"]["commit"], indexed["sha"])
        self.assertEqual(report["observations"]["skill_execution"], "NOT_RUN")
        self.assertEqual(report["observations"]["claude_science_import"], "NOT_OBSERVED")
        self.assertEqual(report["observations"]["scientific_validity"], "NOT_EVALUATED")
        fixture = report["skill"]["fixture_candidates"][0]
        raw = (ROOT / "plugins" / PLUGIN / fixture["path"]).read_bytes()
        self.assertEqual(fixture["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(fixture["synthetic_status"], "NOT_VERIFIED")

    def test_preview_is_deterministic_and_does_not_run_skills_or_contact_hosts(self):
        with mock.patch("subprocess.run", side_effect=AssertionError("no process")), \
             mock.patch("science_passport.sync.urllib.request.urlopen",
                        side_effect=AssertionError("no network")):
            first = passport.encode(passport.generate(ROOT, PLUGIN, SKILL))
            second = passport.encode(passport.generate(ROOT, PLUGIN, SKILL))
        self.assertEqual(first, second)
        self.assertLess(len(first), 8192)

    def test_unknown_and_malformed_names_are_blocked(self):
        for plugin, skill in [("missing", SKILL), (PLUGIN, "missing"), ("../escape", SKILL)]:
            with self.subTest(plugin=plugin, skill=skill), self.assertRaises(passport.PassportError):
                passport.generate(ROOT, plugin, skill)

    def test_tampered_vendored_byte_blocks_preview(self):
        with tempfile.TemporaryDirectory(prefix="ai4s-passport-") as temporary:
            root = pathlib.Path(temporary)
            shutil.copy2(ROOT / "registry.json", root / "registry.json")
            shutil.copytree(ROOT / ".claude-plugin", root / ".claude-plugin")
            shutil.copytree(ROOT / "plugins", root / "plugins")
            target = root / "plugins" / PLUGIN / "skills" / SKILL / "SKILL.md"
            target.write_bytes(target.read_bytes() + b"\nchanged\n")
            with self.assertRaisesRegex(passport.PassportError, "INDEX_STATIC_CHECK_FAILED"):
                passport.generate(root, PLUGIN, SKILL)

    def test_duplicate_registry_key_blocks_preview(self):
        with tempfile.TemporaryDirectory(prefix="ai4s-passport-") as temporary:
            root = pathlib.Path(temporary)
            (root / "registry.json").write_bytes(b'{"name":"one","name":"two"}')
            (root / ".claude-plugin").mkdir()
            (root / "plugins").mkdir()
            with self.assertRaisesRegex(passport.PassportError, "INVALID_INDEX_INPUT"):
                passport.generate(root, PLUGIN, SKILL)

    def test_oversize_metadata_blocks_before_static_audit(self):
        with tempfile.TemporaryDirectory(prefix="ai4s-passport-") as temporary:
            root = pathlib.Path(temporary)
            (root / "registry.json").write_bytes(b"x" * (passport.MAX_METADATA_BYTES + 1))
            with mock.patch.object(passport.check, "audit", side_effect=AssertionError("too late")):
                with self.assertRaisesRegex(passport.PassportError, "OVERSIZE_INPUT"):
                    passport.generate(root, PLUGIN, SKILL)

    def test_tree_entry_budget_blocks_before_static_audit(self):
        with tempfile.TemporaryDirectory(prefix="ai4s-passport-") as temporary:
            root = pathlib.Path(temporary)
            shutil.copy2(ROOT / "registry.json", root / "registry.json")
            shutil.copytree(ROOT / ".claude-plugin", root / ".claude-plugin")
            (root / "plugins").mkdir()
            (root / "plugins" / "one").write_bytes(b"x")
            (root / "plugins" / "two").write_bytes(b"x")
            with mock.patch.object(passport, "MAX_TREE_ENTRIES", 1), \
                 mock.patch.object(passport.check, "audit", side_effect=AssertionError("too late")):
                with self.assertRaisesRegex(passport.PassportError, "TREE_ENTRY_BUDGET_EXCEEDED"):
                    passport.generate(root, PLUGIN, SKILL)

    def test_fixture_and_output_budgets_fail_without_truncation(self):
        with mock.patch.object(passport, "MAX_FIXTURES", 0):
            with self.assertRaisesRegex(passport.PassportError, "FIXTURE_BUDGET_EXCEEDED"):
                passport.generate(ROOT, PLUGIN, SKILL)
        with self.assertRaisesRegex(passport.PassportError, "OUTPUT_BUDGET_EXCEEDED"):
            passport.encode({"oversize": "x" * passport.MAX_OUTPUT_BYTES})

    def test_cli_success_and_blocked_output(self):
        tool = ROOT / "tools" / "science_passport.py"
        good = subprocess.run([sys.executable, "-B", str(tool), "--plugin", PLUGIN,
                               "--skill", SKILL], capture_output=True, check=False)
        self.assertEqual(good.returncode, 0, good.stderr.decode())
        self.assertEqual(json.loads(good.stdout)["decision"], "STATIC_PREVIEW_ONLY")
        bad = subprocess.run([sys.executable, "-B", str(tool), "--plugin", PLUGIN,
                              "--skill", "missing"], capture_output=True, check=False)
        self.assertEqual(bad.returncode, 2)
        self.assertEqual(json.loads(bad.stderr)["decision"], "BLOCKED")
        self.assertEqual(bad.stdout, b"")


if __name__ == "__main__":
    unittest.main()
