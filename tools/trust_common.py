"""Bounded JSON and portable identities for offline trust evidence (stdlib only)."""
import hashlib
import json
import math
import os
import pathlib
import re
import stat

MAX_JSON_BYTES = 2 * 1024 * 1024


class ValidationError(ValueError):
    """Input did not satisfy the bounded evidence contract."""


def text(value, label):
    if not isinstance(value, str) or not value.strip() or len(value) > 4096:
        raise ValidationError(label + ": expected nonempty bounded string")
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValidationError(label + ": control character")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise ValidationError(label + ": invalid Unicode") from exc
    return value


def object_fields(value, required, optional, label):
    if not isinstance(value, dict):
        raise ValidationError(label + ": expected object")
    if not set(required) <= value.keys() or value.keys() - set(required) - set(optional):
        raise ValidationError(label + ": missing or unknown fields")
    return value


def digest(value, label, length=64):
    if not isinstance(value, str) or not re.fullmatch("[0-9a-f]{" + str(length) + "}", value):
        raise ValidationError(label + ": expected lowercase immutable hex digest")
    return value


def portable_path(value, label):
    text(value, label)
    parts = value.split("/")
    reserved = {"con", "prn", "aux", "nul"} | {"com" + str(i) for i in range(1, 10)} | {"lpt" + str(i) for i in range(1, 10)}
    if any(not p or p in {".", ".."} or p.endswith((" ", ".")) or
           p.split(".")[0].casefold() in reserved or
           any(c in p for c in '\\:*?"<>|') for p in parts):
        raise ValidationError(label + ": expected portable repository-relative path")
    return value


def repository(value, label="repository"):
    text(value, label)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*/(?:[A-Za-z0-9][A-Za-z0-9_.-]*|\.[gG][iI][tT][hH][uU][bB])", value):
        raise ValidationError(label + ": expected GitHub owner/name")
    if any(p in {".", ".."} or p.endswith(".git") for p in value.split("/")):
        raise ValidationError(label + ": invalid repository identity")
    return value


def strict_json(data):
    if not isinstance(data, bytes) or len(data) > MAX_JSON_BYTES:
        raise ValidationError("JSON: expected bytes within 2 MiB limit")

    def pairs(items):
        result = {}
        for key, value in items:
            try:
                key.encode("utf-8")
            except UnicodeError as exc:
                raise ValidationError("JSON: invalid Unicode key") from exc
            if key in result:
                raise ValidationError("JSON: duplicate key")
            result[key] = value
        return result

    def constant(_):
        raise ValidationError("JSON: non-finite number")

    try:
        document = json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        if isinstance(exc, ValidationError):
            raise
        raise ValidationError("JSON: invalid UTF-8 or JSON") from exc
    stack = [(document, 0)]
    count = 0
    while stack:
        value, depth = stack.pop()
        count += 1
        if depth > 32 or count > 100000:
            raise ValidationError("JSON: nesting or item limit")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValidationError("JSON: non-finite number")
        if isinstance(value, str):
            try:
                value.encode("utf-8")
            except UnicodeError as exc:
                raise ValidationError("JSON: invalid Unicode") from exc
        if isinstance(value, dict):
            stack.extend((v, depth + 1) for v in value.values())
        elif isinstance(value, list):
            stack.extend((v, depth + 1) for v in value)
    return document


def read_json_bytes(path, max_bytes=MAX_JSON_BYTES):
    if type(max_bytes) is not int or not 0 < max_bytes <= MAX_JSON_BYTES:
        raise ValidationError("JSON input: invalid byte limit")
    path = pathlib.Path(path)
    try:
        for index, component in enumerate((path,) + tuple(path.parents)):
            info = component.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ValidationError("JSON input: links/reparse points refused")
            if (index == 0 and not stat.S_ISREG(info.st_mode)) or (index > 0 and not stat.S_ISDIR(info.st_mode)):
                raise ValidationError("JSON input: regular file and directory ancestors required")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise ValidationError("JSON input: regular file required")
            data = handle.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ValidationError("JSON input: byte limit")
    except OSError as exc:
        raise ValidationError("JSON input: unavailable file") from exc
    return data


def load_json_file(path, max_bytes=MAX_JSON_BYTES):
    return strict_json(read_json_bytes(path, max_bytes))


def canonical_sha256(document):
    try:
        raw = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise ValidationError("JSON: not canonicalizable") from exc
    return hashlib.sha256(raw).hexdigest()
