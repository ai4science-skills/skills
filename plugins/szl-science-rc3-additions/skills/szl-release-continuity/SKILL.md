---
name: szl-release-continuity
description: "Trace supplied immutable release observations across GitHub, PyPI, Hugging Face models, datasets and Spaces, and a runtime. Compare declared revisions, canonical source identities and per-surface artifact hashes; retain missing evidence, conflicts and refused readiness. Use when a green CI run, published wheel, Hub listing or running Space is being treated as an end-to-end release. Offline, bounded, standard library only; no credentials."
license: Apache-2.0
---

# Release continuity across registries

Freeze intended source and surfaces before observation; preserve failed readbacks.

Run `python scripts/run.py assets/example.json`. The synthetic example has a
Space with the wrong source revision and a runtime refusing readiness. Expect
`GAP_OR_CONFLICT` and exit 1. Repairing only the runtime label cannot repair the
publication binding.

[The example](assets/example.json) declares schema `szl.release-continuity.v1`,
one canonical source repository, its full commit and required surfaces.
Kinds: `github`, `pypi`, `hf-model`, `hf-dataset`, `hf-space`, `hf-kernel`, `runtime`.
Native kernels retain their own repository type and immutable revision.
Each expected identity has revision and artifact_sha256 only. A wheel, dataset
and build have separate expected hashes. GitHub, Hub and runtime pins must be
full immutable revisions; PyPI uses a version. GitHub must match declared source.
Every observation binds to the same source repository and revision. Runtime also
requires boolean `ready`; provider RUNNING and HTTP 200 do not supply it.

Set `observed` to null for unavailable readbacks. Use reviewed provider tooling;
retain immutable revisions, file hashes, times and receipts. The skill makes no
network calls. Never publish private names, keys or internal topology.

Exit 0: supplied identity agreement; 1: gap/conflict; 2: malformed input. `kernel.py` exports
`szl_release_continuity(record)`. Workbench type: `release-continuity`; the capsule
and living anatomy bind this result and invalidate conclusions after change.

This does not verify signatures or attestations, authenticate observations,
assess model or dataset quality, grant publication authority, or certify a
release. Use the canonical publisher's cryptographic verification separately.
Lambda remains Conjecture 1 (OPEN).

External services: none. Credentials: none. Dependencies: Python standard library.
