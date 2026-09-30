# SPDX-License-Identifier: Apache-2.0
"""Explicit file manifests; never execute recorded commands."""
import hashlib
import json
import pathlib
import re


def szl_capsule_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def szl_capsule_file(root, relative):
    base = pathlib.Path(root).resolve(strict=True)
    if not base.is_dir() or not isinstance(relative, str) or not relative or "\\" in relative or ":" in relative:
        raise ValueError("Use a directory root and relative POSIX file paths")
    parts = pathlib.PurePosixPath(relative)
    if parts.is_absolute() or ".." in parts.parts or str(parts) != relative:
        raise ValueError("Noncanonical or escaping path")
    path = base
    for part in parts.parts:
        path = path / part
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise ValueError("Symlinks and junctions are excluded")
        if getattr(path.lstat(), "st_file_attributes", 0) & 0x400:
            raise ValueError("Windows reparse points are excluded")
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(base) or not resolved.is_file():
        raise ValueError("File must be inside declared root")
    before = resolved.stat()
    h = hashlib.sha256()
    with resolved.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    after = resolved.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("File changed while hashing")
    return {"path": relative, "size_bytes": after.st_size, "sha256": h.hexdigest()}


def szl_make_capsule(root, files, metadata=None):
    if not isinstance(files, list) or not files or any(not isinstance(p, str) for p in files) or len(set(files)) != len(files):
        raise ValueError("Declare nonempty unique relative files")
    meta = {} if metadata is None else metadata
    if not isinstance(meta, dict):
        raise ValueError("metadata must be an object")
    record = {"schema": "szl.reproducibility-capsule.v1", "files": [szl_capsule_file(root, p) for p in sorted(files)],
              "metadata": meta, "signed": False, "scope": "Byte integrity against this retained unsigned manifest; scientific claims not verified"}
    return dict(record, capsule_sha256=szl_capsule_digest(record))


def szl_verify_capsule(root, capsule):
    if not isinstance(capsule, dict) or capsule.get("schema") != "szl.reproducibility-capsule.v1" or capsule.get("signed") is not False:
        raise ValueError("Expected an unsigned reproducibility capsule")
    body = {k: v for k, v in capsule.items() if k != "capsule_sha256"}
    if not isinstance(capsule.get("capsule_sha256"), str) or szl_capsule_digest(body) != capsule["capsule_sha256"]:
        return {"integrity": "MANIFEST_CHANGED", "authentic": False, "scientific_claims_verified": False}
    files = capsule.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("Empty file manifest")
    seen, results = set(), []
    for entry in files:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str) or entry["path"] in seen:
            raise ValueError("Invalid or duplicate entry")
        seen.add(entry["path"])
        if not isinstance(entry.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]) or type(entry.get("size_bytes")) is not int or entry["size_bytes"] < 0:
            raise ValueError("Invalid hash or size")
        try:
            actual = szl_capsule_file(root, entry["path"])
            status = "MATCH" if actual == entry else "CHANGED"
        except FileNotFoundError:
            status = "MISSING"
        except (ValueError, OSError):
            status = "UNREADABLE_OR_UNSAFE_PATH"
        results.append({"path": entry["path"], "status": status})
    return {"integrity": "MATCH" if all(r["status"] == "MATCH" for r in results) else "MISMATCH",
            "files": results, "authentic": False, "scientific_claims_verified": False,
            "limitation": "A replaced or truncated manifest needs an independently retained digest or signature to detect"}
