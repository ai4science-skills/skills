#!/usr/bin/env python3
"""Two phases, no pipeline execution.

  python scripts/run.py generate DATASET.json --out-dir variants/
      writes variants/plan.json and one variants/<mutation>.json per generated corruption
  python scripts/run.py score variants/plan.json OUTCOMES.json [--output report.json]
      OUTCOMES.json: {"baseline_flagged": false, "variants": {"scale_column": {"flagged": true, "check": "range-check"}, ...}}

Exit 0 = phase ran (read "status"/"coverage"), 2 = error."""
import argparse, json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from kernel import szl_generate_mutations, szl_score_mutations  # noqa: E402

def read(p):
    return json.loads(pathlib.Path(p).read_text(encoding="utf-8"))

def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate"); g.add_argument("dataset"); g.add_argument("--out-dir", required=True)
    s = sub.add_parser("score"); s.add_argument("plan"); s.add_argument("outcomes"); s.add_argument("--output", default=None)
    a = ap.parse_args()
    if a.cmd == "generate":
        plan = szl_generate_mutations(read(a.dataset))
        if plan["status"] == "ERROR":
            print(json.dumps(plan, indent=2)); return 2
        out = pathlib.Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)
        for v in plan["variants"]:
            if v["status"] == "GENERATED":
                (out / f"{v['mutation']}.json").write_text(json.dumps({"mutation": v["mutation"], "sha256": v["sha256"], "detail": v["detail"], "rows": v["rows"]}, indent=2) + "\n", encoding="utf-8")
        slim = dict(plan); slim["variants"] = [{k: val for k, val in v.items() if k != "rows"} for v in plan["variants"]]
        (out / "plan.json").write_text(json.dumps(slim, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": "GENERATED", "out_dir": str(out), "expected_detection": plan["expected_detection"],
                          "skipped": [v["mutation"] for v in plan["variants"] if v["status"] != "GENERATED"]}, indent=2))
        return 0
    report = szl_score_mutations(read(a.plan), read(a.outcomes))
    text = json.dumps(report, indent=2)
    if a.output:
        pathlib.Path(a.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 2 if report["status"] == "ERROR" else 0

if __name__ == "__main__":
    sys.exit(main())
