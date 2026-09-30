#!/usr/bin/env python3
"""Bounded offline validation of recorded census evidence, never approval.

This is a limited projection of explicitly supported census versions. Recorded
archive/tree hashes are not recomputed or authenticated without original bytes.
Unused census metadata stays in the caller's document. No network, extraction,
third-party imports, skill execution, installation or publication occurs.
"""
import argparse
from dataclasses import dataclass
from datetime import datetime
import json
import sys
from typing import Optional, Tuple
import unicodedata
from urllib.parse import quote, urlsplit

from trust_common import (ValidationError, digest, load_json_file, object_fields,
                          portable_path, repository, text)

ACCEPTED_SCHEMA_VERSIONS = ("ai4s.sources-lock/v3-phase0-proposal", "ai4s.sources-lock/v4-phase0-proposal")
HASH_CONTRACT_ID = "ai4s.canonical-content-tree/v0-proposal"
ACQUISITION_STATUSES = ("PINNED_HASHED", "BLOCKED", "MISSING", "UNOBSERVED")
UNAPPROVED_REVIEWS = ("NOT_REVIEWED", "HUMAN_REVIEW_REQUIRED", "BLOCKED", "MISSING", "UNOBSERVED")
V3_REGISTRY_DISPOSITIONS = ("UNASSESSED_NOT_LISTED", "BLOCKED_NOT_LISTED", "MISSING_NOT_LISTED", "UNOBSERVED_NOT_LISTED", "BLOCKED_CUSTOM_LICENSE_SUBTREES")
MAX_SOURCES = 1000
MAX_PATHS = 10000
EMPTY_TREE_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


@dataclass(frozen=True)
class LockedSkill:
    path: str
    root: str


@dataclass(frozen=True)
class LockedSource:
    repository: str
    commit: Optional[str]
    archive_sha256: Optional[str]
    skill_tree_sha256: Optional[str]
    hash_contract_id: Optional[str]
    skill_paths: Tuple[str, ...]
    acquisition_status: str
    skills: Tuple[LockedSkill, ...]
    repository_tree_sha256: Optional[str]
    license_review_status: Optional[str]
    portability_status: Optional[str] = None
    license_reuse_disposition: Optional[str] = None
    blocked_reason: Optional[str] = None
    selection_status: Optional[str] = None
    archive_transport_status: Optional[str] = None


def _integer(value, label, minimum=0):
    if type(value) is not int or not minimum <= value <= 2 ** 63 - 1:
        raise ValidationError(label + ": expected bounded integer")
    return value


def _object(value, fields, optional, label, required):
    return object_fields(value, fields if required else (),
                         optional if required else tuple(fields) + tuple(optional), label)


def _path(value, label, root=False):
    if root and value == ".":
        return value
    portable_path(value, label)
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise ValidationError(label + ": path must be valid UTF-8") from exc
    if unicodedata.normalize("NFC", value) != value:
        raise ValidationError(label + ": path must be NFC normalized")
    return value


def _case_safe(paths, label):
    """Reject differently spelled aliases at ancestors as well as leaves."""
    seen = {}
    for path in paths:
        parts = path.split("/")
        for end in range(1, len(parts) + 1):
            prefix = "/".join(parts[:end])
            key = prefix.casefold()
            if key in seen and seen[key] != prefix:
                raise ValidationError(label + ": case-colliding ancestor")
            seen[key] = prefix


def _paths(value, label, root=False):
    if not isinstance(value, list) or len(value) > MAX_PATHS:
        raise ValidationError(label + ": expected bounded path list")
    result = tuple(_path(p, label, root) for p in value)
    if len({p.casefold() for p in result}) != len(result):
        raise ValidationError(label + ": duplicate or case-colliding path")
    _case_safe(result, label)
    return result


def _timestamp(value, label):
    text(value, label)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError(label + ": expected ISO timestamp") from exc
    if parsed.utcoffset() is None:
        raise ValidationError(label + ": timestamp needs timezone")


def _evidence(value, label, required, expected_url=None, sha256=None, size=None):
    if value is None:
        if required:
            raise ValidationError(label + ": missing acquisition evidence")
        return
    fields = ("requested_url", "observed_at", "http_status", "final_url", "bytes", "sha256", "complete")
    complete = isinstance(value, dict) and value.get("complete") is True
    data = _object(value, fields, (), label, required or complete)
    for key in ("requested_url", "final_url"):
        if key in data:
            observed = text(data[key], label + "." + key)
            try:
                url = urlsplit(observed)
                unsafe = (url.scheme != "https" or url.hostname not in ("api.github.com", "codeload.github.com")
                          or url.username or url.password or url.port or url.fragment)
            except ValueError as exc:
                raise ValidationError(label + ": invalid acquisition URL") from exc
            if unsafe:
                raise ValidationError(label + ": expected public GitHub HTTPS evidence URL")
            if expected_url is not None and observed != expected_url:
                raise ValidationError(label + ": acquisition URL disagrees with immutable source")
    if "observed_at" in data:
        _timestamp(data["observed_at"], label + ".observed_at")
    if "http_status" in data:
        status = _integer(data["http_status"], label + ".http_status", 100)
        if status > 599 or required and status != 200:
            raise ValidationError(label + ": acquisition did not return HTTP 200")
    if "bytes" in data:
        count = _integer(data["bytes"], label + ".bytes")
        if size is not None and count != size:
            raise ValidationError(label + ": byte counts disagree")
    if "sha256" in data:
        observed_sha = digest(data["sha256"], label + ".sha256")
        if sha256 is not None and observed_sha != sha256:
            raise ValidationError(label + ": digests disagree")
    if "complete" in data and type(data["complete"]) is not bool:
        raise ValidationError(label + ": complete must be boolean")
    if required and data["complete"] is not True:
        raise ValidationError(label + ": incomplete acquisition")


