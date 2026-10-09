#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Bounded, offline CSV identifier and unit harmonization with byte readback."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import stat
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path, PurePosixPath

SCHEMA = "szl.measurement-harmonizer.v1"
HEX = re.compile(r"[0-9a-f]{64}\Z")
DECIMAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]{1,2})?\Z")
MAX_FILE = 1024 * 1024
MAX_ROWS = 1000
REPARSE_POINT = 0x400


class AuditError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


def _text(value: object, *, limit: int = 64) -> str:
    if not isinstance(value, str) or not value or len(value) > limit or value.strip() != value:
        raise AuditError("INVALID_TEXT")
    if any(ord(char) < 32 for char in value):
        raise AuditError("INVALID_TEXT")
    return value


def _decimal(value: object, *, positive: bool = False) -> Decimal:
    if not isinstance(value, str) or len(value) > 40 or not DECIMAL.fullmatch(value):
        raise AuditError("INVALID_DECIMAL")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise AuditError("INVALID_DECIMAL") from exc
    if not number.is_finite() or len(number.as_tuple().digits) > 24 or abs(number.as_tuple().exponent) > 20:
        raise AuditError("INVALID_DECIMAL")
    if positive and number <= 0:
        raise AuditError("NONPOSITIVE_SCALE")
    return number


def _unique_strings(value: object, *, minimum: int, maximum: int) -> list[str]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise AuditError("INVALID_ID_LIST")
    items = [_text(item) for item in value]
    if len(set(items)) != len(items):
        raise AuditError("DUPLICATE_ID")
    return items


def _validate(manifest: object) -> tuple[list[dict], list[str], str, dict[str, tuple[Decimal, Decimal]]]:
    if not isinstance(manifest, dict) or set(manifest) != {"schema", "sources", "expected_ids", "target_unit", "conversions"}:
        raise AuditError("INVALID_MANIFEST_FIELDS")
    if manifest["schema"] != SCHEMA:
        raise AuditError("INVALID_SCHEMA")
    expected = _unique_strings(manifest["expected_ids"], minimum=1, maximum=MAX_ROWS)
    target = _text(manifest["target_unit"], limit=32)
    sources = manifest["sources"]
    if not isinstance(sources, list) or not 2 <= len(sources) <= 4:
        raise AuditError("INVALID_SOURCES")
    ids: set[str] = set()
    paths: set[str] = set()
    units = {target}
    checked: list[dict] = []
    for source in sources:
        if not isinstance(source, dict) or set(source) != {"id", "path", "sha256", "id_column", "value_column", "unit", "id_map"}:
            raise AuditError("INVALID_SOURCE_FIELDS")
        sid = _text(source["id"])
        if sid in ids:
            raise AuditError("DUPLICATE_SOURCE")
        ids.add(sid)
        path = _text(source["path"], limit=512)
        if path in paths:
            raise AuditError("DUPLICATE_SOURCE_FILE")
        paths.add(path)
        digest = source["sha256"]
        if not isinstance(digest, str) or not HEX.fullmatch(digest):
            raise AuditError("INVALID_DIGEST")
        id_column = _text(source["id_column"])
        value_column = _text(source["value_column"])
        if id_column == value_column:
            raise AuditError("DUPLICATE_COLUMN")
        unit = _text(source["unit"], limit=32)
        units.add(unit)
        mapping = source["id_map"]
        if not isinstance(mapping, dict) or not mapping:
            raise AuditError("INVALID_ID_MAP")
        original = [_text(key) for key in mapping]
        canonical = [_text(value) for value in mapping.values()]
        if len(set(original)) != len(original) or any(value not in expected for value in canonical):
            raise AuditError("INVALID_ID_MAP")
        if len(set(canonical)) != len(canonical):
            raise AuditError("MANY_TO_ONE_ID_MAP")
        checked.append({**source, "id": sid, "path": path, "unit": unit})
    conversions = manifest["conversions"]
    if not isinstance(conversions, dict) or set(conversions) != units:
        raise AuditError("INCOMPLETE_CONVERSIONS")
    parsed: dict[str, tuple[Decimal, Decimal]] = {}
    for unit, conversion in conversions.items():
        if not isinstance(conversion, dict) or set(conversion) != {"scale", "offset"}:
            raise AuditError("INVALID_CONVERSION")
        parsed[unit] = (_decimal(conversion["scale"], positive=True), _decimal(conversion["offset"]))
    if parsed[target] != (Decimal(1), Decimal(0)):
        raise AuditError("TARGET_NOT_IDENTITY")
    return checked, expected, target, parsed


def _safe_file(root: Path, relative: str) -> Path:
    if "\\" in relative or ":" in relative:
        raise AuditError("UNSAFE_PATH")
    parts = PurePosixPath(relative).parts
    if not parts or any(part in {"", ".", ".."} for part in parts) or relative != "/".join(parts):
        raise AuditError("UNSAFE_PATH")
    current = root
    for part in parts:
        current = current / part
        try:
            mode = current.lstat()
        except FileNotFoundError as exc:
            raise AuditError("MISSING_FILE", relative) from exc
        if stat.S_ISLNK(mode.st_mode) or getattr(mode, "st_file_attributes", 0) & REPARSE_POINT:
            raise AuditError("UNSAFE_PATH")
    if not current.is_file() or not current.resolve().is_relative_to(root):
        raise AuditError("UNSAFE_PATH")
    return current


