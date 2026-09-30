# Phase A static comparison

This additive tooling reads skill repositories as data. It does not install,
import, test, or execute skill programs. A diagnostic finding, a recognized
license label, or a matching content hash grants no approval to reuse, list,
install, experiment, or release a skill.

The canonical implementation is `tools/static_audit.py`, ported from the
inspected `0.1.0-review.1` proposal. `static_io.py` retains its bounded snapshot,
link/reparse rejection, exact-byte hashing, fresh-output, and safe presentation
helpers. `static_metadata.py` retains the bounded YAML subset and adds scoped
license evidence. This deliberately uses a new diagnostic contract; the
separately owned trust-foundation adapter must not silently accept it as its
older reviewed contract.

## License evidence

The skill directory and every ancestor through the repository root are
examined. The nearest applicable LICENSE controls the main evidence path;
an unknown or custom local license cannot fall back to a familiar root label.
Other ancestor scopes, nested subtree licenses, SOURCE.json declarations,
NOTICE evidence, explicit SPDX expressions, and frontmatter declarations are
retained with exact paths and SHA256 values. Source hashes bind provenance
assertions to captured bytes; they do not grant permission. Conflicts, custom
terms, missing terms, malformed evidence, and unresolved mixed scopes retain
`LICENSE_REVIEW`. Human license, biosafety, and clinical approvals remain
`NOT_GRANTED`.

## Static coverage

The scanner implements `bounded-subset-v1` frontmatter validation and inherited
lexical rules, with bounded Python AST inspection. Advanced YAML is
`UNSUPPORTED`; description semantics and dynamic references are unassessed.
The SKILL.md line contract is strictly fewer than 500 physical lines.

Every skill file receives a path, size, byte hash, and coverage status. Invalid
UTF-8, NUL-containing data, files larger than 2,000,000 bytes, Python AST gaps,
finding limits, and trailing unscanned paths prevent complete static coverage.
Missing or unreadable SKILL.md text has `spec: NOT_RUN`, with no fabricated
line count. The scanner never emits an unqualified aggregate PASS.

Static, license, safety, token, and evaluation observations remain separate.
Skill tests are `NOT_RUN`, safety and network are `UNASSESSED`, and installable
is always false. Caller-held protected snapshots are required; these readers
are not an OS sandbox against concurrent adversarial ancestor replacement.
Hard-link provenance is not established.

## Five immutable source tuples

`tools/static_compare.py` accepts a hash-pinned proposed v5 lock and retained
archives for exactly these source commits:

| Repository | Commit |
|---|---|
| ai4science-skills/skills | 41946b95fd34872118894b1c4cee4fa08788a52e |
| K-Dense-AI/scientific-agent-skills | 65d6e786832e2c52832713117bbbf5096b56f77f |
| google-deepmind/science-skills | 68832757cbbf941c620b71df5756cf6e5cc287b0 |
| orchestra-research/AI-research-SKILLs | 773a52944ba4747a18bd4ae9ade53fff041adcbc |
| szl-holdings/szl-skills | 54890f38c4b5abeefb13441e6f3cfd6f80c34769 |

The index baseline is explicit; the other four commits are carried forward
from the unchanged v4 lock. A later SZL main is a different source tuple.
Matching skill names do not merge publishers, pins, paths, or differing bytes.
Archive bytes, regular-file manifests, reconstructed Git trees, literal skill
census, tool/ruleset hashes, and per-path findings bind the produced receipts.
Missing inputs and failed verification stay blocked. Acquisition counts alone
are not static or token results.

## Reporting and stop boundary

Compare the same source tuple and byte hashes under explicitly named before
and after tool contracts. Keep source-version changes separate from checker
changes. The supplied ten-spec-PASS and security-count claims remain unverified
without their producing receipt; a new measurement does not authenticate those
earlier claims.

Only Phase A items 1–3 are implemented. Scorecard, Dependency-Track, hourly
SBOM sync, graph/dashboard, experiments, workflow hardening, deployment, and
releases are `NOT_RUN`. Existing workflows and SZL skill packages are owned
separately and are not changed by these tools.

## Pinned token counting contract

The counter uses OpenAI's `tiktoken==0.12.0`, the official PyPI Linux x86_64 CPython 3.12 wheel, and `cl100k_base`. It also verifies the retained official `regex==2025.9.18` wheel. The complete artifact URLs, exact versions, byte sizes, SHA256 values, encoding parameters, and machine-readable counting contract are in `tools/tokenizer.lock.json`.

