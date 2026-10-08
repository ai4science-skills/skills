#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Modified 2026-09-30: original inline case/artifact binding and loss readback.
"""Offline bounded paired comparison. Source/dependency/data rights are not certified."""
import argparse
import hashlib
import itertools
import json
import math
import pathlib
import re
import sys

MAX_BYTES = 1024 * 1024
MAX_JSON_DEPTH = 64
TOP = {"schema", "source_revision", "dataset_sha256", "plan_sha256", "input_scope",
       "pre_registered", "independent_pairs", "alpha", "minimum_normalized_improvement",
       "identity_control_tolerance", "train_ids", "test_ids", "tasks"}
TASK = {"id", "loss_unit", "training_scale", "scale_scope", "expected_trial_ids", "trials"}
TRIAL = {"id", "baseline_loss", "treatment_loss", "identity_control_loss",
         "baseline_predictions_sha256", "treatment_predictions_sha256",
         "identity_control_predictions_sha256"}


class ProtocolError(ValueError):
    pass


def keys(value, expected, label):
    if not isinstance(value, dict) or set(value) != expected:
        raise ProtocolError(label + ": fields must exactly match protocol")


def number(value, label, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProtocolError(label + ": numeric value required")
    try:
        finite = math.isfinite(value)
    except OverflowError as error:
        raise ProtocolError(label + ": numeric magnitude exceeds budget") from error
    if not finite or value < 0 or (positive and value <= 0):
        raise ProtocolError(label + ": finite " + ("positive" if positive else "nonnegative") + " value required")
    return value


def identifier(value, label):
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ProtocolError(label + ": nonempty identifier of at most 256 characters required")
    return value


def digest(value, length, label):
    if not isinstance(value, str) or not re.fullmatch("[a-f0-9]{%d}" % length, value):
        raise ProtocolError(label + ": exact lowercase hash required")


def identifiers(value, label, minimum=1, maximum=10000):
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ProtocolError(label + ": invalid identifier count")
    for item in value:
        identifier(item, label)
    if len(set(value)) != len(value):
        raise ProtocolError(label + ": duplicate identifiers")
    return set(value)


def sign_flip_p(deltas):
    """Exact one-sided paired randomization, bounded by protocol n <= 16."""
    if not deltas or len(deltas) > 16 or any(not math.isfinite(x) for x in deltas):
        raise ProtocolError("invalid sign-flip inputs")
    observed = math.fsum(deltas)
    tail = sum(math.fsum(s * d for s, d in zip(signs, deltas)) >= observed
               for signs in itertools.product((-1, 1), repeat=len(deltas)))
    return tail / (2 ** len(deltas))


def _qualify_v1(plan, validation_only=False):
    keys(plan, TOP, "experiment")
    if plan["schema"] != "szl.paired-science/v1":
        raise ProtocolError("unsupported schema")
    digest(plan["source_revision"], 40, "source_revision")
    for field in ("dataset_sha256", "plan_sha256"):
        digest(plan[field], 64, field)
    if plan["input_scope"] not in ("SYNTHETIC", "EXTERNAL", "MIXED"):
        raise ProtocolError("unknown input scope")
    for field in ("pre_registered", "independent_pairs"):
        if type(plan[field]) is not bool:
            raise ProtocolError(field + ": boolean required")
    alpha = number(plan["alpha"], "alpha", True)
    if alpha > 0.1:
        raise ProtocolError("alpha must be <= 0.1")
    minimum = number(plan["minimum_normalized_improvement"], "minimum effect")
    tolerance = number(plan["identity_control_tolerance"], "control tolerance")
    train = identifiers(plan["train_ids"], "train_ids")
    test = identifiers(plan["test_ids"], "test_ids")
    if train & test:
        raise ProtocolError("train/test identifiers overlap")
    tasks = plan["tasks"]
    if not isinstance(tasks, list) or not 1 <= len(tasks) <= 8:
        raise ProtocolError("tasks must contain 1 to 8 entries")
    seen, results, blockers = set(), [], []
    if not plan["pre_registered"]:
        blockers.append("PLAN_NOT_DECLARED_PRE_REGISTERED")
    if not plan["independent_pairs"]:
        blockers.append("INDEPENDENT_PAIRS_NOT_DECLARED")
    for task in tasks:
        keys(task, TASK, "task")
        task_id = identifier(task["id"], "task id")
        if task_id in seen:
            raise ProtocolError("duplicate task id")
        seen.add(task_id)
        identifier(task["loss_unit"], "loss unit")
        scale = number(task["training_scale"], "training scale", True)
        if task["scale_scope"] != "TRAIN_ONLY":
            raise ProtocolError("normalization scale must be TRAIN_ONLY")
        expected = identifiers(task["expected_trial_ids"], "expected trials", 3, 16)
        trials = task["trials"]
        if not isinstance(trials, list) or len(trials) != len(expected):
            raise ProtocolError("trial coverage is incomplete")
        trial_ids, deltas, controls = set(), [], True
        for trial in trials:
            keys(trial, TRIAL, "trial")
            trial_id = identifier(trial["id"], "trial id")
            if trial_id in trial_ids or trial_id not in expected:
                raise ProtocolError("duplicate or unexpected trial")
            trial_ids.add(trial_id)
            baseline = number(trial["baseline_loss"], "baseline loss")
            treatment = number(trial["treatment_loss"], "treatment loss")
            control = number(trial["identity_control_loss"], "identity loss")
            delta = (baseline - treatment) / scale
            control_delta = (baseline - control) / scale
            if not math.isfinite(delta) or not math.isfinite(control_delta):
                raise ProtocolError("normalized loss overflow")
            deltas.append(delta)
            for field in ("baseline_predictions_sha256", "treatment_predictions_sha256", "identity_control_predictions_sha256"):
                digest(trial[field], 64, field)
            controls &= (trial["baseline_predictions_sha256"] == trial["identity_control_predictions_sha256"]
                         and abs(control_delta) <= tolerance)
        if validation_only:
            continue
        mean = math.fsum(deltas) / len(deltas)
        p_value = sign_flip_p(deltas)
        adjusted = min(1.0, p_value * len(tasks))
        accepted = controls and mean > 0 and mean >= minimum and adjusted <= alpha
        results.append({"id": task_id, "loss_unit": task["loss_unit"], "pairs": len(deltas),
                        "normalized_pair_improvements": deltas, "mean_normalized_improvement": mean,
                        "sign_flip_p": p_value, "bonferroni_p": adjusted,
                        "identity_control_passed": bool(controls), "qualified": accepted})
        if not accepted:
            blockers.append("TASK_NOT_QUALIFIED:" + task_id)
    if validation_only:
        return None
    return {"schema": "szl.paired-science-report/v1",
            "status": "REJECTED_LOCAL_COMPARISON" if blockers else "QUALIFIED_LOCAL_COMPARISON",
            "production_authority": "NONE", "input_scope": plan["input_scope"],
            "declarations_independently_verified": False,
            "declared_source_revision": plan["source_revision"],
            "declared_dataset_sha256": plan["dataset_sha256"], "declared_plan_sha256": plan["plan_sha256"],
            "raw_cross_task_average": None, "tasks": results, "blockers": blockers}


def canonical_bytes(value):
    """The v2 projection encoding; raw artifacts are hashed without reserialization."""
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError, UnicodeError) as error:
        raise ProtocolError("bounded JSON evidence required") from error
    if len(raw) > MAX_BYTES:
        raise ProtocolError("evidence exceeds 1 MiB")
    return raw


