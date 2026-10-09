"""Exercise the pinned vendored workbench offline; do not confuse this with app import."""
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "szl-science-skills"
SKILL = PLUGIN / "skills" / "szl-science-workbench"


def science_directory(name):
    registry = json.loads((ROOT / "registry.json").read_text(encoding="utf-8"))
    owners = [entry["name"] for entry in registry["plugins"] if name in entry["skills"]]
    if len(owners) != 1:
        raise ValueError("Expected one explicitly selected skill owner")
    return ROOT / "plugins" / owners[0] / "skills" / name


class VendoredScienceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = pathlib.Path(self.temp.name) / "project"

    def tearDown(self):
        self.temp.cleanup()

    def execute(self, command, expected=0):
        result = subprocess.run([sys.executable, "-B", str(SKILL / "scripts" / "workbench.py"), command, str(self.project)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, expected, result.stderr)
        return json.loads(result.stdout)

    def test_immutable_pin_and_generated_helpers_match(self):
        source = json.loads((PLUGIN / "SOURCE.json").read_text())
        self.assertEqual(source["sha"], "baf0160e1acb2bee0de3c2324211d8d95e1b68b1")
        self.assertEqual(source["ref"], source["sha"])
        registry = json.loads((ROOT / "registry.json").read_text())
        entry = next(p for p in registry["plugins"] if p["name"] == "szl-science-skills")
        present = {p.name for p in (PLUGIN / "skills").iterdir() if p.is_dir()}
        self.assertEqual(present, set(entry["skills"]))
        self.assertEqual(len(present), 8)
        self.assertTrue({"szl-typesafe-ai", "szl-governed-decision"}.isdisjoint(present))
        records = json.loads((SKILL / "references" / "implementations.json").read_text())
        self.assertEqual(len(records), 10)
        for record in records:
            raw = (SKILL / record["path"]).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), record["sha256"])
            if record["source"].startswith("skills/"):
                self.assertEqual(raw, (science_directory(record["source"].split("/")[1]) / "/".join(record["source"].split("/")[2:])).read_bytes())

    def test_retained_capsule_and_expected_negative_results(self):
        self.execute("init")
        report = self.execute("run", 1)
        self.assertEqual(report["status"], "COMPLETED_WITH_FINDINGS")
        self.assertEqual(set(report["findings"]), {"dataset-check", "math-check", "paired-check"})
        self.assertFalse(report["scientific_truth_verified"])
        check = self.execute("check")
        self.assertEqual(check["capsule"]["integrity"], "MATCH")
        self.assertEqual(check["completion_record_binding"], "MATCH")
        self.assertEqual(check["changed_sources"], [])

    def test_changed_prediction_invalidates_dependent_conclusions(self):
        self.execute("init")
        self.execute("run", 1)
        path = self.project / "inputs" / "predictions.json"
        payload = json.loads(path.read_text())
        payload["probabilities"][0] = 0.3
        path.write_text(json.dumps(payload))
        report = self.execute("check", 1)
        self.assertEqual(report["changed_sources"], ["predictions"])
        self.assertTrue({"model-check", "kernel-check", "paired-check", "run", "conclusion"} <= set(report["recheck"]))
        self.assertEqual(report["capsule"]["integrity"], "MISMATCH")

    def test_standalone_science_clis_run_with_only_vendored_resources(self):
        registry = json.loads((ROOT / "registry.json").read_text())
        entries = [p for p in registry["plugins"] if p["repo"] == "szl-holdings/szl-skills" and p["name"] != "szl-evidence-skills"]
        names = [name for entry in entries for name in entry["skills"]]
        self.assertEqual(len(names), 37)
        self.assertEqual(len(names), len(set(names)))
        post_rc3 = "b8e259c43f01190a306657c2fe2cde61abb5e801"
        post_rc3_plugins = {"szl-science-replay-skills", "szl-science-rare-disease-replay-skills"}
        for entry in entries:
            expected = post_rc3 if entry["name"] in post_rc3_plugins else "baf0160e1acb2bee0de3c2324211d8d95e1b68b1"
            self.assertEqual(entry["sha"], expected, entry["name"])
        for name in names:
            if name == "szl-science-workbench":
                continue  # Its run/check/invalidation behavior is exercised above.
            with self.subTest(skill=name):
                directory = science_directory(name)
                cli = directory / "scripts" / "run.py"
                fixture = directory / "assets" / "example.json"
                arguments = [str(fixture)]
                if name == "szl-experiment-replay":
                    replay_root = pathlib.Path(self.temp.name) / "replay"
                    shutil.copytree(directory, replay_root)
                    runner = replay_root / "scripts" / "run.py"
                    for command, arguments, expected_status in [
                        ("prepare", ["assets/declaration.json", "--output", "pin.json"], "PINNED"),
                        ("replay", ["pin.json", "--receipt", "receipt.json"], "MATCH"),
                    ]:
                        process = subprocess.run([sys.executable, "-B", str(runner), command, *arguments,
                                                  "--root", str(replay_root)],
                                                 capture_output=True, text=True, timeout=30)
                        self.assertEqual(process.returncode, 0, process.stderr)
                        self.assertEqual(json.loads(process.stdout)["status"], expected_status)
                    continue
                elif name == "szl-measurement-harmonizer":
                    harmonizer_root = pathlib.Path(self.temp.name) / "harmonizer"
                    shutil.copytree(directory, harmonizer_root)
                    process = subprocess.run(
                        [sys.executable, "-B", str(harmonizer_root / "scripts" / "run.py"),
                         str(harmonizer_root / "assets" / "example.json"),
                         "--root", str(harmonizer_root / "assets"),
                         "--output", str(pathlib.Path(self.temp.name) / "harmonized-report.json")],
                        capture_output=True, text=True, timeout=30)
                    self.assertEqual(process.returncode, 0, process.stderr + process.stdout)
                    report = json.loads(process.stdout)
                    self.assertEqual(report["status"], "HARMONIZED")
                    self.assertEqual(report["rows"], 4)
                    continue
                elif name == "szl-rare-disease-evidence-replay":
                    rare_root = pathlib.Path(self.temp.name) / "rare-replay"
                    shutil.copytree(directory, rare_root)
                    process = subprocess.run(
                        [sys.executable, "-I", "-B", str(rare_root / "scripts" / "replay.py"),
                         "--root", str(rare_root), "--manifest", "assets/manifest.json",
                         "--output", "replay-report.json"],
                        capture_output=True, text=True, timeout=30)
                    self.assertEqual(process.returncode, 0, process.stderr)
                    report = json.loads(process.stdout)
                    self.assertEqual(report["status"], "DECLARED_ONLY")
                    self.assertEqual(report["readiness"], "HOLD")
                    continue
                elif name == "szl-figure-data-contract":
                    figure_root = pathlib.Path(self.temp.name) / "figure"
                    shutil.copytree(directory, figure_root)
                    runner = figure_root / "scripts" / "run.py"
                    for command, arguments in [
                        ("render", ["assets/spec.json", "--output", "figure-run"]),
                        ("verify", ["figure-run"]),
                    ]:
                        process = subprocess.run([sys.executable, "-I", "-B", str(runner), command,
                                                  *arguments, "--root", str(figure_root)],
                                                 capture_output=True, text=True, timeout=30)
                        self.assertEqual(process.returncode, 0, process.stderr)
                        self.assertEqual(json.loads(process.stdout)["status"], "MATCH")
                    continue
                elif name == "szl-uncertainty-lineage":
                    cli = directory / "scripts" / "run.py"
                elif name == "szl-paper-evidence-audit":
                    pdf = pathlib.Path(self.temp.name) / "paper-fixture.pdf"
                    document = pathlib.Path(self.temp.name) / "paper-document.json"
                    claims = pathlib.Path(self.temp.name) / "paper-claims.json"
                    pdf.write_bytes(b"%PDF-1.7\nsynthetic evidence locator fixture\n")
                    document.write_text(json.dumps({"tables": [{"prov": [{"page_no": 1,
                        "bbox": {"l": 0, "t": 10, "r": 20, "b": 0, "coord_origin": "BOTTOMLEFT"}}],
                        "data": {"table_cells": [{"text": "7 mg/L"}]}}]}), encoding="utf-8")
                    claims.write_text(json.dumps({"schema": "szl.paper-evidence-claims.v1",
                        "pdf_sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
                        "document_json_sha256": hashlib.sha256(document.read_bytes()).hexdigest(),
                        "extraction": {"tool": "synthetic", "version": "test", "pipeline": "test", "ocr_engine": "none"},
                        "claims": [{"id": "dose", "ref": "#/tables/0", "quote": "7 mg/L"}]}), encoding="utf-8")
                    command = [sys.executable, "-B", str(directory / "scripts" / "audit.py"),
                               "--pdf", str(pdf), "--document-json", str(document), "--claims", str(claims)]
                    process = subprocess.run(command, capture_output=True, text=True, timeout=30)
                    self.assertEqual(process.returncode, 0, process.stderr)
                    self.assertEqual(json.loads(process.stdout)["status"], "REVIEW_REQUIRED")
                    pdf.write_bytes(b"%PDF-1.7\nchanged synthetic evidence\n")
                    process = subprocess.run(command, capture_output=True, text=True, timeout=30)
                    self.assertEqual(process.returncode, 2, process.stderr)
                    self.assertEqual(json.loads(process.stdout)["status"], "UNRESOLVED")
                    continue
                elif name == "szl-skill-update-review":
                    example = directory / "assets" / "example"
                    output = pathlib.Path(self.temp.name) / "update-review"
                    arguments = [str(example / "old-inventory.json"), str(example / "new-inventory.json"),
                                 "--old-root", str(example / "old-package"), "--new-root", str(example / "new-package"),
                                 "--lock", str(example / "retained-lock.json"), "--output-dir", str(output)]
                    process = subprocess.run([sys.executable, "-B", str(cli), *arguments],
                                             capture_output=True, text=True, timeout=30)
                    self.assertEqual(process.returncode, 0, process.stderr)
                    self.assertEqual(json.loads((output / "UPDATE_REVIEW.json").read_text())["status"], "CHANGES_REVIEW_REQUIRED")
                    continue
                elif name == "szl-clustered-replication":
                    lock = json.loads((directory / "assets" / "fixture-lock.json").read_text())
                    arguments += ["--expected-plan-sha256", lock["plan_sha256"]]
                elif name == "szl-multiplicity-audit":
                    arguments = [str(directory / "assets" / "plan.json"), str(directory / "assets" / "results.json")]
                elif name == "szl-paired-science":
                    cli = directory / "scripts" / "qualify.py"
                    lock = json.loads((directory / "assets" / "fixture-lock.json").read_text())
                    arguments = [str(directory / "assets" / "example-v2.json"),
                                 "--expected-manifest-sha256", lock["expected_manifest_sha256"]]
                elif name == "szl-reproducibility-capsule":
                    arguments += ["--root", str(directory)]
                elif name == "szl-analysis-mutation-test":
                    arguments = ["generate", str(fixture), "--out-dir", str(self.project / "variants")]
                elif name == "szl-session-receipt":
                    arguments = ["record", str(fixture), "--root", str(directory / "assets" / "project")]
                elif name == "szl-refutation-ledger":
                    arguments = ["status", str(fixture)]
                elif name == "szl-repo-pin":
                    arguments = ["show", str(fixture)]
                elif name == "szl-reviewer-pack":
                    arguments = [str(directory / "assets" / "project"), "--json", str(self.project / "review.json"),
                                 "--output", str(self.project / "REVIEW.md")]
                    self.project.mkdir(parents=True, exist_ok=True)
                process = subprocess.run([sys.executable, "-B", str(cli), *arguments], cwd=directory,
                                         capture_output=True, text=True, timeout=30)
                result = json.loads(process.stdout)
                if name in {"szl-outcome-preservation", "szl-release-continuity"}:
                    self.assertEqual(process.returncode, 1, process.stderr)
                    self.assertIn(result["status"], {"REGRESSION_OR_GAP", "GAP_OR_CONFLICT"})
                else:
                    self.assertEqual(process.returncode, 0, process.stderr)
                self.assertIsInstance(result, dict)

    def test_new_checks_join_retained_workbench_and_invalidation(self):
        self.execute("init")
        path = self.project / "project.json"
        project = json.loads(path.read_text())
        for name in ("outcome-preservation", "release-continuity"):
            relative = "inputs/" + name + ".json"
            raw = (science_directory("szl-" + name) / "assets" / "example.json").read_bytes()
            (self.project / relative).write_bytes(raw)
            project["artifacts"].append({"id": name, "kind": "code", "title": name, "path": relative})
            project["checks"].append({"id": name + "-check", "type": name, "input": name, "depends_on": [name]})
        path.write_text(json.dumps(project))
        report = self.execute("run", 1)
        self.assertTrue({"outcome-preservation-check", "release-continuity-check"} <= set(report["findings"]))
        self.assertEqual(self.execute("check")["capsule"]["integrity"], "MATCH")
        changed = self.project / "inputs/outcome-preservation.json"
        doc = json.loads(changed.read_text()); doc["candidate_revision"] = "3" * 40
        changed.write_text(json.dumps(doc))
        observed = self.execute("check", 1)
        self.assertEqual(observed["changed_sources"], ["outcome-preservation"])
        self.assertTrue({"outcome-preservation-check", "run", "conclusion"} <= set(observed["recheck"]))


if __name__ == "__main__":
    unittest.main()
