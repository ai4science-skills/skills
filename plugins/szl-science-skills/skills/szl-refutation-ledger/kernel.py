"""szl-refutation-ledger — an append-only, hash-chained record of replication attempts.

Stdlib only. Offline. Every entry carries the SHA-256 of the previous entry, so a ledger
cannot be edited in place without breaking the chain; `verify` finds the first broken link.

Entries (each wrapped as {"seq", "kind", "recorded_at", "body", "prev_sha256", "entry_sha256"}):

  claim       {"claim_id", "statement", "source": {...}, "depends_on": [claim_id, ...],
               "effect": {"metric", "value", "ci": [lo, hi]} (optional)}
  attempt     {"attempt_id", "claim_id", "outcome": "REPLICATED" | "NOT_REPLICATED" | "INCONCLUSIVE",
               "n": int (optional), "effect": {...} (optional), "preregistered": bool (optional),
               "receipt": {"sha256": hex64, "path" or "url"} (optional but counted when absent),
               "actor": str (optional), "notes": str (optional)}
  withdrawal  {"claim_id", "reason"}

Status per claim: UNTESTED, REPLICATED, NOT_REPLICATED, CONTESTED, INCONCLUSIVE, WITHDRAWN.
Foundation per claim: SOUND (every dependency REPLICATED or UNTESTED-with-no-shaken-ancestor is
not enough: UNTESTED dependencies make it UNKNOWN), SHAKEN (some dependency is NOT_REPLICATED,
CONTESTED or WITHDRAWN, directly or transitively), UNKNOWN (an untested dependency, no shaken one).

What a status means: it summarises the attempts recorded in this ledger, with unreceipted
attempts kept in the denominator and flagged. It is not a verdict on the truth of the claim, and
the chain proves order and integrity of the record, not the honesty of any entry.
"""
from __future__ import annotations

import hashlib
import json
import re

SCHEMA = "szl.refutation-ledger.v1"
GENESIS = "0" * 64
OUTCOMES = ("REPLICATED", "NOT_REPLICATED", "INCONCLUSIVE")
KINDS = ("claim", "attempt", "withdrawal")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")


def szl_canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def szl_entry_digest(entry: dict) -> str:
    body = {k: v for k, v in entry.items() if k != "entry_sha256"}
    return hashlib.sha256(szl_canonical(body).encode("utf-8")).hexdigest()


def szl_new_ledger(title: str = "") -> dict:
    return {"schema": SCHEMA, "title": title, "entries": []}


def _err(message: str) -> dict:
    return {"status": "ERROR", "error": message}


def _validate_body(kind: str, body: dict, known_claims: set) -> str | None:
    if not isinstance(body, dict):
        return "entry body must be an object"
    if kind == "claim":
        for key in ("claim_id", "statement"):
            if not isinstance(body.get(key), str) or not body[key].strip():
                return "claim needs a non-empty %s" % key
        if not ID.match(body["claim_id"]):
            return "claim_id has an invalid form"
        if body["claim_id"] in known_claims:
            return "duplicate claim_id %s" % body["claim_id"]
        deps = body.get("depends_on", [])
        if not isinstance(deps, list) or any(not isinstance(d, str) for d in deps):
            return "depends_on must be a list of claim ids"
        if body["claim_id"] in deps:
            return "a claim cannot depend on itself"
        for d in deps:
            if d not in known_claims:
                return "depends_on references unknown claim %s (record it first)" % d
        return None
    if kind == "attempt":
        if not isinstance(body.get("attempt_id"), str) or not ID.match(body["attempt_id"]):
            return "attempt needs a valid attempt_id"
        if body.get("claim_id") not in known_claims:
            return "attempt references unknown claim %r" % body.get("claim_id")
        if body.get("outcome") not in OUTCOMES:
            return "outcome must be one of %s" % ", ".join(OUTCOMES)
        if "n" in body and (not isinstance(body["n"], int) or isinstance(body["n"], bool) or body["n"] < 0):
            return "n must be a non-negative integer"
        receipt = body.get("receipt")
        if receipt is not None:
            if not isinstance(receipt, dict) or not isinstance(receipt.get("sha256"), str) or not HEX64.match(receipt["sha256"]):
                return "receipt.sha256 must be 64 lowercase hex characters"
            if not any(isinstance(receipt.get(k), str) and receipt[k] for k in ("path", "url")):
                return "receipt needs a path or url"
        return None
    if kind == "withdrawal":
        if body.get("claim_id") not in known_claims:
            return "withdrawal references unknown claim %r" % body.get("claim_id")
        if not isinstance(body.get("reason"), str) or not body["reason"].strip():
            return "withdrawal needs a reason"
        return None
    return "unknown entry kind %r" % kind


