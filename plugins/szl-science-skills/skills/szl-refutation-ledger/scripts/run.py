#!/usr/bin/env python3
"""Usage:
  python scripts/run.py init LEDGER.json [--title TEXT]
  python scripts/run.py append LEDGER.json ENTRY.json [--at 2026-10-01T00:00:00Z] [--output LEDGER.json]
  python scripts/run.py verify LEDGER.json
  python scripts/run.py status LEDGER.json [--claim CLAIM_ID]

ENTRY.json is {"kind": "claim" | "attempt" | "withdrawal", "body": {...}} (see references/contract.md).
Exit 0 = ran (read "status"), 2 = ERROR. `append` never rewrites history: it refuses a ledger whose chain is broken.
Without --at, recorded_at is the current UTC time."""
import argparse, datetime, json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from kernel import szl_append, szl_ledger_status, szl_new_ledger, szl_replication_record, szl_verify_ledger  # noqa: E402


def read(p):
    return json.loads(pathlib.Path(p).read_text(encoding="utf-8"))


def write(p, value):
    pathlib.Path(p).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("init"); i.add_argument("ledger"); i.add_argument("--title", default="")
    a = sub.add_parser("append"); a.add_argument("ledger"); a.add_argument("entry"); a.add_argument("--at", default=None); a.add_argument("--output", default=None)
    v = sub.add_parser("verify"); v.add_argument("ledger")
    s = sub.add_parser("status"); s.add_argument("ledger"); s.add_argument("--claim", default=None)
    args = ap.parse_args()
    if args.cmd == "init":
        if pathlib.Path(args.ledger).exists():
            print(json.dumps({"status": "ERROR", "error": "ledger exists; append to it instead"})); return 2
        write(args.ledger, szl_new_ledger(args.title)); print(json.dumps({"status": "CREATED", "ledger": args.ledger})); return 0
    if args.cmd == "append":
        entry = read(args.entry)
        at = args.at or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        result = szl_append(read(args.ledger), entry.get("kind"), entry.get("body"), at)
        if result["status"] == "ERROR":
            print(json.dumps(result, indent=2)); return 2
        write(args.output or args.ledger, result["ledger"])
        print(json.dumps({"status": "APPENDED", "entry": result["entry"]}, indent=2)); return 0
    if args.cmd == "verify":
        result = szl_verify_ledger(read(args.ledger)); print(json.dumps(result, indent=2))
        return 2 if result["status"] == "ERROR" else 0
    status = szl_ledger_status(read(args.ledger))
    if status["status"] == "ERROR":
        print(json.dumps(status, indent=2)); return 2
    if args.claim:
        print(szl_replication_record(status, args.claim)); return 0
    print(json.dumps(status, indent=2)); return 0


if __name__ == "__main__":
    sys.exit(main())
