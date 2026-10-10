# Static receipt normalization, not admission

`tools/normalize_findings.py` is a stdlib-only, data-only contract for a single
static scanner's claimed file coverage and findings. It consumes two bounded
JSON files: a target declaration (`ai4s.static-scan-target/v0`) and a scanner
receipt (`ai4s.static-scan-receipt/v0`). Both name one public GitHub repository,
exact commit, skill subtree, and a per-file SHA-256 inventory. The receipt
also names its producer digest, status, scanned files, findings and explicit
error codes. Paths must be portable and inside the declared skill subtree.

The normalizer rejects duplicate JSON keys, non-finite numbers, oversized
inputs, links/reparse-point inputs, case-colliding or duplicate paths, hash or
source mismatch, out-of-scope findings, and a `COMPLETE` claim without exact
file coverage and zero errors. Error, timeout and unsupported states require
an explicit error; they cannot become an empty-findings success. On accepted
input it emits deterministic `ai4s.findings-normalization/v0` JSON.

Every output remains `decision: BLOCKED`, `installable: false` and exits 2,
including complete zero-finding receipts. The producer digest, source commit,
file hashes and coverage are **caller assertions**. This tool neither reads
source bytes nor executes a scanner, checks its binary/tool lock, authenticates
the receipt, verifies database freshness, applies an approved policy, or
establishes scientific, legal or safety fitness. Findings are untrusted data.
It is one component of the blocked security-prerequisite inventory, not a way
to turn that workflow green. Do not wire it as an admission check until the
independent workflow, producer/tool lock, source acquisition, typed scanner
receipts, and policy are reviewed and tested end to end.

Run the focused offline tests:

```text
python -I -S -B -m unittest discover -s tools -p test_normalize_findings.py -v
```

To inspect a pair of locally supplied JSON files:

```text
python -I -S -B tools/normalize_findings.py --target TARGET.json --receipt RECEIPT.json
```

Exit 2 is intentional and must not be suppressed. This is not a scanner
installation, hosted-service request, release, or listing decision.
