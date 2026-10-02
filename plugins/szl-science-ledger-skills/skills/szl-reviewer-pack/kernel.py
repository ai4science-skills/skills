"""szl-reviewer-pack — one bundle a reviewer can read in five minutes.

Stdlib only. Offline. Reads a project directory produced by the
szl-science-workbench (project.json, runs/<id>/summary.json and the per-check
reports it names) plus any extra standalone reports (evidence gate,
cross-implementation check, mutation coverage, energy receipt, session
receipt) and renders REVIEW.md with:

  1. what was checked, by which check, with the finding state per check
  2. the capsule / integrity state of the inputs behind the run
  3. every unresolved finding, quoted from the report that raised it
  4. an optional declared aggregate

The aggregate uses the weighted geometric mean

    Lambda(x) = prod_i x_i ** w_i,   sum(w_i) = 1,   w_i > 0,   x_i in [0, 1]

over per-check scores the reviewer declares in review-config.json (default:
a check with no findings scores 1.0, a check with findings scores 0.0). The
mean is non-compensatory: one zero drives it to zero, so a clean kernel
comparison cannot paper over a leaking split. It is reported as an
ADVISORY aggregation rule with its inputs shown, not as a quality score,
and the categorical verdict never depends on it.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

SCHEMA = "szl.reviewer-pack.v1"
_RUN_DIR = re.compile(r"^(\d{8}T\d{12}Z)-[0-9a-f]{12}$")


def szl_canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def szl_weighted_geomean(axes, weights=None):
    xs = [float(x) for x in axes]
    if not xs:
        raise ValueError("axes must be nonempty")
    ws = [1.0 / len(xs)] * len(xs) if weights is None else [float(w) for w in weights]
    if len(ws) != len(xs) or any(x < 0 or x > 1 for x in xs) or any(w < 0 for w in ws):
        raise ValueError("axes must lie in [0,1]; weights must be nonnegative and match")
    if not math.isclose(math.fsum(ws), 1.0, rel_tol=0, abs_tol=1e-12):
        raise ValueError("weights must sum to 1")
    if any(x == 0 and w > 0 for x, w in zip(xs, ws)):
        return 0.0
    return math.exp(math.fsum(w * math.log(x) for x, w in zip(xs, ws) if w > 0))


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _latest_run(root: Path):
    runs = root / "runs"
    if not runs.is_dir():
        return None
    candidates = [(m.group(1), d) for d in runs.iterdir() if d.is_dir() and (m := _RUN_DIR.match(d.name))]
    if not candidates:
        return None
    candidates.sort()
    return candidates[-1][1]


def _findings_of(report: dict) -> list:
    out = []
    for key in ("issues", "findings", "failures", "mismatch_indexes", "missing", "required_failures"):
        v = report.get(key)
        if isinstance(v, list) and v:
            out.append({"field": key, "value": v[:10], "count": len(v)})
        elif isinstance(v, dict) and v:
            out.append({"field": key, "value": dict(list(v.items())[:10]), "count": len(v)})
    for key in ("counterexample_count", "invalid_outputs", "mismatches", "divergent"):
        v = report.get(key)
        if isinstance(v, int) and v > 0:
            out.append({"field": key, "value": v, "count": v})
    return out


def _status_of(report: dict) -> str:
    return str(report.get("status") or report.get("readiness") or "UNKNOWN")


def szl_build_pack(root, extra_reports=None, config=None) -> dict:
    root = Path(root)
    config = config or {}
    pack = {"schema": SCHEMA, "project": None, "run": None, "checks": [], "extra": [], "unresolved": [],
            "integrity": {}, "aggregate": None, "status": None}
    project_path = root / "project.json"
    if project_path.is_file():
        project = _read(project_path)
        pack["project"] = {"name": project.get("name") or project.get("project") or project.get("title") or project.get("question") or root.resolve().name, "input_scope": project.get("input_scope")}
    run_dir = _latest_run(root)
    if run_dir is not None:
        summary = _read(run_dir / "summary.json")
        pack["run"] = {"id": summary.get("run_id"), "created_at": summary.get("created_at"),
                       "status": summary.get("status"), "input_scope": summary.get("input_scope"),
                       "scientific_truth_verified": summary.get("scientific_truth_verified", False)}
        for check_id, meta in sorted((summary.get("checks") or {}).items()):
            rel = meta.get("path")
            report_path = root / rel if rel else None
            entry = {"id": check_id, "type": meta.get("type"), "findings": bool(meta.get("findings")),
                     "report_path": rel, "status": None, "details": [], "digest_match": None}
            if report_path and report_path.is_file():
                data = report_path.read_bytes()
                entry["digest_match"] = hashlib.sha256(data).hexdigest() == meta.get("sha256")
                report = json.loads(data.decode("utf-8"))
                entry["status"] = _status_of(report)
                entry["details"] = _findings_of(report)
            else:
                entry["status"] = "REPORT_MISSING"
            pack["checks"].append(entry)
        capsule = run_dir / "capsule.json"
        if capsule.is_file():
            cap = _read(capsule)
            pack["integrity"] = {"capsule_sha256": cap.get("capsule_sha256"), "files": len(cap.get("files", [])),
                                 "signed": bool(cap.get("signed"))}
        report_json = run_dir / "report.json"
        if report_json.is_file():
            rep = _read(report_json)
            pack["integrity"]["last_check"] = {k: rep.get(k) for k in ("capsule", "completion_record_binding", "unavailable_sources") if k in rep}
    for rel in extra_reports or []:
        p = root / rel
        if not p.is_file():
            pack["extra"].append({"path": rel, "status": "MISSING", "schema": None, "details": []}); continue
        rep = _read(p)
        pack["extra"].append({"path": rel, "schema": rep.get("schema"), "status": _status_of(rep),
                              "details": _findings_of(rep), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()})
    for c in pack["checks"]:
        if c["findings"] or c["digest_match"] is False or c["status"] == "REPORT_MISSING":
            pack["unresolved"].append({"source": c["id"], "status": c["status"], "details": c["details"],
                                       "digest_match": c["digest_match"]})
    for e in pack["extra"]:
        if e["status"] in ("FAIL", "DIVERGENT", "MISMATCH", "MISSING", "RECEIPT_TAMPERED", "ERROR", "BASELINE_FLAGGED") or e["details"]:
            pack["unresolved"].append({"source": e["path"], "status": e["status"], "details": e["details"]})
    # declared aggregate
    scores_cfg = config.get("scores", {})
    weights_cfg = config.get("weights", {})
    axes, weights, used = [], [], []
    for c in pack["checks"]:
        default = 0.0 if (c["findings"] or c["digest_match"] is False) else 1.0
        score = float(scores_cfg.get(c["id"], default))
        axes.append(min(1.0, max(0.0, score)))
        weights.append(float(weights_cfg.get(c["id"], 1.0)))
        used.append({"check": c["id"], "score": axes[-1], "weight": weights[-1], "declared": c["id"] in scores_cfg})
    if axes:
        total = math.fsum(weights)
        norm = [w / total for w in weights] if total > 0 else None
        value = szl_weighted_geomean(axes, norm) if norm else None
        pack["aggregate"] = {"rule": "weighted geometric mean (non-compensatory); ADVISORY", "value": value,
                             "inputs": used, "note": "A reviewer-declared aggregation of check scores. One zero-scored check "
                             "drives the value to 0. It is not a validated quality score and does not change the verdict."}
    if pack["run"] is None and not pack["extra"]:
        pack["status"] = "NOTHING_TO_REVIEW"
    elif pack["unresolved"]:
        pack["status"] = "REVIEW_REQUIRED"
    else:
        pack["status"] = "NO_UNRESOLVED_CHECKED_FINDINGS"
    pack["scope"] = ("Summarizes retained check reports and their integrity. Does not re-run checks, verify scientific truth, "
                     "or approve publication.")
    pack["pack_sha256"] = hashlib.sha256(szl_canonical(pack).encode()).hexdigest()
    return pack


def szl_render_markdown(pack: dict) -> str:
    L = []
    L.append(f"# Review pack — {pack.get('project', {}).get('name') if pack.get('project') else 'project'}")
    L.append("")
    L.append(f"Verdict: **{pack['status']}**  ·  pack digest `{pack['pack_sha256'][:16]}`")
    if pack.get("run"):
        r = pack["run"]
        L.append(f"Run `{r['id']}` ({r['created_at']}) — status {r['status']}, input scope {r['input_scope']}, "
                 f"scientific truth verified: {r['scientific_truth_verified']}")
    L.append("")
    if pack["checks"]:
        L.append("## Checks in the latest run")
        L.append("")
        L.append("| Check | Type | Status | Findings | Report intact |")
        L.append("|---|---|---|---|---|")
        for c in pack["checks"]:
            L.append(f"| {c['id']} | {c['type']} | {c['status']} | {'yes' if c['findings'] else 'none checked'} | "
                     f"{'yes' if c['digest_match'] else ('no' if c['digest_match'] is False else 'n/a')} |")
        L.append("")
    if pack["extra"]:
        L.append("## Standalone reports")
        L.append("")
        L.append("| Report | Schema | Status |")
        L.append("|---|---|---|")
        for e in pack["extra"]:
            L.append(f"| {e['path']} | {e.get('schema') or '-'} | {e['status']} |")
        L.append("")
    if pack["integrity"]:
        i = pack["integrity"]
        L.append("## Integrity")
        L.append("")
        L.append(f"- Capsule `{(i.get('capsule_sha256') or '-')[:16]}` over {i.get('files', 0)} file(s); signed: {i.get('signed', False)}")
        if i.get("last_check"):
            L.append(f"- Last `check`: {json.dumps(i['last_check'], sort_keys=True)}")
        L.append("")
    L.append("## Unresolved findings")
    L.append("")
    if not pack["unresolved"]:
        L.append("None among the checks that were run. Checks not run are not covered.")
    for u in pack["unresolved"]:
        L.append(f"- **{u['source']}** — {u['status']}")
        for d in u.get("details", []):
            L.append(f"  - `{d['field']}` ({d['count']}): `{json.dumps(d['value'], sort_keys=True)[:200]}`")
        if u.get("digest_match") is False:
            L.append("  - report bytes differ from the digest recorded in the run summary")
    L.append("")
    if pack.get("aggregate"):
        a = pack["aggregate"]
        L.append("## Declared aggregate (advisory)")
        L.append("")
        L.append(f"Rule: {a['rule']}. Value: **{a['value']:.3f}**" if a["value"] is not None else "Rule declared; no value (weights sum to 0).")
        L.append("")
        L.append("| Check | Score | Weight | Declared by reviewer |")
        L.append("|---|---|---|---|")
        for u in a["inputs"]:
            L.append(f"| {u['check']} | {u['score']:.2f} | {u['weight']:.2f} | {'yes' if u['declared'] else 'default'} |")
        L.append("")
        L.append(a["note"])
        L.append("")
    L.append("---")
    L.append(pack["scope"])
    return "\n".join(L) + "\n"
