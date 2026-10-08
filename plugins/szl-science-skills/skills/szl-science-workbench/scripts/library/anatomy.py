# SPDX-License-Identifier: Apache-2.0
# Modified 2026-09-30: add dated evidence links and retained contradiction review.
"""Local research memory; importing performs no I/O."""
import copy
import datetime
import hashlib
import json
import re


def szl_anatomy_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def szl_anatomy_time(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", value):
        raise ValueError("Timestamps must be UTC YYYY-MM-DDTHH:MM:SSZ")
    try:
        return datetime.datetime(int(value[:4]), int(value[5:7]), int(value[8:10]), int(value[11:13]), int(value[14:16]), int(value[17:19]))
    except ValueError as error:
        raise ValueError("Invalid UTC timestamp") from error


def szl_anatomy_dependencies(graph, index):
    dependencies = {key: set(node.get("depends_on", [])) for key, node in index.items()}
    for link in graph.get("evidence_links", []):
        dependencies[link["claim"]].add(link["evidence"])
    return dependencies


def szl_anatomy_descendants(dependencies, seeds):
    children = {key: [] for key in dependencies}
    for key, deps in dependencies.items():
        for dep in deps:
            children[dep].append(key)
    stale, pending = set(seeds), list(seeds)
    while pending:
        for child in children[pending.pop()]:
            if child not in stale:
                stale.add(child)
                pending.append(child)
    return stale


def szl_anatomy_validate(graph):
    if not isinstance(graph, dict) or graph.get("schema") != "szl.research-anatomy.v1":
        raise ValueError("Expected szl.research-anatomy.v1")
    nodes = graph.get("nodes")
    if not isinstance(nodes, list) or len(nodes) > 10000:
        raise ValueError("nodes must contain at most 10000 entries")
    index = {}
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(node.get("id"), str) or not node["id"] or len(node["id"]) > 128:
            raise ValueError("Each node needs a nonempty id")
        if node["id"] in index:
            raise ValueError("Duplicate id")
        if not isinstance(node.get("kind"), str) or node["kind"] not in {"question", "claim", "paper", "dataset", "code", "model", "kernel", "run", "proof", "decision"}:
            raise ValueError("Unknown node kind")
        if not isinstance(node.get("title"), str) or not node["title"] or len(node["title"]) > 2048:
            raise ValueError("Each node needs a title")
        deps = node.get("depends_on", [])
        if not isinstance(deps, list) or len(deps) > 10000 or any(not isinstance(d, str) for d in deps) or len(set(deps)) != len(deps):
            raise ValueError("Dependencies must be unique string ids")
        digest = node.get("sha256")
        if digest is not None and (not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
            raise ValueError("Invalid sha256")
        if "needs_recheck" in node and type(node["needs_recheck"]) is not bool:
            raise ValueError("needs_recheck must be boolean")
        if not isinstance(node.get("evidence_status", "active"), str) or node.get("evidence_status", "active") not in {"active", "retracted", "corrected"}:
            raise ValueError("evidence_status must be active, retracted or corrected")
        for key in ("observed_at", "expires_at"):
            if key in node:
                szl_anatomy_time(node[key])
        if "expires_at" in node and "observed_at" not in node:
            raise ValueError("Expiry requires observed_at")
        if "expires_at" in node and szl_anatomy_time(node["expires_at"]) <= szl_anatomy_time(node["observed_at"]):
            raise ValueError("Expiry must follow observation")
        if "source_revision" in node and (not isinstance(node["source_revision"], str) or not node["source_revision"].strip() or len(node["source_revision"]) > 256):
            raise ValueError("source_revision must be a bounded nonempty string")
        index[node["id"]] = node
    if "as_of" in graph:
        szl_anatomy_time(graph["as_of"])
    links = graph.get("evidence_links", [])
    if not isinstance(links, list) or len(links) > 20000:
        raise ValueError("evidence_links must contain at most 20000 entries")
    seen = set()
    for link in links:
        if not isinstance(link, dict) or set(link) != {"claim", "evidence", "relation"}:
            raise ValueError("Evidence links need claim, evidence and relation only")
        if any(not isinstance(link.get(key), str) for key in ("claim", "evidence", "relation")):
            raise ValueError("Evidence link fields must be strings")
        if link["claim"] not in index or link["evidence"] not in index:
            raise ValueError("Dangling evidence link")
        if index[link["claim"]]["kind"] != "claim" or link["claim"] == link["evidence"]:
            raise ValueError("Evidence links must target a distinct claim")
        if link["relation"] not in {"supports", "contradicts", "qualifies"}:
            raise ValueError("Unknown evidence relation")
        identity = (link["claim"], link["evidence"], link["relation"])
        if identity in seen:
            raise ValueError("Duplicate evidence link")
        seen.add(identity)
    children = {k: [] for k in index}
    pending = szl_anatomy_dependencies(graph, index)
    for k, deps in pending.items():
        for dep in deps:
            if dep not in index:
                raise ValueError("Dangling dependency")
            children[dep].append(k)
    ready = [k for k, deps in pending.items() if not deps]
    count = 0
    while ready:
        key = ready.pop()
        count += 1
        for child in children[key]:
            pending[child].remove(key)
            if not pending[child]:
                ready.append(child)
    if count != len(index):
        raise ValueError("Cycle: represent feedback as a new dated run")
    if len(json.dumps(graph, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()) > 8 * 1024 * 1024:
        raise ValueError("Research graph exceeds 8 MiB")
    return index


def szl_anatomy_assess(graph, current_digests=None, as_of=None):
    index = szl_anatomy_validate(graph)
    observed = {} if current_digests is None else current_digests
    if not isinstance(observed, dict) or any(k not in index for k in observed):
        raise ValueError("Observed digests must map known ids to hashes")
    if any(not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v) for v in observed.values()):
        raise ValueError("Invalid observed digest")
    if as_of is not None and "as_of" in graph and as_of != graph["as_of"]:
        raise ValueError("Conflicting as_of values")
    selected_time = graph.get("as_of") if as_of is None else as_of
    clock = None if selected_time is None else szl_anatomy_time(selected_time)
    dependencies = szl_anatomy_dependencies(graph, index)
    changed = {k for k, v in observed.items() if index[k].get("sha256") is not None and index[k]["sha256"] != v}
    expired, future = set(), set()
    freshness = {}
    for key, node in index.items():
        freshness[key] = "NOT_CHECKED" if clock is None else "NO_EXPIRY" if "expires_at" not in node else "CURRENT"
        if clock is not None and "observed_at" in node and szl_anatomy_time(node["observed_at"]) > clock:
            future.add(key)
            freshness[key] = "NOT_YET_OBSERVED"
        elif clock is not None and "expires_at" in node and clock >= szl_anatomy_time(node["expires_at"]):
            expired.add(key)
            freshness[key] = "EXPIRED"
    withdrawn = {key for key, node in index.items() if node.get("evidence_status", "active") != "active"}
    seeds = set(changed) | expired | future | withdrawn | {k for k, n in index.items() if n.get("needs_recheck") is True}
    invalid_sources = szl_anatomy_descendants(dependencies, seeds)
    evidence = {key: {"supports": [], "contradicts": [], "qualifies": []} for key, node in index.items() if node["kind"] == "claim"}
    links = []
    for link in sorted(graph.get("evidence_links", []), key=lambda item: (item["claim"], item["relation"], item["evidence"])):
        current = link["evidence"] not in invalid_sources
        links.append(dict(link, usable=current, evidence_status=index[link["evidence"]].get("evidence_status", "active"), freshness=freshness[link["evidence"]]))
        if current:
            evidence[link["claim"]][link["relation"]].append(link["evidence"])
    conflicts = {key for key, ledger in evidence.items() if ledger["supports"] and ledger["contradicts"]}
    contradicted = {key for key, ledger in evidence.items() if ledger["contradicts"]}
    stale = szl_anatomy_descendants(dependencies, seeds | contradicted)
    nodes = []
    for key in sorted(index):
        node = index[key]
        binding = "NOT_CHECKED"
        if key in observed and node.get("sha256") is not None:
            binding = "MISMATCH" if key in changed else "MATCH"
        needs = node["kind"] in {"claim", "proof", "run", "decision"} and not dependencies[key]
        ledger = evidence.get(key)
        evidence_state = "NOT_RECORDED"
        if ledger is not None:
            evidence_state = "CONFLICTING" if key in conflicts else "CONTRADICTED" if ledger["contradicts"] else "SUPPORTED" if ledger["supports"] else "QUALIFIED" if ledger["qualifies"] else "MISSING_EVIDENCE"
        nodes.append({"id": key, "kind": node["kind"], "title": node["title"],
                      "state": "STALE" if key in stale else "MISSING_EVIDENCE" if needs else "RECORDED",
                      "artifact_binding": binding, "truth_verified": False,
                      "recorded_claim_state": node.get("claim_state", "UNKNOWN"),
                      "freshness": freshness[key], "evidence_state": evidence_state})
    return {"graph_sha256": szl_anatomy_digest(graph), "nodes": nodes,
            "changed_sources": sorted(changed), "recheck": sorted(stale),
            "as_of": selected_time, "expired_sources": sorted(expired), "future_observations": sorted(future),
            "withdrawn_sources": sorted(withdrawn), "conflicting_claims": sorted(conflicts), "contradicted_claims": sorted(contradicted), "evidence_links": links,
            "expiry_not_checked": sorted(k for k, node in index.items() if clock is None and "expires_at" in node),
            "signed": False, "execution_authority": "none", "scientific_evaluation": "NOT_MEASURED"}


def szl_anatomy_update(graph, replacements):
    szl_anatomy_validate(graph)
    if not isinstance(replacements, list) or any(not isinstance(n, dict) for n in replacements):
        raise ValueError("Supply replacement nodes")
    ids = [n.get("id") for n in replacements]
    if any(not isinstance(k, str) or not k for k in ids) or len(set(ids)) != len(ids):
        raise ValueError("Replacement ids must be nonempty and unique")
    updated = copy.deepcopy(graph)
    history = updated.setdefault("history", [])
    if not isinstance(history, list):
        raise ValueError("history must be a list")
    by_id = {n["id"]: n for n in updated["nodes"]}
    changed_ids = set()
    for new in replacements:
        old = by_id.get(new["id"])
        if old == new:
            continue
        history.append({"id": new["id"], "previous": copy.deepcopy(old),
                        "replacement_sha256": szl_anatomy_digest(new), "signed": False})
        by_id[new["id"]] = copy.deepcopy(new)
        changed_ids.add(new["id"])
    updated["nodes"] = list(by_id.values())
    szl_anatomy_validate(updated)
    stale = szl_anatomy_descendants(szl_anatomy_dependencies(updated, by_id), changed_ids)
    for key in stale - changed_ids:
        by_id[key]["needs_recheck"] = True
    updated["nodes"] = list(by_id.values())
    szl_anatomy_validate(updated)
    return updated
