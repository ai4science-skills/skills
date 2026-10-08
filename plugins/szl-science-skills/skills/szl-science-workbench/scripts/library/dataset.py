# SPDX-License-Identifier: Apache-2.0
# Modified 2026-09-30: bounded entity/time/preprocessing evidence checks.
"""Local table checks; no download or scientific suitability verdict."""
import collections
import datetime
import hashlib
import json
import math


def szl_dataset_audit_base(rows, feature_columns, split_column="split", group_column=None, metadata=None):
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
                  for h, v in sorted(fingerprints.items()) if len(v) > 1]
    leakage = [d for d in duplicates if len(d["splits"]) > 1]
    group_leakage = [{"group_sha256": h, "splits": sorted(s)} for h, s in sorted(groups.items()) if len(s) > 1]
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


def szl_dataset_json_evidence(value):
    pending, nodes = [(value, 0)], 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if nodes > 1000000 or depth > 32:
            raise ValueError("Evidence exceeds depth/node budget")
        if type(item) is dict:
            if any(type(k) is not str or len(k) > 256 for k in item):
                raise ValueError("Object keys must be bounded strings")
            pending.extend((v, depth + 1) for v in item.values())
        elif type(item) is list:
            pending.extend((v, depth + 1) for v in item)
        elif type(item) is str:
            if len(item) > 65536:
                raise ValueError("String exceeds evidence budget")
        elif type(item) is float:
            if not math.isfinite(item):
                raise ValueError("Nonfinite evidence")
        elif type(item) is int:
            if item.bit_length() > 1024:
                raise ValueError("Integer exceeds evidence budget")
        elif item is not None and type(item) is not bool:
            raise ValueError("Evidence must contain only JSON values")
    blob = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if len(blob) > 8 * 1024 * 1024:
        raise ValueError("Selected evidence exceeds 8 MiB")
    return blob


def szl_dataset_name(value, label):
    if type(value) is not str or not value.strip() or len(value) > 256:
        raise ValueError(label + " must be a bounded nonempty string")
    return value


def szl_dataset_names(value, label, nonempty=True, maximum=100000):
    if type(value) is not list or len(value) > maximum or (nonempty and not value):
        raise ValueError(label + " must be a bounded list")
    for item in value:
        szl_dataset_name(item, label)
    if len(set(value)) != len(value):
        raise ValueError(label + " must be unique")
    return value


def szl_dataset_stamp(value):
    if type(value) is not str or len(value) > 64:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.astimezone(datetime.timezone.utc)
    except (ValueError, OverflowError):
        return None