def _hash_contract(value):
    if value is None:
        return None
    data = object_fields(value, ("id", "digest", "keys"),
                         ("status", "record", "key_values", "scope", "excluded_metadata",
                          "archive_digest", "correspondence", "acquisition"), "hash_contract")
    if data["id"] != HASH_CONTRACT_ID or data["digest"] != "SHA-256" or data["keys"] != ["mode", "path", "sha256", "size", "type"]:
        raise ValidationError("hash_contract: unknown hash semantics")
    for key in ("status", "record", "scope", "excluded_metadata", "archive_digest", "correspondence", "acquisition"):
        if key in data:
            text(data[key], "hash_contract." + key)
    if "key_values" in data:
        values = object_fields(data["key_values"], ("mode", "path", "sha256", "size", "type"), (), "hash_contract.key_values")
        for key, item in values.items():
            text(item, "hash_contract.key_values." + key)
    return data["id"]


def _license(value, repo, commit, required):
    if value is None:
        if required:
            raise ValidationError("license: missing unapproved inventory")
        return None, ()
    data = _object(value, ("review_status", "files"), ("observed_labels", "note", "filename_inventory_rule", "blocked_subtrees"), "license", required)
    _paths(data.get("blocked_subtrees", []), "license.blocked_subtrees")
    review = data.get("review_status")
    if review is not None and review not in UNAPPROVED_REVIEWS:
        raise ValidationError("license.review_status: this census cannot grant approval")
    files = data.get("files", [])
    if not isinstance(files, list) or len(files) > MAX_PATHS:
        raise ValidationError("license.files: expected bounded inventory")
    paths = []
    for record in files:
        item = object_fields(record, ("path", "type", "mode", "size", "sha256", "git_blob_sha1", "url"), (), "license.files[]")
        path = _path(item["path"], "license.path")
        if item["type"] != "file" or item["mode"] not in ("100644", "100755"):
            raise ValidationError("license.files[]: expected regular Git file")
        _integer(item["size"], "license.size")
        digest(item["sha256"], "license.sha256")
        digest(item["git_blob_sha1"], "license.git_blob_sha1", 40)
        if commit is None or item["url"] != "https://github.com/" + repo + "/blob/" + commit + "/" + quote(path, safe="/"):
            raise ValidationError("license.url: expected immutable source file URL")
        paths.append(path)
    _paths(paths, "license.files")
    labels = data.get("observed_labels", [])
    if not isinstance(labels, list) or len(labels) > MAX_PATHS:
        raise ValidationError("license.observed_labels: expected bounded list")
    for label in labels:
        text(label, "license.observed_labels[]")
    return review, tuple(paths)


def _content(value, required):
    if value is None:
        if required:
            raise ValidationError("content: missing census evidence")
        return None, None, (), (), None, None
    fields = ("repository_tree_sha256", "skill_tree_sha256", "regular_file_count", "regular_file_bytes",
              "skill_tree_files", "skill_md_count", "skill_md_paths", "skill_roots", "archive_git_correspondence")
    data = _object(value, fields, (), "content", required)
    repo_sha = digest(data["repository_tree_sha256"], "content.repository_tree_sha256") if data.get("repository_tree_sha256") is not None else None
    skill_sha = digest(data["skill_tree_sha256"], "content.skill_tree_sha256") if data.get("skill_tree_sha256") is not None else None
    paths = _paths(data.get("skill_md_paths", []), "content.skill_md_paths")
    if any(p.rsplit("/", 1)[-1] != "SKILL.md" for p in paths):
        raise ValidationError("content.skill_md_paths: expected exact SKILL.md basename")
    roots = _paths(data.get("skill_roots", []), "content.skill_roots", root=True)
    expected_roots = {p.rsplit("/", 1)[0] if "/" in p else "." for p in paths}
    if "skill_roots" in data and set(roots) != expected_roots:
        raise ValidationError("content.skill_roots: roots disagree with SKILL.md parents")
    _case_safe(paths + roots, "content")
    counts = {}
    for key in ("regular_file_count", "regular_file_bytes", "skill_tree_files", "skill_md_count"):
        if required or data.get(key) is not None:
            counts[key] = _integer(data.get(key), "content." + key)
    skill_count = counts.get("skill_md_count")
    tracked_count = counts.get("regular_file_count")
    if skill_count is not None and ("skill_md_paths" not in data or skill_count != len(paths)):
        raise ValidationError("content.skill_md_count: path count mismatch")
    if required and skill_count == 0 and skill_sha != EMPTY_TREE_SHA256:
        raise ValidationError("skill_tree_sha256: zero-file scope requires empty record digest")
    if "skill_tree_files" in counts and (counts["skill_tree_files"] < len(paths) or tracked_count is not None and counts["skill_tree_files"] > tracked_count):
        raise ValidationError("content.skill_tree_files: inconsistent subtree count")
    if "archive_git_correspondence" in data:
        match = _object(data["archive_git_correspondence"], ("status", "difference_paths", "git_tree_items", "archive_files"), (), "archive_git_correspondence", required)
        differences = _paths(match.get("difference_paths", []), "difference_paths")
        if "status" in match:
            if match["status"] not in ("MATCH", "MISMATCH", "BLOCKED", "MISSING", "UNOBSERVED"):
                raise ValidationError("archive_git_correspondence: unknown status")
            if match["status"] == "MATCH" and differences:
                raise ValidationError("archive_git_correspondence: MATCH cannot contain differences")
        if required and match["status"] != "MATCH":
            raise ValidationError("archive_git_correspondence: missing exact MATCH")
        for key in ("git_tree_items", "archive_files"):
            if key in match:
                count = _integer(match[key], "archive_git_correspondence." + key)
                if required and count != tracked_count:
                    raise ValidationError("archive_git_correspondence: census count mismatch")
    return repo_sha, skill_sha, paths, roots, skill_count, tracked_count


