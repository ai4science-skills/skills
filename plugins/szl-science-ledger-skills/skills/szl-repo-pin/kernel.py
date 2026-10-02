"""szl-repo-pin — one digest over every repository an analysis depends on.

Stdlib only. Offline. Uses the local `git` executable; never contacts a remote.

Input (a declaration the analyst writes once):
  {"project": "...", "repos": [{"name": "analysis", "path": "code/analysis"}, {"name": "data-prep", "path": "code/prep"}]}

`pin` records, for each repository under --root: HEAD commit, whether the working tree is clean,
the exact tag at HEAD if any, the origin URL as configured (not contacted), and the count of
uncommitted changes. The composite pin is the SHA-256 over the sorted (name, head) pairs and is
PINNED only when every tree is clean; otherwise UNPINNED with the dirty repositories named, because
a hash over uncommitted work cannot be re-derived by anyone else.

`verify` re-reads the repositories and reports MATCH / DRIFT / MISSING per repository.

What PINNED means: these exact commits were checked out, with nothing uncommitted, when the pin
was written. It does not mean the commits are published anywhere, or that the code is correct.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

SCHEMA = "szl.repo-pin.v1"


def szl_canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _safe(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or relative.startswith(("/", "\\")) or ".." in Path(relative).parts:
        raise ValueError("repo paths must be relative to the root and may not contain ..: %r" % (relative,))
    return root / relative


def _git(path: Path, *args) -> tuple[int, str]:
    try:
        done = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, timeout=60,
                              env={"GIT_TERMINAL_PROMPT": "0", "PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "")})
    except (OSError, subprocess.TimeoutExpired) as error:
        return 127, str(error)
    return done.returncode, (done.stdout or "").strip()


def szl_inspect_repo(root: Path, relative: str) -> dict:
    path = _safe(root, relative)
    if not path.is_dir():
        return {"path": relative, "state": "MISSING"}
    code, head = _git(path, "rev-parse", "HEAD")
    if code != 0 or len(head) != 40:
        return {"path": relative, "state": "NOT_A_REPOSITORY", "detail": head[:200]}
    code, porcelain = _git(path, "status", "--porcelain", "--untracked-files=all")
    changes = [line for line in porcelain.splitlines() if line.strip()] if code == 0 else None
    _, tag = _git(path, "describe", "--tags", "--exact-match", "HEAD")
    _, origin = _git(path, "remote", "get-url", "origin")
    return {"path": relative, "state": "CLEAN" if changes == [] else ("DIRTY" if changes else "UNKNOWN"), "head": head,
            "uncommitted_changes": len(changes) if changes is not None else None, "tag_at_head": tag or None, "origin_url_as_configured": origin or None}


def szl_make_pin(root, declaration: dict) -> dict:
    root = Path(root)
    if not isinstance(declaration, dict) or not isinstance(declaration.get("repos"), list) or not declaration["repos"]:
        return {"status": "ERROR", "error": "declaration needs a non-empty repos list"}
    names, repos = set(), []
    for item in declaration["repos"]:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"] or item["name"] in names:
            return {"status": "ERROR", "error": "each repo needs a unique name"}
        names.add(item["name"])
        try:
            record = szl_inspect_repo(root, item.get("path"))
        except ValueError as error:
            return {"status": "ERROR", "error": str(error)}
        repos.append({"name": item["name"], **record})
    problems = [r["name"] for r in repos if r["state"] != "CLEAN"]
    pairs = [[r["name"], r.get("head")] for r in sorted(repos, key=lambda r: r["name"])]
    composite = hashlib.sha256(szl_canonical(pairs).encode("utf-8")).hexdigest() if not problems else None
    return {"status": "PINNED" if not problems else "UNPINNED", "schema": SCHEMA, "project": declaration.get("project", ""), "repos": repos,
            "composite_sha256": composite, "not_pinnable": problems,
            "limits": ["A pin records which commits were checked out with nothing uncommitted; it does not say they are published or correct.",
                       "Origin URLs are read from local configuration and never contacted."]}


def szl_verify_pin(root, pin: dict) -> dict:
    root = Path(root)
    if not isinstance(pin, dict) or pin.get("schema") != SCHEMA or not isinstance(pin.get("repos"), list):
        return {"status": "ERROR", "error": "not a %s pin" % SCHEMA}
    rows = []
    for recorded in pin["repos"]:
        try:
            now = szl_inspect_repo(root, recorded.get("path"))
        except ValueError as error:
            return {"status": "ERROR", "error": str(error)}
        if now["state"] in ("MISSING", "NOT_A_REPOSITORY"):
            state = "MISSING"
        elif now.get("head") != recorded.get("head"):
            state = "DRIFT"
        elif now["state"] != "CLEAN":
            state = "DIRTY"
        else:
            state = "MATCH"
        rows.append({"name": recorded.get("name"), "path": recorded.get("path"), "state": state, "recorded_head": recorded.get("head"), "current_head": now.get("head")})
    overall = "MATCH" if all(r["state"] == "MATCH" for r in rows) else "DRIFT"
    return {"status": overall, "schema": SCHEMA, "repos": rows, "composite_sha256_recorded": pin.get("composite_sha256")}
