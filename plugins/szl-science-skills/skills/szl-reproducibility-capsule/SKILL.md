---
name: szl-reproducibility-capsule
description: Create and verify a portable manifest binding explicitly selected research inputs, code and outputs to exact bytes. Use for experiment handoffs, replay records, reproducibility checks or detecting changes since a saved run.
license: Apache-2.0
---

# Reproducibility capsule

Select exact inputs, source, environment specification, command description, seed, parameters,
results and interpretation to retain. Use a declared project root and explicit file list;
never recursively sweep a workspace or include credentials, person records or unrelated data.
Metadata is visible in the manifest and is not automatically redacted.

Call `szl_make_capsule(root, files, metadata)` from `kernel.py`. Files use canonical relative
POSIX paths such as data/observations.csv; absolute paths, traversal, symlinks and junctions
are refused. The manifest stores paths, sizes and streaming SHA-256 hashes, not file contents.
It does not package the files; use the scientist's chosen artifact store or sharing channel.
Keep an independent manifest/digest copy when integrity across sessions matters.

Call `szl_verify_capsule(root, capsule)` on retained files. Report MATCH, CHANGED, MISSING and
unsafe/unreadable paths. Unsigned manifests detect changes relative to a retained copy; an
attacker who replaces the whole manifest can replace its digest too. `authentic: false`
stays false even when all bytes match. Actual SZL receipt signing is a separate integration
requiring a real key and verifier. Never relabel a digest as a signature.

Record exact environment and replay limits. Use deterministic equality only where supported;
otherwise preserve predeclared scientific tolerances. Matching files is not a reproduced
experiment, correct scientific conclusion or sound proof. The helper never executes recorded
commands or installs dependencies.

```bash
python scripts/run.py assets/example.json --root .
```

Creation input contains `files`, optional `metadata`; verification accepts the saved capsule.
`--output` writes a new file exclusively. The synthetic example hashes included protocol
notes; select your own project root/files for real work.

This follows SZL's honest unsigned-receipt and exact-artifact conventions. It does not
perform publication or cryptographic signing. Lambda is Conjecture 1 (OPEN).
Outside services/credentials: none. No uploads, model loading or laboratory actions.

Runtime: Python 3.10+; stdlib; offline; no signing key required.
