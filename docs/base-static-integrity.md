# Base-owned static integrity: deliberately not skill admission

The `ai4s/static-integrity` commit status is a narrow prerequisite for the
community index. A successful status means that one PR head was inspected by
the checker and policy at a signed `main` base commit; its vendored skill
bytes matched the declared upstream commits; and the existing static metadata
check found no failure. It does **not** say a skill is safe, scientifically
valid, current, legally cleared, installable, or ready for release.

## Trust boundary

The `pull_request_target` workflow comes from the protected base. The scan job
has a `contents:read` GitHub token and checks out `github.sha`, never the PR
head. The PR head is downloaded by exact commit SHA as an inert tarball. The
scanner caps compressed and expanded bytes, member count, cumulative upstream
archive bytes, and receipt bytes; rejects traversal, alternate-case paths,
links, special files, and protected-checker modifications; and never imports,
executes, or builds candidate files. It validates the registry, generated
catalog and marketplace, upstream ref-to-commit pins, exact vendored file
bytes, and existing static audit. An unreachable provider, missing policy,
unverified base signature, moving source ref, or other failed check is `HOLD`.

Only protected `main` is an eligible base. The event must bind that ref and the
runner's exact base SHA; publication re-reads both the current base ref/SHA
and PR head, so retargeting to an unprotected branch cannot reuse this status.

Only the second job gets `statuses:write`. It consumes a bounded receipt from
the first job, checks the signed base-owned policy/checker hashes, checks the
scan job's own result, re-reads the open PR's exact head/repository from
GitHub, and posts success or failure to that head SHA. If the PR moved, it
does not post to the old head. If the target base SHA advanced between scan
and publication, it does not post a stale success. No candidate-controlled
field is interpolated into shell script text. A missing receipt or failed scan cannot publish
success. The status API response must confirm the same context, state, and
commit SHA; provider publication remains unverified until a live readback.

The receipt explicitly sets `installable: false`,
`provider_policy: UNVERIFIED`, and enumerates unobserved
dependency, vulnerability, behavior, science, rights, and freshness facets.
`tools/static_audit.py` and `ai4s/static-integrity` are not independent
full-security admission. The existing `prerequisites` check in
`.github/workflows/security-prerequisites.yml` must remain failing until a
separate reviewed security workflow/checker/policy and toolchain are actually
established, run, and evidenced. Do not merge, mark a blocked PR ready, or
admit a skill on the strength of this status alone.

## Deployment and maintenance

This PR is a proposal, not a change to live GitHub policy. Before any release,
an owner must review and merge the checker/policy by the normal protected,
signed path; verify that GitHub Actions ran the base-owned workflow; read back
the exact-head `ai4s/static-integrity` status and the provider app identity
that created it; then pin that observed app ID (not just the context text) as
the expected source when requiring this *additional* context in branch
protection. Read back the protection rule after the change. Until provenance
and rule enforcement are verified, keep the release gate `HOLD`. Do not remove
or weaken the existing `check` and `prerequisites` gates.
Keep strict/up-to-date branch protection enabled and read back a fresh run
after each base update: an older success tied to a previous base does not by
itself establish a current-base result. Commit statuses attach to a head SHA,
not a durable `(head SHA, base SHA)` pair; this context alone cannot enforce
freshness after a later base movement or PR retarget. The branch rule or merge
queue must supply that up-to-date invariant independently.
Test a fork PR as well as a same-repository PR: repository-scoped status
publication to fork heads is not established by offline tests. If Actions
event policy blocks `pull_request_target`, keep `HOLD`; explicitly configure
and read back a narrowly scoped repository event policy if available. Never
silently switch to a candidate-workflow checkout or a broad token.

The policy pins the checker, status publisher, workflow, and their existing
audit/sync dependencies against candidate modifications. Intentional updates
to these files require a separately reviewed protected-base maintenance
change; this checker will not bless its own changes. A live run after that
merge is needed to establish the new base binding. The static checker uses
its read-only token only for allowlisted GitHub API requests and follows
allowlisted GitHub HTTPS endpoints without redirects; unavailable private or
rate-limited sources stay `HOLD`.
