# Change-impact contract

The document has exactly `schema`, `baseline`, `current`, `observed_digests`, `required_claims` and
`as_of`. Schema is `szl.research-change-impact.v1`. Both snapshots use `szl.research-anatomy.v1`:
nodes require unique `id`, valid `kind`, nonempty `title`; `depends_on` and `evidence_links` create
directed dependencies. Every declared parent must exist in that snapshot. Model feedback as a new
run id; cycles are rejected. Evidence links target claim/proof/decision nodes and have relation
supports/contradicts/qualifies. Existing workbench metadata and retained history are accepted as JSON.

Either snapshot may contain zero nodes. An empty current snapshot represents complete retirement:
all baseline nodes and edges remain in the removal report, and required claims remain
MISSING_REQUIRED_CLAIM. Two empty snapshots do not establish healthy coverage. The required-claim
list must still be nonempty; dangling evidence links and readbacks for absent nodes remain invalid.

The artifact digest field is `sha256`: a 64-character lowercase hexadecimal SHA-256 digest, or
omitted/null when no artifact is pinned. A minimal snapshot is self-contained:

```json
{
  "schema": "szl.research-anatomy.v1",
  "nodes": [
    {"id": "data", "kind": "dataset", "title": "Selected data", "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},
    {"id": "result", "kind": "claim", "title": "A claim to reassess", "depends_on": ["data"]}
  ],
  "evidence_links": [{"claim": "result", "evidence": "data", "relation": "supports"}]
}
```

Kinds are question, claim, paper, dataset, code, model, kernel, run, proof and decision. Each id
contains 1..128 characters; titles contain 1..2048. Dependencies are unique ids in the same snapshot.
Optional evidence_status is active, corrected or retracted; needs_recheck is boolean. The digest
above is an illustrative synthetic pin, not a readback. Use actual selected-byte digests in a real audit.

`observed_digests` maps current pinned node ids to actual SHA-256 readbacks, or null when unavailable.
Unknown and unpinned observation ids are rejected. A missing readback stays NOT_OBSERVED. Paper,
dataset, code, model, kernel, run and proof nodes without a digest are UNPINNED. Matching bytes never
clear a change in an ancestor. Caller-entered digests remain assertions until separately verified.

`required_claims` contains 1..1000 unique claim/proof/decision ids. A removed or absent required claim
returns MISSING_REQUIRED_CLAIM rather than silently falling out of the review denominator. `as_of`
and optional observed_at/expires_at fields use UTC YYYY-MM-DDTHH:MM:SSZ. An expired, corrected,
retracted or future-dated observation requires rechecking. A persistent needs_recheck flag is retained.

Added/removed nodes, any changed declared node field, added/removed dependencies, and changed evidence
relations seed impact. Dependencies are combined across baseline and current only for impact
reachability, so removing an old edge cannot hide its effect. A reversal can make the combined graph
cyclic even when each snapshot is valid; finite visited-node traversal still works. Recheck order
uses the current DAG. Removed affected nodes appear separately in retired_affected_nodes.

The report binds canonical input and snapshot JSON with SHA-256, orders ids deterministically and
gives one shortest witness path per required claim. A path is one sufficient declared reason, not
an enumeration of every possible cause. Recheck order includes all impacted current nodes, including
artifacts to reacquire and claims to review; it is not an executable or globally minimal experiment
plan. Unrelated branches are omitted on the supplied graph, subject to missing readbacks remaining
explicit. NO_DECLARED_IMPACT says nothing about omitted dependencies, authenticity or truth.

Bounds: 2 MiB input, JSON depth 64, 100,000 JSON values, 0..1000 nodes and 10,000 declared dependencies
per snapshot. Invalid JSON, duplicate JSON keys, nonfinite values, duplicate ids, dangling parents,
duplicate edges, invalid digests and per-snapshot cycles are rejected. CLI exit 0 means the report
was computed, including REVIEW_REQUIRED; exit 2 means invalid input or I/O failure. Output creation
is exclusive; no existing report is overwritten. Graph data is never evaluated or executed.

Original implementation for SZL Holdings under Apache-2.0; it adapts the repository's existing
research-anatomy schema. This is a useful comparison design, with no priority or first-ever claim.
