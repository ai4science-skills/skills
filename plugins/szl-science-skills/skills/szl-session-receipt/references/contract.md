# Session receipt contract

Schema `szl.session-receipt.v1`. Files are recorded per role (`inputs`, `code`, `outputs`) as
`{path, state: RECORDED|MISSING, size_bytes, sha256}`, sorted and de-duplicated by path.

`root_sha256` = SHA-256 over the newline-joined, sorted list of file digests.
`receipt_sha256` = SHA-256 of the canonical JSON of the body before `signature`, `methods_paragraph`,
`status` and `scope` are attached; `verify` recomputes it and reports `RECEIPT_TAMPERED` on mismatch.

Verification results per file: MATCH, MISMATCH, MISSING, RECORDED_AS_MISSING_NOW_PRESENT, ERROR (bad path).
Overall: MATCH only when the receipt digest is intact and every file matches.

Signing: `szl_sign_session_receipt(receipt, private_key_pem)` imports `szl_receipt._sign.sign_dsse` lazily.
If the package is absent or signing fails, `signature.state` is UNSIGNED with the reason. Keys are never
read by the kernel; the CLI passes the PEM bytes you point it at.
