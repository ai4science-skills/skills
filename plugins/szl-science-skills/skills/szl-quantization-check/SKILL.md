---
name: szl-quantization-check
description: "Compares a quantized, ported or distilled model's outputs with the reference model's on the same inputs, row by row: cosine similarity, KL divergence between softmaxed logits at a declared temperature, top-1 agreement, worst rows named, and WITHIN_TOLERANCE / DEGRADED / INCOMPARABLE against the tolerances you declare. Works from exported logits or embeddings; no framework needed. Use when a lab runs a local GGUF or int8 model, swaps ONNX for PyTorch, distils a classifier, or asks 'is the 4-bit version still the same model'. Not a measure of accuracy against ground truth."
license: Apache-2.0
---

# Quantization and port check

The question is never "is the quantized model good"; it is "does it still answer like the model
we validated". That is a comparison against the reference, input by input, with the worst rows
named and the thresholds written down before the run. Stdlib only, offline: export the logits or
embeddings from both models and point this at the two files.

## When you would use this

- You converted the lab's classifier to 4-bit to run on a laptop and need to know what changed before using it on real samples.
- A collaborator ported the model to another runtime and the numbers look "close enough".
- A distilled student model replaces the teacher in a pipeline; agreement must be shown, not assumed.
- A reviewer asks how you verified that the deployed model is the evaluated model.

## Ten seconds

```
python scripts/run.py assets/example.json
```

Eight inputs, six classes, reference logits versus a candidate with small noise and one row
whose sign was flipped (a plausible porting bug). Expected result: `DEGRADED`; mean cosine
0.7494, worst row `p05` at cosine -1.0, worst KL 1.6977, top-1 agreement 0.875, and three
declared tolerances failed. Remove `p05` from both files and the status becomes
`WITHIN_TOLERANCE` on the remaining rows, which is the honest statement: agreement on those inputs.

## Tolerances

Declare only the ones you will act on: `min_cosine` (worst row), `max_fraction_below_cosine`
(use with `min_cosine` to allow a declared share of outliers), `max_kl` (worst row, logits only),
`min_top1_agreement` (rate, logits only). Undeclared tolerances are not evaluated and are not
reported as passed. `kind: "embeddings"` compares cosine only.

## Status

`WITHIN_TOLERANCE` when every declared tolerance holds, `DEGRADED` when any fails,
`INCOMPARABLE` when shapes differ, a vector is zero or a value is not finite, `ERROR` for malformed input.

## What it will not tell you

- Whether either model is right. A wrong reference is matched just as well as a right one.
- Anything about inputs you did not include; pick the comparison set the way you would pick a test set.
- Latency, memory or energy; see szl-kernel-comparison and szl-compute-energy-receipt.
