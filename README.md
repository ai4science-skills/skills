# AI for Science skills

A community index of Claude skills for scientific work. Every skill is pinned to an exact commit and checked automatically before it is merged.

## Import everything with one line

Claude Science: **Skills > Import from GitHub**, paste:

    ai4science-skills/skills@v0.1.0

Claude Code:

    /plugin marketplace add ai4science-skills/skills

Then pick what you want. See [CATALOG.md](CATALOG.md) for every skill, its maintainer, license, pinned source, and any external service it contacts.

Imported skills do not update automatically. Review available changes in the target application before choosing an update.

## Current source preview

This proposed update pins all 35 science skills to the reviewed source commit
`baf0160e1acb2bee0de3c2324211d8d95e1b68b1`. The eight integrated workbench skills
remain in `szl-science-skills`; nineteen standalone core checks are in
`szl-science-ledger-skills`. Separate families contain experiment design,
multiplicity, assay audit, two replay/figure checks, paper evidence,
research change impact and uncertainty lineage. Each vendored plugin remains
below 1 MiB. The two evidence skills and flotation skill retain their separate pins.

This is a source preview, not a released tag or security admission. The independent
security-prerequisites pipeline is still BLOCKED. Review selected code and external
service declarations before importing; credentials are not required by these offline
science CLIs. An optional explicit workbench fetch reads a pinned public synthetic
study and records hashes without downloading model weights.

In Claude Science, GitHub import uses a repository URL and reads its default branch.
Import `https://github.com/ai4science-skills/skills` after an owner-approved merge;
for a fixed reviewed source use separately verified per-skill ZIPs from
szl-holdings/szl-skills. Do not assume that a GitHub import accepts a tag suffix.
The registry and SOURCE manifests retain exact commits and resource hashes.
Actual Claude Science registration and agent efficacy remain UNKNOWN.

The [current Claude Science documentation](https://claude.com/docs/claude-science/connectors-and-skills)
describes manual **Check for updates**. Imported skills do not update automatically.
Our offline update-preview tool compares captured catalogs, source changes, declared
services and name collisions before a researcher chooses an update; it performs no
application import, rename or installation. See [update-preview.md](docs/update-preview.md).

The explicit SZL smoke step executes only this selected science source. The general
importer and static passport never execute imported skill code. A retained negative
finding, readable figure or matching replay is not scientific validation, a formal
proof, model promotion or a production deployment. Lambda is Conjecture 1 (OPEN).

## What every skill must pass

| Check | Why |
|---|---|
| Plugin folder under 1 MB; only skill folders and license files are copied | Large repos fail to import |
| Unique plugin names and unique skill names | Avoids "name already in use" |
| Pinned to a full 40-character commit | A skill can't change after you import it |
| SKILL.md has a name, a description, and says what it does NOT do | Claude uses it at the right time |
| Every file the SKILL.md references exists | No skills calling code that was never committed |
| License file present and consistent with registry and SKILL.md | Clear reuse terms |
| Recognizable credential and personal-path patterns are scanned in all vendored bytes | Values are withheld from diagnostics; a static scan cannot prove that no sensitive data exists |
| Literal URL hosts and API hostnames are matched to exact declarations | Dynamic destinations still require manual review |

Passing the checks means a skill is well-formed and honest about what it touches. It does not mean the index maintainers vouch for its scientific correctness. Read a skill before relying on it.

The importer validates registry paths before making a request, reconciles each named ref with its immutable commit, refuses redirects and archive links, and limits downloads, decompression, member counts, and selected bytes. It prepares and statically checks the entire generation before replacing existing output, with rollback for handled replacement errors. It never executes skill code. See [SECURITY.md](SECURITY.md) for the remaining limits.

## Add your skill

See [CONTRIBUTING.md](CONTRIBUTING.md). Short version: add one entry to `registry.json`, run `python tools/sync.py` and `python tools/check.py`, open a pull request.

## Maintainers

Started by betterwithage on the Anthropic AI for Science forum. Co-maintainers welcome: ask on the forum or open an issue. Any skill that passes the checks and is relevant to scientific work is merged.
