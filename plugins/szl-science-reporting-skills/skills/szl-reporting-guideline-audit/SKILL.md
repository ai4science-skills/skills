---
name: szl-reporting-guideline-audit
description: Map a manuscript onto the frozen PRISMA 2020, CONSORT 2025, or STROBE 2007 checklist and show every omitted item. Use before calling a paper complete against one of those guidelines. A locator is not visual confirmation, and the report does not judge reporting compliance.
license: Apache-2.0
---

# Reporting guideline audit

Check a declared manuscript map against one frozen checklist:

```bash
python scripts/run.py assets/example.json
```

The helper accepts `PRISMA_2020`, `CONSORT_2025`, or `STROBE_2007`. STROBE also
requires a declared design: `cohort`, `case-control`, or `cross-sectional`.
Every in-scope item must appear. Conditional items need an explicit
applicability. A required item cannot be waived. A locator records where the
author says the item is discussed. Read `references/contract.md` for the input
and report fields.

The helper uses only the Python standard library. It does not download a
guideline, open a manuscript, or confirm that a locator is visible on the page.
`reporting_compliance` stays `NOT_EVALUATED` and `visual_confirmation` stays
`NOT_PERFORMED` for a complete map and for an incomplete map. `MAP_COMPLETE`
means the frozen item list was accounted for. It is not a compliance judgment,
a study-quality score, or a licence to omit an item by leaving it out.
CONSORT 2010 and PRISMA 2009 are refused because this tool does not carry
those superseded checklists.
