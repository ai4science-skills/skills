# Evidence gate contract

Input document: `{"subject": str?, "claims": [Claim]}`.

Claim: `{"id": str, "text": str, "required": bool = true, "evidence": [Item] | [] | null}`.

Item: `{"path": str (relative, no `..`), "sha256": 64 lowercase hex?, "must_contain": [str]?}`.

Per-item result: `PASS`, `FAIL` (`MISSING_ARTIFACT`, `DIGEST_MISMATCH`, `TEXT_NOT_FOUND`), or `ERROR`.
Per-claim status is ERROR if any item errors, else FAIL if any item fails, else PASS; empty or null
evidence gives ABSTAIN with reason `NO_CHECKABLE_EVIDENCE_DECLARED`.

Aggregate: FAIL when a required claim is FAIL or ERROR; ABSTAIN when no required failure but at
least one ABSTAIN; FAIL_OPTIONAL_ONLY when only optional claims failed; PASS otherwise.

The report records `claims_sha256` (canonical JSON digest of the claims file) so a reviewer can
confirm which claims file produced it. Text matching is exact substring on UTF-8 decoded bytes.