def _bounds(value, archive_bytes, content, tracked_count, required, archive_url=None):
    if value is None:
        if required:
            raise ValidationError("bounded_acquisition: missing limits")
        return
    data = object_fields(value, ("compressed_limit_bytes", "expanded_limit_bytes", "per_file_limit_bytes",
                                "entry_limit", "expanded_stream_bytes", "extraction"), ("retry",), "bounded_acquisition")
    for key in data.keys() - {"extraction", "retry"}:
        _integer(data[key], "bounded_acquisition." + key, 0 if key == "expanded_stream_bytes" else 1)
    if "retry" in data:
        retry = object_fields(data["retry"], ("initial_cap_bytes", "revised_cap_bytes", "reason", "initial_evidence"), (), "bounded_acquisition.retry")
        initial = _integer(retry["initial_cap_bytes"], "retry.initial_cap_bytes", 1)
        revised = _integer(retry["revised_cap_bytes"], "retry.revised_cap_bytes", 1)
        if initial >= revised or revised != data["compressed_limit_bytes"]:
            raise ValidationError("retry: recorded revised cap disagrees")
        text(retry["reason"], "retry.reason")
        failed = object_fields(retry["initial_evidence"], ("requested_url", "observed_at", "http_status", "final_url", "complete", "error"), (), "retry.initial_evidence")
        if failed["complete"] is not False:
            raise ValidationError("retry.initial_evidence: failed acquisition must stay incomplete")
        text(failed["error"], "retry.initial_evidence.error")
        _evidence({key: item for key, item in failed.items() if key != "error"}, "retry.initial_evidence", False, archive_url)

    if not text(data["extraction"], "bounded_acquisition.extraction").startswith("NONE;"):
        raise ValidationError("bounded_acquisition: census extraction must be NONE")
    if (data["expanded_stream_bytes"] > data["expanded_limit_bytes"]
            or data["per_file_limit_bytes"] > data["expanded_limit_bytes"]
            or archive_bytes is not None and archive_bytes > data["compressed_limit_bytes"]
            or tracked_count is not None and tracked_count > data["entry_limit"]):
        raise ValidationError("bounded_acquisition: recorded budget exceeded")
    if content and content.get("regular_file_bytes") is not None and content["regular_file_bytes"] > data["expanded_stream_bytes"]:
        raise ValidationError("bounded_acquisition: recorded file bytes exceed inspected stream")