def szl_dataset_audit_leakage(rows, split_column, spec):
    checks = {name: {"status": "NOT_CHECKED", "findings": [], "missing_evidence": []}
              for name in ("entity", "temporal", "preprocessing")}
    if spec is None:
        return checks, []
    fields = {"schema", "row_id_column", "entity_columns", "temporal", "transforms", "expected_transform_ids", "preprocessing_training_splits"}
    if type(spec) is not dict or set(spec) - fields or not {"schema", "row_id_column"} <= set(spec):
        raise ValueError("leakage_spec has unsupported or missing fields")
    if spec["schema"] != "szl.dataset-leakage/v1":
        raise ValueError("Unsupported leakage schema")
    id_col = szl_dataset_name(spec["row_id_column"], "row_id_column")
    row_ids, id_missing, issues = {}, [], []
    for i, row in enumerate(rows):
        value = row.get(id_col)
        if value is None or value == "":
            id_missing.append(i)
            continue
        szl_dataset_name(value, "row id")
        if value in row_ids:
            raise ValueError("row ids must be unique")
        row_ids[value] = i
    check = checks["entity"]
    columns = spec.get("entity_columns")
    if columns is None:
        check["missing_evidence"].append("ENTITY_COLUMNS_UNDECLARED")
    else:
        szl_dataset_names(columns, "entity_columns", maximum=32)
        for col in columns:
            groups = {}
            for i, row in enumerate(rows):
                value, split = row.get(col), row.get(split_column)
                if value is None or value == "" or type(split) is not str or not split:
                    check["missing_evidence"].append({"column": col, "row_index": i})
                    continue
                if type(value) not in (str, int) or (type(value) is str and not value.strip()):
                    raise ValueError("entity ids must be strings/integers excluding booleans")
                token = hashlib.sha256(szl_dataset_json_evidence(value)).hexdigest()
                groups.setdefault(token, []).append((i, split))
            for token, members in sorted(groups.items()):
                splits = sorted({s for _, s in members})
                if len(splits) > 1:
                    check["findings"].append({"code": "CROSS_SPLIT_ENTITY_LEAKAGE", "column": col,
                                              "entity_sha256": token, "row_indexes": [i for i, _ in members], "splits": splits})
    check = checks["temporal"]
    temporal = spec.get("temporal")
    training_scope = None if spec.get("preprocessing_training_splits") is None else set(szl_dataset_names(spec["preprocessing_training_splits"], "preprocessing_training_splits", maximum=32))
    if temporal is None:
        check["missing_evidence"].append("TEMPORAL_DESIGN_UNDECLARED")
    else:
        required = {"observation_time_column", "label_available_at_column", "prediction_time_column",
                    "training_splits", "evaluation_splits", "split_order"}
        if type(temporal) is not dict or set(temporal) != required:
            raise ValueError("temporal fields must exactly match contract")
        columns = [szl_dataset_name(temporal[k], k) for k in ("observation_time_column", "label_available_at_column", "prediction_time_column")]
        if len(set(columns)) != 3:
            raise ValueError("Temporal evidence columns must differ")
        train = set(szl_dataset_names(temporal["training_splits"], "training_splits", maximum=32))
        if training_scope is not None and training_scope != train:
            raise ValueError("Preprocessing and temporal training split declarations disagree")
        training_scope = train
        evaluation = set(szl_dataset_names(temporal["evaluation_splits"], "evaluation_splits", maximum=32))
        order = szl_dataset_names(temporal["split_order"], "split_order", maximum=32)
        if train & evaluation or set(order) != train | evaluation:
            raise ValueError("split_order must cover disjoint training/evaluation splits exactly")
        times, by_split = {}, {}
        for i, row in enumerate(rows):
            split = row.get(split_column)
            if type(split) is not str or split not in train | evaluation:
                check["missing_evidence"].append({"row_index": i, "reason": "UNDECLARED_TEMPORAL_SPLIT"})
                continue
            parsed = tuple(szl_dataset_stamp(row.get(c)) for c in columns)
            for col, stamp in zip(columns, parsed):
                if stamp is None:
                    check["missing_evidence"].append({"row_index": i, "column": col, "reason": "MISSING_AMBIGUOUS_OR_OUT_OF_RANGE_TIME"})
            if None in parsed:
                continue
            times[i] = parsed
            by_split.setdefault(split, []).append(i)
            if parsed[0] > parsed[2]:
                check["findings"].append({"code": "FUTURE_OBSERVATION_LEAKAGE", "row_indexes": [i]})
        origins = [times[i][2] for split in sorted(evaluation) for i in by_split.get(split, [])]
        if not origins:
            check["missing_evidence"].append("NO_COMPLETE_EVALUATION_TIME_EVIDENCE")
        else:
            cutoff = min(origins)
            for split in sorted(train):
                for i in by_split.get(split, []):
                    if times[i][1] > cutoff:
                        check["findings"].append({"code": "TRAIN_LABEL_AVAILABILITY_LEAKAGE", "row_indexes": [i]})
        for split in order:
            if not by_split.get(split):
                check["missing_evidence"].append({"split": split, "reason": "NO_COMPLETE_SPLIT_TIME_EVIDENCE"})
        for a, earlier in enumerate(order):
            for later in order[a + 1:]:
                left, right = by_split.get(earlier, []), by_split.get(later, [])
                if left and right and max(times[i][0] for i in left) >= min(times[i][0] for i in right):
                    check["findings"].append({"code": "TEMPORAL_SPLIT_ORDER_LEAKAGE", "splits": [earlier, later]})
    check = checks["preprocessing"]
    transforms, expected = spec.get("transforms"), spec.get("expected_transform_ids")
    if transforms is None or expected is None:
        check["missing_evidence"].append("FIT_MANIFEST_OR_EXPECTED_TRANSFORMS_UNDECLARED")
    else:
        szl_dataset_names(expected, "expected_transform_ids", nonempty=False)
        if expected and training_scope is None:
            check["missing_evidence"].append("PREPROCESSING_TRAINING_SPLITS_UNDECLARED")
        if type(transforms) is not list or len(transforms) > 1000:
            raise ValueError("transforms must be a bounded list")
        seen = set()
        for transform in transforms:
            if type(transform) is not dict or set(transform) != {"id", "fit_row_ids", "fit_split_ids", "allowed_fit_splits"}:
                raise ValueError("transform fields must exactly match contract")
            name = szl_dataset_name(transform["id"], "transform id")
            if name in seen or name not in expected:
                raise ValueError("Duplicate or unexpected transform")
            seen.add(name)
            fit = szl_dataset_names(transform["fit_row_ids"], "fit_row_ids")
            declared = set(szl_dataset_names(transform["fit_split_ids"], "fit_split_ids", maximum=32))
            allowed = set(szl_dataset_names(transform["allowed_fit_splits"], "allowed_fit_splits", maximum=32))
            actual, fit_evidence_complete = set(), True
            for row_id in fit:
                if row_id not in row_ids:
                    fit_evidence_complete = False
                    check["missing_evidence"].append({"transform": name, "reason": "FIT_ROW_NOT_IN_SELECTED_EVIDENCE"})
                else:
                    split = rows[row_ids[row_id]].get(split_column)
                    if type(split) is not str or not split:
                        fit_evidence_complete = False
                        check["missing_evidence"].append({"transform": name, "reason": "FIT_SPLIT_MISSING"})
                    else:
                        actual.add(split)
            if actual - allowed or declared - allowed or (training_scope is not None and (actual | declared | allowed) - training_scope):
                check["findings"].append({"code": "PREPROCESSING_FIT_SCOPE_LEAKAGE", "transform": name,
                                          "observed_fit_splits": sorted(actual), "declared_fit_splits": sorted(declared)})
            if actual - declared or (fit_evidence_complete and actual != declared):
                check["findings"].append({"code": "FIT_SPLIT_DECLARATION_MISMATCH", "transform": name,
                                          "observed_fit_splits": sorted(actual), "declared_fit_splits": sorted(declared)})
        for name in sorted(set(expected) - seen):
            check["missing_evidence"].append({"transform": name, "reason": "EXPECTED_TRANSFORM_MISSING"})
        for i in id_missing:
            check["missing_evidence"].append({"row_index": i, "reason": "ROW_ID_MISSING"})
    for check in checks.values():
        check["status"] = "ISSUES_FOUND" if check["findings"] else "UNKNOWN" if check["missing_evidence"] else "NO_CHECKED_ISSUES"
        issues.extend(sorted({f["code"] for f in check["findings"]}))
    if any(c["missing_evidence"] for c in checks.values()):
        issues.append("LEAKAGE_EVIDENCE_INCOMPLETE")
    return checks, issues


