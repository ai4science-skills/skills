#!/usr/bin/env python3
"""Base-owned, data-only PR static-integrity check; never skill admission.

Run only from a protected base checkout. Candidate archives are parsed as inert
bytes; no candidate Python, workflow, build script, or skill is executed.
"""

import argparse
import base64
import gzip
import hashlib
import io
import json
import os
import pathlib
import re
import stat
import sys
import tarfile
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import check
import sync
from trust_common import read_json_bytes, strict_json

SCHEMA = "ai4s.static-integrity/v0"
POLICY_SCHEMA = "ai4s.static-integrity-policy/v0"
REPOSITORY = "ai4science-skills/skills"
PROTECTED_BASE_REF = "main"
SHA = re.compile(r"[0-9a-f]{40}\Z")
MAX_EVENT_BYTES = 2 * 1024 * 1024
MAX_POLICY_BYTES = 64 * 1024
MAX_REPORT_BYTES = 64 * 1024
PROTECTED = frozenset({
    ".github/workflows/base-static-integrity.yml",
    ".github/workflows/check.yml",
    ".github/workflows/security-prerequisites.yml",
    "policy/static-integrity.json",
    "tools/check.py",
    "tools/static_integrity.py",
    "tools/static_integrity_status.py",
    "tools/sync.py",
    "tools/test_static_integrity.py",
    "tools/trust_common.py",
})


class Hold(ValueError):
    """Failure category safe to place in a public status receipt."""


def _get(value, *keys):
    try:
        for key in keys:
            value = value[key]
        return value
    except (KeyError, TypeError, IndexError):
        raise Hold("INVALID_EVENT") from None


def identity(event, runner_base_sha):
    if not isinstance(event, dict) or _get(event, "action") not in {
        "opened", "synchronize", "reopened", "ready_for_review", "edited"
    }:
        raise Hold("INVALID_EVENT")
    number = _get(event, "number")
    repo = _get(event, "repository", "full_name")
    base_repo = _get(event, "pull_request", "base", "repo", "full_name")
    base_ref = _get(event, "pull_request", "base", "ref")
    head_repo = _get(event, "pull_request", "head", "repo", "full_name")
    base_sha = _get(event, "pull_request", "base", "sha")
    head_sha = _get(event, "pull_request", "head", "sha")
    if (type(number) is not int or not 1 <= number <= 2**31 - 1
            or repo != REPOSITORY or base_repo != REPOSITORY
            or base_ref != PROTECTED_BASE_REF
            or not isinstance(head_repo, str) or not sync.REPO.fullmatch(head_repo)
            or not isinstance(base_sha, str) or not SHA.fullmatch(base_sha)
            or not isinstance(head_sha, str) or not SHA.fullmatch(head_sha)
            or runner_base_sha != base_sha):
        raise Hold("INVALID_EVENT")
    return {"repository": repo, "number": number, "base_sha": base_sha,
            "base_ref": base_ref,
            "head_repo": head_repo, "head_sha": head_sha}


def policy(root):
    path = root / "policy/static-integrity.json"
    try:
        raw = read_json_bytes(path, MAX_POLICY_BYTES)
        document = strict_json(raw)
    except (OSError, ValueError):
        raise Hold("POLICY_UNAVAILABLE") from None
    expected = {
        "schema": POLICY_SCHEMA, "repository": REPOSITORY,
        "scope": "SOURCE_AND_STATIC_METADATA_ONLY",
        "max_download_bytes": sync.MAX_DOWNLOAD,
        "max_expanded_bytes": sync.MAX_EXPANDED,
        "max_members": sync.MAX_MEMBERS,
        "max_total_source_download_bytes": 256 * 1024 * 1024,
        "protected_paths": sorted(PROTECTED),
    }
    if document != expected:
        raise Hold("POLICY_UNAVAILABLE")
    return document, hashlib.sha256(raw).hexdigest()


def _same_spelling(paths):
    seen = {}
    for path in paths:
        for end in range(1, len(path.split("/")) + 1):
            prefix = "/".join(path.split("/")[:end])
            key = prefix.casefold()
            if key in seen and seen[key] != prefix:
                raise Hold("ARCHIVE_UNSAFE")
            seen[key] = prefix


