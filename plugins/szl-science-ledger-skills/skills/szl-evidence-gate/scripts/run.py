#!/usr/bin/env python3
"""Usage: python scripts/run.py CLAIMS.json [--root DIR] [--output REPORT.json]
Exit 0 = gate ran (read "status"), 2 = ERROR/input problem."""
import argparse, json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from kernel import szl_evidence_gate  # noqa: E402

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("claims")
    ap.add_argument("--root", default=None, help="directory the evidence paths are relative to (default: the claims file's directory)")
    ap.add_argument("--output", default=None)
    a = ap.parse_args()
    path = pathlib.Path(a.claims)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "reason": f"cannot read claims: {exc}"})); return 2
    root = pathlib.Path(a.root) if a.root else path.parent
    report = szl_evidence_gate(root, doc)
    text = json.dumps(report, indent=2, sort_keys=False)
    if a.output:
        pathlib.Path(a.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 2 if report["status"] == "ERROR" else 0

if __name__ == "__main__":
    sys.exit(main())
