# SPDX-License-Identifier: Apache-2.0
"""Original offline paired-cluster audit. No external code or statistical package."""
import hashlib
import json
import math
import re
from decimal import Decimal
from fractions import Fraction

SCHEMA = "szl.clustered-replication.v1"
MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 10000
MAX_CLUSTERS = 16
PLAN_KEYS = {"schema", "experimental_unit", "observational_unit", "unit",
             "expected_cases", "reported_n", "independent_clusters_declared",
             "sign_flip_basis", "min_clusters", "alpha", "minimum_improvement"}
BASES = {"paired_randomization", "symmetric_cluster_differences", "undeclared"}


def canonical_sha256(value):
    """Contract JSON commitment, not a signature or evidence of when a plan was made."""
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def szl_cluster_object(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError(label + " must have the exact contract fields")
    return value


def szl_cluster_id(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value):
        raise ValueError(label + " must be a bounded identifier")
    return value


def szl_cluster_number(value, label, lower=0, upper=1e12):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(label + " must be a finite bounded number")
    if not lower <= value <= upper or not math.isfinite(value):
        raise ValueError(label + " must be a finite bounded number")
    return Fraction(value)


def szl_cluster_report_number(value):
    """Do not turn a nonzero exact aggregate into a contradictory zero summary."""
    reported = float(value)
    if not math.isfinite(reported) or (reported == 0 and value != 0):
        raise ValueError("Aggregate overflows or underflows the supported float report representation")
    return reported


def szl_cluster_integer(value, label, lower, upper):
    if type(value) is not int or not lower <= value <= upper:
        raise ValueError(label + " must be a bounded integer")
    return value


def szl_cluster_unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def szl_cluster_json_integer(token):
    if len(token) > 64:
        raise ValueError("Integer token exceeds 64 characters")
    return int(token)


def szl_cluster_json_float(token):
    if len(token) > 128:
        raise ValueError("Float token exceeds 128 characters")
    value = float(token)
    if not math.isfinite(value) or (value == 0 and Decimal(token) != 0):
        raise ValueError("JSON number overflows or underflows the supported float representation")
    return value


def read_json(raw):
    """Bound bytes and structural nesting before using the stdlib decoder."""
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
        raise ValueError("Input must be bytes of at most 2 MiB")
    text = raw.decode("utf-8")
    depth, quoted, escaped = 0, False, False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > 32:
                raise ValueError("JSON nesting exceeds 32")
        elif char in "]}":
            depth -= 1
    def reject_constant(_):
        raise ValueError("Nonfinite JSON constant")
    value = json.loads(text, object_pairs_hook=szl_cluster_unique, parse_constant=reject_constant,
                       parse_int=szl_cluster_json_integer, parse_float=szl_cluster_json_float)
    # Strict Unicode encoding also rejects JSON-escaped unpaired surrogates.
    json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
    return value


def exact_two_sided(differences):
    """Enumerate all 2**K sign vectors with exact rational comparisons, ties included.

    Conditional on independent paired randomization, or declared independent symmetric
    cluster differences. Zero differences keep their sign vectors in the denominator.
    Gray-code traversal changes one sign each step; no Monte Carlo or early stopping.
    """
    if not 1 <= len(differences) <= MAX_CLUSTERS:
        raise ValueError("Exact test supports 1 to 16 cluster differences")
    differences = [Fraction(value) for value in differences]
    observed = abs(sum(differences, Fraction()))
    running = -sum(differences, Fraction())
    extreme = int(abs(running) >= observed)
    previous = 0
    for index in range(1, 1 << len(differences)):
        gray = index ^ (index >> 1)
        changed = gray ^ previous
        bit = changed.bit_length() - 1
        running += (2 if gray & changed else -2) * differences[bit]
        extreme += int(abs(running) >= observed)
        previous = gray
    total = 1 << len(differences)
    return {"extreme_sign_vectors": extreme, "total_sign_vectors": total,
            "p_two_sided": float(Fraction(extreme, total))}


def szl_cluster_audit(document, expected_plan_sha256):
    szl_cluster_object(document, {"plan", "rows"}, "document")
    plan = szl_cluster_object(document["plan"], PLAN_KEYS, "plan")
    if plan["schema"] != SCHEMA:
        raise ValueError("Unsupported schema")
    for name in ("experimental_unit", "observational_unit", "unit"):
        szl_cluster_id(plan[name], name)
    if type(plan["independent_clusters_declared"]) is not bool:
        raise ValueError("Independent-cluster declaration must be boolean")
    if not isinstance(plan["sign_flip_basis"], str) or plan["sign_flip_basis"] not in BASES:
        raise ValueError("Unsupported sign-flip basis")
    minimum_clusters = szl_cluster_integer(plan["min_clusters"], "min_clusters", 2, MAX_CLUSTERS)
    szl_cluster_integer(plan["reported_n"], "reported_n", 1, MAX_ROWS)
    alpha = szl_cluster_number(plan["alpha"], "alpha", 0, 1)
    if not 0 < alpha < 1:
        raise ValueError("alpha must be strictly between 0 and 1")
    minimum = szl_cluster_number(plan["minimum_improvement"], "minimum_improvement")
    expected = plan["expected_cases"]
    if not isinstance(expected, list) or not 1 <= len(expected) <= MAX_ROWS:
        raise ValueError("Expected case membership must contain 1 to 10000 entries")
    membership = {}
    for case in expected:
        szl_cluster_object(case, {"id", "cluster"}, "expected case")
        case_id, cluster = szl_cluster_id(case["id"], "case id"), szl_cluster_id(case["cluster"], "cluster")
        if case_id in membership:
            raise ValueError("Duplicate expected case")
        membership[case_id] = cluster
    clusters = set(membership.values())
    if len(clusters) > MAX_CLUSTERS:
        raise ValueError("At most 16 experimental units are supported")
    plan_digest = canonical_sha256(plan)
    if expected_plan_sha256 is not None:
        if not isinstance(expected_plan_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_plan_sha256):
            raise ValueError("Expected plan digest must be a lowercase SHA-256")
        if expected_plan_sha256 != plan_digest:
            raise ValueError("Expected plan commitment does not match")
    rows = document["rows"]
    if not isinstance(rows, list) or len(rows) != len(membership):
        raise ValueError("Every expected observation must have exactly one retained pair")
    seen, grouped, all_differences = set(), {}, []
    for row in rows:
        szl_cluster_object(row, {"id", "cluster", "unit", "baseline_loss", "candidate_loss"}, "row")
        case_id = szl_cluster_id(row["id"], "row id")
        if case_id in seen or case_id not in membership:
            raise ValueError("Duplicate or unexpected observation")
        if row["cluster"] != membership[case_id]:
            raise ValueError("Observation assigned to a different experimental unit")
        if row["unit"] != plan["unit"]:
            raise ValueError("Mixed or mismatched measurement units")
        difference = szl_cluster_number(row["baseline_loss"], "baseline_loss") - szl_cluster_number(row["candidate_loss"], "candidate_loss")
        grouped.setdefault(row["cluster"], []).append(difference)
        all_differences.append(difference)
        seen.add(case_id)
    means = {name: sum(grouped[name], Fraction()) / len(grouped[name]) for name in sorted(grouped)}
    k = len(means)
    equal_mean = sum(means.values(), Fraction()) / k
    row_mean = sum(all_differences, Fraction()) / len(rows)
    findings, blockers = [], []
    if plan["reported_n"] != k:
        findings.append("REPORTED_N_DIFFERS_FROM_DECLARED_EXPERIMENTAL_UNITS")
    if len(rows) > k:
        findings.append("MULTIPLE_OBSERVATIONS_PER_EXPERIMENTAL_UNIT")
    if (row_mean > 0) != (equal_mean > 0) and row_mean != equal_mean:
        findings.append("ROW_WEIGHTING_CHANGES_POSITIVE_EFFECT_DECISION")
    if expected_plan_sha256 is None:
        blockers.append("EXPECTED_PLAN_COMMITMENT_UNAVAILABLE")
    if not plan["independent_clusters_declared"]:
        blockers.append("INDEPENDENT_CLUSTER_ASSUMPTION_UNDECLARED")
    if plan["sign_flip_basis"] == "undeclared":
        blockers.append("SIGN_FLIP_ASSUMPTION_UNDECLARED")
    if k < minimum_clusters:
        blockers.append("TOO_FEW_DECLARED_EXPERIMENTAL_UNITS")
    leave_one = []
    if k > 1:
        total = sum(means.values(), Fraction())
        for name, value in means.items():
            omitted_mean = (total - value) / (k - 1)
            leave_one.append({"omitted_cluster": name, "mean_improvement": szl_cluster_report_number(omitted_mean),
                              "positive_effect_retained": omitted_mean > 0,
                              "minimum_improvement_retained": omitted_mean >= minimum})
        if equal_mean > 0 and any(not item["positive_effect_retained"] for item in leave_one):
            findings.append("POSITIVE_EFFECT_DEPENDS_ON_ONE_EXPERIMENTAL_UNIT")
        if equal_mean >= minimum and any(not item["minimum_improvement_retained"] for item in leave_one):
            findings.append("MINIMUM_EFFECT_DEPENDS_ON_ONE_EXPERIMENTAL_UNIT")
    test = None if blockers else exact_two_sided(list(means.values()))
    if test is not None:
        test["alpha"] = float(alpha)
        test["within_declared_alpha"] = Fraction(test["extreme_sign_vectors"], test["total_sign_vectors"]) <= alpha
        test["positive_minimum_effect_met"] = equal_mean > 0 and equal_mean >= minimum
        test["conditional_thresholds_met"] = test["within_declared_alpha"] and test["positive_minimum_effect_met"]
        test["assumptions"] = "DECLARED_NOT_VERIFIED"
    return {"schema": SCHEMA, "status": "DESCRIPTIVE_ONLY" if blockers else "CONDITIONAL_CLUSTER_RESULT",
            "plan_sha256": plan_digest, "observations_sha256": canonical_sha256(rows),
            "plan_binding": "MATCHED_COMMITMENT" if expected_plan_sha256 else "UNBOUND",
            "observations": len(rows), "declared_experimental_units": k,
            "experimental_unit": plan["experimental_unit"], "observational_unit": plan["observational_unit"],
            "reported_n": plan["reported_n"], "unit": plan["unit"],
            "equal_cluster_mean_improvement": szl_cluster_report_number(equal_mean),
            "observation_weighted_mean_improvement": szl_cluster_report_number(row_mean),
            "clusters": [{"id": name, "observations": len(grouped[name]), "mean_improvement": szl_cluster_report_number(value)}
                         for name, value in means.items()],
            "leave_one_cluster_out": leave_one, "conditional_exact_test": test,
            "findings": findings, "inference_blockers": blockers,
            "independence_verified": False, "plan_timing_verified": False,
            "scientific_validity": "NOT_ESTABLISHED", "production_authority": "NONE"}


def szl_clustered_replication(document, expected_plan_sha256=None):
    """Audit a complete paired-loss table and return a typed result without mutation."""
    try:
        return szl_cluster_audit(document, expected_plan_sha256)
    except (ValueError, TypeError, OverflowError, UnicodeError, RecursionError) as error:
        return {"schema": SCHEMA, "status": "INPUT_ERROR", "error_type": type(error).__name__,
                "reason": str(error), "conditional_exact_test": None,
                "scientific_validity": "NOT_ESTABLISHED", "production_authority": "NONE"}
