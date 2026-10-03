"""Offline literal dependency discovery from verified local Git objects.

This is discovery evidence, never a dependency closure, vulnerability scan,
independent gate, installation decision, or permission to execute a skill.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading

from trust_common import ValidationError, repository as repository_identity, strict_json

SCHEMA = "ai4s.dependency-discovery/v0"
REPOSITORY = "ai4science-skills/skills"
MAX_FILE = 512 * 1024
MAX_BYTES = 32 * 1024 * 1024
MAX_ITEMS = 5000
MAX_DEPTH = 16
MAX_NODES = 30000
MAX_FINDINGS = 5000
MAX_TOTAL_FINDINGS = 20000
MAX_REPORT = 2 * 1024 * 1024
HEX = re.compile(r"[0-9a-f]{40}\Z")
NAME = re.compile(r"[a-z0-9][a-z0-9-]{1,63}\Z")
MODULE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*\Z")
PIN = re.compile(r"([A-Za-z0-9][A-Za-z0-9._-]{0,99})==([A-Za-z0-9][A-Za-z0-9._+!-]{0,99})\Z")
DECLARATIONS = {"pyproject.toml", "setup.py", "setup.cfg", "Pipfile", "Pipfile.lock",
                "poetry.lock", "uv.lock", "package.json", "package-lock.json",
                "yarn.lock", "pnpm-lock.yaml", "environment.yml", "environment.yaml"}


class DiscoveryError(ValueError):
    """Only fixed reason codes may leave the CLI."""


def _oid(kind, raw):
    return hashlib.sha1(kind.encode("ascii") + b" " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()


def _path(value):
    reserved = {"con", "prn", "aux", "nul"} | {"com" + str(n) for n in range(1, 10)} | {"lpt" + str(n) for n in range(1, 10)}
    parts = value.split("/")
    if (not value or len(value) > 512 or any(not re.fullmatch(r"[A-Za-z0-9_.-]+", p)
            or p in {".", "..", ".git"} or p.endswith(".")
            or p.split(".")[0].lower() in reserved for p in parts)):
        raise DiscoveryError("UNSAFE_TREE_PATH")
    return value


class GitObjects:
    """Use only Git's object reader. No checkout, filters, hooks, or fetch."""

    def __init__(self, repository):
        self.repository = Path(repository).absolute()
        self.git = shutil.which("git")
        if not self.git:
            raise DiscoveryError("GIT_UNAVAILABLE")
        self.env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        self.env.update(GIT_NO_REPLACE_OBJECTS="1", GIT_CONFIG_NOSYSTEM="1",
                        GIT_CONFIG_SYSTEM=os.devnull, GIT_CONFIG_GLOBAL=os.devnull,
                        GIT_CONFIG_COUNT="0", GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0",
                        GIT_NO_LAZY_FETCH="1", GIT_ALLOW_PROTOCOL="", GIT_PROTOCOL_FROM_USER="0")

    def command(self, args, data, limit):
        # A bounded input file avoids stdin/stdout pipe deadlocks with many IDs.
        with tempfile.TemporaryFile() as input_file:
            input_file.write(data)
            input_file.seek(0)
            try:
                process = subprocess.Popen([self.git, "--no-pager", "--no-lazy-fetch",
                                            "-c", "protocol.allow=never", "-c", "credential.helper=",
                                            "-c", "core.hooksPath=" + os.devnull, "-c", "core.fsmonitor=false",
                                            "-C", str(self.repository), *args],
                                           stdin=input_file, stdout=subprocess.PIPE,
                                           stderr=subprocess.DEVNULL, env=self.env)
            except OSError:
                raise DiscoveryError("GIT_UNAVAILABLE") from None
            timer = threading.Timer(20, process.kill)
            timer.start()
            try:
                raw = process.stdout.read(limit + 1)
                if len(raw) > limit:
                    process.kill()
                    raise DiscoveryError("GIT_OUTPUT_BOUNDS")
                if process.wait() != 0:
                    raise DiscoveryError("GIT_READ_FAILED")
                return raw
            finally:
                timer.cancel()
                process.stdout.close()
                if process.poll() is None:
                    process.kill()
                process.wait()

    def read(self, identifiers, kind):
        ids = sorted(set(identifiers))
        if not ids or len(ids) > MAX_ITEMS or any(not isinstance(oid, str) or not HEX.fullmatch(oid) for oid in ids):
            raise DiscoveryError("INVALID_OBJECT_IDS")
        request = ("\n".join(ids) + "\n").encode("ascii")
        metadata = self.command(["cat-file", "--batch-check"], request, len(ids) * 100)
        lines = metadata.splitlines()
        if len(lines) != len(ids):
            raise DiscoveryError("OBJECT_METADATA_MISMATCH")
        sizes = []
        for oid, line in zip(ids, lines):
            fields = line.split(b" ")
            if len(fields) != 3 or fields[0] != oid.encode("ascii") or fields[1] != kind.encode("ascii"):
                raise DiscoveryError("OBJECT_METADATA_MISMATCH")
            if not re.fullmatch(rb"[0-9]{1,10}", fields[2]):
                raise DiscoveryError("OBJECT_METADATA_MISMATCH")
            size = int(fields[2])
            if size > MAX_FILE:
                raise DiscoveryError("OBJECT_BYTE_BOUNDS")
            sizes.append(size)
        if sum(sizes) > MAX_BYTES:
            raise DiscoveryError("OBJECT_BYTE_BOUNDS")
        captured = self.command(["cat-file", "--batch"], request, sum(sizes) + len(ids) * 100)
        offset, result = 0, {}
        for oid, size in zip(ids, sizes):
            end = captured.find(b"\n", offset)
            expected = (oid + " " + kind + " " + str(size)).encode("ascii")
            if end < 0 or captured[offset:end] != expected:
                raise DiscoveryError("OBJECT_METADATA_MISMATCH")
            start = end + 1
            raw = captured[start:start + size]
            offset = start + size + 1
            if len(raw) != size or captured[start + size:offset] != b"\n" or _oid(kind, raw) != oid:
                raise DiscoveryError("OBJECT_HASH_MISMATCH")
            result[oid] = raw
        if offset != len(captured):
            raise DiscoveryError("OBJECT_METADATA_MISMATCH")
        return result


