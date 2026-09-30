# SPDX-License-Identifier: Apache-2.0
"""Compare outputs and declared timing evidence. No remote code loading."""
import hashlib
import json
import math
import re
import statistics
import time


def szl_numeric_shape(value):
    if isinstance(value, (list, tuple)):
        shapes = [szl_numeric_shape(v) for v in value]
        if shapes and any(s != shapes[0] for s in shapes):
            raise ValueError("Ragged array")
        return [len(value)] + ([] if not shapes else shapes[0])
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Outputs must contain finite numbers")
    return []


def szl_numeric_flatten(value):
    if isinstance(value, (list, tuple)):
        out = []
        for item in value:
            out.extend(szl_numeric_flatten(item))
        return out
    return [float(value)]


def szl_compare_kernel_runs(record):
    ref, cand = record["reference_output"], record["candidate_output"]
    shape = szl_numeric_shape(ref)
    if szl_numeric_shape(cand) != shape:
        raise ValueError("Output shapes differ")
    xs, ys = szl_numeric_flatten(ref), szl_numeric_flatten(cand)
    if not xs:
        raise ValueError("Cannot qualify empty outputs")
    atol, rtol = record["atol"], record["rtol"]
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in (atol, rtol)):
        raise ValueError("Declare finite nonnegative tolerances")
    errors = [abs(x - y) for x, y in zip(xs, ys)]
    limits = [atol + rtol * abs(x) for x in xs]
    if any(not math.isfinite(v) for v in errors + limits):
        raise ValueError("Difference or tolerance overflow; use a suitable numerical representation")
    bad = [i for i, (error, limit) in enumerate(zip(errors, limits)) if error > limit]
    context = record.get("reference_context")
    required = {"hardware", "dtype", "input_sha256", "threads", "warmup", "synchronized", "measurement_method"}
    same = isinstance(context, dict) and required <= context.keys() and all(context[k] is not None for k in required) and context == record.get("candidate_context")
    if same:
        same = (all(isinstance(context[k], str) and bool(context[k].strip()) for k in ("hardware", "dtype", "measurement_method"))
                and isinstance(context["input_sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", context["input_sha256"]) is not None
                and type(context["threads"]) is int and context["threads"] > 0
                and type(context["warmup"]) is int and context["warmup"] >= 0
                and context["synchronized"] is True)
    times = []
    for key in ("reference_seconds", "candidate_seconds"):
        values = record.get(key)
        if values is None:
            times.append(None)
        elif not isinstance(values, list) or len(values) < 3 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 for v in values):
            raise ValueError("Timings require at least three positive durations")
        else:
            times.append(values)
    speedup = None
    if not bad and same and all(v is not None for v in times):
        speedup = statistics.median(times[0]) / statistics.median(times[1])
    digest = hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return {"status": "NUMERICAL_MISMATCH" if bad else "AGREEMENT_ON_SUPPLIED_OUTPUTS",
            "shape": shape, "elements": len(xs), "mismatch_indexes": bad[:100], "mismatch_count": len(bad),
            "max_absolute_error": max(errors), "atol": atol, "rtol": rtol,
            "timing_contexts_match": same, "median_speedup": speedup,
            "timing_source": "CALLER_SUPPLIED", "timing_verified": False, "input_sha256": digest,
            "energy_joules": None, "scope": "Supplied outputs and timings only; no CUDA or general acceleration claim"}


def szl_time_callable(function, warmup=3, repeats=9, synchronize=None):
    if not callable(function) or type(warmup) is not int or type(repeats) is not int or warmup < 0 or not 3 <= repeats <= 10000:
        raise ValueError("Supply a callable, nonnegative warmup, and 3..10000 repeats")
    if synchronize is not None and not callable(synchronize):
        raise ValueError("synchronize must be callable")
    for i in range(warmup):
        function()
    samples = []
    for i in range(repeats):
        if synchronize is not None:
            synchronize()
        start = time.perf_counter()
        function()
        if synchronize is not None:
            synchronize()
        samples.append(time.perf_counter() - start)
    return {"seconds": samples, "median_seconds": statistics.median(samples),
            "warmup": warmup, "repeats": repeats, "synchronize_callback_used": synchronize is not None,
            "energy_joules": None, "measurement_method": "perf_counter"}
