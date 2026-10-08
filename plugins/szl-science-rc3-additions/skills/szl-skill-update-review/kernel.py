"""Offline, bounded comparison of two locked local skill-package snapshots.

The lock must be retained independently of the package snapshots. Hash agreement
establishes byte identity against that lock, not authorship, safety, or validity.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path
from urllib.parse import unquote_to_bytes, urlsplit

INVENTORY_SCHEMA = "szl.skill-package-inventory.v1"
LOCK_SCHEMA = "szl.skill-update-lock.v1"
REPORT_SCHEMA = "szl.skill-update-review.v1"
MAX_INVENTORY = 2 * 1024 * 1024
MAX_LOCK = 64 * 1024
MAX_FILES = 4096
MAX_SKILLS = 256
MAX_FILE = 8 * 1024 * 1024
MAX_TOTAL = 32 * 1024 * 1024
HASH = re.compile(r"[0-9a-f]{64}\Z")
REVISION = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?\Z")
SKILL_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
PACKAGE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9][A-Za-z0-9._-]*)?\Z")
HOST = re.compile(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\Z")
CREDENTIAL = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
URL = re.compile(r"https?://[^\s\]\[()<>\"'`]+", re.I)
ENV = re.compile(r"\b(?:[A-Z][A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD|CREDENTIALS)|API_KEY|TOKEN|SECRET|PASSWORD|CREDENTIALS)\b")
ENV_GENERIC = re.compile(r"\b(?:API_KEY|TOKEN|SECRET|PASSWORD|CREDENTIALS)\b")
ASSIGNMENT = re.compile(r"(?m)^[ \t]*(?:(?:export|const|let|var)[ \t]+)?([A-Za-z_][A-Za-z0-9_]*)[ \t]*=")
BRACKET = re.compile(r"\[([^\[\]\n]+)\]")
DEFINITION = re.compile(r"^[ ]{0,3}\[([^\[\]\n]+)\]:[ \t]*(.*)$", re.M)
CODE = re.compile(r"`([^`\n]+)`")
HELPER_SUFFIXES = {".py", ".sh", ".js", ".ts", ".ps1", ".bat", ".cmd", ".r", ".jl", ".ipynb"}


class Incomplete(ValueError):
    """A snapshot cannot support a complete comparison."""


def _keys(value, wanted, label):
    if not isinstance(value, dict) or set(value) != set(wanted):
        raise Incomplete(f"{label} requires exactly {sorted(wanted)}")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Incomplete(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _bad_constant(value):
    raise Incomplete(f"non-finite JSON number: {value}")


def _json_file(path, maximum, label):
    path = Path(path)
    try:
        if _unsafe_stat(path) or not path.is_file() or path.stat().st_size > maximum:
            raise Incomplete(f"{label} missing, linked, or over {maximum} bytes")
        raw = path.read_bytes()
        if len(raw) > maximum:
            raise Incomplete(f"{label} over {maximum} bytes")
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                           parse_constant=_bad_constant)
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise Incomplete(f"{label} cannot be read: {error}") from error
    return value, hashlib.sha256(raw).hexdigest()


def _path(value):
    if (not isinstance(value, str) or not value or len(value) > 240 or
            value.startswith("/") or any(c in value for c in '\\:*?"<>|') or
            any(ord(c) < 32 for c in value) or
            any(part in ("", ".", "..") or part.endswith((" ", "."))
                for part in value.split("/"))):
        raise Incomplete(f"non-canonical or unsafe relative path: {value!r}")
    return value


def _string(value, label, max_length=160):
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise Incomplete(f"{label} must be a nonempty string of at most {max_length} characters")
    return value


def _sorted_unique(values, label, validate):
    if not isinstance(values, list) or len(values) > MAX_FILES:
        raise Incomplete(f"{label} must be a bounded list")
    checked = [validate(value) for value in values]
    if len(set(checked)) != len(checked) or checked != sorted(checked):
        raise Incomplete(f"{label} must be sorted and unique")
    return checked


def _manifest(value, label):
    _keys(value, {"schema", "package", "revision", "complete", "files", "skills"}, label)
    if value["schema"] != INVENTORY_SCHEMA or value["complete"] is not True:
        raise Incomplete(f"{label} has wrong schema or is not marked complete")
    package = _string(value["package"], f"{label}.package")
    if not PACKAGE.fullmatch(package):
        raise Incomplete(f"{label}.package must be a plain identifier or owner/name")
    if not isinstance(value["revision"], str) or not REVISION.fullmatch(value["revision"]):
        raise Incomplete(f"{label}.revision must be a full lowercase 40- or 64-digit hex pin")
    files = value["files"]
    if not isinstance(files, list) or not files or len(files) > MAX_FILES:
        raise Incomplete(f"{label}.files must be a nonempty bounded list")
    paths, casefolded, total = set(), set(), 0
    for item in files:
        _keys(item, {"path", "sha256", "size"}, f"{label}.file")
        path = _path(item["path"])
        if path in paths or path.casefold() in casefolded:
            raise Incomplete(f"{label} has a duplicate or case-colliding path: {path}")
        paths.add(path); casefolded.add(path.casefold())
        if not isinstance(item["sha256"], str) or not HASH.fullmatch(item["sha256"]):
            raise Incomplete(f"{label} invalid SHA-256 for {path}")
        if type(item["size"]) is not int or not 0 <= item["size"] <= MAX_FILE:
            raise Incomplete(f"{label} invalid size for {path}")
        total += item["size"]
    if total > MAX_TOTAL or [f["path"] for f in files] != sorted(paths):
        raise Incomplete(f"{label} exceeds total byte limit or files are not sorted")
    skills = value["skills"]
    if not isinstance(skills, list) or not skills or len(skills) > MAX_SKILLS:
        raise Incomplete(f"{label}.skills must be a nonempty bounded list")
    skill_paths, skill_names = set(), set()
    for item in skills:
        _keys(item, {"path", "name", "referenced_files", "declared_external_hosts",
                     "declared_credentials", "declared_license", "declared_dynamic_destinations"},
              f"{label}.skill")
        path = _path(item["path"])
        name = item["name"]
        if len(path.split("/")) != 2 or not path.startswith("skills/"):
            raise Incomplete(f"{label} skill path must be skills/<directory>: {path}")
        if not isinstance(name, str) or not SKILL_NAME.fullmatch(name):
            raise Incomplete(f"{label} invalid skill name: {name!r}")
        if path in skill_paths or path.casefold() in {p.casefold() for p in skill_paths}:
            raise Incomplete(f"{label} duplicate skill path: {path}")
        if name in skill_names or name.casefold() in {n.casefold() for n in skill_names}:
            raise Incomplete(f"{label} skill name collision: {name}")
        skill_paths.add(path); skill_names.add(name)
        _sorted_unique(item["referenced_files"], f"{label}.{name}.referenced_files", _path)
        _sorted_unique(item["declared_external_hosts"], f"{label}.{name}.declared_external_hosts",
                       lambda host: _host(host, label))
        _sorted_unique(item["declared_credentials"], f"{label}.{name}.declared_credentials",
                       lambda credential: _credential(credential, label))
        _string(item["declared_license"], f"{label}.{name}.declared_license")
        if type(item["declared_dynamic_destinations"]) is not bool:
            raise Incomplete(f"{label}.{name}.declared_dynamic_destinations must be boolean")
        if f"{path}/SKILL.md" not in paths:
            raise Incomplete(f"{label} lacks {path}/SKILL.md")
        for ref in item["referenced_files"]:
            if f"{path}/{ref}" not in paths:
                raise Incomplete(f"{label} missing referenced file: {path}/{ref}")
    discovered = {p.removesuffix("/SKILL.md") for p in paths if p.endswith("/SKILL.md")}
    if discovered != skill_paths:
        raise Incomplete(f"{label} SKILL.md entrypoints contradict skill declarations")
    if [s["path"] for s in skills] != sorted(skill_paths):
        raise Incomplete(f"{label}.skills must be sorted by path")
    return package


def _host(value, label):
    if not isinstance(value, str) or len(value) > 253 or not HOST.fullmatch(value):
        raise Incomplete(f"{label} invalid lowercase declared host: {value!r}")
    return value


def _credential(value, label):
    if not isinstance(value, str) or len(value) > 100 or not CREDENTIAL.fullmatch(value):
        raise Incomplete(f"{label} invalid credential identifier: {value!r}")
    return value


def _lock(value):
    _keys(value, {"schema", "snapshots"}, "lock")
    if value["schema"] != LOCK_SCHEMA:
        raise Incomplete("wrong lock schema")
    _keys(value["snapshots"], {"old", "new"}, "lock.snapshots")
    for label in ("old", "new"):
        item = value["snapshots"][label]
        _keys(item, {"package", "revision", "inventory_sha256"}, f"lock.{label}")
        if not PACKAGE.fullmatch(_string(item["package"], f"lock.{label}.package")):
            raise Incomplete(f"lock.{label}.package must be a plain identifier or owner/name")
        if not isinstance(item["revision"], str) or not REVISION.fullmatch(item["revision"]):
            raise Incomplete(f"lock.{label}.revision invalid")
        if not isinstance(item["inventory_sha256"], str) or not HASH.fullmatch(item["inventory_sha256"]):
            raise Incomplete(f"lock.{label}.inventory_sha256 invalid")


def _unsafe_stat(path):
    info = path.lstat()
    return (stat.S_ISLNK(info.st_mode) or
            bool(getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)))


def _read_file(path, expected_size):
    before = path.lstat()
    if _unsafe_stat(path) or not stat.S_ISREG(before.st_mode) or before.st_size != expected_size:
        raise Incomplete(f"missing, linked, non-file, or changed size: {path}")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as stream:
            raw = stream.read(MAX_FILE + 1)
    except OSError as error:
        raise Incomplete(f"cannot read package file {path}: {error}") from error
    after = path.lstat()
    if (len(raw) != expected_size or before.st_size != after.st_size or
            before.st_mtime_ns != after.st_mtime_ns or before.st_ino != after.st_ino or
            _unsafe_stat(path)):
        raise Incomplete(f"package file changed while reading: {path}")
    return raw


def _walk(root):
    root = Path(root)
    if not root.is_dir() or _unsafe_stat(root):
        raise Incomplete(f"package root is missing or linked: {root}")
    observed = []
    def unreadable(error):
        raise Incomplete(f"cannot enumerate package directory: {error}")

    for parent, dirs, files in os.walk(root, topdown=True, followlinks=False, onerror=unreadable):
        for name in dirs + files:
            path = Path(parent) / name
            if _unsafe_stat(path):
                raise Incomplete(f"package contains a link or reparse point: {path}")
            _path(path.relative_to(root).as_posix())
        for name in files:
            path = Path(parent) / name
            if not path.is_file():
                raise Incomplete(f"package contains a non-file: {path}")
            observed.append(path.relative_to(root).as_posix())
            if len(observed) > MAX_FILES:
                raise Incomplete("package exceeds file-count bound")
    return sorted(observed)


def _frontmatter(raw, path):
    try:
        text = raw.decode("utf-8")
    except UnicodeError as error:
        raise Incomplete(f"{path} is not UTF-8") from error
    match = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|\Z)", text, re.S)
    if not match:
        raise Incomplete(f"{path} lacks YAML frontmatter")
    fields = {}
    for line in match.group(1).splitlines():
        if not line or line.startswith("#"):
            continue
        found = re.fullmatch(r"([A-Za-z][A-Za-z0-9_-]*):[ \t]*(.+)", line)
        if not found:
            raise Incomplete(f"{path} uses unsupported or ambiguous frontmatter syntax")
        key, value = found.groups()
        if key in fields:
            raise Incomplete(f"{path} duplicates frontmatter key {key}")
        if value.startswith('"') and value.endswith('"'):
            try:
                value = json.loads(value)
            except json.JSONDecodeError as error:
                raise Incomplete(f"{path} invalid quoted {key}") from error
        elif value.startswith("'") and value.endswith("'"):
            value = value[1:-1].replace("''", "'")
        fields[key] = value
    return text, fields


def _markdown_target(value):
    value = value.strip()
    if not value:
        raise Incomplete("empty Markdown destination")
    if value.startswith("<"):
        end = value.find(">")
        if end < 0 or "<" in value[1:end]:
            raise Incomplete("unsupported or ambiguous Markdown link destination")
        destination, rest = value[1:end], value[end + 1:]
    else:
        match = re.match(r"(\S+)(.*)\Z", value, re.S)
        destination, rest = match.groups()
    if rest:
        if not rest[0].isspace():
            raise Incomplete("Markdown link title needs separating whitespace")
        title = rest.strip()
        if (len(title) < 2 or title[0] not in ('"', "'", "(") or
                title[-1] != {'"': '"', "'": "'", "(": ")"}[title[0]]):
            raise Incomplete("unsupported or ambiguous Markdown link title")
        escaped = False
        for char in title[1:-1]:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == title[-1] or (title[0] == "(" and char == "("):
                raise Incomplete("ambiguous Markdown link title punctuation")
        if escaped:
            raise Incomplete("unterminated Markdown title escape")
    return destination


def _inline_end(text, opening):
    depth, angle, quote, escaped = 1, False, None, False
    for offset in range(opening + 1, len(text)):
        char = text[offset]
        if char == "\n":
            break
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = None
            continue
        if char in ('"', "'") and offset > opening + 1 and text[offset - 1].isspace():
            quote = char
            continue
        if char == "<":
            angle = True
        elif char == ">" and angle:
            angle = False
        elif not angle and char == "(":
            depth += 1
        elif not angle and char == ")":
            depth -= 1
            if depth == 0:
                return offset
    raise Incomplete("unterminated or unsupported Markdown inline link")


def _reference_label(value):
    label = " ".join(value.split()).casefold()
    if not label or len(label) > 160:
        raise Incomplete("empty or overlong Markdown reference label")
    return label


def _references(text):
    refs, definitions = set(), {}

    def add(destination):
        candidate = destination.split("#", 1)[0]
        scheme = re.match(r"([A-Za-z][A-Za-z0-9+.-]*):", candidate)
        if scheme and (scheme.group(1).lower() == "file" or len(scheme.group(1)) == 1):
            raise Incomplete("local absolute URI is unsupported")
        if not candidate or candidate.startswith("//") or scheme:
            return
        if re.search(r"%(?![0-9A-Fa-f]{2})", candidate):
            raise Incomplete("malformed percent escape in local Markdown link")
        try:
            candidate = unquote_to_bytes(candidate).decode("utf-8")
        except UnicodeError as error:
            raise Incomplete("local Markdown link is not UTF-8") from error
        if re.search(r"%[0-9A-Fa-f]{2}", candidate):
            raise Incomplete("ambiguous double-encoded local Markdown link")
        if candidate.startswith("./"):
            candidate = candidate[2:]
        refs.add(_path(candidate))

    matches = list(DEFINITION.finditer(text))
    if len(matches) > MAX_FILES:
        raise Incomplete("too many Markdown reference definitions")
    body = list(text)
    for match in matches:
        label = _reference_label(match.group(1))
        if label in definitions:
            raise Incomplete(f"duplicate Markdown reference definition: {label}")
        definitions[label] = _markdown_target(match.group(2))
        add(definitions[label])
        for offset in range(*match.span()):
            body[offset] = " "
    body = "".join(body)
    masked, skip, cursor, in_label = list(body), 0, 0, False
    for match in BRACKET.finditer(body):
        if match.start() < skip:
            continue
        for char in body[cursor:match.start()]:
            if char == "[":
                in_label = True
            elif char in "]\n":
                in_label = False
        if in_label:
            raise Incomplete("unsupported nested Markdown link label")
        cursor = match.end()
        after = match.end()
        if after < len(body) and body[after] == "(":
            skip = _inline_end(body, after) + 1
            add(_markdown_target(body[after + 1:skip - 1]))
            masked[match.start():skip] = [" "] * (skip - match.start())
            cursor = skip
    body = "".join(masked)
    bracket_ends = {match.end() for match in BRACKET.finditer(body)}
    if any(match.start() + 1 not in bracket_ends
           for match in re.finditer(r"\][ \t]*[\[(]", body)):
        raise Incomplete("unsupported nested Markdown link label")
    for match in BRACKET.finditer(body):
        after = match.end()
        next_bracket = after
        while next_bracket < len(body) and body[next_bracket] in " \t":
            next_bracket += 1
        if next_bracket < len(body) and body[next_bracket] == "[":
            end = body.find("]", next_bracket + 1)
            if end < 0 or "\n" in body[next_bracket:end]:
                raise Incomplete("unterminated Markdown reference link")
            label = _reference_label(body[next_bracket + 1:end] or match.group(1))
            if label not in definitions:
                raise Incomplete(f"undefined Markdown reference link: {label}")
            add(definitions[label])
        elif _reference_label(match.group(1)) in definitions:
            add(definitions[_reference_label(match.group(1))])
    for match in CODE.finditer(text):
        if match.group(1).startswith(("assets/", "references/", "scripts/", "docs/")):
            add(match.group(1))
    return sorted(refs)


def _observations(files):
    hosts, credentials = {}, {}
    for path, raw in files.items():
        try:
            text = raw.decode("utf-8")
        except UnicodeError:
            continue
        for url in URL.findall(text):
            host = urlsplit(url.rstrip(".,;:")).hostname
            if host:
                hosts.setdefault(host.lower(), set()).add(path)
        for line in text.splitlines():
            assigned = ASSIGNMENT.match(line)
            if assigned:
                marker = assigned.group(1)
                if ENV.fullmatch(marker):
                    credentials.setdefault(marker, set()).add(path)
                continue
            unquoted = re.sub(r'"[^"\n]*"|\'[^\'\n]*\'', "", line)
            for marker in ENV_GENERIC.findall(unquoted):
                credentials.setdefault(marker, set()).add(path)
    return {"literal_url_hosts": [{"host": host, "files": sorted(paths)} for host, paths in sorted(hosts.items())],
            "literal_credential_markers": [{"marker": marker, "files": sorted(paths)}
                                           for marker, paths in sorted(credentials.items())],
            "dynamic_destinations": "UNKNOWN"}


def _snapshot(root, inventory, label):
    declared = {f["path"]: f for f in inventory["files"]}
    actual = _walk(root)
    if actual != sorted(declared):
        missing = sorted(set(declared) - set(actual))
        extra = sorted(set(actual) - set(declared))
        raise Incomplete(f"{label} file membership differs: missing={missing[:12]}, extra={extra[:12]}")
    files = {}
    for path, item in declared.items():
        raw = _read_file(Path(root) / path, item["size"])
        if hashlib.sha256(raw).hexdigest() != item["sha256"]:
            raise Incomplete(f"{label} SHA-256 mismatch: {path}")
        files[path] = raw
    for item in inventory["skills"]:
        path = item["path"]
        text, fields = _frontmatter(files[f"{path}/SKILL.md"], f"{path}/SKILL.md")
        if fields.get("name") != item["name"] or fields.get("license") != item["declared_license"]:
            raise Incomplete(f"{label} frontmatter contradicts declared name or license: {path}")
        observed = _references(text)
        if not set(observed).issubset(item["referenced_files"]):
            raise Incomplete(f"{label} SKILL.md has undeclared referenced files: {path}; observed={observed}")
    return {"files": files, "observations": _observations(files)}


def _delta(old, new):
    return {"added": sorted(set(new) - set(old)), "removed": sorted(set(old) - set(new))}


def _relative_files(inventory, skill):
    prefix = skill["path"] + "/"
    return {item["path"][len(prefix):]: item["sha256"] for item in inventory["files"]
            if item["path"].startswith(prefix)}


def _declarations(skill):
    return {key: skill[key] for key in ("referenced_files", "declared_external_hosts", "declared_credentials",
                                         "declared_license", "declared_dynamic_destinations")}


def _skill_changes(old_inv, new_inv):
    old_skills = {s["path"]: s for s in old_inv["skills"]}
    new_skills = {s["path"]: s for s in new_inv["skills"]}
    matched = [(p, p) for p in sorted(old_skills.keys() & new_skills.keys())
               if old_skills[p]["name"] == new_skills[p]["name"]]
    left = set(old_skills) - {a for a, _ in matched}
    right = set(new_skills) - {b for _, b in matched}
    renames = []
    for op in sorted(left):
        old_bytes = _relative_files(old_inv, old_skills[op])
        candidates = [np for np in sorted(right) if old_bytes == _relative_files(new_inv, new_skills[np])]
        if len(candidates) == 1 and sum(old_bytes == _relative_files(new_inv, new_skills[np]) for np in right) == 1:
            np = candidates[0]
            renames.append({"old_path": op, "new_path": np, "old_name": old_skills[op]["name"],
                            "new_name": new_skills[np]["name"], "identity": "EQUAL_BYTES_CANDIDATE_ONLY",
                            "old_declarations": _declarations(old_skills[op]),
                            "new_declarations": _declarations(new_skills[np])})
            left.remove(op); right.remove(np)
    modified = []
    for op, np in matched:
        before, after = old_skills[op], new_skills[np]
        bf, af = _relative_files(old_inv, before), _relative_files(new_inv, after)
        file_delta = _delta(bf, af)
        changed = sorted(p for p in bf.keys() & af.keys() if bf[p] != af[p])
        declared = {field: _delta(before[field], after[field])
                    for field in ("referenced_files", "declared_external_hosts", "declared_credentials")}
        license_change = None if before["declared_license"] == after["declared_license"] else {
            "old": before["declared_license"], "new": after["declared_license"]}
        dynamic_change = None if before["declared_dynamic_destinations"] == after["declared_dynamic_destinations"] else {
            "old": before["declared_dynamic_destinations"], "new": after["declared_dynamic_destinations"]}
        if changed or file_delta["added"] or file_delta["removed"] or any(v["added"] or v["removed"] for v in declared.values()) or license_change or dynamic_change:
            changed_paths = changed + file_delta["added"] + file_delta["removed"]
            referenced = set(before["referenced_files"]) | set(after["referenced_files"])
            helper_changed = any(p.startswith(("scripts/", "bin/")) or Path(p).name.startswith("kernel.") or
                                 Path(p).suffix.lower() in HELPER_SUFFIXES or
                                 (p in referenced and Path(p).suffix.lower() not in {".md", ".txt"})
                                 for p in changed_paths)
            docs_only = (bool(changed_paths) and all(Path(p).suffix.lower() in {".md", ".txt"} for p in changed_paths)
                         and not any(v["added"] or v["removed"] for v in declared.values())
                         and license_change is None and dynamic_change is None)
            modified.append({"name": before["name"], "path": op, "files": {**file_delta, "changed": changed},
                             "declarations": {**declared, "license_change": license_change,
                                              "dynamic_destinations_change": dynamic_change},
                             "helper_bytes_changed": helper_changed, "documentation_only": docs_only})
    old_files = {f["path"]: f["sha256"] for f in old_inv["files"]}
    new_files = {f["path"]: f["sha256"] for f in new_inv["files"]}
    package_delta = {**_delta(old_files, new_files),
                     "changed": sorted(p for p in old_files.keys() & new_files.keys()
                                       if old_files[p] != new_files[p])}
    license_paths = sorted(p for field in package_delta.values() for p in field
                           if Path(p).name.upper() in {"LICENSE", "NOTICE", "COPYING"} or
                            Path(p).name.upper().startswith(("LICENSE.", "NOTICE.", "COPYING.")))
    return {"added_skills": [new_skills[p]["name"] for p in sorted(right)],
            "removed_skills": [old_skills[p]["name"] for p in sorted(left)],
            "added_skill_declarations": [{"name": new_skills[p]["name"], "path": p,
                                           **_declarations(new_skills[p])} for p in sorted(right)],
            "removed_skill_declarations": [{"name": old_skills[p]["name"], "path": p,
                                             **_declarations(old_skills[p])} for p in sorted(left)],
            "equal_byte_rename_candidates": renames, "modified_skills": modified,
            "package_files": package_delta, "license_artifact_changes": license_paths}


def _rerun(changes):
    actions = []
    for name in changes["added_skills"]:
        actions.append({"scope": name, "reason": "added skill", "evidence_and_tests":
                        ["review new instructions and declarations", "run skill contract and behavior tests", "rerun evidence before relying on this version"]})
    for name in changes["removed_skills"]:
        actions.append({"scope": name, "reason": "removed skill", "evidence_and_tests":
                        ["locate evidence and workflows that depended on the removed entrypoint"]})
    for item in changes["equal_byte_rename_candidates"]:
        actions.append({"scope": item["new_name"], "reason": "equal-byte path rename candidate", "evidence_and_tests":
                        ["review routing, declarations and package registration", "rerun skill discovery tests",
                         "review newly declared external access before any use"]})
    for item in changes["modified_skills"]:
        tasks = ["review changed instructions and declarations", "rerun skill contract and behavior tests"]
        if item["helper_bytes_changed"]:
            tasks += ["invalidate prior helper-bound receipts", "rerun affected evidence and replay tests"]
        if item["declarations"]["declared_external_hosts"]["added"] or item["declarations"]["declared_credentials"]["added"]:
            tasks += ["review newly declared external access before any use"]
        if item["declarations"]["license_change"]:
            tasks += ["review license terms and attribution"]
        if item["documentation_only"]:
            tasks += ["rerun instruction and trigger review"]
        actions.append({"scope": item["name"], "reason": "changed skill", "evidence_and_tests": tasks})
    if changes["package_files"]["added"] or changes["package_files"]["removed"] or changes["package_files"]["changed"]:
        actions.append({"scope": "package", "reason": "package file set or bytes changed", "evidence_and_tests":
                        ["rerun package registration, inventory, and integration checks"]})
    if changes["license_artifact_changes"]:
        actions.append({"scope": "package licenses", "reason": "license or notice artifact bytes changed",
                        "evidence_and_tests": ["review changed license text and attribution"]})
    return actions


def szl_review_updates(old_root, old_inventory_path, new_root, new_inventory_path, lock_path):
    """Return a structured review; any unverified input yields INCOMPLETE."""
    try:
        lock, lock_hash = _json_file(lock_path, MAX_LOCK, "lock")
        _lock(lock)
        old_inv, old_hash = _json_file(old_inventory_path, MAX_INVENTORY, "old inventory")
        new_inv, new_hash = _json_file(new_inventory_path, MAX_INVENTORY, "new inventory")
        old_package = _manifest(old_inv, "old inventory")
        new_package = _manifest(new_inv, "new inventory")
        if old_package != new_package:
            raise Incomplete("package identities differ")
        for label, inv, digest in (("old", old_inv, old_hash), ("new", new_inv, new_hash)):
            bound = lock["snapshots"][label]
            if (bound["package"] != inv["package"] or bound["revision"] != inv["revision"] or
                    bound["inventory_sha256"] != digest):
                raise Incomplete(f"{label} inventory does not match separately retained lock")
        roots = [Path(old_root).resolve(), Path(new_root).resolve()]
        if roots[0] == roots[1]:
            raise Incomplete("old and new roots must be separate immutable snapshots")
        for root in roots:
            for external in (lock_path, old_inventory_path, new_inventory_path):
                if Path(external).resolve() == root or root in Path(external).resolve().parents:
                    raise Incomplete("lock and inventories must be outside both package roots")
        old = _snapshot(old_root, old_inv, "old")
        new = _snapshot(new_root, new_inv, "new")
        changes = _skill_changes(old_inv, new_inv)
        same = (not changes["added_skills"] and not changes["removed_skills"] and
                not changes["equal_byte_rename_candidates"] and not changes["modified_skills"] and
                not any(changes["package_files"].values()))
        status = "NO_RECORDED_CHANGE" if same else "CHANGES_REVIEW_REQUIRED"
        return {"schema": REPORT_SCHEMA, "status": status, "package": old_package,
                "snapshots": {"old": {"revision": old_inv["revision"], "inventory_sha256": old_hash},
                              "new": {"revision": new_inv["revision"], "inventory_sha256": new_hash},
                              "lock_sha256": lock_hash},
                "changes": changes, "revision_changed": old_inv["revision"] != new_inv["revision"],
                "rerun": _rerun(changes),
                "observations": {"old": old["observations"], "new": new["observations"]},
                "limits": ["Declared capabilities and licenses are claims in local metadata, not verified permissions or rights.",
                           "URL hosts and credential marker names are partial static observations; values are omitted.",
                           "Dynamic destinations remain UNKNOWN; no package code was executed.",
                           "Byte matches do not establish code safety, scientific validity, approval, or installability.",
                           "The lock must be independently retained; its own SHA-256 is not a signature."]}
    except (Incomplete, OSError, TypeError, ValueError) as error:
        return {"schema": REPORT_SCHEMA, "status": "INCOMPLETE", "errors": [str(error)],
                "changes": None, "observations": None,
                "rerun": ["repair and independently relock both complete snapshots before review"],
                "limits": ["No unchanged, safety, approval, installability, or scientific-validity conclusion is available."]}
