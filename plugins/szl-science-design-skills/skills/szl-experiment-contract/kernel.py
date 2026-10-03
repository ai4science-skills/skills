# SPDX-License-Identifier: Apache-2.0
"""Bounded, offline completeness check for a prospective experiment draft."""

import hashlib
import json
import re

SCHEMA = "szl.experiment-contract.input/v1"
MAX_BYTES = 131072
FIELDS = (
    "question", "population", "intervention", "comparator", "primary_metric",
    "direction", "estimand", "experimental_unit", "allocation_unit",
    "analysis_unit", "control", "measurement_window", "exclusion_rule",
    "falsifier", "harm_limit", "cheapest_decisive_measurement",
    "dependence_plan",
)
QUESTIONS = {
    "question": "What decision would this experiment answer?",
    "population": "Which population or setting is the target?",
    "intervention": "What is changed, by whom, and at what unit?",
    "comparator": "What is the contemporaneous baseline or control condition?",
    "primary_metric": "What single primary measurement determines the result?",
    "direction": "Is a higher or lower primary metric better?",
    "estimand": "What population-level contrast is to be estimated?",
    "experimental_unit": "What is the independent experimental unit?",
    "allocation_unit": "At what unit is treatment assigned?",
    "analysis_unit": "At what unit will the primary analysis operate?",
    "control": "Which control checks the key alternative explanation?",
    "measurement_window": "When is the primary metric measured?",
    "exclusion_rule": "Which exclusions are declared before seeing outcomes?",
    "falsifier": "What observable result would count against the proposal?",
    "harm_limit": "What signal stops or limits the experiment for harm?",
    "cheapest_decisive_measurement": "What is the cheapest measurement that can distinguish the alternatives?",
    "dependence_plan": "How will dependence across allocation and analysis units be handled?",
}


def szl_contract_pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def szl_contract_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def read_json(raw):
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
        raise ValueError("input must be UTF-8 JSON of at most 128 KiB")
    source = raw.decode("utf-8")
    depth, quoted, escaped = 0, False, False
    for character in source:
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
            if depth > 16:
                raise ValueError("JSON nesting exceeds 16")
        elif character in "]}":
            depth -= 1
    payload = json.loads(source, object_pairs_hook=szl_contract_pairs,
                         parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
    szl_contract_bytes(payload)
    return payload


def szl_contract_text(value, where, nullable=False):
    if nullable and value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > 2048:
        raise ValueError(where + " must be bounded nonempty text or null")
    return value.strip()


def szl_contract_id(value, where):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value):
        raise ValueError(where + " must be a bounded identifier")
    return value


def szl_draft_experiment_contract(payload):
    if not isinstance(payload, dict) or set(payload) != {"schema", "study_id", "fields", "assumptions", "source_ids"}:
        raise ValueError("input must contain exactly schema, study_id, fields, assumptions, source_ids")
    if payload["schema"] != SCHEMA:
        raise ValueError("unsupported experiment-contract schema")
    study_id = szl_contract_id(payload["study_id"], "study_id")
    fields = payload["fields"]
    if not isinstance(fields, dict) or set(fields) != set(FIELDS):
        raise ValueError("fields must contain the exact experiment-contract field set")
    declared = {key: szl_contract_text(fields[key], "fields." + key, nullable=True) for key in FIELDS}
    if declared["direction"] not in (None, "HIGHER", "LOWER"):
        raise ValueError("direction must be HIGHER, LOWER, or null")

    assumptions = payload["assumptions"]
    if not isinstance(assumptions, list) or len(assumptions) > 16:
        raise ValueError("assumptions must be an array of at most 16 entries")
    normalized_assumptions, assumption_ids = [], set()
    for index, item in enumerate(assumptions):
        if not isinstance(item, dict) or set(item) != {"id", "statement", "check"}:
            raise ValueError("each assumption needs exactly id, statement, check")
        identifier = szl_contract_id(item["id"], "assumptions.id")
        if identifier in assumption_ids:
            raise ValueError("duplicate assumption id")
        assumption_ids.add(identifier)
        normalized_assumptions.append({
            "id": identifier,
            "statement": szl_contract_text(item["statement"], "assumptions.statement"),
            "check": szl_contract_text(item["check"], "assumptions.check", nullable=True),
        })

    source_ids = payload["source_ids"]
    if not isinstance(source_ids, list) or len(source_ids) > 16:
        raise ValueError("source_ids must be an array of at most 16 entries")
    normalized_sources = [szl_contract_text(value, "source_ids entry",) for value in source_ids]
    if len(set(normalized_sources)) != len(normalized_sources):
        raise ValueError("duplicate source id")

    unit_mismatch = (declared["experimental_unit"] is not None
                     and declared["allocation_unit"] is not None
                     and declared["analysis_unit"] is not None
                     and len({declared["experimental_unit"], declared["allocation_unit"], declared["analysis_unit"]}) > 1)
    gaps = [key for key in FIELDS if declared[key] is None and (key != "dependence_plan" or unit_mismatch)]
    if not normalized_assumptions:
        gaps.append("assumptions")
    gaps.extend("assumptions." + item["id"] + ".check" for item in normalized_assumptions if item["check"] is None)
    questions = [{"field": gap, "question": QUESTIONS.get(gap, "How will this assumption be checked?")}
                 for gap in gaps]
    all_units_equal = (declared["experimental_unit"] is not None
                       and declared["experimental_unit"] == declared["allocation_unit"] == declared["analysis_unit"])
    handoff = {
        "target": "szl-analysis-plan-audit",
        "state": "NOT_FROZEN",
        "candidate_fields": {
            "primary_metric": declared["primary_metric"],
            "direction": declared["direction"],
            "estimand": declared["estimand"],
            "sample_unit": declared["analysis_unit"] if all_units_equal else None,
            "group_unit": declared["experimental_unit"] if all_units_equal else None,
        },
        "still_required": ["frozen_at", "split_sha256", "alpha", "family",
                           "practical_margin", "exclusions", "stopping_rule", "scheduled_attempts"],
        "unit_mapping": "CANDIDATE_ONLY_RESEARCHER_MUST_CONFIRM" if all_units_equal else "UNRESOLVED",
    }
    digest = hashlib.sha256(szl_contract_bytes(payload)).hexdigest()
    return {
        "schema": "szl.experiment-contract.draft/v1",
        "study_id": study_id,
        "input_sha256": digest,
        "state": "NEEDS_RESEARCHER_INPUT" if gaps else "DRAFT_READY_FOR_REVIEW",
        "design": declared,
        "assumptions": normalized_assumptions,
        "source_ids": normalized_sources,
        "source_reference_state": "DECLARED_NOT_VERIFIED" if normalized_sources else "NOT_PROVIDED",
        "unit_relation": "DEPENDENCE_PLAN_DECLARED_NOT_VALIDATED" if unit_mismatch and declared["dependence_plan"] else ("UNRESOLVED" if unit_mismatch else "SAME_UNIT_DECLARED_NOT_VALIDATED" if all_units_equal else "INCOMPLETE"),
        "review_questions": questions,
        "analysis_plan_handoff": handoff,
        "preregistration": "NOT_REGISTERED",
        "experiment_execution": "NOT_PERFORMED",
        "statistical_inference": "NOT_PERFORMED",
        "scientific_efficacy": "NOT_EVALUATED",
    }