The wheel hashes are `edde1ec917dfd21c1f2f8046b86348b0f54a2c0547f68149d8600859598769ad` for tiktoken and `4f130c3a7845ba42de42f380fff3c8aebe89a810747d91bcf56d40a069f15352` for regex. The official encoding bytes hash to `223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7`. The contract's canonical JSON SHA256 is `0ad1a8813b522d45c4a2dfc403535f0175234c16352f9b07cfa90775b64fe391`.

Acquisition uses only bounded official PyPI metadata/wheel downloads and the official OpenAI encoding URL. Each wheel must match its official registry SHA256 before any package code is used. Counting itself has no downloader and makes no network, model, provider, or API calls. It does not invoke pip, install hooks, source builds, or candidate imports. It privately expands verified wheels, verifies every expanded byte, restricts import lookup to the verified expansion and standard library, and constructs `Encoding` directly from the verified asset and pinned parameters. Tokenizer extension discovery and tiktoken's requests downloader are not called. Both `-I` and `-S` are required. The shipped lock intentionally supports CPython 3.12 on Linux x86_64 with glibc 2.28 or newer; other platforms produce `NOT_RUN`.

Each captured input file is decoded as strict UTF-8 without replacing errors, removing a BOM, normalizing Unicode, or rewriting line endings. NUL-containing and invalid UTF-8 files are explicit `NOT_RUN` entries with no token field. `encode_ordinary` treats strings that resemble special tokens as ordinary text. Empty valid fragments may have a measured zero; unavailable or unverified tokenizers never generate zero placeholders.

Every literal `SKILL.md` is counted in full and independently split into exact raw byte fragments. Eager metadata is the raw top-level `name` and `description` field lines, including subsequent indented, blank, or comment lines until the next top-level field. YAML keys, punctuation, quoting, and block scalar syntax remain in the counted text. The remaining frontmatter, including its delimiters, and the exact body following the closing delimiter are activation-time fragments. Missing delimiters, ambiguous top-level syntax, or duplicate/missing indexed fields yield `NOT_RUN` for that partition. This is a byte-span contract, not semantic YAML interpretation or a proof of a particular agent loader's behavior.

Other files belong to the closest enclosing literal skill directory. Their first relative component assigns `lazy_references`, `lazy_scripts`, or `lazy_assets`; all other files are `lazy_other`. Nested skill directories own their own files. Repository files outside skill directories are `repo_other`. Lazy-file counts describe the cost of explicitly loading their full text; they are not assumed to be loaded eagerly, and scripts are never executed.

Full files and contiguous fragments are each encoded independently. Fragment sums may differ from a full-file count because tokenizer boundaries differ. The receipt adds no model chat wrapper, separators, tool schemas, or provider overhead. Raw metadata counts therefore should not be described as an actual model prompt charge.

Receipts retain every source repository/full 40-character pin/path tuple and every complete file SHA256. The snapshot input SHA256 is the reviewed scanner's digest over canonical UTF-8 relative paths and exact captured bytes. A separate unique-file total deduplicates only by complete file SHA256 within a source; matching names never collapse sources or pins. Each measured row binds the source tuple, snapshot digest, contract SHA256, and tokenizer receipt SHA256. The tokenizer receipt includes exact package versions, wheel hashes, encoding hash, lock hash, Python/platform, and loading assumptions.

Source status is `COUNTED` only when every captured file and every raw skill partition is counted and input coverage is complete. Missing, skipped, erroneous, non-UTF-8, or NUL-containing content keeps the complete token facet `NOT_RUN`; measured subset totals remain explicitly labeled and cannot become a full-source total. Static, license, safety, token, and evaluation facets remain separate.

Use an empty, dedicated writable runtime parent outside candidate roots. Runtime readers reject symlinks/reparse points, changed files, unbounded artifacts, and invalid wheel members. Callers must hold candidate snapshots immutable; these checks are not an operating-system sandbox against concurrent hostile filesystem replacement, and hard-link provenance is not established.

Example, using retained official artifacts:

```text
python3 -I -S -B tools/token_count.py SNAPSHOT_ROOT --repo https://github.com/OWNER/REPO --pin FULL40CHARCOMMIT --artifacts ARTIFACT_DIRECTORY --runtime-parent EMPTY_WRITABLE_DIRECTORY
python3 -I -S -B tools/test_token_count.py ARTIFACT_DIRECTORY EMPTY_WRITABLE_DIRECTORY
```

The CLI exits 0 for `COUNTED` and 2 for `NOT_RUN`. Pinning and receipt integrity do not approve licensing, biosafety, installation, experiments, or later phases.
