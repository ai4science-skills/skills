"""Adversarial importer tests. No remote code or network calls are executed."""
import copy
import io
import json
import pathlib
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import sync
import check


def entry():
    return {"name": "toy-plugin", "repo": "example/science", "ref": "v1.0.0",
            "sha": "1" * 40, "path": "skills", "skills": ["toy-skill"],
            "description": "Synthetic test fixture", "maintainer": "Test",
            "license": "MIT", "hosted_services": []}


def registry():
    return {"name": "toy-index", "owner": {"name": "Test"}, "description": "Fixture only",
            "version": "1.0.0", "plugins": [entry()]}


def archive(extra=None, omit_license=False):
    data = {"repo/skills/toy-skill/SKILL.md": b'---\nname: toy-skill\ndescription: Synthetic fixture\nlicense: MIT\n---\nDoes not certify science.\n'}
    if not omit_license:
        data["repo/LICENSE"] = b"MIT License\nSynthetic classification fixture: Permission is hereby granted, free of charge"
    data.update(extra or {})
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as handle:
        for name, content in data.items():
            member = tarfile.TarInfo(name)
            if content is None:
                member.type = tarfile.SYMTYPE
                member.linkname = "../../outside"
                handle.addfile(member)
            else:
                member.size = len(content)
                handle.addfile(member, io.BytesIO(content))
    return stream.getvalue()


def install_fixture(root):
    reg = registry()
    files = sync.prepare(entry(), archive())
    for relative, content in files.items():
        target = root / "plugins/toy-plugin" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    (root / "registry.json").write_text(json.dumps(reg), encoding="utf-8")
    (root / ".claude-plugin").mkdir()
    (root / ".claude-plugin/marketplace.json").write_text(json.dumps(sync.marketplace(reg)), encoding="utf-8")
    (root / "CATALOG.md").write_text("previous catalog", encoding="utf-8")


