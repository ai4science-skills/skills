"""Bounded, offline first-order uncertainty propagation for declared graphs."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sys
from decimal import Decimal, DecimalException, Inexact, localcontext
from fractions import Fraction
from pathlib import Path
from typing import Any

SCHEMA = "szl.uncertainty-lineage/v1"
REPORT_SCHEMA = "szl.uncertainty-lineage-report/v1"
NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
MAX_BYTES = 1_048_576
MAX_INTERMEDIATE_EXPONENT = 800


class ContractError(ValueError):
    """The declared numerical model cannot be evaluated as written."""


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError("duplicate JSON key")
        result[key] = value
    return result


def _bad_constant(value: str) -> None:
    raise ContractError(f"nonfinite JSON constant: {value}")


def _keys(value: Any, allowed: set[str], required: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - allowed or required - set(value):
        raise ContractError(f"{label} has missing, extra, or malformed fields")
    return value


def _number(value: Any, label: str) -> Decimal:
    if type(value) not in (int, float, Decimal):
        raise ContractError(f"{label} must be a finite number")
    try:
        number = value if type(value) is Decimal else Decimal(str(value))
    except (ValueError, DecimalException) as error:
        raise ContractError(f"{label} is not a decimal number") from error
    if not number.is_finite():
        raise ContractError(f"{label} must be finite")
    if len(number.as_tuple().digits) > 80 or (number and abs(number.adjusted()) > 400):
        raise ContractError(f"{label} exceeds the numeric range or precision bound")
    return number


def _name(value: Any, label: str) -> str:
    if not isinstance(value, str) or not NAME.fullmatch(value):
        raise ContractError(f"{label} must be a short identifier")
    return value


def _finite(value: Decimal, label: str) -> Decimal:
    if not value.is_finite():
        raise ContractError(f"{label} overflows finite arithmetic")
    if value and abs(value.adjusted()) > MAX_INTERMEDIATE_EXPONENT:
        raise ContractError(f"{label} exceeds the intermediate exponent bound")
    return value


def _json_number(value: Decimal | Fraction, label: str) -> float:
    """Never serialize a nonzero declared result as JSON zero or infinity."""
    try:
        result = float(value)
    except OverflowError as error:
        raise ContractError(f"{label} is outside finite JSON number range") from error
    if not math.isfinite(result) or (value != 0 and result == 0.0):
        raise ContractError(f"{label} is outside finite JSON number range")
    return result


def _psd_correlation(matrix: list[list[Decimal]]) -> None:
    """Exact rational LDL factorization of the supplied decimal matrix."""
    size = len(matrix)
    zero = Fraction(0)
    exact = [[Fraction(value) for value in row] for row in matrix]
    lower = [[zero] * size for _ in range(size)]
    diagonal = [zero] * size
    for k in range(size):
        residual = exact[k][k] - sum(
            (lower[k][j] * lower[k][j] * diagonal[j] for j in range(k)), zero
        )
        if residual < 0:
            raise ContractError("correlation matrix is not positive semidefinite")
        diagonal[k] = residual
        for i in range(k + 1, size):
            link = exact[i][k] - sum(
                (lower[i][j] * lower[k][j] * diagonal[j] for j in range(k)), zero
            )
            if diagonal[k] == 0:
                if link != 0:
                    raise ContractError("correlation matrix is not positive semidefinite")
            else:
                lower[i][k] = link / diagonal[k]


def _correlations(raw: Any, names: list[str]) -> tuple[str, list[list[Decimal]]]:
    spec = _keys(raw, {"mode", "order", "matrix"}, {"mode"}, "correlation")
    mode = spec["mode"]
    count = len(names)
    if mode == "declared_independent":
        if set(spec) != {"mode"}:
            raise ContractError("independence declaration cannot include a matrix")
        return mode, [[Decimal(int(i == j)) for j in range(count)] for i in range(count)]
    if mode != "correlation_matrix" or set(spec) != {"mode", "order", "matrix"}:
        raise ContractError("complete correlation declaration required")
    if spec["order"] != names:
        raise ContractError("correlation order must exactly match input order")
    raw_matrix = spec["matrix"]
    if not isinstance(raw_matrix, list) or len(raw_matrix) != count:
        raise ContractError("correlation matrix dimension mismatch")
    matrix: list[list[Decimal]] = []
    for i, row in enumerate(raw_matrix):
        if not isinstance(row, list) or len(row) != count:
            raise ContractError("correlation matrix must be square")
        values = [_number(value, f"correlation[{i},{j}]") for j, value in enumerate(row)]
        if any(abs(value) > 1 for value in values):
            raise ContractError("correlation entry outside [-1, 1]")
        matrix.append(values)
    for i in range(count):
        if matrix[i][i] != 1:
            raise ContractError("correlation diagonal must be 1")
        for j in range(i):
            if matrix[i][j] != matrix[j][i]:
                raise ContractError("correlation matrix is asymmetric")
    _psd_correlation(matrix)
    return mode, matrix


def _evaluate(model: Any, raw_bytes: bytes) -> dict[str, Any]:
    spec = _keys(
        model,
        {"schema", "inputs", "correlation", "nodes", "targets"},
        {"schema", "inputs", "correlation", "nodes", "targets"},
        "model",
    )
    if spec["schema"] != SCHEMA:
        raise ContractError("unsupported input schema")
    inputs = spec["inputs"]
    if not isinstance(inputs, dict) or not 1 <= len(inputs) <= 32:
        raise ContractError("inputs must contain 1 to 32 declarations")
    names = list(inputs)
    sigmas: list[Decimal] = []
    # Each value has: point estimate, Jacobian, and declared ancestry.
    values: dict[str, tuple[Decimal, list[Decimal], set[str]]] = {}
    for index, name in enumerate(names):
        _name(name, "input name")
        entry = _keys(inputs[name], {"value", "sigma"}, {"value", "sigma"}, name)
        point = _number(entry["value"], f"{name}.value")
        sigma = _number(entry["sigma"], f"{name}.sigma")
        if sigma < 0:
            raise ContractError(f"{name}.sigma must be nonnegative")
        gradient = [Decimal(0)] * len(names)
        gradient[index] = Decimal(1)
        values[name] = (point, gradient, {name})
        sigmas.append(sigma)
    mode, correlation = _correlations(spec["correlation"], names)
    nodes = spec["nodes"]
    if not isinstance(nodes, list) or len(nodes) > 256:
        raise ContractError("nodes must be a list of at most 256 operations")
    for index, node in enumerate(nodes):
        entry = _keys(node, {"id", "op", "args"}, {"id", "op", "args"}, f"node {index}")
        name = _name(entry["id"], f"node {index} id")
        if name in values:
            raise ContractError(f"duplicate input or node name: {name}")
        op = entry["op"]
        args = entry["args"]
        if op not in ("add", "subtract", "multiply", "divide") or not isinstance(args, list) or len(args) != 2:
            raise ContractError(f"node {name} requires a supported binary operation")
        if any(not isinstance(arg, str) or arg not in values for arg in args):
            raise ContractError(f"node {name} refers to an undeclared or later value")
        left, left_grad, left_dep = values[args[0]]
        right, right_grad, right_dep = values[args[1]]
        if op == "add":
            point = left + right
            gradient = [a + b for a, b in zip(left_grad, right_grad)]
        elif op == "subtract":
            point = left - right
            gradient = [a - b for a, b in zip(left_grad, right_grad)]
        elif op == "multiply":
            point = left * right
            gradient = [right * a + left * b for a, b in zip(left_grad, right_grad)]
        else:
            if right == 0:
                raise ContractError(f"node {name} divides by zero")
            point = left / right
            gradient = [(a - point * b) / right for a, b in zip(left_grad, right_grad)]
        values[name] = (
            _finite(point, f"node {name} value"),
            [_finite(item, f"node {name} gradient") for item in gradient],
            left_dep | right_dep,
        )
    targets = spec["targets"]
    if not isinstance(targets, list) or not 1 <= len(targets) <= 32 or len(set(map(str, targets))) != len(targets):
        raise ContractError("targets must be 1 to 32 distinct names")
    if any(not isinstance(name, str) or name not in values for name in targets):
        raise ContractError("target is undeclared")
    reports = []
    for target in targets:
        point, gradient, dependency = values[target]
        terms = []
        for i, name_i in enumerate(names):
            for j in range(i, len(names)):
                # Accumulate the quadratic form exactly on the bounded decimal
                # Jacobian values. Near-perfect correlation can cancel terms
                # whose residual lies below Decimal's intermediate precision.
                contribution = ((1 if i == j else 2) * Fraction(gradient[i]) * Fraction(sigmas[i])
                                * Fraction(gradient[j]) * Fraction(sigmas[j]) * Fraction(correlation[i][j]))
                terms.append({
                    "inputs": [name_i, names[j]],
                    "variance_contribution": contribution,
                })
        variance = sum((item["variance_contribution"] for item in terms), Fraction(0))
        if variance < 0:
            raise ContractError(f"{target} has a negative propagated variance")
        # Reject unrepresentable exact variance before rounding for the square
        # root. The conversion then keeps 80 significant decimal digits.
        variance_json = _json_number(variance, f"{target} variance")
        with localcontext() as approximation:
            # The exact quadratic form is already validated. Its square root
            # is explicitly a numerical approximation, unlike graph arithmetic.
            approximation.traps[Inexact] = False
            variance_decimal = Decimal(variance.numerator) / Decimal(variance.denominator)
            standard_uncertainty = _json_number(variance_decimal.sqrt(), f"{target} standard uncertainty")
        reports.append({
            "target": target,
            "value": _json_number(point, f"{target} value"),
            "variance": variance_json,
            "standard_uncertainty": standard_uncertainty,
            "jacobian": {name: _json_number(item, f"{target} Jacobian") for name, item in zip(names, gradient)},
            "declared_inputs": [name for name in names if name in dependency],
            "covariance_contributions": [
                {"inputs": item["inputs"],
                 "variance_contribution": _json_number(item["variance_contribution"], f"{target} covariance contribution")}
                for item in terms
            ],
        })
    return {
        "schema": REPORT_SCHEMA,
        "status": "EVALUATED_DECLARED_FIRST_ORDER_MODEL",
        "input_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "correlation_mode": mode,
        "targets": reports,
        "limitation": "Local first-order approximation of declared values and correlations; no unit, distribution, or scientific-truth verification.",
    }


def evaluate(model: Any, raw_bytes: bytes) -> dict[str, Any]:
    with localcontext() as context:
        context.prec = 80
        context.traps[Inexact] = True
        try:
            return _evaluate(model, raw_bytes)
        except Inexact as error:
            raise ContractError("point or Jacobian arithmetic is inexact at 80-digit precision") from error
        except DecimalException as error:
            raise ContractError("declared model exceeds decimal arithmetic bounds") from error


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python scripts/run.py MODEL.json", file=sys.stderr)
        return 2
    try:
        path = Path(argv[1])
        if path.stat().st_size > MAX_BYTES:
            raise ContractError("input exceeds 1 MiB")
        raw = path.read_bytes()
        if len(raw) > MAX_BYTES:
            raise ContractError("input exceeds 1 MiB")
        model = json.loads(raw, object_pairs_hook=_object, parse_constant=_bad_constant,
                           parse_float=Decimal, parse_int=Decimal)
        report = evaluate(model, raw)
    except (OSError, UnicodeError, ContractError, ValueError, DecimalException, RecursionError, OverflowError) as error:
        print(f"uncertainty-lineage: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
