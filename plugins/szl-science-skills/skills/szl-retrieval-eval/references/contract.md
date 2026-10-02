# Contract: szl.retrieval-eval.v1

Input: `{"k": int (1..10000, default 10), "qrels": {query: {doc: grade}}, "run": {query: [doc, ...]}, "gates": {...}}`.
Grades are non-negative integers; 0 or absent means not relevant. Rankings are best first. Optional gates:
`min_judged_queries`, `min_ndcg`, `min_mrr`, `min_map`, `min_recall`. TREC formats are accepted by `scripts/run.py --trec-run/--trec-qrels`
(`qid Q0 docid rank score tag` and `qid 0 docid grade`).

Output: `{"status": SCORED | BELOW_GATES | INSUFFICIENT | ERROR, "aggregate": {queries_judged, k, ndcg_at_k, mrr, map, precision_at_k, recall_at_k,
queries_missing_from_run, queries_unjudged_in_run, queries_without_relevant_documents, duplicates_dropped_total}, "per_query": {query: {ndcg, reciprocal_rank,
average_precision, precision, recall, relevant_total, retrieved, relevant_retrieved, duplicates_dropped}}, "gates_evaluated", "gates_failed", "limits"}`.

Rules: every judged query is in the denominator (missing from run = zeros); unjudged run queries are listed, not scored; a query with no relevant judged
document scores zero and is listed; duplicates keep the first position. Exit 0 = ran, 2 = ERROR.
