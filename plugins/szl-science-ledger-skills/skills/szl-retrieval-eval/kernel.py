"""szl-retrieval-eval — ranking quality for literature or document retrieval, denominators complete.

Stdlib only. Offline.

Input:
  {
    "k": 10,
    "qrels": {"q1": {"docA": 2, "docB": 1}, ...},      # graded relevance, 0 or absent = not relevant
    "run":   {"q1": ["docC", "docA", ...], ...},         # ranked document ids per query, best first
    "gates": {"min_judged_queries": 20, "min_ndcg": 0.3} # optional; absent gates are not evaluated
  }

Per judged query: nDCG@k (gain 2^rel - 1, log2 discount), reciprocal rank of the first relevant
document, average precision (binary rel > 0), precision@k, recall@k. A judged query missing from
the run scores zero on every metric and stays in the denominator; a run query with no judgments is
listed as unjudged and excluded from the means. Duplicate document ids in a ranking keep the first
position and are reported.

What a score means: agreement with the judgments supplied. Unjudged documents count as not
relevant, so a pool that was built from other systems penalises a system that finds new relevant
documents. Nothing here measures whether the judgments are right.
"""
from __future__ import annotations

import math

SCHEMA = "szl.retrieval-eval.v1"


def _err(message: str) -> dict:
    return {"status": "ERROR", "error": message}


def _dcg(gains: list) -> float:
    return sum(g / math.log2(i + 2) for i, g in enumerate(gains))


def szl_query_metrics(ranking: list, judgments: dict, k: int) -> dict:
    seen, deduped, duplicates = set(), [], 0
    for doc in ranking:
        if doc in seen:
            duplicates += 1
            continue
        seen.add(doc)
        deduped.append(doc)
    top = deduped[:k]
    rel = [judgments.get(doc, 0) for doc in top]
    gains = [2 ** r - 1 for r in rel]
    ideal = sorted((2 ** r - 1 for r in judgments.values() if r > 0), reverse=True)[:k]
    idcg = _dcg(ideal)
    relevant_total = sum(1 for r in judgments.values() if r > 0)
    hits = [i for i, r in enumerate(rel) if r > 0]
    ap = (sum((n + 1) / (i + 1) for n, i in enumerate(hits)) / relevant_total) if relevant_total else 0.0
    return {"ndcg": (_dcg(gains) / idcg) if idcg > 0 else 0.0,
            "reciprocal_rank": (1.0 / (hits[0] + 1)) if hits else 0.0,
            "average_precision": ap,
            "precision": (len(hits) / k) if k else 0.0,
            "recall": (len(hits) / relevant_total) if relevant_total else 0.0,
            "relevant_total": relevant_total, "retrieved": len(top), "relevant_retrieved": len(hits), "duplicates_dropped": duplicates}


def szl_retrieval_eval(document: dict) -> dict:
    if not isinstance(document, dict):
        return _err("input must be an object")
    k = document.get("k", 10)
    if not isinstance(k, int) or isinstance(k, bool) or k < 1 or k > 10000:
        return _err("k must be an integer between 1 and 10000")
    qrels, run = document.get("qrels"), document.get("run")
    if not isinstance(qrels, dict) or not qrels or not isinstance(run, dict):
        return _err("qrels must be a non-empty object and run an object")
    for q, judgments in qrels.items():
        if not isinstance(judgments, dict) or any(not isinstance(v, int) or isinstance(v, bool) or v < 0 for v in judgments.values()):
            return _err("qrels[%r] must map document ids to non-negative integer grades" % q)
    for q, ranking in run.items():
        if not isinstance(ranking, list) or any(not isinstance(d, str) for d in ranking):
            return _err("run[%r] must be a list of document id strings" % q)
    gates = document.get("gates", {}) or {}
    if not isinstance(gates, dict):
        return _err("gates must be an object")
    per_query, missing = {}, []
    for q in sorted(qrels):
        if q not in run:
            missing.append(q)
        per_query[q] = szl_query_metrics(run.get(q, []), qrels[q], k)
    unjudged = sorted(q for q in run if q not in qrels)
    no_relevant = sorted(q for q in qrels if per_query[q]["relevant_total"] == 0)
    n = len(per_query)
    means = {name: sum(m[name] for m in per_query.values()) / n for name in ("ndcg", "reciprocal_rank", "average_precision", "precision", "recall")}
    aggregate = {"queries_judged": n, "k": k, "ndcg_at_k": means["ndcg"], "mrr": means["reciprocal_rank"], "map": means["average_precision"],
                 "precision_at_k": means["precision"], "recall_at_k": means["recall"],
                 "queries_missing_from_run": missing, "queries_unjudged_in_run": unjudged, "queries_without_relevant_documents": no_relevant,
                 "duplicates_dropped_total": sum(m["duplicates_dropped"] for m in per_query.values())}
    failed = []
    if "min_judged_queries" in gates and n < gates["min_judged_queries"]:
        failed.append("min_judged_queries: %d < %s" % (n, gates["min_judged_queries"]))
    for gate, metric in (("min_ndcg", "ndcg_at_k"), ("min_mrr", "mrr"), ("min_map", "map"), ("min_recall", "recall_at_k")):
        if gate in gates and aggregate[metric] < gates[gate]:
            failed.append("%s: %.4f < %s" % (gate, aggregate[metric], gates[gate]))
    if any(f.startswith("min_judged_queries") for f in failed):
        status = "INSUFFICIENT"
    elif failed:
        status = "BELOW_GATES"
    else:
        status = "SCORED"
    return {"status": status, "schema": SCHEMA, "aggregate": aggregate, "per_query": per_query, "gates_evaluated": sorted(gates), "gates_failed": failed,
            "limits": ["Unjudged documents count as not relevant; a pool built from other systems penalises new relevant findings.",
                       "Judged queries missing from the run score zero and stay in the denominator.",
                       "Scores measure agreement with the supplied judgments, not whether the judgments are right."]}
