"""MODELED flotation rank before the bench.

Sorts one declared public score column into a rank band. Does not invent
recovery, grade, or selectivity percent. A bench CSV may be hashed; its
bytes are never turned into a recovery number. An optional descriptor
prior is unitless and may ABSTAIN. Energy stays UNAVAILABLE. Lambda
uniqueness is not decided here.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA = "szl.frontier.flotation-selectivity.v1"
ORGAN = "flotation-selectivity-before-bench"
DEFAULT_SCORE_COLUMNS = ("public_score", "screen_score")
_FORBIDDEN_TOKENS = frozenset({"recovery", "grade", "selectivity"})
_ID_COLUMNS = ("id", "reagent", "name")


class FlotationError(Exception):
    """Fail-closed flotation input error. No partial rank is emitted."""


def _load_prior():
    path = Path(__file__).with_name("prior.py")
    spec = importlib.util.spec_from_file_location("szl_flotation_prior", path)
    if spec is None or spec.loader is None:
        raise FlotationError("selectivity prior runner is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_prior_mod = _load_prior()
selectivity_prior = _prior_mod.prior


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")


def _forbidden(name: str) -> bool:
    tokens = set(_norm(name).split("_"))
    return bool(tokens & _FORBIDDEN_TOKENS)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _finite(text: str) -> float | None:
    raw = text.strip()
    if raw == "":
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    if not math.isfinite(value):
        return None
    return value


def _band(index: int, count: int) -> str:
    if count < 3:
        return "listed"
    cut = count / 3
    if index < cut:
        return "high"
    if index < 2 * cut:
        return "mid"
    return "low"


def _base_receipt() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "organ": ORGAN,
        "evidenceTier": "SOFTWARE_RECEIPT",
        "directive": "DEFER",
        "selectivity": "MODELED",
        "claims": {
            "execution": "SOFTWARE",
            "identity": "UNAVAILABLE",
            "input": "UNAVAILABLE",
            "policy": "MEASURED",
        },
        "tableSha256": None,
        "benchSha256": None,
        "scoreColumn": None,
        "rankBand": None,
        "rowCount": 0,
        "recoveryPercent": None,
        "note": "rank band only; no invented recovery",
        "energyClass": "UNAVAILABLE",
        "ato": False,
        "lambda": "OPEN",
        "trustCeiling": 0.97,
        "discourse": "REPORTED topic 412",
        "nexusOrgan": False,
        "mintNexusSpace": False,
        "prior": {
            "state": "UNAVAILABLE",
            "reason": "prior not requested",
            "missing": [],
            "S": None,
            "S_class": "UNAVAILABLE",
            "not": "flotation recovery",
            "tau": None,
        },
        "exhibitOnApex": False,
    }


def _read_table(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise FlotationError("reagent table has no header")
        fields = list(reader.fieldnames)
        rows = []
        for row in reader:
            if row is None:
                continue
            if not any((value or "").strip() for value in row.values()):
                continue
            rows.append({key: (value or "") for key, value in row.items() if key})
        return fields, rows


def _column(fields: list[str], wanted: str) -> str | None:
    target = _norm(wanted)
    for field in fields:
        if _norm(field) == target:
            return field
    return None


def build_receipt(
    table: Path | None = None,
    bench: Path | None = None,
    score_column: str | None = None,
    features: Mapping[str, Any] | None = None,
    weights: Mapping[str, Any] | None = None,
    tau: float = 0.15,
) -> dict[str, Any]:
    """Return a software receipt. recoveryPercent is always null."""

    receipt = _base_receipt()
    if features is not None or weights is not None:
        receipt["prior"] = selectivity_prior(features, weights, tau)
    if table is None:
        if features is None and weights is None:
            raise FlotationError("need a reagent table or a descriptor prior")
        receipt["note"] = "PRIOR path; no reagent table; recovery not invented"
        return receipt
    if not table.is_file():
        raise FlotationError(f"reagent table missing: {table}")

    receipt["tableSha256"] = _sha256(table)
    receipt["claims"]["identity"] = "MEASURED"

    if bench is not None and bench.is_file():
        receipt["benchSha256"] = _sha256(bench)
        receipt["claims"]["input"] = "MEASURED"
    elif bench is not None:
        receipt["note"] = "bench path missing; rank band only; no invented recovery"

    if score_column is not None and _forbidden(score_column):
        receipt["directive"] = "BLOCK"
        receipt["scoreColumn"] = _norm(score_column)
        receipt["note"] = "refused recovery, grade, or selectivity column"
        return receipt

    try:
        fields, rows = _read_table(table)
    except FlotationError as exc:
        receipt["note"] = str(exc)
        return receipt
    except OSError as exc:
        receipt["note"] = f"table unreadable: {exc}"
        return receipt

    requested = score_column
    chosen: str | None = None
    if requested is not None:
        chosen = _column(fields, requested)
        if chosen is None:
            receipt["note"] = "declared score column is not in the table"
            return receipt
    else:
        for candidate in DEFAULT_SCORE_COLUMNS:
            chosen = _column(fields, candidate)
            if chosen is not None:
                break
    if chosen is None:
        receipt["note"] = "no declared public score column"
        return receipt
    if _forbidden(chosen):
        receipt["directive"] = "BLOCK"
        receipt["scoreColumn"] = _norm(chosen)
        receipt["note"] = "refused recovery, grade, or selectivity column"
        return receipt

    id_field = next((field for name in _ID_COLUMNS if (field := _column(fields, name))), None)
    if id_field is None:
        receipt["scoreColumn"] = chosen
        receipt["note"] = "reagent table needs an id, reagent, or name column"
        return receipt

    parsed: list[tuple[str, float]] = []
    seen: set[str] = set()
    for row in rows:
        reagent_id = row.get(id_field, "").strip()
        if reagent_id == "":
            receipt["scoreColumn"] = chosen
            receipt["note"] = "blank reagent id"
            return receipt
        if reagent_id in seen:
            receipt["scoreColumn"] = chosen
            receipt["note"] = "duplicate reagent id"
            return receipt
        seen.add(reagent_id)
        score = _finite(row.get(chosen, ""))
        if score is None:
            receipt["scoreColumn"] = chosen
            receipt["note"] = "score column is not finite"
            return receipt
        parsed.append((reagent_id, score))

    if not parsed:
        receipt["scoreColumn"] = chosen
        receipt["note"] = "no reagent rows"
        return receipt

    ordered = sorted(parsed, key=lambda item: (-item[1], item[0]))
    count = len(ordered)
    receipt["scoreColumn"] = chosen
    receipt["rowCount"] = count
    receipt["rankBand"] = [
        {"id": reagent_id, "rank": index + 1, "band": _band(index, count)}
        for index, (reagent_id, _score) in enumerate(ordered)
    ]
    if receipt["benchSha256"] is not None:
        receipt["directive"] = "RELEASE"
        receipt["note"] = "rank band from declared public score; bench hashed; recovery not invented"
    else:
        receipt["directive"] = "DEFER"
        receipt["note"] = "MODELED rank band; bench CSV absent; recovery not invented"
    return receipt


def _load_mapping(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise FlotationError(f"{label} unreadable: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise FlotationError(f"{label} is not JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise FlotationError(f"{label} must be a JSON object")
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="szl-frontier flotation",
        description="MODELED flotation rank and abstaining selectivity prior. Never recovery.",
    )
    parser.add_argument("--table", type=Path, default=None)
    parser.add_argument("--bench", type=Path, default=None)
    parser.add_argument("--score-column", default=None)
    parser.add_argument("--features", type=Path, default=None)
    parser.add_argument("--weights", type=Path, default=None)
    parser.add_argument("--tau", type=float, default=0.15)
    args = parser.parse_args(argv)
    if args.table is None and args.features is None:
        parser.error("need --table or --features")
    try:
        features = _load_mapping(args.features, "features") if args.features is not None else None
        weights = _load_mapping(args.weights, "weights") if args.weights is not None else None
        receipt = build_receipt(
            args.table,
            args.bench,
            args.score_column,
            features,
            weights,
            args.tau,
        )
    except FlotationError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    json.dump(receipt, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    if receipt["directive"] == "BLOCK":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
