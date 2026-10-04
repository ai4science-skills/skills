"""Literal discovery fixtures; candidate source is never imported or executed."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import dependency_inventory as inventory


REGISTRY = {"plugins": [{"name": "sample-plugin", "repo": "Example/Source",
                         "sha": "1" * 40}]}


class Objects:
    def __init__(self):
        self.objects = {}

    def add(self, kind, raw):
        oid = inventory._oid(kind, raw)
        self.objects[kind, oid] = raw
        return oid

    def read(self, identifiers, kind):
        return {oid: self.objects[kind, oid] for oid in set(identifiers)}

    def snapshot(self, files, modes=None):
        modes = modes or {}
        hierarchy = {}
        for path, raw in files.items():
            parts = path.split("/")
            current = hierarchy
            for part in parts[:-1]:
                current = current.setdefault(part, {})
            current[parts[-1]] = (modes.get(path, "100644"), self.add("blob", raw))

        def encode_tree(current):
            raw = b""
            for name, item in sorted(current.items()):
                if isinstance(item, dict):
                    mode, oid = "40000", encode_tree(item)
                else:
                    mode, oid = item
                raw += mode.encode("ascii") + b" " + name.encode("ascii") + b"\0" + bytes.fromhex(oid)
            return self.add("tree", raw)

        tree = encode_tree(hierarchy)
        return self.add("commit", ("tree " + tree + "\nauthor Fixture <fixture@example.invalid> 0 +0000\n"
                                  "committer Fixture <fixture@example.invalid> 0 +0000\n\nfixture\n").encode("ascii"))


def fixture(extra=None, modes=None, registry=None):
    files = {"registry.json": json.dumps(REGISTRY if registry is None else registry).encode("utf-8"),
             "plugins/sample-plugin/skills/sample/SKILL.md": b"Fixture, not a scientific result.\n",
             "plugins/sample-plugin/skills/sample/kernel.py": b"import json\nfrom . import helper\n"}
    files.update(extra or {})
    objects = Objects()
    revision = objects.snapshot(files, modes)
    return objects, revision


class DiscoveryTests(unittest.TestCase):
    def test_complete_tree_and_exact_selected_bytes_without_execution_authority(self):
        objects, revision = fixture({"docs/ignored.py": b"import ignored\n"})
        report = inventory.discover(objects, revision)
        self.assertEqual(report["decision"], "BLOCKED")
        self.assertIs(report["installable"], False)
        self.assertEqual(report["source"]["repository_authority"], "CALLER_ASSERTED")
        self.assertEqual(report["source"]["upstream_parity"], "UNKNOWN")
        self.assertEqual(report["coverage"]["tracked_leaf_count"], 4)
        self.assertEqual(report["coverage"]["selected_file_count"], 2)
        python = next(item for item in report["files"] if item["path"].endswith(".py"))
        self.assertEqual(python["sha256"], hashlib.sha256(b"import json\nfrom . import helper\n").hexdigest())
        self.assertEqual(python["imports"], [{"kind": "import", "module": "json", "level": 0, "line": 1},
                                            {"kind": "from", "module": "", "level": 1, "line": 2}])
        self.assertIn("STDLIB_OR_THIRD_PARTY_CLASSIFICATION", report["unknown"])

    def test_canary_code_and_dynamic_literals_are_only_parsed(self):
        with tempfile.TemporaryDirectory() as root:
            canary = Path(root) / "never-executed"
            source = ("from pathlib import Path\nPath(" + repr(str(canary)) + ").write_text('executed')\n"
                      "import importlib as loader\nfrom importlib import import_module as load\n"
                      "loader.import_module('example.module')\nload('declared')\n"
                      "__import__(computed)\n").encode("utf-8")
            parsed = inventory.python_literals(source)
            self.assertFalse(canary.exists())
            self.assertEqual([item["module"] for item in parsed["imports"] if item["kind"] == "syntactic_dynamic_literal"],
                             ["example.module", "declared"])
            self.assertEqual(parsed["unknowns"], [{"reason": "DYNAMIC_IMPORT_UNRESOLVED", "line": 7}])

    def test_literal_url_credentials_are_not_emitted(self):
        parsed = inventory.python_literals(b"__import__('https://fixture-user:fixture-password@example.invalid/pkg')\n")
        emitted = inventory.encode(parsed)
        self.assertNotIn(b"fixture-password", emitted)
        self.assertNotIn(b"example.invalid", emitted)
        self.assertEqual(parsed["imports"], [])
        self.assertEqual(parsed["unknowns"][0]["reason"], "DYNAMIC_IMPORT_UNRESOLVED")

    def test_requirements_only_exact_plain_pins_have_declared_values(self):
        parsed = inventory.requirement_literals(b"# offline\nExample_Pkg==1.2.3\nother-pkg==2.0+cpu\n")
        self.assertEqual(parsed["analysis"], "DECLARED")
        self.assertEqual(parsed["pins"], [{"distribution": "example-pkg", "declared_version": "1.2.3", "line": 2},
                                         {"distribution": "other-pkg", "declared_version": "2.0+cpu", "line": 3}])

    def test_unsupported_requirement_directives_are_unknown_and_redacted(self):
        lines = [b"-e https://fixture-user:fixture-password@example.invalid/package", b"-r ../private.txt",
                 b"--index-url https://example.invalid", b"package>=1", b"package[extra]==1",
                 b"package==1; sys_platform=='win32'", b"package==1 \\", b"  --hash=sha256:abc",
                 b"package @ https://example.invalid/package", b"package==1 # inline comment"]
        for line in lines:
            with self.subTest(line_hash=hashlib.sha256(line).hexdigest()):
                parsed = inventory.requirement_literals(line + b"\n")
                self.assertEqual(parsed["analysis"], "UNKNOWN")
                self.assertEqual(parsed["pins"], [])
                encoded = inventory.encode(parsed)
                self.assertNotIn(b"fixture-password", encoded)
                self.assertNotIn(b"example.invalid", encoded)

    def test_python_parse_or_encoding_failures_stay_unknown(self):
        for raw in (b"import (", b"\xff", b"x = '\x00'"):
            with self.subTest(sha256=hashlib.sha256(raw).hexdigest()):
                self.assertEqual(inventory.python_literals(raw)["analysis"], "UNKNOWN")
        self.assertEqual(inventory.requirement_literals(b"\xff")["analysis"], "UNKNOWN")

    def test_non_ascii_module_name_is_unknown_without_echo(self):
        parsed = inventory.python_literals("import caf\u00e9\n".encode("utf-8"))
        self.assertEqual(parsed["imports"], [])
        self.assertEqual(parsed["unknowns"][0]["reason"], "MODULE_IDENTIFIER_UNSUPPORTED")

    def test_other_declaration_formats_are_not_misrepresented_as_scanned(self):
        extra = {"plugins/sample-plugin/pyproject.toml": b"[project]\ndependencies=['unresolved']\n",
                 "plugins/sample-plugin/setup.py": b"raise RuntimeError('must not run')\n",
                 "plugins/sample-plugin/package.json": b'{"dependencies":{"fixture":"*"}}'}
        objects, revision = fixture(extra)
        report = inventory.discover(objects, revision)
        unsupported = [item for item in report["files"] if item["kind"] == "UNSUPPORTED_DEPENDENCY_DECLARATION"]
        self.assertEqual(len(unsupported), 3)
        self.assertTrue(all(item["analysis"] == "UNKNOWN" for item in unsupported))

    def test_duplicate_registry_keys_and_invalid_identity_refuse(self):
        with self.assertRaisesRegex(inventory.DiscoveryError, "INVALID_REGISTRY"):
            inventory._plugins(b'{"plugins":[],"plugins":[]}')
        for value in ([], {"plugins": []}, {"plugins": [REGISTRY["plugins"][0]] * 2},
                      {"plugins": [dict(REGISTRY["plugins"][0], name="../escape")]},
                      {"plugins": [dict(REGISTRY["plugins"][0], repo="../escape")]}):
            with self.subTest(value=value), self.assertRaisesRegex(inventory.DiscoveryError, "INVALID_REGISTRY"):
                inventory._plugins(json.dumps(value).encode("utf-8"))

    def test_missing_registered_plugin_and_unregistered_plugin_refuse(self):
        objects, revision = fixture({"plugins/another-plugin/source.py": b"import x\n"})
        with self.assertRaisesRegex(inventory.DiscoveryError, "UNREGISTERED_PLUGIN_PATH"):
            inventory.discover(objects, revision)
        registry = copy.deepcopy(REGISTRY)
        registry["plugins"].append(dict(registry["plugins"][0], name="another-plugin"))
        objects, revision = fixture(registry=registry)
        with self.assertRaisesRegex(inventory.DiscoveryError, "PLUGIN_BYTES_MISSING"):
            inventory.discover(objects, revision)

    def test_links_submodules_and_registry_link_refuse(self):
        for path, mode, reason in (("registry.json", "120000", "REGISTRY_UNAVAILABLE"),
                                   ("plugins/sample-plugin/linked.py", "120000", "UNSAFE_SELECTED_MODE"),
                                   ("plugins/sample-plugin/submodule", "160000", "UNSAFE_SELECTED_MODE")):
            with self.subTest(mode=mode):
                objects, revision = fixture({path: b"../outside"}, {path: mode})
                with self.assertRaisesRegex(inventory.DiscoveryError, reason):
                    inventory.discover(objects, revision)

    def test_traversal_reserved_names_and_case_collisions_refuse(self):
        for path in ("../outside", "plugins/sample-plugin/CON", "plugins/sample-plugin/.git/source", "plugins/sample-plugin/evil."):
            objects, revision = fixture({path: b"untrusted"})
            with self.subTest(path=path), self.assertRaisesRegex(inventory.DiscoveryError, "UNSAFE_TREE_PATH"):
                inventory.discover(objects, revision)
        objects, revision = fixture({"plugins/sample-plugin/skills/sample/KERNEL.py": b"untrusted"})
        with self.assertRaisesRegex(inventory.DiscoveryError, "TREE_PATH_COLLISION"):
            inventory.discover(objects, revision)

    def test_object_tree_ast_finding_and_report_bounds(self):
        objects, revision = fixture()
        with patch.object(inventory, "MAX_ITEMS", 1), self.assertRaisesRegex(inventory.DiscoveryError, "TREE_BOUNDS"):
            inventory.discover(objects, revision)
        with patch.object(inventory, "MAX_DEPTH", 1), self.assertRaisesRegex(inventory.DiscoveryError, "TREE_DEPTH_BOUNDS"):
            inventory.discover(objects, revision)
        with patch.object(inventory, "MAX_BYTES", 1), self.assertRaisesRegex(inventory.DiscoveryError, "TREE_BOUNDS"):
            inventory.discover(objects, revision)
        with patch.object(inventory, "MAX_NODES", 1), self.assertRaisesRegex(inventory.DiscoveryError, "AST_BOUNDS"):
            inventory.python_literals(b"import json")
        with patch.object(inventory, "MAX_FINDINGS", 1), self.assertRaisesRegex(inventory.DiscoveryError, "FINDING_BOUNDS"):
            inventory.python_literals(b"import json, os")
        with patch.object(inventory, "MAX_FINDINGS", 1), self.assertRaisesRegex(inventory.DiscoveryError, "FINDING_BOUNDS"):
            inventory.requirement_literals(b"first==1\nsecond==2")
        with patch.object(inventory, "MAX_REPORT", 1), self.assertRaisesRegex(inventory.DiscoveryError, "REPORT_BOUNDS"):
            inventory.discover(objects, revision)
        with patch.object(inventory, "MAX_TOTAL_FINDINGS", 1), self.assertRaisesRegex(inventory.DiscoveryError, "TOTAL_FINDING_BOUNDS"):
            inventory.discover(objects, revision)

    def test_invalid_revision_and_malformed_tree_refuse(self):
        objects, revision = fixture()
        for invalid in ("main", "0" * 40, "../HEAD", "1" * 39, "1" * 40 + "\n"):
            with self.subTest(revision=invalid), self.assertRaisesRegex(inventory.DiscoveryError, "INVALID_REVISION"):
                inventory.discover(objects, invalid)
        malformed = objects.add("tree", b"100644 without-nul")
        commit = objects.add("commit", ("tree " + malformed + "\n").encode("ascii"))
        with self.assertRaisesRegex(inventory.DiscoveryError, "INVALID_TREE"):
            inventory.discover(objects, commit)

    def test_deterministic_source_report(self):
        objects, revision = fixture()
        self.assertEqual(inventory.encode(inventory.discover(objects, revision)),
                         inventory.encode(inventory.discover(objects, revision)))


@unittest.skipUnless(inventory.shutil.which("git"), "Git object reader unavailable")
class ActualGitTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.reader = inventory.GitObjects(self.root)
        self.git(["init", "-q"])
        objects, self.revision = fixture()
        for (kind, oid), raw in objects.objects.items():
            captured = self.git(["hash-object", "-w", "-t", kind, "--stdin"], raw).decode("ascii").strip()
            self.assertEqual(captured, oid)
        self.objects = objects

    def tearDown(self):
        self.temporary.cleanup()

    def git(self, args, data=b""):
        result = subprocess.run([self.reader.git, "-C", str(self.root), *args], input=data,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.reader.env,
                                check=True, timeout=20)
        return result.stdout

    def test_exact_objects_ignore_working_tree_filters_hooks_and_replacements(self):
        baseline = inventory.encode(inventory.discover(self.reader, self.revision))
        target = self.root / "plugins/sample-plugin/skills/sample/kernel.py"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"raise RuntimeError('dirty working file must not run')")
        self.git(["config", "filter.evil.process", "invalid-command-must-not-run"])
        self.git(["config", "core.hooksPath", str(self.root / "untrusted-hooks")])
        target.with_name(".gitattributes").write_text("*.py filter=evil\n", encoding="utf-8")
        original = next(oid for (kind, oid), raw in self.objects.objects.items() if kind == "blob" and raw.startswith(b"import json"))
        replacement = self.git(["hash-object", "-w", "--stdin"], b"import counterfeit\n").decode("ascii").strip()
        self.git(["replace", original, replacement])
        observed = inventory.encode(inventory.discover(self.reader, self.revision))
        self.assertEqual(observed, baseline)
        self.assertEqual(self.reader.env["GIT_NO_REPLACE_OBJECTS"], "1")
        self.assertEqual(self.reader.env["GIT_CONFIG_GLOBAL"], inventory.os.devnull)

    def test_byte_and_metadata_mismatch_refuse(self):
        oid = inventory._oid("blob", b"x")
        for metadata, captured, reason in (
                ((oid + " blob 1\n").encode("ascii"), (oid + " blob 1\ny\n").encode("ascii"), "OBJECT_HASH_MISMATCH"),
                ((oid + " tree 1\n").encode("ascii"), b"", "OBJECT_METADATA_MISMATCH"),
                ((oid + " blob 9999999\n").encode("ascii"), b"", "OBJECT_BYTE_BOUNDS")):
            with self.subTest(reason=reason), patch.object(self.reader, "command", side_effect=[metadata, captured]), self.assertRaisesRegex(inventory.DiscoveryError, reason):
                self.reader.read([oid], "blob")

    def test_missing_promisor_object_never_launches_transport_canary(self):
        canary, helper = self.root / "transport-executed", self.root / "local_transport.py"
        helper.write_text("from pathlib import Path\nPath(" + repr(str(canary)) + ").write_text('executed')\n",
                          encoding="utf-8")
        self.git(["config", "core.repositoryformatversion", "1"])
        self.git(["config", "extensions.partialClone", "untrusted"])
        self.git(["config", "remote.untrusted.promisor", "true"])
        self.git(["config", "remote.untrusted.url", "ext::" + Path(inventory.sys.executable).as_posix() + " " + helper.as_posix()])
        self.git(["config", "protocol.ext.allow", "always"])
        self.git(["config", "credential.helper", "untrusted-helper-must-not-run"])
        poisoned = {"GIT_NO_LAZY_FETCH": "0", "GIT_ALLOW_PROTOCOL": "ext", "GIT_CONFIG_COUNT": "1",
                    "GIT_CONFIG_KEY_0": "protocol.ext.allow", "GIT_CONFIG_VALUE_0": "always",
                    "GIT_CONFIG_PARAMETERS": "'protocol.ext.allow'='always'"}
        with patch.dict(inventory.os.environ, poisoned):
            protected = inventory.GitObjects(self.root)
            with self.assertRaisesRegex(inventory.DiscoveryError, "OBJECT_METADATA_MISMATCH"):
                protected.read(["9" * 40], "blob")
        self.assertFalse(canary.exists())
        self.assertEqual(protected.env["GIT_NO_LAZY_FETCH"], "1")
        self.assertEqual(protected.env["GIT_ALLOW_PROTOCOL"], "")
        self.assertEqual(protected.env["GIT_PROTOCOL_FROM_USER"], "0")
        self.assertNotIn("GIT_CONFIG_PARAMETERS", protected.env)
        self.assertNotIn("GIT_CONFIG_KEY_0", protected.env)

    def test_cli_typed_failure_does_not_echo_input(self):
        script = ("import sys; sys.path.insert(0, " + repr(str(Path(inventory.__file__).parent)) + "); "
                  "import dependency_inventory; sys.exit(dependency_inventory.main())")
        result = subprocess.run([inventory.sys.executable, "-I", "-S", "-B", "-c", script,
                                 "--git-dir", str(self.root), "--revision", "fixture-secret-url"],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["reason"], "INVALID_REVISION")
        self.assertNotIn(b"fixture-secret-url", result.stdout)


if __name__ == "__main__":
    unittest.main()
