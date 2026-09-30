"""Typed, non-installable trust catalog and inert diagnostic-auditor adapter.

This foundation accepts JSON only. It executes no auditor, skill, provider or
scanner. Listing is deliberately unavailable until authenticated human-review
and full evidence contracts exist.
"""
import argparse
import dataclasses
import datetime as dt
import enum
import hashlib
import json
import re
import sys
from typing import Optional, Tuple

from trust_common import (ValidationError, canonical_sha256, digest, object_fields,
                          portable_path, repository, strict_json, text, load_json_file)

ENTRY_VERSION = "ai4s.skills-entry/v0-foundation"
AUDITOR_VERSION = "0.1.0-review.1"
AUDITOR_CODE_BUNDLE = "33d97bb1c173b3a8760b8c576bca5c87204815be5f4329532b957841764d1e26"
AUDITOR_RECEIPT = "sha256(canonical JSON excluding receipt and receipt_contract); unsigned diagnostic only"


class State(str, enum.Enum):
    CANDIDATE = "CANDIDATE"
    REVIEW = "REVIEW"
    LISTED = "LISTED"
    BLOCKED = "BLOCKED"
    STALE = "STALE"
    DELISTED = "DELISTED"


class Facet(str, enum.Enum):
    STATIC = "STATIC"
    PROSE = "PROSE"
    BEHAVIOR = "BEHAVIOR"
    SCIENCE = "SCIENCE"
    TEST = "TEST"
    EVALUATION = "EVALUATION"
    FRESHNESS = "FRESHNESS"


