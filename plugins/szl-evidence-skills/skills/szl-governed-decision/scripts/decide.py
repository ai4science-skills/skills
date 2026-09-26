#!/usr/bin/env python3
"""Classify text and emit the governed decision record plus its receipt payload."""
import argparse, json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
from szl_triage import policy as policy_mod
from szl_triage.decision import classify, to_receipt_payload


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("text")
    ap.add_argument("--policy", default=str(ROOT / "policies/triage_policy.v3.json"))
    a = ap.parse_args()
    pol = policy_mod.load(a.policy)
    rec = classify(a.text, pol)
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True).stdout.strip() or "unknown"
    print(json.dumps({
        "decision": {"verdict": rec.label, "state": rec.state, "lambda": rec.lambda_value,
                     "threshold": rec.threshold, "refusal_path": rec.refusal_path,
                     "refusal_reason": rec.refusal_reason, "aggregated": rec.aggregated,
                     "axes": dict(rec.axes), "confident": rec.confident},
        "receipt": to_receipt_payload(rec, Path(a.policy).stem, head)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())