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


ARCHIVE_URL = "https://codeload.github.com/example/science-index-fork/tar.gz/" + HEAD
COMPARE_ECHO = "https://api.github.com/repos/%s/compare/%s...%s" % (gate.REPOSITORY, BASE, HEAD)
COMPARE_REQUEST = COMPARE_ECHO + "?per_page=1"
BASE_COMMIT_URL = "https://api.github.com/repos/%s/commits/%s" % (gate.REPOSITORY, BASE)


def compare_record(**changes):
    """Synthetic subset of the GitHub compare response (shape observed on PR18)."""
    record = {"url": COMPARE_ECHO, "status": "ahead", "ahead_by": 1, "behind_by": 0,
              "total_commits": 1, "base_commit": {"sha": BASE},
              "merge_base_commit": {"sha": BASE}, "commits": [{"sha": HEAD}], "files": []}
    record.update(changes)
    return record


def as_bytes(record):
    return record if isinstance(record, bytes) else json.dumps(record).encode()


def evaluate(files=None, source=None, verify_base=None, verify_ref=None,
             compare=None, base_record=None, calls=None):
    source = source or source_archive()
    files = files or candidate_files(source)
    archive = tar_bytes(files)
    compare = compare_record() if compare is None else compare
    calls = [] if calls is None else calls

    def get(url, limit):
        calls.append(url)
        if url == COMPARE_REQUEST:
            if isinstance(compare, Exception):
                raise compare
            return as_bytes(compare)
        if url == BASE_COMMIT_URL and base_record is not None:
            return as_bytes(base_record)
        assert url == ARCHIVE_URL, url
        assert limit == sync.MAX_DOWNLOAD
        return archive

    if base_record is not None:
        verify_base = None
    elif verify_base is None:
        verify_base = lambda _: True
    return gate.evaluate(event(), BASE, ROOT, get=get,
                         verify_ref=verify_ref or (lambda _: None),
                         fetch=lambda repo, sha: source,
                         verify_base=verify_base)


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
            return {"url": publisher.API + "/statuses/" + HEAD, "id": 1,
                    "context": payload["context"], "state": payload["state"]}

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


