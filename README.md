# AI for Science skills

A community index of Claude skills for scientific work. Every skill is pinned to an exact commit and checked automatically before it is merged.

## Import everything with one line

Claude Science: **Skills > Import from GitHub**, paste:

    ai4science-skills/skills@v0.1.0

Claude Code:

    /plugin marketplace add ai4science-skills/skills

Then pick what you want. See [CATALOG.md](CATALOG.md) for every skill, its maintainer, license, pinned source, and any external service it contacts.

Imported skills do not update automatically. Re-import when a new tag is announced.

## Science pack prerelease

The catalog adds an explicit prerelease of eight connected SZL science skills, pinned to
szl-holdings/szl-skills@v0.2.0-rc.1 and its immutable commit. The self-contained workbench
connects living project memory, numerical math checks, dataset leakage checks, model
evaluation, kernel comparison, paired qualification and retained file capsules. A separate
offline CI step exercises this selected pack; the general importer remains static and
never executes downloaded skill code.

The stable import above remains available. To try just the source science pack in Claude
Science, import:

    szl-holdings/szl-skills@v0.2.0-rc.1

Normal workbench use is offline. Optional fetch-triage reads the pinned public synthetic
study from Hugging Face, with no credentials or model weights. Actual Claude Science
registration and agent efficacy remain unverified; local/source CI checks do not establish
them. Setup and pilot instructions are in the source repository. No automatic update occurs.

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
