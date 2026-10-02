#!/usr/bin/env python3
"""Usage: python scripts/run.py INPUT.json [--trec-run RUN.txt --trec-qrels QRELS.txt]
INPUT.json: {"k", "qrels", "run", "gates"} (see references/contract.md). With --trec-run/--trec-qrels the
TREC text formats are read instead of the JSON "run"/"qrels" fields. Exit 0 = ran (read "status"), 2 = ERROR."""
import argparse, json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from kernel import szl_retrieval_eval  # noqa: E402


def read_trec_run(path):
    run = {}
    for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) >= 6:  # qid Q0 docid rank score tag
            run.setdefault(parts[0], []).append((int(parts[3]), parts[2]))
    return {q: [d for _, d in sorted(v)] for q, v in run.items()}


def read_trec_qrels(path):
    qrels = {}
    for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) >= 4:  # qid 0 docid grade
            qrels.setdefault(parts[0], {})[parts[2]] = int(parts[3])
    return qrels


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input"); ap.add_argument("--trec-run", default=None); ap.add_argument("--trec-qrels", default=None)
    a = ap.parse_args()
    doc = json.loads(pathlib.Path(a.input).read_text(encoding="utf-8"))
    if a.trec_run:
        doc["run"] = read_trec_run(a.trec_run)
    if a.trec_qrels:
        doc["qrels"] = read_trec_qrels(a.trec_qrels)
    result = szl_retrieval_eval(doc)
    print(json.dumps(result, indent=2))
    return 2 if result["status"] == "ERROR" else 0


if __name__ == "__main__":
    sys.exit(main())