def tree(objects, revision):
    if not isinstance(revision, str) or not HEX.fullmatch(revision) or revision == "0" * 40:
        raise DiscoveryError("INVALID_REVISION")
    commit = objects.read([revision], "commit")[revision]
    first = commit.split(b"\n", 1)[0]
    if not re.fullmatch(rb"tree [0-9a-f]{40}", first):
        raise DiscoveryError("INVALID_COMMIT")
    root_oid = first[5:].decode("ascii")
    pending, entries, spellings, count, total = [("", root_oid)], {}, {}, 0, 0
    for depth in range(MAX_DEPTH + 1):
        if not pending:
            return root_oid, entries
        raw_trees = objects.read([oid for _, oid in pending], "tree")
        next_pending = []
        for prefix, oid in pending:
            raw, cursor = raw_trees[oid], 0
            total += len(raw)
            if total > MAX_BYTES:
                raise DiscoveryError("TREE_BOUNDS")
            while cursor < len(raw):
                space, nul = raw.find(b" ", cursor), raw.find(b"\0", cursor)
                if space < cursor or nul < space or nul + 21 > len(raw):
                    raise DiscoveryError("INVALID_TREE")
                mode = raw[cursor:space]
                try:
                    name = raw[space + 1:nul].decode("ascii")
                except UnicodeError:
                    raise DiscoveryError("UNSAFE_TREE_PATH") from None
                if "/" in name:
                    raise DiscoveryError("UNSAFE_TREE_PATH")
                path = _path(prefix + name)
                key = path.casefold()
                if key in spellings:
                    raise DiscoveryError("TREE_PATH_COLLISION")
                spellings[key] = path
                child = raw[nul + 1:nul + 21].hex()
                cursor = nul + 21
                count += 1
                if count > MAX_ITEMS:
                    raise DiscoveryError("TREE_BOUNDS")
                if mode == b"40000":
                    next_pending.append((path + "/", child))
                elif mode in {b"100644", b"100755", b"120000", b"160000"}:
                    entries[path] = {"git_blob_sha1": child, "mode": mode.decode("ascii")}
                else:
                    raise DiscoveryError("UNSUPPORTED_TREE_MODE")
        pending = next_pending
    raise DiscoveryError("TREE_DEPTH_BOUNDS")


