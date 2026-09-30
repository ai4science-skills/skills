"""Synthetic, inert fixtures for bounded five-source comparisons."""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import subprocess
import sys
import tarfile
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import static_compare as compare
from static_io import AuditBoundaryError


SKILL = b"---\nname: example\ndescription: Synthetic inert fixture.\n---\nRead the fixture.\n"
MIT = b"MIT License\nPermission is hereby granted, free of charge, to any person obtaining a copy\n"


def tar_bytes(snapshot=None, *, members=None):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.PAX_FORMAT) as archive:
        root = tarfile.TarInfo("repository/")
        root.type = tarfile.DIRTYPE
        archive.addfile(root)
        if snapshot is not None:
            for name, data in snapshot.items():
                member = tarfile.TarInfo("repository/" + name)
                member.size, member.mode = len(data), 0o644
                archive.addfile(member, io.BytesIO(data))
        for member, data in members or []:
            archive.addfile(member, io.BytesIO(data) if data is not None else None)
    return gzip.compress(output.getvalue(), mtime=0)


def assertion(snapshot, raw, repo="ai4science-skills/skills", modes=None):
    modes = modes or {name: "100644" for name in snapshot}
    skills = sorted((name for name in snapshot if name.split("/")[-1] == "SKILL.md"), key=lambda name: name.encode())
    roots = [name.rsplit("/", 1)[0] if "/" in name else "." for name in skills]
    scoped = [name for name in snapshot if any(root == "." or name.startswith(root + "/") for root in roots)]
    tree = compare.git_tree_sha1(snapshot, modes)
    return {"repository": repo, "commit": compare.SOURCE_PINS[repo], "archive_sha256": hashlib.sha256(raw).hexdigest(), "archive_bytes": len(raw), "regular_file_count": len(snapshot), "regular_bytes": sum(map(len, snapshot.values())), "skill_md_count": len(skills), "skill_md_paths": skills, "repository_tree_sha256": hashlib.sha256(compare.manifest_bytes(snapshot, modes)).hexdigest(), "skill_tree_sha256": hashlib.sha256(compare.manifest_bytes(snapshot, modes, scoped)).hexdigest(), "git_tree_sha1": tree, "expected_git_tree_sha1": tree}


class CompareTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.snapshot = {"skills/example/SKILL.md": SKILL, "LICENSE": MIT, "skills/example/references/readme.md": b"Inert reference.\n"}
        self.raw = tar_bytes(self.snapshot)
        self.archive = self.root / "archive.tar.gz"
        self.archive.write_bytes(self.raw)
        self.source = assertion(self.snapshot, self.raw)

    def tearDown(self):
        self.temporary.cleanup()

    def error(self, reason, call):
        with self.assertRaises(AuditBoundaryError) as caught:
            call()
        self.assertEqual(caught.exception.reason, reason)

    def lock(self, *, sources=None):
        sources = sources or [assertion(self.snapshot, self.raw, repo) for repo in compare.SOURCE_PINS]
        lock = {"schema_version": "ai4s.sources-lock/v5-phaseA-proposal", "baseline_commit": compare.BASELINE, "sources": sources, "human_approvals": {"license_scope": "NOT_GRANTED", "biosafety": "NOT_GRANTED"}}
        path = self.root / "sources.lock.json"
        raw = json.dumps(lock).encode()
        path.write_bytes(raw)
        return path, hashlib.sha256(raw).hexdigest(), lock

    def test_archive_verifies_bytes_manifests_census_and_git_tree(self):
        manifest = self.root / "manifest.jsonl"
        manifest.write_bytes(compare.manifest_bytes(self.snapshot, {name: "100644" for name in self.snapshot}))
        snapshot, receipt = compare.load_archive(self.archive, self.source, manifest_path=manifest)
        self.assertEqual(snapshot, self.snapshot)
        self.assertTrue(receipt["complete"])
        self.assertTrue(receipt["retained_manifest_verified"])
        self.assertEqual(receipt["git_tree_sha1"], self.source["git_tree_sha1"])
        self.assertEqual(receipt["configured_limits"]["max_archive_bytes"], 256 * 1024 * 1024)
        self.assertIn("no extraction", receipt["inspection"])

    def test_caps_cannot_be_loosened_past_phase_a_bounds(self):
        caps = {"max_archive_bytes": 256 * 1024 * 1024, "max_file_bytes": 32 * 1024 * 1024, "max_total_bytes": 512 * 1024 * 1024, "max_stream_bytes": 544 * 1024 * 1024, "max_metadata_bytes": 65_536}
        for field, limit in caps.items():
            with self.subTest(field=field), self.assertRaises(ValueError):
                replace(compare.DEFAULT_LIMITS, **{field: limit + 1})

    def test_archive_sha_verified_before_parser(self):
        self.archive.write_bytes(b"not a gzip stream")
        with patch.object(compare.tarfile, "open", side_effect=AssertionError("parser invoked")):
            self.error("archive-sha256-or-size-mismatch", lambda: compare.load_archive(self.archive, self.source))

    def test_file_and_total_bounds(self):
        self.error("archive-file-byte-limit", lambda: compare.load_archive(self.archive, self.source, limits=replace(compare.DEFAULT_LIMITS, max_file_bytes=10)))
        self.error("archive-total-byte-limit", lambda: compare.load_archive(self.archive, self.source, limits=replace(compare.DEFAULT_LIMITS, max_total_bytes=100)))

    def test_compressed_and_member_bounds(self):
        self.error("byte-limit", lambda: compare.load_archive(self.archive, self.source, limits=replace(compare.DEFAULT_LIMITS, max_archive_bytes=10)))
        self.error("archive-member-count-limit", lambda: compare.load_archive(self.archive, self.source, limits=replace(compare.DEFAULT_LIMITS, max_members=1)))

    def test_expanded_stream_bound(self):
        self.error("expanded-tar-stream-byte-limit", lambda: compare.load_archive(self.archive, self.source, limits=replace(compare.DEFAULT_LIMITS, max_stream_bytes=1024)))

    def test_links_devices_traversal_and_duplicates_rejected(self):
        cases = [
            ("repository/link", tarfile.SYMTYPE, "nonregular-archive-member"),
            ("repository/link", tarfile.LNKTYPE, "nonregular-archive-member"),
            ("repository/device", tarfile.CHRTYPE, "nonregular-archive-member"),
            ("repository/../outside", tarfile.REGTYPE, "unsafe-archive-path-or-depth"),
            ("repository/skills/example/SKILL.md", tarfile.REGTYPE, "duplicate-archive-member"),
            ("/repository/absolute", tarfile.REGTYPE, "unsafe-archive-path-or-depth"),
            ("repository/windows\\name", tarfile.REGTYPE, "unsafe-archive-path"),
        ]
        for name, kind, reason in cases:
            with self.subTest(name=name, kind=kind):
                member = tarfile.TarInfo(name)
                member.type, member.linkname = kind, "target"
                raw = tar_bytes(self.snapshot, members=[(member, b"" if kind == tarfile.REGTYPE else None)])
                self.archive.write_bytes(raw)
                source = assertion(self.snapshot, raw)
                self.error(reason, lambda: compare.load_archive(self.archive, source))

    def test_multiple_roots_case_collisions_and_file_directory_collisions(self):
        member = tarfile.TarInfo("other/file")
        raw = tar_bytes(self.snapshot, members=[(member, b"")])
        self.archive.write_bytes(raw)
        self.error("multiple-archive-roots", lambda: compare.load_archive(self.archive, assertion(self.snapshot, raw)))
        snapshot = {"same": b"a", "SAME": b"b"}
        raw = tar_bytes(snapshot)
        self.archive.write_bytes(raw)
        self.error("archive-case-collision", lambda: compare.load_archive(self.archive, assertion(snapshot, raw)))
        snapshot = {"path": b"a", "path/file": b"b"}
        raw = tar_bytes(snapshot)
        self.archive.write_bytes(raw)
        # Generate the invalid assertion without a tree builder to test the loader.
        source = dict(self.source, archive_sha256=hashlib.sha256(raw).hexdigest(), archive_bytes=len(raw))
        self.error("archive-file-directory-collision", lambda: compare.load_archive(self.archive, source))

    def test_retained_manifest_is_exact_not_just_asserted(self):
        manifest = self.root / "manifest.jsonl"
        manifest.write_bytes(b"wrong\n")
        self.error("retained-repository-manifest-mismatch", lambda: compare.load_archive(self.archive, self.source, manifest_path=manifest))

    def test_census_manifest_git_and_mode_mismatch_never_pass(self):
        changes = {"skill_md_paths": [], "repository_tree_sha256": "0" * 64, "expected_git_tree_sha1": "0" * 40, "regular_file_count": 50}
        for field, value in changes.items():
            with self.subTest(field=field):
                source = dict(self.source, **{field: value})
                reason = "archive-expected-git-tree-mismatch" if field == "expected_git_tree_sha1" else "archive-lock-" + field + "-mismatch"
                self.error(reason, lambda: compare.load_archive(self.archive, source))
        member = tarfile.TarInfo("repository/run.sh")
        member.mode, member.size = 0o755, 1
        raw = tar_bytes({"SKILL.md": SKILL}, members=[(member, b"x")])
        snapshot = {"SKILL.md": SKILL, "run.sh": b"x"}
        self.archive.write_bytes(raw)
        modes = {"SKILL.md": "100644", "run.sh": "100755"}
        _, receipt = compare.load_archive(self.archive, assertion(snapshot, raw, modes=modes))
        self.assertEqual(receipt["regular_file_count"], 2)

    def test_truncated_and_hidden_trailing_archive_fail(self):
        for raw in (self.raw[:-4], gzip.compress(gzip.decompress(self.raw) + b"hidden code")):
            with self.subTest(length=len(raw)):
                self.archive.write_bytes(raw)
                source = assertion(self.snapshot, raw)
                with self.assertRaises(AuditBoundaryError):
                    compare.load_archive(self.archive, source)

    def test_oversized_pax_metadata_rejected(self):
        member = tarfile.TarInfo("repository/file")
        member.pax_headers = {"comment": "x" * 100_000}
        raw = tar_bytes(None, members=[(member, b"")])
        self.archive.write_bytes(raw)
        source = dict(self.source, archive_sha256=hashlib.sha256(raw).hexdigest(), archive_bytes=len(raw))
        self.error("tar-metadata-byte-limit", lambda: compare.load_archive(self.archive, source))

    def test_gnu_sparse_pax_versions_rejected_before_sparse_processing(self):
        variants = [
            {"GNU.sparse.map": "0,0"},
            {"GNU.sparse.size": "0", "GNU.sparse.numblocks": "0"},
            {"GNU.sparse.major": "1", "GNU.sparse.minor": "0"},
            {"GNU.sparse.custom": "unknown"},
        ]
        for headers in variants:
            with self.subTest(headers=headers):
                member = tarfile.TarInfo("repository/sparse")
                member.pax_headers = headers
                raw = tar_bytes(None, members=[(member, b"")])
                self.archive.write_bytes(raw)
                source = dict(self.source, archive_sha256=hashlib.sha256(raw).hexdigest(), archive_bytes=len(raw))
                self.error("sparse-archive-member", lambda: compare.load_archive(self.archive, source))

    def test_exact_lock_sha_baseline_five_pins_and_census(self):
        path, digest, lock = self.lock()
        actual, _ = compare.load_lock(path, digest)
        self.assertEqual(len(actual["sources"]), 5)
        self.error("lock-sha256-mismatch", lambda: compare.load_lock(path, "0" * 64))
        lock["sources"][0]["commit"] = "0" * 40
        raw = json.dumps(lock).encode()
        path.write_bytes(raw)
        self.error("source-pin-mismatch-or-duplicate", lambda: compare.load_lock(path, hashlib.sha256(raw).hexdigest()))
        path, _, lock = self.lock()
        lock["sources"].pop()
        raw = json.dumps(lock).encode()
        path.write_bytes(raw)
        self.error("five-sources-required", lambda: compare.load_lock(path, hashlib.sha256(raw).hexdigest()))

    def test_duplicate_json_keys_rejected(self):
        self.error("duplicate-json-key", lambda: compare._json(b'{"source":1,"source":2}', "fixture"))
        for payload in (b'{"extra":NaN}', b'{"extra":Infinity}', b'{"extra":-Infinity}', b'{"extra":1e9999}'):
            self.error("nonfinite-json-number", lambda: compare._json(payload, "fixture"))

    def test_isolated_direct_cli_imports_only_owned_tools(self):
        completed = subprocess.run([sys.executable, '-I', '-S', '-B', str(Path(compare.__file__).resolve()), '--help'],
            cwd=self.root, capture_output=True, text=True, timeout=10)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn('--tokenizer-artifacts', completed.stdout)

    def test_aggregation_keeps_five_distinct_source_tuples_and_null_tokens(self):
        path, digest, _ = self.lock()
        mapping = {repo: self.archive for repo in compare.SOURCE_PINS}
        result, code = compare.run(path, digest, mapping, self.root / "out")
        self.assertEqual(code, 0)
        self.assertEqual(result["counts"]["observed_entries"], 5)
        self.assertEqual(len({entry["id"] for entry in result["entries"]}), 5)
        self.assertEqual(result["counts"]["spec_statuses"], {"PASS": 5})
        self.assertFalse(result["installable"])
        self.assertEqual(result["trust"], "UNSIGNED_HONEST")
        self.assertTrue(all(value == "NOT_RUN" for value in result["later_phases"].values()))
        for source in result["source_receipts"]:
            receipt = json.loads((self.root / "out" / source["artifact"]).read_bytes())
            self.assertEqual(receipt["tokens"]["status"], "NOT_RUN")
            self.assertEqual(receipt["license"]["approval"], "NOT_GRANTED")
            self.assertEqual(receipt["safety"]["status"], "UNASSESSED")
            self.assertEqual(receipt["producer"]["ruleset_sha256"], hashlib.sha256(compare.canonical(receipt["producer"]["ruleset"])).hexdigest())
            self.assertLessEqual(receipt["started_at"], receipt["finished_at"])
            bound = receipt.pop("receipt_sha256")
            self.assertEqual(bound, hashlib.sha256(compare.canonical(receipt)).hexdigest())

    def test_missing_source_keeps_counts_null_and_catalog_partial(self):
        path, digest, _ = self.lock()
        result, code = compare.run(path, digest, {next(iter(compare.SOURCE_PINS)): self.archive}, self.root / "out")
        self.assertEqual(code, 2)
        self.assertEqual(result["completion"], "PARTIAL")
        self.assertEqual(len(result["input_errors"]), 4)
        for row in result["source_receipts"][1:]:
            receipt = json.loads((self.root / "out" / row["artifact"]).read_bytes())
            self.assertIsNone(receipt["static"]["counts"])
            self.assertEqual(receipt["static"]["status"], "NOT_RUN")

    def test_coverage_false_or_omitted_path_never_complete(self):
        path, digest, _ = self.lock()
        mapping = {repo: self.archive for repo in compare.SOURCE_PINS}
        original = compare.audit_snapshot
        for variant in ("false", "missing", "hash"):
            def scanner(*args, **kwargs):
                entry = original(*args, **kwargs)
                if variant == "false":
                    entry["coverage"]["complete"] = False
                elif variant == "missing":
                    entry["coverage"]["paths"].pop()
                else:
                    entry["coverage"]["paths"][0]["sha256"] = "0" * 64
                return entry
            with self.subTest(variant=variant), patch.object(compare, "audit_snapshot", side_effect=scanner):
                result, code = compare.run(path, digest, mapping, self.root / ("out-" + variant))
                self.assertEqual(code, 2)
                self.assertEqual(result["completion"], "PARTIAL")
                self.assertEqual(len(result["input_errors"]), 0)
                self.assertTrue(all(row["status"] == "INCOMPLETE" for row in result["source_receipts"]))

    def test_late_source_abort_resets_unemitted_facets(self):
        path, digest, _ = self.lock()
        mapping = {repo: self.archive for repo in compare.SOURCE_PINS}
        original = compare.audit_snapshot
        def scanner(*args, **kwargs):
            entry = original(*args, **kwargs)
            entry["source"]["path"] = "wrong/path"
            return entry
        with patch.object(compare, "audit_snapshot", side_effect=scanner):
            result, code = compare.run(path, digest, mapping, self.root / "out")
        self.assertEqual(code, 2)
        self.assertIsNone(result["counts"])
        self.assertEqual(len(result["input_errors"]), 5)
        for row in result["source_receipts"]:
            receipt = json.loads((self.root / "out" / row["artifact"]).read_bytes())
            self.assertTrue(receipt["acquisition"]["complete"])
            for facet in ("static", "license", "tokens"):
                self.assertEqual(receipt[facet]["status"], "NOT_RUN")
            self.assertIsNone(receipt["static"]["counts"])
            self.assertIsNone(receipt["tokens"]["counts"])

    def test_scanner_file_bound_produces_incomplete_receipt(self):
        snapshot = dict(self.snapshot, **{"skills/example/references/large.md": b"x" * 2_000_001})
        raw = tar_bytes(snapshot)
        self.archive.write_bytes(raw)
        path, digest, _ = self.lock(sources=[assertion(snapshot, raw, repo) for repo in compare.SOURCE_PINS])
        result, code = compare.run(path, digest, {repo: self.archive for repo in compare.SOURCE_PINS}, self.root / "out")
        self.assertEqual(code, 2)
        self.assertEqual(result["status"], "INCOMPLETE")
        self.assertEqual(result["counts"]["static_coverage_errors"], 5)
        self.assertTrue(all(row["status"] == "INCOMPLETE" for row in result["source_receipts"]))

    def test_candidate_program_never_imported(self):
        sentinel = self.root / "EXECUTED"
        program = ("from pathlib import Path\nPath(" + repr(str(sentinel)) + ").write_text('executed')\n").encode()
        snapshot = dict(self.snapshot, **{"skills/example/scripts/candidate.py": program})
        raw = tar_bytes(snapshot)
        self.archive.write_bytes(raw)
        path, digest, _ = self.lock(sources=[assertion(snapshot, raw, repo) for repo in compare.SOURCE_PINS])
        compare.run(path, digest, {repo: self.archive for repo in compare.SOURCE_PINS}, self.root / "out")
        self.assertFalse(sentinel.exists())

    def test_outputs_exclusive_and_input_overlap_rejected(self):
        path, digest, _ = self.lock()
        mapping = {repo: self.archive for repo in compare.SOURCE_PINS}
        manifests = self.root / "manifests"
        manifests.mkdir()
        self.error("output-input-overlap", lambda: compare.run(path, digest, mapping, manifests / "out", manifests_dir=manifests))
        output = self.root / "out"
        compare.run(path, digest, mapping, output)
        self.error("output-already-exists", lambda: compare.run(path, digest, mapping, output))


if __name__ == "__main__":
    unittest.main()
