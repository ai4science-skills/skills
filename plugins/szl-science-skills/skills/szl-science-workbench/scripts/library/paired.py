#!/usr/bin/env python3
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
    if not math.isfinite(value) or value < 0 or (positive and value <= 0):
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


def qualify(plan):
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
    return {"schema": "szl.paired-science-report/v1",
            "status": "REJECTED_LOCAL_COMPARISON" if blockers else "QUALIFIED_LOCAL_COMPARISON",
            "production_authority": "NONE", "input_scope": plan["input_scope"],
            "declarations_independently_verified": False,
            "declared_source_revision": plan["source_revision"],
            "declared_dataset_sha256": plan["dataset_sha256"], "declared_plan_sha256": plan["plan_sha256"],
            "raw_cross_task_average": None, "tasks": results, "blockers": blockers}


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
    return json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object,
                      parse_constant=lambda value: (_ for _ in ()).throw(ProtocolError("nonfinite JSON")))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=pathlib.Path)
    args = parser.parse_args()
    try:
        with args.input.open("rb") as handle:
            raw = handle.read(MAX_BYTES + 1)
        report = qualify(load_bytes(raw))
        report["input_sha256"] = hashlib.sha256(raw).hexdigest()
        report["helper_sha256"] = hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest()
    except (ValueError, UnicodeError, OSError, OverflowError) as error:
        print(json.dumps({"schema": "szl.paired-science-report/v1", "status": "INVALID_INPUT",
                          "production_authority": "NONE", "error": str(error)}, allow_nan=False))
        return 2
    print(json.dumps(report, sort_keys=True, indent=2, allow_nan=False))
    return 0 if report["status"] == "QUALIFIED_LOCAL_COMPARISON" else 1


if __name__ == "__main__":
    sys.exit(main())
