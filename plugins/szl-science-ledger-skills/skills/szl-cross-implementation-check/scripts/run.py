#!/usr/bin/env python3
"""Usage: python scripts/run.py COMPARISON.json [--output REPORT.json]
Exit 0 = comparison ran (read "status"), 2 = ERROR."""
import argparse, json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from kernel import szl_cross_implementation_check  # noqa: E402

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("comparison")
    ap.add_argument("--output", default=None)
    a = ap.parse_args()
    try:
        doc = json.loads(pathlib.Path(a.comparison).read_text(encoding="utf-8"))
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "reason": f"cannot read comparison: {exc}"})); return 2
    report = szl_cross_implementation_check(doc)
    text = json.dumps(report, indent=2)
    if a.output:
        pathlib.Path(a.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 2 if report["status"] == "ERROR" else 0

if __name__ == "__main__":
    sys.exit(main())