def sha256(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def signed_number(value, label):
    if type(value) not in (int, float):
        raise ProtocolError(label + ": finite numeric value required, excluding booleans")
    try:
        finite = math.isfinite(value)
    except OverflowError as error:
        raise ProtocolError(label + ": numeric magnitude exceeds budget") from error
    if not finite:
        raise ProtocolError(label + ": finite numeric value required")
    return value


def _artifact(value, label, findings, missing):
    if value is None:
        missing.append(label)
        return None
    keys(value, {"utf8", "sha256"}, label)
    digest(value["sha256"], 64, label + " digest")
    if value["utf8"] is None:
        missing.append(label)
        return None
    if type(value["utf8"]) is not str:
        raise ProtocolError(label + ": utf8 text or null required")
    try:
        raw = value["utf8"].encode("utf-8")
    except UnicodeError as error:
        raise ProtocolError(label + ": valid UTF-8 required") from error
    if len(raw) > 262144:
        raise ProtocolError(label + ": artifact exceeds 256 KiB")
    actual = hashlib.sha256(raw).hexdigest()
    if actual != value["sha256"]:
        findings.append("ARTIFACT_DIGEST_MISMATCH:" + label)
    return raw, actual


def _metric(predictions, targets, metric):
    try:
        terms = [abs(a - b) if metric == "mae" else (a - b) ** 2 for a, b in zip(predictions, targets)]
        result = math.fsum(terms) / len(terms)
    except (OverflowError, ZeroDivisionError) as error:
        raise ProtocolError("recomputed loss exceeds numeric budget") from error
    if not math.isfinite(result):
        raise ProtocolError("recomputed loss overflow")
    return result


def plan_projection(plan, digests):
    """Build the inert prespecified plan object for the actual supplied bindings."""
    fields = ("source_revision", "input_scope", "pre_registered", "independent_pairs", "alpha",
              "minimum_normalized_improvement", "identity_control_tolerance")
    result = {field: plan[field] for field in fields}
    result.update(schema="szl.paired-plan/v1", train_ids=sorted(plan["train_ids"]), test_ids=sorted(plan["test_ids"]),
                  artifact_digests=digests,
                  tasks=[{field: task[field] for field in ("id", "loss_unit", "training_scale", "scale_scope")}
                         | {"expected_trial_ids": sorted(task["expected_trial_ids"])}
                         for task in sorted(plan["tasks"], key=lambda t: t["id"])])
    return result


def _verify_bindings(plan, expected_manifest_sha256):
    findings, missing = [], []
    bindings = plan["bindings"]
    if bindings is None:
        return {"status": "DECLARED", "findings": [], "missing_evidence": ["bindings"], "digests": {}}
    keys(bindings, {"schema", "cases", "corpus", "scorer", "normalization", "plan", "trials"}, "bindings")
    if bindings["schema"] != "szl.paired-bindings/v1":
        raise ProtocolError("unsupported binding schema")
    train = identifiers(plan["train_ids"], "train_ids")
    test = identifiers(plan["test_ids"], "test_ids")
    if train & test:
        raise ProtocolError("train/test identifiers overlap")
    if type(plan["tasks"]) is not list or not 1 <= len(plan["tasks"]) <= 8:
        raise ProtocolError("tasks must contain 1 to 8 entries")
    tasks = {}
    expected_pairs = {}
    for task in plan["tasks"]:
        keys(task, TASK, "task")
        task_id = identifier(task["id"], "task id")
        if task_id in tasks:
            raise ProtocolError("duplicate task id")
        tasks[task_id] = task
        expected = identifiers(task["expected_trial_ids"], "expected trials", 3, 16)
        if type(task["trials"]) is not list or len(task["trials"]) != len(expected):
            raise ProtocolError("trial coverage is incomplete")
        for trial in task["trials"]:
            keys(trial, TRIAL, "trial")
            trial_id = identifier(trial["id"], "trial id")
            if trial_id not in expected or (task_id, trial_id) in expected_pairs:
                raise ProtocolError("duplicate or unexpected trial")
            expected_pairs[(task_id, trial_id)] = trial
    case_list = bindings["cases"]
    if type(case_list) is not list or not 1 <= len(case_list) <= 10000:
        raise ProtocolError("cases must contain 1 to 10000 entries")
    cases, targets, case_hashes = {}, {}, []
    for case in case_list:
        keys(case, {"id", "input", "target"}, "case")
        case_id = identifier(case["id"], "case id")
        if case_id in cases or case_id not in train | test:
            raise ProtocolError("duplicate or unexpected case id")
        input_bytes = _artifact(case["input"], "input:" + case_id, findings, missing)
        target_bytes = _artifact(case["target"], "target:" + case_id, findings, missing)
        cases[case_id] = (input_bytes, target_bytes)
        if target_bytes is not None:
            targets[case_id] = signed_number(load_bytes(target_bytes[0]), "target")
        if input_bytes is not None and target_bytes is not None:
            case_hashes.append({"case_id": case_id, "input_sha256": input_bytes[1], "target_sha256": target_bytes[1]})
    if set(cases) != train | test:
        missing.append("case coverage")
    artifacts = {name: _artifact(bindings[name], name, findings, missing)
                 for name in ("corpus", "scorer", "normalization", "plan")}
    if missing:
        return {"status": "DECLARED", "findings": findings, "missing_evidence": sorted(missing), "digests": {}}
    corpus, scorer, normalization, actual_plan = (artifacts[name] for name in ("corpus", "scorer", "normalization", "plan"))
    if corpus[1] != plan["dataset_sha256"]:
        findings.append("CORPUS_DECLARATION_MISMATCH")
    if actual_plan[1] != plan["plan_sha256"]:
        findings.append("PLAN_DECLARATION_MISMATCH")
    case_hashes.sort(key=lambda item: item["case_id"])
    digests = {"corpus_sha256": corpus[1], "scorer_sha256": scorer[1], "normalization_sha256": normalization[1],
               "case_bindings_sha256": sha256(case_hashes)}
    frozen_manifest_digest = sha256(digests)
    if expected_manifest_sha256 is None:
        missing.append("separately frozen manifest digest")
    elif frozen_manifest_digest != expected_manifest_sha256:
        findings.append("FROZEN_MANIFEST_MISMATCH")
    parsed_plan = load_bytes(actual_plan[0])
    if parsed_plan != plan_projection(plan, digests):
        findings.append("PRESPECIFIED_PLAN_BINDING_MISMATCH")
    score_spec = load_bytes(scorer[0])
    keys(score_spec, {"schema", "tasks"}, "scorer")
    if score_spec["schema"] != "szl.scorer/v1" or type(score_spec["tasks"]) is not list:
        raise ProtocolError("unsupported inert scorer schema")
    metrics = {}
    for record in score_spec["tasks"]:
        keys(record, {"task_id", "metric", "loss_unit"}, "scorer task")
        task_id = identifier(record["task_id"], "scorer task id")
        if task_id not in tasks or task_id in metrics or record["metric"] not in ("mae", "mse"):
            raise ProtocolError("duplicate/unknown task or unsupported scorer metric")
        if record["loss_unit"] != tasks[task_id]["loss_unit"]:
            findings.append("SCORER_UNIT_MISMATCH:" + task_id)
        metrics[task_id] = record["metric"]
    if set(metrics) != set(tasks):
        raise ProtocolError("scorer task coverage is incomplete")
    norm_spec = load_bytes(normalization[0])
    keys(norm_spec, {"schema", "tasks"}, "normalization")
    if norm_spec["schema"] != "szl.normalization/v1" or type(norm_spec["tasks"]) is not list:
        raise ProtocolError("unsupported normalization schema")
    norm_tasks = set()
    for record in norm_spec["tasks"]:
        keys(record, {"task_id", "records"}, "normalization task")
        task_id = identifier(record["task_id"], "normalization task id")
        if task_id not in tasks or task_id in norm_tasks or type(record["records"]) is not list:
            raise ProtocolError("duplicate/unknown normalization task")
        norm_tasks.add(task_id)
        values, ids = [], set()
        for row in record["records"]:
            keys(row, {"case_id", "prediction"}, "normalization record")
            case_id = identifier(row["case_id"], "normalization case id")
            if case_id not in train or case_id in ids:
                raise ProtocolError("normalization must contain training cases only, once each")
            ids.add(case_id)
            values.append((signed_number(row["prediction"], "training prediction"), targets[case_id]))
        if ids != train:
            raise ProtocolError("normalization training coverage incomplete")
        scale = _metric([p for p, _ in values], [t for _, t in values], metrics[task_id])
        declared = number(tasks[task_id]["training_scale"], "training scale", True)
        if not math.isclose(scale, declared, rel_tol=1e-12, abs_tol=1e-12):
            findings.append("TRAINING_SCALE_READBACK_MISMATCH:" + task_id)
    if norm_tasks != set(tasks):
        raise ProtocolError("normalization task coverage incomplete")
    input_digest = sha256([{"case_id": i, "sha256": cases[i][0][1]} for i in sorted(test)])
    target_digest = sha256([{"case_id": i, "sha256": cases[i][1][1]} for i in sorted(test)])
    digests.update(input_sha256=input_digest, target_sha256=target_digest)
    trial_bindings = bindings["trials"]
    if type(trial_bindings) is not list or len(trial_bindings) != len(expected_pairs):
        raise ProtocolError("trial binding coverage incomplete")
    seen = set()
    envelope_fields = {"schema", "task_id", "trial_id", "input_sha256", "target_sha256", "corpus_sha256",
                       "scorer_sha256", "normalization_sha256", "predictions"}
    for record in trial_bindings:
        keys(record, {"task_id", "trial_id", "baseline", "treatment", "identity_control"}, "trial binding")
        pair = (identifier(record["task_id"], "bound task id"), identifier(record["trial_id"], "bound trial id"))
        if pair not in expected_pairs or pair in seen:
            raise ProtocolError("duplicate/unexpected trial binding")
        seen.add(pair)
        trial = expected_pairs[pair]
        for role in ("baseline", "treatment", "identity_control"):
            label = pair[0] + ":" + pair[1] + ":" + role
            artifact = _artifact(record[role], label, findings, missing)
            if artifact is None:
                continue
            if artifact[1] != trial[role + "_predictions_sha256"]:
                findings.append("PREDICTION_DECLARATION_MISMATCH:" + label)
            envelope = load_bytes(artifact[0])
            keys(envelope, envelope_fields, "prediction envelope")
            if envelope["schema"] != "szl.predictions/v1" or (envelope["task_id"], envelope["trial_id"]) != pair:
                findings.append("PAIR_BINDING_MISMATCH:" + label)
            for field in ("input_sha256", "target_sha256", "corpus_sha256", "scorer_sha256", "normalization_sha256"):
                digest(envelope[field], 64, "envelope " + field)
                if envelope[field] != digests[field]:
                    findings.append(field.upper() + "_BINDING_MISMATCH:" + label)
            predictions = envelope["predictions"]
            if type(predictions) is not list or len(predictions) != len(test):
                raise ProtocolError("prediction case coverage incomplete")
            values = {}
            for row in predictions:
                keys(row, {"case_id", "value"}, "prediction")
                case_id = identifier(row["case_id"], "prediction case id")
                if case_id not in test or case_id in values:
                    raise ProtocolError("duplicate/substituted prediction case")
                values[case_id] = signed_number(row["value"], "prediction value")
            loss = _metric([values[i] for i in sorted(test)], [targets[i] for i in sorted(test)], metrics[pair[0]])
            declared = number(trial[role + "_loss"], "declared loss")
            if not math.isclose(loss, declared, rel_tol=1e-12, abs_tol=1e-12):
                findings.append("LOSS_READBACK_MISMATCH:" + label)
    return {"status": "DECLARED" if missing else "MISMATCH" if findings else "VERIFIED_INLINE_BYTES",
            "findings": sorted(set(findings)), "missing_evidence": sorted(missing), "digests": digests,
            "manifest_sha256": frozen_manifest_digest, "expected_manifest_sha256": expected_manifest_sha256,
            "loss_readback_tolerance": {"relative": 1e-12, "absolute": 1e-12}}


def qualify(plan, *, expected_manifest_sha256=None):
    if type(plan) is not dict:
        raise ProtocolError("experiment must be an object")
    if plan.get("schema") == "szl.paired-science/v1":
        report = _qualify_v1(plan)
        report.update(binding_status="DECLARED", binding_evidence={"missing_evidence": ["actual input/target/corpus/scorer/normalization/prediction bytes"]},
                      scientific_performance="NOT_MEASURED")
        return report
    keys(plan, TOP | {"bindings"}, "experiment v2")
    if plan["schema"] != "szl.paired-science/v2":
        raise ProtocolError("unsupported schema")
    canonical_bytes(plan)
    digest(plan["source_revision"], 40, "source_revision")
    digest(plan["dataset_sha256"], 64, "dataset_sha256")
    digest(plan["plan_sha256"], 64, "plan_sha256")
    if expected_manifest_sha256 is not None:
        digest(expected_manifest_sha256, 64, "external frozen manifest digest")
    legacy = {key: value for key, value in plan.items() if key != "bindings"}
    legacy["schema"] = "szl.paired-science/v1"
    _qualify_v1(legacy, validation_only=True)
    binding = _verify_bindings(plan, expected_manifest_sha256)
    if binding["status"] != "VERIFIED_INLINE_BYTES":
        return {"schema": "szl.paired-science-report/v2", "status": "REJECTED_LOCAL_COMPARISON",
                "binding_status": binding["status"], "binding_evidence": binding,
                "production_authority": "NONE", "statistical_evaluation": "NOT_RUN",
                "scientific_performance": "NOT_MEASURED", "tasks": [], "raw_cross_task_average": None,
                "blockers": ["ACTUAL_ARTIFACT_BINDING_REQUIRED"] + binding["findings"]}
    report = _qualify_v1(legacy)
    report.update(schema="szl.paired-science-report/v2", binding_status=binding["status"], binding_evidence=binding,
                  scientific_performance="NOT_MEASURED", consumption_verified=False, source_authenticity="NOT_VERIFIED",
                  limitations=["Inline bytes and loss readback do not prove model consumption or source authenticity",
                               "Independence, plan timing, rights and causal validity remain unverified"])
    return report


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ProtocolError("duplicate JSON key")
        value[key] = item
    return value


def load_bytes(raw):
    if len(raw) > MAX_BYTES:
        raise ProtocolError("input exceeds 1 MiB")
    depth, quoted, escaped = 0, False, False
    for byte in raw:
        if quoted:
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                quoted = False
        elif byte == 34:
            quoted = True
        elif byte in (91, 123):
            depth += 1
            if depth > MAX_JSON_DEPTH:
                raise ProtocolError("JSON nesting exceeds 64 levels")
        elif byte in (93, 125):
            depth -= 1
            if depth < 0:
                raise ProtocolError("invalid JSON structure")
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object,
                          parse_constant=lambda value: (_ for _ in ()).throw(ProtocolError("nonfinite JSON")))
    except RecursionError as error:
        raise ProtocolError("JSON nesting exceeds interpreter limit") from error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=pathlib.Path)
    parser.add_argument("--expected-manifest-sha256", help="Digest from a separately frozen input/target/corpus/scorer/normalization manifest")
    args = parser.parse_args()
    try:
        with args.input.open("rb") as handle:
            raw = handle.read(MAX_BYTES + 1)
        report = qualify(load_bytes(raw), expected_manifest_sha256=args.expected_manifest_sha256)
        report["input_sha256"] = hashlib.sha256(raw).hexdigest()
        report["helper_sha256"] = hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest()
    except (ValueError, TypeError, KeyError, UnicodeError, OSError, OverflowError, RecursionError) as error:
        print(json.dumps({"schema": "szl.paired-science-report/v1", "status": "INVALID_INPUT",
                          "production_authority": "NONE", "error": str(error)}, allow_nan=False))
        return 2
    print(json.dumps(report, sort_keys=True, indent=2, allow_nan=False))
    return 0 if report["status"] == "QUALIFIED_LOCAL_COMPARISON" else 1


if __name__ == "__main__":
    sys.exit(main())
