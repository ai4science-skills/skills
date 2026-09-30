#!/usr/bin/env python3
"""Static-only comparison of the five immutable Phase A source archives.

Archives are verified before bounded, non-extracting parsing. Their programs,
imports, tests, build hooks and dependencies are never executed. All assertions
and receipts remain UNSIGNED_HONEST; matching a caller digest is not clearance.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import math
import platform
import re
import sys
import tarfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

# Isolated direct invocation exposes only this reviewed tools directory.
TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
import static_audit as scanner
from static_audit import VERSION as SCANNER_VERSION, audit_snapshot, canonical, source_evidence
from static_io import AuditBoundaryError, fresh_output, read_single, tree_digest, write_exclusive

VERSION = "0.1.0-phase-a.1"
BASELINE = "41946b95fd34872118894b1c4cee4fa08788a52e"
SOURCE_PINS = {
    "ai4science-skills/skills": BASELINE,
    "K-Dense-AI/scientific-agent-skills": "65d6e786832e2c52832713117bbbf5096b56f77f",
    "google-deepmind/science-skills": "68832757cbbf941c620b71df5756cf6e5cc287b0",
    "orchestra-research/AI-research-SKILLs": "773a52944ba4747a18bd4ae9ade53fff041adcbc",
    "szl-holdings/szl-skills": "54890f38c4b5abeefb13441e6f3cfd6f80c34769",
}
HEX256 = re.compile(r"^[0-9a-f]{64}$")
HEX160 = re.compile(r"^[0-9a-f]{40}$")
LATER_PHASES = ["Scorecard", "Dependency-Track", "hourly-SBOM-sync", "graph-dashboard", "experiments", "workflow-hardening", "deployment", "releases"]


@dataclass(frozen=True)
class ArchiveLimits:
    max_archive_bytes: int = 256 * 1024 * 1024
    max_file_bytes: int = 32 * 1024 * 1024
    max_total_bytes: int = 512 * 1024 * 1024
    max_stream_bytes: int = 544 * 1024 * 1024
    max_members: int = 20_000
    max_depth: int = 40
    max_metadata_bytes: int = 65_536

    def __post_init__(self):
        if any(type(value) is not int or value < 1 for value in vars(self).values()):
            raise ValueError("archive limits must be positive integers")
        caps = {"max_archive_bytes": 256 * 1024 * 1024, "max_file_bytes": 32 * 1024 * 1024, "max_total_bytes": 512 * 1024 * 1024, "max_stream_bytes": 544 * 1024 * 1024, "max_members": 20_000, "max_depth": 40, "max_metadata_bytes": 65_536}
        if any(value > caps[name] for name, value in vars(self).items()):
            raise ValueError("archive limits exceed the bounded Phase A caps")


DEFAULT_LIMITS = ArchiveLimits()


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _json(data, label):
    def constant(_):
        raise AuditBoundaryError("nonfinite-json-number", label)
    def floating(value):
        result = float(value)
        if not math.isfinite(result):
            raise AuditBoundaryError("nonfinite-json-number", label)
        return result
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise AuditBoundaryError("duplicate-json-key", label)
            result[key] = value
        return result
    try:
        return json.loads(data.decode("utf-8", errors="strict"), object_pairs_hook=pairs, parse_constant=constant, parse_float=floating)
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise AuditBoundaryError("invalid-json-or-encoding", label) from exc


def _path(name, *, directory=False, limits=DEFAULT_LIMITS):
    if not isinstance(name, str) or not name or "\\" in name or ":" in name or "\x00" in name:
        raise AuditBoundaryError("unsafe-archive-path", name)
    try:
        encoded = name.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise AuditBoundaryError("archive-path-not-utf8", repr(name)) from exc
    if len(encoded) > 4096 or any(ord(c) < 32 or ord(c) == 127 for c in name):
        raise AuditBoundaryError("unsafe-archive-path", repr(name))
    clean = name[:-1] if directory and name.endswith("/") else name
    parts = clean.split("/")
    if any(p in {"", ".", ".."} for p in parts) or len(parts) > limits.max_depth:
        raise AuditBoundaryError("unsafe-archive-path-or-depth", name)
    if PurePosixPath(clean).is_absolute():
        raise AuditBoundaryError("unsafe-archive-path", name)
    return clean


def _hash_field(item, name, pattern=HEX256):
    value = item.get(name)
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise AuditBoundaryError("invalid-lock-hash", name)
    return value


def load_lock(path, expected_sha256):
    if not isinstance(expected_sha256, str) or not HEX256.fullmatch(expected_sha256):
        raise AuditBoundaryError("invalid-lock-sha256")
    raw = read_single(Path(path), 2 * 1024 * 1024)
    if _sha(raw) != expected_sha256:
        raise AuditBoundaryError("lock-sha256-mismatch", path)
    lock = _json(raw, path)
    if not isinstance(lock, dict) or lock.get("schema_version") != "ai4s.sources-lock/v5-phaseA-proposal" or lock.get("baseline_commit") != BASELINE:
        raise AuditBoundaryError("wrong-lock-schema-or-baseline", path)
    sources = lock.get("sources")
    if not isinstance(sources, list) or len(sources) != len(SOURCE_PINS):
        raise AuditBoundaryError("five-sources-required")
    seen = set()
    for source in sources:
        if not isinstance(source, dict):
            raise AuditBoundaryError("invalid-lock-source")
        repo = source.get("repository")
        if repo not in SOURCE_PINS or repo in seen or source.get("commit") != SOURCE_PINS[repo]:
            raise AuditBoundaryError("source-pin-mismatch-or-duplicate", repo)
        seen.add(repo)
        for field in ("archive_sha256", "repository_tree_sha256", "skill_tree_sha256"):
            _hash_field(source, field)
        _hash_field(source, "git_tree_sha1", HEX160)
        _hash_field(source, "expected_git_tree_sha1", HEX160)
        for field in ("archive_bytes", "regular_file_count", "regular_bytes", "skill_md_count"):
            if type(source.get(field)) is not int or source[field] < 0:
                raise AuditBoundaryError("invalid-lock-count", field)
        paths = source.get("skill_md_paths")
        if not isinstance(paths, list) or len(paths) != source["skill_md_count"]:
            raise AuditBoundaryError("invalid-skill-census", repo)
        for name in paths:
            _path(name)
            if PurePosixPath(name).name != "SKILL.md":
                raise AuditBoundaryError("nonliteral-skill-census-path", name)
        if paths != sorted(set(paths), key=lambda p: p.encode("utf-8")):
            raise AuditBoundaryError("unsorted-or-duplicate-skill-census", repo)
    return lock, raw


class _BoundedReader:
    def __init__(self, stream, limit):
        self.stream, self.limit, self.total = stream, limit, 0

    def read(self, size=-1):
        if size < 0:
            size = self.limit - self.total + 1
        if size > self.limit - self.total:
            size = self.limit - self.total + 1
        data = self.stream.read(size)
        self.total += len(data)
        if self.total > self.limit:
            raise AuditBoundaryError("expanded-tar-stream-byte-limit")
        return data


class _BoundedTarInfo(tarfile.TarInfo):
    metadata_limit = 65_536

    def _proc_pax(self, archive):
        if self.size > self.metadata_limit:
            raise AuditBoundaryError("tar-metadata-byte-limit", self.name)
        result = super()._proc_pax(archive)
        if any(k.startswith("GNU.sparse.") for k in result.pax_headers):
            raise AuditBoundaryError("sparse-archive-member", self.name)
        return result

    def _proc_gnulong(self, archive):
        if self.size > self.metadata_limit:
            raise AuditBoundaryError("tar-metadata-byte-limit", self.name)
        return super()._proc_gnulong(archive)

    def _proc_sparse(self, archive):
        raise AuditBoundaryError("sparse-archive-member", self.name)

    def _proc_gnusparse_00(self, *args):
        raise AuditBoundaryError("sparse-archive-member", self.name)

    def _proc_gnusparse_01(self, *args):
        raise AuditBoundaryError("sparse-archive-member", self.name)

    def _proc_gnusparse_10(self, *args):
        raise AuditBoundaryError("sparse-archive-member", self.name)


def manifest_bytes(snapshot, modes, paths=None):
    return b"".join(canonical({"mode": modes[name], "path": name, "sha256": _sha(snapshot[name]), "size": len(snapshot[name]), "type": "file"}) for name in sorted(snapshot if paths is None else paths, key=lambda p: p.encode("utf-8")))


def git_tree_sha1(snapshot, modes):
    tree = {}
    def obj(kind, data):
        return hashlib.sha1(kind.encode("ascii") + b" " + str(len(data)).encode("ascii") + b"\0" + data).digest()
    for name, data in snapshot.items():
        node = tree
        parts = name.split("/")
        for part in parts[:-1]:
            child = node.setdefault(part, {})
            if not isinstance(child, dict):
                raise AuditBoundaryError("archive-file-directory-collision", name)
            node = child
        if parts[-1] in node:
            raise AuditBoundaryError("archive-file-directory-collision", name)
        node[parts[-1]] = (modes[name], obj("blob", data))
    def build(node):
        rows = []
        for name, value in node.items():
            directory = isinstance(value, dict)
            mode, digest = ("40000", build(value)) if directory else value
            key = (name + ("/" if directory else "")).encode("utf-8")
            rows.append((key, mode.encode("ascii") + b" " + name.encode("utf-8") + b"\0" + digest))
        return obj("tree", b"".join(value for _, value in sorted(rows)))
    return build(tree).hex()


def load_archive(path, source, *, manifest_path=None, limits=DEFAULT_LIMITS):
    raw = read_single(Path(path), limits.max_archive_bytes)
    digest = _sha(raw)
    if digest != source["archive_sha256"] or len(raw) != source["archive_bytes"]:
        raise AuditBoundaryError("archive-sha256-or-size-mismatch", path)
    # Hash verification precedes decompression; source contents remain inert.
    snapshot, modes, names, directories = {}, {}, set(), set()
    top, total, members = None, 0, 0
    class Info(_BoundedTarInfo):
        metadata_limit = limits.max_metadata_bytes
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(raw), mode="rb") as expanded:
            bounded = _BoundedReader(expanded, limits.max_stream_bytes)
            with tarfile.open(fileobj=bounded, mode="r|", tarinfo=Info, encoding="utf-8", errors="strict") as archive:
                for member in archive:
                    members += 1
                    if members > limits.max_members:
                        raise AuditBoundaryError("archive-member-count-limit")
                    name = _path(member.name, directory=member.isdir(), limits=limits)
                    if name in names:
                        raise AuditBoundaryError("duplicate-archive-member", name)
                    names.add(name)
                    parts = name.split("/")
                    if top is None:
                        top = parts[0]
                    if parts[0] != top:
                        raise AuditBoundaryError("multiple-archive-roots", name)
                    if not member.isdir() and not member.isreg():
                        raise AuditBoundaryError("nonregular-archive-member", name)
                    if member.issparse():
                        raise AuditBoundaryError("sparse-archive-member", name)
                    if len(parts) == 1:
                        if not member.isdir():
                            raise AuditBoundaryError("archive-missing-repository-root", name)
                        continue
                    relative = "/".join(parts[1:])
                    if member.isdir():
                        directories.add(relative)
                        continue
                    if member.size < 0 or member.size > limits.max_file_bytes:
                        raise AuditBoundaryError("archive-file-byte-limit", relative)
                    if total + member.size > limits.max_total_bytes:
                        raise AuditBoundaryError("archive-total-byte-limit", relative)
                    handle = archive.extractfile(member)
                    if handle is None:
                        raise AuditBoundaryError("archive-member-unreadable", relative)
                    data = handle.read(member.size + 1)
                    if len(data) != member.size:
                        raise AuditBoundaryError("archive-member-size-mismatch", relative)
                    snapshot[relative] = data
                    modes[relative] = "100755" if member.mode & 0o111 else "100644"
                    total += len(data)
                # Read through tar's own buffer: a second hidden archive is not padding.
                while True:
                    tail = archive.fileobj.read(65_536)
                    if not tail:
                        break
                    if any(tail):
                        raise AuditBoundaryError("nonzero-trailing-tar-data", path)
    except (tarfile.TarError, OSError, EOFError, UnicodeError, ValueError, RecursionError) as exc:
        raise AuditBoundaryError("invalid-or-unreadable-archive", path) from exc
    if not snapshot:
        raise AuditBoundaryError("empty-archive", path)
    if directories.intersection(snapshot):
        raise AuditBoundaryError("archive-file-directory-collision", path)
    casefolded = {}
    for name in snapshot:
        key = name.casefold()
        if key in casefolded:
            raise AuditBoundaryError("archive-case-collision", name)
        casefolded[key] = name
    manifest = manifest_bytes(snapshot, modes)
    actual_git_tree = git_tree_sha1(snapshot, modes)
    skills = sorted((name for name in snapshot if PurePosixPath(name).name == "SKILL.md"), key=lambda p: p.encode("utf-8"))
    roots = [str(PurePosixPath(name).parent) for name in skills]
    scoped = [name for name in snapshot if any(root == "." or name.startswith(root + "/") for root in roots)]
    measured = {"regular_file_count": len(snapshot), "regular_bytes": total, "skill_md_count": len(skills), "skill_md_paths": skills, "repository_tree_sha256": _sha(manifest), "skill_tree_sha256": _sha(manifest_bytes(snapshot, modes, scoped)), "git_tree_sha1": actual_git_tree}
    for field, value in measured.items():
        if source[field] != value:
            raise AuditBoundaryError("archive-lock-" + field + "-mismatch", path)
    if actual_git_tree != source["expected_git_tree_sha1"]:
        raise AuditBoundaryError("archive-expected-git-tree-mismatch", path)
    if manifest_path is not None:
        observed_manifest = read_single(Path(manifest_path), 8 * 1024 * 1024)
        if observed_manifest != manifest:
            raise AuditBoundaryError("retained-repository-manifest-mismatch", manifest_path)
    return snapshot, {**measured, "complete": True, "status": "VERIFIED_CALLER_LOCK", "archive_sha256": digest, "archive_bytes": len(raw), "tar_root": top, "members": members, "expanded_stream_bytes": bounded.total, "snapshot_sha256": tree_digest(snapshot), "manifest_sha256": _sha(manifest), "commit_binding": "MATCHES_RETAINED_CALLER_TREE_NO_SIGNATURE", "retained_manifest_verified": manifest_path is not None, "configured_limits": vars(limits).copy(), "inspection": "sequential bounded tar stream; no extraction or candidate execution"}


def _producer():
    paths = ["static_compare.py", "static_audit.py", "static_io.py", "static_metadata.py"]
    if Path(__file__).with_name("token_count.py").is_file():
        paths.append("token_count.py")
    rules = {"lexical_rules": scanner.RULES, "regex_flags": int(re.I | re.S), "invisible_unicode_pattern": scanner.INVISIBLE.pattern, "code_suffixes": sorted(scanner.CODE), "binary_suffixes": sorted(scanner.BIN), "dependency_manifest_names": sorted(scanner.MAN), "max_findings": scanner.MAX_FINDINGS, "max_ast_bytes": scanner.MAX_AST_BYTES, "max_text_bytes": scanner.MAX_TEXT_BYTES}
    return {"adapter_version": VERSION, "scanner_version": SCANNER_VERSION, "module_sha256": {name: _sha(read_single(Path(__file__).with_name(name), 2 * 1024 * 1024)) for name in paths}, "ruleset_sha256": _sha(canonical(rules)), "ruleset": rules, "ruleset_contract": "SHA256 of canonical UTF-8 JSON including trailing newline; inherited diagnostics, no safety-policy approval", "runtime": {"python": platform.python_version(), "implementation": platform.python_implementation(), "system": platform.system(), "machine": platform.machine(), "isolated": sys.flags.isolated, "no_site": sys.flags.no_site}}


def _bound_receipt(value):
    value["receipt_contract"] = "sha256(canonical UTF-8 JSON excluding receipt_sha256); unsigned evidence only"
    value["receipt_sha256"] = _sha(canonical(value))
    return value


def _tokens(snapshot, source, tokenizer, coverage):
    assertion = {"repo": "https://github.com/" + source["repository"], "pin": source["commit"], "archive_sha256": source["archive_sha256"], "path_prefix": ""}
    try:
        from token_count import count_source
    except ModuleNotFoundError as exc:
        if exc.name != "token_count":
            raise
        return _bound_receipt({"status": "NOT_RUN", "reason": "verified tokenizer module unavailable", "source": assertion, "input_sha256": tree_digest(snapshot), "counts": None})
    return count_source(snapshot, assertion, tokenizer, coverage=coverage)


def _counts(entries):
    return {"observed_entries": len(entries), "spec_statuses": dict(Counter(e["spec"]["status"] for e in entries)), "static_findings": dict(Counter(f["severity"] for e in entries for f in e["security"]["findings"])), "static_coverage_errors": sum(len(e["security"]["coverage_errors"]) for e in entries), "license_evidence_statuses": dict(Counter(e["license"]["evidence_status"] for e in entries))}


def _entry_coverage(entry, snapshot, skill_path):
    prefix = "" if skill_path == "." else skill_path + "/"
    selected = {name[len(prefix):]: data for name, data in snapshot.items() if name.startswith(prefix)}
    observed = entry.get("coverage")
    rows = observed.get("paths", []) if isinstance(observed, dict) else []
    valid = isinstance(rows, list) and len(rows) == len(selected)
    seen = set()
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                valid = False
                continue
            name = row.get("path")
            if not isinstance(name, str) or name not in selected or name in seen:
                valid = False
                continue
            seen.add(name)
            valid = valid and row.get("bytes") == len(selected[name]) and row.get("sha256") == _sha(selected[name])
    valid = valid and seen == set(selected)
    complete = valid and isinstance(observed, dict) and observed.get("complete") is True and all(row.get("status") == "SCANNED_LEXICAL" for row in rows)
    return {"complete": complete, "path_hashes_match": valid, "expected_file_count": len(selected), "observed_file_count": len(rows) if isinstance(rows, list) else None, "input_sha256": tree_digest(selected)}


def run(lock_path, lock_sha256, archives, out, *, manifests_dir=None, tokenizer=None, limits=DEFAULT_LIMITS):
    lock, raw_lock = load_lock(lock_path, lock_sha256)
    if not isinstance(archives, dict) or any(repo not in SOURCE_PINS for repo in archives):
        raise AuditBoundaryError("invalid-archive-mapping")
    if any(not isinstance(path, (str, Path)) for path in archives.values()):
        raise AuditBoundaryError("invalid-archive-mapping-path")
    archive_paths = [Path(path) for path in archives.values()]
    roots = [Path(lock_path), *archive_paths]
    if manifests_dir is not None:
        roots.append(Path(manifests_dir))
    destination = fresh_output(Path(out), roots)
    producer = _producer()
    entries, receipts, errors, artifacts = [], [], [], {}
    for source in lock["sources"]:
        repo = source["repository"]
        receipt = {"schema_version": "ai4s.five-source-receipt/phase-a-v1", "source": {"repository": repo, "commit": source["commit"]}, "started_at": datetime.now(timezone.utc).isoformat(), "lock_sha256": _sha(raw_lock), "producer": producer, "configured_limits": vars(limits).copy(), "expected_skill_paths": source["skill_md_paths"], "trust": "UNSIGNED_HONEST", "installable": False, "human_approvals": lock.get("human_approvals", {}), "static": {"status": "NOT_RUN", "counts": None}, "license": {"status": "NOT_RUN", "approval": "NOT_GRANTED"}, "safety": {"status": "UNASSESSED"}, "tokens": {"status": "NOT_RUN", "counts": None}, "evaluation": {"status": "NOT_RUN"}}
        source_entries = []
        try:
            if repo not in archives:
                raise AuditBoundaryError("source-archive-missing", repo)
            manifest_path = None if manifests_dir is None else Path(manifests_dir) / (repo.replace("/", "__") + ".repository-tree.manifest.jsonl")
            snapshot, coverage = load_archive(archives[repo], source, manifest_path=manifest_path, limits=limits)
            receipt["acquisition"] = coverage
            provenance, problems = source_evidence({"repo": "https://github.com/" + repo, "commit": source["commit"], "path_prefix": "", "tree_sha256": tree_digest(snapshot)}, snapshot)
            for name in source["skill_md_paths"]:
                skill_path = str(PurePosixPath(name).parent)
                entry = audit_snapshot(snapshot, skill_path, provenance, problems, root_name=repo.split("/")[-1])
                source_entries.append(entry)
            receipt["tokens"] = _tokens(snapshot, source, tokenizer, coverage)
            coverage_checks = [_entry_coverage(entry, snapshot, str(PurePosixPath(name).parent)) for entry, name in zip(source_entries, source["skill_md_paths"])]
            receipt["static"] = {"status": "INCOMPLETE" if any(e["security"]["coverage_errors"] for e in source_entries) or not all(check["complete"] for check in coverage_checks) else "OBSERVATIONS_ONLY", "counts": _counts(source_entries), "entry_receipts": [{"path": e["source"]["path"], "receipt": e["receipt"], "coverage": e.get("coverage", {"status": "INCOMPLETE", "reason": "scanner path coverage unavailable"}), "coverage_binding": check} for e, check in zip(source_entries, coverage_checks)]}
            receipt["license"] = {"status": "OBSERVATIONS_ONLY", "approval": "NOT_GRANTED", "human_hold": "LICENSE_REVIEW", "per_path": [{"path": e["source"]["path"], "evidence": e["license"]} for e in source_entries]}
            receipt["status"] = "COMPLETE" if receipt["static"]["status"] != "INCOMPLETE" else "INCOMPLETE"
            receipt["observed_skill_paths"] = [e["source"]["path"] + "/SKILL.md" if e["source"]["path"] else "SKILL.md" for e in source_entries]
            if receipt["observed_skill_paths"] != source["skill_md_paths"]:
                raise AuditBoundaryError("auditor-path-coverage-mismatch", repo)
        except (AuditBoundaryError, OSError, UnicodeError, ValueError, RecursionError) as exc:
            source_entries = []
            receipt.update(status="BLOCKED", error={"reason": exc.reason if isinstance(exc, AuditBoundaryError) else type(exc).__name__, "path": exc.path if isinstance(exc, AuditBoundaryError) else repo})
            receipt["static"] = {"status": "NOT_RUN", "counts": None}
            receipt["license"] = {"status": "NOT_RUN", "approval": "NOT_GRANTED", "reason": "source audit aborted; entry evidence was not emitted"}
            receipt["tokens"] = {"status": "NOT_RUN", "counts": None, "reason": "source audit aborted; token evidence was not emitted"}
            receipt.pop("observed_skill_paths", None)
            errors.append({"repository": repo, **receipt["error"]})
        entries.extend(source_entries)
        receipt["finished_at"] = datetime.now(timezone.utc).isoformat()
        _bound_receipt(receipt)
        name = repo.replace("/", "__") + ".receipt.json"
        artifacts[name] = canonical(receipt)
        receipts.append({"repository": repo, "commit": source["commit"], "artifact": name, "sha256": _sha(artifacts[name]), "receipt_sha256": receipt["receipt_sha256"], "status": receipt["status"]})
    entries.sort(key=lambda e: e["id"])
    if len({e["id"] for e in entries}) != len(entries):
        errors.append({"reason": "duplicate-entry-identity"})
    expected = sum(source["skill_md_count"] for source in lock["sources"])
    complete = not errors and len(entries) == expected and all(r["status"] == "COMPLETE" for r in receipts)
    catalog = {"schema_version": "ai4s.five-source-catalog/phase-a-v1", "version": VERSION, "generated_at": datetime.now(timezone.utc).isoformat(), "baseline_commit": BASELINE, "lock_sha256": _sha(raw_lock), "producer": producer, "status": "OBSERVATIONS_ONLY" if complete else "INCOMPLETE", "completion": "COMPLETE" if complete else "PARTIAL", "expected_source_count": len(SOURCE_PINS), "expected_skill_count": expected, "counts": _counts(entries) if entries else None, "entries": entries, "source_receipts": receipts, "input_errors": errors, "trust": "UNSIGNED_HONEST", "installable": False, "human_approvals": lock.get("human_approvals", {}), "baseline_claims": lock.get("baseline_claims", []), "later_phases": {name: "NOT_RUN" for name in LATER_PHASES}, "safety": {"status": "UNASSESSED"}, "evaluation": {"status": "NOT_RUN"}}
    _bound_receipt(catalog)
    artifacts["catalog.json"] = canonical(catalog)
    for name, data in artifacts.items():
        write_exclusive(destination, name, data)
    write_exclusive(destination, "manifest.json", canonical({"complete": complete, "trust": "UNSIGNED_HONEST", "artifact_sha256": {name: _sha(data) for name, data in artifacts.items()}}))
    return catalog, 0 if complete else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--lock-sha256", required=True)
    parser.add_argument("--archives-json", type=Path, required=True, help="repository -> retained local .tar.gz path")
    parser.add_argument("--manifests-dir", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--tokenizer-artifacts", type=Path)
    parser.add_argument("--tokenizer-runtime-parent", type=Path)
    args = parser.parse_args()
    try:
        mapping = _json(read_single(args.archives_json, 65_536), args.archives_json)
        if args.tokenizer_artifacts is not None:
            if args.tokenizer_runtime_parent is None:
                raise AuditBoundaryError("tokenizer-runtime-parent-required")
            from token_count import TokenizerUnavailable, load_tokenizer
            try:
                with load_tokenizer(args.tokenizer_artifacts, args.tokenizer_runtime_parent) as tokenizer:
                    _, code = run(args.lock, args.lock_sha256, mapping, args.out, manifests_dir=args.manifests_dir, tokenizer=tokenizer)
            except TokenizerUnavailable:
                _, code = run(args.lock, args.lock_sha256, mapping, args.out, manifests_dir=args.manifests_dir)
        else:
            _, code = run(args.lock, args.lock_sha256, mapping, args.out, manifests_dir=args.manifests_dir)
        return code
    except (AuditBoundaryError, OSError, ValueError) as exc:
        print(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