class Status(str, enum.Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    MISSING = "MISSING"
    UNOBSERVED = "UNOBSERVED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


REVIEW_KINDS = ("RIGHTS", "SECURITY", "SAFETY_SCOPE", "SCIENCE_APPLICABILITY", "LISTING")


def timestamp(value, label):
    text(value, label)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)", value):
        raise ValidationError(label + ": RFC3339 UTC timestamp required")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError(label + ": invalid timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != dt.timedelta(0):
        raise ValidationError(label + ": UTC offset required")
    return parsed


def choice(value, allowed, label):
    if not isinstance(value, str) or value not in allowed:
        raise ValidationError(label + ": unknown value")
    return value


def array(value, label, limit=1000):
    if not isinstance(value, list) or len(value) > limit:
        raise ValidationError(label + ": expected bounded array")
    return value


@dataclasses.dataclass(frozen=True)
class Source:
    repository: str
    commit: str
    path: str
    archive_sha256: str
    source_skill_tree_sha256: str
    source_hash_contract_id: str
    lock_sha256: str

    @classmethod
    def parse(cls, value):
        names = tuple(f.name for f in dataclasses.fields(cls))
        object_fields(value, names, (), "source")
        repository(value["repository"])
        digest(value["commit"], "source.commit", 40)
        if not isinstance(value["path"], str):
            raise ValidationError("source.path: expected string (empty denotes repository root)")
        if value["path"]:
            portable_path(value["path"], "source.path")
        for name in ("archive_sha256", "source_skill_tree_sha256", "lock_sha256"):
            digest(value[name], "source." + name)
        text(value["source_hash_contract_id"], "source.source_hash_contract_id")
        return cls(**value)


@dataclasses.dataclass(frozen=True)
class Evidence:
    status: str
    coverage: str
    reason: str
    artifacts: Tuple[str, ...] = ()
    checked_at: Optional[str] = None
    expires_at: Optional[str] = None
    checker_sha256: Optional[str] = None

    @classmethod
    def parse(cls, value):
        object_fields(value, tuple(f.name for f in dataclasses.fields(cls)), (), "evidence")
        choice(value["status"], {s.value for s in Status}, "evidence.status")
        choice(value["coverage"], {"NONE", "PARTIAL", "COMPLETE"}, "evidence.coverage")
        text(value["reason"], "evidence.reason")
        artifacts = tuple(digest(v, "evidence.artifact") for v in array(value["artifacts"], "artifacts", 16))
        if len(set(artifacts)) != len(artifacts):
            raise ValidationError("evidence: duplicate artifacts")
        checked = timestamp(value["checked_at"], "checked_at") if value["checked_at"] is not None else None
        expires = timestamp(value["expires_at"], "expires_at") if value["expires_at"] is not None else None
        if expires and (checked is None or expires <= checked):
            raise ValidationError("evidence: expiry must follow check")
        if value["checker_sha256"] is not None:
            digest(value["checker_sha256"], "evidence.checker_sha256")
        if value["status"] == "PASS" and (value["coverage"] != "COMPLETE" or not artifacts or checked is None or value["checker_sha256"] is None):
            raise ValidationError("evidence: PASS requires complete dated checker-bound artifacts")
        return cls(value["status"], value["coverage"], value["reason"], artifacts,
                   value["checked_at"], value["expires_at"], value["checker_sha256"])


@dataclasses.dataclass(frozen=True)
class Review:
    status: str
    receipt_sha256: Optional[str]
    reason: str

    @classmethod
    def parse(cls, value):
        object_fields(value, ("status", "receipt_sha256", "reason"), (), "review")
        choice(value["status"], {"MISSING", "BLOCKED", "UNOBSERVED", "CLAIMED_APPROVED"}, "review.status")
        text(value["reason"], "review.reason")
        if value["receipt_sha256"] is not None:
            digest(value["receipt_sha256"], "review.receipt_sha256")
        if value["status"] == "CLAIMED_APPROVED" and value["receipt_sha256"] is None:
            raise ValidationError("review: claimed approval requires receipt reference")
        return cls(**value)


@dataclasses.dataclass(frozen=True)
class Diagnostic:
    report_sha256: str
    entry_receipt_sha256: str
    auditor_tree_sha256: str
    snapshot_sha256: str
    status: str

    @classmethod
    def parse(cls, value):
        object_fields(value, tuple(f.name for f in dataclasses.fields(cls)), (), "diagnostic")
        for key in ("report_sha256", "entry_receipt_sha256", "auditor_tree_sha256", "snapshot_sha256"):
            digest(value[key], "diagnostic." + key)
        choice(value["status"], {"UNSIGNED_HONEST", "REVIEW", "FAIL", "BLOCKED"}, "diagnostic.status")
        return cls(**value)


@dataclasses.dataclass(frozen=True)
class Entry:
    id: str
    state: State
    source: Source
    facets: Tuple[Tuple[Facet, Evidence], ...]
    human_gates: Tuple[Tuple[str, Review], ...]
    diagnostic: Optional[Diagnostic] = None

    def to_dict(self):
        return {"schema_version": ENTRY_VERSION, "id": self.id, "state": self.state.value,
                "installable": False, "attestation": "UNSIGNED_HONEST",
                "source": dataclasses.asdict(self.source),
                "facets": {k.value: dataclasses.asdict(v) | {"artifacts": list(v.artifacts)} for k, v in self.facets},
                "human_gates": {k: dataclasses.asdict(v) for k, v in self.human_gates},
                "diagnostic": dataclasses.asdict(self.diagnostic) if self.diagnostic else None}

    @classmethod
    def parse(cls, value):
        object_fields(value, ("schema_version", "id", "state", "installable", "attestation", "source", "facets", "human_gates", "diagnostic"), (), "entry")
        if value["schema_version"] != ENTRY_VERSION or value["installable"] is not False or value["attestation"] != "UNSIGNED_HONEST":
            raise ValidationError("entry: unsupported version or trust/install assertion")
        state = State(choice(value["state"], {s.value for s in State}, "state"))
        if state == State.LISTED:
            raise ValidationError("LISTED unavailable: authenticated human gates are not implemented")
        source = Source.parse(value["source"])
        expected_id = hashlib.sha256((source.repository.casefold() + "\0" + source.commit + "\0" + source.path).encode("utf-8")).hexdigest()
        if digest(value["id"], "entry.id") != expected_id:
            raise ValidationError("entry: identity does not match source tuple")
        object_fields(value["facets"], tuple(f.value for f in Facet), (), "facets")
        facets = tuple((f, Evidence.parse(value["facets"][f.value])) for f in Facet)
        object_fields(value["human_gates"], REVIEW_KINDS, (), "human_gates")
        reviews = tuple((k, Review.parse(value["human_gates"][k])) for k in REVIEW_KINDS)
        if any(e.status in {"FAIL", "BLOCKED"} for _, e in facets) and state not in {State.BLOCKED, State.STALE, State.DELISTED}:
            raise ValidationError("entry: negative evidence requires blocked/stale/delisted state")
        if dict(facets)[Facet.EVALUATION].status == "PASS":
            raise ValidationError("EVALUATION PASS unavailable: paired-run receipt contract is not implemented")
        diagnostic = Diagnostic.parse(value["diagnostic"]) if value["diagnostic"] is not None else None
        return cls(expected_id, state, source, facets, reviews, diagnostic)


def listing_blockers(entry, now):
    Entry.parse(entry.to_dict())
    if not isinstance(now, dt.datetime) or now.tzinfo is None:
        raise ValidationError("listing: timezone-aware clock required")
    blockers = ["authenticated-human-review-and-listing-policy-unavailable"]
    for facet, evidence in entry.facets:
        if facet == Facet.EVALUATION:
            continue  # optional paired evaluation cannot be represented as PASS yet
        if evidence.status != "PASS" or evidence.coverage != "COMPLETE":
            blockers.append(facet.value + "-required-evidence")
        if evidence.expires_at is None or timestamp(evidence.expires_at, "expires_at") <= now:
            blockers.append(facet.value + "-not-current")
        if evidence.checked_at and timestamp(evidence.checked_at, "checked_at") > now:
            blockers.append(facet.value + "-future-check")
    blockers.extend("human-" + kind for kind, _ in entry.human_gates)
    return tuple(blockers)


def transition(entry, target, now):
    Entry.parse(entry.to_dict())  # do not trust caller-created dataclasses
    try:
        target = State(target)
    except (ValueError, TypeError) as exc:
        raise ValidationError("transition: unknown target") from exc
    if target == State.LISTED:
        raise ValidationError("listing blocked: " + ",".join(listing_blockers(entry, now)))
    edges = {State.CANDIDATE: {State.REVIEW, State.BLOCKED, State.STALE, State.DELISTED},
             State.REVIEW: {State.BLOCKED, State.STALE, State.DELISTED},
             State.BLOCKED: {State.REVIEW, State.STALE, State.DELISTED},
             State.STALE: {State.REVIEW, State.BLOCKED, State.DELISTED},
             State.DELISTED: set()}
    if target not in edges.get(entry.state, set()):
        raise ValidationError("transition: forbidden state edge")
    result = dataclasses.replace(entry, state=target)
    return Entry.parse(result.to_dict())


@dataclasses.dataclass(frozen=True)
class Ingestion:
    status: str
    entries: Tuple[Entry, ...]
    reasons: Tuple[str, ...]

    def to_dict(self):
        return {"schema_version": "ai4s.ingestion/v0-foundation", "status": self.status,
                "installable": False, "reasons": list(self.reasons),
                "entries": [entry.to_dict() for entry in self.entries]}


def ingest_diagnostic(report_bytes, locked_sources, lock_sha256, expected_report_sha256):
    """Consume a pinned diagnostic contract as observations, never a static PASS.

    Archive/census/auditor digests have distinct scopes. Source assertions in the
    report remain unsigned even if they match the lock and its receipt.
    """
    digest(lock_sha256, "lock_sha256")
    digest(expected_report_sha256, "report_sha256")
    if not isinstance(report_bytes, bytes) or len(report_bytes) > 2 * 1024 * 1024:
        raise ValidationError("diagnostic: bounded report bytes required")
    if hashlib.sha256(report_bytes).hexdigest() != expected_report_sha256:
        raise ValidationError("diagnostic: raw report digest mismatch")
    doc = strict_json(report_bytes)
    object_fields(doc, ("schema_version", "checker_version", "generated_at", "status", "completion", "input_errors", "inputs", "entries", "installable", "trust"), (), "diagnostic catalog")
    if doc["schema_version"] != "ai4s.diagnostic-catalog/review-v1" or doc["checker_version"] != AUDITOR_VERSION:
        raise ValidationError("diagnostic: unsupported auditor contract")
    if doc["installable"] is not False or doc["trust"] != "UNSIGNED_HONEST":
        raise ValidationError("diagnostic: install/trust assertion refused")
    status = choice(doc["status"], {"UNSIGNED_HONEST", "REVIEW", "FAIL", "BLOCKED"}, "catalog.status")
    choice(doc["completion"], {"COMPLETE", "PARTIAL"}, "catalog.completion")
    timestamp(doc["generated_at"], "generated_at")
    errors = array(doc["input_errors"], "input_errors", 512)
    for error in errors:
        object_fields(error, ("reason",), ("input",), "input_error")
        if "input" in error:
            text(error["input"], "input_error.input")
        text(error["reason"], "input_error.reason")
    inputs = array(doc["inputs"], "inputs", 512)
    snapshots = {}
    input_ids = set()
    for item in inputs:
        if not isinstance(item, dict):
            raise ValidationError("diagnostic input: expected object")
        label = text(item.get("input"), "input.label")
        if label in input_ids:
            raise ValidationError("diagnostic: duplicate input identity")
        input_ids.add(label)
        if item.get("status") == "COMPLETE":
            object_fields(item, ("input", "status", "coverage", "snapshot_sha256", "skills"), (), "input")
            coverage = item["coverage"]
            object_fields(coverage, ("complete", "scope", "excluded_paths", "files", "bytes", "entries", "max_depth"), (), "coverage")
            if coverage["complete"] is not True or coverage["excluded_paths"] not in ([], [".git"]):
                raise ValidationError("diagnostic: incomplete declared input coverage")
            if coverage["scope"] != "all file content except root-level .git administrative metadata":
                raise ValidationError("diagnostic: unknown coverage scope")
            for key in ("files", "bytes", "entries", "max_depth"):
                if type(coverage[key]) is not int or coverage[key] < 0:
                    raise ValidationError("diagnostic: invalid coverage count")
            if type(item["skills"]) is not int or item["skills"] < 0:
                raise ValidationError("diagnostic: invalid skill count")
            snap = digest(item["snapshot_sha256"], "input.snapshot_sha256")
            if snap in snapshots:
                raise ValidationError("diagnostic: ambiguous input snapshot")
            snapshots[snap] = item["skills"]
        else:
            object_fields(item, ("input", "status"), (), "input")
            choice(item["status"], {"BLOCKED", "PENDING"}, "input.status")
    raw_entries = array(doc["entries"], "entries", 1000)
    sources = {s.repository.casefold(): s for s in locked_sources}
    if len(sources) != len(locked_sources):
        raise ValidationError("diagnostic: ambiguous locked sources")
    incomplete = doc["completion"] != "COMPLETE" or bool(errors) or not raw_entries or any(i["status"] != "COMPLETE" for i in inputs)
    catalog_negative = status in {"FAIL", "BLOCKED"}
    if incomplete and status != "BLOCKED":
        raise ValidationError("diagnostic: incomplete run must report BLOCKED")
    results, identities, snapshot_counts = [], set(), {}
    entry_statuses = []
    for raw in raw_entries:
        object_fields(raw, ("schema_version", "id", "name", "description", "source", "source_problems", "license", "spec", "dependencies", "security", "tests", "evaluation", "safety", "network", "installable", "status", "checker", "receipt", "receipt_contract"), (), "diagnostic entry")
        if raw["schema_version"] != "ai4s.diagnostic-entry/review-v1" or raw["installable"] is not False or raw["safety"] != "UNASSESSED" or raw["network"] != "UNASSESSED":
            raise ValidationError("diagnostic entry: unsupported trust claim")
        if raw["checker"] != {"name": "ai4s-audit-proposed", "version": AUDITOR_VERSION} or raw["receipt_contract"] != AUDITOR_RECEIPT:
            raise ValidationError("diagnostic entry: checker/receipt contract mismatch")
        receipt_data = {k: v for k, v in raw.items() if k not in {"receipt", "receipt_contract"}}
        receipt = hashlib.sha256((json.dumps(receipt_data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")).hexdigest()
        if digest(raw["receipt"], "diagnostic.receipt") != receipt:
            raise ValidationError("diagnostic: entry receipt mismatch")
        src = raw["source"]
        object_fields(src, ("repository", "commit", "path_prefix", "provenance", "immutable", "snapshot_sha256", "binding", "path", "tree_sha256"), (), "diagnostic source")
        repo_url = text(src["repository"], "diagnostic.repository")
        prefix = "https://github.com/"
        if not repo_url.startswith(prefix):
            raise ValidationError("diagnostic: expected exact GitHub repository URL")
        repo = repository(repo_url[len(prefix):], "diagnostic.repository")
        locked = sources.get(repo.casefold())
        if locked is None or locked.acquisition_status != "PINNED_HASHED" or locked.commit != src["commit"]:
            raise ValidationError("diagnostic: source is not pinned to an eligible census record")
        if not isinstance(src["path"], str) or not isinstance(src["path_prefix"], str):
            raise ValidationError("diagnostic: path and prefix must be strings")
        path = portable_path(src["path"], "diagnostic.path") if src["path"] else ""
        if (path + "/SKILL.md" if path else "SKILL.md") not in locked.skill_paths:
            raise ValidationError("diagnostic: skill path not in source lock")
        if src["path_prefix"]:
            portable_path(src["path_prefix"], "diagnostic.path_prefix")
            if not path.startswith(src["path_prefix"] + "/") and path != src["path_prefix"]:
                raise ValidationError("diagnostic: path prefix mismatch")
        choice(src["provenance"], {"MISSING", "INVALID", "UNSIGNED_HONEST"}, "provenance")
        choice(src["binding"], {"NOT_ESTABLISHED", "MATCHES_CALLER_DIGEST"}, "binding")
        if src["immutable"] is not False:
            raise ValidationError("diagnostic: unexpected immutable assertion")
        snap = digest(src["snapshot_sha256"], "snapshot_sha256")
        digest(src["tree_sha256"], "auditor_tree_sha256")
        auditor_id = hashlib.sha256((repo_url + "\0" + src["commit"] + "\0" + path).encode("utf-8")).hexdigest()
        if digest(raw["id"], "diagnostic.id") != auditor_id:
            raise ValidationError("diagnostic: source identity mismatch")
        if auditor_id in identities:
            raise ValidationError("diagnostic: duplicate source tuple")
        identities.add(auditor_id)
        if snap in snapshots:
            snapshot_counts[snap] = snapshot_counts.get(snap, 0) + 1
        else:
            incomplete = True
        row_status = choice(raw["status"], {"UNSIGNED_HONEST", "REVIEW", "FAIL", "BLOCKED"}, "diagnostic.status")
        entry_statuses.append(row_status)
        spec, security = raw["spec"], raw["security"]
        if not isinstance(spec, dict) or not isinstance(security, dict):
            raise ValidationError("diagnostic: missing spec/security objects")
        object_fields(spec, ("status", "problems", "unsupported", "physical_lines", "profile", "checked_literal_markdown_links"), (), "spec")
        if spec["profile"] != "bounded-subset-v1" or type(spec["physical_lines"]) is not int or spec["physical_lines"] < 0:
            raise ValidationError("diagnostic: unrecognized spec profile or line count")
        array(spec["checked_literal_markdown_links"], "literal_links")
        if not isinstance(raw["dependencies"], dict):
            raise ValidationError("diagnostic: expected dependency observations")
        parse_errors = array(raw["dependencies"].get("parse_errors"), "dependency.parse_errors")
        spec_status = choice(spec.get("status"), {"PASS", "FAIL", "UNSUPPORTED"}, "spec.status")
        problems = array(spec.get("problems"), "spec.problems")
        unsupported = array(spec.get("unsupported"), "spec.unsupported")
        findings = array(security.get("findings"), "findings", 5000)
        coverage_errors = array(security.get("coverage_errors"), "coverage_errors")
        choice(security.get("status"), {"INCOMPLETE", "OBSERVATIONS_ONLY"}, "security.status")
        counts = security.get("counts")
        object_fields(counts, (), ("critical", "high", "medium"), "security.counts")
        observed = {"critical": 0, "high": 0, "medium": 0}
        for finding in findings:
            object_fields(finding, ("rule", "severity", "file", "line"), (), "finding")
            text(finding["rule"], "finding.rule")
            portable_path(finding["file"], "finding.file")
            if type(finding["line"]) is not int or finding["line"] < 0:
                raise ValidationError("diagnostic: invalid finding line")
            observed[choice(finding["severity"], set(observed), "finding.severity")] += 1
        if any(type(counts.get(k, 0)) is not int or counts.get(k, 0) != observed[k] for k in observed):
            raise ValidationError("diagnostic: finding counts mismatch")
        source_problems = array(raw["source_problems"], "source_problems")
        if raw["tests"] != {"status": "NOT_RUN", "reason": "Skill code is never executed."} or raw["evaluation"] != {"status": "NOT_MEASURED"}:
            raise ValidationError("diagnostic: execution/measurement assertion refused")
        source_restricted = (getattr(locked, "portability_status", None) not in {None, "NO_CASE_COLLISIONS_OBSERVED"} or
                             getattr(locked, "selection_status", None) not in {None, "CANDIDATE_EVIDENCE_ONLY_NOT_IMPORTABLE"})
        blocked = incomplete or catalog_negative or source_restricted or src["binding"] != "MATCHES_CALLER_DIGEST" or bool(source_problems) or bool(coverage_errors) or security["status"] == "INCOMPLETE" or bool(parse_errors) or bool(unsupported) or spec_status == "UNSUPPORTED" or src["provenance"] != "UNSIGNED_HONEST" or row_status == "BLOCKED" or snap not in snapshots
        failed = bool(problems) or spec_status == "FAIL" or bool(observed["critical"] or observed["high"]) or row_status == "FAIL"
        static_status = "BLOCKED" if blocked else "FAIL" if failed else "UNOBSERVED"
        source = Source(repo, locked.commit, path, locked.archive_sha256, locked.skill_tree_sha256, locked.hash_contract_id, lock_sha256)
        facets = tuple((facet, Evidence(static_status, "PARTIAL", "Unsigned diagnostic observations; incomplete static assurance.",
                                      (expected_report_sha256,), doc["generated_at"], None, None)
                        if facet == Facet.STATIC else Evidence("UNOBSERVED", "NONE", "Not established by a static diagnostic."))
                       for facet in Facet)
        reuse = getattr(locked, "license_reuse_disposition", None)
        gates = tuple((kind, Review("BLOCKED", None, "Source lock records blocked reuse: " + reuse)
                       if kind == "RIGHTS" and isinstance(reuse, str) and reuse.startswith("BLOCKED")
                       else Review("MISSING", None, "Authenticated human review is not established.")) for kind in REVIEW_KINDS)
        identity = hashlib.sha256((repo.casefold() + "\0" + source.commit + "\0" + path).encode("utf-8")).hexdigest()
        entry = Entry(identity, State.BLOCKED if blocked or failed else State.CANDIDATE, source, facets, gates,
                      Diagnostic(expected_report_sha256, receipt, src["tree_sha256"], snap, row_status))
        results.append(Entry.parse(entry.to_dict()))
    if snapshot_counts != snapshots:
        incomplete = True
    severity_order = {"UNSIGNED_HONEST": 0, "REVIEW": 1, "FAIL": 2, "BLOCKED": 3}
    minimum_status = max(entry_statuses, key=severity_order.get) if entry_statuses else "BLOCKED"
    if severity_order[status] < severity_order[minimum_status]:
        raise ValidationError("diagnostic: catalog status understates entries")
    if incomplete or catalog_negative:
        results = [Entry.parse(dataclasses.replace(e, state=State.BLOCKED,
                   facets=tuple((f, dataclasses.replace(v, status="BLOCKED", reason="Whole diagnostic run is partial or inconsistent.") if f == Facet.STATIC else v)
                                for f, v in e.facets)).to_dict()) for e in results]
    return Ingestion("BLOCKED" if incomplete or any(e.state == State.BLOCKED for e in results) else "CANDIDATE",
                     tuple(results), ("unsigned-diagnostic-only", "human-gates-unavailable") +
                     (("partial-or-inconsistent-run",) if incomplete else ()))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate-entry")
    validate.add_argument("entry")
    ingest = sub.add_parser("ingest")
    ingest.add_argument("--lock", required=True)
    ingest.add_argument("--lock-sha256", required=True)
    ingest.add_argument("--report", required=True)
    ingest.add_argument("--report-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "validate-entry":
            entry = Entry.parse(load_json_file(args.entry))
            result = {"status": "VALID_INPUT_NOT_LISTED", "state": entry.state.value, "installable": False}
        else:
            from source_lock import validate_lock
            from trust_common import read_json_bytes
            lock_bytes = read_json_bytes(args.lock)
            if hashlib.sha256(lock_bytes).hexdigest() != digest(args.lock_sha256, "lock_sha256"):
                raise ValidationError("lock: raw digest mismatch")
            sources = validate_lock(strict_json(lock_bytes))
            outcome = ingest_diagnostic(read_json_bytes(args.report), sources, args.lock_sha256, args.report_sha256)
            result = outcome.to_dict()
        print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
        return 2 if result.get("status") == "BLOCKED" else 0
    except (ValidationError, OSError) as exc:
        print(json.dumps({"status": "BLOCKED", "installable": False, "error": str(exc)}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
