"""Bounded snapshot and presentation helpers for the proposed static auditor.

These helpers do not execute input files or Git. They require caller-held,
immutable input directories. Metadata checks and descriptor identity checks
detect ordinary replacements, but are not an OS sandbox against an adversary
mutating ancestors concurrently. Hard-link provenance is not established.

The content digest commits to relative UTF-8 names and captured file bytes.
It does not commit to permissions or empty directories. Links and special
files are rejected. Only root-level .git administrative metadata is excluded,
and that exclusion is always recorded in coverage.
"""

from __future__ import annotations

import hashlib
import html
import os
import re
import stat
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


class AuditBoundaryError(Exception):
    """A boundary or coverage failure that must prevent an audit PASS."""

    def __init__(self, reason: str, path: object = "") -> None:
        self.reason = reason
        self.path = str(path)
        super().__init__(f"{reason}: {self.path}" if self.path else reason)


@dataclass(frozen=True)
class Limits:
    max_file_bytes: int = 2_000_000
    max_total_bytes: int = 20_000_000
    max_files: int = 10_000
    max_entries: int = 20_000
    max_depth: int = 32

    def __post_init__(self) -> None:
        for name in ("max_file_bytes", "max_total_bytes", "max_files", "max_entries"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if type(self.max_depth) is not int or self.max_depth < 0:
            raise ValueError("max_depth must be a nonnegative integer")


DEFAULT_LIMITS = Limits()
_REPARSE_POINT = 0x0400


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _is_link_or_reparse(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & _REPARSE_POINT
    )


def _stat_signature(
    info: os.stat_result, *, cross_api: bool = False,
) -> tuple[Any, ...]:
    change_time = getattr(info, "st_ctime_ns", info.st_ctime)
    if cross_api and os.name == "nt":
        # Windows Python 3.12 can report creation time through lstat and
        # metadata-change time through fstat. Birth time has common semantics.
        # Older Windows Python uses creation time for both ctime fields.
        change_time = getattr(
            info, "st_birthtime_ns", getattr(info, "st_birthtime", change_time),
        )
    return (
        info.st_dev, info.st_ino, info.st_mode, info.st_size,
        getattr(info, "st_mtime_ns", info.st_mtime),
        change_time,
    )


def _check_existing_components(path: Path) -> bool:
    """Check existing components; return whether the entire path exists."""
    components = [*reversed(path.parents), path]
    for index, component in enumerate(components):
        try:
            info = component.lstat()
        except FileNotFoundError:
            return False
        except OSError as error:
            raise AuditBoundaryError("unreadable-path-metadata", component) from error
        if _is_link_or_reparse(info):
            raise AuditBoundaryError("link-or-reparse-point", component)
        if index < len(components) - 1 and not stat.S_ISDIR(info.st_mode):
            raise AuditBoundaryError("non-directory-ancestor", component)
    return True


def _root_boundary(root: Path) -> Path:
    absolute = _absolute(root)
    if not _check_existing_components(absolute):
        raise AuditBoundaryError("missing-input", absolute)
    try:
        info = absolute.lstat()
    except OSError as error:
        raise AuditBoundaryError("unreadable-input-metadata", absolute) from error
    if not stat.S_ISDIR(info.st_mode):
        raise AuditBoundaryError("input-not-directory", absolute)
    return absolute


def _read_regular(path: Path, expected: os.stat_result, limit: int) -> bytes:
    """Read at most limit+1 bytes after rejecting non-regular input."""
    if _is_link_or_reparse(expected):
        raise AuditBoundaryError("link-or-reparse-point", path)
    if not stat.S_ISREG(expected.st_mode):
        raise AuditBoundaryError("non-regular-file", path)
    if expected.st_size > limit:
        raise AuditBoundaryError("byte-limit", path)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or _is_link_or_reparse(opened):
            raise AuditBoundaryError("non-regular-file", path)
        if _stat_signature(opened, cross_api=True) != _stat_signature(
            expected, cross_api=True,
        ):
            raise AuditBoundaryError("input-changed-before-read", path)
        if opened.st_size > limit:
            raise AuditBoundaryError("byte-limit", path)
        handle = os.fdopen(descriptor, "rb")
        descriptor = None  # The file object now owns the descriptor.
        with handle:
            chunks: list[bytes] = []
            byte_count = 0
            while byte_count <= limit:
                chunk = handle.read(min(65_536, limit + 1 - byte_count))
                if not chunk:
                    break
                chunks.append(chunk)
                byte_count += len(chunk)
            if byte_count > limit:
                raise AuditBoundaryError("byte-limit", path)
            after = os.fstat(handle.fileno())
            if _stat_signature(after) != _stat_signature(opened):
                raise AuditBoundaryError("input-changed-during-read", path)
            if byte_count != opened.st_size:
                raise AuditBoundaryError("input-size-changed", path)
            return b"".join(chunks)
    except OSError as error:
        raise AuditBoundaryError("unreadable-input", path) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _canonical_name(name: str) -> bytes:
    if not isinstance(name, str) or not name or name.startswith("/"):
        raise AuditBoundaryError("invalid-snapshot-name", name)
    if "\\" in name or "\x00" in name or re.match(r"^[A-Za-z]:", name):
        raise AuditBoundaryError("invalid-snapshot-name", name)
    if any(part in {"", ".", ".."} for part in name.split("/")):
        raise AuditBoundaryError("invalid-snapshot-name", name)
    try:
        return name.encode("utf-8", errors="strict")
    except UnicodeError as error:
        raise AuditBoundaryError("non-utf8-snapshot-name", name) from error


def read_single(path: Path, max_bytes: int = 65_536) -> bytes:
    """Read one regular bounded file, without traversing its parent directory."""
    if type(max_bytes) is not int or max_bytes < 1:
        raise ValueError("max_bytes must be a positive integer")
    absolute = _absolute(path)
    if not _check_existing_components(absolute):
        raise AuditBoundaryError("missing-input", absolute)
    try:
        info = absolute.lstat()
    except OSError as error:
        raise AuditBoundaryError("unreadable-input-metadata", absolute) from error
    return _read_regular(absolute, info, max_bytes)


def inventory(
    root: Path, *, limits: Limits = DEFAULT_LIMITS,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    """Capture one bounded snapshot, or raise on incomplete eligible coverage.

    All file contents, including binary and NUL-containing files, are captured.
    Main must decode strictly and report any unscannable content explicitly.
    No filename-extension, node_modules, or __pycache__ omissions are made.
    """
    boundary = _root_boundary(root)
    snapshot: dict[str, bytes] = {}
    excluded: list[str] = []
    total_bytes = 0
    entries_seen = 0
    deepest = 0
    stack = [(boundary, 0)]
    while stack:
        directory, depth = stack.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    entries_seen += 1
                    if entries_seen > limits.max_entries:
                        raise AuditBoundaryError("entry-count-limit", directory)
                    path = directory / entry.name
                    relative = path.relative_to(boundary).as_posix()
                    _canonical_name(relative)
                    info = path.lstat()
                    if _is_link_or_reparse(info):
                        raise AuditBoundaryError("link-or-reparse-point", path)
                    child_depth = depth + 1
                    deepest = max(deepest, child_depth)
                    if child_depth > limits.max_depth:
                        raise AuditBoundaryError("depth-limit", path)
                    if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                        raise AuditBoundaryError("non-regular-file", path)
                    if directory == boundary and entry.name == ".git":
                        excluded.append(relative)
                        continue
                    if stat.S_ISDIR(info.st_mode):
                        stack.append((path, child_depth))
                        continue
                    if len(snapshot) >= limits.max_files:
                        raise AuditBoundaryError("file-count-limit", path)
                    remaining = limits.max_total_bytes - total_bytes
                    data = _read_regular(path, info, min(limits.max_file_bytes, remaining))
                    snapshot[relative] = data
                    total_bytes += len(data)
        except OSError as error:
            raise AuditBoundaryError("unreadable-input", directory) from error
    return snapshot, {
        "complete": True,
        "scope": "all file content except root-level .git administrative metadata",
        "excluded_paths": sorted(excluded),
        "files": len(snapshot),
        "bytes": total_bytes,
        "entries": entries_seen,
        "max_depth": deepest,
    }


def tree_digest(snapshot: Mapping[str, bytes]) -> str:
    """Hash captured names/bytes in canonical relative UTF-8 byte order."""
    ordered = sorted((_canonical_name(name), name) for name in snapshot)
    digest = hashlib.sha256()
    for encoded_name, name in ordered:
        data = snapshot[name]
        if not isinstance(data, bytes):
            raise AuditBoundaryError("snapshot-content-not-bytes", name)
        digest.update(encoded_name)
        digest.update(b"\0")
        digest.update(hashlib.sha256(data).digest())
        digest.update(b"\0")
    return digest.hexdigest()


def fresh_output(out: Path, roots: Iterable[Path]) -> Path:
    """Create a fresh output directory with no input/ancestor overlap."""
    output = _absolute(out)
    if _check_existing_components(output):
        raise AuditBoundaryError("output-already-exists", output)
    for root in roots:
        source = _absolute(root)
        _check_existing_components(source)
        if output == source or output in source.parents or source in output.parents:
            raise AuditBoundaryError("output-input-overlap", output)
    try:
        output.mkdir(parents=True, exist_ok=False)
    except OSError as error:
        raise AuditBoundaryError("cannot-create-output", output) from error
    if not _check_existing_components(output) or not output.is_dir():
        raise AuditBoundaryError("output-boundary-changed", output)
    return output


def write_exclusive(out: Path, name: str, data: bytes) -> None:
    """Create one artifact exclusively; never follow an existing file link."""
    if (
        not isinstance(name, str) or name in {"", ".", ".."}
        or any(character in name for character in ("/", "\\", "\0", ":"))
    ):
        raise AuditBoundaryError("invalid-output-name", name)
    if not isinstance(data, bytes):
        raise TypeError("output data must be bytes")
    output = _absolute(out)
    if not _check_existing_components(output) or not output.is_dir():
        raise AuditBoundaryError("output-not-directory", output)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(output / name, flags, 0o600)
        handle = os.fdopen(descriptor, "wb")
        descriptor = None
        with handle:
            handle.write(data)
    except OSError as error:
        raise AuditBoundaryError("cannot-create-artifact", output / name) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _display_controls(value: str) -> str:
    display: list[str] = []
    common = {"\n": "\\n", "\r": "\\r", "\t": "\\t"}
    for character in value:
        if character in common:
            display.append(common[character])
        elif unicodedata.category(character) in {"Cc", "Cf", "Cs"}:
            codepoint = ord(character)
            display.append(
                f"\\u{codepoint:04x}" if codepoint <= 0xFFFF else f"\\U{codepoint:08x}"
            )
        else:
            display.append(character)
    return "".join(display)


def csv_safe(value: object) -> str:
    """Display controls and neutralize spreadsheet formula-leading values."""
    raw = "" if value is None else str(value)
    meaningful = next(
        (character for character in raw if not character.isspace()
         and unicodedata.category(character) not in {"Cc", "Cf", "Cs"}),
        "",
    )
    display = _display_controls(raw)
    return "'" + display if meaningful in {"=", "+", "-", "@"} else display


def markdown_safe(value: object) -> str:
    """Return a literal Markdown table cell without links, HTML, or newlines."""
    display = _display_controls("" if value is None else str(value))
    escaped = html.escape(display, quote=True)
    return re.sub(r"([\\`*_{}\[\]()|!#])", r"\\\1", escaped)
