#!/usr/bin/env python3
"""Map a manuscript onto one frozen reporting checklist. Compliance stays unevaluated."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

SCHEMA = "szl.reporting-guideline-audit/v1"
REPORT_SCHEMA = "szl.reporting-guideline-audit-report/v1"
MAX_BYTES = 65_536
MAX_TEXT = 240
ITEM_ID = re.compile(r"^[0-9]{1,2}[a-z]?$")
DESIGNS = frozenset({"cohort", "case-control", "cross-sectional"})
UNSUPPORTED = {
    "CONSORT_2010": "CONSORT 2010 is superseded by CONSORT 2025 and is not a frozen checklist here.",
    "PRISMA_2009": "PRISMA 2009 is superseded by PRISMA 2020 and is not a frozen checklist here.",
}
CITATIONS = {
    "PRISMA_2020": "Page et al., BMJ 2021;372:n71. Checklist CC BY 4.0. Item ids only.",
    "CONSORT_2025": "Hopewell et al., BMJ 2025;388:e081123. Statement CC BY 4.0. Item ids only.",
    "STROBE_2007": "von Elm et al., PLoS Med 2007;4(10):e296. Combined checklist item ids only.",
}


def _rows(text: str) -> tuple[tuple[str, str, str, str], ...]:
    rows = []
    for line in text.strip().splitlines():
        item_id, kind, designs, label = line.split("|", 3)
        if kind not in {"R", "C"} or not ITEM_ID.fullmatch(item_id) or not label:
            raise RuntimeError("frozen checklist row is malformed")
        rows.append((item_id, kind, designs, label))
    if len(rows) != len({row[0] for row in rows}):
        raise RuntimeError("frozen checklist repeats an item id")
    return tuple(rows)


# id|R required or C conditional|designs empty for every STROBE design|short topic
PRISMA_2020 = _rows("""
1|R||title
2|R||abstract
3|R||rationale
4|R||objectives
5|R||eligibility criteria
6|R||information sources
7|R||search strategy
8|R||selection process
9|R||data collection process
10a|R||outcome data items
10b|R||other data items
11|R||study risk-of-bias methods
12|R||effect measures
13a|R||studies eligible for each synthesis
13b|R||data preparation
13c|R||result display
13d|R||synthesis model
13e|R||heterogeneity methods
13f|R||sensitivity methods
14|R||reporting-bias methods
15|R||certainty methods
16a|R||selection results
16b|R||excluded studies
17|R||study characteristics
18|R||risk-of-bias results
19|R||individual-study results
20a|R||synthesis characteristics
20b|R||synthesis estimates
20c|R||heterogeneity results
20d|R||sensitivity results
21|R||reporting-bias results
22|R||certainty results
23a|R||interpretation
23b|R||limitations of the evidence
23c|R||limitations of the review process
23d|R||implications
24a|R||registration
24b|R||protocol
24c|R||amendments
25|R||support
26|R||competing interests
27|R||data, code, and materials
""")

CONSORT_2025 = _rows("""
1a|R||randomised-trial identification
1b|R||structured summary
2|R||trial registration
3|R||protocol and analysis plan
4|R||data sharing
5a|R||funding and funder role
5b|R||author conflicts
6|R||background and rationale
7|R||benefit and harm objectives
8|R||patient and public involvement
9|R||trial design
10|R||changes after commencement
11|R||setting and locations
12a|R||participant eligibility
12b|C||site and intervention-deliverer eligibility
13|R||intervention and comparator
14|R||outcomes
15|R||harm assessment
16a|R||sample size
16b|R||interim analyses and stopping
17a|R||allocation sequence
17b|R||randomisation restrictions
18|R||allocation concealment
19|R||enrolment and assignment access
20a|R||who was blinded
20b|C||how blinding was achieved
21a|R||group comparison methods
21b|R||who is analysed
21c|R||missing data
21d|R||additional analyses
22a|R||participant flow numbers
22b|R||losses and exclusions
23a|R||recruitment and follow-up dates
23b|C||why the trial ended
24a|R||intervention as delivered
24b|R||concomitant care
25|R||baseline characteristics
26|R||outcome results
27|R||harm results
28|R||ancillary analyses
29|R||interpretation
30|R||limitations
""")

STROBE_2007 = _rows("""
1a|R||study design in the title or abstract
1b|R||informative abstract
2|R||background and rationale
3|R||objectives
4|R||study design
5|R||setting
6a|R||participant selection
6b|C|cohort,case-control|matching
7|R||variables
8|R||data sources and measurement
9|R||bias
10|R||study size
11|R||quantitative variables
12a|R||statistical methods
12b|R||subgroups and interactions
12c|R||missing data
12d|C||design-specific loss, matching, or sampling
12e|R||sensitivity analyses
13a|R||participant numbers
13b|R||non-participation
13c|R||flow diagram
14a|R||participant characteristics
14b|R||missing-data counts
14c|R|cohort|follow-up time
15|R||outcome data
16a|R||effect estimates
16b|R||category boundaries
16c|C||absolute risk
17|R||other analyses
18|R||key results
19|R||limitations
20|R||interpretation
21|R||generalisability
22|R||funding
""")

CHECKLISTS = {
    "PRISMA_2020": PRISMA_2020,
    "CONSORT_2025": CONSORT_2025,
    "STROBE_2007": STROBE_2007,
}


def ids(guideline: str) -> tuple[str, ...]:
    return tuple(row[0] for row in CHECKLISTS[guideline])


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _bad_constant(value: str) -> None:
    raise ValueError("nonfinite JSON constant")


def _text(value: Any, label: str, required: bool) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(f"{label} must be a single-line string")
    cleaned = value.strip()
    if required and not cleaned:
        raise ValueError(f"{label} is empty")
    if len(cleaned) > MAX_TEXT:
        raise ValueError(f"{label} exceeds {MAX_TEXT} characters")
    return cleaned or None


def _blocked(code: str, detail: str, guideline: str | None, raw: bytes) -> dict[str, Any]:
    return {
        "schema": REPORT_SCHEMA,
        "status": "BLOCKED",
        "readiness": "HOLD",
        "reporting_compliance": "NOT_EVALUATED",
        "visual_confirmation": "NOT_PERFORMED",
        "guideline": guideline,
        "citation": CITATIONS.get(guideline or "", None),
        "findings": [{"code": code, "detail": detail}],
        "items": [],
        "input_sha256": hashlib.sha256(raw).hexdigest(),
    }


def _in_design(designs: str, design: str | None) -> bool:
    return not designs or (design is not None and design in designs.split(","))


def audit(payload: dict[str, Any], raw: bytes) -> dict[str, Any]:
    if set(payload) - {"schema", "guideline", "design", "items"} or {"schema", "guideline", "items"} - set(payload):
        return _blocked("MALFORMED", "missing or unexpected top-level fields", None, raw)
    if payload["schema"] != SCHEMA:
        return _blocked("MALFORMED", "schema is not the reporting-guideline audit", None, raw)
    guideline = payload["guideline"]
    if not isinstance(guideline, str):
        return _blocked("MALFORMED", "guideline must be a string", None, raw)
    if guideline in UNSUPPORTED:
        return _blocked("UNSUPPORTED_GUIDELINE", UNSUPPORTED[guideline], guideline, raw)
    if guideline not in CHECKLISTS:
        return _blocked("UNKNOWN_GUIDELINE", "no frozen checklist for this guideline", guideline, raw)
    design = payload.get("design")
    if guideline == "STROBE_2007":
        if design not in DESIGNS:
            return _blocked("DESIGN_REQUIRED", "declare cohort, case-control, or cross-sectional", guideline, raw)
    elif "design" in payload:
        return _blocked("DESIGN_FORBIDDEN", "this checklist has no study-design axis", guideline, raw)
    supplied = payload["items"]
    if not isinstance(supplied, list) or len(supplied) > 64:
        return _blocked("MALFORMED", "items must be a bounded list", guideline, raw)
    by_id: dict[str, dict[str, Any]] = {}
    for entry in supplied:
        if not isinstance(entry, dict) or set(entry) - {"id", "locator", "applicability", "applicability_reason"}:
            return _blocked("MALFORMED", "an item has missing or unexpected fields", guideline, raw)
        if "id" not in entry:
            return _blocked("MALFORMED", "an item has no id", guideline, raw)
        item_id = entry["id"]
        if not isinstance(item_id, str) or not ITEM_ID.fullmatch(item_id):
            return _blocked("MALFORMED", "an item id is not a checklist id", guideline, raw)
        if item_id in by_id:
            return _blocked("DUPLICATE_ITEM", "an item id is repeated", guideline, raw)
        by_id[item_id] = entry

    rows = []
    missing = []
    findings = []
    for item_id, kind, designs, label in CHECKLISTS[guideline]:
        active = _in_design(designs, design if isinstance(design, str) else None)
        if not active:
            if item_id in by_id:
                return _blocked(
                    "DESIGN_ITEM_NOT_IN_CHECKLIST",
                    f"{item_id} is not an item for the declared design",
                    guideline,
                    raw,
                )
            rows.append({
                "id": item_id,
                "topic": label,
                "expectation": "not_applicable_design",
                "disposition": "NOT_APPLICABLE_DESIGN",
                "locator": None,
                "applicability_reason": None,
            })
            continue
        entry = by_id.pop(item_id, None)
        if entry is None:
            missing.append(item_id)
            rows.append({
                "id": item_id,
                "topic": label,
                "expectation": "conditional" if kind == "C" else "required",
                "disposition": "MISSING",
                "locator": None,
                "applicability_reason": None,
            })
            continue
        applicability = entry.get("applicability")
        if kind == "C":
            if applicability not in {"applicable", "not_applicable"}:
                return _blocked(
                    "CONDITIONAL_APPLICABILITY_REQUIRED",
                    f"{item_id} needs applicability applicable or not_applicable",
                    guideline,
                    raw,
                )
        elif applicability not in {None, "applicable"}:
            return _blocked(
                "REQUIRED_ITEM_NOT_WAIVABLE",
                f"{item_id} is required and cannot be marked not applicable",
                guideline,
                raw,
            )
        try:
            locator = _text(entry.get("locator"), f"{item_id} locator", required=False)
            reason = _text(entry.get("applicability_reason"), f"{item_id} applicability_reason", required=False)
        except ValueError as error:
            return _blocked("MALFORMED", str(error), guideline, raw)
        if applicability == "not_applicable":
            if not reason:
                return _blocked(
                    "NOT_APPLICABLE_REASON_REQUIRED",
                    f"{item_id} needs a reason for not applicable",
                    guideline,
                    raw,
                )
            disposition = "NOT_APPLICABLE"
        else:
            if not locator:
                return _blocked("LOCATOR_REQUIRED", f"{item_id} needs a locator", guideline, raw)
            disposition = "LOCATED"
        rows.append({
            "id": item_id,
            "topic": label,
            "expectation": "conditional" if kind == "C" else "required",
            "disposition": disposition,
            "locator": locator,
            "applicability_reason": reason,
        })
    if by_id:
        return _blocked("UNKNOWN_ITEM", "an item id is not in the frozen checklist", guideline, raw)
    if missing:
        findings.append({"code": "MISSING_ITEM", "detail": "every frozen in-scope item must be present"})
    return {
        "schema": REPORT_SCHEMA,
        "status": "INCOMPLETE" if missing else "MAP_COMPLETE",
        "readiness": "HOLD",
        "reporting_compliance": "NOT_EVALUATED",
        "visual_confirmation": "NOT_PERFORMED",
        "guideline": guideline,
        "design": design if guideline == "STROBE_2007" else None,
        "citation": CITATIONS[guideline],
        "item_count": len(rows),
        "missing_ids": missing,
        "findings": findings,
        "items": rows,
        "input_sha256": hashlib.sha256(raw).hexdigest(),
    }


def evaluate(raw: bytes) -> dict[str, Any]:
    if len(raw) > MAX_BYTES:
        report = _blocked("MALFORMED", "input exceeds 64 KiB", None, b"")
        report["input_sha256"] = None
        return report
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_object, parse_constant=_bad_constant)
    except (UnicodeError, json.JSONDecodeError, ValueError) as error:
        return _blocked("MALFORMED", str(error), None, raw)
    if not isinstance(payload, dict):
        return _blocked("MALFORMED", "input must be a JSON object", None, raw)
    return audit(payload, raw)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        with args.manifest.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
    except OSError as error:
        print(json.dumps({
            "status": "BLOCKED",
            "reporting_compliance": "NOT_EVALUATED",
            "error": str(error),
        }))
        return 2
    if len(raw) > MAX_BYTES:
        report = _blocked("MALFORMED", "input exceeds 64 KiB", None, b"")
        report["input_sha256"] = None
    else:
        report = evaluate(raw)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        try:
            if args.output.resolve() == args.manifest.resolve():
                raise ValueError("output may not replace the input")
            with args.output.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(rendered)
        except (OSError, ValueError) as error:
            print(json.dumps({"status": "BLOCKED", "reporting_compliance": "NOT_EVALUATED", "error": str(error)}))
            return 2
    print(rendered, end="")
    return 0 if report["status"] == "MAP_COMPLETE" else 2


if __name__ == "__main__":
    sys.exit(main())
