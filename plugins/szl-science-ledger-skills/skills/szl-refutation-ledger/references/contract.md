# Contract: szl.refutation-ledger.v1

Ledger: `{"schema": "szl.refutation-ledger.v1", "title": str, "entries": [entry, ...]}`.

Entry: `{"seq": int, "kind": "claim"|"attempt"|"withdrawal", "recorded_at": "YYYY-MM-DDTHH:MM:SSZ", "body": {...}, "prev_sha256": hex64, "entry_sha256": hex64}` where
`entry_sha256 = sha256(canonical(entry without entry_sha256))`, canonical = sorted keys, compact separators, ASCII. The first entry's `prev_sha256` is 64 zeros.

Bodies:

- claim: `claim_id` (required, `[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}`), `statement` (required), `source` (object, free), `depends_on` (list of previously recorded claim ids), `effect` (optional `{"metric", "value", "ci": [lo, hi]}`).
- attempt: `attempt_id` (required, unique), `claim_id` (recorded claim), `outcome` in `REPLICATED | NOT_REPLICATED | INCONCLUSIVE`, optional `n` (non-negative int), `effect`, `preregistered` (bool), `receipt` (`{"sha256": hex64, "path" or "url"}`), `actor`, `notes`.
- withdrawal: `claim_id` (recorded claim), `reason` (required).

Commands and exit codes: `init`, `append`, `verify`, `status` exit 0 when they ran (read `status`), 2 on ERROR. `append` refuses a ledger whose chain does not verify and never rewrites earlier entries.

`verify` -> `VALID {entries, head_sha256, claims, attempts}` or `BROKEN {at_seq, reason}` or `ERROR`.

`status` -> `RECORDED` with per-claim rows `{claim_id, statement, state, attempts: {REPLICATED, NOT_REPLICATED, INCONCLUSIVE}, attempts_total, unreceipted_attempts, preregistered_attempts, depends_on, foundation: SOUND|SHAKEN|UNKNOWN, foundation_trace}`, `summary`, `shaken_claims`, `unreceipted_attempts_total`, `limits`.
