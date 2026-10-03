# Bounded input and report contract

Input schema: `szl.uncertainty-lineage/v1`. Provide `inputs` as an object of at
most 32 names, each with a finite numeric `value` and nonnegative finite
`sigma`. Name order is the order used by the correlation matrix. Boolean
values are not numbers. Convert values to consistent units before this tool;
the tool performs no unit conversion.

`correlation.mode` must be either `declared_independent` or
`correlation_matrix`. For a matrix, include an `order` list exactly matching
the input names and a complete, symmetric, positive-semidefinite `matrix`
with diagonal 1 and entries in [-1, 1]. This declares correlations of the
input errors; it does not validate that the declaration reflects the physical
experiment. Omission of `correlation` is an error.

`nodes` is a list of at most 256 operations in dependency order. Each node has
an unused `id`, one `op` from `add`, `subtract`, `multiply`, `divide`, and two
`args` referring to inputs or earlier nodes. A zero divisor and nonfinite
intermediate are errors. `targets` names one or more inputs or nodes, at most
32. Duplicate JSON keys, unknown fields, missing references and malformed
shapes fail closed. Raw input is capped at 1 MiB.
Input numbers are limited to 80 significant decimal digits and adjusted
exponents within ±400. Matrix positive-semidefiniteness is checked exactly
on the supplied decimal values. Point values and Jacobians use 80-digit decimal
precision and must be exact at that precision; any inexact point or Jacobian
operation, including a nonterminating decimal quotient, fails closed before any
report is emitted. This prevents silent cancellation such as `(1e100 + 1) - 1e100`
becoming zero. Nonzero intermediate point values and Jacobian entries have
adjusted decimal exponents within +/-800. Input precision does not authorize
silent intermediate rounding. Covariance contributions and their sum use exact rational arithmetic
on those decimal Jacobian values, sigmas and correlations, preserving small positive
residuals from near-perfect correlation. The square root uses 80-digit decimal
precision; report
numbers that would serialize as infinity or lose a nonzero value to JSON zero
are rejected. A near-singular correlation matrix may fail the strict
positive-semidefinite check rather than receive an invented zero variance.

For a target function `f`, the helper calculates the Jacobian `J` at the
declared input values and reports `J C J^T`, where
`C[i,j] = sigma[i] * correlation[i,j] * sigma[j]`. Signed pair contributions
make covariance effects visible. The standard uncertainty is the square root
of that local variance, not a confidence or credible interval. The report
includes the SHA-256 of the exact input bytes and retains declared ancestry
even when a derivative is zero.

The bundled example is synthetic: area = length × width with positive shared
correlation. It is a numerical regression fixture, not a measurement.
