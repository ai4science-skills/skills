# SPDX-License-Identifier: Apache-2.0
"""Original bounded audit of supplied computational negative-control evidence."""
import hashlib
import json
import math
import re
from datetime import datetime, timezone

SCHEMA = "szl.negative-control-audit.v1"
MAX_BYTES = 1048576


def szl_control_object(value, keys, where):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError(where + " must have exactly: " + ", ".join(sorted(keys)))
    return value


def szl_control_text(value, where, limit=2048):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(where + " must be bounded nonempty text")
    return value


def szl_control_identifier(value, where):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value):
        raise ValueError(where + " must be an identifier of at most 128 characters")
    return value


def szl_control_digest(value, where):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError(where + " must be a lowercase SHA-256")
    return value


def szl_control_number(value, where, low=-1e12, high=1e12):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high or not math.isfinite(value):
        raise ValueError(where + " must be a finite bounded number")
    return value


def szl_control_time(value, where):
    szl_control_text(value, where, 40)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value):
        raise ValueError(where + " must be UTC YYYY-MM-DDTHH:MM:SSZ")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as error:
        raise ValueError(where + " is not a valid UTC time") from error


def canonical_sha256(value):
    """Digest of this contract's canonical JSON, not a signature or a timestamp."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def szl_control_unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def read_json(raw):
    """Read bounded JSON as data; reject duplicate keys, constants and deep nesting."""
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
        raise ValueError("JSON exceeds 1 MiB or is not bytes")
    text = raw.decode("utf-8")
    depth, quoted, escaped = 0, False, False
    for character in text:
        if quoted:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
        elif character == '"':
            quoted = True
        elif character in "[{":
            depth += 1
            if depth > 32:
                raise ValueError("JSON nesting exceeds 32")
        elif character in "]}":
            depth -= 1
    return json.loads(text, object_pairs_hook=szl_control_unique, parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Nonfinite JSON")))


def szl_audit_negative_controls(payload):
    """Check registry completeness, declared DAG relevance and byte-bound null outcomes."""
    szl_control_object(payload, ["schema", "registry", "artifacts", "results"], "input")
    if payload["schema"] != SCHEMA:
        raise ValueError("Unsupported input schema")
    registry = szl_control_object(payload["registry"], ["id", "version", "scope", "frozen_at", "graph", "main", "protocol_artifact", "scorer_artifact", "execution_artifact", "controls"], "registry")
    szl_control_identifier(registry["id"], "registry.id")
    if type(registry["version"]) is not int or not 1 <= registry["version"] <= 100000:
        raise ValueError("registry.version must be a positive bounded integer")
    if registry["scope"] != "COMPUTATIONAL":
        raise ValueError("Only supplied COMPUTATIONAL evidence is supported")
    frozen = szl_control_time(registry["frozen_at"], "registry.frozen_at")
    findings = []

    def finding(code, control="registry", detail=""):
        findings.append({"code": code, "control_id": control, "detail": detail})

    artifacts = payload["artifacts"]
    if not isinstance(artifacts, list) or not 1 <= len(artifacts) <= 64:
        raise ValueError("artifacts must contain 1 to 64 supplied byte records")
    by_artifact, artifact_report, total = {}, [], 0
    for record in artifacts:
        szl_control_object(record, ["id", "sha256", "content_utf8"], "artifact")
        key = szl_control_identifier(record["id"], "artifact.id")
        if key in by_artifact:
            raise ValueError("Duplicate artifact id")
        szl_control_digest(record["sha256"], "artifact.sha256")
        if not isinstance(record["content_utf8"], str):
            raise ValueError("artifact.content_utf8 must be text")
        content = record["content_utf8"].encode("utf-8")
        total += len(content)
        if len(content) > 65536 or total > MAX_BYTES:
            raise ValueError("Artifact bytes exceed bounded limits")
        actual = hashlib.sha256(content).hexdigest()
        by_artifact[key] = {"actual_sha256": actual, "bytes": content}
        artifact_report.append({"id": key, "actual_sha256": actual, "declared_sha256": record["sha256"], "binding": "MATCH" if actual == record["sha256"] else "MISMATCH"})
        if actual != record["sha256"]:
            finding("ARTIFACT_DIGEST_MISMATCH", detail=key)

    def artifact_digest(key):
        szl_control_identifier(key, "artifact reference")
        if key not in by_artifact:
            finding("MISSING_ARTIFACT", detail=key)
            return None
        return by_artifact[key]["actual_sha256"]

    fixed = {name: artifact_digest(registry[name + "_artifact"]) for name in ["protocol", "scorer", "execution"]}
    graph = szl_control_object(registry["graph"], ["nodes", "edges"], "graph")
    nodes, edges = graph["nodes"], graph["edges"]
    if not isinstance(nodes, list) or not 2 <= len(nodes) <= 128 or not isinstance(edges, list) or len(edges) > 1024:
        raise ValueError("Graph must have 2 to 128 nodes and at most 1024 edges")
    for node in nodes:
        szl_control_identifier(node, "graph node")
    if len(set(nodes)) != len(nodes):
        raise ValueError("Duplicate graph node")
    adjacency = {node: set() for node in nodes}
    edge_seen = set()
    for edge in edges:
        if not isinstance(edge, list) or len(edge) != 2 or any(not isinstance(v, str) or v not in adjacency for v in edge):
            raise ValueError("Each edge must reference two declared nodes")
        pair = tuple(edge)
        if pair in edge_seen or edge[0] == edge[1]:
            raise ValueError("Duplicate or self graph edge")
        edge_seen.add(pair)
        adjacency[edge[0]].add(edge[1])
    reach = {}
    for node in nodes:
        pending, visited = list(adjacency[node]), set()
        while pending:
            other = pending.pop()
            if other == node:
                raise ValueError("Mechanism graph must be acyclic")
            if other not in visited:
                visited.add(other)
                pending.extend(adjacency[other])
        reach[node] = visited
    main = szl_control_object(registry["main"], ["intervention", "readout"], "main")
    if any(not isinstance(v, str) or v not in adjacency for v in main.values()) or main["intervention"] == main["readout"]:
        raise ValueError("main must reference distinct declared graph nodes")
    if main["readout"] not in reach[main["intervention"]]:
        finding("MAIN_MECHANISM_PATH_UNDECLARED")
    controls = registry["controls"]
    if not isinstance(controls, list) or not 1 <= len(controls) <= 32:
        raise ValueError("controls must contain 1 to 32 records")
    planned, control_report = {}, []
    for control in controls:
        szl_control_object(control, ["id", "kind", "intervention", "readout", "shared_nuisance", "rationale", "input_artifact", "metric", "expectation", "tolerance"], "control")
        key = szl_control_identifier(control["id"], "control.id")
        if key in planned:
            raise ValueError("Duplicate control id")
        if control["kind"] not in ["NEGATIVE_EXPOSURE", "NEGATIVE_OUTCOME", "SHAM_COMPUTATION"]:
            raise ValueError("Unsupported computational control kind")
        if any(not isinstance(control[k], str) or control[k] not in adjacency for k in ["intervention", "readout"]):
            raise ValueError("Control must reference declared graph nodes")
        if control["intervention"] == control["readout"]:
            raise ValueError("Control nodes must be distinct")
        szl_control_text(control["rationale"], "control.rationale")
        szl_control_identifier(control["metric"], "control.metric")
        if control["expectation"] != "ABS_DELTA_LE":
            raise ValueError("Only the prespecified absolute-delta null is supported")
        szl_control_number(control["tolerance"], "control.tolerance", 0, 1e12)
        nuisance = control["shared_nuisance"]
        if not isinstance(nuisance, list) or not 1 <= len(nuisance) <= 32 or any(not isinstance(v, str) or v not in adjacency for v in nuisance) or len(set(nuisance)) != len(nuisance):
            raise ValueError("shared_nuisance must list unique graph nodes")
        if control["readout"] in reach[control["intervention"]]:
            finding("EXPECTED_NULL_HAS_CAUSAL_PATH", key)
        for node in nuisance:
            main_relevant = all(v in reach[node] for v in main.values())
            control_relevant = all(control[k] in reach[node] for k in ["intervention", "readout"])
            if not main_relevant or not control_relevant:
                finding("NUISANCE_NOT_SHARED_IN_DECLARED_GRAPH", key, node)
        if control["kind"] == "NEGATIVE_EXPOSURE" and control["readout"] != main["readout"]:
            finding("CONTROL_ROLE_MISMATCH", key, "Negative exposure must retain the main readout")
        if control["kind"] == "NEGATIVE_OUTCOME" and control["intervention"] != main["intervention"]:
            finding("CONTROL_ROLE_MISMATCH", key, "Negative outcome must retain the main intervention")
        planned[key] = (control, artifact_digest(control["input_artifact"]))

    results = payload["results"]
    if not isinstance(results, list) or len(results) > 32:
        raise ValueError("results must be a list of at most 32 records")
    registry_digest = canonical_sha256(registry)
    observed = set()
    required = ["schema", "control_id", "registry_sha256", "protocol_sha256", "scorer_sha256", "execution_sha256", "input_sha256", "metric", "tolerance", "delta", "started_at", "completed_at", "status", "failure_reason", "contaminated"]
    for result in results:
        szl_control_object(result, ["control_id", "outcome_artifact"], "result reference")
        key = szl_control_identifier(result["control_id"], "result.control_id")
        if key in observed:
            raise ValueError("Duplicate control result")
        observed.add(key)
        outcome_digest = artifact_digest(result["outcome_artifact"])
        if key not in planned:
            finding("UNREGISTERED_CONTROL", key)
        if outcome_digest is None:
            finding("MISSING_CONTROL_OUTCOME", key)
            continue
        outcome = read_json(by_artifact[result["outcome_artifact"]]["bytes"])
        szl_control_object(outcome, required, "control outcome")
        if outcome["schema"] != "szl.negative-control-result.v1":
            raise ValueError("Unsupported outcome schema")
        szl_control_identifier(outcome["control_id"], "outcome.control_id")
        szl_control_identifier(outcome["metric"], "outcome.metric")
        for name in ["registry", "protocol", "scorer", "execution", "input"]:
            szl_control_digest(outcome[name + "_sha256"], "outcome." + name + "_sha256")
        szl_control_number(outcome["tolerance"], "outcome.tolerance", 0, 1e12)
        started, completed = szl_control_time(outcome["started_at"], "outcome.started_at"), szl_control_time(outcome["completed_at"], "outcome.completed_at")
        if type(outcome["contaminated"]) is not bool or outcome["status"] not in ["SUCCESS", "FAILED", "ABORTED"]:
            raise ValueError("Invalid outcome contamination flag or status")
        if outcome["status"] == "SUCCESS":
            szl_control_number(outcome["delta"], "outcome.delta")
            if outcome["failure_reason"] is not None:
                raise ValueError("Successful outcome must have null failure_reason")
        else:
            if outcome["delta"] is not None:
                raise ValueError("Failed outcome must have null delta")
            szl_control_text(outcome["failure_reason"], "outcome.failure_reason")
            finding("CONTROL_NOT_SUCCESSFUL", key, outcome["status"])
        if outcome["control_id"] != key:
            finding("CONTROL_IDENTITY_MISMATCH", key)
        if started < frozen or completed < started:
            finding("CONTROL_TIMING_CONFLICT", key)
        if outcome["registry_sha256"] != registry_digest:
            finding("REGISTRY_BINDING_MISMATCH", key)
        for name, actual in fixed.items():
            if actual is None or outcome[name + "_sha256"] != actual:
                finding(name.upper() + "_BINDING_MISMATCH", key)
        if outcome["contaminated"]:
            finding("CONTROL_CONTAMINATED", key)
        if key in planned:
            control, input_digest = planned[key]
            if input_digest is None or outcome["input_sha256"] != input_digest:
                finding("CONTROL_INPUT_BINDING_MISMATCH", key)
            if outcome["metric"] != control["metric"]:
                finding("CONTROL_METRIC_MISMATCH", key)
            if outcome["tolerance"] != control["tolerance"]:
                finding("TOLERANCE_CHANGED", key)
            if outcome["status"] == "SUCCESS" and abs(outcome["delta"]) > control["tolerance"]:
                finding("EXPECTED_NULL_FAILED", key)
        control_report.append({"id": key, "status": outcome["status"], "delta": outcome["delta"], "outcome_sha256": outcome_digest})
    for key in sorted(set(planned) - observed):
        finding("MISSING_REGISTERED_CONTROL", key)
    findings.sort(key=lambda f: (f["control_id"], f["code"], f["detail"]))
    return {"schema": "szl.negative-control-audit-report.v1", "status": "INCONCLUSIVE" if findings else "CONTROLS_CONSISTENT_ON_SUPPLIED_EVIDENCE", "registry_sha256": registry_digest, "findings": findings, "controls": sorted(control_report, key=lambda v: v["id"]), "artifacts": sorted(artifact_report, key=lambda v: v["id"]), "preregistration": "DECLARED_ONLY", "mechanism_validity": "DECLARED_GRAPH_ONLY", "scientific_performance": "NOT_MEASURED", "execution_performed": False, "promotion_effect": "NONE"}
