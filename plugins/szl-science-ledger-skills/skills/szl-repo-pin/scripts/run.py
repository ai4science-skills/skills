#!/usr/bin/env python3
"""Usage:
  python scripts/run.py pin DECLARATION.json --root PROJECT_DIR [--output pin.json]
  python scripts/run.py verify pin.json --root PROJECT_DIR
  python scripts/run.py show pin.json            (prints the recorded pin in one line per repository)

Exit 0 = ran (read "status"), 2 = ERROR. Needs the git executable; never contacts a remote."""
import argparse, json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from kernel import szl_make_pin, szl_verify_pin  # noqa: E402


def read(p):
    return json.loads(pathlib.Path(p).read_text(encoding="utf-8"))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pin"); p.add_argument("declaration"); p.add_argument("--root", required=True); p.add_argument("--output", default=None)
    v = sub.add_parser("verify"); v.add_argument("pin"); v.add_argument("--root", required=True)
    s = sub.add_parser("show"); s.add_argument("pin")
    a = ap.parse_args()
    if a.cmd == "pin":
        result = szl_make_pin(a.root, read(a.declaration))
        text = json.dumps(result, indent=2)
        if a.output and result["status"] != "ERROR":
            pathlib.Path(a.output).write_text(text + "\n", encoding="utf-8")
        print(text); return 2 if result["status"] == "ERROR" else 0
    if a.cmd == "verify":
        result = szl_verify_pin(a.root, read(a.pin)); print(json.dumps(result, indent=2)); return 2 if result["status"] == "ERROR" else 0
    pin = read(a.pin)
    if pin.get("schema") != "szl.repo-pin.v1":
        print(json.dumps({"status": "ERROR", "error": "not a szl.repo-pin.v1 pin"})); return 2
    lines = ["%s  %s  %s  %s" % (r.get("name"), (r.get("head") or "-")[:12], r.get("state"), r.get("tag_at_head") or "") for r in pin.get("repos", [])]
    print(json.dumps({"status": pin.get("status"), "composite_sha256": pin.get("composite_sha256"), "repos": lines}, indent=2)); return 0


if __name__ == "__main__":
    sys.exit(main())
