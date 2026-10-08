# SPDX-License-Identifier: Apache-2.0
# Modified 2026-09-30: add an offline theorem/assumption/runtime scope audit.
"""Numerical investigation does not discharge mathematical proofs."""
import hashlib
import json
import math
import re


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


def szl_scope_text(value, field, limit=65536):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(field + " must be a bounded nonempty string")
    return value


def szl_scope_hash(value, field):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError(field + " must be a lowercase SHA-256")
    return value


def szl_scope_ids(value, field):
    if not isinstance(value, list) or len(value) > 256:
        raise ValueError(field + " must be a list with at most 256 entries")
    result = [szl_scope_text(item, field, 256) for item in value]
    if len(set(result)) != len(result):
        raise ValueError(field + " contains duplicate entries")
    return set(result)


def szl_scope_endpoint(value):
    """Keep integer endpoints exact; floats retain their supplied binary64 value."""
    if type(value) is int or (type(value) is float and math.isfinite(value)):
        return value
    raise ValueError("Expected a finite integer or float interval endpoint")


def szl_scope_domain(value):
    if not isinstance(value, dict) or not value or len(value) > 64:
        raise ValueError("domain must contain 1 to 64 named intervals")
    result = {}
    for variable, interval in value.items():
        szl_scope_text(variable, "domain variable", 128)
        if not isinstance(interval, dict) or set(interval) != {"lower", "upper", "lower_inclusive", "upper_inclusive"}:
            raise ValueError("Each domain interval needs lower/upper and inclusive flags")
        low, high = interval["lower"], interval["upper"]
        if low is not None:
            low = szl_scope_endpoint(low)
        if high is not None:
            high = szl_scope_endpoint(high)
        li, ui = interval["lower_inclusive"], interval["upper_inclusive"]
        if type(li) is not bool or type(ui) is not bool:
            raise ValueError("Interval inclusive flags must be booleans")
        if (low is None and li) or (high is None and ui):
            raise ValueError("Unbounded endpoints cannot be inclusive")
        if low is not None and high is not None and (low > high or (low == high and not (li and ui))):
            raise ValueError("Domain interval is empty or reversed")
        result[variable] = (low, high, li, ui)
    return result


def szl_scope_subset(inner, outer):
    if set(inner) != set(outer):
        return False
    for key in inner:
        lo, hi, li, ui = inner[key]
        base_lo, base_hi, base_li, base_ui = outer[key]
        if base_lo is not None and (lo is None or lo < base_lo or (lo == base_lo and li and not base_li)):
            return False
        if base_hi is not None and (hi is None or hi > base_hi or (hi == base_hi and ui and not base_ui)):
            return False
    return True


