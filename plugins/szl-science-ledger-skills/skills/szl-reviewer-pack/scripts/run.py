#!/usr/bin/env python3
"""Usage: python scripts/run.py PROJECT_DIR [--extra report.json ...] [--config review-config.json] [--output REVIEW.md] [--json pack.json]
Exit 0 = pack rendered (read "status"), 2 = error."""
import argparse, json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from kernel import szl_build_pack, szl_render_markdown  # noqa: E402

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("--extra", action="append", default=[], help="standalone report path relative to PROJECT_DIR (repeatable)")
    ap.add_argument("--config", default=None, help="review-config.json with optional scores/weights per check id")
    ap.add_argument("--output", default=None, help="write REVIEW.md here (default: print)")
    ap.add_argument("--json", default=None, help="also write the pack as JSON")
    a = ap.parse_args()
    config = json.loads(pathlib.Path(a.config).read_text(encoding="utf-8")) if a.config else None
    try:
        pack = szl_build_pack(a.project, a.extra, config)
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "reason": f"{type(exc).__name__}: {exc}"})); return 2
    md = szl_render_markdown(pack)
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(pack, indent=2) + "\n", encoding="utf-8")
    if a.output:
        pathlib.Path(a.output).write_text(md, encoding="utf-8")
        print(json.dumps({"status": pack["status"], "review": a.output, "unresolved": len(pack["unresolved"])}, indent=2))
    else:
        print(md)
    return 0

if __name__ == "__main__":
    sys.exit(main())
