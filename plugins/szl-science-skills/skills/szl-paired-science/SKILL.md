---
name: szl-paired-science
description: "Qualifies a paired before/after or A/B comparison offline: binds the predictions to separately frozen inputs, targets, corpus, scorer and training-only normalization by byte digest, checks every case is complete and unsubstituted, recomputes MAE/MSE, requires an identity negative control, and applies the declared sign-flip procedure with a minimum effect. Use when a candidate model, assay protocol or pipeline change is claimed to beat a baseline on the same cases, or when a reviewer asks whether the comparison was paired and preregistered. Not a general statistics package."
license: Apache-2.0
---

# Paired science

"Our new method beats the baseline" is a paired claim: same cases, frozen inputs, declared scorer,
declared minimum effect, and a control that should show nothing. This helper checks all of that
from bytes and refuses to qualify a comparison whose inputs cannot be bound. Python 3.9+, stdlib, offline.

## Use when

- A fine-tuned model is compared with its base on the same held-out cases.
- A new assay normalization is claimed to reduce error on matched samples.
- A reviewer asks whether the test set, scorer and normalization were frozen before predictions
  were seen.

## Quick start

```bash
python scripts/qualify.py assets/example-v2.json --expected-manifest-sha256 bddba992b16c38934cbabe184cbf4bb97e21c24247fdc5295660672163b72e9f
```

The bundled synthetic experiment returns `"status": "QUALIFIED_LOCAL_COMPARISON"` with
`"binding": "VERIFIED_INLINE_BYTES"` over 6 pairs. Change one byte of a case, drop a pair, or omit the
expected digest and it returns `REJECTED_LOCAL_COMPARISON`. The digest above comes from
`assets/fixture-lock.json`, the separately frozen lock for this toy example only.

## Protocol

Read `references/binding-contract.md` to prepare v2 evidence. Obtain the expected manifest digest
from a separately frozen input/target/corpus/scorer/normalization source before looking at the
predictions; never derive it from the predictions themselves or refresh it to make a failure pass.
The helper checks supplied byte digests, case membership, frozen-manifest continuity and prediction
envelope bindings, then recomputes supported losses and training scale. Missing bytes or an absent
lock stay `DECLARED` and block inference.

After binding succeeds, `references/protocol.md` fixes the identity control, minimum effect and exact
sign-flip procedure. Do not count correlated horizons as independent replications or average unrelated
units. v1 inputs are still accepted and explicitly report declaration-only binding.

## What it does not do

It never verifies the expected digest's authenticity, model consumption, plan timing or independence;
those need separate evidence. No supplied code, model, provider, network or GPU is executed. A qualified
comparison grants no production admission, data rights, novelty, clinical suitability or replication.
Scientific performance stays `NOT_MEASURED`.
