"""Offline, byte-bound audit of a declared family of hypothesis tests.

This computes Holm FWER or Benjamini-Hochberg FDR adjustments on a complete
supplied family. It does not verify raw p-values, preregistration, dependence,
scientific validity, or whether unreported analyses exist.
"""
from __future__ import annotations

import hashlib
import json
import re
from decimal import Context, Decimal, DecimalException, InvalidOperation, Underflow, localcontext


PLAN_SCHEMA = "szl.multiplicity.plan.v1"
RESULTS_SCHEMA = "szl.multiplicity.results.v1"
MAX_BYTES = 1_000_000
MAX_TESTS = 1_000
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
NUMBER = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
LIMITS = [
    "A digest binds the supplied plan bytes, but does not prove when the plan was fixed.",
    "The audit cannot detect analyses, outcomes or p-values omitted from both supplied files.",
    "Raw p-values, study design, dependence assumptions and scientific claims are not validated.",
]


def szl_unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key: " + key)
        result[key] = value
    return result


def szl_bad_constant(value):
    raise ValueError("non-finite JSON number: " + value)


def szl_read_json(data, name):
    if not isinstance(data, bytes) or len(data) > MAX_BYTES:
        raise ValueError(name + " must be bytes of at most 1,000,000 bytes")
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=szl_unique_pairs,
                           parse_float=Decimal, parse_constant=szl_bad_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError(name + " is not UTF-8 JSON: " + str(error)) from error
    if not isinstance(value, dict):
        raise ValueError(name + " must be a JSON object")
    return value


def szl_id(value, name):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError(name + " must be a nonempty simple identifier, at most 64 characters")
    return value


