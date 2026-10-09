#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""CLI for the offline measurement harmonizer."""

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from harmonizer import AuditError, harmonize, read_manifest  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=pathlib.Path)
    parser.add_argument("--root", required=True, type=pathlib.Path)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    args = parser.parse_args()
    if args.output.resolve().is_relative_to(args.root.resolve()) or args.output.resolve() == args.manifest.resolve():
        parser.error("output must be outside the input root and cannot replace the manifest")
    if args.output.exists():
        parser.error("output already exists; choose a new receipt path")
    try:
        report = harmonize(read_manifest(args.manifest), args.root)
    except (AuditError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        report = {"schema": "szl.measurement-harmonizer.v1.report", "status": "BLOCKED", "rows": [],
                  "findings": [{"source": None, "code": getattr(exc, "code", "UNREADABLE_MANIFEST")}],
                  "mapping_authority": "DECLARED_ONLY", "scientific_validity": "NOT_EVALUATED",
                  "network": "NOT_USED", "execution": "NOT_RUN"}
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": report["status"], "rows": len(report["rows"]),
                      "findings": report["findings"], "output": str(args.output)}, sort_keys=True))
    return {"HARMONIZED": 0, "BLOCKED": 2, "UNAVAILABLE": 3}[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
