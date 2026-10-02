# SPDX-License-Identifier: Apache-2.0
"""Offline, bounded checks for one declared increasing linear assay run."""

import decimal
import re


SZL_ASSAY_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]{1,3})?")
SZL_ASSAY_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}")
SZL_ASSAY_UNIT = re.compile(r"[A-Za-z0-9µμ%./^-]{1,32}")


def szl_assay_number(value, label):
    """Parse a bounded finite decimal; booleans and non-decimal tokens are refused."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str, decimal.Decimal)):
        raise ValueError(label + " must be a finite decimal")
    token = str(value)
    if len(token) > 80 or SZL_ASSAY_NUMBER.fullmatch(token) is None:
        raise ValueError(label + " has an unsupported decimal representation")
    result = decimal.Decimal(token)
    magnitude = result.copy_abs()
    if not result.is_finite() or magnitude > decimal.Decimal("1e30") or (
        result != 0 and magnitude < decimal.Decimal("1e-30")
    ):
        raise ValueError(label + " must be zero or have magnitude 1e-30..1e30")
    return result


def szl_assay_text(value):
    """Preserve the bounded Decimal value; digits do not assert measurement precision."""
    return str(value)


def szl_assay_keys(value, required, label, optional=()):
    if not isinstance(value, dict) or not set(required).issubset(value) or set(value) - set(required) - set(optional):
        raise ValueError(label + " has missing or unknown fields")


def szl_assay_id(value, label):
    if not isinstance(value, str) or SZL_ASSAY_ID.fullmatch(value) is None:
        raise ValueError(label + " must be a 1..64 character nonidentifying identifier")
    return value


def szl_assay_unit(value, label):
    if not isinstance(value, str) or SZL_ASSAY_UNIT.fullmatch(value) is None:
        raise ValueError(label + " must be a 1..32 character declared unit")
    return value


def szl_assay_reference(value, label):
    if not isinstance(value, str) or len(value) > 128 or any(ord(char) < 33 or ord(char) > 126 for char in value):
        raise ValueError(label + " must be an optional printable 0..128 character reference")
    return value


def szl_assay_positive(value, label):
    result = szl_assay_number(value, label)
    if result <= 0:
        raise ValueError(label + " must be positive")
    return result


def szl_assay_nonnegative(value, label):
    result = szl_assay_number(value, label)
    if result < 0:
        raise ValueError(label + " must be nonnegative")
    return result


def szl_audit_assay_measurement(record):
    """Check declared controls before returning any sample concentration estimate."""
    szl_assay_keys(record, (
        "schema", "assay_id", "run_id", "concentration_unit", "method_ref", "standards_ref",
        "limits", "calibrators", "blank", "quality_controls", "samples",
    ), "record")
    if record["schema"] != "szl.assay-measurement.v1":
        raise ValueError("Expected szl.assay-measurement.v1")
    assay_id = szl_assay_id(record["assay_id"], "assay_id")
    run_id = szl_assay_id(record["run_id"], "run_id")
    unit = szl_assay_unit(record["concentration_unit"], "concentration_unit")
    method_ref = szl_assay_reference(record["method_ref"], "method_ref")
    standards_ref = szl_assay_reference(record["standards_ref"], "standards_ref")
    limits = record["limits"]
    szl_assay_keys(limits, (
        "max_abs_standard_residual", "max_abs_blank_signal", "max_qc_relative_error",
        "quantification_min",
    ), "limits")
    max_residual = szl_assay_nonnegative(limits["max_abs_standard_residual"], "max_abs_standard_residual")
    max_blank = szl_assay_nonnegative(limits["max_abs_blank_signal"], "max_abs_blank_signal")
    max_qc_error = szl_assay_nonnegative(limits["max_qc_relative_error"], "max_qc_relative_error")
    quantification_min = szl_assay_nonnegative(limits["quantification_min"], "quantification_min")
    if max_qc_error > 1:
        raise ValueError("max_qc_relative_error must be at most 1")
    calibrators = record["calibrators"]
    blank = record["blank"]
    controls = record["quality_controls"]
    samples = record["samples"]
    if not isinstance(calibrators, list) or not 3 <= len(calibrators) <= 16:
        raise ValueError("calibrators must contain 3..16 entries")
    if not isinstance(controls, list) or not 2 <= len(controls) <= 16:
        raise ValueError("quality_controls must contain 2..16 independent entries")
    if not isinstance(samples, list) or not 1 <= len(samples) <= 256:
        raise ValueError("samples must contain 1..256 entries")
    well_ids = set()
    sample_ids = set()

    def register_well(item, label):
        well = szl_assay_id(item["well_id"], label + " well_id")
        if well in well_ids:
            raise ValueError("Duplicate well_id across assay run: " + well)
        well_ids.add(well)
        return well

    # The input grammar permits values near 1e30 separated by 1e-30. A 50-digit
    # context can erase that separation while centering the calibration points.
    # 200 digits retain the bounded input tokens through fit and inversion.
    with decimal.localcontext(decimal.Context(prec=200, rounding=decimal.ROUND_HALF_EVEN, Emax=1000, Emin=-1000)):
        points = []
        concentrations = set()
        for item in calibrators:
            szl_assay_keys(item, ("well_id", "concentration", "unit", "signal"), "calibrator")
            well = register_well(item, "calibrator")
            if szl_assay_unit(item["unit"], "calibrator unit") != unit:
                raise ValueError("Calibrator unit differs from declared concentration_unit")
            concentration = szl_assay_nonnegative(item["concentration"], "calibrator concentration")
            if concentration in concentrations:
                raise ValueError("Calibrator concentrations must be distinct")
            concentrations.add(concentration)
            points.append((well, concentration, szl_assay_number(item["signal"], "calibrator signal")))
        low, high = min(concentrations), max(concentrations)
        if not low <= quantification_min <= high:
            raise ValueError("quantification_min must lie within the calibrator range")
        szl_assay_keys(blank, ("well_id", "signal"), "blank")
        blank_well = register_well(blank, "blank")
        blank_signal = szl_assay_number(blank["signal"], "blank signal")
        checked_controls = []
        for item in controls:
            szl_assay_keys(item, ("well_id", "target_concentration", "unit", "signal"), "quality_control")
            well = register_well(item, "quality_control")
            if szl_assay_unit(item["unit"], "quality_control unit") != unit:
                raise ValueError("Quality-control unit differs from declared concentration_unit")
            target = szl_assay_positive(item["target_concentration"], "quality_control target_concentration")
            if not low <= target <= high:
                raise ValueError("Quality-control target is outside the calibrator range")
            checked_controls.append((well, target, szl_assay_number(item["signal"], "quality_control signal")))
        checked_samples = []
        for item in samples:
            szl_assay_keys(item, ("sample_id", "well_id", "signal", "dilution_factor"), "sample",
                           ("expanded_uncertainty", "coverage_factor", "uncertainty_unit",
                            "uncertainty_basis", "dilution_uncertainty_included"))
            sample_id = szl_assay_id(item["sample_id"], "sample_id")
            if sample_id in sample_ids:
                raise ValueError("Duplicate sample_id")
            sample_ids.add(sample_id)
            well = register_well(item, "sample")
            signal = szl_assay_number(item["signal"], "sample signal")
            factor = szl_assay_positive(item["dilution_factor"], "dilution_factor")
            if factor < 1 or factor > decimal.Decimal("1e6"):
                raise ValueError("dilution_factor must be in 1..1e6")
            checked_samples.append((sample_id, well, signal, factor, item))

        n = decimal.Decimal(len(points))
        mean_x = sum(point[1] for point in points) / n
        mean_y = sum(point[2] for point in points) / n
        sxx = sum((point[1] - mean_x) ** 2 for point in points)
        slope = sum((point[1] - mean_x) * (point[2] - mean_y) for point in points) / sxx
        intercept = mean_y - slope * mean_x
        residuals = [(well, abs(signal - (intercept + slope * concentration)))
                     for well, concentration, signal in points]
        findings = []
        if not method_ref:
            findings.append({"code": "METHOD_REFERENCE_MISSING"})
        if not standards_ref:
            findings.append({"code": "STANDARDS_REFERENCE_MISSING"})
        if slope <= 0:
            findings.append({"code": "NONPOSITIVE_CALIBRATION_SLOPE"})
        for well, residual in residuals:
            if residual > max_residual:
                findings.append({"code": "CALIBRATION_RESIDUAL_OUT_OF_LIMIT", "well_id": well})
        if abs(blank_signal) > max_blank:
            findings.append({"code": "BLANK_OUT_OF_LIMIT", "well_id": blank_well})
        if slope > 0:
            for well, target, signal in checked_controls:
                recovered = (signal - intercept) / slope
                if not low <= recovered <= high:
                    findings.append({"code": "QC_OUTSIDE_CALIBRATION_RANGE", "well_id": well})
                if abs(recovered - target) / target > max_qc_error:
                    findings.append({"code": "QC_OUT_OF_LIMIT", "well_id": well})
        hard_failure = any(finding["code"] not in ("METHOD_REFERENCE_MISSING", "STANDARDS_REFERENCE_MISSING")
                           for finding in findings)
        control_status = "FAIL" if hard_failure else "HOLD" if findings else "PASS_DECLARED_CONTROLS"
        sample_reports = []
        for sample_id, well, signal, factor, item in checked_samples:
            sample_findings = []
            uncertainty_keys = ("expanded_uncertainty", "coverage_factor", "uncertainty_unit",
                                "uncertainty_basis", "dilution_uncertainty_included")
            if not all(key in item for key in uncertainty_keys):
                sample_findings.append({"code": "UNCERTAINTY_NOT_DECLARED"})
                uncertainty = None
                coverage = None
                basis = None
                dilution_included = None
            else:
                uncertainty = szl_assay_positive(item["expanded_uncertainty"], "expanded_uncertainty")
                coverage = szl_assay_positive(item["coverage_factor"], "coverage_factor")
                if coverage < 1:
                    raise ValueError("coverage_factor must be at least 1")
                if szl_assay_unit(item["uncertainty_unit"], "uncertainty_unit") != unit:
                    sample_findings.append({"code": "UNCERTAINTY_UNIT_MISMATCH"})
                basis = item["uncertainty_basis"]
                if basis != "FINAL_REPORTED_CONCENTRATION":
                    sample_findings.append({"code": "UNCERTAINTY_BASIS_NOT_FINAL"})
                dilution_included = item["dilution_uncertainty_included"]
                if not isinstance(dilution_included, bool):
                    raise ValueError("dilution_uncertainty_included must be boolean")
                if factor > 1 and not dilution_included:
                    sample_findings.append({"code": "DILUTION_UNCERTAINTY_NOT_INCLUDED"})
            raw_concentration = (signal - intercept) / slope if slope > 0 else None
            if raw_concentration is not None:
                if not low <= raw_concentration <= high:
                    sample_findings.append({"code": "OUTSIDE_CALIBRATION_RANGE"})
                elif raw_concentration < quantification_min:
                    sample_findings.append({"code": "BELOW_DECLARED_QUANTIFICATION_MIN"})
            if control_status != "PASS_DECLARED_CONTROLS":
                sample_findings.append({"code": "CONTROL_GATE_NOT_PASSED"})
            passed = not sample_findings
            sample_reports.append({
                "sample_id": sample_id,
                "well_id": well,
                "status": "PASS_DECLARED_CHECKS" if passed else "HOLD",
                "concentration": szl_assay_text(raw_concentration * factor) if passed else None,
                "expanded_uncertainty": szl_assay_text(uncertainty) if passed else None,
                "coverage_factor": szl_assay_text(coverage) if passed else None,
                "uncertainty_basis": basis if passed else None,
                "dilution_uncertainty_included": dilution_included if passed else None,
                "findings": sample_findings,
            })
        status = "FAIL" if hard_failure else "HOLD" if findings or any(
            item["status"] == "HOLD" for item in sample_reports) else "PASS_DECLARED_CHECKS"
        return {
            "schema": "szl.assay-measurement-report.v1",
            "assay_id": assay_id,
            "run_id": run_id,
            "concentration_unit": unit,
            "status": status,
            "calibration": {
                "model": "UNWEIGHTED_INCREASING_LINEAR",
                "slope": szl_assay_text(slope),
                "intercept": szl_assay_text(intercept),
                "range": [szl_assay_text(low), szl_assay_text(high)],
                "quantification_min": szl_assay_text(quantification_min),
                "max_abs_residual_observed": szl_assay_text(max(residual for _, residual in residuals)),
                "calibrators": len(points),
            },
            "controls": {"status": control_status, "findings": findings, "quality_controls": len(checked_controls)},
            "samples": sample_reports,
            "finding_count": len(findings) + sum(len(item["findings"]) for item in sample_reports),
            "boundaries": {
                "method_and_standards_references": "DECLARED_ONLY",
                "uncertainty": "DECLARED_NOT_PROPAGATED_OR_VERIFIED",
                "metrological_traceability": "NOT_ESTABLISHED",
                "scientific_validity": "NOT_EVALUATED",
                "clinical_use": "NOT_QUALIFIED",
            },
        }
