---
name: szl-clustered-replication
description: "Audit paired model, assay or pipeline losses when many observations belong to a few independent donors, plates, sites or training runs. Report observational versus experimental counts, equal-cluster effects, a conditional exact cluster sign-flip test and leave-one-cluster sensitivity. Use for pseudoreplication or a result that may depend on one experimental unit."
license: Apache-2.0
---

# Clustered replication

An experiment with 60 measurements from three donors has 60 observations, but only three
declared experimental units. Counting the measurements as independent can overstate evidence.
This skill checks a complete paired-loss table, averages within each declared unit, then gives
each unit equal weight. It keeps observational and experimental counts separate.

Read `references/contract.md` when preparing a table. Save the expected plan digest separately
before examining the outcomes. The helper checks that commitment; it cannot verify its date
or authenticity. Missing commitment or undeclared independence/sign-flip assumptions produce
DESCRIPTIVE_ONLY with no p value.

Run the intentionally sensitive synthetic example without a commitment:

```bash
python scripts/run.py assets/example.json
```

It retains twelve observations in three donor clusters, reports the donor-weighted and
row-weighted effects, and identifies the donor whose removal reverses the positive effect.
For the separately retained fixture commitment, copy the `plan_sha256` from
`assets/fixture-lock.json` into the `--expected-plan-sha256` argument. A conditional result
is a completed calculation, not acceptance of the experiment or its conclusion.

For each result, report the number and meaning of experimental units, the within-unit averaging,
the declared sign-flip basis, the conditional p value when available, and all leave-one-unit
findings. Sensitivity checks are descriptive; they are not additional independent replications
or a reason to remove a donor. Keep the complete table and disclose missing observations.

## Boundaries and services

The helper uses Python 3.9+ standard library, reads one explicit local JSON file, writes JSON
to standard output, and never runs models, supplied code, providers or network requests. No
credentials are required. It does not prove independence, randomization, symmetry, authentic
preregistration, scientific truth, clinical suitability or production readiness. It supports
complete paired scalar losses, one declared unit, 1–16 clusters and at most 10,000 rows; nested
crossed designs, covariates, informative missingness and mixed units need another analysis.

The methodological sources linked in `references/contract.md` are documentation only. Opening
those links contacts journals.plos.org or pmc.ncbi.nlm.nih.gov; this skill sends no research
input to those services and does not download those pages.
