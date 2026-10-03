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
from pathlib import Path, PureWindowsPath

SCHEMA = "szl.repo-pin.v1"


def szl_canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _safe(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise ValueError("repo paths must be relative to the root: %r" % (relative,))
    windows_path = PureWindowsPath(relative)
    if windows_path.drive or windows_path.root or ".." in windows_path.parts:
        raise ValueError("repo paths must be relative to the root and may not contain ..: %r" % (relative,))
    try:
        base = root.resolve()
        path = (base / relative).resolve()
    except (OSError, RuntimeError) as error:
        raise ValueError("repo path cannot be resolved under the root: %r" % (relative,)) from error
    try:
        path.relative_to(base)
    except ValueError:
        raise ValueError("repo path escapes the root: %r" % (relative,))
    return path


def _git(path: Path, *args) -> tuple[int, str]:
    try:
        done = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, timeout=60,
                              env={"GIT_TERMINAL_PROMPT": "0", "PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "")})
    except (OSError, subprocess.TimeoutExpired) as error:
        return 127, str(error)
    output = done.stdout or ""
    return done.returncode, output[:-1] if output.endswith("\n") else output


def szl_inspect_repo(root: Path, relative: str) -> dict:
    path = _safe(root, relative)
    if not path.is_dir():
        return {"path": relative, "state": "MISSING"}
    code, top = _git(path, "rev-parse", "--show-toplevel")
    if code != 0 or not top or Path(top).resolve() != path:
        return {"path": relative, "state": "NOT_A_REPOSITORY", "detail": "path is not a repository root"}
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
    if (not isinstance(pin, dict) or pin.get("schema") != SCHEMA or
            pin.get("status") != "PINNED" or not isinstance(pin.get("repos"), list) or
            not pin["repos"] or pin.get("not_pinnable") != []):
        return {"status": "ERROR", "error": "not a %s pin" % SCHEMA}
    names, pairs = set(), []
    for recorded in pin["repos"]:
        if not isinstance(recorded, dict):
            return {"status": "ERROR", "error": "pin repos must be objects"}
        name, head = recorded.get("name"), recorded.get("head")
        changes = recorded.get("uncommitted_changes")
        if (not isinstance(name, str) or not name or name in names or
                not isinstance(recorded.get("path"), str) or not recorded["path"] or
                recorded.get("state") != "CLEAN" or type(changes) is not int or changes != 0 or
                not isinstance(head, str) or len(head) != 40 or
                any(c not in "0123456789abcdef" for c in head)):
            return {"status": "ERROR", "error": "pin has an invalid clean repository record"}
        names.add(name)
        pairs.append([name, head])
    expected = hashlib.sha256(szl_canonical(sorted(pairs, key=lambda pair: pair[0])).encode("utf-8")).hexdigest()
    if pin.get("composite_sha256") != expected:
        return {"status": "ERROR", "error": "pin composite digest does not match its repositories"}
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
