# SPDX-License-Identifier: Apache-2.0
# Metrics adapted from szl-holdings/szl-calibration, metrics.py at
# b2e317877abed98e70f9cf6730944a797837faf1. Copyright 2026 SZL Holdings.
"""Binary prediction metrics; no model loading, training, or network access."""
import hashlib
import json
import math


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
