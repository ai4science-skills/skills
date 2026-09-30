# SPDX-License-Identifier: Apache-2.0
"""Local table checks; no download or scientific suitability verdict."""
import collections
import hashlib
import json


def szl_audit_dataset(rows, feature_columns, split_column="split", group_column=None, metadata=None):
    if not isinstance(rows, list) or len(rows) > 100000 or any(not isinstance(r, dict) for r in rows):
        raise ValueError("rows must contain at most 100000 objects")
    if not isinstance(feature_columns, list) or not feature_columns or any(not isinstance(c, str) or not c for c in feature_columns):
        raise ValueError("Declare feature_columns; do not infer identity from labels or row ids")
    if len(set(feature_columns)) != len(feature_columns) or split_column in feature_columns:
        raise ValueError("Features must be unique and exclude the split column")
    if not isinstance(split_column, str) or not split_column or (group_column is not None and (not isinstance(group_column, str) or not group_column)):
        raise ValueError("Invalid split/group column")
    meta = {} if metadata is None else metadata
    if not isinstance(meta, dict):
        raise ValueError("metadata must be an object")
    required = list(feature_columns) + [split_column] + ([] if group_column is None else [group_column])
    missing, splits = collections.Counter(), collections.Counter()
    fingerprints, groups, schemas = {}, {}, set()
    for i, row in enumerate(rows):
        schemas.add(tuple(sorted(row)))
        for col in required:
            if col not in row or row[col] is None or row[col] == "":
                missing[col] += 1
        split = row.get(split_column)
        if not isinstance(split, str) or not split:
            split = "UNDECLARED"
        splits[split] += 1
        if all(c in row and row[c] is not None and row[c] != "" for c in feature_columns):
            blob = json.dumps([row[c] for c in feature_columns], sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
            key = hashlib.sha256(blob).hexdigest()
            fingerprints.setdefault(key, []).append((i, split))
        if group_column is not None and row.get(group_column) is not None and row.get(group_column) != "":
            key = hashlib.sha256(json.dumps(row[group_column], sort_keys=True, allow_nan=False).encode()).hexdigest()
            groups.setdefault(key, set()).add(split)
    duplicates = [{"sha256": h, "row_indexes": [i for i, s in v], "splits": sorted({s for i, s in v})}
                  for h, v in fingerprints.items() if len(v) > 1]
    leakage = [d for d in duplicates if len(d["splits"]) > 1]
    group_leakage = [{"group_sha256": h, "splits": sorted(s)} for h, s in groups.items() if len(s) > 1]
    issues = []
    for condition, issue in ((not rows, "EMPTY_DATASET"), (bool(missing), "MISSING_REQUIRED_VALUES"),
        (len(schemas) > 1, "INCONSISTENT_ROW_KEYS"), (bool(duplicates), "EXACT_FEATURE_DUPLICATES"),
        (bool(leakage), "CROSS_SPLIT_FEATURE_LEAKAGE"), (bool(group_leakage), "CROSS_SPLIT_GROUP_LEAKAGE"),
        (not meta.get("source_revision"), "SOURCE_REVISION_UNDECLARED"),
        (not meta.get("license") or str(meta["license"]).lower() in {"other", "unknown", "unavailable"}, "REUSE_TERMS_REQUIRE_REVIEW")):
        if condition:
            issues.append(issue)
    blob = json.dumps(rows, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return {"status": "ISSUES_FOUND" if issues else "NO_CHECKED_ISSUES", "readiness": "REVIEW",
            "rows": len(rows), "splits": dict(splits), "missing": dict(missing), "issues": issues,
            "duplicates": duplicates, "feature_leakage": leakage, "group_leakage": group_leakage,
            "input_sha256": hashlib.sha256(blob).hexdigest(), "declared_metadata": meta,
            "provenance_verified": False, "scientific_suitability": "NOT_ASSESSED",
            "limitations": ["Exact feature equality only; no semantic leakage detector", "Digests do not anonymize sensitive data", "License metadata is recorded, not legally verified"]}
