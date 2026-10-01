"""Data-only prerequisite inventory, not a security scanner or trusted gate.

No candidate module is imported, no command is launched, and no report receipt is
accepted. Presence and hashes are observations, never approval. The result stays
BLOCKED even when every requested file is present.
"""
import argparse
import hashlib
import json
import math
import os
import pathlib
import re
import stat
import sys

SCHEMA = "ai4s.security-prerequisites/v0"
MAX_BYTES = 262144
MAX_DEPTH = 32
MAX_VALUES = 50000
FACETS = ("STATIC", "PROSE", "BEHAVIOR", "SCIENCE", "TEST", "EVALUATION", "FRESHNESS")
STAGES = {
    "bootstrap": ("tools/bootstrap_tools.py", "tools/tools.lock.json"),
    "static": ("tools/ai4s_audit.py", "sources/sources.lock.json", "schema/skills-entry.schema.json"),
    "dependency": ("tools/dependency_audit.py", "tools/tools.lock.json", "sources/sources.lock.json", "policy/registries.yaml"),
    "vulnerability": ("tools/vulnerability_audit.py", "tools/tools.lock.json", "policy/vulnerability.yaml"),
    "normalization": ("tools/normalize_findings.py", "schema/skills-entry.schema.json"),
    "catalog": ("tools/build_catalog.py", "sources/sources.lock.json", "schema/catalog.schema.json"),
    "dashboard": ("tools/build_dashboard.py", "schema/catalog.schema.json"),
    "policy": ("tools/enforce_policy.py", "policy/security-rules.yaml", "policy/registries.yaml", "policy/vulnerability.yaml"),
    "reproducibility": ("tools/build_catalog.py", "tools/build_dashboard.py"),
}
PATHS = tuple(sorted({path for paths in STAGES.values() for path in paths}))
AVAILABILITY = ("MISSING", "PRESENT_UNVERIFIED", "REJECTED")
MAX_TOTAL_BYTES = len(PATHS) * MAX_BYTES
BLOCKERS = ["INDEPENDENT_WORKFLOW_UNESTABLISHED", "CHECKER_POLICY_NOT_APPROVED", "STAGE_NOT_IMPLEMENTED_OR_REVIEWED"]


class PrerequisiteError(ValueError):
    pass


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PrerequisiteError("INVALID_JSON")
        result[key] = value
    return result


def _json_syntax(raw):
    """Bounded JSON syntax checks only; no source/tool-lock schema is assumed."""
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique,
                       parse_constant=lambda _: (_ for _ in ()).throw(PrerequisiteError("INVALID_JSON")))
    pending, count = [(value, 0)], 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if depth > MAX_DEPTH or count > MAX_VALUES:
            raise PrerequisiteError("JSON_BOUNDS")
        if isinstance(item, float) and not math.isfinite(item):
            raise PrerequisiteError("INVALID_JSON")
        if isinstance(item, str):
            item.encode("utf-8")
        elif isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
            pending.extend((key, depth + 1) for key in item)
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)


def _linked(info):
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _root(path):
    try:
        root = pathlib.Path(os.path.abspath(path))
        for item in (root, *root.parents):
            info = item.lstat()
            if _linked(info) or not stat.S_ISDIR(info.st_mode):
                raise PrerequisiteError("UNSAFE_ROOT")
    except (TypeError, ValueError):
        raise PrerequisiteError("UNSAFE_ROOT") from None
    return root


