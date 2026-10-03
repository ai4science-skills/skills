#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline audit. Exit 0 preserved, 1 regression/gap, 2 malformed input."""
import json
import pathlib
import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from kernel import szl_outcome_preservation

def pairs(items):
    out = {}
    for key, value in items:
        if key in out:
            raise ValueError("Duplicate JSON key")
        out[key] = value
    return out

def main():
    try:
        if len(sys.argv) != 2:
            raise ValueError("Supply one input JSON path")
        with pathlib.Path(sys.argv[1]).open('rb') as handle:
            raw = handle.read(262145)
        if len(raw) > 262144:
            raise ValueError("Input exceeds 256 KiB")
        record = json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Nonfinite JSON")))
        result = szl_outcome_preservation(record)
        print(json.dumps(result, indent=2, allow_nan=False))
        return int(result['status'] != 'PRESERVED_ON_SUPPLIED_COHORT')
    except (ValueError, TypeError, KeyError, OSError, OverflowError, RecursionError) as error:
        print(json.dumps({'status': 'ERROR', 'error_type': type(error).__name__}))
        return 2

if __name__ == '__main__':
    sys.exit(main())