def _source(value, hash_contract_id):
    data = object_fields(value, ("repository", "canonical_repository", "repository_url", "acquisition_status", "installable"),
                         ("pin", "archive", "content", "bounded_acquisition", "license", "metadata", "validation",
                          "registry_disposition", "source_tree_evidence", "acquisition_reason"), "source")
    repo = repository(data["repository"])
    canonical = repository(data["canonical_repository"], "canonical_repository")
    if canonical.casefold() != repo.casefold() or data["repository_url"] != "https://github.com/" + repo:
        raise ValidationError("source: canonical GitHub identity or URL mismatch")
    status = data["acquisition_status"]
    if status not in ACQUISITION_STATUSES:
        raise ValidationError("acquisition_status: unsupported explicit status")
    required = status == "PINNED_HASHED"
    if data["installable"] is not False:
        raise ValidationError("installable: a census cannot authorize installation")
    disposition = data.get("registry_disposition", "UNASSESSED_NOT_LISTED")
    if disposition not in V3_REGISTRY_DISPOSITIONS:
        raise ValidationError("registry_disposition: source evidence cannot grant listing")
    if required and hash_contract_id is None:
        raise ValidationError("hash_contract: required for PINNED_HASHED")
    pin = data.get("pin")
    commit = None
    if pin is not None:
        pin = _object(pin, ("commit", "commit_url", "git_tree_sha1", "evidence"),
                      ("commit_date", "author_date", "default_branch_at_observation"), "pin", required)
        if pin.get("commit") is not None:
            commit = digest(pin["commit"], "pin.commit", 40)
        if "commit_url" in pin and (commit is None or pin["commit_url"] != "https://github.com/" + repo + "/commit/" + commit):
            raise ValidationError("pin.commit_url: expected exact immutable URL")
        if "git_tree_sha1" in pin:
            digest(pin["git_tree_sha1"], "pin.git_tree_sha1", 40)
        _evidence(pin.get("evidence"), "pin.evidence", required)
        if pin.get("evidence") is not None:
            for key in ("requested_url", "final_url"):
                if key in pin["evidence"] and not pin["evidence"][key].startswith("https://api.github.com/repos/" + repo + "/commits/"):
                    raise ValidationError("pin.evidence: repository does not match")
    elif required:
        raise ValidationError("pin: missing immutable pin")
    archive = data.get("archive")
    archive_sha = None
    archive_bytes = None
    if archive is not None:
        archive = _object(archive, ("url", "sha256", "bytes", "evidence"), ("quarantine",), "archive", required)
        if archive.get("sha256") is not None:
            archive_sha = digest(archive["sha256"], "archive.sha256")
        if archive.get("bytes") is not None:
            archive_bytes = _integer(archive["bytes"], "archive.bytes", 1)
        archive_url = "https://codeload.github.com/" + repo + "/tar.gz/" + commit if commit else None
        if "url" in archive and (archive_url is None or archive["url"] != archive_url):
            raise ValidationError("archive.url: expected exact codeload commit URL")
        _evidence(archive.get("evidence"), "archive.evidence", required, archive_url, archive_sha, archive_bytes)
    elif required:
        raise ValidationError("archive: missing recorded archive acquisition")
    repo_sha, skill_sha, paths, roots, skill_count, tracked_count = _content(data.get("content"), required)
    review, license_paths = _license(data.get("license"), repo, commit, required)
    if (data.get("license") or {}).get("blocked_subtrees") and disposition != "BLOCKED_CUSTOM_LICENSE_SUBTREES":
        raise ValidationError("registry_disposition: recorded custom-license subtrees must remain explicitly blocked")
    _case_safe(paths + roots + license_paths, "source paths")
    if tracked_count is not None and len(set(paths + license_paths)) > tracked_count:
        raise ValidationError("regular_file_count: smaller than recorded skill/license file union")
    if "validation" in data:
        validation = object_fields(data["validation"], (), ("structure", "static", "prose", "behavior", "science",
                                                          "test", "evaluation", "freshness", "license_approval", "biosafety_approval"), "validation")
        for key, item in validation.items():
            text(item, "validation." + key)
            if key.endswith("_approval") and item != "NOT_GRANTED":
                raise ValidationError("validation: census human approval is not granted")
    tree_url = "https://api.github.com/repos/" + repo + "/git/trees/" + pin["git_tree_sha1"] + "?recursive=1" if pin and pin.get("git_tree_sha1") else None
    _evidence(data.get("source_tree_evidence"), "source_tree_evidence", required, tree_url)
    _bounds(data.get("bounded_acquisition"), archive_bytes, data.get("content"), tracked_count, required, archive.get("url") if archive else None)
    if required and (commit is None or archive_sha is None or archive_bytes is None or repo_sha is None or skill_sha is None or review is None):
        raise ValidationError("PINNED_HASHED: incomplete recorded projection")
    skills = tuple(LockedSkill(p, p.rsplit("/", 1)[0] if "/" in p else ".") for p in paths)
    locked = LockedSource(repo, commit, archive_sha, skill_sha, hash_contract_id, paths, status, skills, repo_sha, review,
                          license_reuse_disposition=disposition if disposition == "BLOCKED_CUSTOM_LICENSE_SUBTREES" else None)
    return locked, skill_count, tracked_count



V4_SCHEMA_VERSION = "ai4s.sources-lock/v4-phase0-proposal"
V4_HASH_CONTRACT_ID = "ai4s.canonical-content-tree/v1-phase0-proposal"
V4_SOURCE_METADATA = (
    "acquired_at", "blocked_reason", "archive", "archive_manifest", "archived", "binary_or_nonutf8_candidate_count",
    "blocked_custom_license_subtrees", "bounded_retry_basis", "case_collision_groups", "commit_url",
    "expected_git_tree_sha1", "git_correspondence", "hash_disagreement_evidence", "human_approvals", "license",
    "license_hash", "license_reuse_disposition", "limits", "pin_evidence", "portability_status", "quarantine",
    "recomputed_git_tree_sha1", "regular_file_count", "repository_tree_manifest", "retained_evidence_recheck",
    "root_license_hashes", "selected_component_manifest", "selected_component_tree_sha256", "selection",
    "skill_md_count", "skill_md_paths", "skill_tree_manifest", "status_dimensions", "symlink_count")
V4_LICENSE_DISPOSITIONS = (
    "NOT_APPROVED_SCOPE_REVIEW_REQUIRED", "BLOCKED_ROOT_LICENSE",
    "BLOCKED_CUSTOM_SUBTREES; OTHER_SCOPE_UNAPPROVED",
    "BLOCKED_CUSTOM_PROPRIETARY_LICENSE; HUMAN_DISPOSITION_REQUIRED")


V4_SELECTION_STATUSES = (
    "CANDIDATE_EVIDENCE_ONLY_NOT_IMPORTABLE", "BLOCKED_SCOPE_PENDING",
    "ARCHIVED_LINEAGE_METADATA_ONLY", "BLOCKED_CUSTOM_LICENSE",
    "BLOCKED_MISSING_GITLINK_VENDOR_PLATFORM", "BLOCKED_ARCHIVE_GIT_BYTE_MISMATCH")


def _exact_paths(value, label):
    """Inert v4 inventory may record case aliases, without granting portability."""
    if not isinstance(value, list) or len(value) > MAX_PATHS:
        raise ValidationError(label + ": expected bounded path list")
    paths = tuple(_path(item, label) for item in value)
    if len(set(paths)) != len(paths):
        raise ValidationError(label + ": duplicate exact path")
    return paths


