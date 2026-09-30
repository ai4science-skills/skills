"""Synthetic and mocked tests; no Git or third-party skill execution."""

from __future__ import annotations

import csv
import hashlib
import io
import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from static_io import (
    AuditBoundaryError, Limits, csv_safe, fresh_output, inventory,
    markdown_safe, read_single, tree_digest, write_exclusive,
    _read_regular,
)


class SnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="ai4s-review-io-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "input"
        self.root.mkdir()

    def assert_reason(self, expected: str, operation) -> None:
        with self.assertRaises(AuditBoundaryError) as caught:
            operation()
        self.assertEqual(caught.exception.reason, expected)

    def test_captures_binary_and_previously_excluded_directories(self) -> None:
        for name in ("node_modules", "__pycache__"):
            directory = self.root / name
            directory.mkdir()
            (directory / "payload.dat").write_bytes(b"\x00\xff")
        snapshot, coverage = inventory(self.root)
        self.assertEqual(len(snapshot), 2)
        self.assertEqual(coverage["bytes"], 4)
        self.assertEqual(coverage["excluded_paths"], [])

    def test_root_name_does_not_hide_content(self) -> None:
        root = self.base / "node_modules"
        root.mkdir()
        (root / "SKILL.md").write_bytes(b"content")
        self.assertEqual(inventory(root)[0], {"SKILL.md": b"content"})

    def test_root_git_exclusion_is_explicit_and_nested_git_is_included(self) -> None:
        (self.root / ".git").mkdir()
        (self.root / ".git" / "config").write_bytes(b"administrative")
        (self.root / "nested").mkdir()
        (self.root / "nested" / ".git").write_bytes(b"content")
        snapshot, coverage = inventory(self.root)
        self.assertEqual(snapshot, {"nested/.git": b"content"})
        self.assertEqual(coverage["excluded_paths"], [".git"])

    def test_oversized_file_refused_before_open(self) -> None:
        (self.root / "large").write_bytes(b"12345")
        with patch("static_io.os.open") as opened:
            self.assert_reason("byte-limit", lambda: inventory(
                self.root, limits=Limits(max_file_bytes=4),
            ))
            opened.assert_not_called()

    def test_read_single_does_not_inventory_parent(self) -> None:
        file = self.root / "sources.json"
        file.write_bytes(b"[]")
        with patch("static_io.os.scandir", side_effect=AssertionError("no traversal")):
            self.assertEqual(read_single(file), b"[]")
        with patch("static_io.os.open") as opened:
            self.assert_reason("byte-limit", lambda: read_single(file, max_bytes=1))
            opened.assert_not_called()

    def test_streaming_read_requests_at_most_limit_plus_one(self) -> None:
        file = self.root / "file"
        file.write_bytes(b"")
        expected = file.lstat()
        handle = MagicMock()
        handle.read.return_value = b"12345"
        with patch("static_io.os.open", return_value=123), patch(
            "static_io.os.fstat", return_value=expected,
        ), patch("static_io.os.fdopen", return_value=handle), patch(
            "static_io.os.close",
        ):
            self.assert_reason("byte-limit", lambda: _read_regular(file, expected, 4))
        handle.read.assert_called_once_with(5)

    def test_descriptor_identity_change_prevents_read(self) -> None:
        file = self.root / "file"
        file.write_bytes(b"content")
        expected = file.lstat()
        changed = SimpleNamespace(
            st_dev=expected.st_dev, st_ino=expected.st_ino + 1,
            st_mode=expected.st_mode, st_size=expected.st_size,
            st_mtime=expected.st_mtime, st_ctime=expected.st_ctime,
            st_mtime_ns=expected.st_mtime_ns, st_ctime_ns=expected.st_ctime_ns,
        )
        with patch("static_io.os.open", return_value=123), patch(
            "static_io.os.fstat", return_value=changed,
        ), patch("static_io.os.fdopen") as wrapped, patch("static_io.os.close"):
            self.assert_reason("input-changed-before-read", lambda: _read_regular(
                file, expected, 100,
            ))
            wrapped.assert_not_called()

    def test_total_count_and_depth_limits(self) -> None:
        (self.root / "a").write_bytes(b"123")
        (self.root / "b").write_bytes(b"456")
        self.assert_reason("byte-limit", lambda: inventory(
            self.root, limits=Limits(max_total_bytes=5),
        ))
        self.assert_reason("file-count-limit", lambda: inventory(
            self.root, limits=Limits(max_files=1),
        ))
        self.assert_reason("entry-count-limit", lambda: inventory(
            self.root, limits=Limits(max_entries=1),
        ))
        self.assert_reason("depth-limit", lambda: inventory(
            self.root, limits=Limits(max_depth=0),
        ))

    def test_unreadable_file_fails_coverage(self) -> None:
        (self.root / "file").write_bytes(b"content")
        with patch("static_io.os.open", side_effect=PermissionError("synthetic")):
            self.assert_reason("unreadable-input", lambda: inventory(self.root))

    def test_symlink_to_disposable_sibling_is_rejected(self) -> None:
        sibling = self.base / "sibling"
        sibling.write_bytes(b"synthetic sentinel")
        try:
            (self.root / "SKILL.md").symlink_to(sibling)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"OS symlink creation unavailable: {type(error).__name__}")
        with patch("static_io.os.open") as opened:
            self.assert_reason("link-or-reparse-point", lambda: inventory(self.root))
            opened.assert_not_called()
        self.assertEqual(sibling.read_bytes(), b"synthetic sentinel")

    def _mock_file_type(self, mode: int, attributes: int = 0):
        target = self.root / "special"
        target.write_bytes(b"")
        original = Path.lstat

        def replacement(path, *args, **kwargs):
            result = original(path, *args, **kwargs)
            if path == target:
                return SimpleNamespace(st_mode=mode, st_file_attributes=attributes)
            return result

        return patch.object(Path, "lstat", replacement)

    def test_mocked_fifo_and_device_are_refused_without_open(self) -> None:
        for mode in (stat.S_IFIFO, stat.S_IFCHR, stat.S_IFBLK):
            with self.subTest(mode=mode), self._mock_file_type(mode), patch(
                "static_io.os.open",
            ) as opened:
                self.assert_reason("non-regular-file", lambda: inventory(self.root))
                opened.assert_not_called()

    def test_mocked_reparse_point_is_refused_without_open(self) -> None:
        with self._mock_file_type(stat.S_IFREG, 0x0400), patch(
            "static_io.os.open",
        ) as opened:
            self.assert_reason("link-or-reparse-point", lambda: inventory(self.root))
            opened.assert_not_called()

    def test_digest_is_byte_ordered_and_snapshot_consistent(self) -> None:
        snapshot = {"a": b"lower", "B": b"upper"}
        expected = hashlib.sha256()
        for name in ("B", "a"):
            expected.update(name.encode("utf-8") + b"\0")
            expected.update(hashlib.sha256(snapshot[name]).digest() + b"\0")
        self.assertEqual(tree_digest(snapshot), expected.hexdigest())
        file = self.root / "content"
        file.write_bytes(b"before")
        captured, _ = inventory(self.root)
        digest = tree_digest(captured)
        file.write_bytes(b"after")
        self.assertEqual(tree_digest(captured), digest)
        self.assertNotEqual(tree_digest(inventory(self.root)[0]), digest)

    def test_digest_rejects_ambiguous_names(self) -> None:
        for name in ("../escape", "/escape", "a//b", "a\\b", "C:/escape"):
            with self.subTest(name=name):
                self.assert_reason("invalid-snapshot-name", lambda: tree_digest({name: b""}))


class OutputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="ai4s-review-output-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "input"
        self.root.mkdir()

    def test_fresh_output_and_exclusive_artifact(self) -> None:
        output = fresh_output(self.base / "output", [self.root])
        write_exclusive(output, "catalog.json", b"first")
        with self.assertRaises(AuditBoundaryError):
            write_exclusive(output, "catalog.json", b"replacement")
        self.assertEqual((output / "catalog.json").read_bytes(), b"first")
        with self.assertRaises(AuditBoundaryError):
            fresh_output(output, [self.root])

    def test_input_descendant_overlap_is_refused(self) -> None:
        with self.assertRaises(AuditBoundaryError) as caught:
            fresh_output(self.root / "audit", [self.root])
        self.assertEqual(caught.exception.reason, "output-input-overlap")
        self.assertFalse((self.root / "audit").exists())

    def test_input_ancestor_overlap_is_refused(self) -> None:
        output = self.base / "future"
        with self.assertRaises(AuditBoundaryError) as caught:
            fresh_output(output, [output / "input"])
        self.assertEqual(caught.exception.reason, "output-input-overlap")
        self.assertFalse(output.exists())

    def test_output_link_collision_preserves_sibling(self) -> None:
        output = fresh_output(self.base / "output", [self.root])
        sibling = self.base / "sentinel"
        sibling.write_bytes(b"keep")
        try:
            (output / "catalog.json").symlink_to(sibling)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"OS symlink creation unavailable: {type(error).__name__}")
        with self.assertRaises(AuditBoundaryError):
            write_exclusive(output, "catalog.json", b"overwrite")
        self.assertEqual(sibling.read_bytes(), b"keep")

    def test_output_name_cannot_escape(self) -> None:
        output = fresh_output(self.base / "output", [self.root])
        for name in ("../escape", "/escape", "a\\b", "C:escape", ""):
            with self.subTest(name=name), self.assertRaises(AuditBoundaryError):
                write_exclusive(output, name, b"content")

    def test_csv_neutralizes_formulas_after_controls_or_whitespace(self) -> None:
        values = ("=1+1", " +1", "\t-1", "\ufeff@SUM(A1)", "\u200b=1")
        buffer = io.StringIO(newline="")
        csv.writer(buffer).writerow(csv_safe(value) for value in values)
        rendered = next(csv.reader(io.StringIO(buffer.getvalue())))
        self.assertTrue(all(value.startswith("'") for value in rendered))
        self.assertFalse(any("\t" in value or "\ufeff" in value for value in rendered))

    def test_markdown_cell_cannot_inject_rows_links_or_html(self) -> None:
        result = markdown_safe('|\n![image](https://example.invalid)<script>&`')
        self.assertNotIn("\n", result)
        self.assertNotIn("<script>", result)
        self.assertIn("&lt;script&gt;", result)
        self.assertIn("\\|", result)
        self.assertIn("\\!\\[", result)
        self.assertIn("\\`", result)


if __name__ == "__main__":
    unittest.main()
