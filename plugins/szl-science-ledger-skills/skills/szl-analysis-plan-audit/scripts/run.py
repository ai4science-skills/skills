#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Audit a frozen computational-analysis plan; no estimator or experiment is run."""
import argparse
import json
import pathlib
import runpy
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=pathlib.Path)
    parser.add_argument("--output", type=pathlib.Path)
    args = parser.parse_args()
    try:
        helper = runpy.run_path(str(pathlib.Path(__file__).resolve().parents[1] / "kernel.py"))
        with args.input.open("rb") as source:
            raw = source.read(helper["MAX_BYTES"] + 1)
        report = helper["szl_audit_analysis_plan"](helper["read_json"](raw))
        output = json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        if args.output:
            with args.output.open("x", encoding="utf-8") as destination:
                destination.write(output)
        else:
            sys.stdout.write(output)
        return 1 if report["status"] == "EXPLORATORY" else 0
    except (ValueError, TypeError, KeyError, OSError, UnicodeError, RecursionError, OverflowError) as error:
        print("INVALID_INPUT: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
