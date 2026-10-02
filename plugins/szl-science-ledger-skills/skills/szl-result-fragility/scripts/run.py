#!/usr/bin/env python3
"""Usage: python scripts/run.py INPUT.json
INPUT.json: {"arms": {"treatment": {"events", "total"}, "control": {"events", "total"}}, "alpha", "lost_to_follow_up", "fragile_if_index_at_most", "label"}.
Exit 0 = ran (read "status"), 2 = ERROR."""
import json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from kernel import szl_result_fragility  # noqa: E402


def main():
    if len(sys.argv) != 2:
        print(__doc__); return 2
    result = szl_result_fragility(json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")))
    print(json.dumps(result, indent=2))
    return 2 if result["status"] == "ERROR" else 0


if __name__ == "__main__":
    sys.exit(main())
