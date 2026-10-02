---
name: flotation-selectivity-before-bench
description: Rank flotation reagent candidates before the bench. MODELED only. Abstains without a measured CSV. Emits a SOFTWARE_RECEIPT. Does not claim recovery percent.
license: Apache-2.0
---

# Flotation selectivity before the bench

Founder report: accepted on Anthropic AI for Science Discourse topic 412
(predicting flotation reagent selectivity before the bench). This skill does not
scrape that login wall and does not treat acceptance as a bench result.

This organ lives inside szl-frontier. It does not mint a Space and it does not
mint SZLHOLDINGS/nexus.

## Job

Given a public reagent table plus an optional local bench CSV, emit a rank band
and a receipt.

```text
python rank.py --table reagents.csv
python rank.py --table reagents.csv --bench bench.csv
python -m szl_frontier flotation --table reagents.csv
```

The rank is a sort of one declared column, `public_score` or `screen_score`.
Bands are tertiles of that order (`high`, `mid`, `low`). Fewer than three rows
are `listed`. The numeric score is not copied into the receipt.

If the bench CSV is missing, the run is MODELED, the directive is DEFER, and
`claims.input` is UNAVAILABLE. A bench file is hashed and may release the
software receipt. It does not create a recovery percent.

## Refuse

- Invented recovery, grade, or selectivity percent
- Using a recovery, grade, or selectivity column as the score (`directive: BLOCK`)
- "Bench-validated" without a row hash
- Cloning Palantir, Anduril, or vendor UI
- Calling Lambda a theorem
- A joule or watt figure from this organ

## Public anchors (not our numbers)

- He et al., Minerals Engineering 2022, QC plus ML screening of collectors
- Separation and Purification Technology 2024, sulfide collector MAE on their set
- AIChE Journal 2025, phosphate flotation screening

Their error bars are not ours.

## Receipt fields

```text
schema: szl.frontier.flotation-selectivity.v1
evidenceTier: SOFTWARE_RECEIPT
selectivity: MODELED
directive: RELEASE only when a rank band exists and the bench CSV is hashed, else DEFER
directive: BLOCK if the score column is recovery, grade, or selectivity
claims.execution: SOFTWARE
claims.identity: MEASURED when the reagent table sha256 is present, else UNAVAILABLE
claims.input: MEASURED only when the bench CSV sha256 is present, else UNAVAILABLE
recoveryPercent: null
energyClass: UNAVAILABLE
ato: false
lambda: OPEN
trustCeiling: 0.97
discourse: REPORTED topic 412
```
