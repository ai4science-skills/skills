# Review a skill update before importing

`tools/update_preview.py` compares two retained local catalog directories. It
does not contact GitHub, install a skill, execute candidate programs, rename a
skill or update application settings. It is an offline prototype for the update
notice and collision/disclosure requests raised in the community forum.

After separately obtaining and reviewing the old and candidate catalogs:

```text
python -B tools/update_preview.py --before OLD_CATALOG --after CANDIDATE_CATALOG --occupied-name my-personal-skill
```

Repeat `--occupied-name` for existing personal or imported skill names. The tool
prints JSON with source pins, changed file hashes, added and removed skills,
complete service-declaration changes, exact hostname changes, byte counts, and
collisions. Each skill also receives a publisher-qualified review identity such
as `example/science/skills/toy-skill`. This identity is a label; it is never used
as an installation path or an automatic rename. Resolve collisions in the target
application after reviewing internal references.

Claude Science's [current documentation](https://claude.com/docs/claude-science/connectors-and-skills#update-skills-imported-from-github)
already describes a manual **Check for updates** flow, with changed and new
skills selected for review, without automatic checks or automatic updates. This
tool adds a separate local record of captured source/file hashes, declared
service changes and publisher-qualified collision identities. It does not claim
to add a missing manual-update button or to have tested that live interface.

`REVIEW_REQUIRED` means something changed or a candidate name is occupied.
`NO_CHANGE` means the captured registry semantics and plugin paths/bytes agree
and no supplied collision was observed. Both are non-installable preview results.
Exit 0 only says the preview completed. Exit 2 with `BLOCKED` means the retained
inputs were incomplete, invalid, linked, modified or oversized. Failed input
values are withheld, including recognizable credential-shaped declarations.

Each catalog is bound to its raw registry digest. Every selected plugin must
have a matching `SOURCE.json` identity, exact file membership and hashes, a
captured license and each selected `SKILL.md`. Reads use the existing bounded
inventory helpers, refuse observed links/reparse points and special files, and
retain at most 1 MiB per plugin including its manifest. Caller-held immutable
input directories are required; these filesystem checks are not an OS sandbox
against concurrent hostile ancestor replacement. Digests bind local paths and
bytes, not modes or empty directories. Supplied Git pins and matching hashes do
not independently authenticate a publisher or prove a remote tag is unchanged.

Service text is a declaration. Dynamic destinations, actual credential needs,
permissions and scientific effects remain unassessed. Credentials lack a
structured registry contract, so the output retains
`UNSTRUCTURED_DECLARATIONS_REVIEW_REQUIRED`; it cannot certify that a new service
is safe or that the description is complete. Read changed code and instructions
and choose any update explicitly. This tool neither clears the repository's
separate security prerequisites nor establishes live Claude Science support.

Run the focused regressions with:

```text
python -B -m unittest discover -s tools -p test_update_preview.py -v
```