def szl_audit_dataset(rows, feature_columns, split_column="split", group_column=None, metadata=None, *, leakage_spec=None):
    """Backward-compatible table audit with optional evidence-bound leakage design."""
    szl_dataset_json_evidence(rows)
    szl_dataset_names(feature_columns, "feature_columns", maximum=64)
    szl_dataset_name(split_column, "split_column")
    if type(rows) is not list or len(rows) > 100000 or any(type(row) is not dict for row in rows):
        raise ValueError("rows must contain at most 100000 objects")
    for row in rows:
        if row.get(split_column) is not None and type(row[split_column]) is not str:
            raise ValueError("split values must be strings or null")
    if group_column is not None:
        szl_dataset_name(group_column, "group_column")
    if metadata is not None:
        szl_dataset_json_evidence(metadata)
        if type(metadata) is not dict:
            raise ValueError("metadata must be an object")
        for field in ("source_revision", "license"):
            if field in metadata and metadata[field] is not None and type(metadata[field]) is not str:
                raise ValueError(field + " metadata must be a string or null")
    if leakage_spec is not None:
        szl_dataset_json_evidence(leakage_spec)
    report = szl_dataset_audit_base(rows, feature_columns, split_column, group_column, metadata)
    checks, issues = szl_dataset_audit_leakage(rows, split_column, leakage_spec)
    report["leakage_checks"] = checks
    report["issues"].extend(issues)
    report["status"] = "ISSUES_FOUND" if report["issues"] else "NO_CHECKED_ISSUES"
    report["behavioral_evaluation"] = "NOT_MEASURED"
    report["splits"] = dict(sorted(report["splits"].items()))
    report["missing"] = dict(sorted(report["missing"].items()))
    report["limitations"].extend(["Temporal ordering checks declared design, not causal validity",
                                  "Fit manifests bind selected rows, not actual transform execution"])
    return report