def _bytes(path: Path) -> bytes:
    before = path.stat()
    if before.st_size > MAX_FILE:
        raise AuditError("FILE_TOO_LARGE")
    with path.open("rb") as stream:
        content = stream.read(MAX_FILE + 1)
    if len(content) > MAX_FILE:
        raise AuditError("FILE_TOO_LARGE")
    after = path.stat()
    identity = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns)
    if identity(before) != identity(after) or len(content) != before.st_size:
        raise AuditError("FILE_CHANGED_DURING_READ")
    return content


def _rows(content: bytes, source: dict) -> list[tuple[int, str, str]]:
    try:
        stream = io.StringIO(content.decode("utf-8"), newline="")
        reader = csv.reader(stream, strict=True)
        header = next(reader)
        if header != [source["id_column"], source["value_column"]]:
            raise AuditError("CSV_HEADER_MISMATCH")
        rows = []
        for number, cells in enumerate(reader, start=2):
            if number > MAX_ROWS + 1:
                raise AuditError("ROW_LIMIT")
            if len(cells) != 2:
                raise AuditError("CSV_ROW_WIDTH", str(number))
            rows.append((number, cells[0], cells[1]))
        return rows
    except (UnicodeError, csv.Error, StopIteration) as exc:
        raise AuditError("INVALID_CSV") from exc


def harmonize(manifest: object, root: str | Path) -> dict:
    """Read selected files only; return no usable rows when an input is incomplete."""
    report = {"schema": SCHEMA + ".report", "status": "BLOCKED", "findings": [], "rows": [],
              "input_sha256": {}, "mapping_authority": "DECLARED_ONLY", "scientific_validity": "NOT_EVALUATED",
              "network": "NOT_USED", "execution": "NOT_RUN"}
    try:
        base = Path(root)
        if not base.is_dir() or base.is_symlink() or getattr(base.lstat(), "st_file_attributes", 0) & REPARSE_POINT:
            raise AuditError("UNSAFE_ROOT")
        base = base.resolve(strict=True)
        sources, expected, target, conversions = _validate(manifest)
        staged = []
        unavailable = False
        seen_locations: set[str] = set()
        seen_file_ids: set[tuple[int, int]] = set()
        for source in sources:
            sid = source["id"]
            try:
                path = _safe_file(base, source["path"])
                location = os.path.normcase(str(path.resolve(strict=True)))
                metadata = path.stat()
                file_id = (metadata.st_dev, metadata.st_ino)
                if location in seen_locations or (metadata.st_ino and file_id in seen_file_ids):
                    raise AuditError("DUPLICATE_SOURCE_FILE")
                seen_locations.add(location)
                if metadata.st_ino:
                    seen_file_ids.add(file_id)
                content = _bytes(path)
                digest = hashlib.sha256(content).hexdigest()
                report["input_sha256"][sid] = digest
                if digest != source["sha256"]:
                    raise AuditError("DIGEST_MISMATCH")
                rows = _rows(content, source)
                observed: set[str] = set()
                canonical_seen: set[str] = set()
                scale, offset = conversions[source["unit"]]
                for number, raw_id, raw_value in rows:
                    _text(raw_id)
                    if raw_id in observed:
                        raise AuditError("DUPLICATE_SOURCE_ROW", f"{sid}:{number}")
                    observed.add(raw_id)
                    if raw_id not in source["id_map"]:
                        raise AuditError("UNMAPPED_ID", f"{sid}:{number}")
                    canonical_id = source["id_map"][raw_id]
                    canonical_seen.add(canonical_id)
                    value = _decimal(raw_value)
                    with localcontext() as context:
                        context.prec = 50
                        normalized = value * scale + offset
                    staged.append({"source": sid, "row": number, "observed_id": raw_id,
                                   "canonical_id": canonical_id, "raw_value": raw_value,
                                   "raw_unit": source["unit"], "normalized_value": format(normalized, "f"),
                                   "target_unit": target})
                if observed != set(source["id_map"]):
                    raise AuditError("UNUSED_ID_MAP", sid)
                if canonical_seen != set(expected):
                    raise AuditError("MISSING_EXPECTED_ID", sid)
            except AuditError as exc:
                report["findings"].append({"source": sid, "code": exc.code, "detail": exc.detail})
                unavailable |= exc.code == "MISSING_FILE"
        if report["findings"]:
            report["status"] = "UNAVAILABLE" if unavailable and all(
                item["code"] == "MISSING_FILE" for item in report["findings"]) else "BLOCKED"
        else:
            report["status"] = "HARMONIZED"
            report["rows"] = sorted(staged, key=lambda row: (row["canonical_id"], row["source"]))
        return report
    except AuditError as exc:
        report["findings"].append({"source": None, "code": exc.code, "detail": exc.detail})
        return report


def read_manifest(path: str | Path) -> dict:
    selected = Path(path)
    if selected.stat().st_size > 64 * 1024:
        raise AuditError("MANIFEST_TOO_LARGE")

    def pairs(items: list[tuple[str, object]]) -> dict:
        result = {}
        for key, value in items:
            if key in result:
                raise AuditError("DUPLICATE_JSON_KEY")
            result[key] = value
        return result

    with selected.open("rb") as stream:
        content = stream.read(64 * 1024 + 1)
    if len(content) > 64 * 1024:
        raise AuditError("MANIFEST_TOO_LARGE")
    try:
        return json.loads(content.decode("utf-8"), object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(AuditError("NONFINITE_JSON")))
    except AuditError:
        raise
    except (RecursionError, ValueError) as exc:
        raise AuditError("INVALID_MANIFEST_JSON") from exc
