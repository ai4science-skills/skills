#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline, bounded replay of declared synthetic evidence at a fixed UTC cutoff."""

import argparse
import datetime
import hashlib
import json
import os
import pathlib
import re
import stat
import sys

MANIFEST_SCHEMA = "szl.rare-disease-evidence-replay.manifest.v1"
CASE_SCHEMA = "szl.rare-disease-evidence-replay.case.v1"
SNAPSHOT_SCHEMA = "szl.rare-disease-evidence-replay.snapshot.v1"
REPORT_SCHEMA = "szl.rare-disease-evidence-replay.report.v1"
LIMITS = {"manifest": 32 * 1024, "case": 16 * 1024, "snapshot": 64 * 1024}
IDENT = re.compile(r"[a-z][a-z0-9-]{0,63}\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
UTC = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z")
TOKENS = {
    "case": re.compile(r"SYNTH-CASE:[0-9]{4,6}\Z"),
    "condition": re.compile(r"SYNTH-COND:[0-9]{4,6}\Z"),
    "term": re.compile(r"SYNTH-HP:[0-9]{4,6}\Z"),
    "vcv": re.compile(r"SYNTH-VCV:[0-9]{4,6}\.[1-9][0-9]*\Z"),
    "rcv": re.compile(r"SYNTH-RCV:[0-9]{4,6}\.[1-9][0-9]*\Z"),
    "scv": re.compile(r"SYNTH-SCV:[0-9]{4,6}\.[1-9][0-9]*\Z"),
    "assertion": re.compile(r"SYNTH-ASSERT:[0-9]{4,6}\Z"),
    "source_ref": re.compile(r"SYNTH-REF:[A-Z0-9][A-Z0-9-]{0,31}\Z"),
    "release": re.compile(r"SYNTHETIC-[A-Z0-9][A-Z0-9.-]{0,63}\Z"),
}
SECRET = re.compile(r"(^|[-_.])(passwords?|secrets?|credentials?|api[-_]?key|access[-_]?token)([-_.]|$)", re.I)
DEVICE = re.compile(r"(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?\Z", re.I)


class Hold(Exception):
    """A stable, non-sensitive reason that prevents a replay result."""


def _must(condition, reason):
    if not condition:
        raise Hold(reason)


def _ident(value, reason):
    _must(isinstance(value, str) and IDENT.fullmatch(value) is not None, reason)
    return value


def _sha(value, reason):
    _must(isinstance(value, str) and SHA.fullmatch(value) is not None, reason)
    return value


def _token(value, kind, reason):
    _must(isinstance(value, str) and TOKENS[kind].fullmatch(value) is not None, reason)
    return value


def _timestamp(value, reason="INVALID_MANIFEST"):
    _must(isinstance(value, str) and UTC.fullmatch(value) is not None, reason)
    try:
        parsed = datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise Hold(reason) from error
    _must(parsed.strftime("%Y-%m-%dT%H:%M:%SZ") == value, reason)
    return parsed


def _reparse(info):
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _root(root):
    path = pathlib.Path(root).absolute()
    try:
        for component in (path, *path.parents):
            info = component.lstat()
            _must(not _reparse(info), "UNSAFE_ROOT")
        _must(path.is_dir(), "UNSAFE_ROOT")
    except OSError as error:
        raise Hold("UNSAFE_ROOT") from error
    return path


def _relative(relative):
    _must(isinstance(relative, str) and 1 <= len(relative) <= 240 and
          "\\" not in relative and ":" not in relative and
          all(ord(char) >= 32 for char in relative), "UNSAFE_PATH")
    pure = pathlib.PurePosixPath(relative)
    _must(not pure.is_absolute() and str(pure) == relative and
          all(part not in ("", ".", "..") for part in pure.parts), "UNSAFE_PATH")
    for part in pure.parts:
        _must(not part.endswith((".", " ")) and not DEVICE.fullmatch(part) and
              part.lower() not in (".git", ".ssh", ".aws", ".env", ".codex", ".netrc", ".npmrc") and
              not SECRET.search(part), "UNSAFE_PATH")
    return pure.parts


def _locate(root, relative, output=False):
    path = _root(root)
    parts = _relative(relative)
    for index, part in enumerate(parts):
        path = path / part
        if output and index == len(parts) - 1:
            try:
                path.lstat()
            except FileNotFoundError:
                return path
            except OSError as error:
                raise Hold("UNSAFE_OUTPUT") from error
            raise Hold("OUTPUT_EXISTS")
        try:
            info = path.lstat()
        except OSError as error:
            raise Hold("INPUT_UNAVAILABLE") from error
        _must(not _reparse(info), "UNSAFE_PATH")
        _must(stat.S_ISDIR(info.st_mode) if index < len(parts) - 1 else
              stat.S_ISREG(info.st_mode), "UNSAFE_PATH")
    return path


def _read(root, relative, limit):
    path = _locate(root, relative)
    try:
        before = path.lstat()
        _must(before.st_size <= limit, "INPUT_TOO_LARGE")
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            _must(stat.S_ISREG(opened.st_mode) and not _reparse(opened) and
                  (opened.st_dev, opened.st_ino) == (before.st_dev, before.st_ino),
                  "INPUT_CHANGED")
            raw = stream.read(limit + 1)
            finished = os.fstat(stream.fileno())
        after = path.lstat()
    except OSError as error:
        raise Hold("INPUT_UNAVAILABLE") from error
    identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
    _must(not _reparse(after) and stat.S_ISREG(after.st_mode) and len(raw) <= limit and
          identity(before) == identity(opened) == identity(finished) == identity(after),
          "INPUT_CHANGED")
    return raw


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _json(raw, reason):
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")),
                          parse_float=lambda _: (_ for _ in ()).throw(ValueError("floating JSON number")))
    except (UnicodeError, ValueError, TypeError, RecursionError) as error:
        raise Hold(reason) from error


