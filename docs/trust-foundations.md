# Trust foundations

This stage adds a non-installable evidence catalog beside the existing plugin
registry. It does not change `registry.json`, vendored plugins, generated
marketplace/catalog files, importer behavior, or the historical report PR.

## Origin

Baseline: `f49e0058a658122547ee24596fad65d886f64638`. The entry contract is a new
`ai4s.skills-entry/v0-foundation` projection. The supplied evaluation-task schema
is not a skills-entry schema; the absent complete prior schema is not assumed.
JSON Schema Draft 2020-12 describes structure; the stdlib semantic validator also
checks identities, portable paths, UTC dates, expiry ordering, and state/evidence
consistency. This tooling reads JSON only; it makes no claim to parse YAML.

Source-lock validation is offline metadata validation. It checks recorded pins,
digests, counts, acquisition/correspondence assertions and non-approval flags.
It does not download archives, independently reconstruct their trees, or verify
publisher identity. The raw input SHA-256 is retained independently from every
archive and tree digest. Rich census metadata stays in its original artifact.

The adapter recognizes only the reviewed proposed auditor contract:
`ai4s.diagnostic-catalog/review-v1`, checker `0.1.0-review.1`. Its reviewed source
SHA-256 is `d7b0763b20a3d3807504a2084a1d57ec5833909ea2934ed87c6bdfd40888ff3d`;
the main-plus-helper bundle digest is
`33d97bb1c173b3a8760b8c576bca5c87204815be5f4329532b957841764d1e26`.
No auditor source is committed, imported or executed by this stage.

## Rights

New index tooling and documentation follow the root index license scope.
No third-party skill code or acquisition corpus is added. License labels/hashes,
transport success and Git correspondence are observations, not reuse grants.
Unknown/custom/proprietary terms, missing license identification and mixed
software/documentation scopes remain unapproved. Human review is not inferred
from a detector or source label.

## Agents and tools

Python stdlib, existing Git tooling, supported Library materialization and
read-only source review were used. Synthetic tests exercise the new local index
tooling and existing importer fixtures. They execute no auditor or skill payload,
install nothing, call no scientific provider and require no credentials/datasets.

The adapter verifies the complete raw report digest and each unsigned canonical
entry receipt, checks the exact checker contract, binds source URL/commit/path
to a validated lock record, and reconciles input snapshots and skill counts.
The expected implementation hashes above are review references; the report does not attest its producer code. Ingested STATIC checker_sha256 remains null. A matching caller-asserted snapshot remains unsigned. It is not a trusted
root-to-repository proof.

The hash scopes stay distinct:

| Field | Scope |
| --- | --- |
| `archive_sha256` | Exact compressed acquisition bytes |
| `source_skill_tree_sha256` | Census union of all source skill subtrees, using the named census contract |
| `diagnostic.auditor_tree_sha256` | Auditor skill subtree relative filenames and raw content digests |
| `diagnostic.snapshot_sha256` | Auditor captured repository content, excluding root .git |
| `lock_sha256` / `diagnostic.report_sha256` | Exact raw evidence artifact bytes |

The auditor tree hash omits modes and empty directories; inherited license files
may be outside a skill subtree. It must not be compared to a census digest with a
different scope or treated as rights evidence.

## Tests

Run from the repository root, with Python 3.9+ and no installs:

```
python -B -m unittest discover -s tools -p 'test_*.py' -v
python -B tools/check.py
```

Fixtures cover malformed/duplicate/non-finite JSON, Unicode and bounds, portable
identities, unavailable/linked files, immutable source-lock metadata, partial
runs, receipt/raw-hash tampering, ambiguous snapshots, source mismatches,
unsupported parsing, coverage gaps, findings, expiry, missing facets and claimed
human receipts. Static observations cannot become LISTED or measured evaluation.

Local validation: 72 synthetic tests passed on existing Python 3.12.10; the static
checker passed for the two existing vendored skills. The exact-hash v3 census
validated 5 sources/317 skill paths with one reuse block. The v4 census validated
115 sources/346 paths while retaining 5 acquisition blocks, 4 portability reviews
and 7 reuse blocks separately from 112 complete transports. This validates recorded
metadata, not archive/tree/receipt bytes. Native link creation is conditional on
platform privileges; mocked reparse/special-file rejection is also tested. No
sandbox-denial claim follows from these unit tests.

The PR records its exact tested head and hosted results. The existing re-vendor CI
step is not replaced by these offline checks.

## Security

Every entry retains independent STATIC, PROSE, BEHAVIOR, SCIENCE, TEST,
EVALUATION and FRESHNESS facets. Missing, blocked and unobserved values stay
explicit. A benign diagnostic becomes a CANDIDATE with partial STATIC observations
and an UNOBSERVED static conclusion; it never becomes STATIC PASS. Other facets
remain UNOBSERVED. Negative findings, unsupported parsing, incomplete coverage,
failed/partial catalogs and source-binding gaps block ingestion results.

Human review fields hold missing/blocked/unobserved or *claimed* approvals with
receipt references. They authenticate nobody. LISTED transitions are unavailable
in this foundation, even if a caller fabricates complete checks or approval
receipts. EVALUATION PASS is also unavailable until a paired-run receipt contract
exists. No vulnerability identifier, measured lift, biosafety approval or clinical
approval is generated.

JSON input is bounded to 2 MiB, 32 levels and 100,000 values; duplicate keys,
non-finite values, invalid Unicode and unsupported contracts fail closed. File
reads reject observed symlinks/reparse points, including parent components.
Those checks are not a filesystem isolation guarantee or a race-free sandbox.

Read-only capability assessment found the Docker engine unavailable. An existing
WSL Python was used only for trusted Library materialization and identity metadata.
Rootless execution, read-only root, no host mounts/socket/devices, dropped
capabilities, no-new-privileges/seccomp, resource/egress limits and fake-canary
denial were not demonstrated. Unknown skill execution remains BLOCKED.

## Rollback

This is additive tooling. Use an ordinary reviewed revert of the new files.
No registry migration, pin update, vendored output replacement, report rewrite,
release, merge or administrative operation is part of this stage.

## Known limits

The foundation is not the full v4 roadmap or a listing/install client. It does not
run vulnerability/dependency scanners, parse arbitrary SKILL frontmatter, evaluate
scientific validity or performance, verify human identity/signatures, or implement
a sandbox. The auditor has a partial YAML profile and heuristic license/security
recognition; those limits are preserved, not converted into assurance.

Source locks and reports are caller-provided unsigned evidence. Raw hashes provide
byte binding, not an independent trust anchor. Archived acquisition/portability,
license reuse, restricted selection and human gates remain separate.

Next gates: review the foundation contract; establish authenticated human-review,
full evidence/receipt and freshness policies; demonstrate an actual supported
sandbox with synthetic canaries before any separately authorized skill execution.
