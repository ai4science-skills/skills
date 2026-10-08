#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Read one bounded change-impact document; create a new report without executing graph data."""
import argparse
import json
import pathlib
import runpy
import sys


def pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("Duplicate JSON key: " + key)
        result[key] = value
    return result


def finite(value):
    raise ValueError("Nonfinite JSON constant: " + value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=pathlib.Path)
    parser.add_argument("--output", type=pathlib.Path)
    args = parser.parse_args()
    try:
        if args.input.is_symlink():
            raise ValueError("Input must be a selected regular file")
        with args.input.open("rb") as handle:
            raw = handle.read(2097153)
        if len(raw) > 2097152:
            raise ValueError("Input exceeds 2 MiB")
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=finite)
        kernel = runpy.run_path(str(pathlib.Path(__file__).resolve().parents[1] / "kernel.py"))
        report = kernel["szl_plan_research_changes"](document)
        text = json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n"
        if args.output:
            with args.output.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
        sys.stdout.write(text)
        return 0
    except (OSError, ValueError, TypeError, RecursionError, UnicodeError) as error:
        sys.stdout.write(json.dumps({"status": "INVALID_INPUT", "error": str(error),
                                    "experiments_executed": False}, sort_keys=True) + "\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())
