#!/usr/bin/env python3
"""Offline review of two retained skill catalogs; never installs or executes skills."""
import argparse
import hashlib
import json
import pathlib
import re
import sys

import check
import sync
from static_io import AuditBoundaryError, Limits, inventory, read_single, tree_digest
from trust_common import ValidationError, strict_json

SCHEMA = "ai4s.update-preview/v1"
CATALOG_LIMITS = Limits(max_file_bytes=sync.MAX_PLUGIN, max_total_bytes=50 * sync.MAX_PLUGIN,
                       max_files=10000, max_entries=20000, max_depth=32)


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _public_text(value):
    """Refuse recognizable secret values before retaining metadata in a preview."""
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValidationError("metadata contains control characters")
    if any(re.search(pattern, value) for pattern in check.SECRETS.values()):
        raise ValidationError("metadata contains a possible sensitive value; withheld")
    return value


def load_catalog(root):
    """Bind registry and SOURCE assertions to bounded captured plugin bytes."""
    root = pathlib.Path(root)
    raw = read_single(root / "registry.json", sync.MAX_PLUGIN)
    registry = strict_json(raw)
    sync.validate_registry(registry)
    stack = [registry]
    while stack:
        value = stack.pop()
        if isinstance(value, str):
            _public_text(value)
        elif isinstance(value, dict):
            stack.extend(value.keys())
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
    captured, coverage = inventory(root / "plugins", limits=CATALOG_LIMITS)
    if coverage["excluded_paths"] or {name.split("/", 1)[0] for name in captured} != {entry["name"] for entry in registry["plugins"]}:
        raise ValidationError("captured plugin membership differs from registry")
    plugins = {}
    for entry in registry["plugins"]:
        prefix = entry["name"] + "/"
        files = {name[len(prefix):]: data for name, data in captured.items() if name.startswith(prefix)}
        byte_count = sum(len(data) for data in files.values())
        if byte_count >= sync.MAX_PLUGIN:
            raise ValidationError("plugin exceeds byte budget")
        folded = set()
        for name in files:
            sync.safe_path(name)
            _public_text(name)
            if name.casefold() in folded:
                raise ValidationError("plugin paths collide across case-insensitive filesystems")
            folded.add(name.casefold())
        source = strict_json(files.get("SOURCE.json", b""))
        identity = {key: entry[key] for key in ("repo", "ref", "sha", "path")}
        if not isinstance(source, dict) or set(source) != set(identity) | {"files_sha256"}:
            raise ValidationError("SOURCE manifest fields do not match the contract")
        if any(source[key] != value for key, value in identity.items()):
            raise ValidationError("SOURCE identity differs from registry")
        observed = {name: _hash(data) for name, data in files.items() if name != "SOURCE.json"}
        if source["files_sha256"] != observed:
            raise ValidationError("SOURCE file hashes or membership differ from captured bytes")
        if any("skills/%s/SKILL.md" % skill not in files for skill in entry["skills"]):
            raise ValidationError("a selected skill has no captured SKILL.md")
        if not any(name in files for name in sync.LICENSE_NAMES[:-1]):
            raise ValidationError("plugin has no captured source license")
        plugins[entry["name"]] = {"entry": entry, "files": observed,
                                  "source_sha256": _hash(files["SOURCE.json"]),
                                  "captured_tree_sha256": tree_digest(files),
                                  "bytes": byte_count}
    return {"registry": registry, "registry_sha256": _hash(raw), "plugins": plugins}


def _identity(entry, skill):
    # This is a display/review identity, never an install path or automatic rename.
    return entry["repo"].casefold() + "/" + entry["path"] + "/" + skill