def _v4_pin(value, repo, commit, expected_tree, required):
    if value is None:
        if required:
            raise ValidationError("pin_evidence: missing recorded provenance")
        return
    if not isinstance(value, dict):
        raise ValidationError("pin_evidence: expected object")
    if "method" in value:
        data = object_fields(value, ("method", "source_file", "source_sha256", "original_observed_at", "commit", "git_tree_sha1"), (), "pin_evidence")
        text(data["method"], "pin_evidence.method")
        _path(data["source_file"], "pin_evidence.source_file")
        digest(data["source_sha256"], "pin_evidence.source_sha256")
        _timestamp(data["original_observed_at"], "pin_evidence.original_observed_at")
        if data["commit"] != commit or data["git_tree_sha1"] != expected_tree:
            raise ValidationError("pin_evidence: retained immutable identities disagree")
    elif "evidence" in value:
        data = object_fields(value, ("commit", "git_tree_sha1", "commit_url", "evidence"),
                             ("commit_date", "author_date", "default_branch_at_observation"), "pin_evidence")
        if data["commit"] != commit or data["git_tree_sha1"] != expected_tree or data["commit_url"] != "https://github.com/" + repo + "/commit/" + commit:
            raise ValidationError("pin_evidence: immutable identities disagree")
        _evidence(data["evidence"], "pin_evidence.evidence", required)
        for key in ("requested_url", "final_url"):
            if data["evidence"] is not None and key in data["evidence"] and not data["evidence"][key].startswith("https://api.github.com/repos/" + repo + "/commits/"):
                raise ValidationError("pin_evidence: repository disagrees")
    else:
        data = object_fields(value, ("requested_url", "acquired_at", "http_status", "final_url", "bytes", "sha256", "complete"),
                             ("body_file", "byte_limit", "time_limit_seconds", "headers", "finished_at"), "pin_evidence")
        projected = {key: data[key] for key in ("requested_url", "http_status", "final_url", "bytes", "sha256", "complete")}
        projected["observed_at"] = data["acquired_at"]
        # The API observation may name main; the immutable source pin stays
        # the separately recorded commit/commit_url and exact codeload URL.
        _evidence(projected, "pin_evidence", required)
        allowed_urls = ("https://api.github.com/repos/" + repo + "/commits/" + str(commit),
                        "https://api.github.com/repos/" + repo + "/commits/main")
        if any(projected[key] not in allowed_urls for key in ("requested_url", "final_url")):
            raise ValidationError("pin_evidence: unsupported repository observation URL")

        for key in ("body_file",):
            if key in data:
                _path(data[key], "pin_evidence." + key)


def _v4_license(value, source, required):
    if value is None:
        if required:
            raise ValidationError("license: missing recorded unapproved inventory")
        return None
    data = object_fields(value, ("filename_inventory_only", "root_license_paths", "license_files", "license_set_sha256", "root_status", "human_approval"),
                         ("custom_or_unknown_license_paths", "scope_caveat"), "license")
    if data["filename_inventory_only"] is not True or data["human_approval"] != "NOT_GRANTED":
        raise ValidationError("license: inventory cannot grant human approval")
    if data["license_set_sha256"] is not None:
        digest(data["license_set_sha256"], "license.license_set_sha256")
    elif data["license_files"] != [] or data["root_status"] != "BLOCKED_NO_ROOT_LICENSE_FOUND" or source.get("license_reuse_disposition") != "BLOCKED_ROOT_LICENSE":
        raise ValidationError("license: absent inventory hash must retain an explicit empty-inventory reuse block")

    if source.get("license_hash") != data["license_set_sha256"]:
        raise ValidationError("license: inventory hash disagreement")
    if data["root_status"] not in ("ROOT_TEXT_OBSERVED_UNAPPROVED", "BLOCKED_NO_ROOT_LICENSE_FOUND", "BLOCKED_UNKNOWN_OR_CUSTOM_ROOT_LICENSE"):
        raise ValidationError("license.root_status: unsupported unapproved status")
    records = data["license_files"]
    if not isinstance(records, list) or len(records) > MAX_PATHS:
        raise ValidationError("license.license_files: expected bounded inventory")
    hashes = {}
    for item in records:
        item = object_fields(item, ("path", "type", "mode", "size", "sha256", "git_blob_sha1", "label", "license_text_approval"), (), "license.license_files[]")
        path = _path(item["path"], "license.path")
        if path in hashes or item["type"] != "file" or item["mode"] not in ("100644", "100755") or item["license_text_approval"] != "NOT_GRANTED":
            raise ValidationError("license: duplicate, nonregular or approved inventory entry")
        _integer(item["size"], "license.size")
        hashes[path] = digest(item["sha256"], "license.sha256")
        digest(item["git_blob_sha1"], "license.git_blob_sha1", 40)
        text(item["label"], "license.label")
    root_paths = _paths(data["root_license_paths"], "license.root_license_paths")
    root_hashes = source.get("root_license_hashes", [])
    if not isinstance(root_hashes, list) or len(root_hashes) > MAX_PATHS:
        raise ValidationError("root_license_hashes: expected bounded inventory")
    observed = {}
    for item in root_hashes:
        item = object_fields(item, ("path", "sha256"), (), "root_license_hashes[]")
        path = _path(item["path"], "root_license_hashes.path")
        if path in observed or path not in hashes or digest(item["sha256"], "root_license_hashes.sha256") != hashes[path]:
            raise ValidationError("root_license_hashes: inventory disagreement")
        observed[path] = item["sha256"]
    if set(observed) != set(root_paths):
        raise ValidationError("root_license_hashes: root inventory disagreement")
    if data["root_status"] == "BLOCKED_NO_ROOT_LICENSE_FOUND" and root_paths or data["root_status"] != "BLOCKED_NO_ROOT_LICENSE_FOUND" and not root_paths:
        raise ValidationError("license.root_status: root file observation disagrees")
    if source.get("regular_file_count") is not None and len(set(hashes) | set(source.get("skill_md_paths", []))) > source["regular_file_count"]:
        raise ValidationError("regular_file_count: smaller than recorded skill/license file union")
    _exact_paths(data.get("custom_or_unknown_license_paths", []), "license.custom_or_unknown_license_paths")
    return data["human_approval"]


