"""Coverage, byte binding, export and spec acceptance tests for the proposal."""
import hashlib
import importlib.util
import json
import sys
import unittest
from pathlib import Path
import test_static_metadata as metadata_fixtures

SPEC = importlib.util.spec_from_file_location("diagnostic_acceptance", Path(__file__).with_name("static_audit.py"))
AUDITOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDITOR)


class DiagnosticAcceptance(unittest.TestCase):
    def snapshot(self, description="Fixture when inspecting data.", extra="", **files):
        result = {"LICENSE": metadata_fixtures.LicenseTests.MIT, "demo/SKILL.md": ("---\nname: demo\ndescription: " + description + "\nlicense: MIT\n" + extra + "---\nBody\n").encode()}
        result.update(files)
        return result

    def audit(self, snapshot):
        source, errors = AUDITOR.source_evidence({"repo": "https://example.invalid/fixture", "commit": "a" * 40}, snapshot)
        return AUDITOR.audit_snapshot(snapshot, "demo", source, errors)

    def test_description_types_fail(self):
        for text in ("", "true", "[text]", "42"):
            with self.subTest(value=text):
                self.assertEqual(self.audit(self.snapshot(text))["spec"]["status"], "FAIL")

    def test_duplicate_keys_fail(self):
        self.assertEqual(self.audit(self.snapshot(extra="name: demo\n"))["spec"]["status"], "FAIL")

    def test_unsupported_yaml_is_not_invalid_or_pass(self):
        entry = self.audit(self.snapshot(description=">\n  Read fixture\n  when inspecting data."))
        self.assertEqual(entry["spec"]["status"], "UNSUPPORTED")
        self.assertEqual(entry["status"], "REVIEW")
        self.assertFalse(entry["installable"])

    def test_crlf_simple_frontmatter_supported_without_hash_normalization(self):
        snapshot = self.snapshot()
        original = snapshot["demo/SKILL.md"]
        first = self.audit(snapshot)
        snapshot["demo/SKILL.md"] = original.replace(b"\n", b"\r\n")
        second = self.audit(snapshot)
        self.assertEqual(second["spec"]["status"], "PASS")
        self.assertNotEqual(first["source"]["tree_sha256"], second["source"]["tree_sha256"])

    def test_compatibility_limit(self):
        self.assertEqual(self.audit(self.snapshot(extra="compatibility: " + "x" * 501 + "\n"))["spec"]["status"], "FAIL")

    def test_line_limit(self):
        snapshot = self.snapshot()
        text = snapshot["demo/SKILL.md"].decode()
        snapshot["demo/SKILL.md"] = (text + "\n".join(["body"] * (500 - len(text.splitlines())))).encode()
        entry = self.audit(snapshot)
        self.assertEqual(entry["spec"]["physical_lines"], 500)
        self.assertEqual(entry["spec"]["status"], "FAIL")

    def test_unknown_binary_and_utf8_coverage_fail_closed(self):
        for data in (b"\x00fixture", b"\xfffixture"):
            with self.subTest(data=data):
                entry = self.audit(self.snapshot(**{"demo/opaque.dat": data}))
                self.assertEqual(entry["status"], "BLOCKED")
                self.assertEqual(entry["security"]["status"], "INCOMPLETE")
                self.assertTrue(entry["security"]["coverage_errors"])

    def test_oversized_text_is_preserved_hashed_and_never_scanned(self):
        from unittest import mock
        payload = b"x" * (AUDITOR.MAX_TEXT_BYTES + 1)
        snapshot = self.snapshot(**{"demo/large.txt": payload})
        entry = self.audit(snapshot)
        covered = {item["path"]: item for item in entry["coverage"]["paths"]}
        self.assertEqual(covered["large.txt"]["status"], "SKIPPED_BYTE_LIMIT")
        self.assertEqual(covered["large.txt"]["sha256"], hashlib.sha256(payload).hexdigest())
        self.assertFalse(entry["coverage"]["complete"])
        self.assertEqual(entry["status"], "BLOCKED")

    def test_unreadable_skill_text_has_no_spec_pass_or_zero_line_count(self):
        snapshot = self.snapshot()
        snapshot["demo/SKILL.md"] = b"\xff"
        entry = self.audit(snapshot)
        self.assertEqual(entry["spec"]["status"], "NOT_RUN")
        self.assertIsNone(entry["spec"]["physical_lines"])
        self.assertEqual(entry["status"], "BLOCKED")

    def test_finding_limit_records_trailing_unscanned_paths(self):
        snapshot = self.snapshot(**{"demo/matches.txt": ("OPENAI_API_KEY\n" * (AUDITOR.MAX_FINDINGS + 1)).encode(), "demo/trailing.txt": b"text"})
        entry = self.audit(snapshot)
        covered = {item["path"]: item for item in entry["coverage"]["paths"]}
        self.assertEqual(covered["matches.txt"]["status"], "TRUNCATED_FINDINGS")
        self.assertEqual(covered["trailing.txt"]["status"], "NOT_SCANNED")
        self.assertFalse(entry["coverage"]["complete"])

    def test_uppercase_binary_and_script_extensions(self):
        entry = self.audit(self.snapshot(**{"demo/fixture.EXE": b"inert", "demo/fixture.PY": b"import json\n"}))
        self.assertIn("fixture.EXE", entry["dependencies"]["binaries"])
        self.assertIn("fixture.PY", entry["dependencies"]["scripts"])
        self.assertIn("json", entry["dependencies"]["python_imports"])
        self.assertEqual(entry["status"], "REVIEW")

    def test_python_parse_failure_remains_incomplete(self):
        entry = self.audit(self.snapshot(**{"demo/fixture.py": b"not valid python ; ("}))
        self.assertEqual(entry["status"], "BLOCKED")
        self.assertTrue(entry["dependencies"]["parse_errors"])

    def test_bounded_ast_does_not_parse_over_limit(self):
        from unittest import mock
        snapshot = self.snapshot(**{"demo/fixture.py": b" " * (AUDITOR.MAX_AST_BYTES + 1)})
        with mock.patch.object(AUDITOR.ast, "parse", side_effect=AssertionError("must not parse")) as parsed:
            entry = self.audit(snapshot)
        parsed.assert_not_called()
        self.assertEqual(entry["status"], "BLOCKED")

    def test_finding_limit_marks_incomplete(self):
        entry = self.audit(self.snapshot(**{"demo/matches.txt": ("OPENAI_API_KEY\n" * (AUDITOR.MAX_FINDINGS + 1)).encode()}))
        self.assertEqual(len(entry["security"]["findings"]), AUDITOR.MAX_FINDINGS)
        self.assertTrue(entry["security"]["coverage_errors"])

    def test_caller_digest_mismatch_blocks(self):
        snapshot = self.snapshot()
        source, errors = AUDITOR.source_evidence({"repo": "https://example.invalid/fixture", "commit": "a" * 40, "tree_sha256": "0" * 64}, snapshot)
        self.assertEqual(source["provenance"], "INVALID")
        self.assertTrue(errors)
        self.assertFalse(source["immutable"])

    def test_snapshot_digest_is_only_caller_binding(self):
        snapshot = self.snapshot()
        source, errors = AUDITOR.source_evidence({"repo": "https://example.invalid/fixture", "commit": "a" * 40, "tree_sha256": AUDITOR.tree_digest(snapshot)}, snapshot)
        self.assertFalse(errors)
        self.assertEqual(source["binding"], "MATCHES_CALLER_DIGEST")
        self.assertEqual(source["provenance"], "UNSIGNED_HONEST")
        self.assertFalse(source["immutable"])

    def test_receipt_covers_identical_record_bytes(self):
        entry = self.audit(self.snapshot())
        received = entry.pop("receipt")
        entry.pop("receipt_contract")
        self.assertEqual(received, hashlib.sha256(AUDITOR.canonical(entry)).hexdigest())

    def test_missing_license_and_restrictive_local_evidence_need_review(self):
        snapshot = self.snapshot()
        snapshot.pop("LICENSE")
        self.assertEqual(self.audit(snapshot)["status"], "REVIEW")
        snapshot["LICENSE"] = metadata_fixtures.LicenseTests.MIT
        snapshot["demo/LICENSE"] = b"All rights reserved, no copying."
        entry = self.audit(snapshot)
        self.assertEqual(entry["license"]["evidence_status"], "UNKNOWN")
        self.assertEqual(entry["status"], "REVIEW")

    def test_no_safety_or_network_clearance_from_no_matches(self):
        entry = self.audit(self.snapshot(**{"demo/notes.md": b"Fixture mentions pathogens and clinical dosing."}))
        self.assertEqual(entry["safety"], "UNASSESSED")
        self.assertEqual(entry["network"], "UNASSESSED")
        self.assertFalse(entry["installable"])
        self.assertEqual(entry["tests"]["status"], "NOT_RUN")

    def test_markdown_reference_failure(self):
        snapshot = self.snapshot()
        snapshot["demo/SKILL.md"] += b"[fixture](missing.txt)\n"
        self.assertEqual(self.audit(snapshot)["spec"]["status"], "FAIL")

    def test_source_prefix_aliases_normalize_to_same_identity(self):
        snapshot = self.snapshot()
        entries = []
        for prefix in ("skills", "skills/", "skills//", "skills/./"):
            source, errors = AUDITOR.source_evidence({"repo": "https://example.invalid/fixture", "commit": "a" * 40, "path_prefix": prefix}, snapshot)
            entries.append(AUDITOR.audit_snapshot(snapshot, "demo", source, errors))
        self.assertEqual(len({entry["id"] for entry in entries}), 1)
        self.assertEqual(entries[0]["source"]["path"], "skills/demo")

    def test_root_folder_identity_requires_explicit_context(self):
        snapshot = {"SKILL.md": b"---\nname: demo\ndescription: Fixture when checking data.\nlicense: MIT\n---\nBody\n", "LICENSE": metadata_fixtures.LicenseTests.MIT}
        source, errors = AUDITOR.source_evidence({"repo": "https://example.invalid/fixture", "commit": "a" * 40}, snapshot)
        entry = AUDITOR.audit_snapshot(snapshot, ".", source, errors, root_name="demo")
        self.assertEqual(entry["spec"]["status"], "PASS")
        self.assertEqual(entry["status"], "UNSIGNED_HONEST")
        self.assertEqual(AUDITOR.audit_snapshot(snapshot, ".", source, errors)["spec"]["status"], "UNSUPPORTED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
