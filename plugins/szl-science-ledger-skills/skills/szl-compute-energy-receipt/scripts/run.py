#!/usr/bin/env python3
"""Usage: python scripts/run.py RUN.json [--output RECEIPT.json]
Exit 0 = receipt written (read "status": MEASURED / REPORTED / UNAVAILABLE), 2 = ERROR."""
import argparse, json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from kernel import szl_energy_receipt  # noqa: E402

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--output", default=None)
    a = ap.parse_args()
    try:
        doc = json.loads(pathlib.Path(a.run).read_text(encoding="utf-8"))
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "reason": f"cannot read run: {exc}"})); return 2
    receipt = szl_energy_receipt(doc)
    text = json.dumps(receipt, indent=2)
    if a.output:
        pathlib.Path(a.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 2 if receipt["status"] == "ERROR" else 0

if __name__ == "__main__":
    sys.exit(main())
