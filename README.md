# AI for Science skills

A community index of Claude skills for scientific work. Every skill is pinned to an exact commit and checked automatically before it is merged.

## Import everything with one line

Claude Science: **Skills > Import from GitHub**, paste:

    ai4science-skills/skills@v0.1.0

Claude Code:

    /plugin marketplace add ai4science-skills/skills

Then pick what you want. See [CATALOG.md](CATALOG.md) for every skill, its maintainer, license, pinned source, and any external service it contacts.

Imported skills do not update automatically. Re-import when a new tag is announced.

## What every skill must pass

| Check | Why |
|---|---|
| Plugin folder under 1 MB; only skill folders and license files are copied | Large repos fail to import |
| Unique plugin names and unique skill names | Avoids "name already in use" |
| Pinned to a full 40-character commit | A skill can't change after you import it |
| SKILL.md has a name, a description, and says what it does NOT do | Claude uses it at the right time |
| Every file the SKILL.md references exists | No skills calling code that was never committed |
| License file present and consistent with registry and SKILL.md | Clear reuse terms |
| No tokens, keys, personal paths, or private IPs | Nothing leaks |
| Every external host a skill names or calls is declared | You know when data leaves your machine |

Passing the checks means a skill is well-formed and honest about what it touches. It does not mean the index maintainers vouch for its scientific correctness. Read a skill before relying on it.

## Add your skill

See [CONTRIBUTING.md](CONTRIBUTING.md). Short version: add one entry to `registry.json`, run `python tools/sync.py` and `python tools/check.py`, open a pull request.

## Maintainers

Started by betterwithage on the Anthropic AI for Science forum. Co-maintainers welcome: ask on the forum or open an issue. Any skill that passes the checks and is relevant to scientific work is merged.