def szl_verify_ledger(ledger: dict) -> dict:
    """Recompute the chain. VALID, or BROKEN at the first bad link; ERROR for malformed input."""
    if not isinstance(ledger, dict) or ledger.get("schema") != SCHEMA or not isinstance(ledger.get("entries"), list):
        return _err("not a %s ledger" % SCHEMA)
    prev, known, attempt_ids = GENESIS, set(), set()
    for i, entry in enumerate(ledger["entries"]):
        expected_seq = i + 1
        if not isinstance(entry, dict) or set(entry) != {"seq", "kind", "recorded_at", "body", "prev_sha256", "entry_sha256"}:
            return {"status": "BROKEN", "at_seq": expected_seq, "reason": "entry fields differ from the contract"}
        if entry["seq"] != expected_seq:
            return {"status": "BROKEN", "at_seq": expected_seq, "reason": "sequence number out of order"}
        if entry["kind"] not in KINDS:
            return {"status": "BROKEN", "at_seq": expected_seq, "reason": "unknown kind"}
        if not isinstance(entry["recorded_at"], str) or not TIME.match(entry["recorded_at"]):
            return {"status": "BROKEN", "at_seq": expected_seq, "reason": "recorded_at must be UTC ISO-8601 with Z"}
        if entry["prev_sha256"] != prev:
            return {"status": "BROKEN", "at_seq": expected_seq, "reason": "prev_sha256 does not match the previous entry"}
        if entry["entry_sha256"] != szl_entry_digest(entry):
            return {"status": "BROKEN", "at_seq": expected_seq, "reason": "entry_sha256 does not match the entry content"}
        problem = _validate_body(entry["kind"], entry["body"], known)
        if problem:
            return {"status": "BROKEN", "at_seq": expected_seq, "reason": problem}
        if entry["kind"] == "claim":
            known.add(entry["body"]["claim_id"])
        elif entry["kind"] == "attempt":
            if entry["body"]["attempt_id"] in attempt_ids:
                return {"status": "BROKEN", "at_seq": expected_seq, "reason": "duplicate attempt_id"}
            attempt_ids.add(entry["body"]["attempt_id"])
        prev = entry["entry_sha256"]
    return {"status": "VALID", "entries": len(ledger["entries"]), "head_sha256": prev, "claims": len(known), "attempts": len(attempt_ids)}


def szl_append(ledger: dict, kind: str, body: dict, recorded_at: str) -> dict:
    """Return a new ledger with one more entry, or ERROR. Never mutates the input."""
    check = szl_verify_ledger(ledger)
    if check["status"] != "VALID":
        return _err("refusing to append to a ledger that does not verify: %s" % json.dumps(check, sort_keys=True))
    if not isinstance(recorded_at, str) or not TIME.match(recorded_at):
        return _err("recorded_at must be UTC ISO-8601 with Z")
    known = {e["body"]["claim_id"] for e in ledger["entries"] if e["kind"] == "claim"}
    problem = _validate_body(kind, body, known)
    if problem:
        return _err(problem)
    if kind == "attempt" and any(e["kind"] == "attempt" and e["body"]["attempt_id"] == body["attempt_id"] for e in ledger["entries"]):
        return _err("duplicate attempt_id %s" % body["attempt_id"])
    entry = {"seq": len(ledger["entries"]) + 1, "kind": kind, "recorded_at": recorded_at, "body": body, "prev_sha256": check["head_sha256"]}
    entry["entry_sha256"] = szl_entry_digest(entry)
    return {"status": "APPENDED", "ledger": {**ledger, "entries": ledger["entries"] + [entry]}, "entry": entry}


def _claim_state(attempts: list, withdrawn: bool) -> str:
    if withdrawn:
        return "WITHDRAWN"
    if not attempts:
        return "UNTESTED"
    outcomes = {a["outcome"] for a in attempts}
    if "REPLICATED" in outcomes and "NOT_REPLICATED" in outcomes:
        return "CONTESTED"
    if "NOT_REPLICATED" in outcomes:
        return "NOT_REPLICATED"
    if "REPLICATED" in outcomes:
        return "REPLICATED"
    return "INCONCLUSIVE"


