# SPDX-License-Identifier: Apache-2.0
"""Original bounded comparison of a frozen analysis plan and supplied run manifest."""
import hashlib
import json
import math
import re
from datetime import datetime, timezone

SCHEMA = "szl.analysis-plan-audit.v1"
MAX_BYTES = 1048576


def szl_plan_object(value, keys, where):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError(where + " must have exactly: " + ", ".join(sorted(keys)))
    return value


def szl_plan_text(value, where, limit=2048):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(where + " must be bounded nonempty text")
    return value


def szl_plan_id(value, where):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value):
        raise ValueError(where + " must be an identifier of at most 128 characters")
    return value


def szl_plan_digest(value, where):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError(where + " must be a lowercase SHA-256")
    return value


def szl_plan_number(value, where, low=0, high=1e12, strict_low=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high or not math.isfinite(value) or (strict_low and value == low):
        raise ValueError(where + " must be a finite bounded number")
    return value


def szl_plan_time(value, where):
    szl_plan_text(value, where, 40)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value):
        raise ValueError(where + " must be UTC YYYY-MM-DDTHH:MM:SSZ")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as error:
        raise ValueError(where + " is not a valid UTC time") from error


def canonical_sha256(value):
    """Digest of canonical contract JSON; authentic preregistration remains unproven."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def szl_plan_unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def read_json(raw):
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
    return json.loads(text, object_pairs_hook=szl_plan_unique, parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Nonfinite JSON")))


def szl_plan_settings(record, where):
    hypotheses, families = record["hypotheses"], record["families"]
    if not isinstance(hypotheses, list) or not 1 <= len(hypotheses) <= 32 or not isinstance(families, list) or not 1 <= len(families) <= 32:
        raise ValueError(where + " needs 1 to 32 hypotheses and families")
    by_hypothesis, by_family = {}, {}
    keys = ["id", "statement", "primary_metric", "direction", "estimand", "sample_unit", "group_unit", "split_sha256", "alpha", "family", "practical_margin", "exclusions"]
    for hypothesis in hypotheses:
        szl_plan_object(hypothesis, keys, where + ".hypothesis")
        key = szl_plan_id(hypothesis["id"], "hypothesis.id")
        if key in by_hypothesis:
            raise ValueError("Duplicate hypothesis id")
        for name in ["primary_metric", "sample_unit", "group_unit", "family"]:
            szl_plan_id(hypothesis[name], "hypothesis." + name)
        for name in ["statement", "estimand"]:
            szl_plan_text(hypothesis[name], "hypothesis." + name)
        szl_plan_digest(hypothesis["split_sha256"], "hypothesis.split_sha256")
        if hypothesis["direction"] not in ["LOWER", "HIGHER"]:
            raise ValueError("Metric direction must be LOWER or HIGHER")
        szl_plan_number(hypothesis["alpha"], "hypothesis.alpha", 0, 0.1, True)
        szl_plan_number(hypothesis["practical_margin"], "hypothesis.practical_margin")
        exclusions = hypothesis["exclusions"]
        if not isinstance(exclusions, list) or len(exclusions) > 128:
            raise ValueError("exclusions must contain at most 128 criteria")
        seen = set()
        for exclusion in exclusions:
            szl_plan_object(exclusion, ["id", "criterion"], "exclusion")
            ex_id = szl_plan_id(exclusion["id"], "exclusion.id")
            szl_plan_text(exclusion["criterion"], "exclusion.criterion")
            if ex_id in seen:
                raise ValueError("Duplicate exclusion id")
            seen.add(ex_id)
        by_hypothesis[key] = hypothesis
    for family in families:
        szl_plan_object(family, ["id", "method", "alpha", "size"], where + ".family")
        key = szl_plan_id(family["id"], "family.id")
        if key in by_family:
            raise ValueError("Duplicate family id")
        if family["method"] not in ["BONFERRONI", "HOLM", "NONE"]:
            raise ValueError("Supported family methods: BONFERRONI, HOLM, NONE")
        szl_plan_number(family["alpha"], "family.alpha", 0, 0.1, True)
        if type(family["size"]) is not int or not 1 <= family["size"] <= 32:
            raise ValueError("family.size must be an integer 1 to 32")
        if family["method"] == "NONE" and family["size"] != 1:
            raise ValueError("NONE multiplicity is supported only for one hypothesis")
        by_family[key] = family
    if any(h["family"] not in by_family for h in hypotheses):
        raise ValueError("Hypothesis refers to an undeclared family")
    for key, family in by_family.items():
        members = [h for h in hypotheses if h["family"] == key]
        if len(members) != family["size"]:
            raise ValueError("Family size must equal its declared member count")
        for h in members:
            expected = family["alpha"] / family["size"] if family["method"] == "BONFERRONI" else family["alpha"]
            if abs(h["alpha"] - expected) > 1e-12:
                raise ValueError("Hypothesis alpha disagrees with declared family allocation")
    stopping = szl_plan_object(record["stopping_rule"], ["kind", "maximum_attempts"], where + ".stopping_rule")
    if stopping["kind"] != "FIXED_ATTEMPTS" or type(stopping["maximum_attempts"]) is not int or not 1 <= stopping["maximum_attempts"] <= 256:
        raise ValueError("Only FIXED_ATTEMPTS with maximum_attempts 1 to 256 is supported")
    return by_hypothesis, by_family


def szl_plan_flatten(hypotheses, families, stopping):
    result = {"/stopping_rule/" + k: v for k, v in stopping.items()}
    for name, records in [("hypotheses", hypotheses), ("families", families)]:
        for key, record in records.items():
            for field, value in record.items():
                if field != "id":
                    result["/" + name + "/" + key + "/" + field] = value
            result["/" + name + "/" + key] = True
    return result


def szl_audit_analysis_plan(payload):
    """Compare declared fixed settings, prespecification and complete attempt/deviation logs."""
    szl_plan_object(payload, ["schema", "plan", "run", "deviations"], "input")
    if payload["schema"] != SCHEMA:
        raise ValueError("Unsupported input schema")
    plan = szl_plan_object(payload["plan"], ["id", "version", "frozen_at", "hypotheses", "families", "stopping_rule", "scheduled_attempts"], "plan")
    run = szl_plan_object(payload["run"], ["plan_id", "plan_version", "plan_sha256", "started_at", "completed_at", "precommit_declared", "hypotheses", "families", "stopping_rule", "attempts"], "run")
    szl_plan_id(plan["id"], "plan.id")
    szl_plan_id(run["plan_id"], "run.plan_id")
    for value in [plan["version"], run["plan_version"]]:
        if type(value) is not int or not 1 <= value <= 100000:
            raise ValueError("Plan versions must be positive bounded integers")
    szl_plan_digest(run["plan_sha256"], "run.plan_sha256")
    if type(run["precommit_declared"]) is not bool:
        raise ValueError("precommit_declared must be Boolean")
    frozen, started, completed = szl_plan_time(plan["frozen_at"], "plan.frozen_at"), szl_plan_time(run["started_at"], "run.started_at"), szl_plan_time(run["completed_at"], "run.completed_at")
    expected_h, expected_f = szl_plan_settings(plan, "plan")
    actual_h, actual_f = szl_plan_settings(run, "run")
    plan_hash = canonical_sha256(plan)
    findings = []

    def finding(code, path, detail=""):
        findings.append({"code": code, "path": path, "detail": detail})

    if plan["id"] != run["plan_id"] or plan["version"] != run["plan_version"]:
        finding("PLAN_VERSION_MISMATCH", "/run/plan_version")
    if plan_hash != run["plan_sha256"]:
        finding("PLAN_DIGEST_MISMATCH", "/run/plan_sha256")
    if not run["precommit_declared"]:
        finding("PRECOMMIT_UNPROVEN", "/run/precommit_declared")
    if frozen > started or completed < started:
        finding("PLAN_TIMING_CONFLICT", "/run/started_at")
    scheduled = plan["scheduled_attempts"]
    if not isinstance(scheduled, list) or not 1 <= len(scheduled) <= 256:
        raise ValueError("scheduled_attempts must contain 1 to 256 records")
    expected_attempts = {}
    for attempt in scheduled:
        szl_plan_object(attempt, ["id", "hypothesis_id"], "scheduled attempt")
        key = szl_plan_id(attempt["id"], "attempt.id")
        szl_plan_id(attempt["hypothesis_id"], "attempt.hypothesis_id")
        if key in expected_attempts or attempt["hypothesis_id"] not in expected_h:
            raise ValueError("Duplicate scheduled attempt or unknown hypothesis")
        expected_attempts[key] = attempt["hypothesis_id"]
    if len(scheduled) != plan["stopping_rule"]["maximum_attempts"]:
        raise ValueError("Fixed stopping rule must match scheduled attempt count")
    if set(expected_attempts.values()) != set(expected_h):
        raise ValueError("Every planned hypothesis needs a scheduled attempt")
    attempts = run["attempts"]
    if not isinstance(attempts, list) or len(attempts) > 256:
        raise ValueError("attempts must be a list of at most 256 records")
    observed, counts = set(), {"SUCCESS": 0, "FAILED": 0, "ABORTED": 0}
    for attempt in attempts:
        szl_plan_object(attempt, ["id", "hypothesis_id", "status", "recorded_at", "result_sha256", "failure_reason"], "run attempt")
        key = szl_plan_id(attempt["id"], "attempt.id")
        hypothesis_id = szl_plan_id(attempt["hypothesis_id"], "attempt.hypothesis_id")
        if key in observed:
            raise ValueError("Duplicate observed attempt")
        observed.add(key)
        if not isinstance(attempt["status"], str) or attempt["status"] not in counts:
            raise ValueError("Attempt status must be SUCCESS, FAILED or ABORTED")
        counts[attempt["status"]] += 1
        recorded = szl_plan_time(attempt["recorded_at"], "attempt.recorded_at")
        if recorded < started or recorded > completed:
            finding("ATTEMPT_TIMING_CONFLICT", "/attempts/" + key)
        if attempt["status"] == "SUCCESS":
            szl_plan_digest(attempt["result_sha256"], "attempt.result_sha256")
            if attempt["failure_reason"] is not None:
                raise ValueError("Successful attempt must have null failure_reason")
        else:
            if attempt["result_sha256"] is not None:
                raise ValueError("Failed or aborted attempt must have null result_sha256")
            szl_plan_text(attempt["failure_reason"], "attempt.failure_reason")
        if key not in expected_attempts:
            finding("UNSCHEDULED_ATTEMPT", "/attempts/" + key)
        elif hypothesis_id != expected_attempts[key]:
            finding("ATTEMPT_HYPOTHESIS_MISMATCH", "/attempts/" + key)
    for key in sorted(set(expected_attempts) - observed):
        finding("MISSING_SCHEDULED_ATTEMPT", "/attempts/" + key)
    if len(attempts) > run["stopping_rule"]["maximum_attempts"]:
        finding("STOPPING_LIMIT_EXCEEDED", "/stopping_rule/maximum_attempts")
    old, new = szl_plan_flatten(expected_h, expected_f, plan["stopping_rule"]), szl_plan_flatten(actual_h, actual_f, run["stopping_rule"])
    changed = {path: (old.get(path), new.get(path)) for path in set(old) | set(new) if canonical_sha256(old.get(path)) != canonical_sha256(new.get(path))}
    deviations = payload["deviations"]
    if not isinstance(deviations, list) or len(deviations) > 256:
        raise ValueError("deviations must contain at most 256 records")
    logged, seen_ids = set(), set()
    for deviation in deviations:
        szl_plan_object(deviation, ["id", "plan_version", "path", "planned_sha256", "observed_sha256", "declared_at", "reason"], "deviation")
        key = szl_plan_id(deviation["id"], "deviation.id")
        path = szl_plan_text(deviation["path"], "deviation.path", 512)
        if not path.startswith("/") or key in seen_ids or path in logged:
            raise ValueError("Deviation ids and paths must be unique JSON-style paths")
        seen_ids.add(key)
        logged.add(path)
        if type(deviation["plan_version"]) is not int or not 1 <= deviation["plan_version"] <= 100000:
            raise ValueError("deviation.plan_version must be a positive bounded integer")
        szl_plan_digest(deviation["planned_sha256"], "deviation.planned_sha256")
        szl_plan_digest(deviation["observed_sha256"], "deviation.observed_sha256")
        szl_plan_text(deviation["reason"], "deviation.reason")
        declared = szl_plan_time(deviation["declared_at"], "deviation.declared_at")
        if path not in changed:
            finding("DEVIATION_WITHOUT_SETTING_CHANGE", path)
        else:
            previous, current = changed[path]
            if deviation["plan_version"] != plan["version"] or deviation["planned_sha256"] != canonical_sha256(previous) or deviation["observed_sha256"] != canonical_sha256(current):
                finding("DEVIATION_BINDING_MISMATCH", path)
            finding("LOGGED_EXPLORATORY_DEVIATION", path, key)
        if declared > completed or declared < frozen:
            finding("DEVIATION_TIMING_CONFLICT", path)
        if declared >= started:
            finding("DEVIATION_AFTER_RUN_START", path)
    for path in sorted(set(changed) - logged):
        finding("UNLOGGED_DEVIATION", path)
    findings.sort(key=lambda f: (f["path"], f["code"], f["detail"]))
    return {"schema": "szl.analysis-plan-audit-report.v1", "status": "EXPLORATORY" if findings else "CONSISTENT_WITH_DECLARED_PLAN", "plan_sha256": plan_hash, "run_sha256": canonical_sha256(run), "findings": findings, "changes": [{"path": path, "planned_sha256": canonical_sha256(values[0]), "observed_sha256": canonical_sha256(values[1])} for path, values in sorted(changed.items())], "attempt_counts": counts, "scheduled_attempt_count": len(scheduled), "observed_attempt_count": len(attempts), "preregistration": "DECLARED_ONLY", "result_binding": "DECLARED_DIGEST_ONLY", "statistical_inference": "NOT_PERFORMED", "scientific_performance": "NOT_MEASURED", "promotion_effect": "NONE"}
