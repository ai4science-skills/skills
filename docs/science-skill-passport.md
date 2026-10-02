# Science skill passport: static preview v0

The community index can now emit a machine-readable preview for one indexed
skill, without running that skill or contacting its source. This is a prototype
for a **pre-import disclosure**, not a scientific or security approval.

```console
python -B tools/science_passport.py --plugin szl-science-skills --skill szl-research-anatomy
```

The command first requires the whole local index to pass its existing static
checks. It then binds the selected skill's vendored bytes to `SOURCE.json` and
reports the exact source repository, ref, 40-character commit, declared license
and maintainer, entrypoint digest, asset fixture candidates and their digests,
and the registry's service declarations. Output is deterministic JSON following
`schema/science-skill-passport.schema.json`. A changed byte or invalid registry
causes a nonzero `BLOCKED` result. No output file is written.
Before the existing auditor runs, the command bounds registry and marketplace
metadata to 256 KiB each and the plugin tree to 10,000 entries and 50 MiB. It
blocks rather than truncates if one skill has over 2,048 vendored files, over 128
fixture candidates, or a JSON preview over 64 KiB. These are resource bounds,
not a sandbox or a race-free filesystem proof.

`STATIC_PREVIEW_ONLY` is deliberately narrow:

- A source ref is checked against an immutable commit by the index importer;
  the passport reads the already-vendored source and cannot re-verify a remote
  ref at display time.
- Service declarations are maintainer prose. Dynamic destinations and credential
  needs are **not** machine-verifiable from the current registry; the passport
  says `NOT_CHECKED` and `UNSTRUCTURED_REVIEW_REQUIRED` respectively.
- Asset files are fixture *candidates*. Their bytes are hashed, but this check
  does not establish that they are synthetic, licensed for reuse, or scientifically
  representative.
- `skill_execution`, `claude_science_import`, and `scientific_validity` remain
  `NOT_RUN`, `NOT_OBSERVED`, and `NOT_EVALUATED`. Passing the index checks is not
  an actual Claude Science import, an agent evaluation, or an efficacy claim.
- The independent security-prerequisites workflow remains a fail-closed scaffold.
  This preview neither replaces nor satisfies that gate.

For a future v1, we propose structured network and credential declarations, an
opt-in synthetic self-test with explicit expected end-state assertions, and an
independently attached in-app run receipt. The receipt must identify the exact
installed version and preserve failures; it must not be inferred from a static
check or auto-updated without the recipient's choice. The v0 tool intentionally
does not accept a caller-supplied `PASS` field.
