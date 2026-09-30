"""Offline inventory/contract fixtures, not scanner or sandbox evaluations."""
import copy
import hashlib
import json
import pathlib
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

import security_prerequisites as preflight

ROOT = pathlib.Path(__file__).resolve().parents[1]
REVISION = "1" * 40


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="ai4s-prerequisite-")
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)

    def write(self, path, raw):
        destination = self.root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
        return destination

    def report(self):
        return preflight.validate_report(preflight.inventory(self.root, REVISION))

    def test_fresh_root_blocks_every_unperformed_stage(self):
        report = self.report()
        self.assertEqual(len(report["prerequisites"]), 15)
        self.assertTrue(all(item["availability"] == "MISSING" for item in report["prerequisites"]))
        self.assertEqual({stage["execution"] for stage in report["stages"]}, {"NOT_RUN"})
        self.assertEqual(report["source_coverage"], {"status": "NOT_RUN", "receipts": []})
        self.assertEqual(report["reproducibility"], {"catalog": "NOT_RUN", "dashboard": "NOT_RUN"})

    def test_all_present_files_still_grant_no_authority(self):
        for path in preflight.PATHS:
            self.write(path, b"{}\n" if path.endswith(".json") else b"inert unapproved bytes\n")
        report = self.report()
        self.assertTrue(all(item["availability"] == "PRESENT_UNVERIFIED" for item in report["prerequisites"]))
        self.assertEqual(report["decision"], "BLOCKED")
        self.assertFalse(report["installable"])
        self.assertEqual(set(report["facets"].values()), {"UNOBSERVED"})
        self.assertTrue(all(stage["receipt"] is None and stage["blockers"] for stage in report["stages"]))

    def test_complete_raw_byte_hash_is_only_unverified_observation(self):
        raw = b'{"version":"unknown"}\n'
        self.write("tools/tools.lock.json", raw)
        item = next(item for item in self.report()["prerequisites"] if item["path"] == "tools/tools.lock.json")
        self.assertEqual(item["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(item["reason"], "NO_APPROVED_CONTRACT")

    def test_corrupt_duplicate_nonfinite_unicode_and_deep_json_rejected(self):
        for raw in (b"broken", b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":1e9999}',
                    b'{"a":"\\ud800"}', b"\xff", b"[" * 2000 + b"0" + b"]" * 2000,
                    b"[" * 40 + b"0" + b"]" * 40):
            with self.subTest(raw_length=len(raw)):
                self.write("tools/tools.lock.json", raw)
                item = next(item for item in self.report()["prerequisites"] if item["path"] == "tools/tools.lock.json")
                self.assertEqual(item["availability"], "REJECTED")
                self.assertIsNone(item["sha256"])

    def test_oversize_input_rejected(self):
        self.write("tools/ai4s_audit.py", b"x" * (preflight.MAX_BYTES + 1))
        item = next(item for item in self.report()["prerequisites"] if item["path"] == "tools/ai4s_audit.py")
        self.assertEqual(item["reason"], "OVERSIZE")
        self.assertEqual(preflight.MAX_TOTAL_BYTES, 15 * preflight.MAX_BYTES)

    def test_missing_and_nonregular_inputs_are_distinct(self):
        (self.root / "tools" / "bootstrap_tools.py").mkdir(parents=True)
        observations = {item["path"]: item for item in self.report()["prerequisites"]}
        self.assertEqual(observations["tools/bootstrap_tools.py"]["reason"], "NON_REGULAR")
        self.assertEqual(observations["tools/tools.lock.json"]["reason"], "ABSENT")

    def test_observed_target_reparse_refused_before_open(self):
        target = self.write("tools/ai4s_audit.py", b"sentinel")
        original = pathlib.Path.lstat
        def observed(path):
            if path == target:
                return types.SimpleNamespace(st_mode=stat.S_IFREG, st_file_attributes=0x400)
            return original(path)
        with mock.patch.object(pathlib.Path, "lstat", observed), mock.patch.object(preflight.os, "open", side_effect=AssertionError("must not open")):
            item = next(item for item in self.report()["prerequisites"] if item["path"] == "tools/ai4s_audit.py")
        self.assertEqual(item["reason"], "UNSAFE_PATH")

    def test_observed_parent_link_refused_before_open(self):
        parent = self.root / "tools"
        parent.mkdir()
        original = pathlib.Path.lstat
        def observed(path):
            if path == parent:
                return types.SimpleNamespace(st_mode=stat.S_IFLNK, st_file_attributes=0)
            return original(path)
        with mock.patch.object(pathlib.Path, "lstat", observed), mock.patch.object(preflight.os, "open", side_effect=AssertionError("must not open")):
            observations = self.report()["prerequisites"]
        self.assertTrue(all(item["reason"] == "UNSAFE_PATH" for item in observations if item["path"].startswith("tools/")))

    def test_observed_root_link_rejected(self):
        with mock.patch.object(preflight, "_linked", return_value=True):
            with self.assertRaises(preflight.PrerequisiteError):
                preflight.inventory(self.root, REVISION)

    def test_unreadable_input_is_rejected_not_clean(self):
        self.write("tools/ai4s_audit.py", b"sentinel")
        with mock.patch.object(preflight.os, "open", side_effect=PermissionError()):
            item = next(item for item in self.report()["prerequisites"] if item["path"] == "tools/ai4s_audit.py")
        self.assertEqual(item["reason"], "UNREADABLE")

    def test_sentinel_scanner_and_build_modules_never_execute(self):
        sentinel = self.root / "executed"
        raw = ("from pathlib import Path\nPath(" + repr(str(sentinel)) + ").write_text('EXECUTED')\n").encode()
        for path in preflight.PATHS:
            if path.endswith(".py"):
                self.write(path, raw)
        with mock.patch.object(subprocess, "run", side_effect=AssertionError("no process launch")):
            report = self.report()
        self.assertFalse(sentinel.exists())
        self.assertEqual({stage["execution"] for stage in report["stages"]}, {"NOT_RUN"})

    def test_git_config_filters_and_stale_outputs_are_not_consumed(self):
        for path in (".git/config", ".gitattributes", "generated/catalog.json", "generated/site/index.html"):
            self.write(path, b"FAKE_AUTH_FILTER_STALE_CANARY")
        encoded = preflight.encode(self.report())
        self.assertNotIn(b"FAKE_AUTH_FILTER_STALE_CANARY", encoded)
        self.assertTrue(all(item["availability"] == "MISSING" for item in self.report()["prerequisites"]))

    def test_reports_deterministic_across_independent_roots(self):
        self.write("tools/tools.lock.json", b"{}\n")
        with tempfile.TemporaryDirectory(prefix="ai4s-prerequisite-second-") as other:
            path = pathlib.Path(other) / "tools" / "tools.lock.json"
            path.parent.mkdir()
            path.write_bytes(b"{}\n")
            second = preflight.inventory(other, REVISION)
        self.assertEqual(preflight.encode(self.report()), preflight.encode(second))
        self.assertNotIn(str(self.root).encode(), preflight.encode(second))
        # Inventory determinism is not catalog/dashboard build reproducibility.
        self.assertEqual(second["reproducibility"], {"catalog": "NOT_RUN", "dashboard": "NOT_RUN"})

    def test_mutable_or_noncanonical_revisions_rejected(self):
        for revision in ("main", "v1", "A" * 40, "1" * 39, "../../escape", None):
            with self.subTest(revision=revision), self.assertRaises(preflight.PrerequisiteError):
                preflight.inventory(self.root, revision)

    def test_contract_rejects_forged_success_authority_and_duplicate_coverage(self):
        report = self.report()
        corruptions = []
        for key, value in (("decision", "PASS"), ("installable", True), ("trust", {"checker_revision": REVISION}),
                           ("source_coverage", {"status": "PASS", "receipts": ["fake"]}),
                           ("reproducibility", {"catalog": "PASS", "dashboard": "NOT_RUN"})):
            damaged = copy.deepcopy(report)
            damaged[key] = value
            corruptions.append(damaged)
        damaged = copy.deepcopy(report)
        damaged["stages"][0]["execution"] = "PASS"
        corruptions.append(damaged)
        damaged = copy.deepcopy(report)
        damaged["prerequisites"][1] = damaged["prerequisites"][0]
        corruptions.append(damaged)
        for damaged in corruptions:
            with self.assertRaises(preflight.PrerequisiteError):
                preflight.validate_report(damaged)

    def test_schema_structure_and_known_contract_constraints(self):
        contracts = json.loads((ROOT / "schema/security-prerequisites.schema.json").read_bytes())
        schema = contracts["$defs"]["inventory"]
        report = self.report()
        self.assertEqual(set(schema["required"]), set(report))
        self.assertFalse(schema["additionalProperties"])
        for key in ("schema", "decision", "installable", "revision_provenance", "source_coverage", "reproducibility"):
            self.assertEqual(schema["properties"][key]["const"], report[key])
        self.assertEqual(schema["properties"]["prerequisites"]["items"]["properties"]["path"]["enum"], list(preflight.PATHS))

    def test_malformed_report_field_types_have_typed_failure(self):
        for value in ([], {}, None, 1, True):
            report = self.report()
            report["prerequisites"][0].update(availability="REJECTED", reason=value)
            with self.subTest(value=value), self.assertRaises(preflight.PrerequisiteError):
                preflight.validate_report(report)
        with self.assertRaises(preflight.PrerequisiteError):
            preflight.inventory(None, REVISION)

    def test_cli_reports_blocked_and_sanitizes_invalid_inputs(self):
        script = ROOT / "tools/security_prerequisites.py"
        for root, revision in ((self.root, REVISION), (self.root / "absent", "main")):
            run = subprocess.run([sys.executable, "-I", "-S", "-B", str(script), "--root", str(root), "--revision", revision], capture_output=True, check=False, timeout=10)
            self.assertEqual(run.returncode, 2)
            report = json.loads(run.stdout)
            self.assertEqual(report["decision"], "BLOCKED")
            if report["schema"] == "ai4s.security-prerequisites/error-v0":
                contract = json.loads((ROOT / "schema/security-prerequisites.schema.json").read_bytes())["$defs"]["error"]
                self.assertEqual(set(contract["required"]), set(report))
                for key, value in report.items():
                    self.assertEqual(contract["properties"][key]["const"], value)
            else:
                preflight.validate_report(report)
            self.assertEqual(run.stderr, b"")
            self.assertNotIn(str(self.root).encode(), run.stdout)


class WorkflowTests(unittest.TestCase):
    def test_json_syntax_yaml_and_event_permission_contract(self):
        workflow = json.loads((ROOT / ".github/workflows/security-prerequisites.yml").read_bytes())
        self.assertEqual(set(workflow["on"]), {"pull_request", "push", "schedule", "workflow_dispatch"})
        self.assertEqual(workflow["on"]["push"]["branches"], ["main"])
        self.assertEqual(workflow["on"]["schedule"], [{"cron": "17 6 * * 1"}])
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        job = workflow["jobs"]["prerequisites"]
        self.assertEqual(job["timeout-minutes"], 20)
        self.assertEqual(job["runs-on"], "ubuntu-latest")
        self.assertNotIn("continue-on-error", json.dumps(workflow))
        self.assertTrue(job["steps"][0]["run"].endswith("exit 2\n"))
        self.assertEqual(job["steps"][1]["if"], "${{ always() }}")

    def test_no_candidate_checkout_token_consumption_or_code_execution(self):
        workflow = json.loads((ROOT / ".github/workflows/security-prerequisites.yml").read_bytes())
        for step in workflow["jobs"]["prerequisites"]["steps"]:
            self.assertNotIn("uses", step)
            script = step["run"]
            for forbidden in ("${{", "git ", "python", "curl", "wget", "node ", "github.token", "secrets.", "|| true", "generated/"):
                self.assertNotIn(forbidden, script)
            self.assertTrue(all(not line.rstrip().endswith("\\") for line in script.splitlines()))
        summary = workflow["jobs"]["prerequisites"]["steps"][1]
        self.assertEqual(set(summary["env"]), {"SECURITY_EVENT", "SECURITY_TRIGGER_SHA", "SECURITY_HEAD_SHA", "SECURITY_BASE_SHA", "SECURITY_WORKFLOW_SHA", "SECURITY_RUN_ID", "SECURITY_RUN_ATTEMPT"})
        self.assertIn("^[0-9a-f]{40}$", summary["run"])
        self.assertIn("^[0-9]{1,20}$", summary["run"])
        self.assertLess(len(summary["run"].encode()), 4096)
        self.assertIn("not an independent security gate", summary["run"])


if __name__ == "__main__":
    unittest.main()
