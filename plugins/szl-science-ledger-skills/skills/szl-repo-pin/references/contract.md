# Contract: szl.repo-pin.v1

Declaration: `{"project": str, "repos": [{"name": unique str, "path": relative path}, ...]}`. Paths must resolve within `--root` to a Git worktree root; drive-qualified paths, symlink escapes, and ancestor-repository discovery are errors.

`pin` -> `{"status": PINNED | UNPINNED | ERROR, "repos": [{name, path, state: CLEAN | DIRTY | UNKNOWN | MISSING | NOT_A_REPOSITORY, head, uncommitted_changes,
tag_at_head, origin_url_as_configured}], "composite_sha256": sha256(canonical(sorted [[name, head], ...])) or null, "not_pinnable": [names], "limits"}`.
PINNED requires every repository CLEAN.

`verify` -> `{"status": MATCH | DRIFT | ERROR, "repos": [{name, path, state: MATCH | DRIFT | DIRTY | MISSING, recorded_head, current_head}], "composite_sha256_recorded"}`.
Overall MATCH only when an internally consistent `PINNED` record with a non-empty repository list is present and every repository is MATCH. A formerly dirty or incomplete record cannot later become a pin by verification.
Each recorded `uncommitted_changes` must be the integer `0`; JSON booleans and floating-point zeroes are not valid clean counts.

Exit 0 = ran (read `status`), 2 = ERROR. Requires the `git` executable; no network.