class ImporterTests(unittest.TestCase):
    def test_registry_rejects_url_path_name_and_nonimmutable_sha(self):
        for field, value in (("name", "../../escape"), ("repo", "evil.example/repo?q=x"),
                             ("repo", "owner/repo/extra"), ("path", "../skills"),
                             ("path", "C:/skills"), ("path", "skills\\escape"),
                             ("sha", "main"), ("skills", ["safe", "../escape"])):
            candidate = entry()
            candidate[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(sync.SyncError):
                sync.validate_entry(candidate)

    def test_duplicate_json_nonfinite_and_deep_json_fail_closed(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'[' * 2000 + b'0' + b']' * 2000):
            with self.assertRaises(ValueError):
                sync.read_json(raw)
        self.assertEqual(sync.read_json(json.dumps({"value": '[' * 2000 + '"escaped"' + ']' * 2000}).encode()),
                         {"value": '[' * 2000 + '"escaped"' + ']' * 2000})

    def test_archive_traversal_absolute_windows_reserved_and_links_rejected(self):
        for path in ("repo/skills/toy-skill/../../escape", "/repo/skills/toy-skill/file",
                     "repo/skills/toy-skill/C:escape", "repo/skills/toy-skill/back\\escape",
                     "repo/skills/toy-skill/CON.txt", "repo/skills/toy-skill/trailing."):
            with self.subTest(path=path), self.assertRaises(sync.SyncError):
                sync.prepare(entry(), archive({path: b"unsafe"}))
        with self.assertRaises(sync.SyncError):
            sync.prepare(entry(), archive({"repo/skills/toy-skill/link": None}))

    def test_download_member_expansion_and_selected_budgets(self):
        with patch.object(sync, "MAX_DOWNLOAD", 2), self.assertRaises(sync.SyncError):
            sync.prepare(entry(), archive())

    def test_case_collisions_and_inconsistent_archive_roots_rejected(self):
        for extra in ({"repo/skills/toy-skill/skill.md": b"collision"},
                      {"another/skills/toy-skill/file.py": b"mixed root"}):
            with self.assertRaises(sync.SyncError):
                sync.prepare(entry(), archive(extra))

    def test_bounded_read_and_origin_only_credentials(self):
        from unittest.mock import MagicMock
        response = MagicMock()
        response.status = 200
        response.geturl.return_value = "https://codeload.github.com/example/science/tar.gz/" + "1" * 40
        response.read.return_value = b"012345"
        response.__enter__.return_value = response
        opener = MagicMock()
        opener.open.return_value = response
        url = response.geturl.return_value
        with patch.object(sync.urllib.request, "build_opener", return_value=opener), patch.dict(sync.os.environ, {"GITHUB_TOKEN": "fixture-only"}), self.assertRaises(sync.SyncError):
            sync.bounded_get(url, 5)
        response.read.assert_called_once_with(6)
        request = opener.open.call_args.args[0]
        self.assertIsNone(request.get_header("Authorization"))
        with patch.object(sync, "MAX_MEMBERS", 1), self.assertRaises(sync.SyncError):
            sync.prepare(entry(), archive())
        with patch.object(sync, "MAX_EXPANDED", 128), self.assertRaises(sync.SyncError):
            sync.prepare(entry(), archive())
        with patch.object(sync, "MAX_PLUGIN", 32), self.assertRaises(sync.SyncError):
            sync.prepare(entry(), archive())

    def test_missing_license_and_skill_rejected(self):
        with self.assertRaises(sync.SyncError):
            sync.prepare(entry(), archive(omit_license=True))
        candidate = entry()
        candidate["skills"] = ["missing-skill"]
        with self.assertRaises(sync.SyncError):
            sync.prepare(candidate, archive())

    def test_ref_resolves_to_exact_commit(self):
        with patch.object(sync, "bounded_get", return_value=b"2" * 40), self.assertRaises(sync.SyncError):
            sync.verify_ref(entry())
        for value in (b"1" * 40, b"1" * 40 + b"\n"):
            with self.subTest(value=value), patch.object(sync, "bounded_get", return_value=value) as get:
                sync.verify_ref(entry())
                get.assert_called_once_with("https://api.github.com/repos/example/science/commits/v1.0.0",
                                            41, accept="application/vnd.github.sha")

    def test_ref_sha_media_type_refuses_json_and_malformed_responses(self):
        for value in (json.dumps({"sha": "1" * 40}).encode(), b"1" * 39, b"1" * 40 + b"x",
                      b"1" * 40 + b"\n\n", b"A" * 40, b"\xff" * 40):
            with self.subTest(value=value), patch.object(sync, "bounded_get", return_value=value), self.assertRaises(sync.SyncError):
                sync.verify_ref(entry())

    def test_sha_media_type_is_sent_without_unbounding_the_read(self):
        from unittest.mock import MagicMock
        url = "https://api.github.com/repos/example/science/commits/v1.0.0"
        response = MagicMock()
        response.status = 200
        response.geturl.return_value = url
        response.read.return_value = b"1" * 40
        response.__enter__.return_value = response
        opener = MagicMock()
        opener.open.return_value = response
        with patch.object(sync.urllib.request, "build_opener", return_value=opener):
            sync.verify_ref(entry())
        self.assertEqual(opener.open.call_args.args[0].get_header("Accept"), "application/vnd.github.sha")
        response.read.assert_called_once_with(42)

    def test_redirects_and_external_source_urls_refused(self):
        with self.assertRaises(sync.SyncError):
            sync.NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://evil.example")
        for url in ("https://api.github.com.evil.example/x", "http://api.github.com/x",
                    "https://user@api.github.com/x", "https://api.github.com:444/x"):
            with patch.object(sync.urllib.request, "build_opener") as opener, self.assertRaises(sync.SyncError):
                sync.bounded_get(url, 100)
            opener.assert_not_called()

    def test_valid_fixture_has_exact_market_and_source_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            install_fixture(root)
            self.assertEqual(check.audit(root)[0], [])
            path = root / "plugins/toy-plugin/skills/toy-skill/SKILL.md"
            path.write_bytes(path.read_bytes() + b"changed")
            self.assertTrue(any("hashes" in failure for failure in check.audit(root)[0]))

    def test_fixture_directory_reference_is_valid_but_file_named_directory_is_not(self):
        for reference, member, valid in (("assets/replay", "assets/replay/protocol.txt", True),
                                         ("assets/example.json", "assets/example.json/protocol.txt", False)):
            with self.subTest(reference=reference), tempfile.TemporaryDirectory() as temporary:
                root = pathlib.Path(temporary)
                install_fixture(root)
                md = (root / "plugins/toy-plugin/skills/toy-skill/SKILL.md").read_bytes()
                candidate = archive({"repo/skills/toy-skill/SKILL.md": md + ("See `" + reference + "`.\n").encode(),
                                     "repo/skills/toy-skill/" + member: b"Synthetic protocol\n"})
                with patch.object(sync, "ROOT", root), patch.object(sync, "verify_ref"), patch.object(sync, "fetch", return_value=candidate):
                    if valid:
                        sync.main()
                        self.assertEqual(check.audit(root)[0], [])
                    else:
                        with self.assertRaises(sync.SyncError):
                            sync.main()

    def test_stale_market_security_metadata_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            install_fixture(root)
            path = root / ".claude-plugin/marketplace.json"
            market = json.loads(path.read_text())
            market["plugins"][0]["source"] = "../../outside"
            path.write_text(json.dumps(market))
            self.assertTrue(any("metadata" in failure for failure in check.audit(root)[0]))

    def test_declared_host_requires_exact_match(self):
        candidate = entry()
        candidate["hosted_services"] = ["api.good.example - optional service"]
        self.assertNotIn("api.good.example.evil.example", sync.declared_hosts(candidate))
        self.assertEqual(check.named_hosts("https://API.GOOD.EXAMPLE.evil.example/send"), {"api.good.example.evil.example"})
        candidate["hosted_services"] = ["some-api.good.example - not the same host"]
        self.assertNotIn("api.good.example", sync.declared_hosts(candidate))

    def test_secret_scanner_withholds_values_and_detects_binary_assets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            install_fixture(root)
            secret = "hf" + "_" + "a" * 35
            asset = root / "plugins/toy-plugin/skills/toy-skill/asset.bin"
            asset.write_bytes(b"\xff" + secret.encode())
            failures = check.audit(root)[0]
            self.assertTrue(any("hf_token" in failure for failure in failures))
            self.assertFalse(any(secret in failure for failure in failures))

    def test_source_license_disagreement_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            install_fixture(root)
            path = root / "registry.json"
            reg = json.loads(path.read_text())
            reg["plugins"][0]["license"] = "Apache-2.0"
            path.write_text(json.dumps(reg))
            self.assertTrue(any("license differs" in failure for failure in check.audit(root)[0]))

    def test_network_failure_keeps_previous_generation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            install_fixture(root)
            before = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            with patch.object(sync, "ROOT", root), patch.object(sync, "verify_ref"), patch.object(sync, "fetch", side_effect=OSError("fixture failure")), self.assertRaises(OSError):
                sync.main()
            after = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            self.assertEqual(before, after)

    def test_staging_static_failure_keeps_previous_generation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            install_fixture(root)
            before = (root / "CATALOG.md").read_bytes()
            malicious = archive({"repo/skills/toy-skill/send.py": b"url='https://undeclared.example/send'"})
            with patch.object(sync, "ROOT", root), patch.object(sync, "verify_ref"), patch.object(sync, "fetch", return_value=malicious), self.assertRaises(sync.SyncError):
                sync.main()
            self.assertEqual(before, (root / "CATALOG.md").read_bytes())
            self.assertFalse((root / "plugins/toy-plugin/skills/toy-skill/send.py").exists())

    def test_partial_replace_exception_rolls_back_generation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            install_fixture(root)
            before = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            actual_replace = sync.os.replace
            def fail_once(source, destination):
                if pathlib.Path(source) == root / ".claude-plugin/marketplace.json":
                    raise OSError("fixture write failure")
                return actual_replace(source, destination)
            with patch.object(sync, "ROOT", root), patch.object(sync, "verify_ref"), patch.object(sync, "fetch", return_value=archive()), patch.object(sync.os, "replace", side_effect=fail_once), self.assertRaises(OSError):
                sync.main()
            after = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
