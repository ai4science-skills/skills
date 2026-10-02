"""Exercise the pinned vendored workbench offline; do not confuse this with app import."""
import hashlib
import json
import pathlib
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
        self.assertEqual(source["sha"], "b36160ea1d6b375670ea662cff6a2cc67cba0f40")
        self.assertEqual(source["ref"], "v0.4.0")
        registry = json.loads((ROOT / "registry.json").read_text())
        entry = next(p for p in registry["plugins"] if p["name"] == "szl-science-skills")
        present = {p.name for p in (PLUGIN / "skills").iterdir() if p.is_dir()}
        self.assertEqual(present, set(entry["skills"]))
        self.assertEqual(len(present), 23)
        self.assertTrue({"szl-typesafe-ai", "szl-governed-decision"}.isdisjoint(present))
        records = json.loads((SKILL / "references" / "implementations.json").read_text())
        self.assertEqual(len(records), 8)
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
                if name == "szl-paired-science":
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
                self.assertEqual(process.returncode, 0, process.stderr)
                self.assertIsInstance(json.loads(process.stdout), dict)


if __name__ == "__main__":
    unittest.main()
