#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Modified 2026-09-30: dispatch the bounded scope-contract mode.
"""Portable offline CLI; every skill contains its own identical copy."""
import argparse
import json
import pathlib
import re
import runpy
import sys


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=pathlib.Path)
    parser.add_argument("--output", type=pathlib.Path)
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path("."))
    args = parser.parse_args()
    skill = pathlib.Path(__file__).resolve().parents[1]
    try:
        with args.input.open("rb") as source:
            raw = source.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise ValueError("Input exceeds 8 MiB; select a bounded table explicitly")
        payload = json.loads(raw, object_pairs_hook=unique_keys,
                             parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Non-finite JSON")))
        if not isinstance(payload, dict):
            raise ValueError("Input must be an object")
        functions = runpy.run_path(str(skill / "kernel.py"))
        entrypoint = (skill / "SKILL.md").read_text(encoding="utf-8")
        match = re.search(r"(?m)^name: ([a-z0-9-]+)$", entrypoint)
        if match is None:
            raise ValueError("Missing skill name")
        skill_name = match.group(1)
        if skill_name == "szl-model-evaluation" and "records" in payload:
            report = functions["szl_evaluate_categories"](**payload)
            output = json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
            if args.output:
                with args.output.open("x", encoding="utf-8") as file:
                    file.write(output)
            else:
                sys.stdout.write(output)
            return 0
        names = {"szl-research-anatomy": "szl_anatomy_assess", "szl-math-claim-check": "szl_check_math_cases",
                 "szl-dataset-readiness": "szl_audit_dataset", "szl-model-evaluation": "szl_evaluate_predictions"}
        if skill_name == "szl-math-claim-check" and payload.get("schema") == "szl.math-claim-scope.v1":
            report = functions["szl_audit_math_scope"](payload)
        elif skill_name in names:
            report = functions[names[skill_name]](**payload)
        elif skill_name == "szl-kernel-comparison":
            report = functions["szl_compare_kernel_runs"](payload)
        elif skill_name == "szl-reproducibility-capsule":
            if payload.get("schema") == "szl.reproducibility-capsule.v1":
                report = functions["szl_verify_capsule"](str(args.root), payload)
            else:
                report = functions["szl_make_capsule"](str(args.root), **payload)
        else:
            raise ValueError("Unknown skill folder name")
        output = json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        if args.output:
            with args.output.open("x", encoding="utf-8") as file:
                file.write(output)
        else:
            sys.stdout.write(output)
        return 0
    except (ValueError, TypeError, KeyError, OSError, RecursionError, OverflowError) as error:
        print("Skill input/execution error: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
