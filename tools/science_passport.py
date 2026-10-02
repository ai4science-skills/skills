#!/usr/bin/env python3
"""Emit a bounded, static preview for one pinned community-index skill.

This reads vendored bytes and registry metadata only. It never executes a skill,
contacts a service, or treats an import or scientific result as verified.
"""

import argparse
import hashlib
import json
import os
import pathlib
import re
import stat
import sys

import check
import sync


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCHEMA = "ai4s.science-skill-passport/v0"
FIXTURE_SUFFIXES = {".json", ".csv", ".tsv", ".txt"}
MAX_METADATA_BYTES = 256 * 1024
MAX_TREE_ENTRIES = 10000
MAX_TREE_BYTES = 50 * sync.MAX_PLUGIN
MAX_SKILL_MEMBERS = 2048
MAX_FIXTURES = 128
MAX_OUTPUT_BYTES = 64 * 1024


class PassportError(ValueError):
    """A preview cannot be established from the checked index."""


def _read_bounded(path, limit=sync.MAX_PLUGIN):
    observed = path.lstat()
    if not stat.S_ISREG(observed.st_mode) or getattr(observed, "st_file_attributes", 0) & 0x400:
        raise PassportError("UNSAFE_INPUT_TYPE")
    if observed.st_size > limit:
        raise PassportError("OVERSIZE_INPUT")
    with path.open("rb") as handle:
        raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise PassportError("OVERSIZE_INPUT")
    return raw


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _preflight(root):
    """Bound the metadata and plugin tree before invoking the existing auditor."""
    try:
        registry = sync.read_json(_read_bounded(root / "registry.json", MAX_METADATA_BYTES))
        sync.validate_registry(registry)
        sync.read_json(_read_bounded(root / ".claude-plugin" / "marketplace.json", MAX_METADATA_BYTES))
    except PassportError:
        raise
    except (OSError, ValueError, TypeError) as error:
        raise PassportError("INVALID_INDEX_INPUT") from error
    plugins = root / "plugins"
    observed = plugins.lstat()
    if not stat.S_ISDIR(observed.st_mode) or getattr(observed, "st_file_attributes", 0) & 0x400:
        raise PassportError("UNSAFE_PLUGIN_TREE")
    stack = [plugins]
    count = total_bytes = 0
    while stack:
        with os.scandir(stack.pop()) as children:
            for child in children:
                count += 1
                if count > MAX_TREE_ENTRIES:
                    raise PassportError("TREE_ENTRY_BUDGET_EXCEEDED")
                item = child.stat(follow_symlinks=False)
                if stat.S_ISLNK(item.st_mode) or getattr(item, "st_file_attributes", 0) & 0x400:
                    raise PassportError("UNSAFE_PLUGIN_TREE")
                if stat.S_ISDIR(item.st_mode):
                    stack.append(child.path)
                elif stat.S_ISREG(item.st_mode):
                    total_bytes += item.st_size
                    if total_bytes > MAX_TREE_BYTES:
                        raise PassportError("TREE_BYTE_BUDGET_EXCEEDED")
                else:
                    raise PassportError("UNSAFE_PLUGIN_TREE")
    return registry


def generate(root, plugin_name, skill_name):
    """Return a static preview, never an installation or execution approval."""
    if not isinstance(plugin_name, str) or not sync.NAME.fullmatch(plugin_name):
        raise PassportError("INVALID_PLUGIN_NAME")
    if not isinstance(skill_name, str) or not sync.NAME.fullmatch(skill_name):
        raise PassportError("INVALID_SKILL_NAME")
    root = pathlib.Path(root).resolve(strict=True)
    registry = _preflight(root)
    failures, _, _ = check.audit(root)
    if failures:
        raise PassportError("INDEX_STATIC_CHECK_FAILED")
    entry = next((item for item in registry["plugins"] if item["name"] == plugin_name), None)
    if entry is None or skill_name not in entry["skills"]:
        raise PassportError("SKILL_NOT_INDEXED")

    folder = root / "plugins" / plugin_name
    source_raw = _read_bounded(folder / "SOURCE.json")
    source = sync.read_json(source_raw)
    prefix = "skills/" + skill_name + "/"
    members = sorted(path for path in source["files_sha256"] if path.startswith(prefix))
    if len(members) > MAX_SKILL_MEMBERS:
        raise PassportError("SKILL_MEMBER_BUDGET_EXCEEDED")
    if prefix + "SKILL.md" not in members:
        raise PassportError("SKILL_ENTRYPOINT_MISSING")
    # The full static audit above checks the manifest against actual vendored bytes.
    # Recheck selected bytes here so the preview is bound to what it reports.
    for member in members:
        expected = source["files_sha256"][member]
        if not re.fullmatch(r"[a-f0-9]{64}", expected):
            raise PassportError("INVALID_SOURCE_DIGEST")
        if _digest(_read_bounded(folder / member)) != expected:
            raise PassportError("SOURCE_BYTES_CHANGED")
    fixtures = [
        {"path": member, "sha256": source["files_sha256"][member],
         "synthetic_status": "NOT_VERIFIED"}
        for member in members
        if member.startswith(prefix + "assets/")
        and pathlib.PurePosixPath(member).suffix.lower() in FIXTURE_SUFFIXES
    ]
    if len(fixtures) > MAX_FIXTURES:
        raise PassportError("FIXTURE_BUDGET_EXCEEDED")
    return {
        "schema": SCHEMA,
        "decision": "STATIC_PREVIEW_ONLY",
        "source": {
            "repo": entry["repo"], "ref": entry["ref"], "commit": entry["sha"],
            "license_declared": entry["license"], "maintainer_declared": entry["maintainer"],
            "source_manifest_sha256": _digest(source_raw),
        },
        "skill": {
            "plugin": plugin_name, "name": skill_name,
            "entrypoint_sha256": source["files_sha256"][prefix + "SKILL.md"],
            "vendored_file_count": len(members), "fixture_candidates": fixtures,
        },
        "access": {
            "service_declarations": entry["hosted_services"],
            "credential_requirements": "UNSTRUCTURED_REVIEW_REQUIRED",
            "dynamic_destinations": "NOT_CHECKED",
        },
        "observations": {
            "source_bytes": "MATCHED_LOCAL_MANIFEST",
            "skill_execution": "NOT_RUN",
            "claude_science_import": "NOT_OBSERVED",
            "scientific_validity": "NOT_EVALUATED",
        },
    }


def encode(report):
    raw = (json.dumps(report, ensure_ascii=True, sort_keys=True,
                      separators=(",", ":")) + "\n").encode("utf-8")
    if len(raw) > MAX_OUTPUT_BYTES:
        raise PassportError("OUTPUT_BUDGET_EXCEEDED")
    return raw


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=pathlib.Path, default=ROOT)
    parser.add_argument("--plugin", required=True)
    parser.add_argument("--skill", required=True)
    args = parser.parse_args(argv)
    try:
        sys.stdout.buffer.write(encode(generate(args.root, args.plugin, args.skill)))
    except (OSError, ValueError, KeyError, TypeError) as error:
        code = str(error) if isinstance(error, PassportError) else "INVALID_INDEX_INPUT"
        print(json.dumps({"schema": SCHEMA, "decision": "BLOCKED", "reason": code},
                         sort_keys=True, separators=(",", ":")), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
