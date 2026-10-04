# Literal dependency discovery, with admission still BLOCKED

`tools/dependency_inventory.py` supplies bounded discovery evidence for a future
reviewed dependency producer. It inventories every tracked regular file below
the plugin roots named by the selected revision's registry, records exact Git
blob identities and captured byte hashes, parses literal Python imports, and
reads plain `distribution==version` requirements declarations. It does not
install packages, resolve a dependency closure, scan vulnerabilities, execute
skills, or approve reuse. Exit 0 means scoped discovery completed; the report
still says `decision: BLOCKED` and `installable: false`.

This separate proposal preserves PR #18's base-owned static integrity checker,
PR #20's released skill pins, the deliberately blocked security scaffold,
existing policies, workflows, and statuses. It creates none of the missing
security-stage paths merely to satisfy a presence check. The nine-stage pipeline
and independent checker/workflow/policy authority remain unestablished.

## Source and parsing contract

The caller supplies a local repository and a full 40-character commit SHA. The
tool walks the entire Git tree recursively, rather than trusting a truncated
provider listing, and checks each observed commit/tree and selected blob against
its Git SHA-1 object identity. Reports bind the root tree, registry SHA-256,
complete tracked-leaf count, selected roots, selected file count/bytes, and each
selected file's mode, Git blob ID, byte length, and SHA-256. Source membership
comes from the observed Git tree. Repository ownership is `CALLER_ASSERTED` and
upstream source parity stays `UNKNOWN`; an arbitrary local object is not proof
that GitHub or an upstream author published it.

Only the trusted Git binary's `cat-file` object-reading commands run. No checkout,
fetch, candidate script, Git filter, or hook runs. Inherited `GIT_*` settings are
discarded; system/global configuration and credential prompting are disabled;
`GIT_NO_REPLACE_OBJECTS=1` applies to every object read. Lazy fetching is disabled
through both `--no-lazy-fetch` and `GIT_NO_LAZY_FETCH=1`; an empty protocol
allowlist refuses every transport. Per-command configuration clears credential
helpers and disables hooks/fsmonitor, in addition to the noninteractive prompt
setting. A missing local object therefore fails instead of fetching it. Git
must support `--no-lazy-fetch`; an unsupported version remains unavailable.
Normal local repository
configuration and Git object storage remain part of the local trusted computing
base. Git executable selection uses the operator's PATH. This is not an
adversarial process sandbox or independent hosted gate.

Paths use a bounded portable ASCII grammar; case collisions, traversal, reserved
device names, unregistered plugin roots, and selected links/submodules are
rejected. Limits cover 5,000 tree entries, 16 directory levels, 512 KiB per
object, 32 MiB captured tree/selected bytes, 30,000 AST nodes, 5,000 findings per
file, 20,000 findings per run, two MiB output, and 20 seconds per Git command. The Python parser version
is recorded. Parsing errors remain `UNKNOWN`. Parsing bounded text does not
prove resource isolation against every possible interpreter defect.

Literal imports are syntactic observations. Conditional/dead-code imports,
shadowed aliases, dynamic runtime behavior, relative import resolution, import
name to distribution mapping, stdlib versus third-party classification, and
transitive dependencies are not established. Obvious `__import__` and
`importlib.import_module` calls retain bounded valid module literals or emit a
fixed unresolved reason. Other runtime import construction remains unknown.
Neither import presence nor a plain version pin establishes a package artifact.

Only plain exact requirements pins are supported. URLs, editable installs,
includes, markers, extras, ranges, line continuations, options, hashes, and
unsupported syntax produce `UNKNOWN` with line number and hash; their raw
content is not echoed. Other recognized declaration formats, including
`pyproject.toml`, setup files, JavaScript lock files and environment YAML, remain
`UNKNOWN`. Opaque skill documents/data retain byte coverage without pretending
to have dependency interpretation. No credentials, services, or database are
needed. No network request or provider mutation occurs.

## Reproduce

From the trusted repository root, with Python 3.9+ and Git already installed:

```
python -S -B -m unittest discover -s tools -p 'test_dependency_inventory.py' -v
python -S -B tools/dependency_inventory.py --git-dir . --revision FULL_COMMIT_SHA
```

The focused suite covers exact source membership/hash coverage, dirty worktree
independence, ignored Git replacement objects, configured filter/hook canaries,
an actual promisor-remote execution canary with missing local objects,
literal/dynamic import handling, requirements credential redaction, unsupported
declarations, malformed and oversized objects, path/link/submodule refusal,
parser/finding/output limits, deterministic output and typed CLI failures.
Fixtures do not establish vulnerability clearance, science, rights, freshness,
host registration or deployment. Existing functional CI may run these tests;
it is not the future independent security admission workflow.

The index tooling follows the root MIT license. Vendored skill licenses and
bytes are unchanged. An ordinary reviewed revert removes this tool, focused
tests and document without changing registry pins or provider state. A future
owner-approved workflow must bind its reviewed checker, policy, input source,
toolchain/database provenance and complete error/coverage receipts before
dependency or vulnerability admission can be established.

The [official Git documentation](https://git-scm.com/docs/git#Documentation/git.txt---no-lazy-fetch)
defines the lazy-fetch switch and corresponding environment flag, and
[Git's protocol allowlist](https://git-scm.com/docs/git#Documentation/git.txt-GITALLOWPROTOCOL)
defines refusal of protocols outside the explicit list. Those configuration
contracts complement the locally exercised promisor canary; they do not prove
a general sandbox.
