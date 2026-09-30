"""Real pinned tokenizer tests plus fail-closed artifact/coverage checks.

Run: python3 -I -S -B tools/test_token_count.py ARTIFACT_DIR RUNTIME_PARENT
No candidate repository code is imported or executed.
"""
import hashlib
import io
import json
from pathlib import Path
import platform
import shutil
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import token_count as tc

# Discovery imports must neither consume runner flags nor enable artifact tests.
# A trusted receipt runner can inject this tuple through runpy.init_globals.
_paths = globals().get("_PINNED_TOKENIZER_TEST_PATHS")
if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Explicit verified artifact and writable runtime directories required; NOT_RUN")
    _paths = (sys.argv[1], sys.argv[2])
    sys.argv[1:] = []
if _paths is not None and (not isinstance(_paths, tuple) or len(_paths) != 2 or not all(isinstance(path, (str, Path)) for path in _paths)):
    raise ValueError("invalid explicit tokenizer-test paths")
ARTIFACTS = Path(_paths[0]) if _paths is not None else None
RUNTIME = Path(_paths[1]) if _paths is not None else None
VERIFIED_TEST_ENVIRONMENT = bool(
    ARTIFACTS is not None and RUNTIME is not None
    and sys.flags.isolated and sys.flags.no_site
    and sys.version_info[:2] == (3, 12)
    and platform.system() == "Linux" and platform.machine() == "x86_64"
)
ARTIFACT_SKIP_REASON = "NOT_RUN: explicit verified artifacts/runtime and isolated -I -S Linux CPython 3.12 required"
SOURCE = {"repo": "https://github.com/example/source", "pin": "a" * 40}
SKILL = b"---\r\nname: alpha\r\ndescription: |\r\n  Exact text.\r\nlicense: MIT\r\n---\r\n\r\nBody <|endoftext|>\r\n"


class ContractTests(unittest.TestCase):
    def test_raw_partition_preserves_every_original_byte(self):
        fragments = tc.split_skill(SKILL)
        self.assertEqual(sum(len(raw) for _, raw in fragments), len(SKILL))
        parts = dict(fragments)
        self.assertEqual(parts["eager_name"], b"name: alpha\r\n")
        self.assertEqual(parts["eager_description"], b"description: |\r\n  Exact text.\r\n")
        self.assertEqual(parts["activation_body"], b"\r\nBody <|endoftext|>\r\n")
        self.assertEqual([raw for category, raw in fragments if category == "activation_frontmatter_other"], [b"---\r\n", b"license: MIT\r\n---\r\n"])

    def test_missing_or_duplicate_fields_and_delimiters_fail(self):
        for raw in (b"No frontmatter", b"---\nname: x\n", b"---\nname: x\n---\nBody", b"---\nname: x\nname: y\ndescription: d\n---\n", b"\xef\xbb\xbf---\nname: x\ndescription: d\n---\n"):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    tc.split_skill(raw)

    def test_unavailable_tokenizer_never_produces_zero_placeholder(self):
        result = tc.count_source({"skills/a/SKILL.md": SKILL}, SOURCE, None)
        self.assertEqual(result["status"], "NOT_RUN")
        self.assertNotIn("measured_file_totals", result)
        self.assertEqual(result["files"], [])
        self.assertEqual(result["input_sha256"], tc.tree_digest({"skills/a/SKILL.md": SKILL}))

    def test_full_source_pin_and_safe_repository_required(self):
        for pin in ("a314917", "A" * 40, "HEAD", "a" * 39):
            with self.assertRaises(ValueError):
                tc.count_source({}, {"repo": SOURCE["repo"], "pin": pin}, None)
        marker = "PRIVATE_TEST_MARKER"
        for repo in ("https://user:" + marker + "@github.com/owner/name", "https://github.com/owner/name?token=" + marker,
                     "https://github.com/owner/name#" + marker, "https://example.com/owner/name", "https://github.com:443/owner/name", "owner/.."):
            with self.subTest(repo=repo):
                with self.assertRaises(ValueError) as raised:
                    tc.count_source({}, {"repo": repo, "pin": SOURCE["pin"]}, None)
                self.assertNotIn(marker, str(raised.exception))
                output = io.StringIO()
                arguments = ["token_count.py", "unused", "--repo", repo, "--pin", SOURCE["pin"], "--artifacts", "unused", "--runtime-parent", "unused"]
                with patch.object(tc.sys, "argv", arguments), patch.object(tc.sys, "stdout", output), patch.object(tc, "load_tokenizer") as loaded:
                    self.assertEqual(tc.main(), 2)
                    loaded.assert_not_called()
                self.assertNotIn(marker, output.getvalue())
                self.assertNotIn("source", json.loads(output.getvalue()))
        self.assertEqual(tc.count_source({"SKILL.md": SKILL}, {"repo": "owner/name", "pin": SOURCE["pin"]}, None)["source"]["repo"], "owner/name")


