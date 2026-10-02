#!/usr/bin/env python3
"""Offline, fail-closed locator audit for Docling paper tables and figures."""

import argparse
import hashlib
import json
import math
import pathlib
import re
import sys

PDF_LIMIT = 128 * 1024 * 1024
DOCUMENT_LIMIT = 32 * 1024 * 1024
CLAIMS_LIMIT = 1024 * 1024
HEX64 = re.compile(r"^[0-9a-f]{64}$")
REF = re.compile(r"^#/(tables|pictures)/(0|[1-9][0-9]*)$")
TEXT_REF = re.compile(r"^#/texts/(0|[1-9][0-9]*)$")


def _no_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("DUPLICATE_JSON_KEY: " + key)
        result[key] = value
    return result


def _read_json(path, limit):
    path = pathlib.Path(path)
    if path.stat().st_size > limit:
        raise ValueError("INPUT_TOO_LARGE: " + path.name)
    data = path.read_bytes()
    obj = json.loads(data, object_pairs_hook=_no_duplicate_keys,
                     parse_constant=lambda value: (_ for _ in ()).throw(ValueError("NONFINITE_JSON")))
    if not isinstance(obj, dict):
        raise ValueError("JSON_ROOT_NOT_OBJECT: " + path.name)
    return obj, hashlib.sha256(data).hexdigest()


def _hash_pdf(path):
    path = pathlib.Path(path)
    if path.stat().st_size > PDF_LIMIT:
        raise ValueError("PDF_TOO_LARGE")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        if source.read(5) != b"%PDF-":
            raise ValueError("NOT_A_PDF")
        source.seek(0)
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha(value, field):
    if not isinstance(value, str) or HEX64.fullmatch(value) is None:
        raise ValueError("INVALID_SHA256: " + field)
    return value


def _locator(item):
    provenance = item.get("prov")
    if not isinstance(provenance, list) or not provenance:
        return None
    locators = []
    for entry in provenance:
        if not isinstance(entry, dict):
            return None
        page = entry.get("page_no")
        bbox = entry.get("bbox")
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            return None
        if not isinstance(bbox, dict):
            return None
        coords = [bbox.get(k) for k in ("l", "t", "r", "b")]
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in coords):
            return None
        origin = bbox.get("coord_origin", "TOPLEFT")
        if origin not in ("TOPLEFT", "BOTTOMLEFT"):
            return None
        if coords[0] >= coords[2] or (origin == "TOPLEFT" and coords[1] >= coords[3]) or (
            origin == "BOTTOMLEFT" and coords[1] <= coords[3]
        ):
            return None
        locators.append({"page": page, "bbox": {k: bbox[k] for k in ("l", "t", "r", "b")},
                         "coord_origin": origin})
    return locators


def _table_matches(item, quote):
    data = item.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("table_cells"), list):
        return None
    matches = []
    for number, cell in enumerate(data["table_cells"]):
        if not isinstance(cell, dict) or not isinstance(cell.get("text"), str):
            return None
        if quote == cell["text"]:
            matches.append({"cell_index": number,
                            "row": cell.get("start_row_offset_idx"),
                            "column": cell.get("start_col_offset_idx")})
    return matches


def _caption_matches(item, texts, quote):
    refs = item.get("captions")
    if not isinstance(refs, list) or not isinstance(texts, list):
        return None
    matches = []
    for reference in refs:
        if not isinstance(reference, dict):
            return None
        value = reference.get("$ref", reference.get("cref"))
        match = TEXT_REF.fullmatch(value) if isinstance(value, str) else None
        if match is None or int(match.group(1)) >= len(texts):
            return None
        caption = texts[int(match.group(1))]
        if not isinstance(caption, dict) or not isinstance(caption.get("text"), str):
            return None
        if quote == caption["text"]:
            matches.append({"caption_ref": value, "locators": _locator(caption)})
    return matches


