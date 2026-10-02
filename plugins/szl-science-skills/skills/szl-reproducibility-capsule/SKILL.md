---
name: szl-reproducibility-capsule
description: "Creates an exact-byte manifest (path, size, SHA-256) for the explicitly selected files of an experiment, verifies them later as changed / missing / unsafe, and validates a bounded replay declaration (inputs, source, environment, plan, outputs) without executing anything. Use when handing an analysis to a collaborator, archiving a result, preparing a replication or when the user asks 'did anything change since the run'. Not a container, not a signature, and it does not reproduce the experiment."
license: Apache-2.0
---

# Reproducibility capsule

Pick the files that define an experiment and freeze their bytes. Later, prove they are the same
bytes or list exactly which ones moved. Python 3.10+, stdlib, offline.

## Use when

- Archiving the input tables, scripts, environment file and reference outputs behind a figure.
- A collaborator re-runs your pipeline and gets different numbers: verify the capsule first.
- Preparing a replay package for a separate sandbox review with declared seed and limits.

## Quick start

```bash
python scripts/run.py assets/example.json --root .
```

Creates a `szl.reproducibility-capsule.v1` record listing `assets/protocol.txt` (270 bytes, its
SHA-256), the synthetic metadata, `signed: false` and a `capsule_sha256`. Verification on retained
bytes reports changed, missing and unsafe or unreadable files separately. `assets/replay-example.json`
adds a replay declaration over the files in `assets/replay`.

## Creating and verifying

`szl_make_capsule(root, files, metadata=None, replay=None)` accepts plain path lists or role-tagged
entries (`path` plus `role`). Paths must be canonical relative POSIX paths, unique, within hard
count and byte bounds; traversal, symlinks, junctions, reparse points and credential-like names
are refused. `szl_verify_capsule(root, capsule)` re-hashes. All bytes matching plus a complete,
valid replay declaration yields `replay_ready: true`, meaning prepared for a separate sandbox review;
`execution: NOT_RUN`, `capability_denial: DECLARED_ONLY` and `tolerance_application: NOT_RUN` stay
explicit. Read `references/contracts.md` before authoring a replay.

Keep an independently retained copy of the manifest when integrity across sessions matters: an
unsigned self-digest cannot detect replacement of the whole manifest. `authentic: false` stays false
even when every byte matches; real signing needs a key and a verifier (see szl-session-receipt for the
optional signing path).

## What it does not do

Never executes argv or source, installs dependencies, launches processes, applies numerical
comparisons to outputs, or inspects file contents for secrets (credential-name guards look at names).
Limits: 128 files, 8 MiB per file, 32 MiB total. It cannot prove source safety, enforce a sandbox or
verify preregistration. Hashes are not signatures; readiness is not reproduction.
