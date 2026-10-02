# SPDX-License-Identifier: Apache-2.0
"""Bounded transformation-digest audit. Importing and auditing perform no I/O."""
import hashlib
import heapq
import json
import re


def szl_lineage_text(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value):
        raise ValueError(label + " must be a 1..128 character identifier")
    return value


def szl_lineage_hash(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError(label + " must be a lowercase SHA-256 digest")
    return value


def szl_lineage_keys(value, required, label):
    if not isinstance(value, dict) or set(value) != set(required):
        raise ValueError(label + " has missing or unknown fields")


def szl_audit_lineage(manifest):
    """Audit declared producers/edges and supplied readback digests; never execute stages."""
    szl_lineage_keys(manifest, ("schema", "artifacts", "stages", "required_stages", "observed_digests"), "manifest")
    if manifest["schema"] != "szl.artifact-lineage.v1":
        raise ValueError("Expected szl.artifact-lineage.v1")
    artifacts, stages = manifest["artifacts"], manifest["stages"]
    if not isinstance(artifacts, list) or not 1 <= len(artifacts) <= 1000:
        raise ValueError("artifacts must contain 1..1000 entries")
    if not isinstance(stages, list) or not 1 <= len(stages) <= 1000:
        raise ValueError("stages must contain 1..1000 entries")
    artifact_index = {}
    for artifact in artifacts:
        szl_lineage_keys(artifact, ("id", "kind", "sha256"), "artifact")
        key = szl_lineage_text(artifact["id"], "artifact id")
        if key in artifact_index:
            raise ValueError("Duplicate artifact id")
        if artifact["kind"] not in ("source", "derived"):
            raise ValueError("artifact kind must be source or derived")
        szl_lineage_hash(artifact["sha256"], "artifact sha256")
        artifact_index[key] = artifact
    required = manifest["required_stages"]
    if not isinstance(required, list) or not 1 <= len(required) <= 1000:
        raise ValueError("required_stages must contain 1..1000 unique ids")
    for key in required:
        szl_lineage_text(key, "required stage id")
    if len(set(required)) != len(required):
        raise ValueError("Duplicate required stage id")
    observed = manifest["observed_digests"]
    if not isinstance(observed, dict) or any(key not in artifact_index for key in observed):
        raise ValueError("observed_digests must map known artifacts to hashes")
    for value in observed.values():
        szl_lineage_hash(value, "observed digest")
    stage_index, producer, findings = {}, {}, []
    edge_count, required_count = 0, 0
    for stage in stages:
        szl_lineage_keys(stage, ("id", "operation", "code_sha256", "config_sha256", "required_inputs", "inputs", "outputs"), "stage")
        key = szl_lineage_text(stage["id"], "stage id")
        if key in stage_index:
            raise ValueError("Duplicate stage id")
        if not isinstance(stage["operation"], str) or not stage["operation"].strip() or len(stage["operation"]) > 256:
            raise ValueError("operation must describe a transform in 1..256 characters")
        szl_lineage_hash(stage["code_sha256"], "code_sha256")
        szl_lineage_hash(stage["config_sha256"], "config_sha256")
        required_inputs = stage["required_inputs"]
        if not isinstance(required_inputs, list) or not 1 <= len(required_inputs) <= 1000:
            raise ValueError("required_inputs must contain 1..1000 unique known artifact ids")
        if any(not isinstance(item, str) or item not in artifact_index for item in required_inputs) or len(set(required_inputs)) != len(required_inputs):
            raise ValueError("Invalid or duplicate required input")
        required_count += len(required_inputs)
        if required_count > 10000:
            raise ValueError("At most 10000 total required input references are supported")
        for side in ("inputs", "outputs"):
            entries = stage[side]
            if not isinstance(entries, list) or len(entries) > 1000 or (side == "outputs" and not entries):
                raise ValueError("Stage IO exceeds bounds or has no outputs")
            edge_count += len(entries)
            if edge_count > 10000:
                raise ValueError("At most 10000 total stage IO entries are supported")
            seen = set()
            for entry in entries:
                szl_lineage_keys(entry, ("artifact", "sha256"), "stage IO")
                artifact_id = entry["artifact"]
                if not isinstance(artifact_id, str) or artifact_id not in artifact_index or artifact_id in seen:
                    raise ValueError("Unknown or duplicate stage IO artifact")
                seen.add(artifact_id)
                szl_lineage_hash(entry["sha256"], "IO sha256")
                if side == "outputs":
                    if artifact_id in producer:
                        raise ValueError("Duplicate producer for artifact " + artifact_id)
                    if artifact_index[artifact_id]["kind"] == "source":
                        raise ValueError("Source artifact cannot have a producer")
                    producer[artifact_id] = (key, entry["sha256"])
        stage_index[key] = stage
    for key in sorted(set(required) - set(stage_index)):
        findings.append({"code": "MISSING_STAGE", "stage": key, "artifact": None, "detail": "Required stage is absent"})
    for key in sorted(set(stage_index) - set(required)):
        findings.append({"code": "UNDECLARED_STAGE", "stage": key, "artifact": None, "detail": "Stage is outside required_stages"})
    children = {key: set() for key in stage_index}
    pending = {key: set() for key in stage_index}
    for key, stage in stage_index.items():
        inputs = {entry["artifact"]: entry["sha256"] for entry in stage["inputs"]}
        for artifact_id in sorted(set(stage["required_inputs"]) - set(inputs)):
            findings.append({"code": "REQUIRED_INPUT_MISSING", "stage": key, "artifact": artifact_id, "detail": "Declared required input has no edge"})
        for artifact_id in sorted(set(inputs) - set(stage["required_inputs"])):
            findings.append({"code": "UNDECLARED_INPUT", "stage": key, "artifact": artifact_id, "detail": "Input edge is outside required_inputs"})
        for entry in stage["inputs"]:
            artifact_id, digest = entry["artifact"], entry["sha256"]
            if digest != artifact_index[artifact_id]["sha256"]:
                findings.append({"code": "INPUT_DIGEST_MISMATCH", "stage": key, "artifact": artifact_id, "detail": "Consumed digest differs from declared artifact"})
            if artifact_id not in observed:
                findings.append({"code": "INPUT_NOT_OBSERVED", "stage": key, "artifact": artifact_id, "detail": "No readback digest supplied for consumed artifact"})
            elif digest != observed[artifact_id]:
                findings.append({"code": "OBSERVED_INPUT_MISMATCH", "stage": key, "artifact": artifact_id, "detail": "Consumed digest differs from supplied readback"})
            if artifact_id in producer:
                parent, parent_digest = producer[artifact_id]
                children[parent].add(key)
                pending[key].add(parent)
                if digest != parent_digest:
                    findings.append({"code": "PARENT_DIGEST_MISMATCH", "stage": key, "artifact": artifact_id, "detail": "Consumed digest differs from producer output"})
        for entry in stage["outputs"]:
            artifact_id, digest = entry["artifact"], entry["sha256"]
            if digest != artifact_index[artifact_id]["sha256"]:
                findings.append({"code": "OUTPUT_DIGEST_MISMATCH", "stage": key, "artifact": artifact_id, "detail": "Produced digest differs from declared artifact"})
            if artifact_id not in observed:
                findings.append({"code": "OUTPUT_NOT_OBSERVED", "stage": key, "artifact": artifact_id, "detail": "No readback digest supplied for produced artifact"})
            elif digest != observed[artifact_id]:
                findings.append({"code": "OBSERVED_OUTPUT_MISMATCH", "stage": key, "artifact": artifact_id, "detail": "Produced digest differs from supplied readback"})
    ready = [key for key, deps in pending.items() if not deps]
    heapq.heapify(ready)
    order = []
    while ready:
        key = heapq.heappop(ready)
        order.append(key)
        for child in sorted(children[key]):
            pending[child].remove(key)
            if not pending[child]:
                heapq.heappush(ready, child)
    if len(order) != len(stage_index):
        raise ValueError("Cycle in transformation graph; version repeated artifacts instead")
    artifact_reports = []
    referenced_sources = {item for stage in stages for item in stage["required_inputs"]}
    for key in sorted(artifact_index):
        artifact = artifact_index[key]
        if artifact["kind"] == "derived" and key not in producer:
            findings.append({"code": "MISSING_PRODUCER", "stage": None, "artifact": key, "detail": "Derived artifact has no producer"})
        binding = "NOT_OBSERVED" if key not in observed else "MATCH" if artifact["sha256"] == observed[key] else "MISMATCH"
        if binding == "MISMATCH":
            findings.append({"code": "ARTIFACT_DIGEST_MISMATCH", "stage": None, "artifact": key, "detail": "Declared artifact differs from supplied readback"})
        if binding == "NOT_OBSERVED" and artifact["kind"] == "source" and key not in referenced_sources:
            findings.append({"code": "UNOBSERVED_SOURCE", "stage": None, "artifact": key, "detail": "Source has no supplied readback"})
        artifact_reports.append({"id": key, "kind": artifact["kind"], "observation": binding, "producer": producer.get(key, (None, None))[0]})
    findings.sort(key=lambda item: (item["code"], item["stage"] or "", item["artifact"] or ""))
    digest = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()
    return {"schema": "szl.artifact-lineage-report.v1", "status": "REVIEW_REQUIRED" if findings else "CONTINUITY_ON_SUPPLIED_DIGESTS",
            "manifest_sha256": digest, "stage_order": order, "artifacts": artifact_reports, "findings": findings,
            "finding_count": len(findings), "authentic": False, "transformations_executed": False,
            "code_and_config_pins_verified": False, "scientific_validity": "NOT_MEASURED", "behavioral_performance": "NOT_MEASURED"}
