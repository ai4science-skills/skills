"""szl-result-fragility — how many patients would have to change outcome before this result flips?

Stdlib only. Offline. Exact arithmetic with math.comb; no approximations.

Input:
  {
    "arms": {"treatment": {"events": 12, "total": 100}, "control": {"events": 25, "total": 100}},
    "alpha": 0.05,
    "lost_to_follow_up": 7,          # optional; compared with the fragility index
    "label": "primary endpoint: 30-day mortality"
  }

Fisher's exact test (two-sided, sum of table probabilities <= the observed) on the 2x2 table.
If p < alpha: the fragility index (Walsh et al. 2014) is the smallest number of participants in the
arm with fewer events whose outcome would have to change from non-event to event for p to reach
alpha; the fragility quotient divides it by the total sample. If p >= alpha: the reverse fragility
index is the smallest number of single-participant outcome changes (any arm, either direction)
that would make p < alpha.

Status: FRAGILE when significant and the fragility index is <= lost_to_follow_up (or <= the
declared threshold), ROBUST when significant and above it, NOT_SIGNIFICANT with the reverse index
otherwise, ERROR for malformed counts.

What FRAGILE means: fewer outcome changes than there were participants lost to follow-up would
remove statistical significance. It is a statement about the table, not about the biology, the
effect size, or the study's design.
"""
from __future__ import annotations

import math

SCHEMA = "szl.result-fragility.v1"


def _err(message: str) -> dict:
    return {"status": "ERROR", "error": message}


def szl_fisher_two_sided(a: int, b: int, c: int, d: int) -> float:
    """2x2 table [[a, b], [c, d]] with rows = arms, columns = (events, non-events)."""
    n = a + b + c + d
    row1, col1 = a + b, a + c
    if n == 0 or row1 == 0 or row1 == n or col1 == 0 or col1 == n:
        return 1.0
    total = math.comb(n, col1)

    def prob(x):
        if x < 0 or x > row1 or col1 - x < 0 or col1 - x > n - row1:
            return 0.0
        return math.comb(row1, x) * math.comb(n - row1, col1 - x) / total
    observed = prob(a)
    tolerance = observed * 1e-9
    return min(1.0, sum(p for p in (prob(x) for x in range(0, row1 + 1)) if p <= observed + tolerance))


def _p(arms):
    t, c = arms["treatment"], arms["control"]
    return szl_fisher_two_sided(t["events"], t["total"] - t["events"], c["events"], c["total"] - c["events"])


def szl_fragility_index(arms: dict, alpha: float) -> dict:
    """Walsh fragility index: flip non-events to events in the arm with fewer events until p >= alpha."""
    arm = "treatment" if arms["treatment"]["events"] <= arms["control"]["events"] else "control"
    work = {k: dict(v) for k, v in arms.items()}
    flips, p = 0, _p(work)
    while p < alpha and work[arm]["events"] < work[arm]["total"]:
        work[arm]["events"] += 1
        flips += 1
        p = _p(work)
    return {"fragility_index": flips if p >= alpha else None, "arm_modified": arm, "p_after": p,
            "exhausted": p < alpha}


def szl_reverse_fragility_index(arms: dict, alpha: float) -> dict:
    """Smallest number of single-participant outcome changes (any arm, either direction) that makes p < alpha."""
    best = None
    for arm in ("treatment", "control"):
        for direction in (+1, -1):
            work = {k: dict(v) for k, v in arms.items()}
            flips, p = 0, _p(work)
            while p >= alpha:
                nxt = work[arm]["events"] + direction
                if nxt < 0 or nxt > work[arm]["total"]:
                    break
                work[arm]["events"] = nxt
                flips += 1
                p = _p(work)
            if p < alpha and (best is None or flips < best["reverse_fragility_index"]):
                best = {"reverse_fragility_index": flips, "arm_modified": arm, "direction": "non-event to event" if direction > 0 else "event to non-event", "p_after": p}
    return best or {"reverse_fragility_index": None, "note": "no sequence of single-arm changes reaches significance"}


def szl_result_fragility(document: dict) -> dict:
    if not isinstance(document, dict) or not isinstance(document.get("arms"), dict):
        return _err("input needs an arms object with treatment and control")
    arms = document["arms"]
    for name in ("treatment", "control"):
        arm = arms.get(name)
        if not isinstance(arm, dict):
            return _err("arms.%s must be an object with events and total" % name)
        for key in ("events", "total"):
            v = arm.get(key)
            if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                return _err("arms.%s.%s must be a non-negative integer" % (name, key))
        if arm["events"] > arm["total"] or arm["total"] == 0:
            return _err("arms.%s: events must not exceed total and total must be positive" % name)
    alpha = document.get("alpha", 0.05)
    if isinstance(alpha, bool) or not isinstance(alpha, (int, float)) or not 0 < alpha < 1:
        return _err("alpha must be a number strictly between 0 and 1")
    ltfu = document.get("lost_to_follow_up")
    if ltfu is not None and (isinstance(ltfu, bool) or not isinstance(ltfu, int) or ltfu < 0):
        return _err("lost_to_follow_up must be a non-negative integer when given")
    threshold = document.get("fragile_if_index_at_most")
    if threshold is not None and (isinstance(threshold, bool) or not isinstance(threshold, int) or threshold < 0):
        return _err("fragile_if_index_at_most must be a non-negative integer when given")
    t, c = arms["treatment"], arms["control"]
    n = t["total"] + c["total"]
    p = _p(arms)
    risk_t, risk_c = t["events"] / t["total"], c["events"] / c["total"]
    out = {"status": None, "schema": SCHEMA, "label": document.get("label", ""), "n": n, "alpha": alpha, "fisher_p_two_sided": p,
           "risk_treatment": risk_t, "risk_control": risk_c, "risk_difference": risk_t - risk_c,
           "risk_ratio": (risk_t / risk_c) if risk_c > 0 else None, "lost_to_follow_up": ltfu}
    if p < alpha:
        fi = szl_fragility_index(arms, alpha)
        out.update(fi)
        out["fragility_quotient"] = (fi["fragility_index"] / n) if fi["fragility_index"] is not None else None
        reasons = []
        if fi["fragility_index"] is None:
            out["status"] = "ROBUST"
            reasons.append("every non-event in the %s arm was flipped and p stayed below alpha" % fi["arm_modified"])
        else:
            fragile = False
            if ltfu is not None and fi["fragility_index"] <= ltfu:
                fragile = True
                reasons.append("fragility index %d <= %d lost to follow-up" % (fi["fragility_index"], ltfu))
            if threshold is not None and fi["fragility_index"] <= threshold:
                fragile = True
                reasons.append("fragility index %d <= declared threshold %d" % (fi["fragility_index"], threshold))
            if ltfu is None and threshold is None:
                reasons.append("no lost_to_follow_up or threshold declared; the index is reported without a FRAGILE/ROBUST judgment")
                out["status"] = "SIGNIFICANT_UNJUDGED"
            else:
                out["status"] = "FRAGILE" if fragile else "ROBUST"
        out["reasons"] = reasons
    else:
        out.update(szl_reverse_fragility_index(arms, alpha))
        out["status"] = "NOT_SIGNIFICANT"
        out["reasons"] = ["p = %.4f >= alpha" % p]
    out["limits"] = ["Fisher's exact test on the 2x2 table only; adjusted or time-to-event analyses are not represented.",
                     "The fragility index describes the table, not the effect size, the design or the biology.",
                     "Flipping outcomes is a thought experiment; it does not model who was lost or why."]
    return out