@unittest.skipUnless(VERIFIED_TEST_ENVIRONMENT, ARTIFACT_SKIP_REASON)
class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="token-test-", dir=RUNTIME)
        self.folder = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_bad_wheel_rejected_before_any_import(self):
        filename = tc.PACKAGES["tiktoken"][1]
        (self.folder / filename).write_bytes(b"unverified executable wheel")
        with patch.object(tc.importlib, "import_module") as imported:
            with self.assertRaises(tc.TokenizerUnavailable):
                tc.load_tokenizer(self.folder, RUNTIME)
            imported.assert_not_called()

    def test_bad_asset_rejected_before_any_import(self):
        for _, filename, _ in tc.PACKAGES.values():
            shutil.copyfile(ARTIFACTS / filename, self.folder / filename)
        (self.folder / tc.ASSET_NAME).write_bytes(b"unverified ranks")
        with patch.object(tc.importlib, "import_module") as imported:
            with self.assertRaises(tc.TokenizerUnavailable):
                tc.load_tokenizer(self.folder, RUNTIME)
            imported.assert_not_called()

    def test_bad_lock_contract_rejected_before_import(self):
        lock = json.loads((TOOLS / "tokenizer.lock.json").read_text())
        lock["contract"]["decoder"] = "replacement decoding"
        path = self.folder / "bad.lock.json"
        path.write_text(json.dumps(lock))
        with patch.object(tc.importlib, "import_module") as imported:
            with self.assertRaises(tc.TokenizerUnavailable):
                tc.load_tokenizer(ARTIFACTS, RUNTIME, path)
            imported.assert_not_called()

    def test_bad_encoding_parameters_fail(self):
        lock = json.loads((TOOLS / "tokenizer.lock.json").read_text())
        lock["pattern"] = "."
        path = self.folder / "bad.lock.json"
        path.write_text(json.dumps(lock))
        with self.assertRaises(tc.TokenizerUnavailable):
            tc._verified_artifacts(ARTIFACTS, path)

    def test_symlink_artifact_is_rejected(self):
        filename = tc.PACKAGES["tiktoken"][1]
        (self.folder / filename).symlink_to(ARTIFACTS / filename)
        with self.assertRaises(tc.AuditBoundaryError):
            tc._verified_artifacts(self.folder, TOOLS / "tokenizer.lock.json")

    def test_nonisolated_interpreter_is_rejected(self):
        with patch.object(tc.sys, "flags") as flags:
            flags.isolated = False
            flags.no_site = False
            with self.assertRaisesRegex(tc.TokenizerUnavailable, "requires-python-I-S"):
                tc.load_tokenizer(ARTIFACTS, RUNTIME)


