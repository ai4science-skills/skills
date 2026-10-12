"""Offline contract tests; no scanner or vendored skill is executed."""

import copy
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

from normalize_findings import normalize
from trust_common import ValidationError


SOURCE = {"repository": "example/research", "commit": "a" * 40, "path": "skills/example"}
FILES = [
    {"path": "skills/example/SKILL.md", "sha256": "1" * 64},
    {"path": "skills/example/scripts/check.py", "sha256": "2" * 64},
]


def inputs():
    target = {"schema": "ai4s.static-scan-target/v0", "source": copy.deepcopy(SOURCE),
              "files": copy.deepcopy(FILES)}
    receipt = {"schema": "ai4s.static-scan-receipt/v0", "source": copy.deepcopy(SOURCE),
               "producer": {"name": "example-static-scanner", "sha256": "3" * 64},
               "status": "COMPLETE", "files": copy.deepcopy(FILES), "findings": [], "errors": []}
    return target, receipt


class NormalizeFindingsTests(unittest.TestCase):
    def test_complete_zero_findings_stays_blocked(self):
        target, receipt = inputs()
        report = normalize(target, receipt)
        self.assertEqual(report["decision"], "BLOCKED")
        self.assertFalse(report["installable"])
        self.assertEqual(report["producer_provenance"], "CALLER_ASSERTED")
        self.assertEqual(report["coverage_claim"], "COMPLETE")
        self.assertEqual(report["unobserved_facets"][-1], "FRESHNESS")
        self.assertEqual(report, normalize(copy.deepcopy(target), copy.deepcopy(receipt)))

    def test_complete_with_findings_stays_blocked_and_preserves_findings(self):
        target, receipt = inputs()
        receipt["findings"] = [{"rule": "R-1", "severity": "HIGH", "path": FILES[0]["path"],
                                "line": 2, "message": "credential-like literal"}]
        report = normalize(target, receipt)
        self.assertEqual(report["decision"], "BLOCKED")
        self.assertEqual(report["findings"], receipt["findings"])

    def test_incomplete_requires_error_and_keeps_unreported_paths(self):
        target, receipt = inputs()
        receipt.update(status="ERROR", files=receipt["files"][:1], errors=["READ_ERROR"])
        report = normalize(target, receipt)
        self.assertEqual(report["reason"], "SCAN_INCOMPLETE")
        self.assertEqual(report["unreported_paths"], [FILES[1]["path"]])
        receipt["errors"] = []
        with self.assertRaises(ValidationError):
            normalize(target, receipt)

    def test_exact_coverage_and_hash_required(self):
        for mutation in ("missing", "wrong-hash", "extra", "duplicate", "case-alias"):
            with self.subTest(mutation=mutation):
                target, receipt = inputs()
                if mutation == "missing":
                    receipt["files"].pop()
                elif mutation == "wrong-hash":
                    receipt["files"][0]["sha256"] = "f" * 64
                elif mutation == "extra":
                    receipt["files"].append({"path": "skills/example/extra.txt", "sha256": "4" * 64})
                elif mutation == "duplicate":
                    receipt["files"].append(copy.deepcopy(receipt["files"][0]))
                else:
                    receipt["files"].append({"path": "skills/example/skill.md", "sha256": "4" * 64})
                with self.assertRaises(ValidationError):
                    normalize(target, receipt)

    def test_source_and_path_binding(self):
        for mutation in ("commit", "repository", "path", "outside", "traversal", "empty"):
            with self.subTest(mutation=mutation):
                target, receipt = inputs()
                if mutation in ("commit", "repository", "path"):
                    receipt["source"][mutation] = "b" * 40 if mutation == "commit" else "other/research"
                elif mutation == "outside":
                    receipt["files"][0]["path"] = "elsewhere/SKILL.md"
                elif mutation == "traversal":
                    target["files"][0]["path"] = "skills/example/../secret.txt"
                else:
                    target["files"] = []
                with self.assertRaises(ValidationError):
                    normalize(target, receipt)

    def test_case_colliding_ancestor_is_rejected(self):
        target, receipt = inputs()
        target["files"] = [
            {"path": "skills/example/Scripts/first.py", "sha256": "1" * 64},
            {"path": "skills/example/scripts/second.py", "sha256": "2" * 64},
        ]
        receipt["files"] = copy.deepcopy(target["files"])
        with self.assertRaises(ValidationError):
            normalize(target, receipt)

    def test_claimed_success_cannot_hide_errors(self):
        target, receipt = inputs()
        receipt["errors"] = ["SCANNER_ERROR"]
        with self.assertRaises(ValidationError):
            normalize(target, receipt)
        receipt.update(status="TIMEOUT", errors=["READ_ERROR"])
        with self.assertRaises(ValidationError):
            normalize(target, receipt)

    def test_findings_need_covered_file_and_nonduplicate_identity(self):
        target, receipt = inputs()
        finding = {"rule": "R-1", "severity": "HIGH", "path": FILES[0]["path"],
                   "line": 1, "message": "finding"}
        receipt["findings"] = [finding, copy.deepcopy(finding)]
        with self.assertRaises(ValidationError):
            normalize(target, receipt)
        receipt["findings"] = [dict(finding, path="skills/example/unknown.txt")]
        with self.assertRaises(ValidationError):
            normalize(target, receipt)

    def test_cli_does_not_accept_duplicate_json_or_missing_file_as_clean(self):
        script = pathlib.Path(__file__).with_name("normalize_findings.py")
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            target, receipt = inputs()
            target_path = root / "target.json"
            receipt_path = root / "receipt.json"
            target_path.write_text(json.dumps(target), encoding="utf-8")
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            command = [sys.executable, "-I", "-S", "-B", str(script), "--target", str(target_path),
                       "--receipt", str(receipt_path)]
            process = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(process.returncode, 2, process.stderr)
            self.assertEqual(json.loads(process.stdout)["decision"], "BLOCKED")
            receipt_path.write_text('{"schema":"x","schema":"y"}', encoding="utf-8")
            process = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(process.returncode, 2)
            self.assertEqual(json.loads(process.stdout)["reason"], "INVALID_OR_UNAVAILABLE_INPUT")
            receipt_path.unlink()
            process = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(process.returncode, 2)
            self.assertEqual(json.loads(process.stdout)["reason"], "INVALID_OR_UNAVAILABLE_INPUT")


if __name__ == "__main__":
    unittest.main()
