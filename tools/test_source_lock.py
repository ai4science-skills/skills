"""Synthetic source census tests. No repositories, archives or skill code run."""
import contextlib
import copy
from dataclasses import FrozenInstanceError
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import source_lock
from trust_common import ValidationError, strict_json


def evidence(url, sha="a" * 64, size=10):
    return {"requested_url": url, "observed_at": "2026-09-30T04:00:00Z",
            "http_status": 200, "final_url": url, "bytes": size,
            "sha256": sha, "complete": True}


def fixture():
    """Hashes label synthetic records, not real upstream file measurements."""
    repo, commit, tree = "Example/Synthetic", "1" * 40, "2" * 40
    archive = "https://codeload.github.com/" + repo + "/tar.gz/" + commit
    source = {
        "repository": repo, "canonical_repository": "example/synthetic",
        "repository_url": "https://github.com/" + repo,
        "acquisition_status": "PINNED_HASHED", "installable": False,
        "pin": {"commit": commit, "git_tree_sha1": tree,
                "commit_url": "https://github.com/" + repo + "/commit/" + commit,
                "evidence": evidence("https://api.github.com/repos/" + repo + "/commits/main")},
        "archive": {"url": archive, "sha256": "a" * 64, "bytes": 10,
                    "evidence": evidence(archive)},
        "content": {"repository_tree_sha256": "b" * 64, "skill_tree_sha256": "c" * 64,
                    "regular_file_count": 3, "regular_file_bytes": 12, "skill_tree_files": 2,
                    "skill_md_count": 2, "skill_md_paths": ["skills/first/SKILL.md", "skills/second/SKILL.md"],
                    "skill_roots": ["skills/first", "skills/second"],
                    "archive_git_correspondence": {"status": "MATCH", "difference_paths": [],
                                                   "git_tree_items": 3, "archive_files": 3}},
        "bounded_acquisition": {"compressed_limit_bytes": 100, "expanded_limit_bytes": 1000,
                                "per_file_limit_bytes": 100, "entry_limit": 100,
                                "expanded_stream_bytes": 100, "extraction": "NONE; synthetic metadata"},
        "license": {"review_status": "NOT_REVIEWED", "observed_labels": ["Synthetic label"],
                    "files": [{"path": "LICENSE", "type": "file", "mode": "100644", "size": 0,
                               "sha256": "d" * 64, "git_blob_sha1": "3" * 40,
                               "url": "https://github.com/" + repo + "/blob/" + commit + "/LICENSE"}]},
        "validation": {"static": "NOT_RUN", "behavior": "NOT_RUN", "science": "NOT_RUN",
                       "evaluation": "NOT_RUN", "license_approval": "NOT_GRANTED", "biosafety_approval": "NOT_GRANTED"},
        "registry_disposition": "UNASSESSED_NOT_LISTED",
        "source_tree_evidence": evidence("https://api.github.com/repos/" + repo + "/git/trees/" + tree + "?recursive=1"),
        "metadata": {"unobserved_private_settings": {"status": "UNOBSERVED", "data": None}},
    }
    return {"schema_version": source_lock.ACCEPTED_SCHEMA_VERSIONS[0],
            "hash_contract": {"id": source_lock.HASH_CONTRACT_ID, "digest": "SHA-256",
                              "keys": ["mode", "path", "sha256", "size", "type"]},
            "execution_performed": False, "publication_performed": False,
            "total_sources": 1, "total_skill_md_files": 2, "total_tracked_files": 3, "sources": [source]}


def assign(document, keys, value):
    target = document
    for key in keys[:-1]:
        target = target[key]
    target[keys[-1]] = value


