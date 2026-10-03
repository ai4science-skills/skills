#!/usr/bin/env python3
"""Compare locked local skill-package inventories without loading package code."""
import argparse
import json
import os
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from kernel import szl_review_updates  # noqa: E402


def _render(report):
    lines = ["# Skill package update review", "", f"Status: **{report['status']}**", ""]
    if report["status"] == "INCOMPLETE":
        lines += ["## Incomplete input", ""]
        lines += [f"- {json.dumps(error)}" for error in report["errors"]]
    else:
        lines += [f"Package: {report['package']}",
                  f"Old revision: {report['snapshots']['old']['revision']}",
                  f"New revision: {report['snapshots']['new']['revision']}",
                  f"Retained lock SHA-256: {report['snapshots']['lock_sha256']}", "", "## Skill changes", ""]
        changes = report["changes"]
        for key in ("added_skills", "added_skill_declarations", "removed_skills", "removed_skill_declarations",
                    "equal_byte_rename_candidates", "modified_skills"):
            lines.append(f"- {key}: {json.dumps(changes[key], sort_keys=True)}")
        lines += ["", "## Package files", "", json.dumps(changes["package_files"], sort_keys=True),
                  "", "License or notice artifacts changed: " + json.dumps(changes["license_artifact_changes"]),
                  "", "## Declared and literal evidence", "",
                  "Declared hosts, credentials, and licenses are metadata claims. URL hosts and credential marker names are partial static observations; values are omitted. Dynamic destinations are UNKNOWN.",
                  "", json.dumps(report["observations"], sort_keys=True), "", "## Evidence and tests to revisit", ""]
        for action in report["rerun"]:
            lines.append(f"- {action['scope']} ({action['reason']}): " + "; ".join(action["evidence_and_tests"]))
        if not report["rerun"]:
            lines.append("- No package byte or declaration change was recorded against the retained lock.")
    lines += ["", "## Limits", ""]
    lines += [f"- {limit}" for limit in report["limits"]]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("old_inventory", help="old inventory JSON retained outside its package root")
    parser.add_argument("new_inventory", help="new inventory JSON retained outside its package root")
    parser.add_argument("--old-root", required=True, help="old immutable local package root")
    parser.add_argument("--new-root", required=True, help="new immutable local package root")
    parser.add_argument("--lock", required=True, help="separately retained lock JSON")
    parser.add_argument("--output-dir", required=True, help="new directory for UPDATE_REVIEW.json and UPDATE_REVIEW.md")
    args = parser.parse_args(argv)
    output = pathlib.Path(args.output_dir).resolve()
    roots = [pathlib.Path(args.old_root).resolve(), pathlib.Path(args.new_root).resolve()]
    if any(output == root or root in output.parents for root in roots):
        parser.error("output directory must be outside both package roots")
    if output.exists() or not output.parent.is_dir():
        parser.error("output directory must be new, with an existing parent")
    report = szl_review_updates(args.old_root, args.old_inventory,
                                args.new_root, args.new_inventory, args.lock)
    try:
        with tempfile.TemporaryDirectory(prefix=".update-review-", dir=output.parent) as temporary:
            stage = pathlib.Path(temporary)
            (stage / "UPDATE_REVIEW.json").write_text(
                json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
            (stage / "UPDATE_REVIEW.md").write_text(_render(report), encoding="utf-8")
            os.replace(stage, output)
    except OSError as error:
        parser.error(f"cannot write review: {error}")
    print(f"{report['status']}: {output}")
    return 2 if report["status"] == "INCOMPLETE" else 0


if __name__ == "__main__":
    sys.exit(main())