def _pinned(root, entry, limit, reason):
    _must(isinstance(entry, dict) and {"path", "sha256"} <= set(entry), reason)
    _sha(entry["sha256"], reason)
    _relative(entry["path"])
    raw = _read(root, entry["path"], limit)
    _must(hashlib.sha256(raw).hexdigest() == entry["sha256"], "PIN_MISMATCH")
    return raw


def _manifest(document, manifest_path):
    _must(isinstance(document, dict) and set(document) ==
          {"schema", "data_class", "cutoff_utc", "case", "sources"} and
          document["schema"] == MANIFEST_SCHEMA and document["data_class"] == "SYNTHETIC",
          "INVALID_MANIFEST")
    cutoff = _timestamp(document["cutoff_utc"])
    case = document["case"]
    _must(isinstance(case, dict) and set(case) == {"path", "sha256"}, "INVALID_MANIFEST")
    _sha(case["sha256"], "INVALID_MANIFEST")
    _relative(case["path"])
    _must(case["path"] != manifest_path, "INVALID_MANIFEST")
    sources = document["sources"]
    _must(isinstance(sources, list) and len(sources) == 2, "INVALID_MANIFEST")
    seen_sources, seen_kinds, seen_snapshots = set(), set(), set()
    seen_paths = {manifest_path, case["path"]}
    count = 0
    for source in sources:
        _must(isinstance(source, dict) and set(source) == {"id", "kind", "snapshots"},
              "INVALID_MANIFEST")
        source_id = _ident(source["id"], "INVALID_MANIFEST")
        _must(source_id not in seen_sources, "INVALID_MANIFEST")
        seen_sources.add(source_id)
        kind = source["kind"]
        _must(kind in ("HPO_ANNOTATIONS", "CLINVAR_ASSERTIONS") and kind not in seen_kinds,
              "INVALID_MANIFEST")
        seen_kinds.add(kind)
        snapshots = source["snapshots"]
        _must(isinstance(snapshots, list) and snapshots and len(snapshots) <= 32, "INVALID_MANIFEST")
        count += len(snapshots)
        _must(count <= 32, "INVALID_MANIFEST")
        for snapshot in snapshots:
            _must(isinstance(snapshot, dict) and set(snapshot) ==
                  {"id", "captured_at_utc", "release", "path", "sha256"},
                  "INVALID_MANIFEST")
            snapshot_id = _ident(snapshot["id"], "INVALID_MANIFEST")
            _must(snapshot_id not in seen_snapshots, "INVALID_MANIFEST")
            seen_snapshots.add(snapshot_id)
            _timestamp(snapshot["captured_at_utc"])
            _token(snapshot["release"], "release", "INVALID_MANIFEST")
            _sha(snapshot["sha256"], "INVALID_MANIFEST")
            _relative(snapshot["path"])
            _must(snapshot["path"] not in seen_paths, "INVALID_MANIFEST")
            seen_paths.add(snapshot["path"])
    _must(seen_kinds == {"HPO_ANNOTATIONS", "CLINVAR_ASSERTIONS"}, "INVALID_MANIFEST")
    return cutoff


