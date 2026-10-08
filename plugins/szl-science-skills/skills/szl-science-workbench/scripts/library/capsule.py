# SPDX-License-Identifier: Apache-2.0
# Modified 2026-09-30: original bounded replay-declaration extensions to SZL baseline
# 9668f1571315e93ca2059b9a44f12beef483532d.
"""Explicit file manifests; never execute recorded commands."""
import hashlib
import json
import math
import pathlib
import re


def szl_capsule_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def szl_capsule_metadata(value, depth=0):
    """Reject common credential fields; this is a guard, not content redaction."""
    if depth > 32:
        raise ValueError("Manifest declarations exceed nesting bound")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or re.search(r"(^|[-_.])(passwords?|secrets?|credentials?|api[-_]?key|access[-_]?token)([-_.]|$)", key, re.I):
                raise ValueError("Credential-like declaration fields are excluded")
            szl_capsule_metadata(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            szl_capsule_metadata(item, depth + 1)
    elif value is not None and not isinstance(value, (str, int, float, bool)):
        raise ValueError("Manifest declarations must be JSON values")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Manifest declarations must be finite")


def szl_capsule_path(relative):
    if not isinstance(relative, str) or not 1 <= len(relative) <= 512 or "\\" in relative or ":" in relative or any(ord(c) < 32 for c in relative):
        raise ValueError("Use bounded relative POSIX file paths")
    parts = pathlib.PurePosixPath(relative)
    if parts.is_absolute() or ".." in parts.parts or str(parts) != relative:
        raise ValueError("Noncanonical or escaping path")
    for part in parts.parts:
        if part.lower() in (".env", ".ssh", ".aws", ".git", ".codex", ".netrc", ".npmrc") or part.lower().startswith("id_rsa") or re.search(r"(^|[-_.])(passwords?|secrets?|credentials?|api[-_]?key|access[-_]?token)([-_.]|$)", part, re.I):
            raise ValueError("Credential-like and private configuration paths are excluded")
    return parts


def szl_capsule_file(root, relative):
    declared_base = pathlib.Path(root)
    if declared_base.is_symlink() or (hasattr(declared_base, "is_junction") and declared_base.is_junction()) or getattr(declared_base.lstat(), "st_file_attributes", 0) & 0x400:
        raise ValueError("Symlink and reparse-point roots are excluded")
    base = declared_base.resolve(strict=True)
    if not base.is_dir():
        raise ValueError("Use a directory root and relative POSIX file paths")
    parts = szl_capsule_path(relative)
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
    if before.st_size > 8 * 1024 * 1024:
        raise ValueError("Individual retained files are bounded at 8 MiB")
    h = hashlib.sha256()
    read_bytes = 0
    with resolved.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            read_bytes += len(chunk)
            if read_bytes > 8 * 1024 * 1024:
                raise ValueError("File grew beyond the retained-file byte bound")
            h.update(chunk)
    after = resolved.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino, before.st_dev) != (after.st_size, after.st_mtime_ns, after.st_ino, after.st_dev) or read_bytes != after.st_size:
        raise ValueError("File changed while hashing")
    return {"path": relative, "size_bytes": after.st_size, "sha256": h.hexdigest()}


