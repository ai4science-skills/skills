---
name: szl-science-workbench
description: "Runs a resumable local research project that connects the SZL science checks (claim ledger, numerical math checks, dataset leakage audit, binary or categorical model scoring, kernel comparison, paired qualification, file capsule) over the project's actual bytes, records immutable runs, and invalidates downstream conclusions when any input changes. Use when the user wants all checks on one project directory, wants to resume or re-check a project, or asks 'what changed since last run'. Start here if unsure which single check to use. Not an experiment runner or a model trainer."
license: Apache-2.0
---

# SZL Science Workbench

One project directory, every check, every byte hashed, every run kept. The workbench bundles the
seven check implementations, so it works alone without the sibling skills, a service, or an install.
Read `references/project.md` for the project schema and evidence boundaries.

## Use when

- A lab wants leakage, calibration, math, kernel and paired checks on one dataset-plus-model project.
- A result must be re-checked after new data, a code change or a corrected label.
- A reviewer pack is needed later (szl-reviewer-pack reads this project's runs).

## Quick start

```bash
python scripts/workbench.py init ./research-project
python scripts/workbench.py run ./research-project
python scripts/workbench.py check ./research-project
```

The synthetic demo deliberately fails: `run` exits 1 with `COMPLETED_WITH_FINDINGS`
(dataset leakage, a math counterexample, a rejected paired comparison; model and kernel checks clean)
and writes `runs/<timestamp>-<digest>/` containing one report per check, actual file and implementation
hashes, a graph snapshot and a reproducibility capsule. `check` re-reads the last run's inputs and code;
changed, missing or unsafe paths invalidate dependent runs and conclusions and exit 1. Exit 2 is an
execution or input error with a retained ERROR record. The newest run is chosen by its retained UTC
timestamp, never by a user-supplied pointer.

## The pinned public study

```bash
python scripts/workbench.py fetch-triage ./triage-project
python scripts/workbench.py run ./triage-project
python scripts/workbench.py check ./triage-project
```

This opt-in command contacts huggingface.co for four small frozen files of a public synthetic triage
study (train and held rows, baseline and seed-011 predictions) at one exact revision; no model weights
are downloaded. The categorical evaluator joins row ids to retained targets and recomputes correctness,
ignoring saved correctness flags. Download receipts cover retrieved bytes, not model authenticity or
data rights. Network errors stop the fetch and leave a visible incomplete project.

## How runs behave

`run` reads only the selected project files. In the demo the kernel stage executes the pinned
calibration reference and the adapted helper on identical inputs, checks agreement, then times both
on the local CPU: a measurement of these implementations on this input, not a GPU, energy or general
speed claim. The paired stage keeps preregistration and independence declarations separate from
numerical qualification; an unregistered demonstration cannot qualify as research. Change explicit
inputs and run again to collect new evidence; prior snapshots stay on disk. To add a claim or paper,
extend the project graph with dependency ids; a rerun clears only the check nodes it executed, never an
unrelated claim's recheck flag. No helper promotes, deploys, merges or marks truth verified.

## What it does not do

Outside services: none during init, run or check; only fetch-triage contacts huggingface.co and its
public CDN. Credentials: none. Runtime: Python 3.10+, standard library only. No packages, weights or
arbitrary commands are installed or executed. A retained capsule and graph cannot authenticate
themselves against wholesale replacement; keep a copy elsewhere when that matters.
