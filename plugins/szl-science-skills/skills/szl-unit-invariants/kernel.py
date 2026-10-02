# SPDX-License-Identifier: Apache-2.0
# Modified 2026-09-30: exact JSON decimal validation and type-preserving input binding.
"""Finite SI normalization and declared numerical invariants, with no expression eval or I/O."""
import decimal
import hashlib
import json
import re


SZL_UNITS = {
    "1": ([0, 0, 0, 0, 0, 0, 0], "1"),
    "m": ([1, 0, 0, 0, 0, 0, 0], "1"),
    "cm": ([1, 0, 0, 0, 0, 0, 0], "0.01"),
    "mm": ([1, 0, 0, 0, 0, 0, 0], "0.001"),
    "km": ([1, 0, 0, 0, 0, 0, 0], "1000"),
    "kg": ([0, 1, 0, 0, 0, 0, 0], "1"),
    "g": ([0, 1, 0, 0, 0, 0, 0], "0.001"),
    "mg": ([0, 1, 0, 0, 0, 0, 0], "0.000001"),
    "s": ([0, 0, 1, 0, 0, 0, 0], "1"),
    "ms": ([0, 0, 1, 0, 0, 0, 0], "0.001"),
    "min": ([0, 0, 1, 0, 0, 0, 0], "60"),
    "h": ([0, 0, 1, 0, 0, 0, 0], "3600"),
    "A": ([0, 0, 0, 1, 0, 0, 0], "1"),
    "K": ([0, 0, 0, 0, 1, 0, 0], "1"),
    "mol": ([0, 0, 0, 0, 0, 1, 0], "1"),
    "cd": ([0, 0, 0, 0, 0, 0, 1], "1"),
    "Hz": ([0, 0, -1, 0, 0, 0, 0], "1"),
    "m/s": ([1, 0, -1, 0, 0, 0, 0], "1"),
    "cm/s": ([1, 0, -1, 0, 0, 0, 0], "0.01"),
    "m/s^2": ([1, 0, -2, 0, 0, 0, 0], "1"),
    "N": ([1, 1, -2, 0, 0, 0, 0], "1"),
    "Pa": ([-1, 1, -2, 0, 0, 0, 0], "1"),
    "J": ([2, 1, -2, 0, 0, 0, 0], "1"),
    "W": ([2, 1, -3, 0, 0, 0, 0], "1")
}


def szl_unit_number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float, str, decimal.Decimal)):
        raise ValueError(label + " must be a finite decimal number, not a boolean")
    token = str(value)
    if len(token) > 80 or re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]{1,3})?", token) is None:
        raise ValueError(label + " has an unsupported decimal representation")
    result = decimal.Decimal(token)
    magnitude = result.copy_abs()
    if not result.is_finite() or magnitude > decimal.Decimal("1e100") or (result != 0 and magnitude < decimal.Decimal("1e-100")):
        raise ValueError(label + " must be zero or have magnitude 1e-100..1e100")
    return result


def szl_unit_format(value):
    if value == 0:
        return "0"
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def szl_unit_json_default(value):
    """Bind Decimal inputs as typed numeric tokens, distinct from quoted strings."""
    if isinstance(value, decimal.Decimal):
        return {"szl_decimal": str(value)}
    raise TypeError("Unsupported canonical input type")


def szl_unit_id(value, label):
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value) is None:
        raise ValueError(label + " must be a 1..128 character identifier")
    return value


def szl_unit_keys(value, required, label):
    if not isinstance(value, dict) or set(value) != set(required):
        raise ValueError(label + " has missing or unknown fields")


