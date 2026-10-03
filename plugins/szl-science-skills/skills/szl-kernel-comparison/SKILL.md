---
name: szl-kernel-comparison
description: "Compares a candidate numerical implementation against a reference on identical inputs: shape agreement, finite values, elementwise tolerance, and a median speedup only when both timings were taken under declared identical conditions. Use when the user claims a faster or GPU-accelerated kernel, a vectorized rewrite, a new solver or a compiled replacement 'gives the same results', or when reviewing a speedup table. Not a profiler, and it does not measure energy."
license: Apache-2.0
---

# Numerical kernel comparison

A speedup claim has two halves: the numbers still agree, and the timing was fair. This helper
checks the first exactly and refuses to report the second unless the measurement contexts match.
Python 3.10+, stdlib, offline; accelerator libraries are optional and user-supplied.

## Use when

- A Numba, JAX, CUDA or Triton rewrite of a scoring function, force field or FFT step is proposed.
- A paper table shows "3.2x faster" without stating warmup, repeats, threads or synchronization.
- Two solvers are supposed to agree to 1e-6 on edge shapes, zeros and extreme values.

## Quick start

```bash
python scripts/run.py assets/example.json
```

The example returns `"status": "NUMERICAL_MISMATCH"` on a 2x2 output with one element off by 0.1
(`mismatch_indexes [3]`, `atol 1e-06`), `timing_contexts_match: false` and `median_speedup: null`,
because a mismatching kernel gets no speed credit. `energy_joules` stays null; this helper does not
measure energy.

## Preparing a comparison

Fix the operation, reference, candidate revision, shapes, dtype, tolerance and representative inputs
first. Call `szl_compare_kernel_runs(record)` from `kernel.py` with `reference_output`,
`candidate_output`, `atol`, `rtol`. Agreement means `abs(candidate - reference) <= atol + rtol*abs(reference)`
on nested shapes that match and finite values.

For timing, use real runs with warmup and at least three repeats, alternate order against thermal
drift, and synchronize asynchronous devices (CPU time around an unsynchronized launch is not GPU
time). Supply `reference_seconds`, `candidate_seconds` and identical `reference_context` and
`candidate_context` (hardware, dtype, input digest, threads, warmup, synchronized, measurement method).
Declarations are recorded, not authenticated. `szl_time_callable` times an already reviewed callable.

## What it does not do

A passing comparison covers these inputs only, not universal equivalence or general acceleration.
It does not install packages, load quarantined pickle or joblib files, or treat a kernel card as
trained weights. Optional source retrieval sends only repository and revision identifiers; nothing
is bundled that contacts a service. Related SZL sources, for inspection rather than installation:
[kernel suite](https://github.com/szl-holdings/szl-kernels/tree/7b59de18d35b1edca3c54a4647fb324b918563a8),
[invariants](https://github.com/szl-holdings/szl-invariants/tree/e9621c5d95e1b6a336981346e473980cfe2d037b).
