---
name: szl-paper-evidence-audit
description: Audits claims taken from scientific PDF tables and figures against a pinned local PDF and Docling JSON, retaining page and bounding-box locators and requiring visual review. Use when a paper has old scans, complex tables, figure values, or an extracted number that must be checked before citation.
license: Apache-2.0
---

# Paper table and figure evidence audit

Use this after extracting a paper, before quoting its tables or figures. It complements a PDF/OCR skill; it does **not** perform OCR, inspect image pixels, prove a scientific claim, or certify a clinical result. A matching extracted string is still a review request, never verified truth.

## Workflow

1. Use a paper you may lawfully access. Keep it local. If the PDF is scanned or the layout is complex, use an installed, locally configured document converter such as Docling to produce DoclingDocument JSON. Record the converter, version, pipeline, and OCR engine. Do not silently install or download models, upload the paper, or send it to a hosted service.
2. Independently inspect the PDF page/crop for every table value or figure claim. Do not infer a plotted value from a caption or extract a clinical result without qualified human review. Record units, row/column headers, uncertainty, footnotes, and whether the source is a scan.
3. Calculate SHA-256 of the original PDF and extraction JSON. Create a claim manifest using the exact format in `assets/example-claims.json`. Each claim names one `#/tables/N` or `#/pictures/N` reference. Its quote must equal the complete extracted text of one table cell or one linked caption text item, not an excerpt. Pin both input hashes; a mismatch fails closed.
4. Run `scripts/audit.py` with the original PDF, Docling JSON, and manifest. Review all `UNRESOLVED` and `REVIEW_REQUIRED` records against the actual page. For figures, a match locates the linked caption and picture; visual values remain unverified.
5. Carry the output hashes and unresolved findings into a project evidence ledger or the companion `szl-artifact-lineage` skill. Never turn the audit's unsigned local record into a publication, model-evaluation, or clinical-use approval.

```bash
python -B scripts/audit.py --pdf paper.pdf --document-json paper.docling.json --claims claims.json --output evidence.json
```

`--output` creates a new file and refuses overwrite. Without it, the command prints JSON. Exit 0 means the manifest was structurally audited and every expected string was located; every claim still requires review. Exit 2 means at least one binding or locator is unresolved; exit 1 means invalid input. The script is offline, Python 3.9+ standard library, and does not need credentials. It reads only the three explicitly selected local files. Input limits: 128 MiB PDF, 32 MiB Docling JSON, 1 MiB manifest, and 1,000 claims.

For old scans and complex table layouts, inspect raw Docling JSON as well as any Markdown rendering: a converter can omit content, normalize text, or misorder reading. Regions must have positive width and height in their declared coordinate origin (Docling's default is top-left). Figure-caption findings require separate picture and caption regions on the same PDF page. A quote spanning multiple caption text items cannot be matched, and a caption longer than the 2,048-character quote limit is invalid. The two input hashes bind selected bytes, but do not prove that the JSON was actually extracted from that PDF. Page number and bounding box locate evidence but do not validate OCR, units, or figure interpretation. No result is approved automatically.

Outside services: none in the bundled script. Optional Docling installation/conversion may download model assets depending on the user's configuration; get approval for those resources and record versions. Credentials: none for the bundled script. Source format references: Docling's [document model](https://docling-project.github.io/docling/reference/docling_document/) and [converter](https://docling-project.github.io/docling/reference/document_converter/); all code here is original.