def szl_ledger_status(ledger: dict) -> dict:
    """Per-claim state, attempt counts with unreceipted attempts flagged, and foundation state from dependencies."""
    check = szl_verify_ledger(ledger)
    if check["status"] != "VALID":
        return {"status": "ERROR", "error": "ledger does not verify", "verification": check}
    claims, attempts, withdrawn = {}, {}, set()
    for e in ledger["entries"]:
        b = e["body"]
        if e["kind"] == "claim":
            claims[b["claim_id"]] = b
            attempts[b["claim_id"]] = []
        elif e["kind"] == "attempt":
            attempts[b["claim_id"]].append(b)
        else:
            withdrawn.add(b["claim_id"])
    state = {cid: _claim_state(attempts[cid], cid in withdrawn) for cid in claims}
    shaken_states = {"NOT_REPLICATED", "CONTESTED", "WITHDRAWN"}

    def foundation(cid, seen=()):
        deps = claims[cid].get("depends_on", [])
        result, trace = "SOUND", []
        for d in deps:
            if d in seen:
                continue
            sub, sub_trace = foundation(d, seen + (cid,))
            if state[d] in shaken_states or sub == "SHAKEN":
                result = "SHAKEN"
                trace.append({"claim_id": d, "state": state[d], "via": sub_trace})
            elif state[d] in {"UNTESTED", "INCONCLUSIVE"} or sub == "UNKNOWN":
                if result != "SHAKEN":
                    result = "UNKNOWN"
                trace.append({"claim_id": d, "state": state[d], "via": sub_trace})
        return result, trace

    rows = []
    for cid, body in claims.items():
        found, trace = foundation(cid)
        atts = attempts[cid]
        counts = {o: sum(1 for a in atts if a["outcome"] == o) for o in OUTCOMES}
        unreceipted = [a["attempt_id"] for a in atts if not a.get("receipt")]
        rows.append({"claim_id": cid, "statement": body["statement"], "state": state[cid], "attempts": counts,
                     "attempts_total": len(atts), "unreceipted_attempts": unreceipted,
                     "preregistered_attempts": sum(1 for a in atts if a.get("preregistered") is True),
                     "depends_on": body.get("depends_on", []), "foundation": found, "foundation_trace": trace})
    summary = {s: sum(1 for r in rows if r["state"] == s) for s in ("UNTESTED", "REPLICATED", "NOT_REPLICATED", "CONTESTED", "INCONCLUSIVE", "WITHDRAWN")}
    return {"status": "RECORDED", "schema": SCHEMA, "title": ledger.get("title", ""), "head_sha256": check["head_sha256"],
            "entries": check["entries"], "claims": rows, "summary": summary,
            "shaken_claims": sorted(r["claim_id"] for r in rows if r["foundation"] == "SHAKEN"),
            "unreceipted_attempts_total": sum(len(r["unreceipted_attempts"]) for r in rows),
            "limits": ["States summarise the attempts in this ledger, not the truth of the claim.",
                       "Unreceipted attempts are counted and flagged, never dropped.",
                       "The hash chain proves order and integrity of the record, not the honesty of any entry."]}


def szl_replication_record(status: dict, claim_id: str) -> str:
    """One plain-language paragraph for a methods section or a reply to a reviewer."""
    row = next((r for r in status.get("claims", []) if r["claim_id"] == claim_id), None)
    if row is None:
        return "No claim %s in this ledger." % claim_id
    c = row["attempts"]
    text = ("Claim %s (\"%s\") has %d recorded replication attempt(s): %d replicated, %d not replicated, %d inconclusive; "
            "ledger state %s." % (claim_id, row["statement"], row["attempts_total"], c["REPLICATED"], c["NOT_REPLICATED"], c["INCONCLUSIVE"], row["state"]))
    if row["unreceipted_attempts"]:
        text += " %d attempt(s) carry no receipt and are counted but flagged." % len(row["unreceipted_attempts"])
    if row["depends_on"]:
        text += " It rests on %s; foundation %s." % (", ".join(row["depends_on"]), row["foundation"])
    text += " Ledger head %s." % status["head_sha256"][:16]
    return text
