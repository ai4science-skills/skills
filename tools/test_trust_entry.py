"""Offline synthetic boundaries; no auditor/skill execution or remote calls."""
import contextlib
import copy
import dataclasses
import datetime as dt
import hashlib
import io
import json
import pathlib
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import trust_common as common
import trust_entry as trust

NOW = dt.datetime(2026, 9, 30, 6, tzinfo=dt.timezone.utc)
H = "a" * 64
COMMIT = "1" * 40


def locked_source():
    return SimpleNamespace(repository="example/science", commit=COMMIT,
                           archive_sha256="b" * 64, skill_tree_sha256="c" * 64,
                           hash_contract_id="ai4s.canonical-content-tree/v0-proposal",
                           skill_paths=("skills/toy/SKILL.md",), acquisition_status="PINNED_HASHED")


def entry():
    source = trust.Source("example/science", COMMIT, "skills/toy", "b" * 64, "c" * 64,
                          "ai4s.canonical-content-tree/v0-proposal", H)
    identity = hashlib.sha256(("example/science\0" + COMMIT + "\0skills/toy").encode()).hexdigest()
    facets = tuple((f, trust.Evidence("UNOBSERVED", "NONE", "Synthetic: not observed.")) for f in trust.Facet)
    gates = tuple((k, trust.Review("MISSING", None, "Synthetic: no human review.")) for k in trust.REVIEW_KINDS)
    return trust.Entry(identity, trust.State.CANDIDATE, source, facets, gates)


def diagnostic():
    src = {"repository": "https://github.com/example/science", "commit": COMMIT,
           "path_prefix": "", "provenance": "UNSIGNED_HONEST", "immutable": False,
           "snapshot_sha256": "d" * 64, "binding": "MATCHES_CALLER_DIGEST",
           "path": "skills/toy", "tree_sha256": "e" * 64}
    raw = {"schema_version": "ai4s.diagnostic-entry/review-v1",
           "id": hashlib.sha256((src["repository"] + "\0" + COMMIT + "\0skills/toy").encode()).hexdigest(),
           "name": "toy", "description": "Synthetic fixture only.", "source": src, "source_problems": [],
           "license": {"evidence_status": "DETECTED", "effective": "MIT"},
           "spec": {"status": "PASS", "problems": [], "unsupported": [], "profile": "bounded-subset-v1",
                    "physical_lines": 10, "checked_literal_markdown_links": []},
           "dependencies": {"manifests": [], "scripts": [], "binaries": [], "python_imports": [], "dynamic_import_files": [], "parse_errors": []},
           "security": {"status": "OBSERVATIONS_ONLY", "counts": {},
                        "findings": [], "coverage_errors": []},
           "tests": {"status": "NOT_RUN", "reason": "Skill code is never executed."},
           "evaluation": {"status": "NOT_MEASURED"}, "safety": "UNASSESSED", "network": "UNASSESSED",
           "installable": False, "status": "UNSIGNED_HONEST",
           "checker": {"name": "ai4s-audit-proposed", "version": trust.AUDITOR_VERSION}}
    return {"schema_version": "ai4s.diagnostic-catalog/review-v1", "checker_version": trust.AUDITOR_VERSION,
            "generated_at": "2026-09-30T04:00:00Z", "status": "UNSIGNED_HONEST", "completion": "COMPLETE",
            "input_errors": [], "inputs": [{"input": "input-1", "status": "COMPLETE",
                "coverage": {"complete": True, "scope": "all file content except root-level .git administrative metadata",
                             "excluded_paths": [], "files": 1, "bytes": 100, "entries": 1, "max_depth": 1},
                "snapshot_sha256": "d" * 64, "skills": 1}], "entries": [raw],
            "installable": False, "trust": "UNSIGNED_HONEST"}