def _v4_source(value, hash_contract_id):
    data = object_fields(value, ("repository", "repository_url", "commit", "archive_sha256", "skill_tree_sha256",
                                 "repository_tree_sha256", "acquisition_status", "installable", "registry_disposition", "selection"),
                         tuple(field for field in V4_SOURCE_METADATA if field != "selection"), "v4 source")
    repo = repository(data["repository"])
    if data["repository_url"] != "https://github.com/" + repo:
        raise ValidationError("repository_url: source identity disagrees")
    status = data["acquisition_status"]
    if status not in ACQUISITION_STATUSES:
        raise ValidationError("acquisition_status: unsupported explicit status")
    required = status == "PINNED_HASHED"
    if data["installable"] is not False or data["registry_disposition"] != "NOT_LISTED":
        raise ValidationError("v4 source: census cannot authorize installation or listing")
    commit = digest(data["commit"], "commit", 40) if data["commit"] is not None else None
    if required and commit is None:
        raise ValidationError("commit: PINNED_HASHED requires immutable pin")
    if required and "commit_url" not in data:
        raise ValidationError("commit_url: PINNED_HASHED requires exact immutable URL")
    if "commit_url" in data and data["commit_url"] != "https://github.com/" + repo + "/commit/" + str(commit):
        raise ValidationError("commit_url: expected exact immutable URL")
    hashes = {}
    for key in ("archive_sha256", "skill_tree_sha256", "repository_tree_sha256", "license_hash", "selected_component_tree_sha256"):
        item = data.get(key)
        hashes[key] = digest(item, key) if item is not None else None
    if required and any(hashes[key] is None for key in ("archive_sha256", "skill_tree_sha256", "repository_tree_sha256")):
        raise ValidationError("PINNED_HASHED: missing recorded hashes")
    for key in ("expected_git_tree_sha1", "recomputed_git_tree_sha1"):
        if data.get(key) is not None:
            digest(data[key], key, 40)
    match = data.get("git_correspondence")
    if match not in (None, "MATCH", "UNKNOWN_OR_MISMATCH", "BLOCKED", "MISSING", "UNOBSERVED"):
        raise ValidationError("git_correspondence: unsupported explicit status")
    if match == "MATCH" and (data.get("expected_git_tree_sha1") is None or data.get("expected_git_tree_sha1") != data.get("recomputed_git_tree_sha1")):
        raise ValidationError("git_correspondence: MATCH identities disagree")
    if required and match != "MATCH":
        raise ValidationError("PINNED_HASHED: requires recorded Git correspondence MATCH")
    reason = data.get("blocked_reason")
    if status == "BLOCKED" or reason is not None:
        text(reason, "blocked_reason")
    if required and reason is not None:
        raise ValidationError("PINNED_HASHED: cannot conceal a recorded acquisition block")
    archive = data.get("archive")
    archive_bytes = 0
    transport = None
    if archive is not None:
        archive = object_fields(archive, ("url", "sha256", "bytes", "transport_status", "acquired_at"),
                                ("rechecked_at", "reused_from_v3", "source_lock_sha256", "download_repeated", "receipt"), "archive")
        if commit is None or archive["url"] != "https://codeload.github.com/" + repo + "/tar.gz/" + commit:
            raise ValidationError("archive.url: expected exact codeload commit URL")
        if digest(archive["sha256"], "archive.sha256") != hashes["archive_sha256"]:
            raise ValidationError("archive.sha256: flattened digest disagreement")
        archive_bytes = _integer(archive["bytes"], "archive.bytes", 1)
        transport = archive["transport_status"]
        if transport not in ("COMPLETE", "BLOCKED", "MISSING", "UNOBSERVED"):
            raise ValidationError("archive.transport_status: unsupported explicit status")
        _timestamp(archive["acquired_at"], "archive.acquired_at")
        if "receipt" in archive:
            _path(archive["receipt"], "archive.receipt")
    if required and (archive is None or transport != "COMPLETE"):
        raise ValidationError("PINNED_HASHED: requires recorded complete archive transport")
    _v4_pin(data.get("pin_evidence"), repo, commit, data.get("expected_git_tree_sha1"), required)
    paths = _paths(data.get("skill_md_paths", []), "skill_md_paths")
    if any(path.rsplit("/", 1)[-1] != "SKILL.md" for path in paths):
        raise ValidationError("skill_md_paths: expected exact SKILL.md basename")
    counts = {}
    for key in ("skill_md_count", "regular_file_count", "symlink_count", "binary_or_nonutf8_candidate_count"):
        if required or data.get(key) is not None:
            counts[key] = _integer(data.get(key), key)
    if counts.get("skill_md_count") is not None and counts["skill_md_count"] != len(paths):
        raise ValidationError("skill_md_count: path count disagrees")
    if counts.get("skill_md_count") == 0 and hashes["skill_tree_sha256"] is not None and hashes["skill_tree_sha256"] != EMPTY_TREE_SHA256:
        raise ValidationError("skill_tree_sha256: zero-file scope requires empty record digest")
    if "regular_file_count" in counts and counts["regular_file_count"] < len(paths):
        raise ValidationError("regular_file_count: cannot be smaller than skill path count")
    limits = data.get("limits")
    if required and limits is None:
        raise ValidationError("limits: missing recorded acquisition bounds")
    if limits is not None:
        limits = object_fields(limits, ("compressed_bytes", "expanded_stream_bytes", "individual_file_bytes", "members", "seconds"), (), "limits")
        for key, item in limits.items():
            _integer(item, "limits." + key, 1)
        if archive_bytes > limits["compressed_bytes"] or counts.get("regular_file_count", 0) + counts.get("symlink_count", 0) > limits["members"] or limits["individual_file_bytes"] > limits["expanded_stream_bytes"]:
            raise ValidationError("limits: recorded acquisition budget exceeded")
    portability = data.get("portability_status")
    if required and portability is None:
        raise ValidationError("portability_status: v4 requires explicit observation")
    if portability not in (None, "NO_CASE_COLLISIONS_OBSERVED", "REVIEW_CASE_COLLISIONS", "BLOCKED", "MISSING", "UNOBSERVED"):
        raise ValidationError("portability_status: unsupported explicit status")
    collisions = data.get("case_collision_groups", [])
    if not isinstance(collisions, list) or len(collisions) > MAX_PATHS:
        raise ValidationError("case_collision_groups: expected bounded list")
    for group in collisions:
        aliases = _exact_paths(group, "case_collision_groups[]")
        if len(aliases) < 2 or len({path.casefold() for path in aliases}) != 1:
            raise ValidationError("case_collision_groups: invalid case aliases")
    if collisions and portability != "REVIEW_CASE_COLLISIONS" or portability == "REVIEW_CASE_COLLISIONS" and not collisions:
        raise ValidationError("portability_status: collision evidence disagrees")
    review = _v4_license(data.get("license"), data, required)
    reuse = data.get("license_reuse_disposition")
    if reuse is not None and reuse not in V4_LICENSE_DISPOSITIONS:
        raise ValidationError("license_reuse_disposition: unsupported or approved status")
    if required and reuse is None:
        raise ValidationError("license_reuse_disposition: missing unapproved scope status")
    approvals = data.get("human_approvals")
    if approvals is not None:
        approvals = object_fields(approvals, (), ("biosafety", "clinical", "custom_license", "critical_security_disposition", "delisting", "external_publication"), "human_approvals")
        if any(item != "NOT_GRANTED" for item in approvals.values()):
            raise ValidationError("human_approvals: census cannot grant approval")
    selection = object_fields(data["selection"], ("status", "approved_for_import"),
                              ("scope_tags", "rationale", "file_count", "exact_paths", "candidate_paths", "domain_dependency_closure", "archive_scope_note"), "selection")
    if selection["approved_for_import"] is not False or selection["status"] not in V4_SELECTION_STATUSES:
        raise ValidationError("selection: census scope cannot authorize import")
    if required and selection["status"] in ("BLOCKED_SCOPE_PENDING", "BLOCKED_MISSING_GITLINK_VENDOR_PLATFORM", "BLOCKED_ARCHIVE_GIT_BYTE_MISMATCH"):
        raise ValidationError("selection: pending scope cannot be PINNED_HASHED")
    selected_paths = _exact_paths(selection.get("exact_paths", selection.get("candidate_paths", [])), "selection paths")
    if archive is not None and any(path.rsplit("/", 1)[-1] == "SKILL.md" and path not in paths for path in selected_paths):
        raise ValidationError("selection: selected SKILL.md is absent from recorded census")
    if "file_count" in selection and _integer(selection["file_count"], "selection.file_count") != len(selected_paths):
        raise ValidationError("selection.file_count: count disagrees")
    for key in ("archive_manifest", "repository_tree_manifest", "skill_tree_manifest", "selected_component_manifest"):
        if data.get(key) is not None:
            _path(data[key], key)
    dimensions = data.get("status_dimensions", {})
    dimensions = object_fields(dimensions, (), ("static", "prose", "dependency", "vulnerability", "behavioral", "scientific", "evaluation", "test", "freshness"), "status_dimensions")
    for key, item in dimensions.items():
        text(item, "status_dimensions." + key)
    skills = tuple(LockedSkill(path, path.rsplit("/", 1)[0] if "/" in path else ".") for path in paths)
    locked = LockedSource(repo, commit, hashes["archive_sha256"], hashes["skill_tree_sha256"], hash_contract_id,
                          paths, status, skills, hashes["repository_tree_sha256"], review,
                          portability, reuse, reason, selection["status"], transport)
    return locked, counts.get("regular_file_count", 0), archive_bytes