def snapshot(raw, limits):
    """Return regular archive files only; never extract tar metadata or links."""
    if not isinstance(raw, bytes) or len(raw) > limits["max_download_bytes"]:
        raise Hold("ARCHIVE_UNSAFE")
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as compressed:
            expanded = compressed.read(limits["max_expanded_bytes"] + 1)
        if len(expanded) > limits["max_expanded_bytes"]:
            raise Hold("ARCHIVE_UNSAFE")
        files, names, root, total = {}, set(), None, 0
        with tarfile.open(fileobj=io.BytesIO(expanded), mode="r:") as archive:
            for count, member in enumerate(archive, 1):
                if count > limits["max_members"]:
                    raise Hold("ARCHIVE_UNSAFE")
                name = member.name.rstrip("/") if member.isdir() else member.name
                sync.safe_path(name)
                parts = name.split("/", 1)
                if root is None:
                    root = parts[0]
                if parts[0] != root or ".git" in name.split("/") or name.casefold() in names:
                    raise Hold("ARCHIVE_UNSAFE")
                names.add(name.casefold())
                if member.isdir():
                    continue
                if not member.isfile() or len(parts) != 2 or member.size < 0:
                    raise Hold("ARCHIVE_UNSAFE")
                total += member.size
                if total > limits["max_expanded_bytes"]:
                    raise Hold("ARCHIVE_UNSAFE")
                relative = parts[1]
                if relative.startswith(".git/") or relative == ".git":
                    raise Hold("ARCHIVE_UNSAFE")
                handle = archive.extractfile(member)
                data = handle.read(member.size + 1) if handle else b""
                if len(data) != member.size or relative in files:
                    raise Hold("ARCHIVE_UNSAFE")
                files[relative] = data
        if not root or not files:
            raise Hold("ARCHIVE_UNSAFE")
        _same_spelling(list(files))
        return files
    except (OSError, EOFError, tarfile.TarError, sync.SyncError, ValueError):
        raise Hold("ARCHIVE_UNSAFE") from None


def _regular_bytes(root, relative):
    path = root / relative
    try:
        for item in (path, *path.parents):
            if item == root.parent:
                break
            info = item.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise Hold("TRUSTED_SOURCE_UNAVAILABLE")
        if not stat.S_ISREG(path.lstat().st_mode) or path.stat().st_size > 2 * 1024 * 1024:
            raise Hold("TRUSTED_SOURCE_UNAVAILABLE")
        return path.read_bytes()
    except OSError:
        raise Hold("TRUSTED_SOURCE_UNAVAILABLE") from None


def _catalog(registry):
    rows = ["| %s | %s | %s | %s | [%s@%s](https://github.com/%s/tree/%s) | %s |" %
            (e["name"], ", ".join(sorted(e["skills"])), e["maintainer"], e["license"],
             e["repo"], e["sha"][:12], e["repo"], e["sha"],
             "; ".join(e["hosted_services"]) or "none") for e in registry["plugins"]]
    return ("# Catalog\n\nGenerated by tools/sync.py from registry.json. Do not edit by hand.\n\n"
            "| Plugin | Skills | Maintainer | License | Pinned source | External services |\n"
            "|---|---|---|---|---|---|---|\n" + "\n".join(rows) + "\n").encode("utf-8")


def _materialize(root, files):
    for relative, data in files.items():
        if relative in {"registry.json", ".claude-plugin/marketplace.json"} or relative.startswith("plugins/"):
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)


