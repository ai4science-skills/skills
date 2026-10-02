"""szl-compute-energy-receipt — a typed energy record for a compute run.

Stdlib only. Offline. Never reads hardware counters itself; it types what you
measured and refuses to round "unknown" up to a number.

Measurement classes (the same three labels used across SZL energy work):
  MEASURED    joules come from a declared on-device counter log (NVML, RAPL,
              a metered plug) with sample timestamps that cover the run
  REPORTED    joules come from a vendor/cloud report or a declared estimate
              (TDP x hours), or from samples with gaps larger than the limit
  UNAVAILABLE no usable energy evidence was supplied

CO2e is derived only when a grid intensity factor with a source is declared,
and is always classed REPORTED (grid factors are published averages).

Output includes a one-sentence methods statement that says exactly what was
and was not measured.
"""
from __future__ import annotations

import hashlib
import json
import math

SCHEMA = "szl.compute-energy-receipt.v1"


def szl_canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _finite(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(float(x))


def _integrate_samples(samples, max_gap_s):
    """samples: [{"t": seconds, "w": watts}], sorted by t. Trapezoidal integration."""
    if not isinstance(samples, list) or len(samples) < 2:
        return None, "FEWER_THAN_TWO_SAMPLES", None
    pts = []
    for s in samples:
        if not isinstance(s, dict) or not _finite(s.get("t")) or not _finite(s.get("w")) or s["w"] < 0:
            return None, "MALFORMED_SAMPLE", None
        pts.append((float(s["t"]), float(s["w"])))
    pts.sort()
    joules, max_gap = 0.0, 0.0
    for (t0, w0), (t1, w1) in zip(pts, pts[1:]):
        dt = t1 - t0
        if dt < 0:
            return None, "NON_MONOTONIC_TIME", None
        max_gap = max(max_gap, dt)
        joules += 0.5 * (w0 + w1) * dt
    duration = pts[-1][0] - pts[0][0]
    if duration <= 0:
        return None, "ZERO_DURATION", None
    cls = "MEASURED" if max_gap <= max_gap_s else "REPORTED"
    return joules, cls, {"samples": len(pts), "duration_s": duration, "max_gap_s": max_gap,
                         "mean_w": joules / duration}


def szl_energy_receipt(document) -> dict:
    if not isinstance(document, dict):
        return {"schema": SCHEMA, "status": "ERROR", "reason": "document must be an object"}
    run = document.get("run", {}) or {}
    meas = document.get("measurement", {}) or {}
    source = meas.get("source")
    max_gap = float(meas.get("max_gap_s", 5.0))
    joules, cls, detail, note = None, "UNAVAILABLE", None, None
    counter_sources = {"nvml", "rapl", "metered_plug", "pdu", "ipmi"}
    if isinstance(meas.get("samples"), list):
        joules, cls_or_reason, detail = _integrate_samples(meas["samples"], max_gap)
        if joules is None:
            cls, note = "UNAVAILABLE", cls_or_reason
        else:
            cls = cls_or_reason if source in counter_sources else "REPORTED"
            if source not in counter_sources:
                note = "SAMPLES_FROM_NON_COUNTER_SOURCE"
            elif cls == "REPORTED":
                note = "SAMPLE_GAP_EXCEEDS_LIMIT"
    elif _finite(meas.get("joules")):
        joules = float(meas["joules"])
        cls = "REPORTED"
        note = "SINGLE_TOTAL_NO_SAMPLES" if source in counter_sources else "VENDOR_OR_ESTIMATE"
    elif _finite(meas.get("tdp_w")) and _finite(run.get("duration_s")):
        joules = float(meas["tdp_w"]) * float(run["duration_s"])
        cls, note = "REPORTED", "TDP_TIMES_DURATION_ESTIMATE"
    else:
        note = "NO_ENERGY_EVIDENCE"
    kwh = joules / 3.6e6 if joules is not None else None

    grid = document.get("grid", {}) or {}
    co2e_g, co2_class, co2_note = None, "UNAVAILABLE", "NO_GRID_FACTOR"
    if kwh is not None and _finite(grid.get("g_co2e_per_kwh")) and isinstance(grid.get("source"), str) and grid["source"]:
        co2e_g = kwh * float(grid["g_co2e_per_kwh"])
        co2_class, co2_note = "REPORTED", "PUBLISHED_AVERAGE_FACTOR"
    elif kwh is not None and _finite(grid.get("g_co2e_per_kwh")):
        co2_note = "GRID_FACTOR_WITHOUT_SOURCE_IGNORED"

    hw = run.get("hardware") or "unspecified hardware"
    if cls == "UNAVAILABLE":
        sentence = f"Energy consumption of this run on {hw} was not measured and is reported as UNAVAILABLE."
    else:
        if cls == "MEASURED":
            how = f"measured via {source} power sampling ({detail['samples']} samples over {detail['duration_s']:g} s)"
        else:
            how = f"reported ({(note or 'declared').lower().replace('_', ' ')})"
        sentence = f"The run on {hw} consumed {kwh:.3f} kWh ({joules:.0f} J), {how}."
        if co2e_g is not None:
            sentence += f" Applying the declared grid factor of {float(grid['g_co2e_per_kwh']):g} gCO2e/kWh ({grid['source']}) gives {co2e_g:.0f} gCO2e (REPORTED, not measured)."
        else:
            sentence += " No grid intensity factor was declared, so no CO2e figure is reported."

    body = {"schema": SCHEMA, "run": {"id": run.get("id"), "hardware": hw, "duration_s": run.get("duration_s"),
                                        "purpose": run.get("purpose")},
            "energy": {"joules": joules, "kwh": kwh, "class": cls, "source": source, "note": note, "detail": detail},
            "co2e": {"grams": co2e_g, "class": co2_class, "note": co2_note,
                     "grid_factor": grid.get("g_co2e_per_kwh"), "grid_source": grid.get("source")},
            "methods_sentence": sentence,
            "scope": "Types the supplied energy evidence. Does not read counters, does not estimate embodied emissions, and does not compare efficiency across runs."}
    body["receipt_sha256"] = hashlib.sha256(szl_canonical(body).encode()).hexdigest()
    body["status"] = cls
    return body
