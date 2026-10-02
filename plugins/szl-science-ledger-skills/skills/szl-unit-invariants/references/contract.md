# Contract: szl.unit-invariants.v1

The top-level object has exactly `schema`, `quantities`, and `invariants`. Unknown fields are rejected. Every quantity has exactly `id`, `unit`, `dimension`, `values`, and `range_si`. Ids match `[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}` and are unique. `values` is a nonempty array of at most 1000 numbers or decimal strings; booleans, NaN, infinity, expressions, and numbers outside zero or magnitude `1e-100..1e100` are rejected. Tokens contain at most 80 characters with an optional at most three-digit exponent. The entire record is bounded to 10000 quantity samples.

`dimension` is a seven-integer vector ordered **length, mass, time, electric current, thermodynamic temperature, amount of substance, luminous intensity**; each exponent is in `-8..8`. For example `m/s` is `[1,0,-1,0,0,0,0]`. A unit's table dimension is authoritative for arithmetic; disagreement with the declared dimension creates a finding. `range_si` is either null or exactly `{"min": decimal, "max": decimal}` in canonical SI units; bounds are inclusive.

The CLI validates each raw noninteger JSON numeric token before constructing a Decimal;
it never first rounds through binary64. Nonzero underflow such as `1e-400`, overflow,
out-of-bound exact values and overlong exponent spellings fail closed. Exact zero with
a supported exponent spelling remains zero. Integer-only fields remain integer-only:
numeric `1.0` does not become an integer dimension exponent or a string identifier.
The direct Python API also accepts Decimal values. A float supplied by a caller has
already lost any original lexical precision; use Decimal or decimal strings for exact
inputs. Arithmetic still uses the documented 50-digit context, rather than unlimited precision.

`input_sha256` binds sorted compact UTF-8 JSON with Decimal values represented by the
typed object `{"szl_decimal": "<Decimal str>"}`. This representation distinguishes a
Decimal number from a quoted decimal string; schema validation rejects caller objects
in numeric fields. Existing records without Decimal values retain their digest encoding.
`input_digest_encoding` names `canonical_json_with_decimal_tags.v1`. The CLI additionally
reports `input_bytes_sha256` of the exact supplied bytes, preserving distinctions in
whitespace and numeric lexeme spelling. Neither digest authenticates the evidence.

Allowlisted symbols and scale to SI:

| Symbols | Scales | SI dimension |
| --- | --- | --- |
| `1` | 1 | dimensionless |
| `m`, `cm`, `mm`, `km` | 1, 0.01, 0.001, 1000 | length |
| `kg`, `g`, `mg` | 1, 0.001, 0.000001 | mass |
| `s`, `ms`, `min`, `h` | 1, 0.001, 60, 3600 | time |
| `A`, `K`, `mol`, `cd` | 1 | corresponding SI base dimension |
| `Hz` | 1 | `[0,0,-1,0,0,0,0]` |
| `m/s`, `cm/s` | 1, 0.01 | `[1,0,-1,0,0,0,0]` |
| `m/s^2` | 1 | `[1,0,-2,0,0,0,0]` |
| `N`, `Pa`, `J`, `W` | 1 | respectively `[1,1,-2,0,0,0,0]`, `[-1,1,-2,0,0,0,0]`, `[2,1,-2,0,0,0,0]`, `[2,1,-3,0,0,0,0]` |

Units are case-sensitive exact symbols, not parsed expressions. `degC`, Fahrenheit, dB, percentages, dates, and arbitrary compound strings are unsupported. No affine offset is inferred.

Each invariant has exactly `id`, `operation`, `operands`, `result`, `atol_si`, and `rtol`. All references name known quantities. `equal` has one operand, `sum` has 2..100, and `difference`, `product`, `ratio` have two. The declared result array is compared to the operation on operand arrays, all of equal length with no broadcasting. Repeated operands are allowed to express, for example, a square via `product`. `equal`/`sum`/`difference` require compatible operand/result dimensions. `product` adds operand vectors and `ratio` subtracts them. Dimensional or shape failure skips numeric checking for that invariant. Zero denominators produce `UNDEFINED_RATIO`; they are never clamped.

The comparison is `abs(actual - expected) <= atol_si + rtol * abs(expected)`, with nonnegative absolute tolerance in result SI units and `rtol` in `0..1`. Tolerances are prespecified caller declarations. A fresh Decimal context uses 50 significant digits and round-half-even independently of ambient caller settings; inexact division and arithmetic are rounded in that context. This checker supplies no uncertainty model. If a failed comparison has two nonzero magnitudes whose larger/smaller ratio is at least 1000, it also emits `SCALE_MISMATCH`. Zero and sign errors still produce numerical findings without an invented scale ratio.

The report schema is `szl.unit-invariants-report.v1`; it contains sorted quantity/invariant reports and fixed finding fields `code`, `quantity`, `invariant`, `indexes`, `count`. Failure-index and detailed-case lists are capped at 100 while counts remain complete. Total invariant cases are limited to 10000. `PASS_DECLARED_CHECKS` means no declared check failed. `observed_units_verified` and `physical_law_verified` remain false. Malformed/unsupported input raises `ValueError`. The CLI exits 0 for a clean audit, 1 for a completed report with findings, and 2 for malformed input or IO failure; `--output` creates exclusively.
