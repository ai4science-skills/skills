---
name: szl-paired-science
description: Qualify a paired scientific benchmark from complete per-trial losses, training-only normalization, an identity negative control, and exact input hashes. Use for comparing algorithms or model checkpoints before making a measured improvement claim.
license: Apache-2.0
---

Use this skill when a researcher needs a reproducible comparison from supplied measurements. It works offline with Python 3.9 or later and contacts no external service.

Read `references/protocol.md` to prepare the declared experimental plan and measurements. Run `scripts/qualify.py` on the JSON file. The helper rejects missing or duplicated pairs, overlapping train/test identifiers, nonfinite losses, zero normalization scales, failed identity controls, and incomplete provenance declarations. It reports each task in its own dimensionless scale and applies a declared minimum effect and a conservative multiple-task correction to exact paired sign-flip tests.

Treat the helper's output as **local comparison evidence**. The plan, independence, train-only scale, source, and dataset identifiers are researcher declarations; the helper cannot establish that they are true merely by checking their syntax. Inspect the underlying prediction files, split construction, plan timestamp, dependencies, hardware, wall time, and memory evidence before using those declarations. Do not combine unrelated units as a raw mean or treat correlated horizons as independent experimental replications.

An identity negative control uses the baseline predictions unchanged. Its losses must match the baseline within the plan's tolerance. A treatment that appears to improve under this control is a measurement or pairing fault requiring investigation.

For a real checkpoint tested on synthetic signals, retain both facts: **real checkpoint, synthetic inputs**. A successful local result does not establish performance on external data, a novel scientific contribution, clinical suitability, independent replication, or production admission. Hashes establish which bytes were checked; they are not signatures or proof of rights. Never replace a failed or unavailable measurement with an estimate.

The helper does not train, download models, execute supplied code, upload data, publish results, change a gate, or grant permission to use third-party data. A researcher must decide which experiment is appropriate and obtain any required data rights.