def _plugins(raw):
    try:
        document = strict_json(raw)
        entries = document["plugins"]
        if not isinstance(entries, list) or not 1 <= len(entries) <= 100:
            raise DiscoveryError("INVALID_REGISTRY")
        names, sources = set(), []
        for entry in entries:
            name, sha, repository = entry["name"], entry["sha"], entry["repo"]
            if (not isinstance(name, str) or not NAME.fullmatch(name) or name in names
                    or not isinstance(sha, str) or not HEX.fullmatch(sha) or sha == "0" * 40
                    or not isinstance(repository, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)):
                raise DiscoveryError("INVALID_REGISTRY")
            repository_identity(repository)
            names.add(name)
            sources.append({"plugin": name, "declared_repository": repository, "declared_commit": sha,
                            "upstream_parity": "UNKNOWN"})
        return sorted(names), sorted(sources, key=lambda item: item["plugin"])
    except (ValidationError, KeyError, TypeError):
        raise DiscoveryError("INVALID_REGISTRY") from None


def python_literals(raw):
    try:
        parsed = ast.parse(raw.decode("utf-8"), filename="candidate-data.py")
    except (SyntaxError, UnicodeError, RecursionError, ValueError):
        return {"analysis": "UNKNOWN", "imports": [], "unknowns": [{"reason": "PYTHON_PARSE_UNAVAILABLE"}]}
    nodes = []
    for node in ast.walk(parsed):
        nodes.append(node)
        if len(nodes) > MAX_NODES:
            raise DiscoveryError("AST_BOUNDS")
    found, unknowns = [], []
    importlib_names, import_module_names = {"importlib"}, set()
    for node in nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "importlib":
                    importlib_names.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module == "importlib":
            import_module_names.update(alias.asname or alias.name for alias in node.names if alias.name == "import_module")
    for node in nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append({"kind": "import", "module": alias.name, "level": 0, "line": node.lineno})
        elif isinstance(node, ast.ImportFrom):
            found.append({"kind": "from", "module": node.module or "", "level": node.level, "line": node.lineno})
        elif isinstance(node, ast.Call):
            fun = node.func
            direct = isinstance(fun, ast.Name) and (fun.id == "__import__" or fun.id in import_module_names)
            qualified = (isinstance(fun, ast.Attribute) and fun.attr == "import_module"
                         and isinstance(fun.value, ast.Name) and fun.value.id in importlib_names)
            if direct or qualified:
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str) and MODULE.fullmatch(node.args[0].value):
                    found.append({"kind": "syntactic_dynamic_literal", "module": node.args[0].value, "level": 0, "line": node.lineno})
                else:
                    unknowns.append({"reason": "DYNAMIC_IMPORT_UNRESOLVED", "line": node.lineno})
    safe = []
    for item in found:
        if item["module"] == "" and item["level"] > 0 or MODULE.fullmatch(item["module"]):
            safe.append(item)
        else:
            unknowns.append({"reason": "MODULE_IDENTIFIER_UNSUPPORTED", "line": item["line"]})
    if len(safe) + len(unknowns) > MAX_FINDINGS:
        raise DiscoveryError("FINDING_BOUNDS")
    return {"analysis": "DECLARED", "imports": sorted(safe, key=lambda item: (item["line"], item["kind"], item["module"])),
            "unknowns": unknowns}


def requirement_literals(raw):
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeError:
        return {"analysis": "UNKNOWN", "pins": [], "unknowns": [{"reason": "DECLARATION_ENCODING_UNSUPPORTED"}]}
    pins, unknowns = [], []
    for number, original in enumerate(lines, 1):
        line = original.strip()
        if not line or line.startswith("#"):
            continue
        match = PIN.fullmatch(line)
        if match:
            pins.append({"distribution": re.sub(r"[-_.]+", "-", match[1]).lower(), "declared_version": match[2], "line": number})
        else:
            # Never echo unsupported directives, URLs, auth fields, or markers.
            unknowns.append({"reason": "DECLARATION_SYNTAX_UNSUPPORTED", "line": number,
                             "line_sha256": hashlib.sha256(original.encode("utf-8")).hexdigest()})
        if len(pins) + len(unknowns) > MAX_FINDINGS:
            raise DiscoveryError("FINDING_BOUNDS")
    return {"analysis": "DECLARED" if not unknowns else "UNKNOWN", "pins": pins, "unknowns": unknowns}