def szl_audit_math_scope(contract):
    """Check supplied record bindings and declared scope; never execute a prover."""
    if not isinstance(contract, dict) or contract.get("schema") != "szl.math-claim-scope.v1":
        raise ValueError("Expected szl.math-claim-scope.v1")
    encoded = json.dumps(contract, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    if len(encoded) > 8 * 1024 * 1024:
        raise ValueError("Scope contract exceeds 8 MiB")
    claim, theorem, runtime = (contract.get(key) for key in ("claim", "theorem", "runtime"))
    if any(not isinstance(item, dict) for item in (claim, theorem, runtime)):
        raise ValueError("claim, theorem and runtime must be objects")
    statement = szl_scope_text(claim.get("statement"), "claim.statement")
    proposition = szl_scope_text(theorem.get("proposition"), "theorem.proposition")
    statement_digest = hashlib.sha256(statement.encode()).hexdigest()
    proposition_digest = hashlib.sha256(proposition.encode()).hexdigest()
    symbol = szl_scope_text(theorem.get("symbol"), "theorem.symbol", 256)
    source_hash = szl_scope_hash(theorem.get("source_sha256"), "theorem.source_sha256")
    runtime_hash = szl_scope_hash(runtime.get("source_sha256"), "runtime.source_sha256")
    compiler = szl_scope_hash(theorem.get("toolchain_sha256"), "theorem.toolchain_sha256")
    lock = szl_scope_hash(theorem.get("dependency_lock_sha256"), "theorem.dependency_lock_sha256")
    assumptions = szl_scope_ids(theorem.get("assumptions"), "theorem.assumptions")
    runtime_assumptions = szl_scope_ids(runtime.get("assumptions"), "runtime.assumptions")
    allowed_axioms = szl_scope_ids(contract.get("allowed_axioms", []), "allowed_axioms")
    theorem_domain, runtime_domain = szl_scope_domain(theorem.get("domain")), szl_scope_domain(runtime.get("domain"))
    relations = {"equal", "le", "ge", "implies", "iff"}
    if any(not isinstance(item.get("relation"), str) or item["relation"] not in relations for item in (claim, theorem, runtime)):
        raise ValueError("Relations must be equal, le, ge, implies or iff")
    semantics = runtime.get("numeric_semantics")
    if not isinstance(semantics, str) or semantics not in {"integer", "rational", "binary64", "symbolic"}:
        raise ValueError("Unknown runtime numeric_semantics")
    findings = []
    if not assumptions <= runtime_assumptions:
        findings.append({"severity": "BLOCKED", "code": "MISSING_RUNTIME_ASSUMPTIONS", "items": sorted(assumptions - runtime_assumptions)})
    if not szl_scope_subset(runtime_domain, theorem_domain):
        findings.append({"severity": "BLOCKED", "code": "RUNTIME_OUTSIDE_THEOREM_DOMAIN"})
    if claim["relation"] != theorem["relation"]:
        findings.append({"severity": "BLOCKED", "code": "CLAIM_RELATION_NOT_ESTABLISHED"})
    if runtime["relation"] != theorem["relation"]:
        findings.append({"severity": "BLOCKED", "code": "RUNTIME_RELATION_MISMATCH"})
    observed = contract.get("observed_artifacts", {})
    if not isinstance(observed, dict) or set(observed) - {"formal_source", "runtime_source", "toolchain", "dependency_lock"}:
        raise ValueError("Unknown observed artifact binding")
    for key, expected in (("formal_source", source_hash), ("runtime_source", runtime_hash), ("toolchain", compiler), ("dependency_lock", lock)):
        if key not in observed:
            findings.append({"severity": "UNKNOWN", "code": "ARTIFACT_NOT_OBSERVED", "artifact": key})
        elif szl_scope_hash(observed[key], "observed_artifacts." + key) != expected:
            findings.append({"severity": "BLOCKED", "code": "ARTIFACT_DIGEST_MISMATCH", "artifact": key})
    proof = contract.get("proof_record")
    log_digest = None
    if proof is None:
        findings.append({"severity": "UNKNOWN", "code": "MISSING_PROOF_LOG"})
    else:
        if not isinstance(proof, dict):
            raise ValueError("proof_record must be an object")
        log = szl_scope_text(proof.get("log"), "proof_record.log")
        log_digest = hashlib.sha256(log.encode()).hexdigest()
        if szl_scope_hash(proof.get("log_sha256"), "proof_record.log_sha256") != log_digest:
            findings.append({"severity": "BLOCKED", "code": "PROOF_LOG_DIGEST_MISMATCH"})
        if type(proof.get("exit_code")) is not int:
            raise ValueError("Proof exit_code must be an integer")
        if proof["exit_code"] != 0:
            findings.append({"severity": "BLOCKED", "code": "PROOF_TOOL_REPORTED_FAILURE"})
        for key, expected in (("theorem_symbol", symbol), ("proposition_sha256", proposition_digest), ("source_sha256", source_hash), ("toolchain_sha256", compiler), ("dependency_lock_sha256", lock)):
            actual = proof.get(key)
            if key == "theorem_symbol":
                szl_scope_text(actual, "proof_record." + key, 256)
            else:
                szl_scope_hash(actual, "proof_record." + key)
            if actual != expected:
                findings.append({"severity": "BLOCKED", "code": "PROOF_RECORD_BINDING_MISMATCH", "field": key})
        for flag in ("contains_sorry", "contains_admit"):
            if type(proof.get(flag)) is not bool:
                raise ValueError(flag + " must be a boolean observation")
            if proof[flag]:
                findings.append({"severity": "BLOCKED", "code": "UNFINISHED_PROOF", "field": flag})
        axioms = szl_scope_ids(proof.get("transitive_axioms"), "proof_record.transitive_axioms")
        custom = szl_scope_ids(proof.get("custom_axioms"), "proof_record.custom_axioms")
        if custom:
            findings.append({"severity": "BLOCKED", "code": "CUSTOM_AXIOMS", "items": sorted(custom)})
        if axioms - allowed_axioms:
            findings.append({"severity": "BLOCKED", "code": "UNREVIEWED_TRANSITIVE_AXIOMS", "items": sorted(axioms - allowed_axioms)})
    correspondence = contract.get("correspondence")
    if correspondence is None:
        findings.append({"severity": "UNKNOWN", "code": "CORRESPONDENCE_NOT_REVIEWED"})
    else:
        if not isinstance(correspondence, dict):
            raise ValueError("correspondence must be an object")
        for key, expected in (("statement_sha256", statement_digest), ("proposition_sha256", proposition_digest), ("runtime_source_sha256", runtime_hash)):
            if szl_scope_hash(correspondence.get(key), "correspondence." + key) != expected:
                findings.append({"severity": "BLOCKED", "code": "CORRESPONDENCE_BINDING_MISMATCH", "field": key})
        szl_scope_text(correspondence.get("reviewer"), "correspondence.reviewer", 256)
        szl_scope_hash(correspondence.get("evidence_sha256"), "correspondence.evidence_sha256")
        for key in ("informal_to_formal", "formal_to_runtime"):
            if not isinstance(correspondence.get(key), str) or correspondence[key] not in {"REVIEWED", "NOT_REVIEWED"}:
                raise ValueError("Correspondence status must be REVIEWED or NOT_REVIEWED")
            if correspondence[key] != "REVIEWED":
                findings.append({"severity": "UNKNOWN", "code": "CORRESPONDENCE_NOT_REVIEWED", "field": key})
        numeric = correspondence.get("numeric_semantics_reviewed")
        if type(numeric) is not bool:
            raise ValueError("numeric_semantics_reviewed must be boolean")
        if semantics == "binary64" and not numeric:
            findings.append({"severity": "UNKNOWN", "code": "FLOATING_POINT_BOUNDARY_NOT_REVIEWED"})
    findings.sort(key=lambda item: json.dumps(item, sort_keys=True))
    status = "BLOCKED" if any(item["severity"] == "BLOCKED" for item in findings) else "UNKNOWN" if findings else "STRUCTURAL_CHECKS_PASSED"
    return {"schema": "szl.math-claim-scope-report.v1", "status": status, "findings": findings,
            "statement_sha256": statement_digest, "proposition_sha256": proposition_digest,
            "supplied_log_sha256": log_digest, "input_sha256": hashlib.sha256(encoded).hexdigest(),
            "proof_discharged": False, "authentic": False, "scientific_evaluation": "NOT_MEASURED",
            "execution_authority": "none", "limitation": "Checks caller-supplied records and interval scope; no prover invocation, log authentication, semantic theorem equivalence or proof certification."}