def evaluate(event, runner_base_sha, trusted_root, get=sync.bounded_get,
             verify_ref=sync.verify_ref, fetch=sync.fetch, verify_base=None):
    """Verify candidate bytes; callbacks permit offline negative fixtures."""
    bound = identity(event, runner_base_sha)
    rules, policy_sha = policy(trusted_root)
    if verify_base is None:
        def verify_base(sha):
            raw = get("https://api.github.com/repos/%s/commits/%s" % (REPOSITORY, sha), 128 * 1024)
            record = sync.read_json(raw)
            return record.get("sha") == sha and record.get("commit", {}).get("verification", {}).get("verified") is True
    if not verify_base(bound["base_sha"]):
        raise Hold("BASE_SIGNATURE_UNVERIFIED")
    url = "https://codeload.github.com/%s/tar.gz/%s" % (bound["head_repo"], bound["head_sha"])
    candidate_raw = get(url, rules["max_download_bytes"])
    files = snapshot(candidate_raw, rules)
    for relative in PROTECTED:
        if files.get(relative) != _regular_bytes(trusted_root, relative):
            raise Hold("PROTECTED_CHECKER_CHANGE")
    trusted_workflows = {
        path.relative_to(trusted_root).as_posix():
        _regular_bytes(trusted_root, path.relative_to(trusted_root).as_posix())
        for path in (trusted_root / ".github/workflows").rglob("*") if path.is_file() or path.is_symlink()
    }
    if {path: data for path, data in files.items() if path.startswith(".github/workflows/")} != trusted_workflows:
        raise Hold("PROTECTED_CHECKER_CHANGE")
    try:
        registry = sync.read_json(files["registry.json"])
        sync.validate_registry(registry)
        if files.get("CATALOG.md") != _catalog(registry):
            raise Hold("CATALOG_MISMATCH")
        upstream = []
        total_source_bytes = 0
        for entry in registry["plugins"]:
            verify_ref(entry)
            raw = fetch(entry["repo"], entry["sha"])
            total_source_bytes += len(raw)
            if total_source_bytes > rules["max_total_source_download_bytes"]:
                raise Hold("SOURCE_BUDGET_EXCEEDED")
            expected = {"plugins/" + entry["name"] + "/" + path: data
                        for path, data in sync.prepare(entry, raw).items()}
            prefix = "plugins/" + entry["name"] + "/"
            actual = {path: data for path, data in files.items() if path.startswith(prefix)}
            if actual != expected:
                raise Hold("SOURCE_BYTES_MISMATCH")
            upstream.append({"name": entry["name"], "repository": entry["repo"],
                             "commit": entry["sha"], "archive_sha256": hashlib.sha256(raw).hexdigest()})
    except (KeyError, OSError, ValueError, sync.SyncError) as exc:
        if isinstance(exc, Hold):
            raise
        raise Hold("SOURCE_PIN_UNVERIFIED") from None
    with tempfile.TemporaryDirectory(prefix="ai4s-pr-static-") as temporary:
        _materialize(pathlib.Path(temporary), files)
        failures, _, count = check.audit(pathlib.Path(temporary))
    if failures:
        raise Hold("STATIC_METADATA_FAILURE")
    return {"schema": SCHEMA, "decision": "STATIC_MATCH", "installable": False,
            "provider_policy": "UNVERIFIED",
            "scope": "SOURCE_AND_STATIC_METADATA_ONLY", **bound,
            "trusted_base_sha": runner_base_sha, "policy_sha256": policy_sha,
            "checker_sha256": hashlib.sha256(_regular_bytes(trusted_root, "tools/static_integrity.py")).hexdigest(),
            "candidate_archive_sha256": hashlib.sha256(candidate_raw).hexdigest(),
            "plugin_count": len(upstream), "skill_count": count, "upstream": upstream,
            "unobserved": ["DEPENDENCIES", "VULNERABILITIES", "BEHAVIOR", "SCIENCE", "RIGHTS_REVIEW", "FRESHNESS"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--report")
    args = parser.parse_args(argv)
    root = pathlib.Path(__file__).resolve().parent.parent
    try:
        event = strict_json(read_json_bytes(args.event, MAX_EVENT_BYTES))
        report = evaluate(event, args.base_sha, root)
    except (Hold, OSError, ValueError, TypeError, KeyError) as error:
        report = {"schema": SCHEMA, "decision": "HOLD", "installable": False,
                  "reason": str(error) if isinstance(error, Hold) else "UNEXPECTED_ERROR"}
    raw = (json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    if len(raw) > MAX_REPORT_BYTES:
        report = {"schema": SCHEMA, "decision": "HOLD", "installable": False,
                  "reason": "RECEIPT_TOO_LARGE"}
        raw = (json.dumps(report, sort_keys=True) + "\n").encode("utf-8")
    if args.report:
        path = pathlib.Path(args.report)
        with path.open("xb") as handle:
            handle.write(raw)
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="ascii") as handle:
            handle.write("report_b64=" + base64.b64encode(raw).decode("ascii") + "\n")
    print("static integrity: " + report["decision"] + "; full security admission remains BLOCKED")
    return 0 if report["decision"] == "STATIC_MATCH" else 2


if __name__ == "__main__":
    sys.exit(main())
