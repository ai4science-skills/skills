# SPDX-License-Identifier: Apache-2.0
"""Local research memory; importing performs no I/O."""
import copy
import hashlib
import json
import re


def szl_anatomy_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def szl_anatomy_validate(graph):
    if not isinstance(graph, dict) or graph.get("schema") != "szl.research-anatomy.v1":
        raise ValueError("Expected szl.research-anatomy.v1")
    nodes = graph.get("nodes")
    if not isinstance(nodes, list) or len(nodes) > 10000:
        raise ValueError("nodes must contain at most 10000 entries")
    index = {}
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(node.get("id"), str) or not node["id"]:
            raise ValueError("Each node needs a nonempty id")
        if node["id"] in index:
            raise ValueError("Duplicate id")
        if node.get("kind") not in {"question", "claim", "paper", "dataset", "code", "model", "kernel", "run", "proof", "decision"}:
            raise ValueError("Unknown node kind")
        if not isinstance(node.get("title"), str) or not node["title"]:
            raise ValueError("Each node needs a title")
        deps = node.get("depends_on", [])
        if not isinstance(deps, list) or any(not isinstance(d, str) for d in deps) or len(set(deps)) != len(deps):
            raise ValueError("Dependencies must be unique string ids")
        digest = node.get("sha256")
        if digest is not None and (not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
            raise ValueError("Invalid sha256")
        index[node["id"]] = node
    children = {k: [] for k in index}
    pending = {k: set(v.get("depends_on", [])) for k, v in index.items()}
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
    szl_anatomy_digest(graph)
    return index


def szl_anatomy_assess(graph, current_digests=None):
    index = szl_anatomy_validate(graph)
    observed = {} if current_digests is None else current_digests
    if not isinstance(observed, dict) or any(k not in index for k in observed):
        raise ValueError("Observed digests must map known ids to hashes")
    if any(not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v) for v in observed.values()):
        raise ValueError("Invalid observed digest")
    changed = {k for k, v in observed.items() if index[k].get("sha256") is not None and index[k]["sha256"] != v}
    stale = set(changed) | {k for k, n in index.items() if n.get("needs_recheck") is True}
    while True:
        more = {k for k, node in index.items() if any(d in stale for d in node.get("depends_on", []))}
        if more <= stale:
            break
        stale.update(more)
    nodes = []
    for key, node in index.items():
        binding = "NOT_CHECKED"
        if key in observed and node.get("sha256") is not None:
            binding = "MISMATCH" if key in changed else "MATCH"
        needs = node["kind"] in {"claim", "proof", "run", "decision"} and not node.get("depends_on")
        nodes.append({"id": key, "kind": node["kind"], "title": node["title"],
                      "state": "STALE" if key in stale else "MISSING_EVIDENCE" if needs else "RECORDED",
                      "artifact_binding": binding, "truth_verified": False,
                      "recorded_claim_state": node.get("claim_state", "UNKNOWN")})
    return {"graph_sha256": szl_anatomy_digest(graph), "nodes": nodes,
            "changed_sources": sorted(changed), "recheck": sorted(stale),
            "signed": False, "execution_authority": "none"}


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
    stale = set(changed_ids)
    while True:
        more = {k for k, node in by_id.items() if any(d in stale for d in node.get("depends_on", []))}
        if more <= stale:
            break
        stale.update(more)
    for key in stale - changed_ids:
        by_id[key]["needs_recheck"] = True
    updated["nodes"] = list(by_id.values())
    szl_anatomy_validate(updated)
    return updated