class AncestryTests(unittest.TestCase):
    """The evaluated head must descend from the exact protected base."""

    def test_head_must_descend_from_exact_base(self):
        other = "c" * 40
        for name, record in (
            ("diverged", compare_record(status="diverged", ahead_by=1, behind_by=2,
                                        merge_base_commit={"sha": other})),
            ("behind", compare_record(status="behind", ahead_by=0, behind_by=1)),
            ("identical", compare_record(status="identical", ahead_by=0)),
            ("ahead_but_other_merge_base", compare_record(merge_base_commit={"sha": other})),
            ("ahead_but_behind_by", compare_record(behind_by=1)),
            ("status_diverged_merge_base_equal", compare_record(status="diverged")),
            ("ahead_status_zero_commits", compare_record(ahead_by=0)),
            ("ahead_status_negative_commits", compare_record(ahead_by=-1)),
        ):
            with self.subTest(case=name), self.assertRaisesRegex(gate.Hold, "BASE_NOT_ANCESTOR"):
                evaluate(compare=record)

    def test_ancestry_record_binds_exact_base_and_head_shas(self):
        for name, record in (
            ("moving_base_ref", compare_record(url="https://api.github.com/repos/%s/compare/main...%s"
                                               % (gate.REPOSITORY, HEAD))),
            ("other_head", compare_record(url="https://api.github.com/repos/%s/compare/%s...%s"
                                          % (gate.REPOSITORY, BASE, "d" * 40))),
            ("other_repo", compare_record(url=COMPARE_ECHO.replace(gate.REPOSITORY, "someone/else"))),
            ("base_commit_differs", compare_record(base_commit={"sha": "e" * 40})),
        ):
            with self.subTest(case=name), self.assertRaisesRegex(gate.Hold, "ANCESTRY_UNVERIFIED"):
                evaluate(compare=record)

    def test_ancestry_is_checked_before_candidate_archive_is_requested(self):
        calls = []
        with self.assertRaisesRegex(gate.Hold, "BASE_NOT_ANCESTOR"):
            evaluate(compare=compare_record(status="diverged", merge_base_commit={"sha": "c" * 40}),
                     calls=calls)
        self.assertEqual(calls, [COMPARE_REQUEST])
        calls = []
        evaluate(calls=calls)
        self.assertEqual(calls, [COMPARE_REQUEST, ARCHIVE_URL])

    def test_malformed_compare_record_holds(self):
        good = json.dumps(compare_record())
        for name, record in (
            ("top_level_list", [compare_record()]),
            ("missing_merge_base", {k: v for k, v in compare_record().items() if k != "merge_base_commit"}),
            ("missing_url", {k: v for k, v in compare_record().items() if k != "url"}),
            ("merge_base_string", compare_record(merge_base_commit=BASE)),
            ("merge_base_sha_int", compare_record(merge_base_commit={"sha": 7})),
            ("ahead_by_string", compare_record(ahead_by="1")),
            ("ahead_by_bool", compare_record(ahead_by=True)),
            ("behind_by_float", compare_record(behind_by=0.0)),
            ("status_list", compare_record(status=["ahead"])),
            ("nan_literal", good.replace('"behind_by": 0', '"behind_by": NaN').encode()),
            ("overflow_infinity", good.replace('"ahead_by": 1', '"ahead_by": 1e999').encode()),
            ("duplicate_key", good.replace('"status": "ahead"', '"status": "diverged", "status": "ahead"').encode()),
            ("invalid_utf8", b'{"url": "\xff"}'),
            ("not_json", b"<html>rate limited</html>"),
            ("transport_error", sync.SyncError("source response exceeds byte budget")),
        ):
            with self.subTest(case=name), self.assertRaisesRegex(gate.Hold, "ANCESTRY_UNVERIFIED"):
                evaluate(compare=record)

    def test_receipt_records_merge_base_and_keeps_holds(self):
        report = evaluate()
        self.assertEqual(report["merge_base_sha"], BASE)
        self.assertIs(report["installable"], False)
        self.assertEqual(report["provider_policy"], "UNVERIFIED")


