"""Synthetic, offline trust-boundary tests for the base-owned static gate."""

import base64
import copy
import io
import json
import os
import pathlib
import tarfile
import tempfile
import unittest
from unittest import mock

import static_integrity as gate
import static_integrity_status as publisher
import sync

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASE = "b" * 40
HEAD = "a" * 40


def event():
    return {"action": "synchronize", "number": 27,
            "repository": {"full_name": gate.REPOSITORY},
            "pull_request": {
                "base": {"sha": BASE, "ref": "main", "repo": {"full_name": gate.REPOSITORY}},
                "head": {"sha": HEAD, "repo": {"full_name": "example/science-index-fork"}},
            }}


def entry():
    return {"name": "toy-plugin", "repo": "example/science", "ref": "v1.0.0",
            "sha": "1" * 40, "path": "skills", "skills": ["toy-skill"],
            "description": "Synthetic test fixture", "maintainer": "Test",
            "license": "MIT", "hosted_services": []}


def registry():
    return {"name": "toy-index", "owner": {"name": "Test"},
            "description": "Fixture only", "version": "1.0.0", "plugins": [entry()]}


def tar_bytes(files, root="archive"):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as archive:
        for path, data in files.items():
            member = tarfile.TarInfo(root + "/" + path)
            if data is None:
                member.type = tarfile.SYMTYPE
                member.linkname = "../../outside"
                archive.addfile(member)
            else:
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
    return stream.getvalue()


def source_archive():
    return tar_bytes({
        "LICENSE": b"MIT License\nPermission is hereby granted, free of charge",
        "skills/toy-skill/SKILL.md": b"---\nname: toy-skill\ndescription: Synthetic fixture\nlicense: MIT\n---\nDoes not certify science.\n",
        "skills/toy-skill/scripts/run.py": b'raise RuntimeError("would execute if imported")\n',
    }, root="source")


def candidate_files(source=None):
    source = source or source_archive()
    reg = registry()
    files = {"registry.json": (json.dumps(reg, indent=2) + "\n").encode(),
             ".claude-plugin/marketplace.json": (json.dumps(sync.marketplace(reg), indent=2) + "\n").encode(),
             "CATALOG.md": gate._catalog(reg)}
    for path, data in sync.prepare(entry(), source).items():
        files["plugins/toy-plugin/" + path] = data
    for path in gate.PROTECTED:
        files[path] = (ROOT / path).read_bytes()
    return files


def evaluate(files=None, source=None, verify_base=None, verify_ref=None):
    source = source or source_archive()
    files = files or candidate_files(source)
    archive = tar_bytes(files)

    def get(url, limit):
        assert url == "https://codeload.github.com/example/science-index-fork/tar.gz/" + HEAD
        assert limit == sync.MAX_DOWNLOAD
        return archive

    return gate.evaluate(event(), BASE, ROOT, get=get,
                         verify_ref=verify_ref or (lambda _: None),
                         fetch=lambda repo, sha: source,
                         verify_base=verify_base or (lambda _: True))