class SourceLockTests(unittest.TestCase):
    def test_pinned_projection_is_frozen_and_preserves_raw_census(self):
        document = fixture()
        original = copy.deepcopy(document)
        locked, = source_lock.validate_lock(document)
        self.assertEqual(document, original)
        self.assertEqual(locked.repository, "Example/Synthetic")
        self.assertEqual(locked.commit, "1" * 40)
        self.assertEqual(locked.archive_sha256, "a" * 64)
        self.assertEqual(locked.skill_tree_sha256, "c" * 64)
        self.assertEqual(locked.hash_contract_id, source_lock.HASH_CONTRACT_ID)
        self.assertEqual(locked.skill_paths, ("skills/first/SKILL.md", "skills/second/SKILL.md"))
        self.assertEqual(locked.skills[0], source_lock.LockedSkill("skills/first/SKILL.md", "skills/first"))
        with self.assertRaises(FrozenInstanceError):
            locked.commit = "0" * 40
        with self.assertRaises(FrozenInstanceError):
            locked.skills[0].path = "other/SKILL.md"

    def test_only_explicit_version_and_hash_contract_are_accepted(self):
        for keys, value in (
                (["schema_version"], "ai4s.sources-lock/v4-unknown"),
                (["schema_version"], None),
                (["hash_contract", "id"], "auditor-tree/v1"),
                (["hash_contract", "digest"], "SHA-1"),
                (["hash_contract", "keys"], ["path", "sha256"]),
                (["hash_contract"], None)):
            document = fixture()
            assign(document, keys, value)
            with self.subTest(keys=keys, value=value), self.assertRaises(ValidationError):
                source_lock.validate_lock(document)

    def test_identity_pin_and_immutable_urls_fail_closed(self):
        for keys, value in (
                (["canonical_repository"], "other/repository"),
                (["repository"], "example/repo/extra"),
                (["repository"], "example/repo.git"),
                (["repository_url"], "https://github.com/another/repo"),
                (["pin", "commit"], "main"),
                (["pin", "commit"], "A" * 40),
                (["pin", "commit"], None),
                (["pin", "commit_url"], "https://github.com/Example/Synthetic/commit/main"),
                (["pin", "git_tree_sha1"], "bad"),
                (["pin", "evidence", "requested_url"], "https://api.github.com/repos/other/repo/commits/main"),
                (["archive", "url"], "https://codeload.github.com/Example/Synthetic/tar.gz/main"),
                (["archive", "evidence", "final_url"], "https://codeload.github.com/Example/Synthetic/tar.gz/" + "4" * 40),
                (["source_tree_evidence", "requested_url"], "https://api.github.com/repos/Example/Synthetic/git/trees/main?recursive=1")):
            document = fixture()
            assign(document["sources"][0], keys, value)
            with self.subTest(keys=keys, value=value), self.assertRaises(ValidationError):
                source_lock.validate_lock(document)

    def test_acquisition_evidence_and_hashes_must_agree(self):
        for keys, value in (
                (["archive", "sha256"], "x" * 64),
                (["archive", "bytes"], 11),
                (["archive", "bytes"], True),
                (["archive", "bytes"], 0),
                (["archive", "evidence", "sha256"], "e" * 64),
                (["archive", "evidence", "complete"], False),
                (["archive", "evidence", "complete"], 1),
                (["archive", "evidence", "http_status"], 401),
                (["pin", "evidence", "observed_at"], "2026-09-30"),
                (["pin", "evidence", "requested_url"], "https://api.github.com:bad/repos/x"),
                (["pin", "evidence", "requested_url"], "https://[bad/repos/x"),
                (["pin", "evidence", "requested_url"], "https://secret@api.github.com/repos/x"),
                (["source_tree_evidence", "complete"], False),
                (["content", "skill_tree_sha256"], None),
                (["content", "repository_tree_sha256"], "0" * 40)):
            document = fixture()
            assign(document["sources"][0], keys, value)
            with self.subTest(keys=keys, value=value), self.assertRaises(ValidationError):
                source_lock.validate_lock(document)
        for key in ("pin", "archive", "source_tree_evidence", "content", "license", "bounded_acquisition"):
            document = fixture()
            del document["sources"][0][key]
            with self.subTest(missing=key), self.assertRaises(ValidationError):
                source_lock.validate_lock(document)

    def test_match_counts_totals_and_budgets_are_consistent(self):
        mutations = (
            (["content", "regular_file_count"], 1),
            (["content", "regular_file_count"], None),
            (["content", "regular_file_bytes"], None),
            (["content", "skill_md_count"], 3),
            (["content", "skill_md_count"], None),
            (["content", "skill_tree_files"], 1),
            (["content", "archive_git_correspondence", "status"], "MISMATCH"),
            (["content", "archive_git_correspondence", "difference_paths"], ["other.txt"]),
            (["content", "archive_git_correspondence", "archive_files"], 4),
            (["bounded_acquisition", "compressed_limit_bytes"], 9),
            (["bounded_acquisition", "expanded_limit_bytes"], 99),
            (["bounded_acquisition", "entry_limit"], 2),
            (["bounded_acquisition", "expanded_stream_bytes"], 11),
            (["bounded_acquisition", "extraction"], "YES"),
        )
        for keys, value in mutations:
            document = fixture()
            assign(document["sources"][0], keys, value)
            with self.subTest(keys=keys, value=value), self.assertRaises(ValidationError):
                source_lock.validate_lock(document)
        for key, value in (("total_sources", 0), ("total_skill_md_files", 1),
                           ("total_tracked_files", 2), ("total_sources", True)):
            document = fixture()
            document[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValidationError):
                source_lock.validate_lock(document)

    def test_recorded_bounded_retry_preserves_failed_incomplete_evidence(self):
        document = fixture()
        source = document["sources"][0]
        failed = evidence(source["archive"]["url"])
        failed.pop("sha256")
        failed.pop("bytes")
        failed.update(complete=False, error="Synthetic acquisition exceeded its initial cap")
        source["bounded_acquisition"]["retry"] = {
            "initial_cap_bytes": 5, "revised_cap_bytes": 100,
            "reason": "Synthetic recorded bounded retry, never a request to acquire data",
            "initial_evidence": failed,
        }
        self.assertEqual(source_lock.validate_lock(document)[0].acquisition_status, "PINNED_HASHED")
        self.assertFalse(failed["complete"])
        for keys, value in ((["initial_cap_bytes"], 100), (["revised_cap_bytes"], 99),
                            (["initial_evidence", "complete"], True),
                            (["initial_evidence", "error"], ""),
                            (["initial_evidence", "final_url"], "https://codeload.github.com/Example/Synthetic/tar.gz/main")):
            changed = copy.deepcopy(document)
            assign(changed["sources"][0]["bounded_acquisition"]["retry"], keys, value)
            with self.subTest(keys=keys), self.assertRaises(ValidationError):
                source_lock.validate_lock(changed)


    def test_portable_case_sensitive_skill_paths_and_roots(self):
        for path in ("../SKILL.md", "/SKILL.md", "C:/SKILL.md", "skills/back\\SKILL.md",
                     "skills/CON/SKILL.md", "skills/trailing./SKILL.md", "skills/first/skill.md",
                     "skills/e\u0301/SKILL.md", "skills/\ud800/SKILL.md"):
            document = fixture()
            document["sources"][0]["content"]["skill_md_paths"][0] = path
            with self.subTest(path=repr(path)), self.assertRaises(ValidationError):
                source_lock.validate_lock(document)
        for paths, roots in (
                (["skills/first/SKILL.md", "skills/first/SKILL.md"], ["skills/first"]),
                (["skills/First/SKILL.md", "skills/first/nested/SKILL.md"], ["skills/First", "skills/first/nested"]),
                (["skills/first/SKILL.md", "skills/second/SKILL.md"], ["skills/wrong", "skills/second"])):
            document = fixture()
            document["sources"][0]["content"].update(skill_md_paths=paths, skill_roots=roots)
            with self.subTest(paths=paths), self.assertRaises(ValidationError):
                source_lock.validate_lock(document)
        document = fixture()
        document["sources"][0]["content"].update(skill_md_paths=["SKILL.md", "skills/nested/SKILL.md"],
                                                 skill_roots=[".", "skills/nested"])
        locked, = source_lock.validate_lock(document)
        self.assertEqual(locked.skills[0].root, ".")

    def test_license_inventory_is_hashed_but_cannot_approve(self):
        for keys, value in (
                (["review_status"], "APPROVED"),
                (["files", 0, "sha256"], None),
                (["files", 0, "git_blob_sha1"], "tag"),
                (["files", 0, "mode"], "120000"),
                (["files", 0, "type"], "symlink"),
                (["files", 0, "size"], -1),
                (["files", 0, "path"], "../LICENSE"),
                (["files", 0, "url"], "https://github.com/Example/Synthetic/blob/main/LICENSE")):
            document = fixture()
            assign(document["sources"][0]["license"], keys, value)
            with self.subTest(keys=keys, value=value), self.assertRaises(ValidationError):
                source_lock.validate_lock(document)
        document = fixture()
        document["sources"][0]["license"]["files"].append(copy.deepcopy(document["sources"][0]["license"]["files"][0]))
        with self.assertRaises(ValidationError):
            source_lock.validate_lock(document)
        for review in source_lock.UNAPPROVED_REVIEWS:
            document = fixture()
            document["sources"][0]["license"]["review_status"] = review
            self.assertEqual(source_lock.validate_lock(document)[0].license_review_status, review)

    def test_explicit_v3_custom_license_block_is_preserved_without_approval(self):
        document = fixture()
        source = document["sources"][0]
        source["registry_disposition"] = "BLOCKED_CUSTOM_LICENSE_SUBTREES"
        source["license"]["blocked_subtrees"] = ["skills/first"]
        source["license"]["review_status"] = "HUMAN_REVIEW_REQUIRED"
        locked, = source_lock.validate_lock(document)
        self.assertEqual(locked.acquisition_status, "PINNED_HASHED")
        self.assertEqual(locked.license_review_status, "HUMAN_REVIEW_REQUIRED")
        self.assertEqual(locked.license_reuse_disposition, "BLOCKED_CUSTOM_LICENSE_SUBTREES")
        for invalid in ("BLOCKED_CUSTOM_LICENSE_SUBTREES_APPROVED", "APPROVED", "LISTED", "UNASSESSED_NOT_LISTED"):
            source["registry_disposition"] = invalid
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                source_lock.validate_lock(document)


    def test_no_census_status_or_static_pass_grants_listing(self):
        for keys, value in ((["installable"], True), (["installable"], 0),
                            (["registry_disposition"], "LISTED"),
                            (["validation", "license_approval"], "GRANTED"),
                            (["validation", "biosafety_approval"], "GRANTED"),
                            (["acquisition_status"], "STATIC_PASS")):
            document = fixture()
            assign(document["sources"][0], keys, value)
            with self.subTest(keys=keys, value=value), self.assertRaises(ValidationError):
                source_lock.validate_lock(document)
        document = fixture()
        document["sources"][0]["validation"]["static"] = "PASS"
        locked, = source_lock.validate_lock(document)
        self.assertFalse(hasattr(locked, "installable"))
        for key in ("execution_performed", "publication_performed"):
            document = fixture()
            document[key] = True
            with self.assertRaises(ValidationError):
                source_lock.validate_lock(document)

    def test_degraded_sources_keep_unknowns_and_never_invent_pins(self):
        for status in ("BLOCKED", "MISSING", "UNOBSERVED"):
            document = fixture()
            source = document["sources"][0]
            for key in ("pin", "archive", "content", "license", "bounded_acquisition", "source_tree_evidence", "validation"):
                del source[key]
            source["acquisition_status"] = status
            source["acquisition_reason"] = "Synthetic acquisition gap"
            document.update(hash_contract=None, total_skill_md_files=None, total_tracked_files=None)
            locked, = source_lock.validate_lock(document)
            self.assertEqual(locked.acquisition_status, status)
            self.assertIsNone(locked.commit)
            self.assertIsNone(locked.archive_sha256)
            self.assertIsNone(locked.skill_tree_sha256)
            self.assertEqual(locked.skill_paths, ())
            for key in ("total_skill_md_files", "total_tracked_files"):
                changed = copy.deepcopy(document)
                changed[key] = 0
                with self.assertRaises(ValidationError):
                    source_lock.validate_lock(changed)
        document["sources"][0]["pin"] = {"commit": "1" * 40}
        self.assertEqual(source_lock.validate_lock(document)[0].commit, "1" * 40)
        document["sources"][0]["archive"] = {"evidence": {"complete": True}}
        with self.assertRaises(ValidationError):
            source_lock.validate_lock(document)

    def test_duplicate_canonical_sources_and_unknown_fields_are_rejected(self):
        document = fixture()
        document["sources"].append(copy.deepcopy(document["sources"][0]))
        document.update(total_sources=2, total_skill_md_files=4, total_tracked_files=6)
        with self.assertRaises(ValidationError):
            source_lock.validate_lock(document)
        for keys in ([], ["sources", 0], ["sources", 0, "pin"], ["sources", 0, "archive"],
                     ["sources", 0, "content"], ["sources", 0, "license"], ["hash_contract"]):
            document = fixture()
            target = document
            for key in keys:
                target = target[key]
            target["unrecognized_trust_field"] = True
            with self.subTest(keys=keys), self.assertRaises(ValidationError):
                source_lock.validate_lock(document)

    def test_malformed_input_shapes_raise_shared_validation_error(self):
        for value in (None, [], "text", 1, True):
            with self.subTest(root=value), self.assertRaises(ValidationError):
                source_lock.validate_lock(value)
        for keys in (["sources"], ["sources", 0], ["hash_contract"], ["sources", 0, "pin"],
                     ["sources", 0, "archive"], ["sources", 0, "content"], ["sources", 0, "license"],
                     ["sources", 0, "validation"], ["sources", 0, "bounded_acquisition"]):
            for value in ([], "text", 1, True):
                document = fixture()
                assign(document, keys, value)
                with self.subTest(keys=keys, value=value), self.assertRaises(ValidationError):
                    source_lock.validate_lock(document)

    def test_json_and_cli_are_bounded_read_only_and_honest(self):
        for data in (b'{"schema_version":1,"schema_version":2}', b'{"x":NaN}', b'\xff', b"[" * 100 + b"0" + b"]" * 100):
            with self.assertRaises(ValidationError):
                strict_json(data)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.json"
            original = json.dumps(fixture()).encode("utf-8")
            path.write_bytes(original)
            output, errors = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                self.assertEqual(source_lock.main([str(path)]), 0)
            summary = json.loads(output.getvalue())
            self.assertEqual(summary["result"], "RECORDED_CENSUS_CONSISTENT")
            self.assertFalse(summary["archive_or_tree_bytes_reverified"])
            self.assertFalse(summary["install_or_listing_authorized"])
            self.assertEqual(path.read_bytes(), original)
            path.write_bytes(b"{}")
            with contextlib.redirect_stderr(errors):
                self.assertEqual(source_lock.main([str(path)]), 1)
            self.assertIn("source lock invalid:", errors.getvalue())
            path.write_bytes(b"x" * (2097152 + 1))
            with contextlib.redirect_stderr(errors):
                self.assertEqual(source_lock.main([str(path)]), 1)

    def test_schema_declares_limited_contract_and_supported_version(self):
        schema = json.loads((Path(__file__).resolve().parent.parent / "schema/source-lock.schema.json").read_text(encoding="utf-8"))
        self.assertIn("limited", schema["description"].lower())
        self.assertEqual(schema["properties"]["schema_version"]["enum"], list(source_lock.ACCEPTED_SCHEMA_VERSIONS))
        self.assertEqual(schema["$defs"]["source"]["properties"]["acquisition_status"]["enum"], list(source_lock.ACQUISITION_STATUSES))
        self.assertEqual(schema["$defs"]["source"]["properties"]["registry_disposition"]["enum"], list(source_lock.V3_REGISTRY_DISPOSITIONS))
        self.assertEqual(schema["$defs"]["source_v4"]["properties"]["selection"]["properties"]["status"]["enum"], list(source_lock.V4_SELECTION_STATUSES))

