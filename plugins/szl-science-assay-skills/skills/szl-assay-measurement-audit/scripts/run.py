#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Audit one declared linear assay JSON file offline without replacing outputs."""

import argparse
import decimal
import hashlib
import json
import os
import pathlib
import runpy
import sys
import tempfile


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
        functions = runpy.run_path(str(pathlib.Path(__file__).resolve().parents[1] / "kernel.py"))
        payload = json.loads(raw, object_pairs_hook=unique_keys, parse_constant=reject_constant,
                             parse_float=decimal.Decimal)
        report = functions["szl_audit_assay_measurement"](payload)
        report["input_bytes_sha256"] = hashlib.sha256(raw).hexdigest()
        output = json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        if args.output:
            staged = None
            try:
                # Finish and sync a sibling before a non-replacing, same-volume
                # hard link makes it visible at the requested final path.
                with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n",
                                                 dir=args.output.parent, prefix=".szl-assay-",
                                                 suffix=".tmp", delete=False) as destination:
                    staged = pathlib.Path(destination.name)
                    destination.write(output)
                    destination.flush()
                    os.fsync(destination.fileno())
                os.link(staged, args.output)
            finally:
                if staged is not None:
                    try:
                        staged.unlink(missing_ok=True)
                    except OSError:
                        sys.stderr.write("Warning: staged output cleanup failed\n")
        else:
            sys.stdout.write(output)
        return 0 if report["status"] == "PASS_DECLARED_CHECKS" else 1
    except (ValueError, TypeError, KeyError, OSError, RecursionError, OverflowError,
            decimal.DecimalException) as error:
        sys.stderr.write("Skill input/execution error: " + str(error) + "\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())
