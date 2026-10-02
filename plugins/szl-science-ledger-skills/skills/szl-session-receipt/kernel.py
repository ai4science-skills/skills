"""szl-session-receipt — a methods section that can be re-verified.

Stdlib only. Offline. Optional signing through the separately installed
szl-receipt-dsse package (never required; absence is recorded, not hidden).

Input: a session manifest the analyst or agent writes while working:

  {
    "project": "...", "session_id": "...",
    "started_at": "...Z", "finished_at": "...Z",
    "actor": {"kind": "agent"|"human", "name": "..."},
    "inputs":  ["data/raw.csv", ...],          # files read
    "code":    ["analysis.py", ...],           # scripts/notebooks executed
    "outputs": ["results/table1.csv", ...],    # files produced
    "commands": ["python analysis.py --seed 7", ...],
    "environment": {"python": "3.12.1", "platform": "...", "packages": {"numpy": "2.1.0"}},
    "notes": "free text"
  }

Output: a receipt that records size and SHA-256 of every listed file by role,
a root digest over the whole receipt body, the commands and environment as
declared, and a plain-language Methods paragraph. `verify` re-hashes every
file and reports MATCH / MISMATCH / MISSING per file.

What a MATCH means: the files on disk are byte-identical to the ones recorded.
It does not mean the analysis was correct, that the commands were the only
ones run, or that the declared environment was the real one.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

SCHEMA = "szl.session-receipt.v1"
ROLES = ("inputs", "code", "outputs")


def szl_canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _safe(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or relative.startswith(("/", "\\")) or ".." in Path(relative).parts:
        raise ValueError("paths must be relative to the root and may not contain ..: %r" % (relative,))
    return root / relative


def _file_record(root: Path, relative: str) -> dict:
    target = _safe(root, relative)
    if not target.is_file():
        return {"path": relative, "state": "MISSING", "size_bytes": None, "sha256": None}
    data = target.read_bytes()
    return {"path": relative, "state": "RECORDED", "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def szl_methods_paragraph(receipt: dict) -> str:
    files = receipt["files"]
    n = {r: len(files[r]) for r in ROLES}
    env = receipt.get("environment") or {}
    actor = receipt.get("actor") or {}
    who = {"agent": "an AI agent", "human": "the analyst"}.get(actor.get("kind"), "the analyst")
    if actor.get("name"):
        who += f" ({actor['name']})"
    pk = env.get("packages") or {}
    pk_txt = ", ".join(f"{k} {v}" for k, v in sorted(pk.items())[:8]) + (" and others" if len(pk) > 8 else "")
    py = f"Python {env['python']}" if env.get("python") else "an undeclared Python version"
    parts = [
        f"Analysis for {receipt.get('project') or 'this project'} was performed by {who} between "
        f"{receipt.get('started_at') or 'an unrecorded start'} and {receipt.get('finished_at') or 'an unrecorded end'}.",
        f"It read {n['inputs']} input file(s), executed {n['code']} script(s) via {len(receipt.get('commands') or [])} recorded command(s), "
        f"and produced {n['outputs']} output file(s); the SHA-256 digest of every file is recorded in session receipt "
        f"{receipt['receipt_sha256'][:16]} (root digest {receipt['root_sha256'][:16]}).",
        f"The environment was declared as {py}" + (f" with {pk_txt}" if pk_txt else "") + ".",
    ]
    missing = [f["path"] for r in ROLES for f in files[r] if f["state"] == "MISSING"]
    if missing:
        parts.append(f"{len(missing)} declared file(s) were missing when the receipt was written and are recorded as MISSING.")
    sig = receipt.get("signature", {})
    parts.append("The receipt is signed (DSSE)." if sig.get("state") == "SIGNED"
                 else "The receipt is unsigned; integrity can be re-verified by re-hashing the listed files, authenticity is not established.")
    return " ".join(parts)


def szl_make_session_receipt(root, manifest: dict) -> dict:
    root = Path(root)
    if not isinstance(manifest, dict):
        return {"schema": SCHEMA, "status": "ERROR", "reason": "manifest must be an object"}
    files = {}
    try:
        for role in ROLES:
            listed = manifest.get(role, []) or []
            if not isinstance(listed, list) or not all(isinstance(p, str) for p in listed):
                return {"schema": SCHEMA, "status": "ERROR", "reason": f"{role} must be a list of relative paths"}
            files[role] = [_file_record(root, p) for p in sorted(set(listed))]
    except ValueError as exc:
        return {"schema": SCHEMA, "status": "ERROR", "reason": str(exc)}
    commands = manifest.get("commands", []) or []
    if not isinstance(commands, list) or not all(isinstance(c, str) for c in commands):
        return {"schema": SCHEMA, "status": "ERROR", "reason": "commands must be a list of strings"}
    body = {
        "schema": SCHEMA,
        "project": manifest.get("project"),
        "session_id": manifest.get("session_id"),
        "started_at": manifest.get("started_at"),
        "finished_at": manifest.get("finished_at"),
        "actor": manifest.get("actor"),
        "files": files,
        "commands": commands,
        "environment": manifest.get("environment"),
        "notes": manifest.get("notes"),
        "declared_only": ["commands", "environment", "actor", "started_at", "finished_at"],
    }
    digests = sorted(f["sha256"] for r in ROLES for f in files[r] if f["sha256"])
    body["root_sha256"] = hashlib.sha256("\n".join(digests).encode()).hexdigest()
    body["receipt_sha256"] = hashlib.sha256(szl_canonical(body).encode()).hexdigest()
    body["signature"] = {"state": "UNSIGNED", "note": "no signer supplied; integrity only"}
    body["methods_paragraph"] = szl_methods_paragraph(body)
    missing = sum(1 for r in ROLES for f in files[r] if f["state"] == "MISSING")
    body["status"] = "RECORDED_WITH_MISSING_FILES" if missing else "RECORDED"
    body["scope"] = ("Byte identity of listed files plus declared commands and environment. "
                     "Not evidence that the analysis is correct or complete.")
    return body


def szl_sign_session_receipt(receipt: dict, private_key_pem) -> dict:
    """Optional. Uses szl-receipt-dsse (pip install szl-receipt-dsse) if present.
    Returns the receipt with a signature block; UNSIGNED with a reason otherwise."""
    try:
        from szl_receipt._sign import sign_dsse  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on optional package
        receipt["signature"] = {"state": "UNSIGNED", "note": f"szl-receipt-dsse not importable: {type(exc).__name__}"}
        return receipt
    signable = {k: v for k, v in receipt.items() if k not in ("signature", "methods_paragraph", "status", "scope")}
    try:
        payload_b64, sig_b64 = sign_dsse(signable, private_key_pem)
        receipt["signature"] = {"state": "SIGNED", "algo": "ECDSA-P256-SHA256", "envelope": "DSSE",
                                "payload_b64": payload_b64, "sig_b64": sig_b64}
    except Exception as exc:  # pragma: no cover
        receipt["signature"] = {"state": "UNSIGNED", "note": f"signing failed: {type(exc).__name__}"}
    receipt["methods_paragraph"] = szl_methods_paragraph(receipt)
    return receipt


def szl_verify_session_receipt(root, receipt: dict) -> dict:
    root = Path(root)
    if not isinstance(receipt, dict) or receipt.get("schema") != SCHEMA or not isinstance(receipt.get("files"), dict):
        return {"schema": SCHEMA + ".verification", "status": "ERROR", "reason": "not a szl.session-receipt.v1 document"}
    rows, mismatch, missing = [], 0, 0
    for role in ROLES:
        for rec in receipt["files"].get(role, []):
            try:
                now = _file_record(root, rec["path"])
            except ValueError as exc:
                rows.append({"role": role, "path": rec["path"], "result": "ERROR", "reason": str(exc)}); mismatch += 1; continue
            if now["state"] == "MISSING":
                result = "MISSING"; missing += 1
            elif rec.get("sha256") is None:
                result = "RECORDED_AS_MISSING_NOW_PRESENT"; mismatch += 1
            elif now["sha256"] == rec["sha256"]:
                result = "MATCH"
            else:
                result = "MISMATCH"; mismatch += 1
            rows.append({"role": role, "path": rec["path"], "result": result, "recorded_sha256": rec.get("sha256"), "observed_sha256": now["sha256"]})
    check = {k: v for k, v in receipt.items() if k not in ("receipt_sha256", "signature", "methods_paragraph", "status", "scope")}
    receipt_ok = hashlib.sha256(szl_canonical(check).encode()).hexdigest() == receipt.get("receipt_sha256")
    status = "MATCH" if receipt_ok and not mismatch and not missing else ("RECEIPT_TAMPERED" if not receipt_ok else "MISMATCH")
    return {"schema": SCHEMA + ".verification", "status": status, "receipt_digest_intact": receipt_ok,
            "files_checked": len(rows), "mismatches": mismatch, "missing": missing, "rows": rows,
            "signature_state": (receipt.get("signature") or {}).get("state", "UNSIGNED"),
            "scope": "Byte identity against the recorded receipt. A MATCH is not evidence of correctness."}