def v4_fixture():
    document = fixture()
    old = document["sources"][0]
    content = old["content"]
    license_file = {key: value for key, value in old["license"]["files"][0].items() if key != "url"}
    license_file.update(label="SYNTHETIC_UNAPPROVED_TEXT", license_text_approval="NOT_GRANTED")
    source = {
        "repository": old["repository"], "repository_url": old["repository_url"],
        "commit": old["pin"]["commit"], "commit_url": old["pin"]["commit_url"],
        "archive_sha256": old["archive"]["sha256"], "skill_tree_sha256": content["skill_tree_sha256"],
        "repository_tree_sha256": content["repository_tree_sha256"], "license_hash": "d" * 64,
        "root_license_hashes": [{"path": "LICENSE", "sha256": "d" * 64}],
        "acquisition_status": "PINNED_HASHED", "blocked_reason": None,
        "archive": {"url": old["archive"]["url"], "sha256": "a" * 64, "bytes": 10,
                    "transport_status": "COMPLETE", "acquired_at": "2026-09-30T04:00:00Z",
                    "receipt": "synthetic-evidence/archive.receipt.json"},
        "pin_evidence": old["pin"], "expected_git_tree_sha1": "2" * 40,
        "recomputed_git_tree_sha1": "2" * 40, "git_correspondence": "MATCH",
        "regular_file_count": 3, "symlink_count": 0, "skill_md_count": 2,
        "skill_md_paths": content["skill_md_paths"], "binary_or_nonutf8_candidate_count": 0,
        "case_collision_groups": [], "portability_status": "NO_CASE_COLLISIONS_OBSERVED",
        "limits": {"compressed_bytes": 100, "expanded_stream_bytes": 1000,
                   "individual_file_bytes": 100, "members": 100, "seconds": 240},
        "license": {"filename_inventory_only": True, "root_license_paths": ["LICENSE"],
                    "license_files": [license_file], "license_set_sha256": "d" * 64,
                    "root_status": "ROOT_TEXT_OBSERVED_UNAPPROVED",
                    "custom_or_unknown_license_paths": [], "human_approval": "NOT_GRANTED"},
        "status_dimensions": {"static": "NOT_RUN", "prose": "NOT_RUN", "dependency": "NOT_RUN",
                              "vulnerability": "NOT_RUN", "behavioral": "NOT_RUN",
                              "scientific": "NOT_RUN", "evaluation": "NOT_RUN"},
        "human_approvals": {"biosafety": "NOT_GRANTED", "clinical": "NOT_GRANTED",
                            "custom_license": "NOT_GRANTED", "external_publication": "NOT_GRANTED"},
        "installable": False, "registry_disposition": "NOT_LISTED",
        "selection": {"status": "CANDIDATE_EVIDENCE_ONLY_NOT_IMPORTABLE", "approved_for_import": False,
                      "file_count": 2, "exact_paths": content["skill_md_paths"]},
        "license_reuse_disposition": "NOT_APPROVED_SCOPE_REVIEW_REQUIRED",
    }
    return {"schema_version": source_lock.V4_SCHEMA_VERSION,
            "hash_contract": {"id": source_lock.V4_HASH_CONTRACT_ID, "algorithm": "SHA-256",
                              "keys": ["mode", "path", "sha256", "size", "type"]},
            "summary": {"total_lock_entries": 1, "literal_skill_md_paths": 2,
                        "regular_file_records": 3, "archive_bytes_total": 10},
            "all_sources_acquisition_complete": True, "catalog_security_science_evaluation_complete": False,
            "execution_performed": False, "upstream_mutation_performed": False,
            "external_publication_performed": False, "third_party_skill_registry_copy_performed": False,
            "sources": [source]}


