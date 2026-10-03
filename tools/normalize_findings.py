#!/usr/bin/env python3
"""Normalize one bounded static-scanner receipt without granting admission.

Both the target inventory and scanner receipt are caller-supplied assertions.
This parser verifies their internal agreement; it does not authenticate the
producer, read candidate source, execute a scanner, or approve a skill.
"""

import argparse
import json
import pathlib
import sys

# Isolated CLI mode removes the script directory; load only the adjacent
# repository helper, never a candidate skill path or user PYTHONPATH.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from trust_common import (ValidationError, canonical_sha256, digest,
                          load_json_file, object_fields, portable_path,
                          repository, text)

TARGET_SCHEMA = "ai4s.static-scan-target/v0"
RECEIPT_SCHEMA = "ai4s.static-scan-receipt/v0"
REPORT_SCHEMA = "ai4s.findings-normalization/v0"
MAX_FILES = 10000
MAX_FINDINGS = 10000
STATUSES = {"COMPLETE", "ERROR", "TIMEOUT", "UNSUPPORTED"}
ERRORS = {"SCANNER_ERROR", "TIMEOUT", "UNSUPPORTED", "READ_ERROR"}
SEVERITIES = {"INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"}


def _list(value, limit, label):
    if not isinstance(value, list) or len(value) > limit:
        raise ValidationError(label + ": expected bounded array")
    return value


def _source(value):
    object_fields(value, ("repository", "commit", "path"), (), "source")
    repository(value["repository"])
    digest(value["commit"], "source.commit", 40)
    portable_path(value["path"], "source.path")
    return value


def _files(value, source, label):
    result = {}
    seen_names = set()
    seen_components = {}
    prefix = source["path"] + "/"
    for item in _list(value, MAX_FILES, label):
        object_fields(item, ("path", "sha256"), (), label + "[]")
        path = portable_path(item["path"], label + ".path")
        if not path.startswith(prefix):
            raise ValidationError(label + ": file outside declared source path")
        folded = path.casefold()
        if folded in seen_names:
            raise ValidationError(label + ": duplicate or case-colliding path")
        parts = path.split("/")
        for end in range(1, len(parts) + 1):
            ancestor = "/".join(parts[:end])
            key = ancestor.casefold()
            if key in seen_components and seen_components[key] != ancestor:
                raise ValidationError(label + ": case-colliding ancestor")
            seen_components[key] = ancestor
        seen_names.add(folded)
        result[path] = digest(item["sha256"], label + ".sha256")
    return result


def _findings(value, files):
    findings = []
    identities = set()
    for item in _list(value, MAX_FINDINGS, "findings"):
        object_fields(item, ("rule", "severity", "path", "line", "message"), (), "finding")
        rule = text(item["rule"], "finding.rule")
        if len(rule) > 128 or not isinstance(item["severity"], str) or item["severity"] not in SEVERITIES:
            raise ValidationError("finding: unknown rule or severity")
        path = portable_path(item["path"], "finding.path")
        if path not in files or type(item["line"]) is not int or not 1 <= item["line"] <= 10000000:
            raise ValidationError("finding: uncovered path or invalid line")
        message = text(item["message"], "finding.message")
        if len(message) > 1024:
            raise ValidationError("finding: message too long")
        identity = (rule, path, item["line"], message)
        if identity in identities:
            raise ValidationError("finding: duplicate")
        identities.add(identity)
        findings.append(dict(item))
    return sorted(findings, key=lambda f: (f["path"], f["line"], f["rule"], f["message"]))


def normalize(target, receipt):
    """Return a deterministic, always-blocked review artifact or reject input."""
    object_fields(target, ("schema", "source", "files"), (), "target")
    if target["schema"] != TARGET_SCHEMA:
        raise ValidationError("target: unsupported schema")
    source = _source(target["source"])
    expected = _files(target["files"], source, "target.files")
    if not expected:
        raise ValidationError("target: empty source scope")

    object_fields(receipt, ("schema", "source", "producer", "status", "files", "findings", "errors"), (), "receipt")
    if receipt["schema"] != RECEIPT_SCHEMA or receipt["source"] != source:
        raise ValidationError("receipt: unsupported schema or source mismatch")
    producer = object_fields(receipt["producer"], ("name", "sha256"), (), "producer")
    text(producer["name"], "producer.name")
    if len(producer["name"]) > 128:
        raise ValidationError("producer: name too long")
    digest(producer["sha256"], "producer.sha256")
    status = receipt["status"]
    if not isinstance(status, str) or status not in STATUSES:
        raise ValidationError("receipt: unknown status")
    scanned = _files(receipt["files"], source, "receipt.files")
    if any(path not in expected or sha != expected[path] for path, sha in scanned.items()):
        raise ValidationError("receipt: undeclared file or hash mismatch")
    findings = _findings(receipt["findings"], scanned)
    errors = _list(receipt["errors"], 16, "errors")
    if any(not isinstance(error, str) or error not in ERRORS for error in errors) or len(set(errors)) != len(errors):
        raise ValidationError("receipt: duplicate or unknown error")
    if status == "COMPLETE":
        if scanned != expected or errors:
            raise ValidationError("receipt: complete claim without exact coverage and zero errors")
    elif not errors:
        raise ValidationError("receipt: incomplete scan requires explicit error")
    elif (status == "TIMEOUT" and errors != ["TIMEOUT"]
          or status == "UNSUPPORTED" and errors != ["UNSUPPORTED"]
          or status == "ERROR" and not set(errors) <= {"SCANNER_ERROR", "READ_ERROR"}):
        raise ValidationError("receipt: status and error disagree")

    return {
        "schema": REPORT_SCHEMA,
        "decision": "BLOCKED",
        "installable": False,
        "reason": "UNAUTHENTICATED_PRODUCER_AND_POLICY" if status == "COMPLETE" else "SCAN_INCOMPLETE",
        "source": dict(source),
        "producer": dict(producer),
        "producer_provenance": "CALLER_ASSERTED",
        "target_sha256": canonical_sha256(target),
        "receipt_sha256": canonical_sha256(receipt),
        "scan_status": status,
        "coverage_claim": "COMPLETE" if scanned == expected and status == "COMPLETE" else "PARTIAL_OR_UNVERIFIED",
        "declared_file_count": len(expected),
        "reported_file_count": len(scanned),
        "unreported_paths": sorted(set(expected) - set(scanned)),
        "findings": findings,
        "errors": sorted(errors),
        "unobserved_facets": ["PROSE", "BEHAVIOR", "SCIENCE", "TEST", "EVALUATION", "FRESHNESS"],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    parser.add_argument("--receipt", required=True)
    args = parser.parse_args(argv)
    try:
        result = normalize(load_json_file(args.target), load_json_file(args.receipt))
    except (ValidationError, OSError, ValueError, TypeError):
        result = {"schema": REPORT_SCHEMA, "decision": "BLOCKED", "installable": False,
                  "reason": "INVALID_OR_UNAVAILABLE_INPUT"}
    sys.stdout.write(json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
