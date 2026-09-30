# Contributing a skill

1. Put your skills in a public GitHub repo, one folder per skill, each with a `SKILL.md` (YAML frontmatter with `name` and `description`). A `LICENSE` file must be at the repo root.
2. Fork this repo and add one entry to `registry.json`:

```json
{
  "name": "your-plugin-name",
  "repo": "your-user/your-repo",
  "ref": "v1.0.0",
  "sha": "full 40-character commit id of that ref",
  "path": "skills",
  "skills": ["skill-one", "skill-two"],
  "description": "One sentence: what these skills do.",
  "maintainer": "your forum or GitHub name",
  "license": "MIT",
  "hosted_services": ["api.example.com - what is sent and when; or leave the list empty"]
}
```

Get the full commit id with: `git ls-remote https://github.com/your-user/your-repo.git refs/tags/v1.0.0^{}` (or `refs/tags/v1.0.0` for a lightweight tag).

3. Run, from the repo root (Python 3.9+, no installs):

```
python tools/sync.py
python tools/check.py
```

4. Commit everything (`registry.json`, `plugins/`, `.claude-plugin/marketplace.json`, `CATALOG.md`) and open a pull request. CI re-runs both scripts and fails if anything differs.

Run `python -B -m unittest discover -s tools -p 'test_*.py' -v` when changing the importer. Keep paths portable, list every intended skill explicitly, and declare hosts as `hostname - purpose and data sent`. Literal documentation and credential-console links also need declarations when they are outside the built-in source/example/license hosts. Declaration matching uses exact hostnames, not substring matches. See SECURITY.md for archive limits and static-check boundaries.

To update your skill later, change `ref` and `sha`, run the two scripts, and open a new pull request.

## Naming

Use a plugin name and skill names that are unlikely to clash, e.g. prefix them with your lab or handle (`mylab-plate-reader`). The check fails if a skill name is already taken in the index.