@unittest.skipUnless(VERIFIED_TEST_ENVIRONMENT, ARTIFACT_SKIP_REASON)
class PinnedTokenizerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Prove that verified direct construction needs no connection attempt.
        with patch.object(socket, "create_connection", side_effect=AssertionError("network forbidden")), patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")):
            cls.tokenizer = tc.load_tokenizer(ARTIFACTS, RUNTIME)

    @classmethod
    def tearDownClass(cls):
        cls.tokenizer.close()

    def test_real_known_count_and_special_spellings_are_ordinary(self):
        self.assertEqual(self.tokenizer.count(b"hello world"), 2)
        self.assertEqual(self.tokenizer.count(b"<|endoftext|>"), 7)
        self.assertEqual(self.tokenizer.receipt["encoding"]["sha256"], tc.ASSET_HASH)
        self.assertEqual(self.tokenizer.receipt["packages"][0]["sha256"], tc.PACKAGES["tiktoken"][2])
        self.assertNotIn("requests", sys.modules)
        self.assertNotIn("tiktoken_ext.openai_public", sys.modules)

    def test_unicode_and_newlines_are_not_rewritten(self):
        for text in ("é", "e\u0301", "A\r\nB\r\n", "A\nB\n", "\ufeffhello"):
            raw = text.encode("utf-8")
            self.assertEqual(self.tokenizer.count(raw), len(self.tokenizer.encoding.encode_ordinary(text)))
        self.assertNotEqual(hashlib.sha256("é".encode()).hexdigest(), hashlib.sha256("e\u0301".encode()).hexdigest())
        for raw in (b"\xff", b"\xed\xa0\x80", b"A\x00B"):
            with self.assertRaises(ValueError):
                self.tokenizer.count(raw)

    def test_duplicate_bytes_use_hash_while_source_tuples_stay_distinct(self):
        snapshot = {"skills/alpha/SKILL.md": SKILL, "skills/beta/SKILL.md": SKILL}
        first = tc.count_source(snapshot, SOURCE, self.tokenizer)
        second = tc.count_source(snapshot, {"repo": SOURCE["repo"], "pin": "b" * 40}, self.tokenizer)
        self.assertEqual(first["status"], "COUNTED")
        self.assertEqual(len(first["files"]), 2)
        self.assertEqual(len(first["unique_files"]), 1)
        self.assertEqual(first["measured_file_totals"]["occurrences"], 2 * first["measured_file_totals"]["unique_by_full_sha256"])
        self.assertNotEqual(first["source"], second["source"])
        self.assertEqual(first["files"][0]["tokenizer_receipt_sha256"], first["tokenizer_receipt_sha256"])

    def test_candidate_script_is_data_and_lazy_categories_are_explicit(self):
        snapshot = {"skills/a/SKILL.md": SKILL, "skills/a/scripts/never.py": b"raise RuntimeError('must never execute')\n", "skills/a/references/guide.md": b"Reference\n", "skills/a/assets/text.svg": b"<svg/>\n", "skills/a/NOTICE": b"Notice\n", "README.md": b"Repository text\n"}
        result = tc.count_source(snapshot, SOURCE, self.tokenizer)
        self.assertEqual(result["status"], "COUNTED")
        self.assertEqual({record["category"] for record in result["files"]}, {"skill_document", "lazy_scripts", "lazy_references", "lazy_assets", "lazy_other", "repo_other"})
        self.assertEqual(len(result["skills"][0]["lazy_files"]), 4)

    def test_invalid_bytes_make_complete_facet_not_run_without_fake_count(self):
        snapshot = {"skills/a/SKILL.md": SKILL, "skills/a/assets/binary.png": b"\xff\x00"}
        result = tc.count_source(snapshot, SOURCE, self.tokenizer)
        self.assertEqual(result["status"], "NOT_RUN")
        bad = next(record for record in result["files"] if record["path"].endswith(".png"))
        self.assertEqual(bad["status"], "NOT_RUN")
        self.assertNotIn("tokens", bad)
        self.assertEqual(result["skills"][0]["status"], "NOT_RUN")

    def test_bad_partition_retains_measured_whole_file_and_missing_split(self):
        result = tc.count_source({"skills/a/SKILL.md": b"name: not frontmatter\n"}, SOURCE, self.tokenizer)
        self.assertEqual(result["status"], "NOT_RUN")
        self.assertEqual(result["files"][0]["status"], "COUNTED")
        self.assertEqual(result["skills"][0]["status"], "NOT_RUN")
        self.assertNotIn("fragments", result["skills"][0])

    def test_missing_or_incomplete_input_never_complete(self):
        self.assertEqual(tc.count_source({}, SOURCE, self.tokenizer)["status"], "NOT_RUN")
        self.assertEqual(tc.count_source({"SKILL.md": SKILL}, SOURCE, self.tokenizer, {"complete": False})["status"], "NOT_RUN")

    def test_receipt_is_deterministic_without_timestamp_or_path_leak(self):
        first = tc.count_source({"SKILL.md": SKILL}, SOURCE, self.tokenizer)
        second = tc.count_source({"SKILL.md": SKILL}, SOURCE, self.tokenizer)
        self.assertEqual(tc.canonical(first), tc.canonical(second))
        self.assertNotIn(str(ARTIFACTS), json.dumps(first))


if __name__ == "__main__":
    if ARTIFACTS is None or RUNTIME is None:
        raise SystemExit("Explicit verified artifact and writable runtime directories required; NOT_RUN")
    unittest.main(verbosity=2)
