---
name: szl-evidence-gate
description: "Checks whether each claim in a paper, model card, README or grant report has a real artifact behind it (file present, bytes match a declared digest, required text present) and returns PASS / FAIL / ABSTAIN / ERROR per claim. Use when the user asks to verify a results section, audit a model card or dataset card, check supplementary files against the text, or prepare a reviewer response; also when someone says 'is this claim backed up'. Not for judging whether a claim is scientifically correct."
license: Apache-2.0
---

# Evidence gate

Answers one question per claim: is there a checkable artifact behind it? Each claim names
the files that are supposed to support it; the gate confirms presence, byte digest and
required text, and says ABSTAIN when a claim declares nothing checkable at all. Stdlib only,
offline, reads only the files the claims file names.

## Use when

- A PI asks "does every number in the results section point at a file in the repo?"
- A model card says "ECE < 0.05" or "no template leakage" and you need to show which file proves it.
- A reviewer asks for the artifact behind a specific sentence.
- Preparing supplementary material: the gate's report is the artifact index.

## Quick start

Write a claims file (see `assets/example.json`) and run it against the directory that holds the artifacts:

```bash
python scripts/run.py assets/example.json
```

The synthetic example returns `"status": "ABSTAIN"` with counts `{"PASS": 2, "FAIL": 1, "ABSTAIN": 1, "ERROR": 0}`:
the accuracy claim PASSes (digest matches `assets/artifacts/held_out_metrics.csv`), the leakage claim PASSes
(`assets/artifacts/eval_protocol.txt` contains the declared sentence), the calibration claim ABSTAINs (no evidence
declared), and the optional energy claim FAILs with `MISSING_ARTIFACT`. The exit code is 0 whenever the gate ran; 2 on malformed input. Read the status, not the exit code.

## Claims file

```json
{"subject": "what is being audited",
 "claims": [{"id": "held-out-accuracy", "text": "the sentence as written", "required": true,
             "evidence": [{"path": "artifacts/metrics.csv", "sha256": "<64 hex>", "must_contain": ["0.912"]}]}]}
```

`sha256` and `must_contain` are optional; with neither, the item is checked for presence only and the
claim is labelled `PRESENCE_ONLY_NO_DIGESTS_DECLARED`. `required: false` keeps a failing claim out of the
aggregate FAIL. Paths are relative to `--root` (default: the claims file's directory) and may not escape it.

## Reading the result

| Status | Meaning |
|---|---|
| PASS | every declared artifact present, digests and text match |
| FAIL | an artifact is missing, its bytes differ, or a required snippet is absent |
| ABSTAIN | the claim declares no evidence, so there is nothing to check |
| ERROR | the claim or evidence record is malformed |

The aggregate is FAIL if any required claim fails, otherwise ABSTAIN if any claim abstains, otherwise PASS.

## What it does not do

It does not read the claim text for meaning, does not open PDFs or notebooks, does not recompute
numbers, and does not decide whether the artifact actually supports the sentence. A PASS says the
evidence exists and is intact; a human still has to read it. Contract: `references/contract.md`.
