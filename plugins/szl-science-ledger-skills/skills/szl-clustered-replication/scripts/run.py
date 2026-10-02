#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline paired-cluster audit; 0 conditional, 1 descriptive only, 2 invalid input."""
import argparse
import hashlib
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from kernel import MAX_BYTES, read_json, szl_clustered_replication


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=pathlib.Path)
    parser.add_argument("--expected-plan-sha256")
    args = parser.parse_args()
    try:
        if args.input.is_symlink() or not args.input.is_file():
            raise ValueError("Input must be a regular non-symlink file")
        with args.input.open("rb") as handle:
            raw = handle.read(MAX_BYTES + 1)
        report = szl_clustered_replication(read_json(raw), args.expected_plan_sha256)
        report["input_raw_sha256"] = hashlib.sha256(raw).hexdigest()
        report["implementation_sha256"] = hashlib.sha256(
            (pathlib.Path(__file__).resolve().parents[1] / "kernel.py").read_bytes()).hexdigest()
    except (OSError, ValueError, UnicodeError, RecursionError) as error:
        report = {"status": "INPUT_ERROR", "error_type": type(error).__name__,
                  "reason": "Unable to read bounded valid experiment JSON", "conditional_exact_test": None}
    print(json.dumps(report, indent=2, allow_nan=False))
    return {"CONDITIONAL_CLUSTER_RESULT": 0, "DESCRIPTIVE_ONLY": 1, "INPUT_ERROR": 2}[report["status"]]


if __name__ == "__main__":
    sys.exit(main())
