"""Bounded static metadata helpers for the isolated auditor proposal.

The frontmatter reader deliberately supports a small YAML subset. Unsupported
syntax is an error, never an approximate successful parse. License recognition
describes evidence; it does not approve licenses, biosafety, or installation.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import PurePosixPath
from typing import Any

MAX_LICENSE_BYTES = 2_000_000
_KEY = re.compile(r"^([A-Za-z0-9_-]+):(?:\s+(.*)|\s*)$")
_INTEGER = re.compile(r"^[+-]?[0-9]+$")
_FLOAT = re.compile(r"^[+-]?(?:[0-9]+\.[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$|^[+-]?[0-9]+[eE][+-]?[0-9]+$")


def _without_comment(value: str) -> str:
    quote = ""
    escaped = False
    index = 0
    while index < len(value):
        char = value[index]
        if quote == '"' and escaped:
            escaped = False
        elif quote == '"' and char == "\\":
            escaped = True
        elif quote:
            if char == quote:
                if quote == "'" and index + 1 < len(value) and value[index + 1] == "'":
                    index += 1
                else:
                    quote = ""
        elif char in {"'", '"'} and (not value[:index].strip() or value[:index].rstrip().endswith(("[", ","))):
            quote = char
        elif char == "#" and (index == 0 or value[index - 1].isspace()):
            return value[:index].rstrip()
        index += 1
    return value.strip()


def _list_parts(value: str) -> list[str]:
    parts: list[str] = []
    start = 0
    quote = ""
    escaped = False
    index = 0
    while index < len(value):
        char = value[index]
        if quote == '"' and escaped:
            escaped = False
        elif quote == '"' and char == "\\":
            escaped = True
        elif quote:
            if char == quote:
                if quote == "'" and index + 1 < len(value) and value[index + 1] == "'":
                    index += 1
                else:
                    quote = ""
        elif char in {"'", '"'} and not value[start:index].strip():
            quote = char
        elif char == ",":
            parts.append(value[start:index].strip())
            start = index + 1
        elif char in "[]{}":
            raise ValueError("nested-flow-value")
        index += 1
    if quote:
        raise ValueError("unterminated-quote")
    parts.append(value[start:].strip())
    if any(not part for part in parts):
        raise ValueError("empty-flow-list-item")
    return parts


def _scalar(raw: str, allow_list: bool = True) -> Any:
    value = _without_comment(raw).strip()
    if not value or value.lower() in {"null", "~"}:
        return None
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if value.startswith('"'):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError) as error:
            raise ValueError("unsupported-double-quoted-scalar") from error
        if not isinstance(parsed, str):
            raise ValueError("invalid-quoted-scalar")
        return parsed
    if value.startswith("'"):
        if not value.endswith("'") or len(value) < 2:
            raise ValueError("unterminated-quote")
        inner = value[1:-1]
        if "'" in inner.replace("''", ""):
            raise ValueError("invalid-single-quoted-scalar")
        return inner.replace("''", "'")
    if value.startswith("["):
        if not allow_list or not value.endswith("]"):
            raise ValueError("invalid-flow-list")
        inner = value[1:-1].strip()
        return [] if not inner else [_scalar(item, False) for item in _list_parts(inner)]
    if value[0] in "{}]|>&*!`@%," or re.match(r"^[-?:](?:\s|$)", value) or re.search(r":(?:\s|$)", value):
        raise ValueError("block-map-anchor-tag-or-reserved-syntax")
    if value.lower() in {".nan", ".inf", "-.inf", "+.inf"}:
        raise ValueError("nonfinite-number")
    if _INTEGER.fullmatch(value):
        return int(value)
    if _FLOAT.fullmatch(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("nonfinite-number")
        return number
    return value


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str, list[str]]:
    """Read exact delimiters, scalar values and simple lists; retain value types.

    Nested mappings, block scalars, aliases, tags and advanced YAML escapes are
    unsupported. Every such case produces an ``unsupported-yaml`` problem.
    """
    normalized = text.replace("\r\n", "\n")
    lines = normalized.split("\n")
    if not lines or lines[0] != "---":
        return {}, text, ["missing-yaml-frontmatter"]
    closing = next((index for index in range(1, len(lines)) if lines[index] == "---"), None)
    if closing is None:
        return {}, text, ["unterminated-yaml-frontmatter"]
    metadata: dict[str, Any] = {}
    problems: list[str] = []
    active_list: str | None = None
    for line_number, line in enumerate(lines[1:closing], 2):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        list_item = re.fullmatch(r"\s+-\s+(.*)", line)
        if list_item and active_list is not None:
            try:
                item = _scalar(list_item.group(1), False)
                if metadata[active_list] is None:
                    metadata[active_list] = []
                metadata[active_list].append(item)
            except ValueError as error:
                problems.append(f"unsupported-yaml:{line_number}:{error}")
            continue
        active_list = None
        match = _KEY.fullmatch(line)
        if match is None:
            problems.append(f"unsupported-yaml:{line_number}:nested-or-unrecognized-line")
            continue
        key, raw = match.groups()
        if key in metadata:
            problems.append(f"duplicate-yaml-key:{key}:{line_number}")
            continue
        try:
            metadata[key] = _scalar(raw or "")
            if metadata[key] is None:
                active_list = key
        except ValueError as error:
            metadata[key] = None
            problems.append(f"unsupported-yaml:{line_number}:{error}")
    return metadata, "\n".join(lines[closing + 1:]).lstrip("\n"), problems


_LICENSE_NAMES = {"license", "license.md", "license.txt", "licence", "licence.md", "licence.txt", "copying", "copying.md", "copying.txt"}
_LICENSE_PATTERNS = [
    ("Apache-2.0", re.compile(r"Apache License,?\s+Version 2\.0", re.I)),
    ("MIT", re.compile(r"MIT License\b|Permission is hereby granted, free of charge", re.I)),
    ("MPL-2.0", re.compile(r"Mozilla Public License,?\s*(?:Version|v)?\s*2\.0", re.I)),
    ("GPL-3.0", re.compile(r"GNU GENERAL PUBLIC LICENSE\s+Version 3", re.I)),
    ("AGPL-3.0", re.compile(r"GNU AFFERO GENERAL PUBLIC LICENSE", re.I)),
    ("CC-BY-4.0", re.compile(r"Creative Commons Attribution 4\.0", re.I)),
    ("CC-BY-NC-4.0", re.compile(r"Attribution-NonCommercial 4\.0", re.I)),
    ("ISC", re.compile(r"Permission to use, copy, modify, and/or distribute", re.I)),
    ("CC0-1.0", re.compile(r"CC0 1\.0 Universal|Creative Commons Zero v1\.0", re.I)),
    ("Unlicense", re.compile(r"free and unencumbered software released into the public domain", re.I)),
]
_KNOWN_IDS = {item[0] for item in _LICENSE_PATTERNS} | {
    "BSD-2-Clause", "BSD-3-Clause", "GPL-2.0-only", "GPL-2.0-or-later",
    "GPL-3.0-only", "GPL-3.0-or-later", "AGPL-3.0-only", "AGPL-3.0-or-later",
    "LGPL-2.1-only", "LGPL-2.1-or-later", "LGPL-3.0-only", "LGPL-3.0-or-later",
    "CC-BY-SA-4.0", "CC-BY-NC-SA-4.0", "CC-BY-NC-ND-4.0", "CC-BY-ND-4.0",
}
# A bounded, deliberately incomplete recognition vocabulary, not a rights policy.
_KNOWN_EXCEPTIONS = {"Classpath-exception-2.0", "LLVM-exception", "GCC-exception-3.1"}
MAX_EVIDENCE_FILES = 10_000
MAX_EVIDENCE_DEPTH = 32
MAX_SPDX_HEADERS = 128
_CUSTOM_TERMS = re.compile(
    r"\b(?:non[- ]commercial|research use only|no redistribution|proprietary|"
    r"custom licen[cs]e|additional restrictions|unknown licen[cs]e)\b", re.I,
)
_SCOPED_DECLARATION = re.compile(
    r"\b(?:non[- ]commercial|proprietary|api|unknown|commercial use|dataset|"
    r"data only|code only|except|excluding|portions|terms|see|licensed under)\b", re.I,
)
_CONTENT_SCOPE_NOUN = r"(?:files?|directories|folders?|skills?|plugins?|tools?|scripts?|references?|assets?|code|documentation|content|datasets?|data)"
# Content-scope observations must name content or separate terms. Canonical
# Apache patent claims, contribution definitions and notice-attribution clauses
# also use applies-only/excluding language; those are not content exclusions.
_SCOPE_CLAUSES = re.compile(
    r"\b(?:this licen[cs]e covers"
    r"|(?:this |the )?licen[cs]e applies only\s+to\s+(?:the\s+)?" + _CONTENT_SCOPE_NOUN +
    r"|each skill.{0,100}own licen[cs]e"
    r"|(?:excludes?|excluding|except for)\s+(?:the\s+)?" + _CONTENT_SCOPE_NOUN +
    r"|portions[^\r\n]{0,80}\b(?:separate|different|own)\s+licen[cs]e)\b",
    re.I | re.S,
)
# These are term-presence skeletons, not legal validity or exact canonical-text
# verification. A heading/SPDX line alone can identify a label but cannot meet
# the evidence-identification contract. Other observed IDs remain review-held.
_TERM_SKELETONS = {
    "MIT": [r"Permission is hereby granted, free of charge", r"without restriction", r"subject to the following conditions", r"copyright notice", r"permission notice", r"software is provided\s+[\"']as is[\"']", r"warranty", r"liability"],
    "Apache-2.0": [r"TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION", r"1\.\s*Definitions", r"2\.\s*Grant of Copyright License", r"3\.\s*Grant of Patent License", r"4\.\s*Redistribution", r"5\.\s*Submission of Contributions", r"6\.\s*Trademarks", r"7\.\s*Disclaimer of Warranty", r"8\.\s*Limitation of Liability", r"9\.\s*Accepting Warranty or Additional Liability", r"END OF TERMS AND CONDITIONS"],
}


def _valid_relative_path(value: Any) -> bool:
    if not isinstance(value, str) or not value or any(char in value for char in "\\\x00:"):
        return False
    if any(part in {"", ".", ".."} for part in value.split("/")):
        return False
    if len(value.split("/")) > MAX_EVIDENCE_DEPTH:
        return False
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        return False
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError:
        return False
    return True


def _spdx_expression(value: str) -> dict[str, Any]:
    """Observe bounded SPDX syntax; no expression grants approval or permission.

    AND binds more tightly than OR. WITH applies only to a single license ID.
    LicenseRef/DocumentRef and IDs outside this explicit vocabulary are retained
    as unsupported observations, never silently accepted as standard licenses.
    """
    observation: dict[str, Any] = {"expression": "UNSUPPORTED_EXPRESSION_REDACTED", "expression_sha256": hashlib.sha256(value.encode("utf-8", errors="surrogatepass")).hexdigest(), "normalized": "", "identifiers": [], "exceptions": [], "problem": ""}
    if len(value) > 4096:
        observation["problem"] = "oversized-spdx-expression"
        return observation
    token_pattern = r"\(|\)|[A-Za-z0-9][A-Za-z0-9.+:_-]*"
    tokens = re.findall(token_pattern, value)
    if not tokens or len(tokens) > 256 or re.sub(token_pattern + r"|\s+", "", value):
        observation["problem"] = "invalid-spdx-expression"
        return observation
    index = 0
    ids: set[str] = set()
    exceptions: set[str] = set()

    def primary(depth: int = 0) -> None:
        nonlocal index
        if depth > MAX_EVIDENCE_DEPTH or index >= len(tokens):
            raise ValueError("invalid-spdx-expression")
        token = tokens[index]
        index += 1
        if token == "(":
            disjunction(depth + 1)
            if index >= len(tokens) or tokens[index] != ")":
                raise ValueError("invalid-spdx-expression")
            index += 1
            return
        if token in {"AND", "OR", "WITH", ")"}:
            raise ValueError("invalid-spdx-expression")
        ids.add(token)
        if index < len(tokens) and tokens[index] == "WITH":
            index += 1
            if index >= len(tokens) or tokens[index] in {"(", ")", "AND", "OR", "WITH"}:
                raise ValueError("invalid-spdx-expression")
            exceptions.add(tokens[index])
            index += 1

    def conjunction(depth: int) -> None:
        nonlocal index
        primary(depth)
        while index < len(tokens) and tokens[index] == "AND":
            index += 1
            primary(depth)

    def disjunction(depth: int) -> None:
        nonlocal index
        conjunction(depth)
        while index < len(tokens) and tokens[index] == "OR":
            index += 1
            conjunction(depth)

    try:
        disjunction(0)
        if index != len(tokens):
            raise ValueError("invalid-spdx-expression")
    except ValueError as error:
        observation["problem"] = str(error)
    observation["identifiers"] = sorted(ids & _KNOWN_IDS)
    observation["exceptions"] = sorted(exceptions & _KNOWN_EXCEPTIONS)
    observation["unsupported_identifier_sha256"] = sorted(hashlib.sha256(identifier.encode("utf-8")).hexdigest() for identifier in ids - _KNOWN_IDS)
    observation["unsupported_exception_sha256"] = sorted(hashlib.sha256(identifier.encode("utf-8")).hexdigest() for identifier in exceptions - _KNOWN_EXCEPTIONS)
    if not observation["problem"]:
        if not ids <= _KNOWN_IDS or not exceptions <= _KNOWN_EXCEPTIONS:
            observation["problem"] = "unsupported-spdx-identifier-or-exception"
        else:
            observation["expression"] = value
            observation["normalized"] = " ".join(tokens)
    return observation


def _spdx_headers(text: str) -> list[dict[str, Any]]:
    values: list[str] = []
    for match in re.finditer(r"SPDX-License-Identifier:\s*([^\r\n]+)", text, flags=re.I):
        if len(values) >= MAX_SPDX_HEADERS:
            return [{"expression": "REDACTED", "normalized": "", "identifiers": [], "exceptions": [], "problem": "spdx-header-count-limit"}]
        value = re.sub(r"\s*(?:\*/|-->)\s*$", "", match.group(1)).strip()
        values.append(value)
    return [_spdx_expression(value) for value in values]


def _evidence_text(data: Any, kind: str) -> tuple[str, str | None]:
    if not isinstance(data, bytes):
        return "", f"nonbytes-{kind}-evidence"
    if len(data) > MAX_LICENSE_BYTES:
        return "", f"oversized-{kind}-evidence"
    if b"\x00" in data:
        return "", f"binary-{kind}-evidence"
    try:
        return data.decode("utf-8", errors="strict"), None
    except UnicodeError:
        return "", f"nonutf8-{kind}-evidence"


def _license_observation(data: Any) -> tuple[set[str], str | None, list[dict[str, Any]]]:
    text, problem = _evidence_text(data, "license")
    if problem:
        return set(), problem, []
    recognized = {spdx for spdx, pattern in _LICENSE_PATTERNS if pattern.search(text)}
    expressions = _spdx_headers(text)
    for expression in expressions:
        recognized.update(identifier for identifier in expression["identifiers"] if identifier in _KNOWN_IDS)
    explicit_ids = {identifier for expression in expressions for identifier in expression["identifiers"]}
    # Generic GPL title text cannot determine the only/or-later variant. Retain
    # the explicitly observed SPDX variant instead of manufacturing a conflict.
    for generic in ("GPL-3.0", "AGPL-3.0"):
        if any(identifier.startswith(generic + "-") for identifier in explicit_ids):
            recognized.discard(generic)
    if re.search(r"Redistribution and use in source and binary forms", text, re.I):
        recognized.add("BSD-3-Clause" if re.search(r"Neither the name", text, re.I) else "BSD-2-Clause")
    if any(expression["problem"] for expression in expressions):
        problem = "unsupported-spdx-expression"
    elif _CUSTOM_TERMS.search(text):
        problem = "custom-license-terms"
    elif not recognized:
        problem = "unrecognized-license-text"
    elif any(identifier not in _TERM_SKELETONS or not all(re.search(pattern, text, re.I | re.S) for pattern in _TERM_SKELETONS[identifier]) for identifier in recognized):
        problem = "incomplete-or-unverified-license-terms"
    return recognized, problem, expressions


def _recognize_license(data: bytes) -> tuple[set[str], str | None]:
    matches, problem, _ = _license_observation(data)
    return matches, problem


def _json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate-source-json-key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError("nonfinite-source-json")


def _valid_claim_text(value: Any) -> bool:
    if not isinstance(value, str) or not value or len(value) > 4096:
        return False
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        return False
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError:
        return False
    return True


def _valid_json_tree(value: Any, depth: int = 0) -> bool:
    if depth > MAX_EVIDENCE_DEPTH:
        return False
    if isinstance(value, str):
        try:
            value.encode("utf-8", errors="strict")
        except UnicodeError:
            return False
    elif isinstance(value, dict):
        return len(value) <= MAX_EVIDENCE_FILES and all(_valid_json_tree(key, depth + 1) and _valid_json_tree(item, depth + 1) for key, item in value.items())
    elif isinstance(value, list):
        return len(value) <= MAX_EVIDENCE_FILES and all(_valid_json_tree(item, depth + 1) for item in value)
    elif isinstance(value, float):
        return math.isfinite(value)
    return True


def _source_scope_claims(value: Any, prefix: str = "") -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    if isinstance(value, list):
        for index, child in enumerate(value):
            if isinstance(child, (dict, list)):
                observations.extend(_source_scope_claims(child, prefix + f"[{index}]."))
        return observations
    for key, item in value.items():
        if key == "files_sha256":
            continue
        # Arbitrary key/value strings are not copied into public receipts.
        name = prefix + key if re.fullmatch(r"[A-Za-z0-9_-]{1,80}", key) else prefix + "UNSAFE_FIELD_NAME"
        if re.search(r"licen[cs]e|scope|rights|terms", key, re.I):
            encoded = json.dumps(item, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
            observations.append({"field": name, "value_sha256": hashlib.sha256(encoded).hexdigest(), "status": "SOURCE_SCOPE_REVIEW"})
        elif isinstance(item, (dict, list)):
            observations.extend(_source_scope_claims(item, name + "."))
    return observations


def _source_bindings(snapshot: dict[str, bytes], key: str, text: str) -> tuple[dict[str, Any], list[str]]:
    details: dict[str, Any] = {"binding_status": "NOT_PROVIDED", "bindings": [], "claims_status": "UNSIGNED_HONEST"}
    problems: list[str] = []
    try:
        manifest = json.loads(text, object_pairs_hook=_json_object, parse_constant=_reject_json_constant)
    except (ValueError, TypeError, RecursionError):
        return details, ["invalid-source-json"]
    if not isinstance(manifest, dict):
        return details, ["source-json-not-object"]
    if not _valid_json_tree(manifest):
        return details, ["invalid-source-json-unicode-value-or-depth"]
    scope_claims = _source_scope_claims(manifest)
    details["scope_claims"] = scope_claims
    if scope_claims:
        problems.append("source-license-or-scope-claim-review")
    for required in ("repo", "sha", "path"):
        if required not in manifest:
            problems.append(f"missing-source-provenance-claim:{required}")
    claims: dict[str, str] = {}
    for field in ("repo", "ref", "sha", "path"):
        if field not in manifest:
            continue
        value = manifest[field]
        if not _valid_claim_text(value):
            problems.append(f"invalid-source-claim:{field}")
        elif field == "repo" and not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value):
            problems.append("invalid-source-claim:repo")
        elif field == "ref" and (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", value) or ".." in value):
            problems.append("invalid-source-claim:ref")
        elif field == "sha" and not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", value):
            problems.append("invalid-source-claim:sha")
        elif field == "path" and not _valid_relative_path(value):
            problems.append("invalid-source-claim:path")
        else:
            claims[field] = value
    details["claims"] = claims
    bindings = manifest.get("files_sha256")
    if bindings is None:
        return details, problems + ["source-file-bindings-missing"]
    if not isinstance(bindings, dict) or not bindings or len(bindings) > MAX_EVIDENCE_FILES:
        return details, problems + ["invalid-source-file-bindings"]
    parent = PurePosixPath(key).parent
    for relative, expected in sorted(bindings.items()):
        if not _valid_relative_path(relative) or not isinstance(expected, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
            problems.append("invalid-source-file-binding")
            continue
        target = (parent / relative).as_posix()
        data = snapshot.get(target)
        actual = hashlib.sha256(data).hexdigest() if isinstance(data, bytes) else ""
        status = "MATCH" if actual == expected.lower() else "MISMATCH" if actual else "MISSING_OR_UNREADABLE"
        details["bindings"].append({"file": target, "declared_relative_path": relative, "expected_sha256": expected.lower(), "actual_sha256": actual, "status": status})
        if status != "MATCH":
            problems.append(f"source-file-binding-{status.lower()}:{target}")
    details["binding_status"] = "VERIFIED" if not problems else "ERROR"
    return details, problems


def _notice_derived_scopes(snapshot: dict[str, bytes], key: str, text: str) -> tuple[list[str], bool]:
    """Map explicit skill names only, including a unique bundled szl- alias.

    This is a conservative review selector, never a transfer of license rights.
    Unresolved or unscoped third-party portions require review for the ancestor.
    """
    if not re.search(r"portions derived|overlay on|third.party|non[- ]commercial|proprietary", text, re.I):
        return [], False
    parent = PurePosixPath(key).parent
    candidates = [PurePosixPath(name).parent for name in snapshot if PurePosixPath(name).name == "SKILL.md" and parent in PurePosixPath(name).parents]
    references = re.findall(r"\bskills/([A-Za-z0-9][A-Za-z0-9_-]*)", text)
    scopes: list[str] = []
    unresolved = not references
    for reference in references:
        exact = [candidate for candidate in candidates if candidate.name == reference]
        matches = exact or [candidate for candidate in candidates if candidate.name == "szl-" + reference]
        if len(matches) == 1:
            scopes.append(matches[0].as_posix())
        else:
            unresolved = True
    return sorted(set(scopes)), unresolved


def detect_license(snapshot: dict[str, bytes], skill_path: str, declared: Any) -> dict[str, Any]:
    """Record all ancestry/scoped evidence; never approve or infer whole-tree rights.

    The caller must supply a complete immutable byte snapshot captured by the
    bounded reader, which rejects links, special files and read errors. This
    function performs no filesystem IO and cannot establish link provenance.
    The nearest license directory controls the main skill observation. Every
    ancestor through repository root and license/provenance evidence below the
    skill is retained. Unknown/custom/conflicting terms and incomplete source
    bindings require human review; SOURCE/NOTICE are never legal permission.
    SPDX observations use an explicit bounded vocabulary and syntax subset.
    """
    declaration = declared if isinstance(declared, str) else ""
    result: dict[str, Any] = {
        "evidence_status": "MISSING", "declared": declaration,
        "detected": "", "effective": declaration or "UNKNOWN",
        "file": "", "file_sha256": "", "matches": [], "reasons": [],
        "evidence": [], "disposition": "LICENSE_REVIEW", "human_approval": "NOT_GRANTED",
        "permission": "NOT_ASSESSED", "applicable_scope": "", "applicable_evidence_paths": [],
        "ancestor_scopes": [], "declaration_expression": None,
        "snapshot_boundary": "REQUIRES_COMPLETE_LINK_FREE_BYTE_SNAPSHOT",
    }
    if declared is not None and not isinstance(declared, str):
        result["reasons"].append("nonstring-license-declaration")
    if skill_path != "." and not _valid_relative_path(skill_path):
        result["evidence_status"] = "UNKNOWN"
        result["reasons"].append("invalid-skill-path")
        return result
    if not isinstance(snapshot, dict) or len(snapshot) > MAX_EVIDENCE_FILES:
        result["evidence_status"] = "UNKNOWN"
        result["reasons"].append("invalid-or-oversized-snapshot")
        return result
    if any(not _valid_relative_path(key) for key in snapshot):
        result["evidence_status"] = "UNKNOWN"
        result["reasons"].append("invalid-snapshot-key")
        return result
    for key, data in snapshot.items():
        if not isinstance(data, bytes):
            result["reasons"].append(f"snapshot-content-not-bytes:{key}")
    path = PurePosixPath(skill_path)
    directories = [path, *path.parents]
    result["ancestor_scopes"] = [directory.as_posix() for directory in directories]
    nearest: list[str] = []
    for directory in directories:
        nearest = sorted(key for key in snapshot if PurePosixPath(key).parent == directory and PurePosixPath(key).name.lower() in _LICENSE_NAMES)
        if nearest:
            break
    if nearest:
        result["applicable_scope"] = PurePosixPath(nearest[0]).parent.as_posix()
        result["applicable_evidence_paths"] = nearest
        result["file"] = nearest[0]
        data = snapshot[nearest[0]]
        result["file_sha256"] = hashlib.sha256(data).hexdigest() if isinstance(data, bytes) else ""
    selected: list[str] = []
    for directory in directories:
        selected.extend(sorted(key for key in snapshot if PurePosixPath(key).parent == directory and (PurePosixPath(key).name.lower() in _LICENSE_NAMES or PurePosixPath(key).name.lower() in {"source.json", "notice", "notice.md", "notice.txt"})))
    selected.extend(sorted(key for key in snapshot if path in PurePosixPath(key).parent.parents and (PurePosixPath(key).name.lower() in _LICENSE_NAMES or PurePosixPath(key).name.lower() in {"source.json", "notice", "notice.md", "notice.txt"})))
    all_matches: set[str] = set()
    nearest_signatures: set[str] = set()
    unknown = bool(result["reasons"])
    main_unknown = "nonstring-license-declaration" in result["reasons"]
    conflicting = False
    ancestor_matches: dict[str, set[str]] = {}
    ancestor_expressions: dict[str, set[str]] = {}
    for key in selected:
        data = snapshot[key]
        file_hash = hashlib.sha256(data).hexdigest() if isinstance(data, bytes) else ""
        parent = PurePosixPath(key).parent
        nested = path in parent.parents
        kind = "license" if PurePosixPath(key).name.lower() in _LICENSE_NAMES else "source" if PurePosixPath(key).name.lower() == "source.json" else "notice"
        relation = "applicable_license" if key in nearest else "nested_license_override" if nested and kind == "license" else "ancestor_license" if kind == "license" else "nested_provenance" if nested else "ancestor_provenance"
        evidence: dict[str, Any] = {"file": key, "file_sha256": file_hash, "scope": parent.as_posix(), "kind": kind, "relation": relation, "matches": [], "problem": ""}
        if kind == "license":
            matches, problem, expressions = _license_observation(data)
            evidence["matches"] = sorted(matches)
            evidence["spdx_expressions"] = expressions
            text, _ = _evidence_text(data, "license")
            evidence["scope_clauses_observed"] = bool(_SCOPE_CLAUSES.search(text))
            evidence["terms_verification"] = "SKELETON_IDENTIFIED" if not problem else "REVIEW_REQUIRED"
            if key in nearest and evidence["scope_clauses_observed"]:
                result["reasons"].append(f"applicable-license-scope-clause-review:{key}")
                unknown = True
            if key in nearest:
                all_matches.update(matches)
                if expressions and not any(expression["problem"] for expression in expressions):
                    signature = " | ".join(sorted(set(expression["normalized"] for expression in expressions)))
                    # Multiple separate SPDX lines or additional unexpressed terms
                    # cannot silently become an intended compound expression.
                    if len({expression["normalized"] for expression in expressions}) > 1 or not matches <= set(identifier for expression in expressions for identifier in expression["identifiers"]):
                        conflicting = True
                    nearest_signatures.add(signature)
                elif len(matches) == 1:
                    nearest_signatures.add(next(iter(matches)))
                elif len(matches) > 1:
                    conflicting = True
            ancestor_matches.setdefault(parent.as_posix(), set()).update(matches)
            signature = " | ".join(sorted(set(expression["normalized"] for expression in expressions))) if expressions else next(iter(matches)) if len(matches) == 1 else ""
            ancestor_expressions.setdefault(parent.as_posix(), set()).add(signature)
        else:
            text, problem = _evidence_text(data, kind)
            if not problem and kind == "source":
                details, source_problems = _source_bindings(snapshot, key, text)
                evidence.update(details)
                for source_problem in source_problems:
                    result["reasons"].append(f"{source_problem}:{key}")
                if source_problems:
                    unknown = True
                    evidence["binding_status"] = "ERROR"
            elif not problem and kind == "notice":
                scopes, unresolved = _notice_derived_scopes(snapshot, key, text)
                evidence["derived_scope_paths"] = scopes
                evidence["derived_scope_unresolved"] = unresolved
                evidence["scope_resolution"] = "EXACT_OR_UNIQUE_SZL_PREFIX_ALIAS_REVIEW_SELECTOR"
                if unresolved or any(path == PurePosixPath(scope) or PurePosixPath(scope) in path.parents or path in PurePosixPath(scope).parents for scope in scopes):
                    result["reasons"].append(f"notice-derived-portions-scope-review:{key}")
                    unknown = True
        evidence["problem"] = problem or ""
        result["evidence"].append(evidence)
        if problem:
            unknown = True
            if key in nearest:
                main_unknown = True
            result["reasons"].append(f"{problem}:{key}")
    result["matches"] = sorted(all_matches)
    if len(nearest_signatures) == 1:
        result["detected"] = next(iter(nearest_signatures))
    elif len(all_matches) == 1:
        result["detected"] = next(iter(all_matches))
    if len(nearest_signatures) > 1:
        conflicting = True
    # Same-scope conflict is recorded even on an overridden ancestor. A single
    # explicit compound expression remains a syntax observation, not a conflict.
    for scope, matches in ancestor_matches.items():
        signatures = ancestor_expressions[scope]
        if len(signatures) > 1 or (len(matches) > 1 and "" in signatures):
            result["reasons"].append(f"same-scope-license-conflict:{scope}")
            conflicting = True
    for evidence in result["evidence"]:
        if evidence["relation"] == "nested_license_override" and evidence["matches"]:
            nested_expressions = {expression["normalized"] for expression in evidence["spdx_expressions"] if not expression["problem"]}
            if set(evidence["matches"]) != all_matches or (nested_expressions and nested_expressions != nearest_signatures):
                result["reasons"].append(f"nested-license-scope-override:{evidence['file']}")
                unknown = True
    scoped_files = sorted(key for key in snapshot if PurePosixPath(key).parent == path or path in PurePosixPath(key).parent.parents)
    uninspected: list[str] = []
    scanned_bytes = 0
    for key in scoped_files:
        data = snapshot[key]
        text, problem = _evidence_text(data, "file-license-scope")
        if problem:
            uninspected.append(key)
            result["reasons"].append(f"{problem}:{key}")
            unknown = True
            continue
        scanned_bytes += len(data)
        if key in selected:
            continue
        expressions = _spdx_headers(text)
        if not expressions:
            continue
        matches = sorted({identifier for expression in expressions for identifier in expression["identifiers"] if identifier in _KNOWN_IDS})
        evidence = {"file": key, "file_sha256": hashlib.sha256(data).hexdigest(), "scope": key, "kind": "file_spdx", "relation": "file_license_scope", "matches": matches, "spdx_expressions": expressions, "problem": "unsupported-spdx-expression" if any(expression["problem"] for expression in expressions) else ""}
        result["evidence"].append(evidence)
        if evidence["problem"]:
            result["reasons"].append(f"unsupported-file-spdx-expression:{key}")
            unknown = True
        if {expression["normalized"] for expression in expressions if not expression["problem"]} != nearest_signatures:
            result["reasons"].append(f"file-spdx-scope-override:{key}")
            unknown = True
    header_limit_hit = any(expression.get("problem") == "spdx-header-count-limit" for evidence in result["evidence"] for expression in evidence.get("spdx_expressions", []))
    result["license_header_coverage"] = {"scope": "all captured files within skill directory", "encoding": "STRICT_UTF8", "files_scanned": len(scoped_files) - len(uninspected), "bytes_scanned": scanned_bytes, "uninspected_paths": uninspected, "spdx_header_limit_hit": header_limit_hit, "complete": not uninspected and not header_limit_hit}
    result["scope_assertion"] = "MAIN_SKILL_AND_RECORDED_SCOPED_OBSERVATIONS;NO_WHOLE_TREE_RIGHTS_INFERENCE"
    if declaration:
        declaration_expression = _spdx_expression(declaration.strip())
        result["declaration_expression"] = declaration_expression
        if declaration_expression["problem"]:
            result["reasons"].append("unrecognized-or-scoped-license-declaration")
            unknown = True
            main_unknown = True
        if _SCOPED_DECLARATION.search(declaration) or any(identifier.startswith("CC-") for identifier in declaration_expression["identifiers"]):
            result["reasons"].append("frontmatter-license-scope-review")
            unknown = True
        if result["detected"] and not declaration_expression["problem"] and declaration_expression["normalized"] != result["detected"]:
            conflicting = True
    if not nearest:
        result["reasons"].append("missing-license-file")
    if conflicting:
        result["evidence_status"] = "CONFLICT"
        result["reasons"].append("ambiguous-or-mismatched-license-evidence")
    elif main_unknown:
        result["evidence_status"] = "UNKNOWN"
    elif nearest:
        result["evidence_status"] = "DETECTED"
        if not unknown:
            result["disposition"] = "EVIDENCE_IDENTIFIED"
    result["effective"] = declaration or result["detected"] or "UNKNOWN"
    result["reasons"] = sorted(set(result["reasons"]))
    return result
