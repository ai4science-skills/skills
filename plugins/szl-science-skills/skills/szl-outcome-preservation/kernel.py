# SPDX-License-Identifier: Apache-2.0
"""Audit a complete supplied optimization cohort, including downstream decisions."""
import hashlib
import json
import math
import re
import statistics


def szl_finite(value, minimum=None):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("Expected a finite number")
    if minimum is not None and value < minimum:
        raise ValueError("Number below declared bound")
    return value


def szl_outcome_preservation(record):
    if not isinstance(record, dict) or record.get("schema") != "szl.outcome-preservation.v1":
        raise ValueError("Unsupported schema")
    for key in ("reference_revision", "candidate_revision"):
        if not isinstance(record.get(key), str) or not re.fullmatch("[0-9a-f]{40}", record[key]):
            raise ValueError("Declare full immutable implementation revisions")
    mode = record["mode"]
    if mode not in ("exact", "fast", "big"):
        raise ValueError("Declare exact, fast or big mode")
    ids = record["expected_case_ids"]
    if not isinstance(ids, list) or not 1 <= len(ids) <= 1000 or any(not isinstance(x, str) or not x or len(x) > 128 for x in ids) or len(set(ids)) != len(ids):
        raise ValueError("Declare 1..1000 unique expected case ids before evaluation")
    cases = record["cases"]
    if not isinstance(cases, list) or len(cases) > 1000 or any(not isinstance(c, dict) for c in cases):
        raise ValueError("At most 1000 case records")
    found = [c["id"] for c in cases]
    if len(set(found)) != len(found):
        raise ValueError("Duplicate case id")
    atol = szl_finite(record["atol"], 0)
    rtol = szl_finite(record["rtol"], 0)
    rule = record["decision_rule"]
    if not isinstance(rule, dict):
        raise ValueError("Decision rule must be an object")
    threshold = szl_finite(rule["threshold"])
    drift = szl_finite(rule["maximum_metric_absolute_drift"], 0)
    if rule["operator"] not in ("ge", "le"):
        raise ValueError("Decision operator must be ge or le")
    failures = []
    missing = sorted(set(ids) - set(found))
    unexpected = sorted(set(found) - set(ids))
    if missing or unexpected:
        failures.append("INCOMPLETE_COHORT")
    results = []
    for case in cases:
        ref, cand = case["reference"], case["candidate"]
        if not isinstance(ref, dict) or not isinstance(cand, dict):
            raise ValueError("Implementation records must be objects")
        issues = []
        if ref.get("status") != "SUCCESS" or cand.get("status") != "SUCCESS":
            issues.append("EXECUTION_FAILED_OR_UNOBSERVED")
        if cand.get("activated_mode") != mode:
            issues.append("OPTIMIZATION_NOT_ACTIVE")
        metric_delta, changed, numeric_mismatches = None, None, None
        speedup, memory_ratio, fair = None, None, False
        if not issues:
            xs, ys = ref["output"], cand["output"]
            if not isinstance(xs, list) or not isinstance(ys, list) or not 1 <= len(xs) <= 10000 or len(xs) != len(ys):
                raise ValueError("Outputs must be matched nonempty flat arrays of at most 10000 numbers")
            xs = [szl_finite(x) for x in xs]
            ys = [szl_finite(y) for y in ys]
            differences = [szl_finite(abs(x - y), 0) for x, y in zip(xs, ys)]
            limits = [szl_finite(atol + rtol * abs(x), 0) for x in xs]
            numeric_mismatches = sum(d > lim for d, lim in zip(differences, limits))
            if numeric_mismatches:
                issues.append("NUMERICAL_MISMATCH")
            if mode == "exact":
                hashes = [r.get("output_sha256") for r in (ref, cand)]
                if any(not isinstance(h, str) or re.fullmatch("[0-9a-f]{64}", h) is None for h in hashes):
                    issues.append("EXACT_BYTES_UNOBSERVED")
                elif hashes[0] != hashes[1] or xs != ys:
                    issues.append("EXACT_BYTES_MISMATCH")
            a, b = szl_finite(ref["scientific_metric"]), szl_finite(cand["scientific_metric"])
            metric_delta = szl_finite(abs(a - b), 0)
            decisions = [m >= threshold if rule["operator"] == "ge" else m <= threshold for m in (a, b)]
            changed = decisions[0] != decisions[1]
            if changed:
                issues.append("SCIENTIFIC_DECISION_CHANGED")
            if metric_delta > drift:
                issues.append("SCIENTIFIC_METRIC_DRIFT")
            contexts = [r.get("benchmark_context") for r in (ref, cand)]
            required = {"hardware", "dtype", "input_sha256", "warmup", "synchronized", "measurement_method"}
            context = contexts[0]
            fair = isinstance(context, dict) and required <= context.keys() and context == contexts[1]
            if fair:
                fair = (all(isinstance(context[k], str) and context[k].strip() for k in ("hardware", "dtype", "measurement_method"))
                        and isinstance(context["input_sha256"], str) and re.fullmatch("[0-9a-f]{64}", context["input_sha256"]) is not None
                        and type(context["warmup"]) is int and context["warmup"] >= 0 and context["synchronized"] is True)
            times = [r.get("seconds") for r in (ref, cand)]
            if all(t is not None for t in times):
                if any(not isinstance(t, list) or not 3 <= len(t) <= 1000 for t in times):
                    raise ValueError("Timings require 3..1000 durations per implementation")
                for t in times:
                    if any(szl_finite(v, 0) == 0 for v in t):
                        raise ValueError("Durations must be positive")
            memory = [r.get("peak_memory_bytes") for r in (ref, cand)]
            if all(m is not None for m in memory):
                if any(type(m) is not int or m <= 0 for m in memory):
                    raise ValueError("Peak memory requires positive integer byte counts")
            if fair and not issues and case["id"] in ids and not missing and not unexpected:
                if all(t is not None for t in times):
                    speedup = szl_finite(statistics.median(times[0]) / statistics.median(times[1]), 0)
                if all(m is not None for m in memory) and isinstance(context.get("memory_measurement_method"), str) and context["memory_measurement_method"].strip():
                    memory_ratio = szl_finite(memory[0] / memory[1], 0)
        failures.extend(issues)
        results.append({"id": case["id"], "issues": issues, "scientific_metric_absolute_drift": metric_delta,
                        "decision_changed": changed, "numerical_mismatches": numeric_mismatches,
                        "benchmark_contexts_match": bool(fair),
                        "supplied_median_speedup": speedup, "supplied_memory_reduction_ratio": memory_ratio})
    # A failed case cannot be hidden by reporting an average speedup on the remaining cases.
    if failures:
        for row in results:
            row["supplied_median_speedup"] = None
            row["supplied_memory_reduction_ratio"] = None
    digest = hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return {"schema": "szl.outcome-preservation-result.v1",
            "status": "REGRESSION_OR_GAP" if failures else "PRESERVED_ON_SUPPLIED_COHORT",
            "mode": mode, "expected_cases": len(ids), "observed_cases": len(cases),
            "reference_revision": record["reference_revision"], "candidate_revision": record["candidate_revision"],
            "missing_case_ids": missing, "unexpected_case_ids": unexpected,
            "findings": sorted(set(failures)), "cases": results, "input_sha256": digest,
            "measurements": "CALLER_SUPPLIED_NOT_INDEPENDENTLY_VERIFIED", "scientific_generalization": "NOT_ESTABLISHED"}
