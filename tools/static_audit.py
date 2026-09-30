#!/usr/bin/env python3
"""Proposed static-only diagnostic auditor, independent of the science index.

No Git, network, package installation, or skill-code execution occurs here.
Inputs must be protected snapshots; ordinary path checks cannot defeat a
concurrent adversary. Source manifests are caller assertions, never signatures.
This bounded YAML profile is not a full YAML parser or an installability gate.
"""
from __future__ import annotations

import argparse
import ast
import bisect
import csv
import hashlib
import io
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from static_io import AuditBoundaryError, csv_safe, fresh_output, inventory, markdown_safe, read_single, tree_digest, write_exclusive
from static_metadata import detect_license, parse_frontmatter

VERSION = "0.1.0-phase-a.1"
NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SHA = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
CODE = {".py", ".sh", ".bash", ".js", ".mjs", ".cjs", ".ts", ".ps1", ".rb", ".pl", ".r", ".jl"}
BIN = {".exe", ".dll", ".so", ".dylib", ".bin", ".jar", ".class", ".whl", ".pyc", ".o", ".a"}
MAN = {"requirements.txt", "pyproject.toml", "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "environment.yml", "environment.yaml", "Dockerfile", "Cargo.toml", "go.mod"}
MAX_FINDINGS = 1000
MAX_AST_BYTES = 128_000
MAX_TEXT_BYTES = 2_000_000
# These lexical rules are inherited diagnostics, not a human-owned safety policy.
RULES = [
    ("remote-shell-pipe", "critical", r"(curl|wget)[^\n|]{0,300}\|\s*(sudo\s+)?(ba|z)?sh\b"),
    ("credential-access", "critical", r"(\.ssh|id_rsa|id_ed25519|AWS_SECRET|GITHUB_TOKEN|ANTHROPIC_API_KEY|OPENAI_API_KEY|HF_TOKEN|\.env\b)"),
    ("agent-persistence", "critical", r"(MEMORY\.md|SOUL\.md|CLAUDE\.md|AGENTS\.md|\.claude/settings\.json).{0,150}(write|append|modify|replace)"),
    ("instruction-override", "high", r"(ignore|override|disregard).{0,80}(previous|prior|system|developer|security|safety).{0,80}(instruction|prompt|policy|rule)"),
    ("shell-execution", "high", r"(subprocess\.(run|Popen|call)|os\.system|child_process|Invoke-Expression|\beval\s*\(|\bexec\s*\()"),
    ("network-egress", "medium", r"(requests\.(get|post|put|delete)|urllib\.request|fetch\s*\(|axios\.|curl\s+|wget\s+|Invoke-WebRequest)"),
    ("destructive-command", "critical", r"(rm\s+-rf|Remove-Item.{0,40}-Recurse|shutil\.rmtree|mkfs\.|dd\s+if=|DROP\s+(TABLE|DATABASE))"),
    ("encoded-payload", "high", r"(base64\s+(-d|--decode)|b64decode|fromCharCode|Compressed-EncodedCommand)"),
]
COMPILED = [(name, severity, re.compile(pattern, re.I | re.S)) for name, severity, pattern in RULES]
INVISIBLE = re.compile("[\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff\U000e0000-\U000e007f]")


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def source_evidence(assertion, snapshot):
    result = {"repository": "", "commit": "", "path_prefix": "", "provenance": "MISSING", "immutable": False,
              "snapshot_sha256": tree_digest(snapshot), "binding": "NOT_ESTABLISHED"}
    if not isinstance(assertion, dict):
        return result, ["source-manifest-missing"]
    repo, commit = assertion.get("repo"), assertion.get("commit")
    try:
        parsed = urlsplit(repo) if isinstance(repo, str) else None
        valid = parsed and parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment and not any(ord(c) < 32 for c in repo)
    except ValueError:
        valid = False
    if not valid:
        result["provenance"] = "INVALID"
        return result, ["source-repository-invalid-or-credential-bearing"]
    if not isinstance(commit, str) or not SHA.fullmatch(commit):
        result["provenance"] = "INVALID"
        return result, ["source-commit-not-full-sha"]
    prefix = assertion.get("path_prefix", "")
    if not isinstance(prefix, str) or "\\" in prefix or PurePosixPath(prefix).is_absolute() or ".." in PurePosixPath(prefix).parts or "\x00" in prefix:
        result["provenance"] = "INVALID"
        return result, ["source-path-prefix-invalid"]
    canonical_prefix = PurePosixPath(prefix).as_posix()
    result.update(repository=repo, commit=commit, path_prefix="" if canonical_prefix == "." else canonical_prefix, provenance="UNSIGNED_HONEST")
    expected = assertion.get("tree_sha256")
    if expected is not None:
        if not isinstance(expected, str) or not SHA256.fullmatch(expected) or expected != result["snapshot_sha256"]:
            result["provenance"] = "INVALID"
            return result, ["caller-snapshot-hash-mismatch"]
        result["binding"] = "MATCHES_CALLER_DIGEST"
    return result, []


def audit_snapshot(snapshot, skill_path, provenance, source_problems, root_name=None):
    prefix = "" if skill_path == "." else skill_path + "/"
    selected = {path[len(prefix):]: data for path, data in snapshot.items() if path.startswith(prefix)}
    problems, unsupported, coverage_errors, findings = [], [], [], []
    texts, path_coverage = {}, {}
    for path, data in selected.items():
        path_coverage[path] = {"path": path, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "status": "NOT_SCANNED"}
        if Path(path).suffix.lower() in BIN:
            findings.append({"rule": "bundled-binary", "severity": "high", "file": path, "line": 0})
        if len(data) > MAX_TEXT_BYTES:
            coverage_errors.append({"file": path, "reason": "text-byte-limit"})
            path_coverage[path]["status"] = "SKIPPED_BYTE_LIMIT"
            continue
        if b"\x00" in data:
            coverage_errors.append({"file": path, "reason": "binary-nul-content"})
            path_coverage[path]["status"] = "SKIPPED_BINARY"
            continue
        try:
            texts[path] = data.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            coverage_errors.append({"file": path, "reason": "invalid-utf8"})
            path_coverage[path]["status"] = "SKIPPED_ENCODING"
    text = texts.get("SKILL.md", "")
    metadata, _, parse_problems = parse_frontmatter(text)
    for problem in parse_problems:
        (unsupported if problem.startswith("unsupported-yaml") else problems).append(problem)
    for key, limit in (("name", 64), ("description", 1024)):
        value = metadata.get(key)
        if value is None and unsupported:
            continue
        if not isinstance(value, str) or not value.strip():
            problems.append("invalid-" + key + "-type-or-empty")
        elif len(value) > limit:
            problems.append(f"{key}-over-{limit}")
    name, description = metadata.get("name", ""), metadata.get("description", "")
    folder_name = root_name if skill_path == "." else PurePosixPath(skill_path).name
    if folder_name is None:
        unsupported.append("unsupported-root-folder-identity")
    if isinstance(name, str) and name:
        if not NAME.fullmatch(name): problems.append("invalid-name")
        if folder_name is not None and name != folder_name: problems.append("name-folder-mismatch")
    compatibility = metadata.get("compatibility")
    if compatibility is not None and (not isinstance(compatibility, str) or len(compatibility) > 500):
        problems.append("invalid-compatibility-type-or-length")
    physical_lines = len(text.splitlines())
    if physical_lines >= 500: problems.append("skill-md-not-under-500-lines")
    # Only literal Markdown relative links are checked. Dynamic references are unresolved.
    reference_checks = []
    for target in re.findall(r"\[[^\]]*\]\(([^\s)]+)\)", text):
        if target.startswith(("#", "https://", "http://", "mailto:")): continue
        target = target.split("#", 1)[0]
        reference = PurePosixPath(prefix + target)
        if reference.is_absolute() or ".." in reference.parts or "\\" in target or ":" in target:
            unsupported.append("unsupported-yaml-or-relative-reference:" + target)
        elif reference.as_posix() not in snapshot:
            problems.append("missing-referenced-file:" + target)
        reference_checks.append(target)
    modules, dynamics, parse_errors = set(), set(), []
    for path, decoded in texts.items():
        path_coverage[path]["status"] = "SCANNED_LEXICAL"
        offsets = [-1] + [i for i, char in enumerate(decoded) if char == "\n"]
        if INVISIBLE.search(decoded):
            findings.append({"rule": "invisible-unicode", "severity": "critical", "file": path, "line": 0})
        for rule, severity, pattern in COMPILED:
            for match in pattern.finditer(decoded):
                findings.append({"rule": rule, "severity": severity, "file": path, "line": bisect.bisect_left(offsets, match.start())})
                if len(findings) >= MAX_FINDINGS:
                    coverage_errors.append({"file": path, "reason": "finding-limit-reached"})
                    path_coverage[path]["status"] = "TRUNCATED_FINDINGS"
                    break
            if len(findings) >= MAX_FINDINGS: break
        if len(findings) >= MAX_FINDINGS: break
        if Path(path).suffix.lower() == ".py":
            if len(selected[path]) > MAX_AST_BYTES:
                coverage_errors.append({"file": path, "reason": "python-ast-byte-limit"})
                path_coverage[path]["status"] = "INCOMPLETE_AST"
                continue
            try:
                parsed = ast.parse(decoded)
            except (SyntaxError, RecursionError, MemoryError) as exc:
                parse_errors.append({"file": path, "reason": type(exc).__name__})
                coverage_errors.append({"file": path, "reason": "python-parse-incomplete"})
                path_coverage[path]["status"] = "INCOMPLETE_AST"
                continue
            for node in ast.walk(parsed):
                if isinstance(node, ast.Import): modules.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module: modules.add(node.module.split(".")[0])
                elif isinstance(node, ast.Call):
                    function = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
                    if function in {"__import__", "import_module"}: dynamics.add(path)
    license_info = detect_license(snapshot, skill_path, metadata.get("license"))
    counts = Counter(finding["severity"] for finding in findings)
    status = "UNSIGNED_HONEST"
    if unsupported or counts["high"] or license_info["evidence_status"] != "DETECTED" or license_info.get("disposition") == "LICENSE_REVIEW": status = "REVIEW"
    if problems: status = "FAIL"
    if source_problems or coverage_errors or counts["critical"]: status = "BLOCKED"
    source = dict(provenance, path="/".join(p for p in (provenance["path_prefix"], skill_path) if p and p != "."), tree_sha256=tree_digest(selected))
    identity = hashlib.sha256((source["repository"] + "\0" + source["commit"] + "\0" + source["path"]).encode()).hexdigest()
    entry = {
        "schema_version": "ai4s.diagnostic-entry/phase-a-v1", "id": identity,
        "name": name if isinstance(name, str) else folder_name,
        "description": description if isinstance(description, str) else "",
        "source": source, "source_problems": source_problems,
        "license": license_info,
        "spec": {"status": "NOT_RUN" if "SKILL.md" not in texts else "FAIL" if problems else "UNSUPPORTED" if unsupported else "PASS", "problems": sorted(set(problems)) if "SKILL.md" in texts else [], "unsupported": sorted(set(unsupported)), "physical_lines": physical_lines if "SKILL.md" in texts else None, "profile": "bounded-subset-v1", "checked_literal_markdown_links": reference_checks},
        "dependencies": {"manifests": sorted(path for path in selected if Path(path).name in MAN), "scripts": sorted(path for path in selected if Path(path).suffix.lower() in CODE), "binaries": sorted(path for path in selected if Path(path).suffix.lower() in BIN), "python_imports": sorted(modules), "dynamic_import_files": sorted(dynamics), "parse_errors": parse_errors},
        "security": {"status": "INCOMPLETE" if coverage_errors else "OBSERVATIONS_ONLY", "counts": dict(counts), "findings": findings, "coverage_errors": coverage_errors},
        "coverage": {"complete": all(item["status"] == "SCANNED_LEXICAL" for item in path_coverage.values()), "scope": "skill subtree lexical rules and bounded Python AST only", "paths": [path_coverage[key] for key in sorted(path_coverage)]},
        "tests": {"status": "NOT_RUN", "reason": "Skill code is never executed."},
        "evaluation": {"status": "NOT_MEASURED"}, "safety": "UNASSESSED", "network": "UNASSESSED", "installable": False,
        "status": status, "checker": {"name": "ai4s-audit-proposed", "version": VERSION},
    }
    entry["receipt"] = hashlib.sha256(canonical(entry)).hexdigest()
    entry["receipt_contract"] = "sha256(canonical JSON excluding receipt and receipt_contract); unsigned diagnostic only"
    return entry


def emit(result, out):
    artifacts = {"catalog.json": canonical(result)}
    rows = io.StringIO(newline="")
    fields = ["id", "name", "status", "repository", "commit", "path", "license", "spec", "installable"]
    writer = csv.DictWriter(rows, fieldnames=fields)
    writer.writeheader()
    for entry in result["entries"]:
        values = {"id": entry["id"], "name": entry["name"], "status": entry["status"], "repository": entry["source"]["repository"], "commit": entry["source"]["commit"], "path": entry["source"]["path"], "license": entry["license"]["effective"], "spec": entry["spec"]["status"], "installable": False}
        writer.writerow({key: csv_safe(value) for key, value in values.items()})
    artifacts["catalog.csv"] = rows.getvalue().encode("utf-8")
    rows = io.StringIO(newline="")
    fields = ["id", "rule", "severity", "file", "line"]
    writer = csv.DictWriter(rows, fieldnames=fields)
    writer.writeheader()
    for entry in result["entries"]:
        for finding in entry["security"]["findings"]:
            writer.writerow({key: csv_safe(value) for key, value in dict(id=entry["id"], **finding).items()})
    artifacts["findings.csv"] = rows.getvalue().encode("utf-8")
    lines = ["# Proposed static diagnostic audit", "", "Status: " + result["status"], "", "No installability or behavioral-security clearance is issued.", "", "| Name | Status | License evidence | Spec |", "|---|---|---|---|"]
    for entry in result["entries"]:
        lines.append("| " + " | ".join(markdown_safe(value) for value in (entry["name"], entry["status"], entry["license"]["effective"], entry["spec"]["status"])) + " |")
    lines.extend(["", "Input errors: " + str(len(result["input_errors"])), "", "The bounded YAML profile is not full YAML validation. Human safety policy and formal target schema integration remain unresolved.", ""])
    artifacts["REPORT.md"] = "\n".join(lines).encode("utf-8")
    run_record = {key: result[key] for key in ("status", "completion", "inputs", "input_errors", "generated_at", "checker_version")}
    run_record["artifact_sha256"] = {name: hashlib.sha256(data).hexdigest() for name, data in artifacts.items()}
    artifacts["run.json"] = canonical(run_record)
    for name, data in artifacts.items(): write_exclusive(out, name, data)
    write_exclusive(out, "manifest.json", canonical({"complete": True, "artifact_sha256": {name: hashlib.sha256(data).hexdigest() for name, data in artifacts.items()}}))


def run(repositories, out, expected_sources=None):
    roots = [Path(os.path.abspath(root)) for root in repositories]
    destination = fresh_output(Path(out), roots)
    entries, input_errors, inputs, seen = [], [], [], set()
    if not roots:
        input_errors.append({"reason": "no-inputs-supplied"})
    expected_sources = expected_sources or {}
    for ordinal, root in enumerate(roots):
        label = f"input-{ordinal + 1}"
        normalized = str(root)
        if normalized in seen:
            input_errors.append({"input": label, "reason": "duplicate-input"})
            continue
        seen.add(normalized)
        inputs.append({"input": label, "status": "PENDING"})
        try:
            snapshot, coverage = inventory(root)
        except AuditBoundaryError as exc:
            inputs[-1].update(status="BLOCKED")
            input_errors.append({"input": label, "reason": str(exc)})
            continue
        provenance, source_problems = source_evidence(expected_sources.get(normalized), snapshot)
        skill_paths = sorted({str(PurePosixPath(path).parent) for path in snapshot if PurePosixPath(path).name == "SKILL.md"})
        inputs[-1].update(status="COMPLETE", coverage=coverage, snapshot_sha256=tree_digest(snapshot), skills=len(skill_paths))
        if not skill_paths:
            input_errors.append({"input": label, "reason": "no-skills-found"})
        for path in skill_paths:
            entries.append(audit_snapshot(snapshot, path, provenance, source_problems, root_name=root.name))
    entries.sort(key=lambda entry: entry["id"])
    if len({entry["id"] for entry in entries}) != len(entries): input_errors.append({"reason": "duplicate-entry-identity"})
    statuses = {entry["status"] for entry in entries}
    status = "BLOCKED" if input_errors or not entries else next(value for value in ("BLOCKED", "FAIL", "REVIEW", "UNSIGNED_HONEST") if value in statuses)
    result = {"schema_version": "ai4s.diagnostic-catalog/phase-a-v1", "checker_version": VERSION,
              "generated_at": datetime.now(timezone.utc).isoformat(), "status": status,
              "completion": "PARTIAL" if input_errors else "COMPLETE", "input_errors": input_errors, "inputs": inputs,
              "entries": entries, "installable": False, "trust": "UNSIGNED_HONEST"}
    emit(result, destination)
    return result, 0 if status == "UNSIGNED_HONEST" else 2 if status == "BLOCKED" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repositories", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--sources-json", type=Path, help="Trusted caller source assertions; no Git verification")
    arguments = parser.parse_args()
    try:
        assertions = None
        if arguments.sources_json:
            content = read_single(arguments.sources_json.absolute(), max_bytes=65536)
            assertions = json.loads(content)
            if not isinstance(assertions, dict): raise ValueError("source-manifest-not-mapping")
        result, code = run(arguments.repositories, arguments.out, assertions)
        print(json.dumps({"status": result["status"], "completion": result["completion"], "skills": len(result["entries"]), "installable": False}))
        return code
    except (AuditBoundaryError, ValueError, OSError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc), "installable": False}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