def audit(pdf_path, document_path, claims_path):
    pdf_hash = _hash_pdf(pdf_path)
    document, document_hash = _read_json(document_path, DOCUMENT_LIMIT)
    manifest, manifest_hash = _read_json(claims_path, CLAIMS_LIMIT)
    if manifest.get("schema") != "szl.paper-evidence-claims.v1":
        raise ValueError("UNSUPPORTED_CLAIMS_SCHEMA")
    expected_pdf = _sha(manifest.get("pdf_sha256"), "pdf_sha256")
    expected_document = _sha(manifest.get("document_json_sha256"), "document_json_sha256")
    extraction = manifest.get("extraction")
    if not isinstance(extraction, dict) or any(
        not isinstance(extraction.get(k), str) or not extraction[k].strip() or len(extraction[k]) > 128
        for k in ("tool", "version", "pipeline", "ocr_engine")
    ):
        raise ValueError("EXTRACTION_METADATA_MISSING")
    claims = manifest.get("claims")
    if not isinstance(claims, list) or not claims or len(claims) > 1000:
        raise ValueError("INVALID_CLAIM_COUNT")
    pdf_bound = pdf_hash == expected_pdf
    document_bound = document_hash == expected_document
    seen = set()
    findings = []
    for claim in claims:
        if not isinstance(claim, dict):
            raise ValueError("CLAIM_NOT_OBJECT")
        claim_id, ref, quote = (claim.get(k) for k in ("id", "ref", "quote"))
        if not isinstance(claim_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", claim_id):
            raise ValueError("INVALID_CLAIM_ID")
        if claim_id in seen:
            raise ValueError("DUPLICATE_CLAIM_ID")
        seen.add(claim_id)
        match = REF.fullmatch(ref) if isinstance(ref, str) else None
        if match is None or not isinstance(quote, str) or not quote.strip() or len(quote) > 2048:
            raise ValueError("INVALID_CLAIM_REF_OR_QUOTE")
        finding = {"id": claim_id, "ref": ref, "quote_sha256": hashlib.sha256(quote.encode("utf-8")).hexdigest(),
                   "status": "UNRESOLVED", "issues": [], "locators": [],
                   "caption_locators": [], "match": None}
        if not pdf_bound:
            finding["issues"].append("PDF_DIGEST_MISMATCH")
        if not document_bound:
            finding["issues"].append("EXTRACTION_DIGEST_MISMATCH")
        kind, index = match.group(1), int(match.group(2))
        items = document.get(kind)
        if not isinstance(items, list) or index >= len(items) or not isinstance(items[index], dict):
            finding["issues"].append("SOURCE_ITEM_MISSING")
        else:
            item = items[index]
            locators = _locator(item)
            if locators is None:
                finding["issues"].append("PAGE_REGION_MISSING")
            else:
                finding["locators"] = locators
            matches = (_table_matches(item, quote) if kind == "tables"
                       else _caption_matches(item, document.get("texts"), quote))
            if matches is None:
                finding["issues"].append("EXTRACTION_STRUCTURE_UNSUPPORTED")
            elif not matches:
                finding["issues"].append("QUOTE_NOT_LOCATED")
            elif len(matches) != 1:
                finding["issues"].append("AMBIGUOUS_QUOTE")
            else:
                if kind == "pictures":
                    caption_match = matches[0]
                    finding["match"] = {"caption_ref": caption_match["caption_ref"]}
                    caption_locators = caption_match["locators"]
                    if caption_locators is None:
                        finding["issues"].append("CAPTION_REGION_MISSING")
                    else:
                        finding["caption_locators"] = caption_locators
                        if locators is not None and not {
                            entry["page"] for entry in caption_locators
                        }.issubset({entry["page"] for entry in locators}):
                            finding["issues"].append("CAPTION_PICTURE_PAGE_MISMATCH")
                else:
                    finding["match"] = matches[0]
            if not finding["issues"]:
                finding["status"] = ("TABLE_TEXT_LOCATED_REVIEW_REQUIRED" if kind == "tables"
                                     else "FIGURE_CAPTION_LOCATED_VISUAL_REVIEW_REQUIRED")
        findings.append(finding)
    return {"schema": "szl.paper-evidence-audit.v1", "status": (
        "UNRESOLVED" if any(f["status"] == "UNRESOLVED" for f in findings) else "REVIEW_REQUIRED"),
        "pdf_sha256": pdf_hash, "document_json_sha256": document_hash,
        "claims_manifest_sha256": manifest_hash, "pdf_bound": pdf_bound,
        "document_bound": document_bound, "extraction_declared": extraction,
        "scientific_truth_verified": False, "clinical_use_authorized": False,
        "findings": findings}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=pathlib.Path, required=True)
    parser.add_argument("--document-json", type=pathlib.Path, required=True)
    parser.add_argument("--claims", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path)
    args = parser.parse_args(argv)
    try:
        report = audit(args.pdf, args.document_json, args.claims)
        encoded = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        if args.output is None:
            sys.stdout.write(encoded)
        else:
            with args.output.open("x", encoding="utf-8", newline="\n") as target:
                target.write(encoded)
        return 2 if report["status"] == "UNRESOLVED" else 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print("paper-evidence-audit: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
