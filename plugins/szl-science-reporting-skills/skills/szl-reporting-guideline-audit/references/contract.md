# Reporting map contract

Input schema: `szl.reporting-guideline-audit/v1`. Fields are `schema`,
`guideline`, `items`, and, only for `STROBE_2007`, `design`. Any other field
is a contract error.

`guideline` is `PRISMA_2020`, `CONSORT_2025`, or `STROBE_2007`. `CONSORT_2010`
and `PRISMA_2009` are refused as unsupported superseded checklists. No other
guideline is inferred.

`design` is `cohort`, `case-control`, or `cross-sectional` for STROBE. Items
that the combined checklist limits to another design are reported as
`NOT_APPLICABLE_DESIGN` and must not be supplied. For the other two
guidelines, `design` is forbidden.

Each item has `id` and may have `locator`, `applicability`, and
`applicability_reason`. A required item needs a non-empty locator. Conditional
items are CONSORT `12b`, `20b`, and `23b`, and STROBE `6b` (cohort and
case-control only), `12d`, and `16c`. A conditional item needs `applicability`
of `applicable` or `not_applicable`. `not_applicable` needs a reason. A
required item cannot be marked `not_applicable`.

Locators and reasons are single-line text of at most 240 characters. The input
is at most 64 KiB. Duplicate JSON keys and unknown item ids fail closed.
Leaving an in-scope item out yields `INCOMPLETE`, not a smaller passing map.

The report schema is `szl.reporting-guideline-audit-report/v1`. Status is
`MAP_COMPLETE`, `INCOMPLETE`, or `BLOCKED`. Exit 0 is only `MAP_COMPLETE`.
Every report keeps `readiness` `HOLD`, `reporting_compliance` `NOT_EVALUATED`,
and `visual_confirmation` `NOT_PERFORMED`. Topics are short reminders of the
frozen ids, not the guideline elaboration. Citations name the statement; they
are not a copy of the checklist prose.

The bundled example is a synthetic PRISMA map. Its locators are fixture
labels, not pages of a review.
