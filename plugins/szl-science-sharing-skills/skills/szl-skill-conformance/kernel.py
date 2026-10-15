# SPDX-License-Identifier: Apache-2.0
"""Offline supplied-evidence conformance. Never executes candidate resources."""
import hashlib
import json
import os
import pathlib
import re
import stat
import unicodedata

MAX_FILE = 1024 * 1024
MAX_TOTAL = 4 * MAX_FILE
MAX_NODES = 512
MAX_FILES = 128
SHA = re.compile(r"[0-9a-f]{64}\Z")
NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")


def strict_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    def constant(value):
        raise ValueError("nonfinite JSON constant")
    return json.loads(data, object_pairs_hook=pairs, parse_constant=constant)


def regular_path(path, directory=False):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise ValueError("symlink or reparse point")
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected(info.st_mode):
        raise ValueError("unsupported filesystem object")
    return info


def safe_root(value):
    path = pathlib.Path(os.path.abspath(value))
    for parent in list(path.parents)[::-1] + [path]:
        regular_path(parent, directory=True)
    return path


def portable_parts(value):
    if not isinstance(value, str) or not value or len(value) > 512:
        raise ValueError("invalid resource path")
    if unicodedata.normalize("NFC", value) != value or re.search(r'[<>:"\\|?*\x00-\x1f]', value):
        raise ValueError("nonportable resource path")
    parts = value.split("/")
    reserved = {"CON", "PRN", "AUX", "NUL"} | {f"{p}{n}" for p in ("COM", "LPT") for n in range(1, 10)}
    if len(parts) > 12 or any(p in ("", ".", "..") or p.endswith((" ", ".")) or p.split(".")[0].upper() in reserved for p in parts):
        raise ValueError("unsafe resource path")
    return parts


def bounded_bytes(path):
    before = regular_path(path)
    if before.st_size > MAX_FILE:
        raise ValueError("file size bound")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(path, flags), "rb") as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise ValueError("resource changed while opening")
        data = stream.read(MAX_FILE + 1)
        after = os.fstat(stream.fileno())
    final = regular_path(path)
    fingerprint = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
    if len(data) > MAX_FILE or fingerprint(before) != fingerprint(after) or fingerprint(after) != fingerprint(final):
        raise ValueError("resource changed while reading")
    return data


