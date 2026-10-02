#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Audit an explicit bounded JSON manifest offline; never execute recorded transforms."""
import argparse
import json
import pathlib
import runpy
import sys


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError("Non-finite JSON constant")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=pathlib.Path)
    parser.add_argument("--output", type=pathlib.Path)
    args = parser.parse_args(argv)
    try:
        if args.input.is_symlink() or not args.input.is_file():
            raise ValueError("Input must be an explicit regular file")
        with args.input.open("rb") as source:
            raw = source.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError("Input exceeds 1 MiB")
        payload = json.loads(raw, object_pairs_hook=unique_keys, parse_constant=reject_constant)
        functions = runpy.run_path(str(pathlib.Path(__file__).resolve().parents[1] / "kernel.py"))
        report = functions["szl_audit_lineage"](payload)
        output = json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        if args.output:
            with args.output.open("x", encoding="utf-8") as destination:
                destination.write(output)
        else:
            sys.stdout.write(output)
        return 1 if report["finding_count"] else 0
    except (ValueError, TypeError, KeyError, OSError, RecursionError, OverflowError) as error:
        sys.stderr.write("Skill input/execution error: " + str(error) + "\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())