def szl_probability(value, name, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError(name + " must be a decimal string or JSON number")
    literal = str(value)
    if len(literal) > 80 or not NUMBER.fullmatch(literal):
        raise ValueError(name + " must be a finite nonnegative decimal, at most 80 characters")
    try:
        number = Decimal(literal)
    except InvalidOperation as error:
        raise ValueError(name + " is not a decimal") from error
    # Decimal's default Emin is finite. Extreme exponents can silently
    # underflow a nonzero adjusted p-value to zero during multiplication.
    if abs(number.as_tuple().exponent) > 1_000:
        raise ValueError(name + " exponent exceeds the supported range")
    if not (Decimal(0) < number < Decimal(1) if positive else Decimal(0) <= number <= Decimal(1)):
        raise ValueError(name + " is outside its allowed range")
    return number


def szl_report(status, family_id, method, plan_digest, results_digest, planned_ids, observed_ids, findings):
    return {
        "status": status, "family_id": family_id, "method": method,
        "plan_sha256_readback": plan_digest, "results_sha256_readback": results_digest,
        "planned_count": len(planned_ids), "observed_count": len(observed_ids),
        "missing_ids": sorted(set(planned_ids) - set(observed_ids)),
        "extra_ids": sorted(set(observed_ids) - set(planned_ids)),
        "findings": sorted(set(findings)), "adjusted": [], "limits": LIMITS,
    }


def szl_audit_multiplicity(plan_bytes: bytes, results_bytes: bytes) -> dict:
    """Audit one entire declared family; never adjust a partial family."""
    try:
        plan = szl_read_json(plan_bytes, "plan")
        results = szl_read_json(results_bytes, "results")
        if plan.get("schema") != PLAN_SCHEMA or results.get("schema") != RESULTS_SCHEMA:
            raise ValueError("unsupported plan or results schema")
        family_id = szl_id(plan.get("family_id"), "plan family_id")
        szl_id(results.get("family_id"), "results family_id")
        method = plan.get("method")
        if method not in ("holm", "bh"):
            raise ValueError("method must be holm or bh")
        alpha = szl_probability(plan.get("alpha"), "alpha", positive=True)
        hypotheses = plan.get("hypotheses")
        if not isinstance(hypotheses, list) or not 1 <= len(hypotheses) <= MAX_TESTS:
            raise ValueError("hypotheses must contain 1 to 1,000 entries")
        planned_ids = []
        for item in hypotheses:
            if not isinstance(item, dict):
                raise ValueError("each hypothesis must be an object")
            planned_ids.append(szl_id(item.get("id"), "hypothesis id"))
            description = item.get("description")
            if not isinstance(description, str) or not description.strip() or len(description) > 500:
                raise ValueError("each hypothesis needs a description of at most 500 characters")
        if len(set(planned_ids)) != len(planned_ids):
            raise ValueError("duplicate hypothesis id")
        rows = results.get("results")
        if not isinstance(rows, list) or len(rows) > MAX_TESTS:
            raise ValueError("results must be a list of at most 1,000 entries")
        observed_ids, raw, findings = [], {}, []
        for item in rows:
            if not isinstance(item, dict):
                raise ValueError("each result must be an object")
            key = szl_id(item.get("id"), "result id")
            observed_ids.append(key)
            if key in raw:
                findings.append("DUPLICATE_RESULT_ID")
            value = item.get("p_value")
            if value is None:
                findings.append("MISSING_P_VALUE")
            else:
                raw[key] = szl_probability(value, "p_value for " + key)
        attempts = results.get("extra_attempts")
        if not isinstance(attempts, list) or len(attempts) > MAX_TESTS:
            raise ValueError("extra_attempts must be a list of at most 1,000 ids")
        for attempt in attempts:
            szl_id(attempt, "extra attempt id")
        if attempts:
            findings.append("EXTRA_ANALYSIS_ATTEMPTS")
        recorded_digest = results.get("plan_sha256")
        if not isinstance(recorded_digest, str) or not SHA256.fullmatch(recorded_digest):
            raise ValueError("results plan_sha256 must be lowercase SHA-256")
        plan_digest = hashlib.sha256(plan_bytes).hexdigest()
        results_digest = hashlib.sha256(results_bytes).hexdigest()
        if recorded_digest != plan_digest:
            findings.append("PLAN_DIGEST_MISMATCH")
        if results["family_id"] != family_id:
            findings.append("FAMILY_ID_MISMATCH")
        if set(planned_ids) - set(observed_ids):
            findings.append("MISSING_PLANNED_RESULTS")
        if set(observed_ids) - set(planned_ids):
            findings.append("UNPLANNED_RESULTS")
        if method == "bh" and plan.get("dependence_assumption") not in (
            "independent", "positive_regression_dependency"
        ):
            findings.append("BH_DEPENDENCE_NOT_DECLARED")
        report = szl_report("HOLD" if findings else "COMPLETE", family_id, method,
                         plan_digest, results_digest, planned_ids, observed_ids, findings)
        report["alpha"] = str(alpha)
        report["extra_attempts"] = attempts
        if findings:
            return report
        ordered = sorted(((raw[key], key) for key in planned_ids), key=lambda row: (row[0], row[1]))
        count = len(ordered)
        adjusted = {}
        # Do not inherit the embedding agent's Decimal context: a narrow Emin
        # or Inexact trap could otherwise change decisions or crash BH division.
        with localcontext(Context(prec=96, Emin=-999999, Emax=999999)) as context:
            context.traps[Underflow] = True
            if method == "holm":
                running = Decimal(0)
                for rank, (value, key) in enumerate(ordered):
                    running = max(running, min(Decimal(1), value * (count - rank)))
                    adjusted[key] = running
            else:
                running = Decimal(1)
                for rank in range(count - 1, -1, -1):
                    value, key = ordered[rank]
                    running = min(running, Decimal(1), value * count / (rank + 1))
                    adjusted[key] = running
        report["adjusted"] = [
            {"id": key, "raw_p_value": str(raw[key]),
             "adjusted_p_value": str(adjusted[key]), "reject_at_alpha": adjusted[key] <= alpha}
            for key in planned_ids
        ]
        report["rejections"] = sum(row["reject_at_alpha"] for row in report["adjusted"])
        report["family_decision"] = "REJECTIONS_PRESENT" if report["rejections"] else "NO_REJECTIONS"
        if method == "bh":
            report["dependence_assumption_as_declared"] = plan["dependence_assumption"]
        return report
    except (ValueError, DecimalException) as error:
        return {"status": "ERROR", "error": str(error), "adjusted": [], "limits": LIMITS}