def _case(document, cutoff):
    _must(isinstance(document, dict) and set(document) ==
          {"schema", "synthetic", "rights", "case_id", "features"} and
          document["schema"] == CASE_SCHEMA and document["synthetic"] is True and
          document["rights"] == "SYNTHETIC_ONLY", "INVALID_CASE")
    case_id = _token(document["case_id"], "case", "INVALID_CASE")
    raw_features = document["features"]
    _must(isinstance(raw_features, list) and 1 <= len(raw_features) <= 32, "INVALID_CASE")
    by_term, future_count = {}, 0
    for feature in raw_features:
        _must(isinstance(feature, dict) and set(feature) ==
              {"term", "state", "recorded_at_utc"}, "INVALID_CASE")
        term = _token(feature["term"], "term", "INVALID_CASE")
        _must(feature["state"] in ("PRESENT", "EXCLUDED"), "INVALID_CASE")
        recorded_at = _timestamp(feature["recorded_at_utc"], "INVALID_CASE")
        if recorded_at > cutoff:
            future_count += 1
        else:
            by_term.setdefault(term, []).append(feature)
    selected = []
    for term, states in sorted(by_term.items()):
        latest = max(_timestamp(item["recorded_at_utc"]) for item in states)
        tied = [item for item in states if _timestamp(item["recorded_at_utc"]) == latest]
        _must(len(tied) == 1, "AMBIGUOUS_CASE_FEATURE")
        selected.append(tied[0])
    _must(selected, "CASE_WITHOUT_ELIGIBLE_FEATURE")
    return case_id, selected, future_count


def _admissible(value, captured_at, cutoff):
    observed_at = _timestamp(value, "INVALID_SNAPSHOT")
    _must(observed_at <= cutoff, "OBSERVATION_AFTER_CUTOFF")
    _must(observed_at <= captured_at, "OBSERVATION_AFTER_SNAPSHOT")


def _snapshot(document, source, chosen, captured_at, cutoff):
    kind = source["kind"]
    payload_key = "annotations" if kind == "HPO_ANNOTATIONS" else "records"
    _must(isinstance(document, dict) and set(document) ==
          {"schema", "synthetic", "rights", "source_id", "kind", "release",
           "complete", payload_key} and document["schema"] == SNAPSHOT_SCHEMA and
          document["synthetic"] is True and document["rights"] == "SYNTHETIC_ONLY" and
          document["source_id"] == source["id"] and document["kind"] == kind and
          document["release"] == chosen["release"] and type(document["complete"]) is bool,
          "INVALID_SNAPSHOT")
    _must(document["complete"], "LATEST_SNAPSHOT_INCOMPLETE")
    rows = document[payload_key]
    _must(isinstance(rows, list) and len(rows) <= 100, "INVALID_SNAPSHOT")
    seen = set()
    if kind == "HPO_ANNOTATIONS":
        for row in rows:
            _must(isinstance(row, dict) and set(row) ==
                  {"condition", "term", "qualifier", "source_ref", "observed_at_utc"},
                  "INVALID_SNAPSHOT")
            _token(row["condition"], "condition", "INVALID_SNAPSHOT")
            _token(row["term"], "term", "INVALID_SNAPSHOT")
            _token(row["source_ref"], "source_ref", "INVALID_SNAPSHOT")
            _must(row["qualifier"] in ("ANNOTATED", "EXPLICIT_NEGATIVE_ANNOTATION"),
                  "INVALID_SNAPSHOT")
            _admissible(row["observed_at_utc"], captured_at, cutoff)
            identity = (row["condition"], row["term"], row["qualifier"], row["source_ref"])
            _must(identity not in seen, "DUPLICATE_ANNOTATION")
            seen.add(identity)
    else:
        seen_scv = set()
        for row in rows:
            _must(isinstance(row, dict) and set(row) ==
                  {"condition", "vcv", "rcv", "observed_at_utc", "submissions"},
                  "INVALID_SNAPSHOT")
            _token(row["condition"], "condition", "INVALID_SNAPSHOT")
            _token(row["vcv"], "vcv", "INVALID_SNAPSHOT")
            rcv = _token(row["rcv"], "rcv", "INVALID_SNAPSHOT")
            _must(rcv not in seen, "DUPLICATE_RCV")
            seen.add(rcv)
            _admissible(row["observed_at_utc"], captured_at, cutoff)
            submissions = row["submissions"]
            _must(isinstance(submissions, list) and 1 <= len(submissions) <= 16,
                  "INVALID_SNAPSHOT")
            for submitted in submissions:
                _must(isinstance(submitted, dict) and set(submitted) ==
                      {"scv", "assertion_token", "source_ref", "observed_at_utc"},
                      "INVALID_SNAPSHOT")
                scv = _token(submitted["scv"], "scv", "INVALID_SNAPSHOT")
                _must(scv not in seen_scv, "DUPLICATE_SCV")
                seen_scv.add(scv)
                _token(submitted["assertion_token"], "assertion", "INVALID_SNAPSHOT")
                _token(submitted["source_ref"], "source_ref", "INVALID_SNAPSHOT")
                _admissible(submitted["observed_at_utc"], captured_at, cutoff)
    return rows


