# Dated claim/evidence contract

The original APIs remain `szl_anatomy_validate(graph)`, `szl_anatomy_assess(graph,
current_digests=None, as_of=None)` and `szl_anatomy_update(graph, replacements)`.
`szl.research-anatomy.v1` adds optional fields without changing legacy payloads.

Nodes require unique nonempty `id` (at most 128 characters), bounded `title` (2,048), and
`kind`: question, claim, paper, dataset, code, model, kernel, run, proof or decision.
Optional `depends_on` contains unique known IDs and `sha256` is a lowercase SHA-256 of actual
selected artifact bytes. A graph must be a DAG; feedback needs a new run node. Maximums are
10,000 nodes, 20,000 evidence links and 8 MiB of canonical JSON.

Optional `evidence_links` is a list of exactly `{claim, evidence, relation}`. Both IDs must
exist, the target must be a distinct claim, and relation is `supports`, `contradicts`,
`qualifies`. Exact duplicate links are rejected. Evidence links also enter dependency/cycle
checks and source-change/update propagation. Multiple relations remain visible; the helper
never selects a winning paper or converts vote counts into confidence.

Optional source fields are `source`, bounded nonempty `source_revision`, `observed_at`,
`expires_at`, and `evidence_status` (active/default, retracted, corrected). Retain selected
correction/retraction evidence and revision provenance externally. The helper does not fetch
sources or verify whether a paper was actually retracted.

Timestamps must be valid UTC `YYYY-MM-DDTHH:MM:SSZ`; offsets, naive times, leap seconds and
impossible dates are rejected. Expiry requires an observation and must strictly follow it.
Supply fixed `as_of` on the graph or as the third API argument. If both are present they must
match. No time is inferred. At `as_of == expires_at`, evidence is EXPIRED. Before an
observation it is NOT_YET_OBSERVED. Without `as_of`, freshness is NOT_CHECKED and
`expiry_not_checked` retains the IDs; absent expiry is NO_EXPIRY when a clock is supplied.
Choosing expiry intervals is a scientific review decision, not an automatic quality score.

`current_digests` maps known IDs to observed lowercase hashes. A comparison is MATCH or
MISMATCH only where both recorded and observed hashes exist; omitted readbacks are
NOT_CHECKED. A changed observation, explicit `needs_recheck: true`, expired/future source,
or withdrawn status seeds transitive invalidation. Sources reached by this invalidation are
excluded from active conflict classification while all their links remain in the report.
Active contradiction rechecks the claim and its descendants; active support plus active
contradiction also yields CONFLICTING. No ancestor or unrelated branch is invalidated.

Report fields retain `graph_sha256`, `nodes`, `changed_sources`, `recheck`, `signed: false`
and `execution_authority: none`. Additions are fixed `as_of`, `expired_sources`,
`future_observations`, `withdrawn_sources`, `conflicting_claims`, `contradicted_claims`, sorted `evidence_links`,
`expiry_not_checked` and `scientific_evaluation: NOT_MEASURED`. Nodes add `freshness` and
`evidence_state`. `usable` on a link means its source is not structurally invalidated; it
does not establish scientific reliability, artifact readback or authenticated provenance.
SUPPORTED, CONTRADICTED and QUALIFIED are descriptions of recorded links only.

Updates deep-copy the graph, preserve replaced nodes in unsigned history and add persistent
recheck flags to downstream nodes. A newer revision does not erase an earlier failure or
authenticate the source. New evidence and explicit review are needed to clear a flag.

Synthetic acceptance cases cover unchanged support, expiry at the exact boundary, omitted
clock, conflict, retraction/correction, changed-source evidence-edge propagation, unsigned
history, cycle/missing parent/duplicate relation, malformed dates/types, future observations,
conflicting clocks, stable output ordering and legacy API compatibility.