class MalformedShapeTests(unittest.TestCase):
    """Wrong JSON shapes and types are refused with a named Hold, never a crash or a pass."""

    def test_default_base_verification_refuses_malformed_provider_record(self):
        good = {"sha": BASE, "commit": {"verification": {"verified": True}}}
        self.assertEqual(evaluate(base_record=good)["decision"], "STATIC_MATCH")
        raw = json.dumps(good)
        for name, record in (
            ("top_level_list", [good]),
            ("commit_list", {"sha": BASE, "commit": []}),
            ("verification_string", {"sha": BASE, "commit": {"verification": "verified"}}),
            ("verified_string", {"sha": BASE, "commit": {"verification": {"verified": "true"}}}),
            ("verified_int", {"sha": BASE, "commit": {"verification": {"verified": 1}}}),
            ("sha_missing", {"commit": {"verification": {"verified": True}}}),
            ("sha_other", dict(good, sha="c" * 40)),
            ("duplicate_sha", raw.replace('"sha": "%s"' % BASE, '"sha": "%s", "sha": "%s"' % ("c" * 40, BASE)).encode()),
            ("nan", raw.replace("true", "NaN").encode()),
        ):
            with self.subTest(case=name), self.assertRaisesRegex(gate.Hold, "BASE_SIGNATURE_UNVERIFIED"):
                evaluate(base_record=record)

    def test_base_verifier_must_return_exactly_true(self):
        for value in ("yes", 1, [True], object()):
            with self.subTest(value=repr(value)), self.assertRaisesRegex(gate.Hold, "BASE_SIGNATURE_UNVERIFIED"):
                evaluate(verify_base=lambda _, value=value: value)

    def test_policy_refuses_type_confused_values(self):
        raw = (ROOT / "policy/static-integrity.json").read_bytes()
        document = json.loads(raw)

        def check(data):
            # Rooted in the checkout: read_json_bytes refuses unreadable/link ancestors.
            with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
                target = pathlib.Path(temporary) / "policy" / "static-integrity.json"
                target.parent.mkdir()
                target.write_bytes(data)
                return gate.policy(pathlib.Path(temporary))

        self.assertEqual(check(raw)[1], gate.policy(ROOT)[1])
        text = raw.decode()
        for name, data in (
            ("max_members_float", json.dumps(dict(document, max_members=float(document["max_members"]))).encode()),
            ("max_download_float", json.dumps(dict(document, max_download_bytes=float(document["max_download_bytes"]))).encode()),
            ("extra_field", json.dumps(dict(document, installable=True)).encode()),
            ("missing_field", json.dumps({k: v for k, v in document.items() if k != "scope"}).encode()),
            ("duplicate_key", text.replace('"scope"', '"scope": "ANY", "scope"', 1).encode()),
            ("nan", text.replace(str(document["max_members"]), "NaN", 1).encode()),
        ):
            with self.subTest(case=name), self.assertRaisesRegex(gate.Hold, "POLICY_UNAVAILABLE"):
                check(data)

    def test_event_refuses_non_string_action_and_non_object_shapes(self):
        for name, change in (
            ("action_list", lambda p: p.__setitem__("action", ["synchronize"])),
            ("action_object", lambda p: p.__setitem__("action", {"synchronize": True})),
            ("action_null", lambda p: p.__setitem__("action", None)),
            ("pull_request_list", lambda p: p.__setitem__("pull_request", [])),
            ("head_string", lambda p: p["pull_request"].__setitem__("head", HEAD)),
            ("number_float", lambda p: p.__setitem__("number", 27.0)),
        ):
            payload = event()
            change(payload)
            with self.subTest(case=name), self.assertRaisesRegex(gate.Hold, "INVALID_EVENT"):
                gate.identity(payload, BASE)
        for payload in ([event()], "synchronize", None):
            with self.subTest(event=type(payload).__name__), self.assertRaisesRegex(gate.Hold, "INVALID_EVENT"):
                gate.identity(payload, BASE)

    def test_duplicate_key_and_nonfinite_event_emit_hold_receipt(self):
        good = json.dumps(event())
        for name, raw in (
            ("duplicate", good.replace('"number": 27', '"number": 27, "number": 28').encode()),
            ("nan", good.replace('"number": 27', '"number": NaN').encode()),
            ("overflow", good.replace('"number": 27', '"number": 1e999').encode()),
        ):
            with self.subTest(case=name), tempfile.TemporaryDirectory(dir=ROOT) as temporary:
                event_path = pathlib.Path(temporary) / "event.json"
                output_path = pathlib.Path(temporary) / "output.txt"
                event_path.write_bytes(raw)
                output_path.write_text("", encoding="utf-8")
                # Control: the file itself is readable, so the HOLD comes from its JSON content.
                self.assertEqual(gate.read_json_bytes(event_path, gate.MAX_EVENT_BYTES), raw)
                with self.assertRaises(ValueError):
                    gate.strict_json(raw)
                with mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(output_path)}):
                    self.assertEqual(gate.main(["--event", str(event_path), "--base-sha", BASE]), 2)
                encoded = output_path.read_text(encoding="ascii").removeprefix("report_b64=").strip()
                report = json.loads(base64.b64decode(encoded, validate=True))
                self.assertEqual((report["decision"], report["installable"]), ("HOLD", False))


def open_pr():
    return {"state": "open", "head": {"sha": HEAD, "repo": {"full_name": "example/science-index-fork"}},
            "base": {"sha": BASE, "ref": "main", "repo": {"full_name": gate.REPOSITORY}}}


