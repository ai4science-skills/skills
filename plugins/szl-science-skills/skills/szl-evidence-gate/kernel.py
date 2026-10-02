"""szl-evidence-gate — does each claim have a checkable artifact behind it?

Stdlib only. Offline. Reads only the files the claims file names.

Verdicts per claim (same vocabulary as the published szl-evidence-mandate gate):
  PASS    every declared evidence item exists and matches its declared digest
  FAIL    a declared evidence item is missing, or its bytes differ from the
          declared digest, or an expected text snippet is absent
  ABSTAIN the claim declares no checkable evidence (nothing to verify)
  ERROR   the claim or evidence record is malformed

Aggregate: FAIL if any required claim FAILs or ERRORs; otherwise ABSTAIN if any
claim is ABSTAIN; otherwise PASS. A PASS proves integrity and presence of the
declared artifacts. It does not prove the claim is true.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

SCHEMA = "szl.evidence-gate-report.v1"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def szl_canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def szl_sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_path(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or relative.startswith(("/", "\\")) or ".." in Path(relative).parts:
        raise ValueError("evidence path must be relative and may not escape the root: %r" % (relative,))
    if ":" in relative.split("/")[0] and os.name == "nt":
        raise ValueError("evidence path must be relative: %r" % (relative,))
    return (root / relative).resolve()


def _check_item(root: Path, item) -> dict:
    if not isinstance(item, dict) or not isinstance(item.get("path"), str):
        return {"path": item.get("path") if isinstance(item, dict) else None, "status": "ERROR",
                "reason": "evidence item must be an object with a string path"}
    record = {"path": item["path"], "status": "PASS", "reason": None, "observed_sha256": None,
              "declared_sha256": item.get("sha256"), "size_bytes": None}
    try:
        target = _safe_path(root, item["path"])
        if not str(target).startswith(str(root.resolve())):
            raise ValueError("path escapes root")
    except ValueError as exc:
        record.update(status="ERROR", reason=str(exc))
        return record
    if not target.is_file():
        record.update(status="FAIL", reason="MISSING_ARTIFACT")
        return record
    data = target.read_bytes()
    record["observed_sha256"] = szl_sha256_bytes(data)
    record["size_bytes"] = len(data)
    declared = item.get("sha256")
    if declared is not None:
        if not isinstance(declared, str) or not _HEX64.match(declared):
            record.update(status="ERROR", reason="declared sha256 must be 64 lowercase hex characters")
            return record
        if declared != record["observed_sha256"]:
            record.update(status="FAIL", reason="DIGEST_MISMATCH")
            return record
    snippets = item.get("must_contain")
    if snippets is not None:
        if not isinstance(snippets, list) or not all(isinstance(s, str) and s for s in snippets):
            record.update(status="ERROR", reason="must_contain must be a list of non-empty strings")
            return record
        text = data.decode("utf-8", errors="replace")
        missing = [s for s in snippets if s not in text]
        if missing:
            record.update(status="FAIL", reason="TEXT_NOT_FOUND", missing_text=missing)
            return record
    if record["declared_sha256"] is None and snippets is None:
        record["reason"] = "PRESENCE_ONLY"
    return record


def szl_gate_claim(root: Path, claim) -> dict:
    if not isinstance(claim, dict) or not isinstance(claim.get("id"), str) or not isinstance(claim.get("text"), str):
        return {"id": claim.get("id") if isinstance(claim, dict) else None, "status": "ERROR",
                "reason": "claim must be an object with string id and text", "evidence": []}
    evidence = claim.get("evidence", [])
    required = bool(claim.get("required", True))
    if evidence is None or evidence == []:
        return {"id": claim["id"], "text": claim["text"], "required": required, "status": "ABSTAIN",
                "reason": "NO_CHECKABLE_EVIDENCE_DECLARED", "evidence": []}
    if not isinstance(evidence, list):
        return {"id": claim["id"], "text": claim["text"], "required": required, "status": "ERROR",
                "reason": "evidence must be a list", "evidence": []}
    items = [_check_item(root, item) for item in evidence]
    statuses = {i["status"] for i in items}
    if "ERROR" in statuses:
        status, reason = "ERROR", "MALFORMED_EVIDENCE"
    elif "FAIL" in statuses:
        status, reason = "FAIL", ",".join(sorted({i["reason"] for i in items if i["status"] == "FAIL"}))
    else:
        status, reason = "PASS", "ALL_DECLARED_EVIDENCE_PRESENT"
        if all(i.get("reason") == "PRESENCE_ONLY" for i in items):
            reason = "PRESENCE_ONLY_NO_DIGESTS_DECLARED"
    return {"id": claim["id"], "text": claim["text"], "required": required, "status": status,
            "reason": reason, "evidence": items}


def szl_evidence_gate(root, claims_document) -> dict:
    root = Path(root)
    if not isinstance(claims_document, dict) or not isinstance(claims_document.get("claims"), list):
        return {"schema": SCHEMA, "status": "ERROR", "reason": "document must contain a claims list",
                "claims": [], "counts": {}}
    results = [szl_gate_claim(root, c) for c in claims_document["claims"]]
    counts = {k: sum(1 for r in results if r["status"] == k) for k in ("PASS", "FAIL", "ABSTAIN", "ERROR")}
    required_bad = [r["id"] for r in results if r.get("required", True) and r["status"] in ("FAIL", "ERROR")]
    if required_bad:
        status = "FAIL"
    elif counts["ABSTAIN"]:
        status = "ABSTAIN"
    elif counts["ERROR"] or counts["FAIL"]:
        status = "FAIL_OPTIONAL_ONLY"
    else:
        status = "PASS"
    return {
        "schema": SCHEMA,
        "status": status,
        "subject": claims_document.get("subject"),
        "claims_sha256": szl_sha256_bytes(szl_canonical(claims_document).encode()),
        "counts": counts,
        "required_failures": required_bad,
        "claims": results,
        "scope": "Presence, byte digests and declared text of named artifacts under the root. "
                 "A PASS does not establish that any claim is scientifically true.",
    }
