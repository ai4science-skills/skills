# Supplied-evidence contract v1

`source` and `host-export` are resource-only directories containing SKILL.md and
all scripts/references/assets. Every file name, byte length and SHA-256 participates
in a canonical JSON manifest digest. The directories must be stable during reading.
This is observational checking, not a sandbox against a hostile concurrent filesystem.
No extra export files are permitted. A host display-name alias is recorded explicitly;
the exported SKILL.md payload must retain its original source identity and bytes.
The identity field must use one literal unquoted `name: lowercase-hyphenated-name`
line. Names start with a lowercase letter and are at most 64 characters; ambiguous
implicit-type tokens (`true`, `false`, `null`, `yes`, `no`, `on`, `off`, `y`, `n`)
are rejected. Numeric/date-like names are outside this subset.
Frontmatter is a flat mapping of unique literal unquoted identifier keys to nonempty
single-line scalar values. Blank lines and comments are allowed. Indented non-comment
content, empty values, duplicate fields, quoted/merge keys, block or flow structures,
anchors, aliases, tags and multiline quoted values fail closed. Single-quoted values
must close on the same line (doubled quotes are allowed); double-quoted values must
be valid JSON strings on one line. Plain values cannot start with YAML structural
indicators or contain a colon followed by ASCII space/tab. Quoted names are rejected.
Structural trimming uses ASCII space/tab only. The checker does not implement
general YAML interpretation or importer security.
CRLF, CR and LF are normalized only for structural frontmatter checks, which all
use the same line view. Retained bytes and bundle hashes are never normalized.
Other Python `splitlines` separators (VT, FF, NEL, LS and PS) are rejected inside
frontmatter; they may occur in the opaque Markdown body. This is a conservative
subset, not a general YAML parser.

Trials JSON has exactly these fields:

```json
{
  "schema_version": 1,
  "evidence_kind": "operator_supplied_export",
  "source_bundle_sha256": "<64 lowercase hex characters>",
  "host_bundle_sha256": "<64 lowercase hex characters>",
  "imported_skill": "szl-example",
  "cases": [
    {
      "case_id": "related-task",
      "kind": "positive",
      "task_path": "tasks/positive.txt",
      "task_sha256": "<64 lowercase hex characters>",
      "result_path": "results/positive.txt",
      "result_sha256": "<64 lowercase hex characters>",
      "invocation_reported": true,
      "outcome": "PASS"
    },
    {
      "case_id": "irrelevant-control",
      "kind": "negative",
      "task_path": "tasks/negative.txt",
      "task_sha256": "<64 lowercase hex characters>",
      "result_path": "results/negative.txt",
      "result_sha256": "<64 lowercase hex characters>",
      "invocation_reported": false,
      "outcome": "PASS"
    }
  ]
}
```

The other accepted evidence kind is `synthetic_fixture`. Both remain supplied
declarations, never authenticated host evidence. PASS is a declared outcome, not
one measured by this checker. Task hashes must differ; this does not prove relevance.
Case IDs are unique lowercase hyphenated identifiers. Outcomes are PASS, FAIL or
UNAVAILABLE; a FAIL/UNAVAILABLE or contradictory trigger declaration rejects consistency.

Bounds: 1 MiB/file, 4 MiB/bundle, 128 files, 512 nodes, depth 12, 50 trials,
4 MiB total retained task/result bytes. Nonfinite JSON, duplicate/unknown keys,
unsafe relative paths, Windows reserved names, Unicode normalization aliases,
case collisions, symlinks and reparse points are rejected. Files are never imported
or executed. On Windows, concurrent filesystem replacement is outside the trust
boundary; use stable owner-controlled exported directories.

CLI exit 0 means CONSISTENT_SUPPLIED_EVIDENCE only; 2 is INCOMPLETE; 1 is REJECTED.
`actual_host_invocation` always stays NOT_VERIFIED and `scientific_result_validity`
stays NOT_EVALUATED. Any source update changes its digest and invalidates earlier
trial binding. Preserve earlier receipts; this pilot has no write/update operation.
