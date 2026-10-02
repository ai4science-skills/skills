"""szl-cross-implementation-check — do two independent implementations agree?

Stdlib only. Offline. Compares two result sets (for example an R script and a
Python notebook that claim to compute the same statistics) and returns one of
three verdicts per quantity and overall, using the vocabulary of the published
szl-crosscheck package:

  CONSISTENT    both report the quantity and |a-b| <= max(atol, rtol*max(|a|,|b|))
  DIVERGENT     both report it and the difference exceeds the declared tolerance
  INCOMPARABLE  only one side reports it, a value is non-finite or non-numeric,
                or the two sides declare different inputs (input digests differ)

Overall: DIVERGENT if any compared quantity diverges; else INCOMPARABLE if any
quantity is incomparable or the inputs differ; else CONSISTENT. Agreement is
evidence that two implementations agree on these inputs; it is not evidence
that either is correct.
"""
from __future__ import annotations

import hashlib
import json
import math

SCHEMA = "szl.cross-implementation-report.v1"


def szl_canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    f = float(value)
    return f if math.isfinite(f) else None


def _flatten(prefix, value, out):
    if isinstance(value, dict):
        for k in sorted(value):
            _flatten(f"{prefix}.{k}" if prefix else str(k), value[k], out)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            _flatten(f"{prefix}[{i}]", v, out)
    else:
        out[prefix] = value
    return out


def _side(label, side):
    if not isinstance(side, dict) or not isinstance(side.get("results"), dict):
        raise ValueError(f"{label}: must be an object with a results object")
    return {
        "label": side.get("label", label),
        "implementation": side.get("implementation"),
        "input_sha256": side.get("input_sha256"),
        "flat": _flatten("", side["results"], {}),
    }


def szl_compare_quantity(name, a, b, atol, rtol) -> dict:
    row = {"quantity": name, "a": a, "b": b, "status": None, "abs_diff": None, "tolerance": None}
    if a is None or b is None:
        row.update(status="INCOMPARABLE", reason="REPORTED_BY_ONE_SIDE_ONLY")
        return row
    fa, fb = _number(a), _number(b)
    if fa is None or fb is None:
        if isinstance(a, str) and isinstance(b, str) or isinstance(a, bool) and isinstance(b, bool):
            row.update(status="CONSISTENT" if a == b else "DIVERGENT", reason="EXACT_COMPARISON")
            return row
        row.update(status="INCOMPARABLE", reason="NON_NUMERIC_OR_NON_FINITE")
        return row
    tol = max(atol, rtol * max(abs(fa), abs(fb)))
    diff = abs(fa - fb)
    row.update(abs_diff=diff, tolerance=tol, status="CONSISTENT" if diff <= tol else "DIVERGENT",
               reason="WITHIN_TOLERANCE" if diff <= tol else "EXCEEDS_TOLERANCE")
    return row


def szl_cross_implementation_check(document) -> dict:
    if not isinstance(document, dict):
        return {"schema": SCHEMA, "status": "ERROR", "reason": "document must be an object"}
    try:
        a = _side("a", document.get("a"))
        b = _side("b", document.get("b"))
    except ValueError as exc:
        return {"schema": SCHEMA, "status": "ERROR", "reason": str(exc)}
    tol = document.get("tolerance", {}) or {}
    atol = float(tol.get("atol", 0.0))
    rtol = float(tol.get("rtol", 0.0))
    if atol < 0 or rtol < 0 or not math.isfinite(atol) or not math.isfinite(rtol):
        return {"schema": SCHEMA, "status": "ERROR", "reason": "tolerances must be finite and non-negative"}
    overrides = document.get("per_quantity_tolerance", {}) or {}
    names = sorted(set(a["flat"]) | set(b["flat"]))
    rows = []
    for name in names:
        o = overrides.get(name, {})
        rows.append(szl_compare_quantity(name, a["flat"].get(name), b["flat"].get(name),
                                         float(o.get("atol", atol)), float(o.get("rtol", rtol))))
    inputs_match = None
    if a["input_sha256"] and b["input_sha256"]:
        inputs_match = a["input_sha256"] == b["input_sha256"]
    statuses = [r["status"] for r in rows]
    if "DIVERGENT" in statuses:
        status = "DIVERGENT"
    elif "INCOMPARABLE" in statuses or inputs_match is False or not rows:
        status = "INCOMPARABLE"
    else:
        status = "CONSISTENT"
    return {
        "schema": SCHEMA,
        "status": status,
        "inputs_match": inputs_match,
        "implementations": [a["implementation"], b["implementation"]],
        "compared": sum(1 for s in statuses if s != "INCOMPARABLE"),
        "consistent": statuses.count("CONSISTENT"),
        "divergent": statuses.count("DIVERGENT"),
        "incomparable": statuses.count("INCOMPARABLE"),
        "tolerance": {"atol": atol, "rtol": rtol},
        "quantities": rows,
        "document_sha256": hashlib.sha256(szl_canonical(document).encode()).hexdigest(),
        "scope": "Agreement between two supplied result sets on declared inputs; correctness of either implementation is not established.",
    }
