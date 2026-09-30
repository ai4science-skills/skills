---
name: szl-kernel-comparison
description: Compare a numerical kernel with a reference for output shape, finite values, declared tolerances and comparable timing evidence. Use when validating scientific optimizations or assessing a CPU, CUDA or tensor-kernel speedup claim.
license: Apache-2.0
---

# Numerical kernel comparison

Fix operation, reference, candidate revision, shapes, dtype, tolerance and representative
inputs before running. Review source before executing; pin immutable source revisions.
Do not load quarantined joblib/pickle files or treat a kernel card as trained weights.

Call `szl_compare_kernel_runs(record)` from `kernel.py`. Supply `reference_output`,
`candidate_output`, `atol`, `rtol`. Nested shapes must agree and values must be finite.
Agreement means `abs(candidate-reference) <= atol + rtol*abs(reference)`. Include edge
shapes, zeros, extreme values and production layouts when relevant.

For timing, use actual runs with warmup and at least three repeats. Address order/thermal
effects, for example with alternating order. `szl_time_callable` measures an already reviewed
user-supplied callable. Pass device synchronization for asynchronous accelerators; CPU time
around an unsynchronized launch is not GPU execution time. Avoid machine identifiers and
unrelated workloads.

For a median ratio supply `reference_seconds`, `candidate_seconds` and identical
`reference_context`, `candidate_context` with hardware, dtype, input_sha256, threads, warmup,
synchronized and measurement_method. These declarations are recorded, not authenticated.
Numerical mismatch or absent/different context suppresses the ratio. A passing comparison
covers only these inputs; it does not establish universal equivalence or general acceleration.

```bash
python scripts/run.py assets/example.json
```

The example mismatches one value and has no timings. Energy stays null; the helper does
not measure energy. Keep a separate actual energy artifact if that claim matters.

SZL sources to investigate:
[kernel suite](https://github.com/szl-holdings/szl-kernels/tree/7b59de18d35b1edca3c54a4647fb324b918563a8),
[invariants](https://github.com/szl-holdings/szl-invariants/tree/e9621c5d95e1b6a336981346e473980cfe2d037b).
The pack provides a comparison harness, not installed kernels or a published benchmark.

Outside services: none bundled. Optional source retrieval sends repo/revision identifiers
to GitHub/Hugging Face. No credential is required offline. Loading this skill does not
authorize remote-code trust, package installation or an accelerator workload.

Runtime: Python 3.10+ offline; accelerator libraries are optional and user-supplied.