def bundle(value):
    root = safe_root(value)
    files, aliases, nodes, total = {}, set(), 0, 0
    pending = [root]
    while pending:
        directory = pending.pop()
        regular_path(directory, directory=True)
        with os.scandir(directory) as entries:
            for entry in entries:
                nodes += 1
                if nodes > MAX_NODES:
                    raise ValueError("bundle node bound")
                path = pathlib.Path(entry.path)
                rel = path.relative_to(root).as_posix()
                portable_parts(rel)
                alias = rel.casefold()
                if alias in aliases:
                    raise ValueError("case-colliding bundle members")
                aliases.add(alias)
                info = path.lstat()
                if stat.S_ISDIR(info.st_mode):
                    regular_path(path, directory=True)
                    pending.append(path)
                else:
                    data = bounded_bytes(path)
                    total += len(data)
                    if total > MAX_TOTAL or len(files) >= MAX_FILES:
                        raise ValueError("bundle aggregate bound")
                    files[rel] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    if "SKILL.md" not in files:
        raise ValueError("missing SKILL.md")
    entry = bounded_bytes(root / "SKILL.md")
    if hashlib.sha256(entry).hexdigest() != files["SKILL.md"]["sha256"]:
        raise ValueError("entrypoint changed during bundle scan")
    text = entry.decode("utf-8")
    # Interpret CRLF, CR and LF uniformly without changing retained file bytes.
    # Every frontmatter check must consume this same structural line view.
    parse_text = text.replace("\r\n", "\n").replace("\r", "\n")
    front = re.match(r"\A---\n(.*?)\n---(?:\n|\Z)", parse_text, re.S)
    if front is None:
        raise ValueError("missing skill frontmatter")
    front_text = front.group(1)
    if any(separator in front_text for separator in ("\x0b", "\x0c", "\x85", "\u2028", "\u2029")):
        raise ValueError("unsupported frontmatter line separator")
    if re.search(r"[\x00-\x08\x0e-\x1f\x7f]", front_text):
        raise ValueError("unsupported frontmatter control character")
    front_lines = front_text.split("\n")
    fields = {}
    for line in front_lines:
        if not line.strip(" \t") or line.lstrip(" \t").startswith("#"):
            continue
        field = re.fullmatch(r"([A-Za-z][A-Za-z0-9_-]*):[ \t]+(.+)", line)
        if field is None or field[1] in fields:
            raise ValueError("unsupported or duplicate frontmatter field")
        scalar = field[2].strip(" \t")
        if not scalar:
            raise ValueError("empty frontmatter scalar")
        if scalar.startswith('"'):
            if not isinstance(json.loads(scalar), str):
                raise ValueError("unsupported double-quoted scalar")
        elif scalar.startswith("'"):
            if re.fullmatch(r"'(?:[^']|'')*'", scalar) is None:
                raise ValueError("unsupported single-quoted scalar")
        elif scalar[0] in "-?:,[]{}#&*!|>%@`" or re.search(r":[ \t]", scalar):
            raise ValueError("unsupported frontmatter scalar syntax")
        fields[field[1]] = scalar
    name = fields.get("name", "")
    if (not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", name)
            or name in {"true", "false", "null", "yes", "no", "on", "off", "y", "n"}):
        raise ValueError("invalid skill identity")
    records = [{"path": key, **files[key]} for key in sorted(files)]
    canonical = json.dumps(records, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return {"name": name, "bundle_sha256": hashlib.sha256(canonical).hexdigest(), "files": files, "total_bytes": total}


def keys(value, expected):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError("missing or unknown evidence fields")


def retained_file(root, rel):
    parts = portable_parts(rel)
    path = root
    for part in parts[:-1]:
        path = path / part
        regular_path(path, directory=True)
    return bounded_bytes(path / parts[-1])


def validate_trials(root_value, document, source, exported, imported_name):
    keys(document, ("schema_version", "evidence_kind", "source_bundle_sha256", "host_bundle_sha256", "imported_skill", "cases"))
    if type(document["schema_version"]) is not int or document["schema_version"] != 1:
        raise ValueError("unsupported trial schema")
    if document["evidence_kind"] not in ("synthetic_fixture", "operator_supplied_export"):
        raise ValueError("unsupported evidence kind")
    for field, expected in (("source_bundle_sha256", source["bundle_sha256"]), ("host_bundle_sha256", exported["bundle_sha256"])):
        if not isinstance(document[field], str) or not SHA.fullmatch(document[field]) or document[field] != expected:
            raise ValueError("trial bundle digest mismatch")
    if document["imported_skill"] != imported_name:
        raise ValueError("trial skill identity mismatch")
    cases = document["cases"]
    if not isinstance(cases, list) or not 2 <= len(cases) <= 50:
        raise ValueError("positive and negative trials required within bound")
    root = safe_root(root_value)
    ids, task_aliases, kinds, rows, total = set(), set(), set(), [], 0
    for case in cases:
        keys(case, ("case_id", "kind", "task_path", "task_sha256", "result_path", "result_sha256", "invocation_reported", "outcome"))
        if not isinstance(case["case_id"], str) or not NAME.fullmatch(case["case_id"]) or case["case_id"] in ids:
            raise ValueError("invalid or duplicate trial identity")
        ids.add(case["case_id"])
        kind = case["kind"]
        if kind not in ("positive", "negative") or type(case["invocation_reported"]) is not bool:
            raise ValueError("invalid trial kind or invocation declaration")
        kinds.add(kind)
        if case["outcome"] not in ("PASS", "FAIL", "UNAVAILABLE"):
            raise ValueError("invalid declared outcome")
        hashes = {}
        for prefix in ("task", "result"):
            claimed = case[prefix + "_sha256"]
            if not isinstance(claimed, str) or not SHA.fullmatch(claimed):
                raise ValueError("invalid retained digest")
            data = retained_file(root, case[prefix + "_path"])
            total += len(data)
            if total > MAX_TOTAL:
                raise ValueError("trial aggregate bound")
            actual = hashlib.sha256(data).hexdigest()
            if actual != claimed:
                raise ValueError("retained task or result digest mismatch")
            hashes[prefix] = actual
        if hashes["task"] in task_aliases:
            raise ValueError("duplicate task bytes are not independent controls")
        task_aliases.add(hashes["task"])
        expected_invocation = kind == "positive"
        consistent = case["invocation_reported"] == expected_invocation and case["outcome"] == "PASS"
        rows.append({"case_id": case["case_id"], "kind": kind, "task_sha256": hashes["task"], "result_sha256": hashes["result"], "declaration_consistent": consistent})
    if kinds != {"positive", "negative"}:
        raise ValueError("positive and negative trials required")
    return {"evidence_kind": document["evidence_kind"], "cases": rows, "consistent": all(row["declaration_consistent"] for row in rows)}


def check(source_path, export_path=None, trials_path=None, trial_root=None, imported_name=None):
    report = {"schema_version": 1, "offline_conformance": "INCOMPLETE", "source_binding": "UNAVAILABLE", "supplied_export_binding": "UNAVAILABLE", "supplied_trial_consistency": "UNAVAILABLE", "actual_host_invocation": "NOT_VERIFIED", "scientific_result_validity": "NOT_EVALUATED", "issues": []}
    try:
        source = bundle(source_path)
        report["source_binding"] = "OBSERVED_LOCAL_BYTES"
        report["source"] = source
        identity = source["name"] if imported_name is None else imported_name
        if not isinstance(identity, str) or not NAME.fullmatch(identity):
            raise ValueError("invalid imported identity")
        report["identity_mapping"] = {"source": source["name"], "imported": identity, "explicit_alias": imported_name is not None}
        if export_path is None:
            report["issues"].append("no supplied host export")
            return report
        exported = bundle(export_path)
        report["supplied_export_bundle_sha256"] = exported["bundle_sha256"]
        if source["files"] != exported["files"] or source["name"] != exported["name"]:
            report["supplied_export_binding"] = "MISMATCH"
            raise ValueError("supplied host export differs from source")
        report["supplied_export_binding"] = "MATCHED_SUPPLIED_BYTES"
        if trials_path is None or trial_root is None:
            report["issues"].append("no complete supplied trial evidence")
            return report
        trial_path = pathlib.Path(os.path.abspath(trials_path))
        safe_root(trial_path.parent)
        document = strict_json(bounded_bytes(trial_path).decode("utf-8"))
        trials = validate_trials(trial_root, document, source, exported, identity)
        report["trials"] = trials
        report["supplied_trial_consistency"] = "CONSISTENT_DECLARATIONS" if trials["consistent"] else "CONTRADICTED_DECLARATIONS"
        report["offline_conformance"] = "CONSISTENT_SUPPLIED_EVIDENCE" if trials["consistent"] else "REJECTED"
        if not trials["consistent"]:
            report["issues"].append("declared outcome or trigger control failed")
    except (ValueError, OSError, UnicodeError, RecursionError) as error:
        report["offline_conformance"] = "REJECTED"
        report["issues"].append(str(error) if isinstance(error, ValueError) else type(error).__name__)
    return report
