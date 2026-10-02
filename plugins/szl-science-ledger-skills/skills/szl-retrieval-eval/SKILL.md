---
name: szl-retrieval-eval
description: "Scores a literature or document retrieval system against relevance judgments: nDCG@k, MRR, MAP, precision@k and recall@k per query and on average, with judged queries that the system never answered kept in the denominator at zero, unjudged queries listed rather than silently scored, and duplicate results dropped and counted. Accepts JSON or TREC run/qrels files. Use when a lab evaluates a RAG or search pipeline over papers, protocols or records, compares two retrievers, or asks 'did the new embedding model actually find more of the relevant papers'. Not a judgment of whether the relevance labels are right."
license: Apache-2.0
---

# Retrieval evaluation with complete denominators

Labs building literature RAG usually report one nDCG from a notebook that quietly skipped the
queries the system failed on. This skill keeps every judged query in the denominator, lists the
queries nobody judged instead of scoring them, drops duplicate results and says how many, and
evaluates the gates you declare. Stdlib only, offline.

## When you would use this

- You replaced the embedding model in a paper-search pipeline and need to know whether recall@10 moved.
- Two retrievers are compared on the same judged query set and the comparison has to be reproducible.
- A reviewer asks how many of the evaluation queries had any relevant document at all.
- You have TREC-format run and qrels files from an existing benchmark and want the metrics without a framework.

## Ten seconds

```
python scripts/run.py assets/example.json
```

Five judged queries about CRISPR off-target search, organoid protocols, power analysis and
reporting guidelines, one of which the system never answered, plus one unjudged query the system
did answer. Expected result: `SCORED`, nDCG@5 0.5144, MRR 0.5, MAP 0.4511, recall@5 0.6;
`queries_missing_from_run` lists `q5-never-run` (scored zero, kept in the mean),
`queries_unjudged_in_run` lists `q9-unjudged` (excluded, reported), one duplicate dropped.
Raise `gates.min_judged_queries` to 20 and the status becomes `INSUFFICIENT` without hiding the numbers.

TREC files:

```
python scripts/run.py config.json --trec-run run.txt --trec-qrels qrels.txt
```

## Definitions

nDCG@k uses gain 2^grade - 1 and a log2(rank + 1) discount against the ideal ordering of the
judged relevant documents. MRR uses the first document with grade > 0. MAP is the mean of
average precision with binary relevance over all relevant documents, not only those retrieved.
Precision@k divides by k; recall@k divides by the number of judged relevant documents.

## Status

`SCORED` when no declared gate fails, `BELOW_GATES` when a metric gate fails, `INSUFFICIENT`
when fewer judged queries than `min_judged_queries` exist, `ERROR` for malformed input. Gates you
do not declare are not evaluated and are not reported as passed.

## What it will not tell you

- Whether the judgments are right or complete. Unjudged documents count as not relevant, so a pool
  built from other systems penalises a retriever that finds new relevant documents.
- Whether the difference between two systems is significant; pair the per-query metrics with
  szl-paired-science for that.
- Anything about answer quality downstream of retrieval.
