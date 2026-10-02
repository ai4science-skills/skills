#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Prepare and replay an offline, pinned CSV column mean experiment."""

import argparse
import json
import pathlib
import runpy
import sys

# This loads trusted package code before the engine's post-load drift comparison.
ENGINE = runpy.run_path(str(pathlib.Path(__file__).resolve().parent / "engine.py"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    make = sub.add_parser("prepare", help="freeze input, reference and engine hashes")
    make.add_argument("declaration", help="declaration JSON path relative to --root")
    make.add_argument("--root", required=True)
    make.add_argument("--output", required=True, help="new pin JSON path relative to --root")
    run = sub.add_parser("replay", help="run the fixed CSV mean and retain a receipt")
    run.add_argument("pin", help="pin JSON path relative to --root")
    run.add_argument("--root", required=True)
    run.add_argument("--receipt", required=True, help="new receipt JSON path relative to --root")
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            payload = ENGINE["_read_json"](ENGINE["read_file"](
                args.root, args.declaration, ENGINE["MAX_JSON"]))
            result = ENGINE["prepare"](args.root, payload)
            ENGINE["write_new_json"](args.root, args.output, result)
            print(json.dumps({"status": "PINNED", "pin_sha256": result["pin_sha256"], "output": args.output}, sort_keys=True))
            return 0
        ENGINE["_root"](args.root)
        try:
            pin_raw = ENGINE["read_file"](args.root, args.pin, ENGINE["MAX_JSON"])
        except FileNotFoundError:
            result = ENGINE["_receipt"](None, "REFUSED", "PIN_MISSING")
        except (OSError, ValueError):
            result = ENGINE["_receipt"](None, "REFUSED", "PIN_UNREADABLE")
        else:
            try:
                pin = ENGINE["_read_json"](pin_raw)
            except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError):
                result = ENGINE["_receipt"](None, "REFUSED", "INVALID_PIN")
            else:
                result = ENGINE["replay"](args.root, pin)
        ENGINE["write_new_json"](args.root, args.receipt, result)
        print(json.dumps({"status": result["status"], "reason": result["reason"], "receipt": args.receipt,
                          "receipt_sha256": result["receipt_sha256"]}, sort_keys=True))
        return {"MATCH": 0, "DIVERGED": 1}.get(result["status"], 2)
    except (OSError, ValueError, TypeError, UnicodeError, OverflowError, RecursionError) as error:
        print("experiment replay error: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