class StaticIntegrityTests(unittest.TestCase):
    def test_failed_scan_emits_bounded_hold_receipt_for_separate_publisher(self):
        with tempfile.TemporaryDirectory() as temporary:
            event_path = pathlib.Path(temporary) / "event.json"
            output_path = pathlib.Path(temporary) / "output.txt"
            event_path.write_text("{}", encoding="utf-8")
            output_path.write_text("", encoding="utf-8")
            with mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(output_path)}):
                self.assertEqual(gate.main(["--event", str(event_path), "--base-sha", BASE]), 2)
            encoded = output_path.read_text(encoding="ascii").removeprefix("report_b64=").strip()
            report = json.loads(base64.b64decode(encoded, validate=True))
            self.assertEqual(report["decision"], "HOLD")
            self.assertFalse(report["installable"])

    def test_valid_fixture_is_only_static_match_never_installable(self):
        report = evaluate()
        self.assertEqual(report["decision"], "STATIC_MATCH")
        self.assertFalse(report["installable"])
        self.assertEqual(report["provider_policy"], "UNVERIFIED")
        self.assertEqual(report["head_sha"], HEAD)
        self.assertEqual(report["trusted_base_sha"], BASE)
        self.assertEqual(report["skill_count"], 1)
        self.assertIn("VULNERABILITIES", report["unobserved"])

    def test_policy_is_exact_and_missing_policy_holds(self):
        _, digest = gate.policy(ROOT)
        self.assertEqual(len(digest), 64)
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(gate.Hold, "POLICY_UNAVAILABLE"):
                gate.policy(pathlib.Path(temporary))

    def test_event_binds_exact_repository_base_and_head(self):
        for change in ("base", "base_ref", "head", "repo", "number", "action"):
            with self.subTest(change=change):
                payload = event()
                if change == "base":
                    payload["pull_request"]["base"]["sha"] = "0" * 40
                elif change == "base_ref":
                    payload["pull_request"]["base"]["ref"] = "unprotected"
                elif change == "head":
                    payload["pull_request"]["head"]["sha"] = "main"
                elif change == "repo":
                    payload["repository"]["full_name"] = "someone/else"
                elif change == "number":
                    payload["number"] = True
                else:
                    payload["action"] = "closed"
                with self.assertRaisesRegex(gate.Hold, "INVALID_EVENT"):
                    gate.identity(payload, BASE)

    def test_archive_refuses_traversal_link_case_alias_and_limits(self):
        policy, _ = gate.policy(ROOT)
        for unsafe in (
            {"safe": b"ok", "../escape": b"bad"},
            {"safe": b"ok", "plugins/link": None},
            {"A": b"one", "a": b"two"},
            {"safe": b"ok", "plugins\\escape": b"bad"},
            {"safe": b"ok", "nested/.git/config": b"bad"},
        ):
            with self.subTest(paths=list(unsafe)), self.assertRaisesRegex(gate.Hold, "ARCHIVE_UNSAFE"):
                gate.snapshot(tar_bytes(unsafe), policy)
        valid = tar_bytes({"safe": b"ok"})
        tiny = dict(policy, max_download_bytes=len(valid) - 1)
        with self.assertRaisesRegex(gate.Hold, "ARCHIVE_UNSAFE"):
            gate.snapshot(valid, tiny)

    def test_protected_checker_and_policy_change_hold(self):
        files = candidate_files()
        files["tools/check.py"] += b"\n# changed by candidate\n"
        with self.assertRaisesRegex(gate.Hold, "PROTECTED_CHECKER_CHANGE"):
            evaluate(files)
        files = candidate_files()
        files["tools/trust_common.py"] += b"\n# changed by candidate\n"
        with self.assertRaisesRegex(gate.Hold, "PROTECTED_CHECKER_CHANGE"):
            evaluate(files)
        files = candidate_files()
        files[".github/workflows/extra.yml"] = b"name: unsafe\n"
        with self.assertRaisesRegex(gate.Hold, "PROTECTED_CHECKER_CHANGE"):
            evaluate(files)
        files = candidate_files()
        del files["policy/static-integrity.json"]
        with self.assertRaisesRegex(gate.Hold, "PROTECTED_CHECKER_CHANGE"):
            evaluate(files)

    def test_missing_or_changed_source_pin_holds(self):
        files = candidate_files()
        reg = registry()
        reg["plugins"][0]["sha"] = "main"
        files["registry.json"] = json.dumps(reg).encode()
        with self.assertRaisesRegex(gate.Hold, "SOURCE_PIN_UNVERIFIED"):
            evaluate(files)
        files = candidate_files()
        files["plugins/toy-plugin/skills/toy-skill/SKILL.md"] += b"changed"
        with self.assertRaisesRegex(gate.Hold, "SOURCE_BYTES_MISMATCH"):
            evaluate(files)
        def bad_ref(_):
            raise sync.SyncError("source tag moved")
        with self.assertRaisesRegex(gate.Hold, "SOURCE_PIN_UNVERIFIED"):
            evaluate(verify_ref=bad_ref)

    def test_provider_base_signature_unavailable_holds_before_archive(self):
        with self.assertRaisesRegex(gate.Hold, "BASE_SIGNATURE_UNVERIFIED"):
            evaluate(verify_base=lambda _: False)

    def test_catalog_and_static_metadata_fail_closed(self):
        files = candidate_files()
        files["CATALOG.md"] = b"not the generated catalog\n"
        with self.assertRaisesRegex(gate.Hold, "CATALOG_MISMATCH"):
            evaluate(files)
        files = candidate_files()
        files["plugins/toy-plugin/skills/toy-skill/SKILL.md"] += b"https://undeclared.example/send\n"
        source = source_archive()
        with self.assertRaisesRegex(gate.Hold, "SOURCE_BYTES_MISMATCH"):
            evaluate(files, source)

    def test_workflow_never_checks_out_or_executes_candidate(self):
        workflow = json.loads((ROOT / ".github/workflows/base-static-integrity.yml").read_text())
        self.assertEqual(set(workflow["on"]), {"pull_request_target"})
        self.assertEqual(workflow["permissions"], {})
        scanner = workflow["jobs"]["scan_inert_pr_bytes"]
        publisher = workflow["jobs"]["publish_exact_head_status"]
        self.assertEqual(scanner["permissions"], {"contents": "read"})
        self.assertEqual(publisher["permissions"],
                         {"contents": "read", "pull-requests": "read", "statuses": "write"})
        self.assertEqual(publisher["needs"], ["scan_inert_pr_bytes"])
        self.assertEqual(publisher["if"], "${{ always() }}")
        self.assertEqual(scanner["outputs"], {"report_b64": "${{ steps.scan.outputs.report_b64 }}"})
        self.assertEqual(scanner["steps"][2]["id"], "scan")
        self.assertEqual(scanner["steps"][2]["env"],
                         {"GITHUB_TOKEN": "${{ github.token }}", "GH_TOKEN": ""})
        for job in (scanner, publisher):
            self.assertEqual(job["steps"][0]["with"]["ref"], "${{ github.sha }}")
            self.assertFalse(job["steps"][0]["with"]["persist-credentials"])
            for step in job["steps"]:
                self.assertNotIn("github.event.pull_request.head", json.dumps(step))


