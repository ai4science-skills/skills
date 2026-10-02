#!/usr/bin/env python3
"""Usage: python scripts/run.py INPUT.json
INPUT.json: {"kind", "reference", "candidate", "ids", "temperature", "tolerances"} (see references/contract.md).
Exit 0 = ran (read "status"), 2 = ERROR."""
import json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from kernel import szl_quantization_check  # noqa: E402


def main():
    if len(sys.argv) != 2:
        print(__doc__); return 2
    result = szl_quantization_check(json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")))
    print(json.dumps(result, indent=2))
    return 2 if result["status"] == "ERROR" else 0


if __name__ == "__main__":
    sys.exit(main())
