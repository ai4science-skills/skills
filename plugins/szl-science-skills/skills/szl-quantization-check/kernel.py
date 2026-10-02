"""szl-quantization-check — does the quantized (or ported, or distilled) model still answer like the reference?

Stdlib only. Offline. No framework; you export the numbers.

Input:
  {
    "kind": "logits" | "embeddings",
    "reference": [[...], ...],   # one row per input example, same order as candidate
    "candidate": [[...], ...],
    "ids": ["ex-1", ...],        # optional row labels
    "temperature": 1.0,          # logits only; softmax temperature before KL
    "tolerances": {"min_cosine": 0.99, "max_kl": 0.02, "min_top1_agreement": 0.98, "max_fraction_below_cosine": 0.05}
  }

Per row: cosine similarity; for logits also KL(softmax(reference) || softmax(candidate)) and top-1
agreement. Aggregates: mean and worst cosine, mean and worst KL, top-1 agreement rate, fraction
of rows below min_cosine. Status WITHIN_TOLERANCE, DEGRADED (a declared tolerance failed),
INCOMPARABLE (shapes differ, non-finite values, empty input), ERROR (malformed input).

What WITHIN_TOLERANCE means: on these inputs the two models agree to the declared degree. It
does not mean the candidate is accurate, safe, or equivalent on inputs you did not include.
"""
from __future__ import annotations

import math

SCHEMA = "szl.quantization-check.v1"
KINDS = ("logits", "embeddings")


def _err(message: str) -> dict:
    return {"status": "ERROR", "error": message}


def _finite_rows(rows, name):
    if not isinstance(rows, list) or not rows:
        return "%s must be a non-empty list of rows" % name
    width = None
    for i, row in enumerate(rows):
        if not isinstance(row, list) or not row:
            return "%s[%d] must be a non-empty list" % (name, i)
        if width is None:
            width = len(row)
        elif len(row) != width:
            return "%s[%d] has %d values, expected %d" % (name, i, len(row), width)
        for v in row:
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                return "%s[%d] contains a non-finite or non-numeric value" % (name, i)
    return None


def szl_cosine(a: list, b: list) -> float | None:
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return None
    return max(-1.0, min(1.0, sum(x * y for x, y in zip(a, b)) / (na * nb)))


def szl_softmax(logits: list, temperature: float) -> list:
    scaled = [v / temperature for v in logits]
    m = max(scaled)
    exps = [math.exp(v - m) for v in scaled]
    total = sum(exps)
    return [e / total for e in exps]


def szl_kl(p: list, q: list) -> float:
    eps = 1e-12
    return sum(pi * math.log((pi + eps) / (qi + eps)) for pi, qi in zip(p, q) if pi > 0.0)


def _argmax(row: list) -> int:
    return max(range(len(row)), key=lambda i: (row[i], -i))


def szl_quantization_check(document: dict) -> dict:
    if not isinstance(document, dict):
        return _err("input must be an object")
    kind = document.get("kind", "logits")
    if kind not in KINDS:
        return _err("kind must be one of %s" % ", ".join(KINDS))
    tol = document.get("tolerances", {}) or {}
    if not isinstance(tol, dict) or any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in tol.values()):
        return _err("tolerances must map names to numbers")
    temperature = document.get("temperature", 1.0)
    if isinstance(temperature, bool) or not isinstance(temperature, (int, float)) or not temperature > 0:
        return _err("temperature must be a positive number")
    ref, cand = document.get("reference"), document.get("candidate")
    for rows, name in ((ref, "reference"), (cand, "candidate")):
        problem = _finite_rows(rows, name)
        if problem:
            return {"status": "INCOMPARABLE", "schema": SCHEMA, "reason": problem}
    if len(ref) != len(cand) or len(ref[0]) != len(cand[0]):
        return {"status": "INCOMPARABLE", "schema": SCHEMA, "reason": "reference is %dx%d, candidate is %dx%d" % (len(ref), len(ref[0]), len(cand), len(cand[0]))}
    ids = document.get("ids") or ["row-%d" % i for i in range(len(ref))]
    if not isinstance(ids, list) or len(ids) != len(ref) or any(not isinstance(x, str) for x in ids):
        return _err("ids must be a list of strings, one per row")
    rows = []
    for rid, a, b in zip(ids, ref, cand):
        cos = szl_cosine(a, b)
        row = {"id": rid, "cosine": cos}
        if cos is None:
            return {"status": "INCOMPARABLE", "schema": SCHEMA, "reason": "row %s has a zero vector; cosine is undefined" % rid}
        if kind == "logits":
            p, q = szl_softmax(a, temperature), szl_softmax(b, temperature)
            row["kl"] = szl_kl(p, q)
            row["top1_reference"], row["top1_candidate"] = _argmax(a), _argmax(b)
            row["top1_agree"] = row["top1_reference"] == row["top1_candidate"]
        rows.append(row)
    n = len(rows)
    agg = {"rows": n, "width": len(ref[0]), "kind": kind, "cosine_mean": sum(r["cosine"] for r in rows) / n, "cosine_min": min(r["cosine"] for r in rows)}
    if kind == "logits":
        agg.update({"kl_mean": sum(r["kl"] for r in rows) / n, "kl_max": max(r["kl"] for r in rows),
                    "top1_agreement": sum(1 for r in rows if r["top1_agree"]) / n, "temperature": temperature})
    if "min_cosine" in tol:
        agg["fraction_below_min_cosine"] = sum(1 for r in rows if r["cosine"] < tol["min_cosine"]) / n
    failed = []
    if "min_cosine" in tol and agg["cosine_min"] < tol["min_cosine"] and "max_fraction_below_cosine" not in tol:
        failed.append("min_cosine: worst row %.6f < %s" % (agg["cosine_min"], tol["min_cosine"]))
    if "max_fraction_below_cosine" in tol and "min_cosine" in tol and agg["fraction_below_min_cosine"] > tol["max_fraction_below_cosine"]:
        failed.append("max_fraction_below_cosine: %.4f > %s" % (agg["fraction_below_min_cosine"], tol["max_fraction_below_cosine"]))
    if kind == "logits":
        if "max_kl" in tol and agg["kl_max"] > tol["max_kl"]:
            failed.append("max_kl: worst row %.6f > %s" % (agg["kl_max"], tol["max_kl"]))
        if "min_top1_agreement" in tol and agg["top1_agreement"] < tol["min_top1_agreement"]:
            failed.append("min_top1_agreement: %.4f < %s" % (agg["top1_agreement"], tol["min_top1_agreement"]))
    elif any(k in tol for k in ("max_kl", "min_top1_agreement")):
        failed.append("max_kl / min_top1_agreement are not defined for embeddings")
    worst = sorted(rows, key=lambda r: r["cosine"])[:5]
    return {"status": "DEGRADED" if failed else "WITHIN_TOLERANCE", "schema": SCHEMA, "aggregate": agg, "tolerances_evaluated": sorted(tol),
            "tolerances_failed": failed, "worst_rows": [r["id"] for r in worst], "per_row": rows,
            "limits": ["Agreement on these inputs only; nothing is implied about inputs not included.",
                       "Agreement with the reference is not accuracy: a wrong reference is matched just as well.",
                       "KL uses softmax at the declared temperature with a 1e-12 floor; rows are compared position by position."]}