def szl_audit_unit_invariants(record):
    """Check a restricted unit/dimension contract and fixed, pointwise SI invariants."""
    szl_unit_keys(record, ("schema", "quantities", "invariants"), "record")
    if record["schema"] != "szl.unit-invariants.v1":
        raise ValueError("Expected szl.unit-invariants.v1")
    quantities, invariants = record["quantities"], record["invariants"]
    if not isinstance(quantities, list) or not 1 <= len(quantities) <= 1000:
        raise ValueError("quantities must contain 1..1000 entries")
    if not isinstance(invariants, list) or len(invariants) > 1000:
        raise ValueError("invariants must contain at most 1000 entries")
    with decimal.localcontext(decimal.Context(prec=50, rounding=decimal.ROUND_HALF_EVEN, Emax=500, Emin=-500)):
        index, reports, findings = {}, [], []
        total_values = 0
        for quantity in quantities:
            szl_unit_keys(quantity, ("id", "unit", "dimension", "values", "range_si"), "quantity")
            key = szl_unit_id(quantity["id"], "quantity id")
            if key in index:
                raise ValueError("Duplicate quantity id")
            unit = quantity["unit"]
            if not isinstance(unit, str) or unit not in SZL_UNITS:
                raise ValueError("Unsupported unit; offset/logarithmic/contextual units are excluded")
            dimension = quantity["dimension"]
            if not isinstance(dimension, list) or len(dimension) != 7 or any(type(value) is not int or not -8 <= value <= 8 for value in dimension):
                raise ValueError("dimension needs seven integer SI exponents in -8..8")
            values = quantity["values"]
            if not isinstance(values, list) or not 1 <= len(values) <= 1000:
                raise ValueError("values must contain 1..1000 decimal samples")
            total_values += len(values)
            if total_values > 10000:
                raise ValueError("At most 10000 total quantity samples are supported")
            actual_dimension, factor = SZL_UNITS[unit]
            normalized = [szl_unit_number(value, "sample") * decimal.Decimal(factor) for value in values]
            dimension_match = dimension == actual_dimension
            if not dimension_match:
                findings.append({"code": "DECLARED_DIMENSION_MISMATCH", "quantity": key, "invariant": None, "indexes": [], "count": 1})
            bounds = quantity["range_si"]
            if bounds is not None:
                szl_unit_keys(bounds, ("min", "max"), "range_si")
                low = szl_unit_number(bounds["min"], "range min")
                high = szl_unit_number(bounds["max"], "range max")
                if low > high:
                    raise ValueError("range min exceeds max")
                bad = [position for position, value in enumerate(normalized) if not low <= value <= high]
                if bad:
                    findings.append({"code": "RANGE_VIOLATION", "quantity": key, "invariant": None, "indexes": bad[:100], "count": len(bad)})
            index[key] = {"dimension": actual_dimension, "values": normalized}
            reports.append({"id": key, "unit": unit, "si_dimension": list(actual_dimension),
                            "declared_dimension_match": dimension_match, "values_si": [szl_unit_format(value) for value in normalized]})
        invariant_ids, invariant_reports, total_cases = set(), [], 0
        for invariant in invariants:
            szl_unit_keys(invariant, ("id", "operation", "operands", "result", "atol_si", "rtol"), "invariant")
            key = szl_unit_id(invariant["id"], "invariant id")
            if key in invariant_ids:
                raise ValueError("Duplicate invariant id")
            invariant_ids.add(key)
            operation, operands, result_id = invariant["operation"], invariant["operands"], invariant["result"]
            if not isinstance(operation, str) or operation not in ("equal", "sum", "difference", "product", "ratio"):
                raise ValueError("Unsupported invariant operation; arbitrary expressions are forbidden")
            if not isinstance(operands, list) or not 1 <= len(operands) <= 100 or any(not isinstance(item, str) or item not in index for item in operands):
                raise ValueError("operands must reference 1..100 known quantities")
            if not isinstance(result_id, str) or result_id not in index:
                raise ValueError("result must reference a known quantity")
            if (operation == "equal" and len(operands) != 1) or (operation == "sum" and len(operands) < 2) or (operation in ("difference", "product", "ratio") and len(operands) != 2):
                raise ValueError("Wrong operand count for invariant operation")
            atol, rtol = szl_unit_number(invariant["atol_si"], "atol_si"), szl_unit_number(invariant["rtol"], "rtol")
            if atol < 0 or not 0 <= rtol <= 1:
                raise ValueError("atol_si must be nonnegative and rtol must be in 0..1")
            dims = [index[item]["dimension"] for item in operands]
            if operation in ("equal", "sum", "difference"):
                expected_dimension = dims[0]
                dimensional = all(item == expected_dimension for item in dims)
            elif operation == "product":
                expected_dimension = [left + right for left, right in zip(dims[0], dims[1])]
                dimensional = True
            else:
                expected_dimension = [left - right for left, right in zip(dims[0], dims[1])]
                dimensional = True
            dimensional = dimensional and index[result_id]["dimension"] == expected_dimension
            lengths = [len(index[item]["values"]) for item in operands + [result_id]]
            total_cases += max(lengths)
            if total_cases > 10000:
                raise ValueError("At most 10000 total invariant cases are supported")
            report = {"id": key, "operation": operation, "result": result_id, "status": "AGREEMENT_ON_DECLARED_CASES", "cases_checked": 0,
                      "mismatch_count": 0, "undefined_count": 0, "scale_mismatch_count": 0, "failures": []}
            if not dimensional:
                report["status"] = "DIMENSION_MISMATCH"
                findings.append({"code": "DIMENSION_MISMATCH", "quantity": None, "invariant": key, "indexes": [], "count": 1})
            elif len(set(lengths)) != 1:
                report["status"] = "ARRAY_LENGTH_MISMATCH"
                findings.append({"code": "ARRAY_LENGTH_MISMATCH", "quantity": None, "invariant": key, "indexes": [], "count": 1})
            else:
                mismatches, undefined, scale_mismatches = [], [], []
                for position in range(lengths[0]):
                    inputs = [index[item]["values"][position] for item in operands]
                    actual = index[result_id]["values"][position]
                    if operation == "ratio" and inputs[1] == 0:
                        undefined.append(position)
                        continue
                    if operation == "equal":
                        expected = inputs[0]
                    elif operation == "sum":
                        expected = sum(inputs, decimal.Decimal(0))
                    elif operation == "difference":
                        expected = inputs[0] - inputs[1]
                    elif operation == "product":
                        expected = inputs[0] * inputs[1]
                    else:
                        expected = inputs[0] / inputs[1]
                    report["cases_checked"] += 1
                    error, limit = abs(actual - expected), atol + rtol * abs(expected)
                    scale_ratio = None
                    if actual != 0 and expected != 0:
                        scale_ratio = max(abs(actual / expected), abs(expected / actual))
                    if error > limit:
                        mismatches.append(position)
                        if len(report["failures"]) < 100:
                            report["failures"].append({"index": position, "expected_si": szl_unit_format(expected), "actual_si": szl_unit_format(actual),
                                                       "absolute_error_si": szl_unit_format(error), "tolerance_si": szl_unit_format(limit),
                                                       "scale_ratio": None if scale_ratio is None else szl_unit_format(scale_ratio)})
                        if scale_ratio is not None and scale_ratio >= 1000:
                            scale_mismatches.append(position)
                for code, positions in (("NUMERICAL_MISMATCH", mismatches), ("UNDEFINED_RATIO", undefined), ("SCALE_MISMATCH", scale_mismatches)):
                    if positions:
                        findings.append({"code": code, "quantity": None, "invariant": key, "indexes": positions[:100], "count": len(positions)})
                report["mismatch_count"], report["undefined_count"], report["scale_mismatch_count"] = len(mismatches), len(undefined), len(scale_mismatches)
                if undefined:
                    report["status"] = "UNDEFINED_RATIO"
                elif mismatches:
                    report["status"] = "NUMERICAL_MISMATCH"
            invariant_reports.append(report)
        findings.sort(key=lambda item: (item["code"], item["quantity"] or "", item["invariant"] or ""))
        reports.sort(key=lambda item: item["id"])
        invariant_reports.sort(key=lambda item: item["id"])
        digest = hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False, default=szl_unit_json_default).encode("utf-8")).hexdigest()
        return {"schema": "szl.unit-invariants-report.v1", "status": "REVIEW_REQUIRED" if findings else "PASS_DECLARED_CHECKS",
                "input_sha256": digest, "input_digest_encoding": "canonical_json_with_decimal_tags.v1",
                "quantities": reports, "invariants": invariant_reports, "findings": findings,
                "finding_count": len(findings), "arithmetic_precision_decimal_digits": 50, "observed_units_verified": False,
                "physical_law_verified": False, "scientific_validity": "NOT_MEASURED", "behavioral_performance": "NOT_MEASURED"}
