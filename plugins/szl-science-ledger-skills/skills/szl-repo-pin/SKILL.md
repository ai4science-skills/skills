---
name: szl-repo-pin
description: "Records one SHA-256 pin over every Git repository an analysis depends on: HEAD commit, clean or dirty tree, exact tag, configured origin, for each declared repository, and a composite digest that exists only when every tree is clean; later re-reads them and reports MATCH / DRIFT / DIRTY / MISSING per repository. Use when an analysis spans several repositories (analysis code, data preparation, a vendored utility library), when a capsule or session receipt needs to name the code versions, or when a collaborator asks 'which commits did you actually run'. Not a statement that the commits are published or correct."
license: Apache-2.0
---

# Multi-repository pin

Most analyses live in more than one repository, and "we ran the main branch" names none of
them. This records the exact commit of each declared repository and refuses to produce a
composite pin while any tree has uncommitted changes, because a hash over work nobody else can
check out is not a pin. Stdlib plus the local `git` executable; no remote is contacted.

## When you would use this

- The paper's analysis uses your code, a data-preparation repository and a lab utility library; the methods section needs all three commits.
- A session receipt or reproducibility capsule should name code versions, not branch names.
- Six months later a result differs and you need to know which repository moved.
- A collaborator reruns your pipeline and you want MATCH or DRIFT, not a conversation.

## Ten seconds

```
python scripts/run.py pin assets/declaration.json --root /path/to/project --output pin.json
python scripts/run.py verify pin.json --root /path/to/project
```

`assets/declaration.json` names three repositories under a project root. With clean trees the
pin is `PINNED` with one composite digest; with an uncommitted file in any of them it is
`UNPINNED` and names the repository. `verify` reports per repository `MATCH`, `DRIFT` (HEAD
moved), `DIRTY` (same HEAD, uncommitted changes) or `MISSING`. `assets/example.json` is a recorded
pin for reading with `show`; the tests build real temporary repositories.

## Rules

- Paths are relative to `--root` and may not escape it.
- A repository is `CLEAN` only when `git status --porcelain --untracked-files=all` is empty.
- The composite digest is SHA-256 over the sorted (name, HEAD) pairs; it is `null` when any repository is not clean.
- Origin URLs are read from local configuration for the record and never contacted.

## What it will not tell you

- Whether the commits exist anywhere but your disk. Push them, or archive the capsule, before citing the pin.
- Whether the code is correct, or whether the dependencies installed matched; see szl-reproducibility-capsule and szl-session-receipt for files and environment.
- Anything about repositories you did not declare.
