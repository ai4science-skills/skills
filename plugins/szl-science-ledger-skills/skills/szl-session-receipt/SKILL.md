---
name: szl-session-receipt
description: "Writes a verifiable record of an analysis session: SHA-256 of every input, script and output file, the commands and environment as declared, a root digest, and a plain-language Methods paragraph; later re-hashes the files to report MATCH / MISMATCH / MISSING. Use at the end of a Claude Science or notebook session, when handing an analysis to a collaborator, when a journal asks for a reproducibility statement, or when the user says 'record what we just did'. Not a signature of correctness."
license: Apache-2.0
---

# Session receipt

A methods section that can be checked. While working, keep a manifest of the files read, the
scripts run, the files produced and the commands used. `record` hashes all of it and writes the
paragraph; `verify` re-hashes it tomorrow, or in a reviewer's hands, and says whether anything
changed. Stdlib only, offline; signing is optional and absence is stated, never hidden.

## Use when

- Ending an agent-assisted analysis: "record this session" produces the receipt and the paragraph.
- Submitting: the Methods paragraph and the receipt file go in supplementary material.
- Receiving a colleague's analysis: run `verify` against their files before reading their conclusions.
- Re-running months later: a MISMATCH on the raw data file explains the different numbers before anyone argues.

## Quick start

```bash
python scripts/run.py record assets/example.json --root assets/project --output /tmp/receipt.json
python scripts/run.py verify /tmp/receipt.json --root assets/project
python scripts/run.py methods /tmp/receipt.json
```

The synthetic project gives `"status": "RECORDED"`, `verify` gives `"status": "MATCH"` over 3 files, and
the paragraph reads:

> Analysis for SYNTHETIC dose-response reanalysis was performed by an AI agent (Claude (Claude Science))
> between 2026-10-01T14:00:00Z and 2026-10-01T14:25:00Z. It read 1 input file(s), executed 1 script(s) via
> 1 recorded command(s), and produced 1 output file(s); the SHA-256 digest of every file is recorded in
> session receipt e042750035a157ae (root digest ...). The environment was declared as Python 3.12.1 with
> numpy 2.1.0, pandas 2.2.3. The receipt is unsigned; integrity can be re-verified by re-hashing the
> listed files, authenticity is not established.

## Manifest

```json
{"project": "...", "session_id": "...", "started_at": "...Z", "finished_at": "...Z",
 "actor": {"kind": "agent|human", "name": "..."},
 "inputs": ["data/raw.csv"], "code": ["analysis.py"], "outputs": ["results/summary.csv"],
 "commands": ["python analysis.py"],
 "environment": {"python": "3.12.1", "platform": "...", "packages": {"numpy": "2.1.0"}}}
```

Paths are relative to `--root` and may not escape it. Fields under `declared_only` (commands,
environment, actor, timestamps) are recorded as stated, not observed. Optional `--sign-key KEY.pem`
produces a DSSE signature when `szl-receipt-dsse` is installed; otherwise the receipt says UNSIGNED.

## What it does not do

A MATCH means the files are byte-identical to the recorded ones. It does not mean the analysis is
correct, that the recorded commands were the only ones run, or that the declared environment was
real. It does not capture files you did not list. Details: `references/contract.md`.