class StatusBindingTests(unittest.TestCase):
    """A published status binds to the exact evaluated head SHA, never a moving ref."""

    def publish(self, report, status_response=None, pr=None):
        calls = []

        def request(url, token, payload=None):
            calls.append((url, payload))
            if payload is None:
                return open_pr() if pr is None else pr
            if status_response is not None:
                return status_response(payload)
            return {"url": publisher.API + "/statuses/" + HEAD, "context": payload["context"],
                    "state": payload["state"]}

        return publisher.publish(event(), BASE, report, "test-token", "success", request=request), calls

    def test_status_response_binds_exact_head_url(self):
        report = evaluate()
        matched, calls = self.publish(report)
        self.assertTrue(matched)
        self.assertEqual(calls[-1][0], publisher.API + "/statuses/" + HEAD)
        for name, response in (
            ("other_sha", lambda p: {"url": publisher.API + "/statuses/" + "c" * 40,
                                     "context": p["context"], "state": p["state"]}),
            ("moving_ref", lambda p: {"url": publisher.API + "/statuses/main",
                                      "context": p["context"], "state": p["state"]}),
            ("url_missing_sha_only", lambda p: {"sha": HEAD, "context": p["context"], "state": p["state"]}),
            ("sha_field_disagrees", lambda p: {"url": publisher.API + "/statuses/" + HEAD, "sha": "c" * 40,
                                               "context": p["context"], "state": p["state"]}),
            ("other_context", lambda p: {"url": publisher.API + "/statuses/" + HEAD,
                                         "context": "ci", "state": p["state"]}),
            ("not_object", lambda p: [p]),
        ):
            with self.subTest(case=name), self.assertRaisesRegex(gate.Hold, "PROVIDER_STATUS_UNAVAILABLE"):
                self.publish(report, status_response=response)

    def test_report_must_have_exact_fields_and_types(self):
        valid = evaluate()

        def changed(**edits):
            report = copy.deepcopy(valid)
            for key, value in edits.items():
                if value is KeyError:
                    report.pop(key, None)
                else:
                    report[key] = value
            return report

        upstream_extra = copy.deepcopy(valid["upstream"])
        upstream_extra[0]["installable"] = True
        for name, report in (
            ("extra_admission_field", changed(admission="GRANTED")),
            ("missing_upstream", changed(upstream=KeyError)),
            ("missing_merge_base", changed(merge_base_sha=KeyError)),
            ("other_merge_base", changed(merge_base_sha="c" * 40)),
            ("number_float", changed(number=27.0)),
            ("skill_count_string", changed(skill_count="1")),
            ("skill_count_bool", changed(skill_count=True)),
            ("plugin_count_mismatch", changed(plugin_count=2)),
            ("upstream_not_list", changed(upstream={"name": "toy-plugin"})),
            ("upstream_extra_field", changed(upstream=upstream_extra)),
            ("upstream_bad_commit", changed(upstream=[dict(valid["upstream"][0], commit="main")])),
        ):
            with self.subTest(case=name):
                matched, calls = self.publish(report)
                self.assertFalse(matched)
                self.assertEqual(calls[-1][1]["state"], "failure")

    def test_malformed_pr_record_holds_before_posting(self):
        for name, pr in (
            ("list", [open_pr()]),
            ("head_string", dict(open_pr(), head=HEAD)),
            ("head_repo_null", dict(open_pr(), head={"sha": HEAD, "repo": None})),
            ("base_list", dict(open_pr(), base=[BASE])),
            ("state_missing", {k: v for k, v in open_pr().items() if k != "state"}),
        ):
            with self.subTest(case=name):
                with self.assertRaisesRegex(gate.Hold, "STALE_OR_UNAVAILABLE_PR"):
                    self.publish(evaluate(), pr=pr)


if __name__ == "__main__":
    unittest.main()
