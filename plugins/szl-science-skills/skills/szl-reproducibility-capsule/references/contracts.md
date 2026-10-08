# Exact-byte manifest and inert replay contract

## Manifest

`szl_make_capsule(root, files, metadata=None, replay=None)` retains schema
`szl.reproducibility-capsule.v1` and existing string file lists. A selected file may also
be exactly `{"path": "source.py", "role": "source"}`. Supported roles are `input`,
`source`, `environment`, `analysis_plan`, `output`, `protocol`. Each unique path is
canonical relative POSIX syntax (at most 512 characters), points to a regular file
inside the declared non-symlink root, and has no symlink/junction/reparse component.
Common credential/private configuration path names are excluded. These guards are
not a secret scanner; inspect selected file content and metadata before sharing.

At most 128 files, 8 MiB each and 32 MiB retained total are accepted. Hashing is streaming,
bounded and checks file identity/size/modification time before and after reading. No
directory sweep or file packaging occurs. Metadata must be finite JSON, at most 64 KiB
and at most 32 nesting levels; common credential field names are refused.
Use a quiescent, trusted project root. Portable path/identity checks do not provide
race-proof filesystem confinement against a malicious concurrent path replacement;
untrusted artifact inspection still needs an independently enforced filesystem sandbox.

The manifest binds sorted paths, sizes, SHA-256 bytes, optional roles and metadata with
an unsigned canonical self-digest. The verifier validates the schema and entries, then
reports sorted `MATCH`, `CHANGED`, `MISSING`, `UNREADABLE_OR_UNSAFE_PATH` file results.
An altered self-digest reports `MANIFEST_CHANGED`. Self-consistent replacement of the
entire unsigned record remains undetectable without an independently retained anchor.

## Replay declaration

A replay is exactly these fields:

```json
{
  "schema": "szl.offline-replay.v1",
  "argv": ["python", "analysis.py", "--seed", "7"],
  "environment": {"path": "environment.json", "sha256": "64 lowercase hex characters"},
  "analysis_plan": {"path": "plan.json", "sha256": "64 lowercase hex characters"},
  "seed": 7,
  "limits": {"network": "denied", "process_spawn": "denied", "secret_access": "denied", "max_seconds": 30, "max_memory_mib": 128},
  "expected_outputs": [{"path": "result.txt", "sha256": "64 lowercase hex characters", "comparison": {"mode": "exact_bytes"}}]
}
```

The illustrative digest descriptions above are explanatory notation, not valid digests.
Use digests of actual selected bytes. All five `input/source/environment/analysis_plan/
output` roles must exist. `argv` contains 2..64 bounded nonempty strings. The interpreter
is `python` or `python3`; its second element is a retained canonical `.py` source path
that must not start with `-`. Interpreter options and the stdin marker are refused,
including a retained filename such as `-cprint(7)#.py`. A canonical nested path whose
basename starts with a dash is a path, while a leading `./` remains noncanonical. Shell-like,
multiline or credential-like arguments are refused. All arguments are inert text, never
passed to an interpreter. This validates a declaration, not the safety of its source.

Environment and analysis-plan references must bind to matching path/role/digest entries.
Seed is an integer 0..4294967295. Network, process spawning and secret access are
declared `denied`; resource declarations are integer 1..300 seconds and 16..1024 MiB.
These statements are not enforcement. Establish a real approved sandbox separately.

Declare 1..64 unique expected outputs, exactly covering retained output-role files.
Each output's retained reference digest must match its manifest entry. Comparison is
`{"mode": "exact_bytes"}` or `{"mode": "numeric_tolerance", "absolute_tolerance":
0.001, "relative_tolerance": 0.01, "predeclared": true}` with finite nonnegative values.
The helper verifies that this policy exists; it does not parse output numbers, apply
tolerances, establish scientific appropriateness or prove that the policy predates results.

`replay_ready` is true only for a complete valid declaration and all retained byte matches.
Missing/changed/unsafe bytes make it false. No replay field gives false/`NOT_SPECIFIED`.
Execution, sandbox capability denial and tolerance application remain respectively
`NOT_RUN`, `DECLARED_ONLY`, `NOT_RUN`; scientific performance stays `NOT_MEASURED`.
A human must review sensitive scientific use, executable source and licensing separately.

## Acceptance and provenance

`tests/test_science_attempts_replay.py` creates only synthetic temporary artifacts. It
checks full replay readiness without execution, changed/missing/tampered records,
duplicate roles/outputs, traversal, secret-like fields, symlink/reparse rejection,
environment/plan/output digest disagreement, invalid tolerances and denied-capability
declarations. Test execution evidence is reported separately; authored tests alone do
not establish successful execution or agent efficacy.

Inspected base: `szl-holdings/szl-skills` commit
`9668f1571315e93ca2059b9a44f12beef483532d`, paths
`skills/szl-reproducibility-capsule/{kernel.py,SKILL.md,scripts/run.py,assets/example.json}`.
The bounded role/replay validator, fixtures and tests are independently authored under
the existing repository Apache-2.0 license. No third-party skill code, proprietary SZL
platform content, CC-BY text, model weights or dataset rows were imported.
