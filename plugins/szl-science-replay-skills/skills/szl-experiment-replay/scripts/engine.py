#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Bounded, same-host replay of one built-in CSV column mean operation."""

import csv
import hashlib
import io
import json
import os
import pathlib
import re
import stat
from decimal import Decimal, localcontext

SCHEMA = "szl.experiment-replay.pin.v1"
RECEIPT_SCHEMA = "szl.experiment-replay.receipt.v1"
REFERENCE_SCHEMA = "szl.experiment-replay.reference.v1"
DECLARATION_SCHEMA = "szl.experiment-replay.declaration.v1"
OPERATION = "csv_column_mean_v1"
MAX_CSV = 256 * 1024
MAX_REFERENCE = 4096
MAX_JSON = 8192
MAX_ENGINE = 128 * 1024
MAX_ROWS = 10000
MAX_COLUMNS = 64
DECIMAL = re.compile(r"-?(?:0|[1-9][0-9]{0,17})(?:\.[0-9]{1,18})?\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
FORBIDDEN = re.compile(r"(^|[-_.])(passwords?|secrets?|credentials?|api[-_]?key|access[-_]?token)([-_.]|$)", re.I)
DEVICE = re.compile(r"(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?\Z", re.I)


def _digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _pairs_unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def _read_json(raw):
    return json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs_unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite JSON")))


def _is_reparse(info):
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _root(root):
    path = pathlib.Path(root).absolute()
    for part in (path, *path.parents):
        info = part.lstat()
        if _is_reparse(info):
            raise ValueError("root contains a symlink or reparse point")
    if not path.is_dir():
        raise ValueError("root is not a directory")
    return path


def _relative(relative):
    if not isinstance(relative, str) or not 1 <= len(relative) <= 240 or "\\" in relative or ":" in relative or any(ord(c) < 32 for c in relative):
        raise ValueError("unsafe relative path")
    pure = pathlib.PurePosixPath(relative)
    if pure.is_absolute() or str(pure) != relative or any(part in ("", ".", "..") for part in pure.parts):
        raise ValueError("noncanonical relative path")
    for part in pure.parts:
        if part.endswith((".", " ")) or DEVICE.fullmatch(part) or part.lower() in (".git", ".ssh", ".aws", ".env", ".codex", ".netrc", ".npmrc") or FORBIDDEN.search(part):
            raise ValueError("unsafe path component")
    return pure.parts


def _locate(root, relative, *, output=False):
    root = _root(root)
    parts = _relative(relative)
    path = root
    for index, part in enumerate(parts):
        path = path / part
        if output and index == len(parts) - 1:
            try:
                path.lstat()
            except FileNotFoundError:
                pass
            else:
                raise FileExistsError("output already exists")
            break
        info = path.lstat()
        if _is_reparse(info):
            raise ValueError("path contains a symlink or reparse point")
        if index < len(parts) - 1 and not stat.S_ISDIR(info.st_mode):
            raise ValueError("path parent is not a directory")
        if index == len(parts) - 1 and not stat.S_ISREG(info.st_mode):
            raise ValueError("input is not a regular file")
    return path


def read_file(root, relative, limit):
    """Read only a regular bounded file, checking the same path before and after."""
    path = _locate(root, relative)
    before = path.lstat()
    if before.st_size > limit:
        raise ValueError("input exceeds byte limit")
    with path.open("rb") as source:
        opened = os.fstat(source.fileno())
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise ValueError("input changed during opening")
        raw = source.read(limit + 1)
        finished = os.fstat(source.fileno())
    after = path.lstat()
    if _is_reparse(after) or not stat.S_ISREG(after.st_mode):
        raise ValueError("input changed during reading")
    identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
    if len(raw) > limit or identity(before) != identity(opened) or identity(opened) != identity(finished) or identity(finished) != identity(after):
        raise ValueError("input changed or exceeded byte limit")
    return raw


def write_new_json(root, relative, value):
    path = _locate(root, relative, output=True)
    raw = (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    with path.open("xb") as target:
        target.write(raw)
        target.flush()
        os.fsync(target.fileno())
    return path


def _number(value):
    if not isinstance(value, str) or not DECIMAL.fullmatch(value):
        raise ValueError("number must be a bounded plain decimal string")
    return Decimal(value)


def _reference(raw):
    value = _read_json(raw)
    if not isinstance(value, dict) or set(value) != {"schema", "value"} or value["schema"] != REFERENCE_SCHEMA:
        raise ValueError("invalid reference result")
    return _number(value["value"])


def _column(column):
    if not isinstance(column, str) or not 1 <= len(column) <= 128 or any(ord(c) < 32 for c in column):
        raise ValueError("invalid column name")
    return column


def _sum_column(raw, column):
    column = _column(column)
    text = raw.decode("utf-8")
    old_limit = csv.field_size_limit()
    csv.field_size_limit(1024)
    try:
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        header = next(reader, None)
        if not header or len(header) > MAX_COLUMNS or len(set(header)) != len(header) or any(not name or len(name) > 128 or any(ord(c) < 32 for c in name) for name in header):
            raise ValueError("invalid CSV header")
        if column not in header:
            raise ValueError("column absent from CSV")
        index = header.index(column)
        count = 0
        total = Decimal(0)
        with localcontext() as context:
            context.prec = 80
            for row in reader:
                count += 1
                if count > MAX_ROWS or len(row) != len(header):
                    raise ValueError("CSV row limit or width mismatch")
                total += _number(row[index])
        if count == 0:
            raise ValueError("CSV has no data rows")
        return total, count
    except csv.Error as error:
        raise ValueError("invalid CSV") from error
    finally:
        csv.field_size_limit(old_limit)


def _file_pin(root, relative, limit):
    raw = read_file(root, relative, limit)
    return {"path": relative, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}, raw


def _engine_hash():
    source = pathlib.Path(__file__)
    before = source.lstat()
    if _is_reparse(before) or not stat.S_ISREG(before.st_mode):
        raise ValueError("engine is not a regular file")
    if before.st_size > MAX_ENGINE:
        raise ValueError("engine exceeds byte limit")
    with source.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise ValueError("engine changed during opening")
        raw = stream.read(MAX_ENGINE + 1)
        finished = os.fstat(stream.fileno())
    after = source.lstat()
    identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
    if (_is_reparse(after) or not stat.S_ISREG(after.st_mode) or len(raw) > MAX_ENGINE
            or identity(before) != identity(opened) or identity(opened) != identity(finished)
            or identity(finished) != identity(after)):
        raise ValueError("engine changed or exceeds byte limit")
    return hashlib.sha256(raw).hexdigest()


def prepare(root, declaration):
    if not isinstance(declaration, dict) or set(declaration) != {"schema", "operation", "input_path", "reference_path", "column", "absolute_tolerance"}:
        raise ValueError("invalid declaration fields")
    if declaration["schema"] != DECLARATION_SCHEMA or declaration["operation"] != OPERATION:
        raise ValueError("unsupported declaration or operation")
    column = _column(declaration["column"])
    tolerance = _number(declaration["absolute_tolerance"])
    if tolerance < 0:
        raise ValueError("negative tolerance")
    input_pin, input_raw = _file_pin(root, declaration["input_path"], MAX_CSV)
    reference_pin, reference_raw = _file_pin(root, declaration["reference_path"], MAX_REFERENCE)
    if input_pin["path"] == reference_pin["path"]:
        raise ValueError("input and reference must be separate files")
    _sum_column(input_raw, column)
    _reference(reference_raw)
    pin = {"schema": SCHEMA, "operation": OPERATION, "input": input_pin,
           "reference": reference_pin, "column": column,
           "absolute_tolerance": declaration["absolute_tolerance"],
           "engine_sha256": _engine_hash()}
    pin["pin_sha256"] = _digest(pin)
    return pin


def _validate_pin(pin):
    if not isinstance(pin, dict) or set(pin) != {"schema", "operation", "input", "reference", "column", "absolute_tolerance", "engine_sha256", "pin_sha256"}:
        raise ValueError("invalid pin fields")
    if pin["schema"] != SCHEMA or pin["operation"] != OPERATION:
        raise ValueError("unsupported pin")
    if not isinstance(pin["pin_sha256"], str) or not SHA256.fullmatch(pin["pin_sha256"]) or pin["pin_sha256"] != _digest({key: value for key, value in pin.items() if key != "pin_sha256"}):
        raise ValueError("pin digest mismatch")
    if not isinstance(pin["engine_sha256"], str) or not SHA256.fullmatch(pin["engine_sha256"]):
        raise ValueError("invalid engine digest")
    for key in ("input", "reference"):
        value = pin[key]
        if not isinstance(value, dict) or set(value) != {"path", "bytes", "sha256"}:
            raise ValueError("invalid file pin")
        _relative(value["path"])
        if type(value["bytes"]) is not int or not 0 <= value["bytes"] <= (MAX_CSV if key == "input" else MAX_REFERENCE):
            raise ValueError("invalid file byte count")
        if not isinstance(value["sha256"], str) or not SHA256.fullmatch(value["sha256"]):
            raise ValueError("invalid file digest")
    if pin["input"]["path"] == pin["reference"]["path"]:
        raise ValueError("file pins overlap")
    _column(pin["column"])
    if _number(pin["absolute_tolerance"]) < 0:
        raise ValueError("negative tolerance")


def _receipt(pin, status, reason, execution="NOT_RUN", **details):
    pin_hash = pin.get("pin_sha256") if isinstance(pin, dict) else None
    if not isinstance(pin_hash, str) or not SHA256.fullmatch(pin_hash):
        pin_hash = None
    value = {"schema": RECEIPT_SCHEMA, "status": status, "reason": reason,
             "execution": execution, "pin_sha256": pin_hash,
             "evidence_scope": "SAME_HOST_LOCAL", "signed": False,
             "independent_witness": False, "scientific_claims_verified": False}
    value.update(details)
    value["receipt_sha256"] = _digest(value)
    return value


def replay(root, pin):
    try:
        _validate_pin(pin)
    except (ValueError, TypeError, OverflowError, RecursionError):
        return _receipt(None, "REFUSED", "INVALID_PIN")
    try:
        engine_hash = _engine_hash()
    except (OSError, ValueError):
        return _receipt(pin, "INCOMPLETE", "ENGINE_UNREADABLE")
    if engine_hash != pin["engine_sha256"]:
        return _receipt(pin, "INCOMPLETE", "ENGINE_CHANGED", engine_sha256_observed=engine_hash)
    observed = {}
    for role, limit in (("input", MAX_CSV), ("reference", MAX_REFERENCE)):
        try:
            raw = read_file(root, pin[role]["path"], limit)
        except FileNotFoundError:
            return _receipt(pin, "INCOMPLETE", role.upper() + "_MISSING", observed_hashes=observed)
        except (OSError, ValueError):
            return _receipt(pin, "INCOMPLETE", role.upper() + "_UNSAFE_OR_UNREADABLE", observed_hashes=observed)
        actual_hash = hashlib.sha256(raw).hexdigest()
        observed[role] = actual_hash
        if actual_hash != pin[role]["sha256"] or len(raw) != pin[role]["bytes"]:
            return _receipt(pin, "INCOMPLETE", role.upper() + "_CHANGED", observed_hashes=observed)
        if role == "input":
            input_raw = raw
        else:
            reference_raw = raw
    try:
        total, count = _sum_column(input_raw, pin["column"])
        expected = _reference(reference_raw)
        tolerance = _number(pin["absolute_tolerance"])
        with localcontext() as context:
            context.prec = 80
            difference_total = abs(total - expected * count)
            within = difference_total <= tolerance * count
            mean = total / count
            error = difference_total / count
    except (ValueError, UnicodeError, OverflowError, csv.Error):
        return _receipt(pin, "REFUSED", "PINNED_CONTENT_INVALID", observed_hashes=observed)
    return _receipt(pin, "MATCH" if within else "DIVERGED", "WITHIN_TOLERANCE" if within else "OUTSIDE_TOLERANCE",
                    execution="COMPLETED", observed_hashes=observed, row_count=count,
                    observed_mean=format(mean, "f"), expected_mean=format(expected, "f"),
                    absolute_error=format(error, "f"), absolute_tolerance=pin["absolute_tolerance"])
