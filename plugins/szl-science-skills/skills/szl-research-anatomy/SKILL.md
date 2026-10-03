---
name: szl-research-anatomy
description: "Maintains a project's claim-and-evidence ledger as a dependency graph: datasets, code, runs, claims and proofs with supporting, contradicting and qualifying evidence links, observation dates, expiry, source revisions and corrections, then reports which conclusions need rechecking when any input changes. Use for persistent project memory across sessions, when a source is retracted or updated, when two findings conflict, or when the user asks 'what depends on this'. Not a literature monitor and not a truth oracle."
license: Apache-2.0
---

# Living research anatomy

A project's conclusions rest on specific bytes. When those bytes change, expire or get contradicted,
the ledger says which claims are now stale instead of letting them live on in the paper. Python 3.10+,
stdlib, offline.

## Use when

- A reference dataset got a new release; which figures must be regenerated?
- A supporting preprint was withdrawn, or a replication contradicts an earlier finding.
- Resuming a project months later and needing the evidence state, not just the files.
- Recording negative results and open questions so they survive the next session.

## Quick start

```bash
python scripts/run.py assets/example.json
python scripts/run.py assets/ledger-example.json
```

The first example changes one dataset digest and returns `conclusion` as `STALE` with `recheck`
propagated to dependents. The second (as of a fixed UTC time) reports `expired_sources ["old-source"]`,
`conflicting_claims ["conclusion"]` with one `supports` and one `contradicts` link both active, and
`recheck ["conclusion", "next-run", "old-claim", "old-source"]`.

## Working with the ledger

Nodes follow `szl.research-anatomy.v1` with `depends_on` edges. Add `evidence_links` from evidence
to claims with `supports`, `contradicts` or `qualifies`; they also create dependencies. Model feedback
as a new dated run (cycles and dangling parents are rejected). Set `observed_at`, `expires_at`,
`source_revision` and declared `evidence_status`; expiry uses an explicit fixed UTC `as_of`, never the
helper's clock. Read `references/ledger-contract.md` for the schema.

`szl_anatomy_assess(graph, current_digests, as_of)` takes actual byte readbacks. Changed, expired,
withdrawn or future-dated observations propagate rechecks to descendants; unrelated branches are
untouched. Missing readbacks stay `NOT_CHECKED`; `MATCH` establishes byte integrity only.
`szl_anatomy_update(graph, replacements)` applies corrections, retains unsigned prior nodes and marks
dependents `needs_recheck: true`. Record fresh evidence before clearing a flag.

The companion szl-science-workbench observes selected files and keeps project revisions; this helper
is independently usable. Caller-entered `MEASURED` or `PROVEN` never verifies truth.

## What it does not do

Dependency edges establish neither causality nor scientific truth. History is unsigned. Freshness and
retraction records are supplied observations, not live literature monitoring. Graph limits: 8 MiB,
10,000 nodes, 20,000 evidence links. No external lookup, model or installation is bundled.
Source pins and rights boundaries: `references/provenance.md`.