def _validate_v4_lock(document):
    data = object_fields(document, ("schema_version", "hash_contract", "summary", "sources"),
                         ("created_at", "phase", "scope", "exit", "all_sources_acquisition_complete",
                          "catalog_security_science_evaluation_complete", "execution_performed", "upstream_mutation_performed",
                          "external_publication_performed", "third_party_skill_registry_copy_performed", "prior_v3",
                          "inventory_basis", "tooling", "receipt_trust", "excluded_repositories", "stopping_condition", "next_three_actions"), "v4 lock")
    contract = object_fields(data["hash_contract"], ("id", "algorithm", "keys"),
                             ("serialization", "regular_files", "symlinks", "case_collisions", "skill_scope", "selected_component_scope",
                              "empty_skill_tree", "license_hash", "archive_hash", "git_identity", "method_revision"), "hash_contract")
    if contract["id"] != V4_HASH_CONTRACT_ID or contract["algorithm"] != "SHA-256" or contract["keys"] != ["mode", "path", "sha256", "size", "type"]:
        raise ValidationError("hash_contract: unsupported v4 recorded hash semantics")
    for key, item in contract.items():
        if key != "keys":
            text(item, "hash_contract." + key)
    for key in ("catalog_security_science_evaluation_complete", "execution_performed", "upstream_mutation_performed",
                "external_publication_performed", "third_party_skill_registry_copy_performed"):
        if key in data and data[key] is not False:
            raise ValidationError(key + ": census does not establish execution or approval")
    sources = data["sources"]
    if not isinstance(sources, list) or len(sources) > MAX_SOURCES:
        raise ValidationError("sources: expected bounded list")
    results = tuple(_v4_source(item, contract["id"]) for item in sources)
    identities = [item[0].repository.casefold() for item in results]
    if len(set(identities)) != len(identities):
        raise ValidationError("sources: duplicate canonical repository")
    summary = object_fields(data["summary"], ("total_lock_entries", "literal_skill_md_paths", "regular_file_records", "archive_bytes_total"),
                            ("public_szl_inventory", "public_szl_archived", "szl_sources_selected_and_archives_acquired",
                             "non_szl_explicit_sources", "archives_acquired_in_full", "byte_identity_correspondence_complete",
                             "source_identity_blocked", "scope_pending_blocked", "excluded_szl_repositories", "selected_component_file_records",
                             "root_license_missing", "root_custom_license", "sources_with_case_collision_review"), "summary")
    for key, item in summary.items():
        _integer(item, "summary." + key)
    expected = {"total_lock_entries": len(results), "literal_skill_md_paths": sum(len(item[0].skill_paths) for item in results),
                "regular_file_records": sum(item[1] for item in results), "archive_bytes_total": sum(item[2] for item in results)}
    expected.update({
        "archives_acquired_in_full": sum(item[0].archive_transport_status == "COMPLETE" for item in results),
        "byte_identity_correspondence_complete": sum(item.get("git_correspondence") == "MATCH" for item in sources),
        "source_identity_blocked": sum(item[0].acquisition_status == "BLOCKED" and item[0].archive_transport_status is not None for item in results),
        "scope_pending_blocked": sum(item[0].selection_status == "BLOCKED_SCOPE_PENDING" for item in results),
        "selected_component_file_records": sum(item["selection"].get("file_count", 0) for item in sources),
        "root_license_missing": sum((item.get("license") or {}).get("root_status") == "BLOCKED_NO_ROOT_LICENSE_FOUND" for item in sources),
        "root_custom_license": sum((item.get("license") or {}).get("root_status") == "BLOCKED_UNKNOWN_OR_CUSTOM_ROOT_LICENSE" for item in sources),
        "sources_with_case_collision_review": sum(item[0].portability_status == "REVIEW_CASE_COLLISIONS" for item in results),
    })
    for key, item in expected.items():
        if key in summary and summary[key] != item:
            raise ValidationError("summary." + key + ": observed census count disagrees")
    if "all_sources_acquisition_complete" in data:
        if type(data["all_sources_acquisition_complete"]) is not bool:
            raise ValidationError("all_sources_acquisition_complete: expected boolean")
        if data["all_sources_acquisition_complete"] and any(item[0].acquisition_status != "PINNED_HASHED" for item in results):
            raise ValidationError("all_sources_acquisition_complete: blocked sources remain")
    return tuple(item[0] for item in results)


