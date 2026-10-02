#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""An inspectable, bounded, file-based research workflow. No arbitrary-code inputs."""
import argparse
import copy
import datetime
import hashlib
import json
import os
import pathlib
import platform
import re
import runpy
import sys
import uuid
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
LIMIT = 8 * 1024 * 1024
TRIAGE_REVISION = "eb79a26a2934d5eaa667984720feacdcb90dcc28"
TRIAGE_REPO = "SZLHOLDINGS/szl-triage-qwen3.5-0.8b-lora-study5"
LIBRARIES = {name: runpy.run_path(str(HERE / "library" / (name + ".py")))
             for name in ("anatomy", "math_claim", "dataset", "model", "kernel_compare", "capsule", "paired", "calibration_reference", "outcome_preservation", "release_continuity")}


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def parse(raw):
    if len(raw) > LIMIT:
        raise ValueError("Input exceeds 8 MiB")
    return json.loads(raw, object_pairs_hook=unique_keys,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Nonfinite JSON")))


def read(path):
    with path.open("rb") as handle:
        return parse(handle.read(LIMIT + 1))


def write(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False, allow_nan=False)
        handle.write("\n")


def safe_path(root, relative):
    if not isinstance(relative, str) or not relative or "\\" in relative or ":" in relative:
        raise ValueError("Use canonical relative POSIX paths")
    parts = pathlib.PurePosixPath(relative)
    if parts.is_absolute() or ".." in parts.parts or str(parts) != relative:
        raise ValueError("Noncanonical or escaping path")
    path = root
    for part in parts.parts:
        path = path / part
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise ValueError("Symlinks and junctions excluded")
        if path.exists() and getattr(path.lstat(), "st_file_attributes", 0) & 0x400:
            raise ValueError("Windows reparse points excluded")
    if not path.resolve().is_relative_to(root):
        raise ValueError("Path escapes project")
    return path


def file_record(root, relative):
    return LIBRARIES["capsule"]["szl_capsule_file"](str(root), relative)


def read_rows(path):
    if path.suffix == ".csv":
        import csv
        if path.stat().st_size > LIMIT:
            raise ValueError("CSV exceeds 8 MiB")
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
                raise ValueError("Missing or duplicate CSV columns")
            rows = []
            for row in reader:
                if None in row or len(rows) >= 100000:
                    raise ValueError("Ragged or oversized CSV")
                rows.append(row)
            return rows
    with path.open("rb") as handle:
        raw = handle.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise ValueError("Rows exceed 8 MiB")
    rows = [parse(line) for line in raw.splitlines() if line.strip()] if path.suffix == ".jsonl" else parse(raw)
    if not isinstance(rows, list) or len(rows) > 100000 or any(not isinstance(row, dict) for row in rows):
        raise ValueError("Expected at most 100000 row objects")
    return rows


def project_row(row, columns):
    """Apply only an explicitly declared mapping of nested field paths."""
    if not isinstance(columns, dict) or not 1 <= len(columns) <= 100:
        raise ValueError("Declare a bounded columns mapping")
    result = {}
    for name, parts in columns.items():
        if not isinstance(name, str) or not name or not isinstance(parts, list) or not 1 <= len(parts) <= 10 or any(not isinstance(p, str) or not p for p in parts):
            raise ValueError("Column paths must contain explicit nonempty field names")
        value = row
        for part in parts:
            value = value.get(part) if isinstance(value, dict) else None
        result[name] = value
    return result


def validate_project(project, root):
    if not isinstance(project, dict) or project.get("schema") != "szl.science-project.v1":
        raise ValueError("Expected szl.science-project.v1")
    if project.get("input_scope") not in {"SYNTHETIC", "EXTERNAL", "MIXED"}:
        raise ValueError("Declare input scope")
    if not isinstance(project.get("question"), str) or not project["question"]:
        raise ValueError("Declare a research question")
    artifacts = project.get("artifacts")
    checks = project.get("checks")
    if not isinstance(artifacts, list) or not 1 <= len(artifacts) <= 1000 or not isinstance(checks, list) or not 1 <= len(checks) <= 100:
        raise ValueError("Declare bounded artifacts and checks")
    reserved = {"question", "conclusion", "lambda", "run", "implementation", "project-plan", "graph-template"}
    known, paths = set(reserved), set()
    for item in artifacts:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or item["id"] in known or not item["id"]:
            raise ValueError("Artifact ids must be nonempty and unique")
        safe_path(root, item.get("path"))
        if item["path"] in paths or item["path"] in {"project.json", "graph.json"} or item["path"].startswith("runs/"):
            raise ValueError("Duplicate or reserved artifact path")
        if item.get("kind") not in {"dataset", "model", "code", "kernel", "paper", "proof"} or not item.get("title"):
            raise ValueError("Declare artifact kind and title")
        paths.add(item["path"])
        known.add(item["id"])
    artifact_ids = {a["id"] for a in artifacts}
    kinds = {"dataset", "binary-model", "categorical-model", "math", "kernel", "calibration-benchmark", "paired", "outcome-preservation", "release-continuity"}
    for check in checks:
        if not isinstance(check, dict) or not isinstance(check.get("id"), str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", check["id"]) or check["id"] in known:
            raise ValueError("Check ids must be unique slugs")
        dependencies = check.get("depends_on")
        if check.get("type") not in kinds or check.get("input") not in artifact_ids or not isinstance(dependencies, list) or not dependencies or len(set(dependencies)) != len(dependencies) or any(d not in known - reserved for d in dependencies):
            raise ValueError("Invalid check input, type or ordered dependencies")
        if check["input"] not in dependencies:
            raise ValueError("Check input must be a dependency")
        known.add(check["id"])
    return {a["id"]: a for a in artifacts}


def implementations():
    paths = [HERE / "workbench.py"] + sorted((HERE / "library").glob("*.py"))
    records = [{"path": p.relative_to(HERE.parent).as_posix(), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths]
    return {"files": records, "sha256": LIBRARIES["anatomy"]["szl_anatomy_digest"](records), "signed": False}


def latest_run(root):
    base = safe_path(root, "runs")
    completed = []
    if base.exists():
        for directory in base.iterdir():
            if not re.fullmatch(r"[0-9]{8}T[0-9]{12}Z-[0-9a-f]{12}", directory.name):
                continue
            report = safe_path(root, "runs/" + directory.name + "/report.json")
            if report.is_file():
                value = read(report)
                if value.get("schema") == "szl.science-run.v1" and value.get("completed") is True:
                    if value.get("run_id") != directory.name or value.get("created_at") != directory.name.split("-")[0]:
                        raise ValueError("Run timestamp/name mismatch")
                    completed.append((value["created_at"], directory.name, value))
    if not completed:
        return None
    return max(completed, key=lambda item: (item[0], item[1]))


def assess_snapshot(root, run):
    directory = safe_path(root, "runs/" + run[1])
    graph = read(safe_path(root, "runs/" + run[1] + "/graph.json"))
    observation, unavailable = {}, []
    for node in graph["nodes"]:
        if node.get("artifact_path"):
            try:
                observation[node["id"]] = file_record(root, node["artifact_path"])["sha256"]
            except (OSError, ValueError):
                unavailable.append(node["id"])
                node["needs_recheck"] = True
    observation["implementation"] = implementations()["sha256"]
    report = LIBRARIES["anatomy"]["szl_anatomy_assess"](graph, observation)
    report["unavailable_sources"] = unavailable
    report["capsule"] = LIBRARIES["capsule"]["szl_verify_capsule"](str(root), read(safe_path(root, "runs/" + run[1] + "/capsule.json")))
    report["completion_record_binding"] = "MATCH" if run[2] == read(safe_path(root, "runs/" + run[1] + "/summary.json")) else "MISMATCH"
    return report


def benchmark(payload):
    probabilities, labels = payload["probabilities"], payload["labels"]
    bins = payload.get("n_bins", 10)
    model = LIBRARIES["model"]
    reference = LIBRARIES["calibration_reference"]
    names = ["brier", "log_loss", "ece", "mce", "auroc"]
    def baseline():
        return [reference["brier_score"](probabilities, labels), reference["log_loss"](probabilities, labels),
                reference["expected_calibration_error"](probabilities, labels, bins),
                reference["maximum_calibration_error"](probabilities, labels, bins), reference["auroc"](probabilities, labels)]
    def candidate():
        value = model["szl_binary_metrics"](probabilities, labels, bins)
        return [value[k] for k in names]
    context = {"hardware": platform.machine() + " / " + platform.system() + " CPU",
               "dtype": "Python float64", "input_sha256": LIBRARIES["anatomy"]["szl_anatomy_digest"](payload),
               "threads": 1, "warmup": 3, "synchronized": True, "measurement_method": "perf_counter, synchronous CPU"}
    record = {"reference_output": baseline(), "candidate_output": candidate(),
              "atol": payload.get("atol", 1e-12), "rtol": payload.get("rtol", 1e-9),
              "reference_context": context, "candidate_context": context}
    # Check correctness before executing timing loops.
    first = LIBRARIES["kernel_compare"]["szl_compare_kernel_runs"](record)
    if first["mismatch_count"]:
        return first
    timer = LIBRARIES["kernel_compare"]["szl_time_callable"]
    record["reference_seconds"] = timer(baseline)["seconds"]
    record["candidate_seconds"] = timer(candidate)["seconds"]
    result = LIBRARIES["kernel_compare"]["szl_compare_kernel_runs"](record)
    result.update({"measurement_executed_locally": True, "measurement_record": record,
                   "reference_revision": "b2e317877abed98e70f9cf6730944a797837faf1",
                   "compared_metrics": names,
                   "scope": "Five reference metric calls versus the unified helper (also computes accuracy/confusion); this CPU/input only"})
    return result


def execute(check, artifacts, root):
    payload = read(safe_path(root, artifacts[check["input"]]["path"]))
    kind = check["type"]
    if kind == "dataset":
        payload = copy.deepcopy(payload)
        if "rows_files" in payload:
            rows = []
            for selected in payload.pop("rows_files"):
                if selected.get("artifact") not in check["depends_on"]:
                    raise ValueError("Rows file must be an explicit dependency")
                for row in read_rows(safe_path(root, artifacts[selected["artifact"]]["path"])):
                    if "columns" in selected:
                        row = project_row(row, selected["columns"])
                    rows.append(dict(row, **{payload.get("split_column", "split"): selected["split"]}))
            payload["rows"] = rows
        return LIBRARIES["dataset"]["szl_audit_dataset"](**payload)
    if kind == "binary-model":
        return LIBRARIES["model"]["szl_evaluate_predictions"](**payload)
    if kind == "categorical-model":
        for selected in (payload["predictions"], payload["held"]):
            if selected not in check["depends_on"]:
                raise ValueError("Prediction and held-out files must be explicit dependencies")
        records = read_rows(safe_path(root, artifacts[payload["predictions"]]["path"]))
        held = read_rows(safe_path(root, artifacts[payload["held"]]["path"]))
        return LIBRARIES["model"]["szl_evaluate_categories"](records, held, payload["label_set"], payload.get("metadata"))
    if kind == "math":
        payload = copy.deepcopy(payload)
        compute = payload.pop("compute", None)
        if compute is not None:
            if compute != "weighted_geomean":
                raise ValueError("Only the reviewed weighted_geomean formula can be executed")
            for case in payload["cases"]:
                case["lhs"] = LIBRARIES["math_claim"]["szl_weighted_geomean"](case["inputs"])
        result = LIBRARIES["math_claim"]["szl_check_math_cases"](**payload)
        result["lhs_execution"] = "SZL_WEIGHTED_GEOMEAN" if compute else "SUPPLIED_VALUES_ONLY"
        return result
    if kind == "kernel":
        return LIBRARIES["kernel_compare"]["szl_compare_kernel_runs"](payload)
    if kind == "calibration-benchmark":
        return benchmark(payload)
    if kind == "paired":
        return LIBRARIES["paired"]["qualify"](payload)
    if kind == "outcome-preservation":
        return LIBRARIES["outcome_preservation"]["szl_outcome_preservation"](payload)
    if kind == "release-continuity":
        return LIBRARIES["release_continuity"]["szl_release_continuity"](payload)
    raise ValueError("Unknown check type")


def has_findings(report):
    return (bool(report.get("issues")) or report.get("status") in {"NUMERICAL_MISMATCH", "NUMERICAL_COUNTEREXAMPLE", "REJECTED_LOCAL_COMPARISON", "REGRESSION_OR_GAP", "GAP_OR_CONFLICT"}
            or report.get("counterexample_count", 0) > 0 or report.get("invalid_outputs", 0) > 0)


def run_project(root):
    control_records = {relative: file_record(root, relative) for relative in ("project.json", "graph.json")}
    project = read(safe_path(root, "project.json"))
    artifacts = validate_project(project, root)
    lock = safe_path(root, ".science-lock")
    with lock.open("x", encoding="utf-8") as handle:
        handle.write("pid=" + str(os.getpid()) + "\n")
    directory = None
    try:
        prior = latest_run(root)
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        run_id = stamp + "-" + uuid.uuid4().hex[:12]
        directory = safe_path(root, "runs/" + run_id)
        directory.parent.mkdir(exist_ok=True)
        directory.mkdir()
        prefix = "runs/" + run_id + "/"
        template = read(safe_path(root, "graph.json"))
        write(directory / "template.json", template)
        if prior:
            write(directory / "prior-assessment.json", assess_snapshot(root, prior))
            graph = read(safe_path(root, "runs/" + prior[1] + "/graph.json"))
            previous_template = read(safe_path(root, "runs/" + prior[1] + "/template.json"))
            previous_nodes = {n["id"]: n for n in previous_template["nodes"]}
            old_ids = {n["id"] for n in graph["nodes"] if not n.get("generated")}
            if not old_ids <= {n["id"] for n in template["nodes"]}:
                raise ValueError("Retain prior user nodes; record RETRACTED instead of deleting history")
            user_replacements = [n for n in template["nodes"] if not n.get("generated") and n != previous_nodes.get(n["id"])]
        else:
            graph = {"schema": "szl.research-anatomy.v1", "nodes": []}
            user_replacements = [n for n in template["nodes"] if not n.get("generated")]
        code = implementations()
        write(directory / "implementations.json", code)
        records = [file_record(root, a["path"]) for a in artifacts.values()]
        before = {r["path"]: r for r in records}
        before.update(control_records)
        replacements = [{"id": a["id"], "kind": a["kind"], "title": a["title"],
                         "artifact_path": a["path"], "sha256": before[a["path"]]["sha256"], "generated": True}
                        for a in artifacts.values()]
        replacements += [{"id": "implementation", "kind": "code", "title": "Observed workbench implementations", "sha256": code["sha256"], "generated": True},
                         {"id": "project-plan", "kind": "code", "title": "Declared project plan", "artifact_path": "project.json", "sha256": before["project.json"]["sha256"], "generated": True},
                         {"id": "graph-template", "kind": "code", "title": "Declared research graph", "artifact_path": "graph.json", "sha256": before["graph.json"]["sha256"], "generated": True}]
        reports, findings = {}, []
        for check in project["checks"]:
            result = execute(check, artifacts, root)
            write(directory / (check["id"] + ".json"), result)
            relative = prefix + check["id"] + ".json"
            reports[check["id"]] = {"type": check["type"], "path": relative, "sha256": file_record(root, relative)["sha256"], "findings": has_findings(result)}
            if reports[check["id"]]["findings"]:
                findings.append(check["id"])
            replacements.append({"id": check["id"], "kind": "run", "title": check["type"] + " check",
                                 "depends_on": check["depends_on"] + ["implementation", "project-plan", "graph-template"],
                                 "sha256": reports[check["id"]]["sha256"], "artifact_path": relative, "generated": True,
                                 "needs_recheck": False, "claim_state": "COMPUTED_ON_SELECTED_INPUTS"})
        # Do not bind a result to bytes that changed after its read.
        if any(file_record(root, relative) != record for relative, record in before.items()) or implementations() != code:
            raise ValueError("Input or implementation changed during execution")
        replacements.append({"id": "run", "kind": "run", "title": "Completed selected checks", "generated": True,
                             "depends_on": list(reports), "sha256": LIBRARIES["anatomy"]["szl_anatomy_digest"](reports), "needs_recheck": False})
        graph = LIBRARIES["anatomy"]["szl_anatomy_update"](graph, user_replacements + replacements)
        write(directory / "graph.json", graph)
        observed = {n["id"]: n["sha256"] for n in graph["nodes"] if n.get("generated") and n.get("sha256")}
        anatomy = LIBRARIES["anatomy"]["szl_anatomy_assess"](graph, observed)
        write(directory / "anatomy.json", anatomy)
        report = {"schema": "szl.science-run.v1", "run_id": run_id, "created_at": stamp,
                  "completed": True, "status": "COMPLETED_WITH_FINDINGS" if findings else "COMPLETED",
                  "input_scope": project["input_scope"], "checks": reports, "findings": findings,
                  "scientific_truth_verified": False, "signed": False, "lambda": "Conjecture 1 (OPEN)"}
        # Write completion marker only after the retained capsule has been made.
        write(directory / "summary.json", report)
        files = ["project.json", "graph.json"] + [a["path"] for a in artifacts.values()]
        files += [p.relative_to(root).as_posix() for p in sorted(directory.iterdir()) if p.is_file()]
        capsule = LIBRARIES["capsule"]["szl_make_capsule"](str(root), files, {"run_id": run_id, "input_scope": project["input_scope"]})
        write(directory / "capsule.json", capsule)
        write(directory / "report.json", report)
        return report
    except Exception as error:
        if directory is not None:
            write(directory / "error.json", {"status": "ERROR", "completed": False, "error_type": type(error).__name__, "message": str(error), "scientific_truth_verified": False})
        raise
    finally:
        lock.unlink()


def start_project(root, files, checks, input_scope):
    root.mkdir(parents=True, exist_ok=False)
    (root / "inputs").mkdir()
    artifacts = []
    for key, value in files.items():
        relative = "inputs/" + key + ".json"
        write(root / relative, value)
        artifacts.append({"id": key, "kind": "dataset", "title": key, "path": relative})
    project = {"schema": "szl.science-project.v1", "question": "What evidence supports this selected scientific workflow?",
               "input_scope": input_scope, "artifacts": artifacts, "checks": checks}
    write(root / "project.json", project)
    write(root / "graph.json", {"schema": "szl.research-anatomy.v1", "nodes": [
        {"id": "question", "kind": "question", "title": project["question"]},
        {"id": "lambda", "kind": "claim", "title": "Lambda uniqueness", "claim_state": "Conjecture 1 (OPEN)"},
        {"id": "run", "kind": "run", "title": "No checks executed yet", "generated": True, "claim_state": "NOT_EXECUTED"},
        {"id": "conclusion", "kind": "claim", "title": "Research conclusions require scientist review", "depends_on": ["run"], "claim_state": "UNKNOWN"}]})
    return project


def initialize(root):
    files = read(HERE.parent / "assets" / "demo.json")
    checks = [{"id": "dataset-check", "type": "dataset", "input": "dataset", "depends_on": ["dataset"]},
              {"id": "model-check", "type": "binary-model", "input": "predictions", "depends_on": ["predictions", "dataset-check"]},
              {"id": "math-check", "type": "math", "input": "math", "depends_on": ["math"]},
              {"id": "kernel-check", "type": "calibration-benchmark", "input": "predictions", "depends_on": ["predictions", "model-check"]},
              {"id": "paired-check", "type": "paired", "input": "paired", "depends_on": ["paired", "kernel-check"]}]
    return start_project(root, files, checks, "SYNTHETIC")


def fetch_triage(root):
    checks = [{"id": "dataset-check", "type": "dataset", "input": "dataset", "depends_on": ["dataset", "train", "held"]},
              {"id": "baseline-check", "type": "categorical-model", "input": "baseline-plan", "depends_on": ["baseline-plan", "base", "held", "dataset-check"]},
              {"id": "seed-011-check", "type": "categorical-model", "input": "seed-plan", "depends_on": ["seed-plan", "seed", "held", "dataset-check"]}]
    project = start_project(root, {}, checks, "SYNTHETIC")
    urls = {"train": "evidence/frozen/train.jsonl", "held": "evidence/frozen/held.jsonl",
            "base": "evidence/evaluation/predictions-base.jsonl", "seed": "evidence/evaluation/predictions-seed-011.jsonl"}
    receipts = []
    for key, relative in urls.items():
        url = "https://huggingface.co/" + TRIAGE_REPO + "/resolve/" + TRIAGE_REVISION + "/" + relative
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "szl-science-workbench"}), timeout=45) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError("Pinned artifact exceeds 2 MiB")
        for line in raw.splitlines():
            if line.strip():
                parse(line)
        path = "inputs/" + key + ".jsonl"
        with (root / path).open("xb") as handle:
            handle.write(raw)
        receipts.append({"url": url, "revision": TRIAGE_REVISION, "path": path, "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw), "signed": False})
        project["artifacts"].append({"id": key, "kind": "dataset", "title": relative, "path": path})
    labels = sorted({r["target"]["label"] for r in read_rows(root / "inputs/held.jsonl")})
    metadata = {"source_revision": TRIAGE_REVISION, "source": TRIAGE_REPO, "license": "apache-2.0", "input_scope": "SYNTHETIC", "model_outputs": "SAVED_STUDY_DECLARATIONS"}
    files = {"dataset": {"rows_files": [
                         {"artifact": "train", "split": "train", "columns": {"prompt": ["row", "input"], "family": ["family"], "row_id": ["row_id"]}},
                         {"artifact": "held", "split": "held", "columns": {"prompt": ["prompt"], "family": ["family"], "row_id": ["row_id"]}}],
                         "feature_columns": ["prompt"], "group_column": "family", "metadata": metadata},
             "baseline-plan": {"predictions": "base", "held": "held", "label_set": labels, "metadata": metadata},
             "seed-plan": {"predictions": "seed", "held": "held", "label_set": labels, "metadata": metadata}}
    for key, value in files.items():
        path = "inputs/" + key + ".json"
        write(root / path, value)
        project["artifacts"].append({"id": key, "kind": "dataset", "title": key, "path": path})
    # The initial incomplete plan is not retained as an apparently ready project.
    (root / "project.json").unlink()
    write(root / "project.json", project)
    write(root / "download-receipts.json", {"schema": "szl.public-downloads.v1", "files": receipts, "signed": False, "authenticity_verified": False})
    return {"status": "FETCHED_PINNED_PUBLIC_STUDY", "revision": TRIAGE_REVISION, "files": len(receipts), "model_loaded": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["init", "run", "check", "fetch-triage"])
    parser.add_argument("project", type=pathlib.Path)
    args = parser.parse_args()
    try:
        root = args.project.resolve()
        if args.command == "init":
            initialize(root)
            result = {"status": "INITIALIZED_SYNTHETIC_PROJECT"}
        elif args.command == "fetch-triage":
            result = fetch_triage(root)
        elif args.command == "run":
            result = run_project(root)
        else:
            run = latest_run(root)
            if run is None:
                raise ValueError("No completed retained run")
            result = assess_snapshot(root, run)
            print(json.dumps(result, indent=2, allow_nan=False))
            return 1 if result["changed_sources"] or result["unavailable_sources"] or result["capsule"]["integrity"] != "MATCH" or result["completion_record_binding"] != "MATCH" else 0
        print(json.dumps(result, indent=2, allow_nan=False))
        return 1 if result.get("findings") else 0
    except (OSError, ValueError, TypeError, KeyError, RecursionError, OverflowError) as error:
        print(json.dumps({"status": "ERROR", "completed": False, "error_type": type(error).__name__, "message": str(error)}, allow_nan=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
