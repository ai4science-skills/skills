# SPDX-License-Identifier: Apache-2.0
"""Numerical investigation does not discharge mathematical proofs."""
import hashlib
import json
import math


def szl_math_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Expected a finite real number")
    return float(value)


def szl_weighted_geomean(axes, weights=None):
    if not isinstance(axes, (list, tuple)) or not axes:
        raise ValueError("axes must be nonempty")
    xs = [szl_math_number(x) for x in axes]
    ws = [1.0 / len(xs)] * len(xs) if weights is None else [szl_math_number(w) for w in weights]
    if len(ws) != len(xs) or any(x < 0 or x > 1 for x in xs) or any(w < 0 for w in ws):
        raise ValueError("axes must lie in [0,1]; weights must be nonnegative and match")
    if not math.isclose(math.fsum(ws), 1.0, rel_tol=0, abs_tol=1e-12):
        raise ValueError("weights must sum to 1")
    if any(x == 0 and w > 0 for x, w in zip(xs, ws)):
        return 0.0
    return math.exp(math.fsum(w * math.log(x) for x, w in zip(xs, ws) if w > 0))


def szl_check_math_cases(claim, cases, relation="equal", atol=1e-12, rtol=1e-9):
    if not isinstance(claim, str) or not claim.strip() or not isinstance(cases, list) or not cases:
        raise ValueError("Supply a claim and nonempty observed cases")
    if relation not in {"equal", "le", "ge"}:
        raise ValueError("relation must be equal, le, or ge")
    a, r = szl_math_number(atol), szl_math_number(rtol)
    if a < 0 or r < 0:
        raise ValueError("Negative tolerance")
    failures = []
    for i, case in enumerate(cases):
        lhs, rhs = szl_math_number(case["lhs"]), szl_math_number(case["rhs"])
        margin = a + r * abs(rhs)
        ok = abs(lhs - rhs) <= margin if relation == "equal" else lhs <= rhs + margin if relation == "le" else lhs >= rhs - margin
        if not ok:
            failures.append({"case": i, "inputs": case.get("inputs"), "lhs": lhs, "rhs": rhs})
    record = {"claim": claim, "cases": cases, "relation": relation, "atol": a, "rtol": r}
    digest = hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return {"status": "NUMERICAL_COUNTEREXAMPLE" if failures else "NO_COUNTEREXAMPLE_IN_TESTED_CASES",
            "case_count": len(cases), "failures": failures, "input_sha256": digest,
            "proof_discharged": False, "lambda_status": "Conjecture 1 (OPEN)",
            "interpretation": "Floating-point observations under declared tolerances; inspect exact arithmetic and assumptions before mathematical refutation."}
