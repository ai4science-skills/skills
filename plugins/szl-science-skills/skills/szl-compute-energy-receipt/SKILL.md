---
name: szl-compute-energy-receipt
description: "Turns a compute run's energy evidence into a typed receipt (MEASURED from counter samples, REPORTED from vendor totals or TDP estimates, UNAVAILABLE when nothing usable exists) with kWh, optional CO2e from a declared grid factor, and a ready-to-paste methods sentence. Use when a paper, grant report or model card needs an energy or carbon statement for training, simulation or inference runs, or when a reviewer asks how much compute was used. Not a hardware monitor and not a carbon-accounting standard."
license: Apache-2.0
---

# Compute energy receipt

Reviewers and funders increasingly ask what a run cost in energy. Most answers are estimates
dressed as measurements. This skill keeps the two apart: it integrates power samples if you have
them, labels anything else REPORTED or UNAVAILABLE, and writes the methods sentence that says so.
Stdlib only, offline; it never reads hardware counters itself.

## Use when

- "Add an energy statement to the methods section" for a fine-tune, MD simulation or inference sweep.
- A model card needs a compute figure and you have an NVML or RAPL log, or only a cloud bill.
- A reviewer asks for CO2e and you must disclose that the grid factor is a published average.

## Quick start

```bash
python scripts/run.py assets/example.json
```

Seven NVML samples over 60 s give `"status": "MEASURED"` and this sentence:

> The run on 1x RTX 4060 Ti 16 GB consumed 0.002 kWh (8072 J), measured via nvml power sampling
> (7 samples over 60 s). Applying the declared grid factor of 386 gCO2e/kWh (declared regional annual
> average (operator supplied)) gives 1 gCO2e (REPORTED, not measured).

`assets/unavailable-example.json` has no energy evidence and yields the honest alternative:
"Energy consumption of this run on laptop CPU was not measured and is reported as UNAVAILABLE."

## Input

```json
{"run": {"id": "...", "purpose": "...", "hardware": "...", "duration_s": 60},
 "measurement": {"source": "nvml|rapl|metered_plug|pdu|ipmi|vendor|estimate|none",
                 "samples": [{"t": 0, "w": 62.0}, ...]  OR  "joules": 8072  OR  "tdp_w": 165,
                 "max_gap_s": 10},
 "grid": {"g_co2e_per_kwh": 386, "source": "where the factor comes from"}}
```

Samples are integrated trapezoidally. MEASURED requires a counter source and no gap larger than
`max_gap_s`; otherwise the class drops to REPORTED and the reason is recorded (`SAMPLE_GAP_EXCEEDS_LIMIT`,
`TDP_TIMES_DURATION_ESTIMATE`, `VENDOR_OR_ESTIMATE`). A grid factor without a source is ignored.

## What it does not do

It does not sample hardware, does not estimate embodied emissions or data-centre overhead (PUE),
does not compare efficiency between runs, and never promotes an estimate to MEASURED. The receipt
digest covers the record as written, not the truth of the declared samples.