def _summary(case_features, annotations, records, conditions):
    feature_state = {row["term"]: row["state"] for row in case_features}
    result = []
    for condition in conditions:
        hpo = sorted((row for row in annotations if row["condition"] == condition),
                     key=lambda row: (row["term"], row["qualifier"], row["source_ref"]))
        clinvar = sorted((row for row in records if row["condition"] == condition),
                         key=lambda row: row["rcv"])
        links = sorted(({"term": row["term"], "case_state": feature_state[row["term"]],
                         "annotation_qualifier": row["qualifier"], "source_ref": row["source_ref"]}
                        for row in hpo if row["term"] in feature_state),
                       key=lambda row: (row["term"], row["case_state"],
                                        row["annotation_qualifier"], row["source_ref"]))
        scopes = [{"vcv": row["vcv"], "rcv": row["rcv"],
                   "submissions": sorted(({"scv": item["scv"],
                                           "assertion_token": item["assertion_token"],
                                           "source_ref": item["source_ref"]}
                                          for item in row["submissions"]),
                                         key=lambda item: item["scv"])}
                  for row in clinvar]
        result.append({
            "condition": condition,
            "hpo_annotation_rows": len(hpo),
            "hpo_explicit_negative_rows": sum(row["qualifier"] == "EXPLICIT_NEGATIVE_ANNOTATION"
                                              for row in hpo),
            "case_feature_annotation_links": links,
            "clinvar_rcv_records": len(clinvar),
            "clinvar_scv_submissions": sum(len(row["submissions"]) for row in clinvar),
            "clinvar_scopes": scopes,
            "declared_missing_sources": (["HPO_ANNOTATIONS"] if not hpo else []) +
                                        (["CLINVAR_ASSERTIONS"] if not clinvar else []),
        })
    return result


def _without_provenance(annotations, records, provenance):
    hpo = [row for row in annotations if row["source_ref"] != provenance]
    clinvar = []
    for row in records:
        submissions = [item for item in row["submissions"] if item["source_ref"] != provenance]
        if submissions:
            clinvar.append({**row, "submissions": submissions})
    return hpo, clinvar


