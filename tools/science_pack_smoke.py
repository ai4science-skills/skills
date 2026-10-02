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
        self.assertEqual(source["sha"], "5c51a023fccb0630298fdaa9f5dc955a716bb6dc")
        self.assertEqual(source["ref"], source["sha"])
        registry = json.loads((ROOT / "registry.json").read_text())
        entry = next(p for p in registry["plugins"] if p["name"] == "szl-science-skills")
        present = {p.name for p in (PLUGIN / "skills").iterdir() if p.is_dir()}
        self.assertEqual(present, set(entry["skills"]))
        self.assertEqual(len(present), 26)
        self.assertTrue({"szl-typesafe-ai", "szl-governed-decision"}.isdisjoint(present))
        records = json.loads((SKILL / "references" / "implementations.json").read_text())
        self.assertEqual(len(records), 10)
        for record in records:
            raw = (SKILL / record["path"]).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), record["sha256"])
            if record["source"].startswith("skills/"):
                self.assertEqual(raw, (PLUGIN / record["source"]).read_bytes())

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
        entry = next(p for p in registry["plugins"] if p["name"] == "szl-science-skills")
        for name in entry["skills"]:
            if name == "szl-science-workbench":
                continue  # Its run/check/invalidation behavior is exercised above.
            with self.subTest(skill=name):
                directory = PLUGIN / "skills" / name
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
            raw = (PLUGIN / "skills" / ("szl-" + name) / "assets" / "example.json").read_bytes()
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
