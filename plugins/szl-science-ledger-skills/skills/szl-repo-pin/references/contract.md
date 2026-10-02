# Contract: szl.repo-pin.v1

Declaration: `{"project": str, "repos": [{"name": unique str, "path": relative path}, ...]}`.

`pin` -> `{"status": PINNED | UNPINNED | ERROR, "repos": [{name, path, state: CLEAN | DIRTY | UNKNOWN | MISSING | NOT_A_REPOSITORY, head, uncommitted_changes,
tag_at_head, origin_url_as_configured}], "composite_sha256": sha256(canonical(sorted [[name, head], ...])) or null, "not_pinnable": [names], "limits"}`.
PINNED requires every repository CLEAN.

`verify` -> `{"status": MATCH | DRIFT | ERROR, "repos": [{name, path, state: MATCH | DRIFT | DIRTY | MISSING, recorded_head, current_head}], "composite_sha256_recorded"}`.
Overall MATCH only when every repository is MATCH.

Exit 0 = ran (read `status`), 2 = ERROR. Requires the `git` executable; no network.
