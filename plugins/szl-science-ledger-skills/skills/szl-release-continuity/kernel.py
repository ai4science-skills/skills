# SPDX-License-Identifier: Apache-2.0
"""Compare declared release identities with supplied registry and runtime observations."""
import hashlib
import json
import re


def szl_release_continuity(record):
    if not isinstance(record, dict) or record.get("schema") != "szl.release-continuity.v1":
        raise ValueError("Unsupported schema")
    repository, source = record["repository"], record["source_revision"]
    if not isinstance(repository, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Declare owner/repository")
    if not isinstance(source, str) or not re.fullmatch("[0-9a-f]{40}", source):
        raise ValueError("Declare full immutable GitHub source revision")
    surfaces = record["surfaces"]
    if not isinstance(surfaces, list) or not 1 <= len(surfaces) <= 100 or any(not isinstance(s, dict) for s in surfaces):
        raise ValueError("Declare 1..100 required surfaces")
    names = [s["id"] for s in surfaces]
    if any(not isinstance(n, str) or not n or len(n) > 200 for n in names) or len(set(names)) != len(names):
        raise ValueError("Unique nonempty surface ids required")
    allowed = ("github", "pypi", "hf-model", "hf-dataset", "hf-space", "hf-kernel", "runtime")
    results, findings = [], []
    for surface in surfaces:
        kind = surface["kind"]
        if kind not in allowed:
            raise ValueError("Unknown registry kind")
        expected, observed = surface["expected"], surface.get("observed")
        if not isinstance(expected, dict) or set(expected) != {"revision", "artifact_sha256"}:
            raise ValueError("Expected identity must contain revision and artifact_sha256 only")
        for key in ("revision", "artifact_sha256"):
            value = expected[key]
            if not isinstance(value, str) or not value or len(value) > 128:
                raise ValueError("Expected revision and artifact digest required")
        if not re.fullmatch("[0-9a-f]{64}", expected["artifact_sha256"]):
            raise ValueError("Expected artifact SHA-256 required")
        if kind != "pypi" and not re.fullmatch("[0-9a-f]{40}", expected["revision"]):
            raise ValueError("Expected full immutable revision required")
        if kind == "github" and expected["revision"] != source:
            raise ValueError("GitHub expectation must identify the declared source")
        issues = []
        if observed is None:
            issues.append("UNOBSERVED")
        elif not isinstance(observed, dict):
            raise ValueError("Observation must be an object or null")
        else:
            expected_identity = dict(expected, source_repository=repository, source_revision=source)
            for key, value in expected_identity.items():
                if observed.get(key) is None:
                    issues.append("MISSING_" + key.upper())
                elif observed[key] != value:
                    issues.append("MISMATCH_" + key.upper())
            if kind == "runtime":
                if type(observed.get("ready")) is not bool:
                    issues.append("READINESS_UNOBSERVED")
                elif observed["ready"] is False:
                    issues.append("READINESS_REFUSED")
        findings.extend(issues)
        results.append({"id": surface["id"], "kind": kind,
                        "status": "GAP_OR_CONFLICT" if issues else "IDENTITY_AGREEMENT",
                        "findings": issues, "expected": expected,
                        "observed": observed})
    digest = hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return {"schema": "szl.release-continuity-result.v1",
            "status": "GAP_OR_CONFLICT" if findings else "IDENTITY_AGREEMENT_ON_SUPPLIED_EVIDENCE",
            "source_repository": repository, "source_revision": source, "surfaces": results,
            "input_sha256": digest, "signature_verification": "NOT_PERFORMED",
            "observation_authenticity": "NOT_ESTABLISHED", "model_or_dataset_quality": "NOT_EVALUATED",
            "release_authorization": "NOT_GRANTED"}
