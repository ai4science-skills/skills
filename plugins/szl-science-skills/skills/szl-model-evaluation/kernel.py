# SPDX-License-Identifier: Apache-2.0
# Modified 2026-09-30: original attempt-ledger extensions to SZL baseline
# 9668f1571315e93ca2059b9a44f12beef483532d; metric attribution below retained.
# Metrics adapted from szl-holdings/szl-calibration, metrics.py at
# b2e317877abed98e70f9cf6730944a797837faf1. Copyright 2026 SZL Holdings.
"""Binary prediction metrics; no model loading, training, or network access."""
import hashlib
import json
import math
import re


def szl_binary_metrics(probabilities, labels, n_bins=10, threshold=0.5):
    if not isinstance(probabilities, (list, tuple)) or not isinstance(labels, (list, tuple)) or not probabilities or len(probabilities) != len(labels):
        raise ValueError("Nonempty probabilities and labels must have matching lengths")
    if any(isinstance(p, bool) or not isinstance(p, (int, float)) or not math.isfinite(p) or not 0 <= p <= 1 for p in probabilities):
        raise ValueError("Probabilities must be finite numbers in [0,1]")
    if any(type(y) is not int or y not in (0, 1) for y in labels):
        raise ValueError("Labels must be integer 0 or 1")
    if type(n_bins) is not int or not 1 <= n_bins <= 1000:
        raise ValueError("n_bins must be an integer between 1 and 1000")
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError("Threshold must lie in [0,1]")
    n = len(labels)
    buckets = [[] for i in range(n_bins)]
    for p, y in zip(probabilities, labels):
        buckets[min(int(p * n_bins), n_bins - 1)].append((p, y))
    bins = [{"lo": i / n_bins, "hi": (i + 1) / n_bins, "count": len(b),
             "mean_probability": sum(p for p, y in b) / len(b), "positive_fraction": sum(y for p, y in b) / len(b)}
            for i, b in enumerate(buckets) if b]
    ece = sum(b["count"] / n * abs(b["mean_probability"] - b["positive_fraction"]) for b in bins)
    loss = 0.0
    for p, y in zip(probabilities, labels):
        q = min(max(p, 1e-15), 1 - 1e-15)
        loss -= y * math.log(q) + (1 - y) * math.log(1 - q)
    order = sorted(range(n), key=lambda i: probabilities[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and probabilities[order[j + 1]] == probabilities[order[i]]:
            j += 1
        rank = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = rank
        i = j + 1
    positives, negatives = sum(labels), n - sum(labels)
    auc = None if positives == 0 or negatives == 0 else (sum(r for r, y in zip(ranks, labels) if y == 1) - positives * (positives + 1) / 2) / (positives * negatives)
    confusion = {"tp": 0, "tn": 0, "fp": 0, "fn": 0}
    for p, y in zip(probabilities, labels):
        key = "tp" if p >= threshold and y == 1 else "fp" if p >= threshold else "fn" if y == 1 else "tn"
        confusion[key] += 1
    return {"n": n, "brier": sum((p - y) ** 2 for p, y in zip(probabilities, labels)) / n,
            "log_loss": loss / n, "log_loss_clip_epsilon": 1e-15, "ece": ece,
            "mce": max(abs(b["mean_probability"] - b["positive_fraction"]) for b in bins),
            "auroc": auc, "accuracy": (confusion["tp"] + confusion["tn"]) / n,
            "confusion": confusion, "reliability_bins": bins, "n_bins": n_bins, "threshold": threshold}


def szl_evaluate_predictions(probabilities, labels, n_bins=10, threshold=0.5, groups=None, metadata=None):
    metrics = szl_binary_metrics(probabilities, labels, n_bins, threshold)
    cohort = []
    if groups is not None:
        if not isinstance(groups, (list, tuple)) or len(groups) != len(labels) or any(not isinstance(g, str) or not g for g in groups):
            raise ValueError("groups must contain names matching the predictions")
        for g in sorted(set(groups)):
            ix = [i for i, value in enumerate(groups) if value == g]
            m = szl_binary_metrics([probabilities[i] for i in ix], [labels[i] for i in ix], n_bins, threshold)
            cohort.append({"group": g, "metrics": m})
    meta = {} if metadata is None else metadata
    if not isinstance(meta, dict):
        raise ValueError("metadata must be an object")
    record = {"probabilities": probabilities, "labels": labels, "groups": groups,
              "n_bins": n_bins, "threshold": threshold, "metadata": meta}
    digest = hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return {"status": "COMPUTED_ON_SUPPLIED_PREDICTIONS", "metrics": metrics, "cohorts": cohort,
            "input_sha256": digest, "declared_metadata": meta, "model_loaded": False,
            "prediction_model_binding": "NOT_VERIFIED", "held_out_status": "DECLARED_ONLY",
            "promotion_effect": "NONE", "energy_joules": None,
            "warnings": ["No confidence intervals or population-level inference", "Undefined AUROC is null", "ECE depends on binning; compare identical settings"]}


def szl_evaluate_categories(records, held_rows, label_set, metadata=None):
    """Join saved generated triage outputs to retained targets; recompute correctness."""
    if not isinstance(records, list) or not records or len(records) > 100000 or not isinstance(held_rows, list):
        raise ValueError("Supply bounded prediction and held-out row lists")
    if not isinstance(label_set, list) or not label_set or any(not isinstance(v, str) or not v for v in label_set) or len(set(label_set)) != len(label_set):
        raise ValueError("Declare unique nonempty categorical labels")
    target_by_id = {}
    for row in held_rows:
        if not isinstance(row, dict) or not isinstance(row.get("row_id"), str) or not row["row_id"] or row["row_id"] in target_by_id:
            raise ValueError("Held-out row ids must be unique and nonempty")
        target = row.get("target")
        if not isinstance(target, dict) or target.get("label") not in label_set or not isinstance(target.get("state"), str) or not isinstance(target.get("evidence"), list) or any(not isinstance(e, str) for e in target["evidence"]):
            raise ValueError("Invalid held-out target")
        target_by_id[row["row_id"]] = row
    seen, confusion, correct, state_correct, joint_correct, invalid = set(), {}, 0, 0, 0, 0
    for record in records:
        if not isinstance(record, dict) or record.get("row_id") not in target_by_id or record["row_id"] in seen:
            raise ValueError("Duplicate or unmatched prediction id")
        seen.add(record["row_id"])
        row = target_by_id[record["row_id"]]
        target = row["target"]
        if record.get("target") != target or record.get("family") != row.get("family"):
            raise ValueError("Saved target or family disagrees with retained held-out row")
        parsed = record.get("parsed")
        valid = isinstance(parsed, dict) and parsed.get("label") in label_set and isinstance(parsed.get("state"), str) and isinstance(parsed.get("evidence"), list) and all(isinstance(e, str) for e in parsed["evidence"])
        predicted = parsed["label"] if valid else "INVALID_OUTPUT"
        invalid += int(not valid)
        label_ok = valid and predicted == target["label"]
        state_ok = valid and parsed["state"] == target["state"]
        evidence_ok = valid and parsed["evidence"] == target["evidence"]
        correct += int(label_ok)
        state_correct += int(state_ok)
        joint_correct += int(label_ok and state_ok and evidence_ok)
        confusion.setdefault(target["label"], {})[predicted] = confusion.get(target["label"], {}).get(predicted, 0) + 1
    if seen != set(target_by_id):
        raise ValueError("Prediction coverage must exactly match retained held-out rows")
    meta = {} if metadata is None else metadata
    if not isinstance(meta, dict):
        raise ValueError("metadata must be an object")
    n = len(records)
    return {"status": "RECOMPUTED_ON_SAVED_CATEGORICAL_OUTPUTS", "n": n,
            "label_accuracy": correct / n, "state_accuracy": state_correct / n,
            "joint_label_state_evidence_accuracy": joint_correct / n,
            "invalid_outputs": invalid, "confusion": confusion, "label_set": label_set,
            "target_binding": "MATCHED_RETAINED_ROWS_BY_ID", "model_loaded": False,
            "prediction_model_binding": "DECLARED_ONLY", "held_out_status": "DECLARED_ONLY",
            "declared_metadata": meta, "promotion_effect": "NONE", "energy_joules": None,
            "scope": "Saved parsed outputs and exact evidence-list order; stored correctness flags ignored"}


def szl_audit_attempts(planned_attempts, attempts, n_bins=10, threshold=0.5,
                       expected_plan_sha256=None, metadata=None):
    """Audit a bounded binary evaluation plan without dropping failed attempts.

    Labels come from the retained plan, never from an attempt's output. Missing
    observations remain in the planned denominator; probability metrics apply
    only to successful outputs and are explicitly conditional on their coverage.
    """
    if not isinstance(planned_attempts, list) or not 1 <= len(planned_attempts) <= 10000:
        raise ValueError("Declare between 1 and 10000 planned attempts")
    if not isinstance(attempts, list) or len(attempts) > 10000:
        raise ValueError("Supply at most 10000 observed attempts")
    # Validate settings even when every output is missing or invalid.
    szl_binary_metrics([0.5], [0], n_bins, threshold)
    plan, row_labels = {}, {}
    for item in planned_attempts:
        if not isinstance(item, dict) or set(item) != {"attempt_id", "row_id", "label"}:
            raise ValueError("A planned attempt requires only attempt_id, row_id and label")
        for key in ("attempt_id", "row_id"):
            if not isinstance(item[key], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", item[key]):
                raise ValueError("Attempt and row ids must be bounded identifier strings")
        if item["attempt_id"] in plan or type(item["label"]) is not int or item["label"] not in (0, 1):
            raise ValueError("Planned attempt ids must be unique and labels binary integers")
        if item["row_id"] in row_labels and row_labels[item["row_id"]] != item["label"]:
            raise ValueError("Repeated row ids must retain the same label")
        row_labels[item["row_id"]] = item["label"]
        plan[item["attempt_id"]] = dict(item)
    ordered_plan = [plan[key] for key in sorted(plan)]
    plan_sha256 = hashlib.sha256(json.dumps(ordered_plan, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    if expected_plan_sha256 is not None:
        if not isinstance(expected_plan_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_plan_sha256) or expected_plan_sha256 != plan_sha256:
            raise ValueError("Retained plan digest does not match the supplied plan")
    statuses = ("success", "invalid_output", "timeout", "failed", "aborted", "unavailable")
    observed = {}
    for item in attempts:
        if not isinstance(item, dict) or set(item) - {"attempt_id", "row_id", "status", "probability", "reason"}:
            raise ValueError("Unknown observed-attempt fields")
        attempt_id = item.get("attempt_id")
        if not isinstance(attempt_id, str) or attempt_id not in plan or attempt_id in observed:
            raise ValueError("Observed attempt ids must be planned and unique")
        if item.get("row_id") != plan[attempt_id]["row_id"] or item.get("status") not in statuses:
            raise ValueError("Observed row binding or status is invalid")
        if item["status"] == "success":
            szl_binary_metrics([item.get("probability")], [plan[attempt_id]["label"]], n_bins, threshold)
            if "reason" in item:
                raise ValueError("A successful output cannot also declare a failure reason")
        else:
            if "probability" in item or not isinstance(item.get("reason"), str) or not 1 <= len(item["reason"]) <= 1024:
                raise ValueError("Non-success attempts need a bounded reason and no probability")
        observed[attempt_id] = dict(item)
    meta = {} if metadata is None else metadata
    if not isinstance(meta, dict) or len(json.dumps(meta, sort_keys=True, allow_nan=False).encode()) > 65536:
        raise ValueError("metadata must be a JSON object of at most 64 KiB")
    counts = {status: 0 for status in statuses + ("missing",)}
    ledger, probabilities, labels, correct = [], [], [], 0
    for planned in ordered_plan:
        item = observed.get(planned["attempt_id"])
        status = item["status"] if item else "missing"
        counts[status] += 1
        entry = dict(planned, status=status)
        if item:
            if status == "success":
                probability = item["probability"]
                probabilities.append(probability)
                labels.append(planned["label"])
                entry["probability"] = probability
                entry["correct"] = int(probability >= threshold) == planned["label"]
                correct += int(entry["correct"])
            else:
                entry["reason"] = item["reason"]
        ledger.append(entry)
    n = len(ordered_plan)
    attempted = n - counts["missing"] - counts["unavailable"]
    completed = counts["success"] + counts["invalid_output"]
    digest_record = {"plan": ordered_plan, "ledger": ledger, "n_bins": n_bins,
                     "threshold": threshold, "metadata": meta}
    issues = ["MISSING_ATTEMPT_RECORDS"] if counts["missing"] else []
    issues += ["NON_SUCCESS_ATTEMPTS"] if counts["success"] != n else []
    return {"status": "COMPLETE_ATTEMPT_LEDGER" if not counts["missing"] else "INCOMPLETE_ATTEMPT_LEDGER",
            "planned": n, "recorded": len(observed), "attempted": attempted, "completed": completed,
            "successful": counts["success"], "distinct_rows": len(row_labels), "status_counts": counts,
            "attempted_rate": attempted / n, "completion_rate": completed / n,
            "successful_output_rate": counts["success"] / n,
            "planned_accuracy": {"numerator": correct, "denominator": n, "value": correct / n,
                                 "failure_policy": "COUNT_NON_SUCCESS_AS_INCORRECT"},
            "conditional_probability_metrics": szl_binary_metrics(probabilities, labels, n_bins, threshold) if probabilities else None,
            "probability_metric_coverage": {"numerator": counts["success"], "denominator": n},
            "plan_sha256": plan_sha256,
            "plan_binding": "MATCHED_RETAINED_DIGEST" if expected_plan_sha256 is not None else "DECLARED_ONLY",
            "input_sha256": hashlib.sha256(json.dumps(digest_record, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest(),
            "ledger": ledger, "issues": sorted(issues), "declared_metadata": meta,
            "model_loaded": False, "prediction_model_binding": "NOT_VERIFIED", "held_out_status": "DECLARED_ONLY",
            "scientific_performance": "NOT_MEASURED", "promotion_effect": "NONE", "energy_joules": None,
            "limitations": ["Repeated rows are repeated attempts, not independent scientific samples",
                            "Success-only probability metrics can be selection biased; missing probabilities are never imputed",
                            "Statuses, held-out construction and model origin are supplied declarations"]}
