---
name: szl-skill-conformance
description: "Checks retained scientific skill-sharing evidence: exact local source and supplied host-export resource bytes, explicit import aliases, task and result digests, and positive versus irrelevant-task trigger declarations. Use when a shared skill appears imported but invocation is uncertain, when comparing retained trials across hosts, or when an update may invalidate an earlier result. Offline checking never executes the candidate and never certifies real host invocation or scientific correctness."
license: Apache-2.0
---

# Skill conformance

Use this when asked whether an imported scientific skill actually worked. Separate
local source integrity, supplied export binding, declared trial consistency, actual
host observation, and scientific result validity. Never combine them into "verified".

1. Ask for the exact source skill directory, the host-exported resource directory,
   and retained task/result files. An import screenshot or catalog entry is not an
   invocation trace. Do not fabricate absent files or execute unknown candidate code.
2. Read [the evidence contract](references/contract.md). Record the source revision
   separately. This checker hashes local bytes, not Git publication or signatures.
3. Run the reviewed checker with Python 3.10+ and `-B` (no dependencies, network,
   credentials, provider writes, model weights, or subprocess execution):

   ```text
   python -B scripts/run.py --source PATH --host-export EXPORT --trials trials.json --trial-root RETAINED
   ```

   Without an export or trials, report `INCOMPLETE`. Do not turn missing evidence
   into a successful empty comparison. `--imported-name ALIAS` declares a display-name
   mapping; it does not excuse modified payload bytes.
4. Include a task that should invoke the skill and an unrelated task that should not.
   Bind both to retained results. Inspect whether the controls are meaningful:
   this checker cannot judge task relevance or output correctness from hashes.
5. Report `actual_host_invocation: NOT_VERIFIED` even when supplied records are
   internally consistent. Synthetic fixtures and operator exports cannot prove
   the app executed a skill. Unknown evidence fields, including `verified`, fail closed.
6. For a real Claude Science pilot, collect evidence inside the actual app through
   documented interfaces, retain exports, and have a researcher inspect the task,
   selected skill, resources, result and irrelevant-task control. Do not inject app
   state, change private databases, bypass permissions or auto-update imports.

This source candidate is outside the immutable v0.4.0 and v0.5.0-rc.3 releases.
No claims of cross-host portability, agent efficacy, novelty or scientific validation
follow from its offline tests. Review every resource before importing this skill.