def szl_validate_replay(replay, file_entries):
    """Validate inert replay declarations only; never interpret or execute argv."""
    if not isinstance(replay, dict) or set(replay) != {"schema", "argv", "environment", "analysis_plan", "seed", "limits", "expected_outputs"} or replay.get("schema") != "szl.offline-replay.v1":
        raise ValueError("Expected an exact szl.offline-replay.v1 declaration")
    if not isinstance(file_entries, list) or not 1 <= len(file_entries) <= 128:
        raise ValueError("Replay needs a bounded retained-file list")
    declared_paths = set()
    for entry in file_entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "size_bytes", "sha256", "role"}:
            raise ValueError("Replay files need exact path/size/digest/role entries")
        szl_capsule_path(entry["path"])
        if entry["path"] in declared_paths or entry["role"] not in ("input", "source", "environment", "analysis_plan", "output", "protocol"):
            raise ValueError("Duplicate replay file or invalid role")
        if not isinstance(entry["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]) or type(entry["size_bytes"]) is not int or not 0 <= entry["size_bytes"] <= 8 * 1024 * 1024:
            raise ValueError("Replay file digest/size is invalid")
        declared_paths.add(entry["path"])
    by_path = {entry["path"]: entry for entry in file_entries}
    roles = {entry.get("role") for entry in file_entries}
    if not {"input", "source", "environment", "analysis_plan", "output"}.issubset(roles):
        raise ValueError("Replay requires input/source/environment/analysis_plan/output roles")
    argv = replay["argv"]
    if not isinstance(argv, list) or not 2 <= len(argv) <= 64 or any(not isinstance(arg, str) or not 1 <= len(arg) <= 512 or any(ord(c) < 32 for c in arg) for arg in argv):
        raise ValueError("Replay argv must be a bounded inert string list")
    if argv[0] not in ("python", "python3"):
        raise ValueError("Replay declaration supports a Python source entrypoint only")
    if argv[1].startswith("-"):
        raise ValueError("Replay entrypoint cannot be an interpreter option or stdin marker")
    szl_capsule_path(argv[1])
    if argv[1] not in by_path or by_path[argv[1]].get("role") != "source" or not argv[1].endswith(".py"):
        raise ValueError("Replay entrypoint must be a retained .py source file")
    if any(re.search(r"[;&|`<>]|\$\(|\$\{|(^|[-_])(passwords?|secrets?|tokens?|api[-_]?key|credentials?)([-_=]|$)", arg, re.I) for arg in argv[2:]):
        raise ValueError("Shell-like or credential-like replay arguments are excluded")
    for field, role in (("environment", "environment"), ("analysis_plan", "analysis_plan")):
        reference = replay[field]
        if not isinstance(reference, dict) or set(reference) != {"path", "sha256"}:
            raise ValueError("Replay environment and analysis plan need retained path/digest references")
        szl_capsule_path(reference["path"])
        entry = by_path.get(reference["path"])
        if entry is None or entry.get("role") != role or reference["sha256"] != entry["sha256"]:
            raise ValueError("Replay environment or analysis-plan binding disagrees with retained bytes")
    if type(replay["seed"]) is not int or not 0 <= replay["seed"] <= 4294967295:
        raise ValueError("Replay seed must be an unsigned 32-bit integer")
    limits = replay["limits"]
    if not isinstance(limits, dict) or set(limits) != {"network", "process_spawn", "secret_access", "max_seconds", "max_memory_mib"}:
        raise ValueError("Replay needs exact resource and denied-capability declarations")
    if any(limits[key] != "denied" for key in ("network", "process_spawn", "secret_access")):
        raise ValueError("Replay declarations must deny network, process spawning and secret access")
    if type(limits["max_seconds"]) is not int or not 1 <= limits["max_seconds"] <= 300 or type(limits["max_memory_mib"]) is not int or not 16 <= limits["max_memory_mib"] <= 1024:
        raise ValueError("Replay resource declarations exceed bounded offline limits")
    expected = replay["expected_outputs"]
    if not isinstance(expected, list) or not 1 <= len(expected) <= 64:
        raise ValueError("Declare between 1 and 64 expected outputs")
    seen = set()
    for item in expected:
        if not isinstance(item, dict) or set(item) != {"path", "sha256", "comparison"}:
            raise ValueError("Expected output requires a retained path/digest and comparison policy")
        szl_capsule_path(item["path"])
        entry = by_path.get(item["path"])
        if item["path"] in seen or entry is None or entry.get("role") != "output" or item["sha256"] != entry["sha256"]:
            raise ValueError("Duplicate or unbound expected output")
        seen.add(item["path"])
        comparison = item["comparison"]
        if not isinstance(comparison, dict):
            raise ValueError("Expected output comparison must be an object")
        if comparison == {"mode": "exact_bytes"}:
            continue
        if set(comparison) != {"mode", "absolute_tolerance", "relative_tolerance", "predeclared"} or comparison.get("mode") != "numeric_tolerance" or comparison.get("predeclared") is not True:
            raise ValueError("Use exact bytes or an explicitly predeclared numeric tolerance")
        for key in ("absolute_tolerance", "relative_tolerance"):
            value = comparison[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError("Numeric tolerances must be finite nonnegative values")
    if seen != {entry["path"] for entry in file_entries if entry.get("role") == "output"}:
        raise ValueError("Every retained output needs an expected-output comparison")
    return {"specification": "VALIDATED", "replay_ready": True, "execution": "NOT_RUN",
            "capability_denial": "DECLARED_ONLY", "tolerance_application": "NOT_RUN",
            "scientific_performance": "NOT_MEASURED"}


def szl_make_capsule(root, files, metadata=None, replay=None):
    if not isinstance(files, list) or not 1 <= len(files) <= 128:
        raise ValueError("Declare between 1 and 128 unique relative files")
    selected, seen = [], set()
    for item in files:
        if isinstance(item, str):
            declaration = {"path": item}
        elif isinstance(item, dict) and set(item) == {"path", "role"} and item["role"] in ("input", "source", "environment", "analysis_plan", "output", "protocol"):
            declaration = dict(item)
        else:
            raise ValueError("Files must be paths or exact path/role declarations")
        szl_capsule_path(declaration["path"])
        if declaration["path"] in seen:
            raise ValueError("Declare unique file paths")
        seen.add(declaration["path"])
        selected.append(declaration)
    meta = {} if metadata is None else metadata
    if not isinstance(meta, dict):
        raise ValueError("metadata must be an object")
    szl_capsule_metadata(meta)
    if len(json.dumps(meta, allow_nan=False).encode()) > 65536:
        raise ValueError("Metadata exceeds 64 KiB")
    entries, total = [], 0
    for declaration in sorted(selected, key=lambda value: value["path"]):
        entry = szl_capsule_file(root, declaration["path"])
        total += entry["size_bytes"]
        if total > 32 * 1024 * 1024:
            raise ValueError("Total retained files exceed 32 MiB")
        if "role" in declaration:
            entry["role"] = declaration["role"]
        entries.append(entry)
    if replay is not None:
        # Replay uses an exact typed schema, including secret_access="denied".
        # Credential fields are rejected by that schema, not by metadata heuristics.
        szl_validate_replay(replay, entries)
    record = {"schema": "szl.reproducibility-capsule.v1", "files": entries,
              "metadata": meta, "signed": False, "scope": "Byte integrity against this retained unsigned manifest; scientific claims not verified"}
    if replay is not None:
        record["replay"] = replay
    return dict(record, capsule_sha256=szl_capsule_digest(record))


def szl_verify_capsule(root, capsule):
    if not isinstance(capsule, dict) or capsule.get("schema") != "szl.reproducibility-capsule.v1" or capsule.get("signed") is not False:
        raise ValueError("Expected an unsigned reproducibility capsule")
    if set(capsule) - {"schema", "files", "metadata", "signed", "scope", "replay", "capsule_sha256"}:
        raise ValueError("Unknown capsule fields")
    body = {k: v for k, v in capsule.items() if k != "capsule_sha256"}
    if not isinstance(capsule.get("capsule_sha256"), str) or szl_capsule_digest(body) != capsule["capsule_sha256"]:
        return {"integrity": "MANIFEST_CHANGED", "authentic": False, "scientific_claims_verified": False,
                "replay_ready": False, "execution": "NOT_RUN", "scientific_performance": "NOT_MEASURED"}
    files = capsule.get("files")
    if not isinstance(files, list) or not 1 <= len(files) <= 128:
        raise ValueError("File manifest must contain between 1 and 128 entries")
    if not isinstance(capsule.get("metadata"), dict) or len(json.dumps(capsule["metadata"], allow_nan=False).encode()) > 65536:
        raise ValueError("Retained metadata must be an object of at most 64 KiB")
    szl_capsule_metadata(capsule.get("metadata"))
    seen, results, total = set(), [], 0
    for entry in files:
        if not isinstance(entry, dict) or set(entry) not in ({"path", "size_bytes", "sha256"}, {"path", "size_bytes", "sha256", "role"}) or not isinstance(entry.get("path"), str) or entry["path"] in seen:
            raise ValueError("Invalid or duplicate entry")
        seen.add(entry["path"])
        if "role" in entry and entry["role"] not in ("input", "source", "environment", "analysis_plan", "output", "protocol"):
            raise ValueError("Invalid retained-file role")
        if not isinstance(entry.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]) or type(entry.get("size_bytes")) is not int or not 0 <= entry["size_bytes"] <= 8 * 1024 * 1024:
            raise ValueError("Invalid hash or size")
        total += entry["size_bytes"]
        if total > 32 * 1024 * 1024:
            raise ValueError("Declared retained bytes exceed 32 MiB")
        try:
            actual = szl_capsule_file(root, entry["path"])
            status = "MATCH" if all(actual[key] == entry[key] for key in ("path", "size_bytes", "sha256")) else "CHANGED"
        except FileNotFoundError:
            status = "MISSING"
        except (ValueError, OSError):
            status = "UNREADABLE_OR_UNSAFE_PATH"
        results.append({"path": entry["path"], "status": status})
    results.sort(key=lambda value: value["path"])
    replay_result = {"specification": "NOT_SPECIFIED", "replay_ready": False, "execution": "NOT_RUN"}
    if "replay" in capsule:
        replay_result = szl_validate_replay(capsule["replay"], files)
    match = all(r["status"] == "MATCH" for r in results)
    replay_result["replay_ready"] = replay_result["replay_ready"] and match
    return {"integrity": "MATCH" if all(r["status"] == "MATCH" for r in results) else "MISMATCH",
            "files": results, "authentic": False, "scientific_claims_verified": False,
            "replay_ready": replay_result["replay_ready"], "replay_validation": replay_result,
            "execution": "NOT_RUN", "scientific_performance": "NOT_MEASURED",
            "limitation": "A replaced or truncated manifest needs an independently retained digest or signature to detect"}
