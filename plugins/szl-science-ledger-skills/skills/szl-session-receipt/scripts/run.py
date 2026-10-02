#!/usr/bin/env python3
"""Usage:
  python scripts/run.py record MANIFEST.json --root PROJECT_DIR [--output receipt.json] [--sign-key KEY.pem]
  python scripts/run.py verify receipt.json --root PROJECT_DIR
  python scripts/run.py methods receipt.json          (prints the Methods paragraph only)

record/verify exit 0 = ran (read "status"), 2 = ERROR.
--sign-key is optional and needs `pip install szl-receipt-dsse`; without it the receipt is UNSIGNED and says so."""
import argparse, json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from kernel import szl_make_session_receipt, szl_sign_session_receipt, szl_verify_session_receipt  # noqa: E402

def read(p):
    return json.loads(pathlib.Path(p).read_text(encoding="utf-8"))

def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record"); r.add_argument("manifest"); r.add_argument("--root", required=True); r.add_argument("--output", default=None); r.add_argument("--sign-key", default=None)
    v = sub.add_parser("verify"); v.add_argument("receipt"); v.add_argument("--root", required=True)
    m = sub.add_parser("methods"); m.add_argument("receipt")
    a = ap.parse_args()
    if a.cmd == "record":
        receipt = szl_make_session_receipt(a.root, read(a.manifest))
        if receipt["status"] == "ERROR":
            print(json.dumps(receipt, indent=2)); return 2
        if a.sign_key:
            receipt = szl_sign_session_receipt(receipt, pathlib.Path(a.sign_key).read_bytes())
        text = json.dumps(receipt, indent=2)
        if a.output:
            pathlib.Path(a.output).write_text(text + "\n", encoding="utf-8")
        print(text)
        return 0
    if a.cmd == "verify":
        result = szl_verify_session_receipt(a.root, read(a.receipt))
        print(json.dumps(result, indent=2))
        return 2 if result["status"] == "ERROR" else 0
    receipt = read(a.receipt)
    print(receipt.get("methods_paragraph", ""))
    return 0

if __name__ == "__main__":
    sys.exit(main())
