---
name: szl-uncertainty-lineage
description: Propagate declared measurement uncertainty through a small arithmetic dependency graph using a first-order delta approximation. Use when a researcher needs to see how corrected inputs or shared-source correlation change a reported standard uncertainty; require unit checks separately.
license: Apache-2.0
---

# Uncertainty lineage

Run the offline helper on a bounded, explicitly declared model:

```bash
python scripts/run.py assets/example.json
```

The report retains every declared input dependency, including one whose local
derivative cancels to zero. It gives each target's value, Jacobian, propagated
variance, standard uncertainty, and signed per-input covariance contributions.
Compare those quantities with a separately calculated reference before using
the result in research. Read `references/contract.md` when preparing an input
model or interpreting a failure.

The helper uses only the Python standard library. It contacts no external
services and requires no credentials. This family supplies a CLI resource;
it has no native sidecar kernel or verified application registration.
Point and Jacobian operations must be exact at 80-digit decimal precision;
nonterminating decimal divisions such as 1/3 fail closed. The standard-uncertainty
square root is separately approximated. Read the contract before choosing this
bounded tool for an arithmetic graph.

Require the researcher to declare either input independence or the complete
correlation matrix. Missing correlations are unknown, never silently treated
as zero. Keep the original model and report when a value or correlation is
revised; run the revised model as a new version. Verify units with a separate
unit check before this numerical step.

This evaluates a **first-order local approximation** to supplied arithmetic.
It does not establish the input uncertainty model, distribution coverage,
physical units, causality, or a scientific conclusion. Large uncertainty near
a nonlinear boundary may require simulation or an analytic reference.
