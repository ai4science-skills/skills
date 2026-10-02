---
name: szl-negative-control-audit
description: "Audits a registry of computational negative controls against a declared mechanism graph and the supplied outcome bytes: flags controls with a directed path from intervention to readout (not a null), controls that do not share the nuisance they are meant to absorb, post hoc tolerance changes, contamination, failed expected nulls and missing registered controls. Use when a study claims an effect is specific, when designing or reviewing scrambled, sham, shuffled-label or dummy-exposure controls, or when a reviewer asks what the controls rule out. Not a wet-lab protocol designer."
license: Apache-2.0
---

# Negative control audit

A negative control is a claim about the mechanism graph: this intervention should not reach this
readout, and it shares the same nuisance as the real one. The helper checks the declared graph for
exactly that, then checks that the recorded outcomes and settings were not edited after the fact.
Python 3.9+, stdlib, offline; it executes no scorer or experiment.

## Use when

- A knockout, scrambled sequence, shuffled label or sham exposure is offered as proof of specificity.
- The control passed but its scoring tolerance was changed after the main run.
- A registered control has no outcome on file.

## Quick start

```bash
python scripts/run.py assets/example.json
```

The synthetic registry returns `"status": "CONTROLS_CONSISTENT_ON_SUPPLIED_EVIDENCE"` with one
control (`dummy-exposure`, `SUCCESS`, delta 0.005) and artifact bindings `MATCH` on hashed bytes.
Remove a registered control's outcome and the report carries `MISSING_REGISTERED_CONTROL`; let an
expected null fail and status becomes `INCONCLUSIVE` with `EXPECTED_NULL_FAILED`.

## Preparing the registry

Read `references/contract.md` for the graph, registry and artifact format. An expected-null control
needs no directed intervention-to-readout path and must share a declared nuisance ancestor of both
endpoints in each mechanism; a common readout alone does not establish nuisance exposure. Graph edges
are scientific declarations, not causal discoveries. Retain every registered control including failed
and aborted ones. Missing evidence, changed tolerances, contamination and null failures produce
`INCONCLUSIVE`. For unchanged-baseline prediction identity checks use szl-paired-science.

## What it does not do

A clean report is consistency on supplied evidence, not proof that the control is sensitive, that the
graph is right, or that the main effect is causal. Power, nuisance coverage, actual execution and
pre-data registration need separate inspection; timestamps and digests cannot authenticate
preregistration. Limits: 1 MiB input, 128 DAG nodes, 32 controls. No efficacy estimate, model training,
data fetch, provider call or intervention design. Provenance: `references/provenance.md`.
