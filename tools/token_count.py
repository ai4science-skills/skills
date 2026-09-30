#!/usr/bin/env python3
"""Offline exact-byte text counts with pre-import verification of pinned wheels.

Candidate files are data. This module never imports them, discovers tokenizer
plugins, downloads anything, or calls a provider. See tokenizer.lock.json.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import importlib
import io
import json
import platform
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import sysconfig
import tempfile
import zipfile

# Support isolated direct invocation without placing candidate trees on sys.path.
TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
from static_io import AuditBoundaryError, Limits, inventory, read_single, tree_digest


PACKAGES = {
    "tiktoken": ("0.12.0", "tiktoken-0.12.0-cp312-cp312-manylinux_2_28_x86_64.whl", "edde1ec917dfd21c1f2f8046b86348b0f54a2c0547f68149d8600859598769ad"),
    "regex": ("2025.9.18", "regex-2025.9.18-cp312-cp312-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl", "4f130c3a7845ba42de42f380fff3c8aebe89a810747d91bcf56d40a069f15352"),
}
ASSET_NAME = "cl100k_base.tiktoken"
ASSET_HASH = "223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7"
PATTERN = r"'(?i:[sdmt]|ll|ve|re)|[^\r\n\p{L}\p{N}]?+\p{L}++|\p{N}{1,3}+| ?[^\s\p{L}\p{N}]++[\r\n]*+|\s++$|\s*[\r\n]|\s+(?!\S)|\s"
SPECIALS = {"<|endoftext|>": 100257, "<|fim_prefix|>": 100258, "<|fim_middle|>": 100259, "<|fim_suffix|>": 100260, "<|endofprompt|>": 100276}
CONTRACT = {
    "id": "ai4science-exact-text-v1",
    "decoder": "strict UTF-8; reject NUL; no BOM removal, normalization, or newline rewriting",
    "encoder": "cl100k_base encode_ordinary; special-token spellings are ordinary text",
    "fragments": "each full file and each contiguous SKILL fragment encoded independently; no wrapper, separator, or chat overhead",
    "eager": "raw name/description top-level field lines including indented continuation lines; YAML syntax retained",
    "activation": "remaining frontmatter including delimiters, and exact body after closing delimiter",
    "lazy": "every other file below closest enclosing literal SKILL.md directory; references/scripts/assets/other by first relative path component",
    "outside_skills": "repo_other; excluded from per-skill loading totals, included in whole-repository file counts",
    "dedup": "per-file occurrences retained by repo/full pin/path; separate unique totals by complete file SHA256, never name",
    "coverage": "missing/ambiguous raw fields or non-UTF8/NUL file yields NOT_RUN for complete facet; measured file receipts retained",
    "semantics": "raw text inventory, not a YAML interpretation, actual loader trace, model context charge, or evaluation",
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


CONTRACT_HASH = hashlib.sha256(canonical(CONTRACT)).hexdigest()


class TokenizerUnavailable(Exception):
    pass


def _verified_artifacts(artifact_dir, lock_path):
    """Capture, verify, and inspect all executable/encoding bytes before import."""
    lock_raw = read_single(Path(lock_path), 65_536)
    lock = json.loads(lock_raw.decode("utf-8"))
    if lock.get("contract") != CONTRACT or lock.get("contract_sha256") != CONTRACT_HASH:
        raise TokenizerUnavailable("counting-contract-mismatch")
    if lock.get("pattern") != PATTERN or lock.get("special_tokens") != SPECIALS:
        raise TokenizerUnavailable("encoding-parameters-lock-mismatch")
    if lock.get("encoding", {}).get("sha256") != ASSET_HASH or lock["encoding"].get("filename") != ASSET_NAME:
        raise TokenizerUnavailable("encoding-lock-mismatch")
    specifications = lock.get("packages", [])
    if not isinstance(specifications, list) or len(specifications) != len(PACKAGES):
        raise TokenizerUnavailable("package-lock-mismatch")
    members = {}
    receipts = []
    for package, (version, filename, expected) in PACKAGES.items():
        matches = [item for item in specifications if item.get("name") == package]
        if len(matches) != 1 or tuple(matches[0].get(key) for key in ("version", "filename", "sha256")) != (version, filename, expected):
            raise TokenizerUnavailable("package-lock-mismatch")
        raw = read_single(Path(artifact_dir) / filename, 8_000_000)
        if hashlib.sha256(raw).hexdigest() != expected or len(raw) != matches[0].get("bytes"):
            raise TokenizerUnavailable("wheel-hash-or-size-mismatch:" + package)
        receipts.append(matches[0])
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            if len(entries) > 250 or sum(entry.file_size for entry in entries) > 20_000_000:
                raise TokenizerUnavailable("wheel-byte-or-entry-limit")
            for entry in entries:
                path = PurePosixPath(entry.filename)
                if (path.is_absolute() or ".." in path.parts or "\\" in entry.filename
                        or ":" in entry.filename or "\0" in entry.filename
                        or stat.S_ISLNK(entry.external_attr >> 16)):
                    raise TokenizerUnavailable("invalid-wheel-path")
                if entry.is_dir():
                    continue
                if entry.filename in members or entry.file_size > 8_000_000:
                    raise TokenizerUnavailable("duplicate-or-oversized-wheel-member")
                members[entry.filename] = archive.read(entry)
    asset = read_single(Path(artifact_dir) / ASSET_NAME, 2_000_000)
    if hashlib.sha256(asset).hexdigest() != ASSET_HASH or len(asset) != lock["encoding"].get("bytes"):
        raise TokenizerUnavailable("encoding-hash-or-size-mismatch")
    return members, asset, {
        "status": "VERIFIED", "lock_sha256": hashlib.sha256(lock_raw).hexdigest(),
        "packages": receipts, "encoding": lock["encoding"],
        "contract_id": CONTRACT["id"], "contract_sha256": CONTRACT_HASH,
        "python": platform.python_version(), "platform": platform.system(),
        "machine": platform.machine(), "loading": "verified wheels expanded privately; direct Encoding; no downloader or plugin discovery",
    }


class VerifiedTokenizer:
    def __init__(self, encoding, receipt, runtime):
        self.encoding, self.receipt, self._runtime = encoding, receipt, runtime

    def count(self, raw):
        if b"\0" in raw:
            raise ValueError("nul-containing-input")
        # Strict decoding excludes surrogate code points before tiktoken's fallback.
        text = raw.decode("utf-8", errors="strict")
        return len(self.encoding.encode_ordinary(text))

    def close(self):
        self._runtime.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def load_tokenizer(artifact_dir, runtime_parent, lock_path=TOOLS / "tokenizer.lock.json"):
    """Fail closed unless exact official bytes and an isolated supported ABI match."""
    runtime = None
    try:
        if not sys.flags.isolated or not sys.flags.no_site:
            raise TokenizerUnavailable("requires-python-I-S")
        if sys.version_info[:2] != (3, 12) or platform.system() != "Linux" or platform.machine() != "x86_64":
            raise TokenizerUnavailable("unsupported-pinned-wheel-platform")
        members, asset, receipt = _verified_artifacts(artifact_dir, lock_path)
        if any(name == "tiktoken" or name.startswith(("tiktoken.", "tiktoken_ext", "regex")) for name in sys.modules):
            raise TokenizerUnavailable("tokenizer-module-already-loaded")
        # Caller-provided writable parent is checked with the reviewed bounded reader.
        runtime_root = Path(runtime_parent)
        inventory(runtime_root, limits=Limits(max_total_bytes=100_000_000, max_files=10000))
        runtime = tempfile.TemporaryDirectory(prefix="verified-tokenizer-", dir=runtime_root)
        expanded = Path(runtime.name)
        for name, raw in members.items():
            target = expanded / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as handle:
                handle.write(raw)
        captured, _ = inventory(expanded, limits=Limits(max_file_bytes=8_000_000, max_total_bytes=40_000_000))
        if captured != members:
            raise TokenizerUnavailable("expanded-wheel-byte-mismatch")
        # Drop cwd/tools/site-package search entries during official-code import.
        original_path = sys.path[:]
        sys.path[:] = [str(expanded), sysconfig.get_path("stdlib"), sysconfig.get_config_var("DESTSHARED")]
        try:
            module = importlib.import_module("tiktoken")
            if module.__version__ != PACKAGES["tiktoken"][0]:
                raise TokenizerUnavailable("imported-tokenizer-version-mismatch")
            for name, loaded in list(sys.modules.items()):
                if name == "tiktoken" or name.startswith(("tiktoken.", "tiktoken_ext", "regex")):
                    origins = ([loaded.__file__] if getattr(loaded, "__file__", None) else list(getattr(loaded, "__path__", [])))
                    if not origins or any(expanded not in Path(origin).parents for origin in origins):
                        raise TokenizerUnavailable("import-outside-verified-wheel")
            ranks = {}
            for line in asset.splitlines():
                token, rank = line.split()
                decoded = base64.b64decode(token, validate=True)
                if decoded in ranks:
                    raise TokenizerUnavailable("duplicate-encoding-token")
                ranks[decoded] = int(rank)
            if len(ranks) != 100256 or set(ranks.values()) != set(range(100256)):
                raise TokenizerUnavailable("invalid-encoding-ranks")
            encoding = module.Encoding(name="cl100k_base", pat_str=PATTERN, mergeable_ranks=ranks, special_tokens=SPECIALS)
        finally:
            sys.path[:] = original_path
        return VerifiedTokenizer(encoding, receipt, runtime)
    except (TokenizerUnavailable, AuditBoundaryError, OSError, ValueError, ImportError, KeyError, TypeError, zipfile.BadZipFile) as error:
        if runtime is not None:
            runtime.cleanup()
        if isinstance(error, TokenizerUnavailable):
            raise
        raise TokenizerUnavailable(type(error).__name__ + ":" + str(error)) from error


def split_skill(raw):
    """Partition exact bytes without interpreting YAML values or rewriting lines."""
    raw.decode("utf-8", errors="strict")
    lines = raw.splitlines(keepends=True)
    def content(line):
        return line[:-2] if line.endswith(b"\r\n") else line[:-1] if line.endswith(b"\n") else line
    if not lines or content(lines[0]) != b"---":
        raise ValueError("missing-exact-frontmatter")
    closing = next((index for index in range(1, len(lines)) if content(lines[index]) == b"---"), None)
    if closing is None:
        raise ValueError("unterminated-frontmatter")
    fields = []
    for index in range(1, closing):
        match = re.match(rb"^([A-Za-z0-9_-]+):(?:[ \t]|$)", content(lines[index]))
        if match:
            fields.append((index, match.group(1)))
        elif content(lines[index]) and not content(lines[index]).startswith((b" ", b"\t", b"#")):
            raise ValueError("ambiguous-top-level-frontmatter")
    if any(sum(key == requested for _, key in fields) != 1 for requested in (b"name", b"description")):
        raise ValueError("missing-or-duplicate-index-field")
    eager = []
    used = set()
    for field_index, (start, key) in enumerate(fields):
        if key not in (b"name", b"description"):
            continue
        end = fields[field_index + 1][0] if field_index + 1 < len(fields) else closing
        # Count a raw field including following indented/comment/blank lines.
        eager.append(("eager_" + key.decode("ascii"), b"".join(lines[start:end])))
        used.update(range(start, end))
    # Keep contiguous non-eager spans separate, preserving original ordering.
    remaining = []
    span = []
    for index in range(closing + 1):
        if index in used:
            if span:
                remaining.append(("activation_frontmatter_other", b"".join(span)))
                span = []
        else:
            span.append(lines[index])
    if span:
        remaining.append(("activation_frontmatter_other", b"".join(span)))
    return eager + remaining + [("activation_body", b"".join(lines[closing + 1:]))]


def _source_identity(source):
    """Accept only canonical GitHub identifiers; errors never echo input values."""
    if not isinstance(source, dict):
        raise ValueError("invalid-source-identity")
    repo, pin = source.get("repo"), source.get("pin")
    slug = repo[len("https://github.com/"):] if isinstance(repo, str) and repo.startswith("https://github.com/") else repo
    match = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9-]{0,38})/([A-Za-z0-9_.-]{1,100})", slug) if isinstance(slug, str) else None
    if (match is None or match.group(2) in {".", ".."} or not isinstance(pin, str)
            or re.fullmatch(r"[0-9a-f]{40}", pin) is None):
        raise ValueError("invalid-source-identity")
    identity = {key: source[key] for key in ("repo", "pin", "archive_sha256", "path_prefix") if key in source}
    return identity


def count_source(snapshot, source, tokenizer, coverage=None):
    """Count one immutable snapshot; keep gaps explicit and tuples separate."""
    identity = _source_identity(source)
    digest = tree_digest(snapshot)
    bound = {"source": identity, "input_sha256": digest, "contract_sha256": CONTRACT_HASH}
    receipt = {"schema": "ai4science-token-count-v1", **bound, "status": "NOT_RUN", "files": [], "skills": [], "coverage": coverage or {"complete": True, "files": len(snapshot)}}
    if tokenizer is None:
        receipt["reason"] = "tokenizer-unavailable-or-unverified"
        return receipt
    receipt["tokenizer"] = tokenizer.receipt
    bound["tokenizer_receipt_sha256"] = hashlib.sha256(canonical(tokenizer.receipt)).hexdigest()
    receipt["tokenizer_receipt_sha256"] = bound["tokenizer_receipt_sha256"]
    skill_files = sorted(name for name in snapshot if PurePosixPath(name).name == "SKILL.md")
    directories = {str(PurePosixPath(name).parent): name for name in skill_files}
    totals = {}
    unique = {}
    problems = []
    for name in sorted(snapshot, key=lambda item: item.encode("utf-8")):
        raw = snapshot[name]
        file_hash = hashlib.sha256(raw).hexdigest()
        ancestors = [str(PurePosixPath(name).parent), *(str(parent) for parent in PurePosixPath(name).parents)]
        owner = next((parent for parent in ancestors if parent in directories), None)
        category = "repo_other"
        if owner is not None:
            relative = PurePosixPath(name).relative_to(PurePosixPath(owner))
            category = "skill_document" if name == directories[owner] else {"references": "lazy_references", "scripts": "lazy_scripts", "assets": "lazy_assets"}.get(relative.parts[0], "lazy_other")
        file_record = {**bound, "path": name, "sha256": file_hash, "bytes": len(raw), "category": category, "status": "NOT_RUN"}
        if owner is not None:
            file_record["skill_path"] = directories[owner]
        try:
            number = tokenizer.count(raw)
            file_record.update(status="COUNTED", tokens=number)
            totals[category] = totals.get(category, 0) + number
            unique.setdefault(file_hash, {"sha256": file_hash, "bytes": len(raw), "tokens": number, "occurrences": []})["occurrences"].append(name)
            if category == "skill_document":
                fragments = []
                for fragment_index, (part, data) in enumerate(split_skill(raw)):
                    fragments.append({"category": part, "fragment": fragment_index, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "tokens": tokenizer.count(data)})
                receipt["skills"].append({**bound, "path": name, "sha256": file_hash, "status": "COUNTED", "fragments": fragments})
        except (ValueError, UnicodeError) as error:
            reason = str(error) if not isinstance(error, UnicodeError) else "non-utf8-input"
            # A full file can be measured even when the raw field split fails.
            file_record["partition_status"] = "NOT_RUN"
            file_record["reason"] = reason
            problems.append({"path": name, "reason": reason})
            if category == "skill_document":
                receipt["skills"].append({**bound, "path": name, "sha256": file_hash, "status": "NOT_RUN", "reason": reason})
        receipt["files"].append(file_record)
    for skill_record in receipt["skills"]:
        owned = [record for record in receipt["files"] if record.get("skill_path") == skill_record["path"] and record["category"] != "skill_document"]
        skill_record["lazy_files"] = [{key: record[key] for key in ("path", "sha256", "bytes", "category", "status", "tokens", "reason") if key in record} for record in owned]
        skill_record["lazy_measured_tokens_by_category"] = {
            category: sum(record["tokens"] for record in owned if record["status"] == "COUNTED" and record["category"] == category)
            for category in sorted({record["category"] for record in owned if record["status"] == "COUNTED"})
        }
        if any(record["status"] != "COUNTED" for record in owned):
            skill_record["status"] = "NOT_RUN"
    if not skill_files:
        problems.append({"reason": "no-literal-SKILL.md"})
    if not receipt["coverage"].get("complete", False):
        problems.append({"reason": "input-coverage-incomplete"})
    receipt["measured_file_totals"] = {"occurrences": sum(item["tokens"] for item in receipt["files"] if item["status"] == "COUNTED"), "by_category": totals, "unique_by_full_sha256": sum(item["tokens"] for item in unique.values())}
    receipt["unique_files"] = [unique[key] for key in sorted(unique)]
    receipt["problems"] = problems
    receipt["status"] = "COUNTED" if not problems else "NOT_RUN"
    receipt["scope"] = "measured_file_totals include only explicitly COUNTED files; complete facet requires all files and raw SKILL partitions"
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pin", required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--runtime-parent", type=Path, required=True)
    args = parser.parse_args()
    try:
        source = _source_identity({"repo": args.repo, "pin": args.pin})
    except ValueError:
        print(json.dumps({"schema": "ai4science-token-count-v1", "status": "NOT_RUN", "reason": "invalid-source-identity", "contract_sha256": CONTRACT_HASH}, sort_keys=True))
        return 2
    tokenizer = None
    reason = None
    try:
        tokenizer = load_tokenizer(args.artifacts, args.runtime_parent)
    except TokenizerUnavailable as error:
        reason = str(error)
    try:
        snapshot, coverage = inventory(args.root, limits=Limits(max_file_bytes=8_000_000, max_total_bytes=100_000_000, max_files=20000, max_entries=40000))
        result = count_source(snapshot, source, tokenizer, coverage)
        if reason:
            result["reason"] = reason
    except (AuditBoundaryError, ValueError) as error:
        result = {"schema": "ai4science-token-count-v1", "source": source, "status": "NOT_RUN", "reason": str(error), "contract_sha256": CONTRACT_HASH}
    finally:
        if tokenizer is not None:
            tokenizer.close()
    print(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "COUNTED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