def replay(root, manifest_path):
    manifest_raw = _read(root, manifest_path, LIMITS["manifest"])
    manifest_sha = hashlib.sha256(manifest_raw).hexdigest()
    manifest = _json(manifest_raw, "INVALID_MANIFEST")
    cutoff = _manifest(manifest, manifest_path)
    case_raw = _pinned(root, manifest["case"], LIMITS["case"], "INVALID_MANIFEST")
    case_id, case_features, future_case_count = _case(_json(case_raw, "INVALID_CASE"), cutoff)
    selected, domain_rows = [], {}
    future_count = 0
    for source in sorted(manifest["sources"], key=lambda entry: entry["id"]):
        eligible = []
        for snapshot in source["snapshots"]:
            if _timestamp(snapshot["captured_at_utc"]) <= cutoff:
                eligible.append(snapshot)
            else:
                future_count += 1
        _must(eligible, "SOURCE_WITHOUT_ELIGIBLE_SNAPSHOT")
        latest = max(_timestamp(item["captured_at_utc"]) for item in eligible)
        tied = [item for item in eligible if _timestamp(item["captured_at_utc"]) == latest]
        _must(len(tied) == 1, "AMBIGUOUS_LATEST_SNAPSHOT")
        chosen = tied[0]
        raw = _pinned(root, chosen, LIMITS["snapshot"], "INVALID_MANIFEST")
        domain_rows[source["kind"]] = _snapshot(_json(raw, "INVALID_SNAPSHOT"),
                                                 source, chosen, latest, cutoff)
        selected.append({"source_id": source["id"], "snapshot_id": chosen["id"],
                         "kind": source["kind"], "release": chosen["release"],
                         "captured_at_utc": chosen["captured_at_utc"],
                         "sha256": chosen["sha256"]})
    annotations = domain_rows["HPO_ANNOTATIONS"]
    records = domain_rows["CLINVAR_ASSERTIONS"]
    conditions = sorted({row["condition"] for row in annotations} |
                        {row["condition"] for row in records})
    provenances = ({row["source_ref"] for row in annotations} |
                   {item["source_ref"] for row in records for item in row["submissions"]})
    _must(len(provenances) <= 32, "TOO_MANY_PROVENANCE_GROUPS")
    ablations = {}
    for provenance in sorted(provenances):
        without_hpo, without_clinvar = _without_provenance(annotations, records, provenance)
        ablations[provenance] = _summary(case_features, without_hpo, without_clinvar, conditions)
    return {
        "schema": REPORT_SCHEMA,
        "status": "DECLARED_ONLY",
        "readiness": "HOLD",
        "qualification": "NOT_EVALUATED",
        "data_class": "SYNTHETIC_DECLARED",
        "clinical_use": "NOT_FOR_CLINICAL_USE",
        "signed": False,
        "independent_witness": False,
        "manifest_sha256": manifest_sha,
        "case_sha256": manifest["case"]["sha256"],
        "case_id": case_id,
        "cutoff_utc": manifest["cutoff_utc"],
        "future_snapshots_excluded": future_count,
        "future_case_features_excluded": future_case_count,
        "case_features_at_cutoff": case_features,
        "selected_snapshots": selected,
        "base_evidence": _summary(case_features, annotations, records, conditions),
        "leave_one_source_out": {
            source["source_id"]: _summary(
                case_features,
                [] if source["kind"] == "HPO_ANNOTATIONS" else annotations,
                [] if source["kind"] == "CLINVAR_ASSERTIONS" else records,
                conditions)
            for source in selected
        },
        "leave_one_provenance_out": ablations,
        "limits": ["NOT_AUTHENTICATED_PROVIDER_DATA", "NOT_CLINICALLY_VALIDATED",
                   "NO_PATIENT_OR_VARIANT_INTERPRETATION"],
    }


def _hold(reason):
    return {"schema": REPORT_SCHEMA, "status": "HOLD", "reason": reason,
            "readiness": "HOLD",
            "qualification": "NOT_EVALUATED", "data_class": "SYNTHETIC_DECLARED",
            "clinical_use": "NOT_FOR_CLINICAL_USE", "signed": False,
            "independent_witness": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        destination = _locate(args.root, args.output, output=True)
    except Hold as error:
        print(error.args[0], file=sys.stderr)
        return 2
    try:
        report = replay(args.root, args.manifest)
    except Hold as error:
        report = _hold(error.args[0])
    raw = (json.dumps(report, sort_keys=True, indent=2, ensure_ascii=False,
                      allow_nan=False) + "\n").encode("utf-8")
    try:
        with destination.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        print("OUTPUT_UNAVAILABLE", file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
    return 0 if report["status"] == "DECLARED_ONLY" else 2


if __name__ == "__main__":
    sys.exit(main())