class PublisherTests(unittest.TestCase):
    def test_exact_head_success_and_invalid_report_failure(self):
        calls = []

        def request(url, token, payload=None):
            self.assertEqual(token, "test-token")
            calls.append((url, payload))
            if payload is None:
                return {"state": "open", "head": {"sha": HEAD, "repo": {"full_name": "example/science-index-fork"}},
                        "base": {"sha": BASE, "ref": "main", "repo": {"full_name": gate.REPOSITORY}}}
            return {"context": payload["context"], "state": payload["state"], "sha": HEAD}

        self.assertTrue(publisher.publish(event(), BASE, evaluate(), "test-token", "success", request=request))
        self.assertEqual(calls[-1][1]["state"], "success")
        self.assertEqual(calls[-1][0], publisher.API + "/statuses/" + HEAD)
        self.assertFalse(publisher.publish(event(), BASE, None, "test-token", "success", request=request))
        self.assertEqual(calls[-1][1]["state"], "failure")
        self.assertFalse(publisher.publish(event(), BASE, evaluate(), "test-token", "failure", request=request))
        self.assertEqual(calls[-1][1]["state"], "failure")

    def test_stale_pr_cannot_publish_success(self):
        calls = []

        def request(url, token, payload=None):
            calls.append((url, payload))
            return {"state": "open", "head": {"sha": "c" * 40},
                    "base": {"repo": {"full_name": gate.REPOSITORY}}}

        with self.assertRaisesRegex(gate.Hold, "STALE_OR_UNAVAILABLE_PR"):
            publisher.publish(event(), BASE, evaluate(), "test-token", "success", request=request)
        self.assertEqual(len(calls), 1)

    def test_advanced_base_cannot_publish_old_scan_success(self):
        calls = []

        def request(url, token, payload=None):
            calls.append((url, payload))
            return {"state": "open", "head": {"sha": HEAD, "repo": {"full_name": "example/science-index-fork"}},
                    "base": {"sha": "c" * 40, "ref": "main", "repo": {"full_name": gate.REPOSITORY}}}

        with self.assertRaisesRegex(gate.Hold, "STALE_OR_UNAVAILABLE_PR"):
            publisher.publish(event(), BASE, evaluate(), "test-token", "success", request=request)
        self.assertEqual(len(calls), 1)

    def test_retargeted_base_cannot_publish_old_scan_success(self):
        calls = []

        def request(url, token, payload=None):
            calls.append((url, payload))
            return {"state": "open", "head": {"sha": HEAD, "repo": {"full_name": "example/science-index-fork"}},
                    "base": {"sha": BASE, "ref": "unprotected", "repo": {"full_name": gate.REPOSITORY}}}

        with self.assertRaisesRegex(gate.Hold, "STALE_OR_UNAVAILABLE_PR"):
            publisher.publish(event(), BASE, evaluate(), "test-token", "success", request=request)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