def validate_lock(document: dict) -> Tuple[LockedSource, ...]:
    """Check recorded evidence consistency, without external verification."""
    if isinstance(document, dict) and document.get("schema_version") == V4_SCHEMA_VERSION:
        return _validate_v4_lock(document)
    data = object_fields(document, ("schema_version", "sources", "hash_contract", "total_sources", "total_skill_md_files", "total_tracked_files"),
                         ("purpose", "created_at", "input_payload", "phase", "exit", "execution_performed",
                          "publication_performed", "prior_report", "concurrent_pr_observation", "next_three_actions"), "source lock")
    if data["schema_version"] not in ACCEPTED_SCHEMA_VERSIONS:
        raise ValidationError("schema_version: unsupported recorded census contract")
    for key in ("execution_performed", "publication_performed"):
        if key in data and data[key] is not False:
            raise ValidationError(key + ": accepts only an unexecuted, unpublished census")
    sources = data["sources"]
    if not isinstance(sources, list) or len(sources) > MAX_SOURCES:
        raise ValidationError("sources: expected bounded list")
    if _integer(data["total_sources"], "total_sources") != len(sources):
        raise ValidationError("total_sources: census count mismatch")
    hash_contract_id = _hash_contract(data["hash_contract"])
    results = tuple(_source(source, hash_contract_id) for source in sources)
    identities = [item[0].repository.casefold() for item in results]
    if len(set(identities)) != len(identities):
        raise ValidationError("sources: duplicate canonical repository")
    for key, index in (("total_skill_md_files", 1), ("total_tracked_files", 2)):
        counts = [item[index] for item in results]
        if any(count is None for count in counts):
            if data[key] is not None:
                raise ValidationError(key + ": unknown source counts require explicit null total")
        elif data[key] is None or _integer(data[key], key) != sum(counts):
            raise ValidationError(key + ": census count mismatch")
    return tuple(item[0] for item in results)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only offline source census check; no approval or execution.")
    parser.add_argument("lock", help="Local JSON census file (2 MiB maximum)")
    args = parser.parse_args(argv)
    try:
        sources = validate_lock(load_json_file(args.lock))
    except ValidationError as exc:
        print("source lock invalid: " + str(exc), file=sys.stderr)
        return 1
    print(json.dumps({"recorded_sources": len(sources), "recorded_skill_paths": sum(len(item.skill_paths) for item in sources),
                      "acquisition_statuses": [item.acquisition_status for item in sources],
                      "result": "RECORDED_CENSUS_CONSISTENT", "archive_or_tree_bytes_reverified": False,
                      "install_or_listing_authorized": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
