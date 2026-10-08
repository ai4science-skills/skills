# Security pipeline prerequisites

## Origin

Original implementation snapshot, 2026-09-30: main
`41946b95fd34872118894b1c4cee4fa08788a52e`, foundations PR #5
(`ff795c794b0949974723c0daac3aa550f7312fbe`) and report PR #3. Foundations
[PR #5](https://github.com/ai4science-skills/skills/pull/5) and the prerequisite
[PR #6](https://github.com/ai4science-skills/skills/pull/6) are now merged;
their delivered source is not an operational end-to-end security pipeline.
The supplied proposal was reviewed through its delegated requirements/findings;
its original literal bytes were not available here for a syntax certification.

Current source observation: `ai4science-skills/skills` main
`67c0b83faad8ac04c3d7549b795df044750bb810`, observed 2026-10-08 between
09:49:50 and 09:57:57 UTC. This is bounded GitHub source/control metadata,
not a new scanner run, runtime qualification, human approval or signed receipt.
Related paths below establish file presence only; they are not validated aliases
for the originally proposed commands. Fourteen of those fifteen requested paths
remain absent; the limited foundation entry schema is present.

| Prerequisite | Current main | Related observed source | Required before execution |
| --- | --- | --- | --- |
| `tools/ai4s_audit.py` | Missing | `tools/static_audit.py` present, different path | Reviewed implementation and immutable producer binding |
| `tools/bootstrap_tools.py` | Missing | None established | Verified preprovisioned tool producer and digest contract |
| `tools/dependency_audit.py` | Missing | `tools/dependency_inventory.py` present, different path | Reviewed data-only wrapper and exact source coverage |
| `tools/vulnerability_audit.py` | Missing | None established | Reviewed wrapper, offline DB provenance/freshness and error contract |
| `tools/normalize_findings.py` | Missing | Open [PR #17](https://github.com/ai4science-skills/skills/pull/17), candidate only | Typed receipt validation; missing output cannot mean no findings |
| `tools/build_catalog.py` | Missing | None established | Deterministic builder that treats candidates only as data |
| `tools/build_dashboard.py` | Missing | None established | Deterministic data-only builder; no candidate build scripts |
| `tools/enforce_policy.py` | Missing | None established | Independently approved immutable policy/checker |
| `sources/sources.lock.json` | Missing | Validator source present; private lock is not this path | Approved data-only acquisition and complete immutable source binding |
| `schema/skills-entry.schema.json` | Present | Foundation v0; merged source only | Required receipt/human gates; no LISTED/approval shortcut |
| `schema/catalog.schema.json` | Missing | Passport schema present at a different path; contract/equivalence not reviewed | Catalog and per-entry facet/receipt contract |
| `policy/security-rules.yaml` | Missing | None established | Human-approved security scope; not authored by this scaffold |
| `policy/registries.yaml` | Missing | None established | Approved source/registry rules with explicit license gates |
| `policy/vulnerability.yaml` | Missing | None established | Approved vulnerability/DB/KEV freshness and error semantics |
| `tools/tools.lock.json` | Missing | Tokenizer lock present at a different path; contract/equivalence not reviewed | Pinned approved tools and offline database identities |

The snapshot includes open normalization PR #17 at
`336a43e092f5da577555b82fa3049cc998e82f77` and the static-integrity proposal
[PR #18](https://github.com/ai4science-skills/skills/pull/18) at
`6886ec13a2002ac132c455fafe81184dd7949585`. PR #18's own documentation
describes a narrow static prerequisite, not full security admission. Its
`pull_request_target` and status-publication proposal requires separate review;
this observation does not authorize, deploy, execute or qualify it. Neither
open proposal establishes an independently enforced checker/policy authority.

Observed authority/control evidence:

- The pinned security workflow is `.github/workflows/security-prerequisites.yml`,
  Git blob `91b3264a482340f68526627988e3753e74b8d4fc`, exact UTF-8 source
  SHA-256 `6bd6086cd21f547890c008bd7eb39c2e1b8ecc766a54ea51033ee96c4c3ee11e`.
- Existing [main prerequisites run](https://github.com/ai4science-skills/skills/actions/runs/37731301351)
  reports exit 2 and BLOCKED, with no security stages run. Existing
  [check run](https://github.com/ai4science-skills/skills/actions/runs/37731301382)
  reports SUCCESS. These are previously produced CI observations, not newly
  executed tests and not scanner, rights or runtime authority.
- Main branch protection observed 09:50:55-09:50:59 UTC requires strict/up-to-date
  `check` from GitHub Actions app `15368`. The effective ruleset lookup, including
  parents, returned an empty list, confirmed at 09:57:57 UTC.
  Check-name/publisher restrictions do not bind
  an independently approved workflow revision or checker/policy byte digests.
- Independently approved authority origin, checker/policy bundle digests,
  authenticated approval and external enforcement receipts remain UNESTABLISHED
  in this bounded inspection. Candidate-controlled records cannot grant them.

The smallest remaining authority dependency is an approved origin with an exact
workflow revision and checker/policy digests, plus enforcement outside candidate
control binding that producer to the exact candidate revision. No placeholder
approval, signer, policy hash or readiness claim is supplied by this document.

Acquisition success does not grant rights or installation authority. Private v4
locks/reports, third-party code, scanner binaries and databases are not copied
into this PR. The existing plugin registry and vendoring architecture are unchanged.

## Rights

New index tooling follows the root index license scope. No license disposition,
clinical/biosafety policy, scientific validity or human approval is created.
Mixed, missing and custom/proprietary rights require their existing human gates.

## Agents and tools

`security_prerequisites.py` is a local, data-only inventory of 15 fixed paths.
It launches no commands and imports no candidate modules. Observed regular-file
bytes are bounded to 256 KiB per file, at most 3.75 MiB across the fixed inventory.
Observed links/reparse points and special files are rejected before reads. Reads
check captured bytes and their raw digest; they do not establish filesystem
isolation or eliminate all races. No directory traversal, `.git` inspection,
Git filters, stale `generated/` outputs or source-code execution is used.

JSON syntax checks reject duplicate/non-finite values, invalid UTF-8/surrogates,
excessive nesting and value counts. Policy YAML is not parsed. A file that exists
or contains valid JSON remains `PRESENT_UNVERIFIED`; this is not bootstrap,
schema, source-lock, signature, scanner or policy verification. The provided
JSON Schema describes the inventory and fixed `error-v0` CLI failure report.
Schema-only validation is insufficient: the mandatory stdlib semantic validator
enforces exact-once fixed inventory/stage identities, status/reason relationships
and the blocked inventory contract; it is not a general JSON
Schema or YAML validator. Report order/bytes are deterministic and contain no
wall-clock timestamps or absolute local paths. Revisions remain caller assertions.

The Actions file uses JSON syntax, a YAML 1.2 subset, to avoid ambiguous literal
continuations. It has the requested PR, main-push, Monday 06:17 UTC and manual
triggers, read-only contents permission, Ubuntu runner and 20-minute limit.
It introduces no Actions dependency and consumes no token. It performs no
checkout, fetch, inventory, Python/scanner/build execution, artifact/SARIF
publication or automatic remediation. It fails with exit 2 and always writes a
bounded summary of static `BLOCKED`/`NOT_RUN` declarations plus allowlisted event,
trigger/merge, head, base, workflow and run metadata. These are invocation fields,
not audited source receipts. It cannot observe absent files without acquisition.

## Tests

Run offline from the repository root, without installs:

```
python -I -S -B -m unittest discover -s tools -p 'test_security_prerequisites.py' -v
python -I -S -B tools/security_prerequisites.py --root . --revision 67c0b83faad8ac04c3d7549b795df044750bb810
```

The second example is for the inspected main snapshot; use the actual full
commit for another checkout. The revision is a caller assertion, not independent
source binding. It intentionally returns exit 2 and emits a BLOCKED inventory.
The existing importer test suite is separately identified when run; it is not
scaffold-only coverage.
Fixtures cover absent/corrupt/oversized JSON, observed link/special-file refusal,
unreadable paths, unapproved presence/hashes, forged success/coverage, sentinel
scanner/build modules that never execute, ignored Git/config/stale output data,
independent-root inventory determinism and CLI error sanitization. Workflow tests
check the JSON-syntax structure, event/permission contract, failure preservation
and bounded metadata bindings. These do not validate arbitrary YAML or scanner
execution. Bash syntax is checked separately without executing the workflow.

Historical local results from 2026-09-30 on Python 3.12.10: 20 focused fixtures
passed in 0.557s;
the 17 unchanged importer fixtures also passed in the earlier combined run.
The existing static checker passed for all 10 vendored skills. Both authored
Bash blocks passed parse-only checks. Actual-tree inventory confirmed 15 missing
prerequisites, nine NOT_RUN stages, seven UNOBSERVED facets and native exit 2.
That 15-missing count belongs to the original snapshot, not current main. This
documentation refresh does not repeat tests or execute candidate/scanner code.

Scanner crash, timeout, missing/malformed/unsupported receipts, stale or missing
DB/KEV evidence, exact per-locked-source scan coverage and two retained catalog
plus site generations have not been tested as implemented behavior: required
reviewed producers, adapters, receipts and builders have not been established.
Related file presence was not qualified or exercised in this refresh. These
remain explicit future acceptance tests, not fabricated passing stages.
Inventory reproducibility proves no build result.

## Security

Every stage is `NOT_RUN`, every STATIC/PROSE/BEHAVIOR/SCIENCE/TEST/EVALUATION/
FRESHNESS facet is `UNOBSERVED`, and the decision is always `BLOCKED`, including
when every prerequisite path exists. No receipt is accepted and no entry is
listed or installable. Unavailable/error/unsupported/stale scanners or DB/KEV
evidence must eventually block their stage; empty findings cannot substitute for
a complete successful receipt with scanner digest, database version/freshness,
source identity, coverage and explicit errors.

PR-controlled workflow YAML, checker and policy are not independent authority.
Required checks must not be bypassed. The observed PR #5/#6 merge states do not
verify their merge procedures or approval.
The prerequisite check remains intentionally failing. It must not be bypassed,
suppressed or relabeled to manufacture security admission; merged scaffold source
does not establish operational readiness.
The existing `check.yml` remains unchanged; it executes repository tests and a
science smoke helper, so it also must not be described as an independent security
gate. Read-only permissions constrain the token; they do not prove isolation or
eliminate the automatic job token. `ubuntu-latest` is a mutable runner label.
No `pull_request_target`, privileged workflow chain or native merge queue trigger
is added; no native queue configuration was established in this inspection.

Future candidate acquisition must exclude `.git`, isolate system/global Git
configuration and executable filters, avoid authenticated remotes/configuration,
and validate all lock-selected sources as bounded inert data. Future output must
use fresh external roots and reject links/special files/escapes and stale files.
Build catalog and site twice in independent roots, compare both and retain both;
volatile run timestamps/provenance belong in separate receipts. No candidate
builder, install hook or repository script may execute on the host. Rootless
isolation and canary denial remain unobserved; unknown execution stays blocked.

Official references: [GitHub token scope](https://docs.github.com/en/actions/concepts/security/github_token),
[PR workflow trust](https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target),
[Git remote persistence](https://git-scm.com/docs/git-remote#_discussion), and
[Git executable filter configuration](https://git-scm.com/docs/gitattributes.html#_filter).
`set -e` correctly propagates nonzero results; it is not itself a fail-open defect.
No confirmed credential exfiltration or write access is claimed.

## Rollback

An ordinary reviewed revert removes the original five additive scaffold files.
This refresh changes documentation only. There is no registry/pin migration,
skill/catalog/site release, remediation or deployment; draft source publication
is a separate review action. No workflow, code, schema, settings or gate changes
are part of this refresh, and the security admission decision remains blocked.

## Known limits

Next actions: establish an independent approved workflow plus immutable checker
and policy authority; review pinned offline tool/DB producers and typed per-source
coverage/error/freshness receipts; then implement deterministic catalog/site
builders with both output comparisons and the missing negative fixtures.
Foundation contract/human-gate review and an actually demonstrated disposable sandbox remain
dependencies. No full vulnerability pipeline is operational in this stage.
