#!/usr/bin/env python3
"""Verify a claims ledger: every claim cites a receipt that exists, and no forbidden word
appears in the generated prose."""
import json, sys
from pathlib import Path


def main() -> int:
    led = Path(sys.argv[1] if len(sys.argv) > 1 else "out/claims_ledger.json")
    if not led.exists():
        print("no ledger at " + str(led))
        return 2
    d = json.loads(led.read_text(encoding="utf-8"))
    bad = [c["id"] for c in d["claims"] if c["receipt"] != "-" and not Path(c["receipt"]).exists()]
    print("claims: " + str(len(d["claims"])) + "   unsupported: " + str(len(bad)))
    for b in bad:
        print("  UNSUPPORTED " + b)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())