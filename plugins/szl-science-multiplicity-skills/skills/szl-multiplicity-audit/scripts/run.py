#!/usr/bin/env python3
"""Usage: python scripts/run.py PLAN.json RESULTS.json [--output NEW_REPORT.json]."""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from kernel import MAX_BYTES, szl_audit_multiplicity  # noqa: E402


def _bounded(path):
    with path.open("rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=pathlib.Path)
    parser.add_argument("results", type=pathlib.Path)
    parser.add_argument("--output", type=pathlib.Path, help="New report path; existing files are retained")
    args = parser.parse_args()
    try:
        report = szl_audit_multiplicity(_bounded(args.plan), _bounded(args.results))
        rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if args.output:
            if args.output.resolve() in (args.plan.resolve(), args.results.resolve()):
                raise ValueError("output may not overwrite an input")
            with args.output.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(rendered)
        print(rendered, end="")
        return 2 if report["status"] == "ERROR" else (1 if report["status"] == "HOLD" else 0)
    except (OSError, ValueError) as error:
        print(json.dumps({"status": "ERROR", "error": str(error)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