def _observe(root, relative):
    observation = {"path": relative, "availability": "MISSING", "reason": "ABSENT", "sha256": None}
    current = root
    try:
        for index, part in enumerate(pathlib.PurePosixPath(relative).parts):
            current = current / part
            info = current.lstat()
            if _linked(info):
                raise PrerequisiteError("UNSAFE_PATH")
            if index < len(pathlib.PurePosixPath(relative).parts) - 1:
                if not stat.S_ISDIR(info.st_mode):
                    raise PrerequisiteError("UNSAFE_PATH")
            elif not stat.S_ISREG(info.st_mode):
                raise PrerequisiteError("NON_REGULAR")
        if info.st_size > MAX_BYTES:
            raise PrerequisiteError("OVERSIZE")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        with os.fdopen(os.open(current, flags), "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise PrerequisiteError("NON_REGULAR")
            raw = handle.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise PrerequisiteError("OVERSIZE")
        if relative.endswith(".json"):
            _json_syntax(raw)
        observation.update(availability="PRESENT_UNVERIFIED", reason="NO_APPROVED_CONTRACT", sha256=hashlib.sha256(raw).hexdigest())
    except FileNotFoundError:
        pass
    except PrerequisiteError as error:
        observation.update(availability="REJECTED", reason=str(error))
    except (UnicodeError, ValueError, RecursionError):
        observation.update(availability="REJECTED", reason="INVALID_JSON")
    except OSError:
        observation.update(availability="REJECTED", reason="UNREADABLE")
    return observation


def inventory(root, revision):
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise PrerequisiteError("INVALID_REVISION")
    root = _root(root)
    observations = [_observe(root, path) for path in PATHS]
    by_path = {item["path"]: item for item in observations}
    stages = []
    for name, required in STAGES.items():
        stages.append({"id": name, "execution": "NOT_RUN", "receipt": None,
                       "prerequisites": list(required),
                       "unavailable": [path for path in required if by_path[path]["availability"] != "PRESENT_UNVERIFIED"],
                       "blockers": list(BLOCKERS)})
    return {"schema": SCHEMA, "decision": "BLOCKED", "installable": False,
            "inspected_revision": revision, "revision_provenance": "CALLER_ASSERTED",
            "facets": {name: "UNOBSERVED" for name in FACETS},
            "trust": {"checker_revision": None, "policy_sha256": None, "workflow_independence": "UNESTABLISHED"},
            "prerequisites": observations, "stages": stages,
            "source_coverage": {"status": "NOT_RUN", "receipts": []},
            "reproducibility": {"catalog": "NOT_RUN", "dashboard": "NOT_RUN"}}


def validate_report(report):
    """Validate this narrow inventory contract, not arbitrary JSON Schema."""
    def require(condition):
        if not condition:
            raise PrerequisiteError("INVALID_REPORT")
    require(isinstance(report, dict) and set(report) == {
        "schema", "decision", "installable", "inspected_revision", "revision_provenance", "facets",
        "trust", "prerequisites", "stages", "source_coverage", "reproducibility"})
    require(report["schema"] == SCHEMA and report["decision"] == "BLOCKED" and report["installable"] is False)
    require(isinstance(report["inspected_revision"], str) and bool(re.fullmatch(r"[0-9a-f]{40}", report["inspected_revision"])))
    require(report["revision_provenance"] == "CALLER_ASSERTED")
    require(report["facets"] == {name: "UNOBSERVED" for name in FACETS})
    require(report["trust"] == {"checker_revision": None, "policy_sha256": None, "workflow_independence": "UNESTABLISHED"})
    require(report["source_coverage"] == {"status": "NOT_RUN", "receipts": []})
    require(report["reproducibility"] == {"catalog": "NOT_RUN", "dashboard": "NOT_RUN"})
    items = report["prerequisites"]
    require(isinstance(items, list) and len(items) == len(PATHS))
    for expected, item in zip(PATHS, items):
        require(isinstance(item, dict) and set(item) == {"path", "availability", "reason", "sha256"})
        require(isinstance(item["availability"], str) and isinstance(item["reason"], str))
        require(item["path"] == expected and item["availability"] in AVAILABILITY)
        if item["availability"] == "PRESENT_UNVERIFIED":
            require(item["reason"] == "NO_APPROVED_CONTRACT" and isinstance(item["sha256"], str) and bool(re.fullmatch(r"[0-9a-f]{64}", item["sha256"])))
        else:
            require(item["sha256"] is None)
            require(item["reason"] == "ABSENT" if item["availability"] == "MISSING" else item["reason"] in {"UNSAFE_PATH", "NON_REGULAR", "OVERSIZE", "JSON_BOUNDS", "INVALID_JSON", "UNREADABLE"})
    stages = report["stages"]
    require(isinstance(stages, list) and len(stages) == len(STAGES))
    by_path = {item["path"]: item for item in items}
    for (name, paths), stage in zip(STAGES.items(), stages):
        require(isinstance(stage, dict) and stage == {
            "id": name, "execution": "NOT_RUN", "receipt": None, "prerequisites": list(paths),
            "unavailable": [path for path in paths if by_path[path]["availability"] != "PRESENT_UNVERIFIED"],
            "blockers": BLOCKERS})
    return report


def encode(report):
    return (json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--revision", required=True)
    args = parser.parse_args()
    try:
        report = validate_report(inventory(args.root, args.revision))
    except (PrerequisiteError, OSError):
        report = {"schema": "ai4s.security-prerequisites/error-v0", "decision": "BLOCKED", "reason": "INVALID_INPUT"}
    sys.stdout.buffer.write(encode(report))
    return 2


if __name__ == "__main__":
    sys.exit(main())
