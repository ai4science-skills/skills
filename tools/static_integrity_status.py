#!/usr/bin/env python3
"""Post a fail-closed, exact-PR-head static-integrity status from base code.

This step has a narrowly scoped token. Candidate files are never imported or
executed. Its success means only source-byte and static-metadata agreement.
"""

import argparse
import base64
import binascii
import hashlib
import json
import os
import pathlib
import re
import sys
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import static_integrity as gate
import sync
from trust_common import read_json_bytes, strict_json

CONTEXT = "ai4s/static-integrity"
API = "https://api.github.com/repos/" + gate.REPOSITORY
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
REPORT_KEYS = frozenset({
    "schema", "decision", "installable", "provider_policy", "scope", "repository", "number",
    "base_sha", "base_ref", "head_repo", "head_sha", "trusted_base_sha", "merge_base_sha",
    "policy_sha256", "checker_sha256", "candidate_archive_sha256", "plugin_count",
    "skill_count", "upstream", "unobserved",
})
UPSTREAM_KEYS = frozenset({"name", "repository", "commit", "archive_sha256"})


def _request(url, token, payload=None):
    if not isinstance(token, str) or len(token) < 8:
        raise gate.Hold("TOKEN_UNAVAILABLE")
    method = "POST" if payload is not None else "GET"
    raw = None if payload is None else json.dumps(payload, sort_keys=True).encode("utf-8")
    request = urllib.request.Request(url, data=raw, method=method, headers={
        "Accept": "application/vnd.github+json",
        "Authorization": "Bearer " + token,
        "User-Agent": "ai4science-base-static-integrity",
        **({"Content-Type": "application/json"} if raw is not None else {}),
    })
    opener = urllib.request.build_opener(sync.NoRedirect)
    with opener.open(request, timeout=30) as response:
        if response.status not in ({201} if raw is not None else {200}) or response.geturl() != url:
            raise gate.Hold("PROVIDER_STATUS_UNAVAILABLE")
        data = response.read(1024 * 1024 + 1)
    return sync.read_json(data)


def _upstream(report):
    upstream = report["upstream"]
    return (type(report["plugin_count"]) is int and type(report["skill_count"]) is int
            and report["skill_count"] >= 0 and isinstance(upstream, list)
            and report["plugin_count"] == len(upstream)
            and all(isinstance(item, dict) and item.keys() == UPSTREAM_KEYS
                    and all(type(item[key]) is str for key in UPSTREAM_KEYS)
                    and gate.SHA.fullmatch(item["commit"]) and HEX64.fullmatch(item["archive_sha256"])
                    for item in upstream))


def _result(report, bound):
    if not isinstance(report, dict) or report.keys() != REPORT_KEYS or report.get("schema") != gate.SCHEMA:
        return False
    if (report.get("decision") != "STATIC_MATCH" or report.get("installable") is not False
            or report.get("provider_policy") != "UNVERIFIED"):
        return False
    for key in ("repository", "number", "base_ref", "base_sha", "head_sha", "head_repo"):
        if not gate._exact(report.get(key), bound[key]):
            return False
    if not gate._exact(report.get("merge_base_sha"), bound["base_sha"]) or not _upstream(report):
        return False
    root = pathlib.Path(__file__).resolve().parent.parent
    _, expected_policy_sha = gate.policy(root)
    expected_checker_sha = hashlib.sha256(gate._regular_bytes(root, "tools/static_integrity.py")).hexdigest()
    return (report.get("trusted_base_sha") == bound["base_sha"]
            and report.get("scope") == "SOURCE_AND_STATIC_METADATA_ONLY"
            and all(isinstance(report.get(key), str) and HEX64.fullmatch(report[key])
                    for key in ("policy_sha256", "checker_sha256", "candidate_archive_sha256"))
            and report.get("policy_sha256") == expected_policy_sha
            and report.get("checker_sha256") == expected_checker_sha
            and report.get("unobserved") == ["DEPENDENCIES", "VULNERABILITIES", "BEHAVIOR", "SCIENCE", "RIGHTS_REVIEW", "FRESHNESS"])


def publish(event, base_sha, report, token, scan_result, request=_request):
    bound = gate.identity(event, base_sha)
    current = request(API + "/pulls/" + str(bound["number"]), token)
    stale = "STALE_OR_UNAVAILABLE_PR"
    if (gate._field(current, stale, str, "state") != "open"
            or gate._field(current, stale, str, "head", "sha") != bound["head_sha"]
            or gate._field(current, stale, str, "head", "repo", "full_name") != bound["head_repo"]
            or gate._field(current, stale, str, "base", "ref") != gate.PROTECTED_BASE_REF
            or gate._field(current, stale, str, "base", "sha") != bound["base_sha"]
            or gate._field(current, stale, str, "base", "repo", "full_name") != gate.REPOSITORY):
        raise gate.Hold(stale)
    matched = scan_result == "success" and _result(report, bound)
    payload = {"state": "success" if matched else "failure", "context": CONTEXT,
               "description": ("Pinned source/static metadata match; not security admission" if matched
                               else "HOLD: static integrity unavailable; not security admission")}
    status_url = API + "/statuses/" + bound["head_sha"]
    response = request(status_url, token, payload)
    unavailable = "PROVIDER_STATUS_UNAVAILABLE"
    # GitHub's status object identifies its commit by url (.../statuses/<sha>), not a sha field.
    if (gate._field(response, unavailable, str, "url") != status_url
            or gate._field(response, unavailable, str, "context") != CONTEXT
            or gate._field(response, unavailable, str, "state") != payload["state"]
            or ("sha" in response and response["sha"] != bound["head_sha"])):
        raise gate.Hold(unavailable)
    return matched


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--report-b64", required=True)
    parser.add_argument("--scan-result", required=True)
    args = parser.parse_args(argv)
    try:
        event = strict_json(read_json_bytes(args.event, gate.MAX_EVENT_BYTES))
        try:
            raw = base64.b64decode(args.report_b64, validate=True)
            if len(raw) > gate.MAX_REPORT_BYTES:
                raise ValueError("receipt too large")
            report = strict_json(raw)
        except (binascii.Error, ValueError):
            report = None
        matched = publish(event, args.base_sha, report, os.environ.get("GITHUB_TOKEN"), args.scan_result)
    except (gate.Hold, OSError, ValueError, TypeError, KeyError):
        print("static integrity status: HOLD; exact-head provider publication unavailable")
        return 2
    print("static integrity status: " + ("STATIC_MATCH" if matched else "HOLD") + "; not security admission")
    return 0 if matched else 2


if __name__ == "__main__":
    sys.exit(main())