def discover(objects, revision):
    tree_oid, entries = tree(objects, revision)
    registry = entries.get("registry.json")
    if not registry or registry["mode"] not in {"100644", "100755"}:
        raise DiscoveryError("REGISTRY_UNAVAILABLE")
    registry_raw = objects.read([registry["git_blob_sha1"]], "blob")[registry["git_blob_sha1"]]
    plugins, sources = _plugins(registry_raw)
    selected = {}
    for path, entry in sorted(entries.items()):
        parts = path.split("/")
        if parts[0] == "plugins":
            if len(parts) < 3 or parts[1] not in plugins:
                raise DiscoveryError("UNREGISTERED_PLUGIN_PATH")
            if entry["mode"] not in {"100644", "100755"}:
                raise DiscoveryError("UNSAFE_SELECTED_MODE")
            selected[path] = entry
    if any(not any(path.startswith("plugins/" + name + "/") for path in selected) for name in plugins):
        raise DiscoveryError("PLUGIN_BYTES_MISSING")
    captured = objects.read([entry["git_blob_sha1"] for entry in selected.values()], "blob")
    files, total, finding_total, report_bytes = [], len(registry_raw), 0, 0
    for path, entry in selected.items():
        raw = captured[entry["git_blob_sha1"]]
        total += len(raw)
        if total > MAX_BYTES:
            raise DiscoveryError("SOURCE_BYTE_BOUNDS")
        basename = path.rsplit("/", 1)[-1]
        record = {"path": path, **entry, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        if basename == "setup.py" or basename in DECLARATIONS:
            record.update(kind="UNSUPPORTED_DEPENDENCY_DECLARATION", analysis="UNKNOWN", reason="DECLARATION_FORMAT_UNSUPPORTED")
        elif basename.lower().startswith("requirements") and basename.lower().endswith(".txt"):
            record.update(kind="REQUIREMENTS_LITERAL_PINS", **requirement_literals(raw))
        elif basename.endswith(".py"):
            record.update(kind="PYTHON_LITERAL_IMPORTS", **python_literals(raw))
        else:
            record.update(kind="OPAQUE_DATA", analysis="UNKNOWN")
        finding_total += sum(len(record.get(key, [])) for key in ("imports", "pins", "unknowns"))
        if finding_total > MAX_TOTAL_FINDINGS:
            raise DiscoveryError("TOTAL_FINDING_BOUNDS")
        report_bytes += len(json.dumps(record, sort_keys=True, allow_nan=False).encode("utf-8"))
        if report_bytes > MAX_REPORT:
            raise DiscoveryError("REPORT_BOUNDS")
        files.append(record)
    report = {"schema": SCHEMA, "decision": "BLOCKED", "installable": False,
              "discovery": "MEASURED", "scope": "LOCAL_GIT_VENDORED_LITERAL_DISCOVERY_ONLY",
              "source": {"repository": REPOSITORY, "repository_authority": "CALLER_ASSERTED",
                         "commit": revision, "git_tree_sha1": tree_oid,
                         "object_hashes": "MEASURED", "upstream_parity": "UNKNOWN",
                         "registry_sha256": hashlib.sha256(registry_raw).hexdigest()},
              "coverage": {"git_tree_complete": True, "tracked_leaf_count": len(entries),
                           "selected_roots": ["plugins/" + name for name in plugins],
                           "selected_file_count": len(files), "selected_bytes": total - len(registry_raw)},
              "declarations": sources, "files": files,
              "checker": {"python": ".".join(map(str, sys.version_info[:3])), "parser": "stdlib.ast"},
              "unknown": ["INDEPENDENT_WORKFLOW_AUTHORITY", "DISTRIBUTION_RESOLUTION", "STDLIB_OR_THIRD_PARTY_CLASSIFICATION",
                          "TRANSITIVE_DEPENDENCIES", "RUNTIME_IMPORTS_AND_ALIAS_SEMANTICS", "VULNERABILITIES",
                          "DATABASE_FRESHNESS", "BEHAVIOR", "SCIENCE", "RIGHTS", "HOST_REGISTRATION"]}
    encode(report)
    return report


def encode(report):
    raw = (json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    if len(raw) > MAX_REPORT:
        raise DiscoveryError("REPORT_BOUNDS")
    return raw


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--git-dir", required=True, help="Local repository/worktree; no remote is contacted")
    parser.add_argument("--revision", required=True, help="Full immutable commit SHA, never a ref name")
    args = parser.parse_args(argv)
    try:
        report = discover(GitObjects(args.git_dir), args.revision)
        code = 0  # Completed scoped discovery, while admission is still BLOCKED.
    except (DiscoveryError, OSError, ValueError, RecursionError) as error:
        report = {"schema": SCHEMA, "decision": "BLOCKED", "installable": False,
                  "discovery": "UNAVAILABLE", "reason": str(error) if isinstance(error, DiscoveryError) else "INVALID_INPUT"}
        code = 2
    sys.stdout.buffer.write(encode(report))
    return code


if __name__ == "__main__":
    sys.exit(main())