def compare(before, after, occupied=()):
    """Compute deterministic changes and surface collisions without rewriting names."""
    occupied = list(occupied)
    if len(occupied) > 10000 or any(not isinstance(name, str) or not sync.NAME.fullmatch(name)
                                    for name in occupied):
        raise ValidationError("occupied names must be at most 10000 portable skill names")
    occupied = {name.casefold() for name in occupied}
    changes = []
    for name in sorted(set(before["plugins"]) | set(after["plugins"])):
        old, new = before["plugins"].get(name), after["plugins"].get(name)
        old_entry, new_entry = (old or {}).get("entry", {}), (new or {}).get("entry", {})
        old_files, new_files = (old or {}).get("files", {}), (new or {}).get("files", {})
        file_changes = [{"path": path, "before_sha256": old_files.get(path),
                         "after_sha256": new_files.get(path)}
                        for path in sorted(set(old_files) | set(new_files))
                        if old_files.get(path) != new_files.get(path)]
        metadata_changes = [key for key in sorted(set(old_entry) | set(new_entry))
                            if old_entry.get(key) != new_entry.get(key)]
        if not file_changes and not metadata_changes:
            continue
        old_services, new_services = old_entry.get("hosted_services", []), new_entry.get("hosted_services", [])
        old_hosts = sync.declared_hosts(old_entry) if old else set()
        new_hosts = sync.declared_hosts(new_entry) if new else set()
        changes.append({"plugin": name, "change": "ADDED" if not old else "REMOVED" if not new else "CHANGED",
                        "before_source": {k: old_entry.get(k) for k in ("repo", "ref", "sha", "path")},
                        "after_source": {k: new_entry.get(k) for k in ("repo", "ref", "sha", "path")},
                        "metadata_changed": metadata_changes, "files": file_changes,
                        "skills_added": sorted(set(new_entry.get("skills", [])) - set(old_entry.get("skills", []))),
                        "skills_removed": sorted(set(old_entry.get("skills", [])) - set(new_entry.get("skills", []))),
                        "services_added": sorted(set(new_services) - set(old_services)),
                        "services_removed": sorted(set(old_services) - set(new_services)),
                        "hosts_added": sorted(new_hosts - old_hosts), "hosts_removed": sorted(old_hosts - new_hosts),
                        "declared_service_change_requires_review": old_services != new_services,
                        "bytes_before": old["bytes"] if old else None, "bytes_after": new["bytes"] if new else None})
    identities, names = [], {}
    for plugin, capture in sorted(after["plugins"].items()):
        entry = capture["entry"]
        for skill in sorted(entry["skills"]):
            identity = {"plugin": plugin, "name": skill, "publisher_qualified_id": _identity(entry, skill)}
            identities.append(identity)
            names.setdefault(skill.casefold(), []).append(identity)
    collisions = [{"name": name, "occupied_by_caller": name in occupied, "candidate_identities": rows}
                  for name, rows in sorted(names.items()) if name in occupied or len(rows) > 1]
    registry_changed = before["registry"] != after["registry"]
    result = {"schema": SCHEMA, "status": "REVIEW_REQUIRED" if changes or collisions or registry_changed else "NO_CHANGE",
              "installable": False, "automatic_update": False, "skill_code_executed": False,
              "before_registry_sha256": before["registry_sha256"], "after_registry_sha256": after["registry_sha256"],
              "registry_metadata_changed": [key for key in sorted(set(before["registry"]) | set(after["registry"]))
                                            if key != "plugins" and before["registry"].get(key) != after["registry"].get(key)],
              "changes": changes, "candidate_identities": identities, "name_collisions": collisions,
              "catalog_bindings": {label: {name: {key: item[key] for key in ("source_sha256", "captured_tree_sha256", "bytes")}
                                           for name, item in sorted(catalog["plugins"].items())}
                                   for label, catalog in (("before", before), ("after", after))},
              "credentials": "UNSTRUCTURED_DECLARATIONS_REVIEW_REQUIRED",
              "capabilities": "UNASSESSED; service declarations and file changes are review inputs",
              "proof_scope": "Captured local file paths and bytes; caller-provided pins are not independently authenticated. Modes and empty directories are outside the digest.",
              "next_step": "Review changes, credentials and collisions; choose any update explicitly in the target application. This tool performs no import, rename, update or installation."}
    result["receipt_sha256"] = _hash(json.dumps(result, sort_keys=True, separators=(",", ":"),
                                               ensure_ascii=False, allow_nan=False).encode("utf-8"))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", required=True, help="retained old catalog directory")
    parser.add_argument("--after", required=True, help="retained candidate catalog directory")
    parser.add_argument("--occupied-name", action="append", default=[], help="existing personal or imported skill name")
    args = parser.parse_args(argv)
    try:
        result = compare(load_catalog(args.before), load_catalog(args.after), args.occupied_name)
    except (ValidationError, sync.SyncError, AuditBoundaryError, OSError, UnicodeError, ValueError, RecursionError):
        # Do not echo paths, input values or credential-shaped metadata on failure.
        print(json.dumps({"schema": SCHEMA, "status": "BLOCKED", "installable": False,
                          "error": "Invalid, incomplete, linked, changed or oversized retained catalog; input values withheld."}))
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
    return 0  # Preview completed; REVIEW_REQUIRED never grants an update.


if __name__ == "__main__":
    sys.exit(main())