class V4SourceLockTests(unittest.TestCase):
    def test_flattened_v4_preserves_independent_transport_and_scope_statuses(self):
        document = v4_fixture()
        original = copy.deepcopy(document)
        locked, = source_lock.validate_lock(document)
        self.assertEqual(document, original)
        self.assertEqual(locked.hash_contract_id, source_lock.V4_HASH_CONTRACT_ID)
        self.assertEqual(locked.archive_transport_status, "COMPLETE")
        self.assertEqual(locked.acquisition_status, "PINNED_HASHED")
        self.assertEqual(locked.portability_status, "NO_CASE_COLLISIONS_OBSERVED")
        self.assertEqual(locked.license_review_status, "NOT_GRANTED")
        self.assertEqual(locked.license_reuse_disposition, "NOT_APPROVED_SCOPE_REVIEW_REQUIRED")
        self.assertEqual(locked.selection_status, "CANDIDATE_EVIDENCE_ONLY_NOT_IMPORTABLE")

    def test_flattened_identity_and_transport_cannot_contradict_nested_evidence(self):
        for keys, value in (
                (["commit"], "main"), (["archive_sha256"], "0" * 64),
                (["archive", "bytes"], 101), (["archive", "transport_status"], "UNOBSERVED"),
                (["archive", "url"], "https://codeload.github.com/Example/Synthetic/tar.gz/main"),
                (["git_correspondence"], "UNKNOWN_OR_MISMATCH"),
                (["recomputed_git_tree_sha1"], "4" * 40), (["pin_evidence", "commit"], "4" * 40),
                (["blocked_reason"], "Unresolved acquisition gap"),
                (["skill_md_count"], 3), (["limits", "members"], 2),
                (["license", "license_set_sha256"], "5" * 64),
                (["license", "root_license_paths"], []), (["regular_file_count"], 2),
                (["license", "license_set_sha256"], None),
                (["selection", "exact_paths"], ["other/SKILL.md", "skills/second/SKILL.md"])):
            document = v4_fixture()
            assign(document["sources"][0], keys, value)
            with self.subTest(keys=keys, value=value), self.assertRaises(ValidationError):
                source_lock.validate_lock(document)

    def test_complete_archive_with_identity_mismatch_stays_blocked(self):
        document = v4_fixture()
        source = document["sources"][0]
        source.update(acquisition_status="BLOCKED", git_correspondence="UNKNOWN_OR_MISMATCH",
                      recomputed_git_tree_sha1="4" * 40, blocked_reason="Synthetic raw-byte identity mismatch")
        document["all_sources_acquisition_complete"] = False
        locked, = source_lock.validate_lock(document)
        self.assertEqual(locked.acquisition_status, "BLOCKED")
        self.assertEqual(locked.archive_transport_status, "COMPLETE")
        self.assertIn("mismatch", locked.blocked_reason)
        document["all_sources_acquisition_complete"] = True
        with self.assertRaises(ValidationError):
            source_lock.validate_lock(document)
        source["git_correspondence"] = "MATCH"
        with self.assertRaises(ValidationError):
            source_lock.validate_lock(document)

    def test_scope_pending_does_not_invent_acquisition_or_census_zeroes(self):
        document = v4_fixture()
        previous = document["sources"][0]
        source = {key: previous[key] for key in ("repository", "repository_url", "commit", "installable", "registry_disposition")}
        source.update(archive_sha256=None, skill_tree_sha256=None, repository_tree_sha256=None,
                      acquisition_status="BLOCKED", blocked_reason="Synthetic scope pending",
                      selection={"status": "BLOCKED_SCOPE_PENDING", "approved_for_import": False,
                                 "candidate_paths": ["candidate/schema.json"]})
        document["sources"] = [source]
        document["all_sources_acquisition_complete"] = False
        document["summary"].update(literal_skill_md_paths=0, regular_file_records=0, archive_bytes_total=0)
        locked, = source_lock.validate_lock(document)
        self.assertEqual(locked.commit, "1" * 40)
        self.assertIsNone(locked.archive_sha256)
        self.assertIsNone(locked.archive_transport_status)
        self.assertIsNone(locked.license_review_status)
        self.assertEqual(locked.selection_status, "BLOCKED_SCOPE_PENDING")
        self.assertEqual(locked.skill_paths, ())
        source["acquisition_status"] = "PINNED_HASHED"
        with self.assertRaises(ValidationError):
            source_lock.validate_lock(document)

    def test_portability_and_root_license_blocks_do_not_become_acquisition_passes(self):
        document = v4_fixture()
        source = document["sources"][0]
        source["portability_status"] = "REVIEW_CASE_COLLISIONS"
        source["case_collision_groups"] = [["docs/README.md", "docs/readme.md"]]
        source["license"]["root_status"] = "BLOCKED_NO_ROOT_LICENSE_FOUND"
        source["license_hash"] = source["license"]["license_set_sha256"] = None
        source["license"]["license_files"] = []
        source["license"]["root_license_paths"] = []
        source["root_license_hashes"] = []
        source["license_reuse_disposition"] = "BLOCKED_ROOT_LICENSE"
        locked, = source_lock.validate_lock(document)
        self.assertEqual(locked.acquisition_status, "PINNED_HASHED")
        self.assertEqual(locked.portability_status, "REVIEW_CASE_COLLISIONS")
        self.assertEqual(locked.license_reuse_disposition, "BLOCKED_ROOT_LICENSE")
        source["portability_status"] = "NO_CASE_COLLISIONS_OBSERVED"
        with self.assertRaises(ValidationError):
            source_lock.validate_lock(document)

    def test_exact_v4_archived_and_blocked_selection_statuses_are_preserved(self):
        for status in ("ARCHIVED_LINEAGE_METADATA_ONLY", "BLOCKED_CUSTOM_LICENSE",
                       "BLOCKED_MISSING_GITLINK_VENDOR_PLATFORM", "BLOCKED_ARCHIVE_GIT_BYTE_MISMATCH"):
            document = v4_fixture()
            source = document["sources"][0]
            source["selection"]["status"] = status
            if status == "ARCHIVED_LINEAGE_METADATA_ONLY":
                source["archived"] = True
            elif status == "BLOCKED_CUSTOM_LICENSE":
                source["license_reuse_disposition"] = "BLOCKED_CUSTOM_PROPRIETARY_LICENSE; HUMAN_DISPOSITION_REQUIRED"
            else:
                source.update(acquisition_status="BLOCKED", git_correspondence="UNKNOWN_OR_MISMATCH",
                              recomputed_git_tree_sha1="4" * 40, blocked_reason="Synthetic identity block")
                document["all_sources_acquisition_complete"] = False
            locked, = source_lock.validate_lock(document)
            self.assertEqual(locked.selection_status, status)
            self.assertFalse(source["selection"]["approved_for_import"])
            source["selection"]["status"] = status + "_APPROVED"
            with self.subTest(status=status), self.assertRaises(ValidationError):
                source_lock.validate_lock(document)


    def test_v4_census_cannot_grant_any_approval(self):
        for keys, value in (
                (["installable"], True), (["registry_disposition"], "LISTED"),
                (["selection", "approved_for_import"], True),
                (["selection", "status"], "APPROVED"),
                (["human_approvals", "clinical"], "GRANTED"),
                (["license", "human_approval"], "GRANTED"),
                (["license", "license_files", 0, "license_text_approval"], "GRANTED"),
                (["license_reuse_disposition"], "APPROVED")):
            document = v4_fixture()
            assign(document["sources"][0], keys, value)
            with self.subTest(keys=keys, value=value), self.assertRaises(ValidationError):
                source_lock.validate_lock(document)
        for key in ("execution_performed", "external_publication_performed", "third_party_skill_registry_copy_performed",
                    "catalog_security_science_evaluation_complete", "upstream_mutation_performed"):
            document = v4_fixture()
            document[key] = True
            with self.subTest(key=key), self.assertRaises(ValidationError):
                source_lock.validate_lock(document)

    def test_v4_pin_receipt_shapes_remain_recorded_provenance(self):
        document = v4_fixture()
        source = document["sources"][0]
        source["pin_evidence"] = {"method": "Synthetic retained snapshot", "source_file": "synthetic/metadata.json",
                                  "source_sha256": "f" * 64, "original_observed_at": "2026-09-30T04:00:00Z",
                                  "commit": "1" * 40, "git_tree_sha1": "2" * 40}
        self.assertEqual(source_lock.validate_lock(document)[0].commit, "1" * 40)
        receipt = evidence("https://api.github.com/repos/Example/Synthetic/commits/" + "1" * 40)
        receipt["acquired_at"] = receipt.pop("observed_at")
        source["pin_evidence"] = receipt
        self.assertEqual(source_lock.validate_lock(document)[0].commit, "1" * 40)
        source["pin_evidence"]["requested_url"] = source["pin_evidence"]["final_url"] = "https://api.github.com/repos/Example/Synthetic/commits/main"
        self.assertEqual(source_lock.validate_lock(document)[0].commit, "1" * 40)
        source["pin_evidence"]["final_url"] = "https://api.github.com/repos/Example/Synthetic/commits/unreviewed-ref"
        with self.assertRaises(ValidationError):
            source_lock.validate_lock(document)
        source["pin_evidence"]["final_url"] = source["pin_evidence"]["requested_url"]
        source["pin_evidence"]["complete"] = False
        with self.assertRaises(ValidationError):
            source_lock.validate_lock(document)


    def test_explicit_empty_skill_scope_is_distinct_from_missing_acquisition(self):
        document = v4_fixture()
        source = document["sources"][0]
        source.update(skill_md_count=0, skill_md_paths=[], skill_tree_sha256=source_lock.EMPTY_TREE_SHA256)
        source["selection"].update(exact_paths=[], file_count=0)
        document["summary"]["literal_skill_md_paths"] = 0
        locked, = source_lock.validate_lock(document)
        self.assertEqual(locked.skill_paths, ())
        self.assertEqual(locked.skill_tree_sha256, source_lock.EMPTY_TREE_SHA256)
        self.assertEqual(locked.acquisition_status, "PINNED_HASHED")
        source["skill_tree_sha256"] = "0" * 64
        with self.assertRaises(ValidationError):
            source_lock.validate_lock(document)

    def test_v4_summary_counters_and_versions_fail_closed(self):
        for key in ("total_lock_entries", "literal_skill_md_paths", "regular_file_records", "archive_bytes_total"):
            document = v4_fixture()
            document["summary"][key] += 1
            with self.subTest(key=key), self.assertRaises(ValidationError):
                source_lock.validate_lock(document)
        for keys, value in ((["hash_contract", "id"], source_lock.HASH_CONTRACT_ID),
                            (["schema_version"], "ai4s.sources-lock/v4"), (["sources", 0, "portability_status"], None),
                            (["sources", 0, "root_license_hashes", 0, "sha256"], "0" * 64)):
            document = v4_fixture()
            assign(document, keys, value)
            with self.subTest(keys=keys, value=value), self.assertRaises(ValidationError):
                source_lock.validate_lock(document)
        document = v4_fixture()
        document["summary"]["byte_identity_correspondence_complete"] = 0
        with self.assertRaises(ValidationError):
            source_lock.validate_lock(document)



if __name__ == "__main__":
    unittest.main()