def seal(doc):
    for row in doc["entries"]:
        core = {k: v for k, v in row.items() if k not in {"receipt", "receipt_contract"}}
        row["receipt"] = hashlib.sha256((json.dumps(core, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()).hexdigest()
        row["receipt_contract"] = trust.AUDITOR_RECEIPT
    return json.dumps(doc, ensure_ascii=False).encode()


def ingest(doc=None, sources=None):
    raw = seal(doc if doc is not None else diagnostic())
    return trust.ingest_diagnostic(raw, sources if sources is not None else (locked_source(),), H,
                                   hashlib.sha256(raw).hexdigest())


class JsonBoundaryTests(unittest.TestCase):
    def test_malformed_duplicate_nonfinite_and_unicode_refused(self):
        for raw in (b"", b"[] trailing", b"\xff", b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}',
                    b'{"a":1e999}', b'{"a":"\\ud800"}', b'{"\\ud800":0}'):
            with self.subTest(raw=raw), self.assertRaises(common.ValidationError):
                common.strict_json(raw)

    def test_depth_and_byte_limits(self):
        for raw in (b"[" * 34 + b"0" + b"]" * 34, b" " * (common.MAX_JSON_BYTES + 1)):
            with self.assertRaises(common.ValidationError):
                common.strict_json(raw)

    def test_portability_and_repository_identity(self):
        for path in ("../x", "/x", "C:/x", "x\\y", "x//y", "x/CON.txt", "x/aux", "x.", "x "):
            with self.subTest(path=path), self.assertRaises(common.ValidationError):
                common.portable_path(path, "path")
        self.assertEqual(common.repository("example/.github"), "example/.github")
        for repo in ("x/../y", "https://github.com/x/y", "x/.git", "x/repo.git", "x/."):
            with self.subTest(repo=repo), self.assertRaises(common.ValidationError):
                common.repository(repo)

    def test_missing_oversized_file_and_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            with self.assertRaises(common.ValidationError):
                common.load_json_file(root / "missing.json")
            target = root / "target.json"
            target.write_bytes(b'{"synthetic":true}')
            with self.assertRaises(common.ValidationError):
                common.load_json_file(target, max_bytes=2)
            self.assertEqual(common.load_json_file(target), {"synthetic": True})
            link = root / "link.json"
            try:
                link.symlink_to(target)
            except OSError:
                # Native Windows may lack link creation privileges; policy branch
                # is still checked with a mocked reparse attribute below.
                pass
            else:
                with self.assertRaises(common.ValidationError):
                    common.load_json_file(link)
            fake = SimpleNamespace(st_mode=0, st_file_attributes=0x400)
            with patch.object(pathlib.Path, "lstat", return_value=fake), self.assertRaises(common.ValidationError):
                common.load_json_file(target)


    def test_nonregular_files_and_invalid_limits_refused_before_open(self):
        for limit in (0, -1, True, common.MAX_JSON_BYTES + 1):
            with self.assertRaises(common.ValidationError):
                common.read_json_bytes("synthetic-unused", limit)
        fake_fifo = SimpleNamespace(st_mode=0o010000, st_file_attributes=0)
        with patch.object(pathlib.Path, "lstat", return_value=fake_fifo), patch.object(common.os, "open", side_effect=AssertionError("must not open special file")), self.assertRaises(common.ValidationError):
            common.read_json_bytes("synthetic-unused")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(common.ValidationError):
                common.read_json_bytes(tmp)


class EntryStateTests(unittest.TestCase):
    def test_roundtrip_keeps_every_facet_and_missing_review(self):
        parsed = trust.Entry.parse(entry().to_dict())
        self.assertEqual(parsed, entry())
        self.assertEqual(set(parsed.to_dict()["facets"]), {f.value for f in trust.Facet})
        self.assertFalse(parsed.to_dict()["installable"])

    def test_listing_never_follows_static_or_claimed_human_receipt(self):
        e = entry()
        fields = e.to_dict()
        fields["facets"]["STATIC"] = dataclasses.asdict(trust.Evidence("PASS", "COMPLETE", "Synthetic full subcheck.",
            (H,), "2026-09-30T04:00:00Z", "2026-10-01T04:00:00Z", H))
        fields["facets"]["STATIC"]["artifacts"] = [H]
        for gate in fields["human_gates"].values():
            gate.update(status="CLAIMED_APPROVED", receipt_sha256=H)
        reviewed = trust.transition(trust.Entry.parse(fields), "REVIEW", NOW)
        with self.assertRaises(common.ValidationError):
            trust.transition(reviewed, "LISTED", NOW)
        with self.assertRaises(common.ValidationError):
            trust.transition(e, "LISTED", NOW)
        fields["state"] = "LISTED"
        with self.assertRaises(common.ValidationError):
            trust.Entry.parse(fields)

    def test_complete_static_pass_does_not_fill_other_facets(self):
        fields = entry().to_dict()
        fields["facets"]["STATIC"].update(status="PASS", coverage="COMPLETE", artifacts=[H],
            checked_at="2026-09-30T04:00:00Z", expires_at="2026-10-01T04:00:00Z", checker_sha256=H)
        blockers = trust.listing_blockers(trust.Entry.parse(fields), NOW)
        self.assertIn("BEHAVIOR-required-evidence", blockers)
        self.assertIn("SCIENCE-required-evidence", blockers)
        self.assertIn("human-RIGHTS", blockers)

    def test_expiry_future_checks_and_missing_tests_are_blockers(self):
        fields = entry().to_dict()
        fields["facets"]["STATIC"].update(status="PASS", coverage="COMPLETE", artifacts=[H],
            checked_at="2026-09-29T04:00:00Z", expires_at="2026-09-30T04:00:00Z", checker_sha256=H)
        fields["facets"]["TEST"]["status"] = "MISSING"
        blockers = trust.listing_blockers(trust.Entry.parse(fields), NOW)
        self.assertIn("STATIC-not-current", blockers)
        self.assertIn("TEST-required-evidence", blockers)
        fields["facets"]["STATIC"].update(checked_at="2026-10-01T04:00:00Z", expires_at="2026-10-02T04:00:00Z")
        self.assertIn("STATIC-future-check", trust.listing_blockers(trust.Entry.parse(fields), NOW))

    def test_bad_facets_dates_and_unmeasured_evaluation_reject(self):
        variations = [
            ("status", "PASS"), ("coverage", "FULL"), ("checked_at", "2026-09-30"),
            ("checked_at", "2026-09-30T04:00:00+01:00"), ("checker_sha256", "main")]
        for key, value in variations:
            fields = entry().to_dict()
            fields["facets"]["STATIC"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(common.ValidationError):
                trust.Entry.parse(fields)
        fields = entry().to_dict()
        fields["facets"]["EVALUATION"].update(status="PASS", coverage="COMPLETE", artifacts=[H],
            checked_at="2026-09-30T04:00:00Z", checker_sha256=H)
        with self.assertRaises(common.ValidationError):
            trust.Entry.parse(fields)
        fields = entry().to_dict()
        fields["facets"]["STATIC"].update(checked_at="2026-10-01T04:00:00Z", expires_at="2026-09-30T04:00:00Z")
        with self.assertRaises(common.ValidationError):
            trust.Entry.parse(fields)

    def test_negative_evidence_and_delisted_edges_fail_closed(self):
        fields = entry().to_dict()
        fields["facets"]["STATIC"]["status"] = "BLOCKED"
        with self.assertRaises(common.ValidationError):
            trust.Entry.parse(fields)
        fields["state"] = "BLOCKED"
        blocked = trust.Entry.parse(fields)
        with self.assertRaises(common.ValidationError):
            trust.transition(blocked, "REVIEW", NOW)
        e = trust.transition(entry(), "DELISTED", NOW)
        with self.assertRaises(common.ValidationError):
            trust.transition(e, "REVIEW", NOW)

    def test_source_identity_unknown_fields_and_bool_install_refused(self):
        for update in ({"id": "f" * 64}, {"installable": 0}, {"attestation": "VERIFIED"},
                       {"schema_version": "future"}, {"unknown": "field"}):
            fields = entry().to_dict()
            fields.update(update)
            with self.subTest(update=update), self.assertRaises(common.ValidationError):
                trust.Entry.parse(fields)


class DiagnosticAdapterTests(unittest.TestCase):
    def test_benign_report_is_unsigned_candidate_with_partial_observation(self):
        result = ingest()
        self.assertEqual(result.status, "CANDIDATE")
        e = result.entries[0]
        static = dict(e.facets)[trust.Facet.STATIC]
        self.assertEqual((static.status, static.coverage), ("UNOBSERVED", "PARTIAL"))
        self.assertIsNone(static.checker_sha256)  # producer implementation is not attested
        self.assertEqual(e.source.source_skill_tree_sha256, "c" * 64)
        self.assertEqual(e.diagnostic.auditor_tree_sha256, "e" * 64)
        self.assertEqual(e.diagnostic.snapshot_sha256, "d" * 64)
        for facet, evidence in e.facets:
            if facet != trust.Facet.STATIC:
                self.assertEqual(evidence.status, "UNOBSERVED")
        self.assertFalse(result.to_dict()["installable"])

    def test_raw_hash_and_entry_receipt_tamper_refused(self):
        raw = seal(diagnostic())
        with self.assertRaises(common.ValidationError):
            trust.ingest_diagnostic(raw, (locked_source(),), H, "0" * 64)
        doc = common.strict_json(raw)
        doc["entries"][0]["description"] = "Tampered"
        raw = json.dumps(doc).encode()
        with self.assertRaises(common.ValidationError):
            trust.ingest_diagnostic(raw, (locked_source(),), H, hashlib.sha256(raw).hexdigest())

    def test_lock_source_commit_path_and_remote_identity_refused(self):
        for key, value in (("repository", "https://evil.example/example/science"), ("commit", "2" * 40),
                           ("path", "skills/other"), ("path_prefix", "../escape")):
            doc = diagnostic()
            doc["entries"][0]["source"][key] = value
            with self.subTest(key=key), self.assertRaises(common.ValidationError):
                ingest(doc)
        source = locked_source()
        source.acquisition_status = "BLOCKED"
        with self.assertRaises(common.ValidationError):
            ingest(sources=(source,))

    def test_partial_and_empty_reports_are_blocked_without_dropped_results(self):
        doc = diagnostic()
        doc.update(status="BLOCKED", completion="PARTIAL", input_errors=[{"input": "input-2", "reason": "Synthetic unavailable input"}])
        doc["inputs"].append({"input": "input-2", "status": "BLOCKED"})
        result = ingest(doc)
        self.assertEqual((result.status, len(result.entries), result.entries[0].state), ("BLOCKED", 1, trust.State.BLOCKED))
        doc["entries"] = []
        self.assertEqual(ingest(doc).status, "BLOCKED")

    def test_unsupported_yaml_coverage_and_unbound_source_are_blocked(self):
        for change in ("unsupported", "coverage", "binding", "portability", "source_problem", "catalog_blocked"):
            doc = diagnostic()
            source = locked_source()
            row = doc["entries"][0]
            if change == "unsupported":
                row["spec"].update(status="UNSUPPORTED", unsupported=["nested-yaml-mapping"])
                row["status"] = doc["status"] = "REVIEW"
            elif change == "coverage":
                row["security"].update(status="INCOMPLETE", coverage_errors=[{"file": "x.bin", "reason": "binary-nul-content"}])
                row["status"] = doc["status"] = "BLOCKED"
            elif change == "binding":
                row["source"]["binding"] = "NOT_ESTABLISHED"
            elif change == "portability":
                source.portability_status = "REVIEW_CASE_COLLISIONS"
            elif change == "source_problem":
                row["source_problems"] = ["caller-snapshot-hash-mismatch"]
                row["status"] = doc["status"] = "BLOCKED"
            else:
                doc["status"] = "BLOCKED"
            with self.subTest(change=change):
                self.assertEqual(ingest(doc, (source,)).status, "BLOCKED")

    def test_critical_high_and_spec_errors_never_pass(self):
        for severity in ("critical", "high", "spec"):
            doc = diagnostic()
            row = doc["entries"][0]
            if severity == "spec":
                row["spec"].update(status="FAIL", problems=["name-mismatch"])
                row["status"] = doc["status"] = "FAIL"
            else:
                row["security"]["findings"] = [{"rule": "synthetic-boundary", "severity": severity, "file": "SKILL.md", "line": 1}]
                row["security"]["counts"][severity] = 1
                row["status"] = doc["status"] = "BLOCKED" if severity == "critical" else "REVIEW"
            with self.subTest(severity=severity):
                self.assertEqual(ingest(doc).status, "BLOCKED")

    def test_missing_ambiguous_snapshot_or_count_mismatch_never_candidate(self):
        for change in ("missing", "ambiguous", "count", "skills_bool"):
            doc = diagnostic()
            if change == "missing":
                doc["inputs"] = []
                self.assertEqual(ingest(doc).status, "BLOCKED")
            elif change == "ambiguous":
                duplicate = copy.deepcopy(doc["inputs"][0])
                duplicate["input"] = "input-2"
                doc["inputs"].append(duplicate)
                with self.assertRaises(common.ValidationError):
                    ingest(doc)
            elif change == "count":
                doc["inputs"][0]["skills"] = 2
                self.assertEqual(ingest(doc).status, "BLOCKED")
            else:
                doc["inputs"][0]["skills"] = True
                with self.assertRaises(common.ValidationError):
                    ingest(doc)

    def test_claimed_execution_lift_or_positive_trust_refused(self):
        for location, field, value in (("catalog", "trust", "VERIFIED"), ("catalog", "installable", True),
                                      ("row", "installable", True), ("row", "evaluation", {"status": "MEASURED", "lift": 0.5}),
                                      ("row", "tests", {"status": "PASS"}), ("row", "status", "PASS")):
            doc = diagnostic()
            (doc if location == "catalog" else doc["entries"][0])[field] = value
            with self.subTest(field=field), self.assertRaises(common.ValidationError):
                ingest(doc)

    def test_duplicate_unknown_contract_counts_and_receipt_refused(self):
        for change in ("duplicate", "version", "checker", "counts", "receipt", "incomplete_claim"):
            doc = diagnostic()
            if change == "duplicate":
                doc["entries"].append(copy.deepcopy(doc["entries"][0]))
                doc["inputs"][0]["skills"] = 2
            elif change == "version":
                doc["schema_version"] = "unknown"
            elif change == "checker":
                doc["entries"][0]["checker"]["version"] = "future"
            elif change == "counts":
                doc["entries"][0]["security"]["counts"]["high"] = 1
            elif change == "receipt":
                # seal restores receipt; mutate contract instead.
                raw = seal(doc)
                parsed = json.loads(raw)
                parsed["entries"][0]["receipt_contract"] = "unrecognized"
                raw = json.dumps(parsed).encode()
                with self.assertRaises(common.ValidationError):
                    trust.ingest_diagnostic(raw, (locked_source(),), H, hashlib.sha256(raw).hexdigest())
                continue
            else:
                doc["completion"] = "PARTIAL"
            with self.subTest(change=change), self.assertRaises(common.ValidationError):
                ingest(doc)

    def test_adapter_has_no_network_or_process_calls(self):
        with patch("socket.socket", side_effect=AssertionError("network forbidden")), patch("subprocess.Popen", side_effect=AssertionError("execution forbidden")):
            self.assertEqual(ingest().status, "CANDIDATE")


    def test_actual_optional_errors_exclusions_and_zero_counter_contract(self):
        doc = diagnostic()
        self.assertEqual(ingest(doc).status, "CANDIDATE")
        doc["inputs"][0]["coverage"]["excluded_paths"] = [".git"]
        self.assertEqual(ingest(doc).status, "CANDIDATE")
        doc.update(status="BLOCKED", completion="PARTIAL", input_errors=[{"reason": "no-inputs-supplied"}], inputs=[], entries=[])
        self.assertEqual(ingest(doc).status, "BLOCKED")

    def test_repository_root_skill_has_explicit_empty_path(self):
        doc = diagnostic()
        row = doc["entries"][0]
        row["source"]["path"] = ""
        row["id"] = hashlib.sha256((row["source"]["repository"] + "\0" + COMMIT + "\0").encode()).hexdigest()
        source = locked_source()
        source.skill_paths = ("SKILL.md",)
        result = ingest(doc, (source,))
        self.assertEqual(result.entries[0].source.path, "")

    def test_incomplete_security_profile_parse_and_scope_claims_block(self):
        for change in ("security", "parse", "profile", "scope"):
            doc = diagnostic()
            row = doc["entries"][0]
            if change == "security":
                row["security"]["status"] = "INCOMPLETE"
                self.assertEqual(ingest(doc).status, "BLOCKED")
            elif change == "parse":
                row["dependencies"]["parse_errors"] = [{"file": "x.py", "reason": "SyntaxError"}]
                self.assertEqual(ingest(doc).status, "BLOCKED")
            else:
                if change == "profile":
                    row["spec"]["profile"] = "unknown"
                else:
                    doc["inputs"][0]["coverage"]["scope"] = "selected markdown only"
                with self.assertRaises(common.ValidationError):
                    ingest(doc)


    def test_archived_lineage_and_restricted_selection_stay_blocked(self):
        for status in ("ARCHIVED_LINEAGE_METADATA_ONLY", "BLOCKED_CUSTOM_LICENSE", "BLOCKED_SCOPE_PENDING"):
            source = locked_source()
            source.selection_status = status
            with self.subTest(status=status):
                self.assertEqual(ingest(sources=(source,)).status, "BLOCKED")

    def test_reuse_block_is_preserved_as_rights_gate(self):
        source = locked_source()
        source.license_reuse_disposition = "BLOCKED_CUSTOM_PROPRIETARY_LICENSE; HUMAN_DISPOSITION_REQUIRED"
        e = ingest(sources=(source,)).entries[0]
        self.assertEqual(dict(e.human_gates)["RIGHTS"].status, "BLOCKED")
        self.assertEqual(e.state, trust.State.CANDIDATE)  # census candidate, no reuse authorization
        self.assertFalse(e.to_dict()["installable"])


class CliSchemaTests(unittest.TestCase):
    def test_cli_ingestion_binds_raw_artifacts_with_typed_lock_projection(self):
        from test_source_lock import fixture
        lock = fixture()
        report = diagnostic()
        template = report["entries"][0]
        report["entries"] = []
        for path in ("skills/first", "skills/second"):
            row = copy.deepcopy(template)
            row["source"].update(repository="https://github.com/Example/Synthetic", path=path)
            row["id"] = hashlib.sha256((row["source"]["repository"] + chr(0) + COMMIT + chr(0) + path).encode()).hexdigest()
            report["entries"].append(row)
        report["inputs"][0]["skills"] = 2
        report["inputs"][0]["coverage"]["entries"] = 2
        lock_bytes, report_bytes = json.dumps(lock).encode(), seal(report)
        with tempfile.TemporaryDirectory() as tmp:
            lock_path, report_path = pathlib.Path(tmp) / "lock.json", pathlib.Path(tmp) / "report.json"
            lock_path.write_bytes(lock_bytes)
            report_path.write_bytes(report_bytes)
            args = ["ingest", "--lock", str(lock_path), "--lock-sha256", hashlib.sha256(lock_bytes).hexdigest(),
                    "--report", str(report_path), "--report-sha256", hashlib.sha256(report_bytes).hexdigest()]
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = trust.main(args)
            result = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "CANDIDATE")
            self.assertEqual(len(result["entries"]), 2)
            self.assertFalse(result["installable"])
            self.assertTrue(all(row["facets"]["STATIC"]["status"] == "UNOBSERVED" for row in result["entries"]))
            args[args.index("--lock-sha256") + 1] = "0" * 64
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = trust.main(args)
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(output.getvalue())["status"], "BLOCKED")

    def test_cli_missing_file_is_structured_blocked_without_traceback(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = trust.main(["validate-entry", "synthetic-missing-file.json"])
        self.assertEqual(code, 2)
        result = json.loads(output.getvalue())
        self.assertEqual(result["status"], "BLOCKED")
        self.assertNotIn("Traceback", output.getvalue())

    def test_schema_has_all_facets_and_denies_listing_and_eval_pass(self):
        schema = json.loads((pathlib.Path(__file__).resolve().parents[1] / "schema/skills-entry.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(set(schema["properties"]["facets"]["required"]), {f.value for f in trust.Facet})
        self.assertNotIn("LISTED", schema["properties"]["state"]["enum"])
        self.assertFalse(schema["properties"]["installable"]["const"])


if __name__ == "__main__":
    unittest.main()
