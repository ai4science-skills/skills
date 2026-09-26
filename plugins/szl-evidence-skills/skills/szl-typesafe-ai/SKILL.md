---
name: szl-typesafe-ai
license: Apache-2.0
description: >
  TypeSafe/Jev: Choice/Noul/Score in code, not TypeScript types. System One
  models turn natural language and application state into probabilities
  that software can compose. Use when building routing, ranking,
  extraction, verification, or replacing an LLM prompt-and-parse step
  with structured decisions; also when brainstorming what TypeSafe could
  make possible. Do not use for TypeScript/Java/Rust static types,
  Zod/Pydantic/mypy/JSON Schema/protobuf codegen, or asking whether a
  pipeline is type-safe. At SZL, Jev is an optional second reader only.
---

# TypeSafe at SZL — second reader, not the gate

Live docs are the source of truth. Read them as part of the task:

- Index: https://docs.typesafe.ai/llms.txt
- System One: https://docs.typesafe.ai/concepts/system-one.md
- How to build: https://docs.typesafe.ai/concepts/how-to-build-with-system-one.md
- State: https://docs.typesafe.ai/concepts/state.md
- Primitives: https://docs.typesafe.ai/primitives.md
- Choice: https://docs.typesafe.ai/primitives/choice.md
- Noul: https://docs.typesafe.ai/primitives/noul.md
- Score: https://docs.typesafe.ai/primitives/score.md
- Confidence: https://docs.typesafe.ai/confidence.md
- HTTP API: https://docs.typesafe.ai/api.md
- Python SDK: https://docs.typesafe.ai/sdk/python.md
- JavaScript SDK: https://docs.typesafe.ai/sdk/javascript.md
- Official skill (MIT): https://github.com/typesafe-ai/skills/blob/main/skills/typesafe-ai/SKILL.md

This overlay does not replace those pages. If the index is unreachable, say so
and do not invent version-dependent fields.

## What Jev is allowed to do here

Code owns the workflow. Jev supplies typed judgments.

| Need | Primitive | Estate use |
| --- | --- | --- |
| One of a defined set | Choice | evidence class: MEASURED / HOLD / BLOCK / UNAVAILABLE |
| Whether a condition holds | Noul | claims_live, invents_joules, treats_hf_as_source, lambda_as_theorem, unsigned_as_live |
| Degree on ordered levels | Score | overclaim_severity |

Pack: `jev-plane/packs/overclaim_reader.json` (`szl.overclaim_reader.v1`).
Reference implementation (not bundled with this skill): the Jev client and compose helpers in [szl-typesafe-triage/jev-plane/plane](https://github.com/szl-holdings/szl-typesafe-triage/tree/8d73dd23f640aace362172fff55d82ef7de63f98/jev-plane/plane).
Governed wrap: `skills/szl-governed-decision`.

## Fail-closed contract (non-negotiable)

1. Missing `TYPESAFE_API_KEY`, HTTP 401/422/429/529, timeout, or malformed JSON → class `UNAVAILABLE`. Never PASS. Never MEASURED.
2. Local doctrine scanners stay deterministic code. Jev cannot raise an axis that code already blocked. Stricter of local class and reader wins.
3. Jev never mints `LIVE`. HTTP 200, Space Running, likes, and first paint are REACHABLE / MEASURED, not LIVE.
4. Jev never writes the Hugging Face Hub. GitHub `szl-holdings` is source. Hub is a demo mirror.
5. `jev_allow_alone` is always false. `auto_merge` is always false.
6. Noul has no separate confidence. Values near 0.5 are HOLD. `noul >= 0.65` on a forbidden claim → BLOCK.
7. Choice/Score `confidence < 0.55` → HOLD, even if the chosen label is MEASURED.
8. Energy / joules stay `UNAVAILABLE` unless a live exporter delta exists. Do not write `0`.
9. Unsigned receipts stay UNSIGNED-honest. Signer ABSENT and DSSE-LIVE stay distinct.
10. Pin a model id in receipts (`jev-1.13.0` today). Do not treat `jev-latest` as a proof pin.
11. This skill is not TypeScript, Zod, Pydantic, mypy, or JSON Schema.

## HTTP shape (current docs)

```
POST https://api.typesafe.ai/v1/systemone
Authorization: Bearer $TYPESAFE_API_KEY
```

```json
{
  "state": { "command_or_pr": { "text": "..." }, "measured": { } },
  "model": "jev-1.13.0",
  "questions": {
    "evidence_class": {
      "type": "choice",
      "instructions": "...",
      "criteria": { "MEASURED": "...", "HOLD": "...", "BLOCK": "...", "UNAVAILABLE": "..." }
    },
    "claims_live": { "type": "noul", "instructions": "..." }
  }
}
```

Python: `pip install typesafe-sdk` then `TypeSafeClient().system_one(state=..., questions={...})`
with `Noul`, `Choice`, `Score` from `typesafe_sdk`. Env: `TYPESAFE_API_KEY` from
https://console.typesafe.ai/keys — never commit the key, never print it.

## Compose rule

```
final = max_strict(local_class, jev_class)
BLOCK > HOLD > UNAVAILABLE > MEASURED
```

If Jev is UNAVAILABLE, local class still stands. Missing reader is not a veto of a
clean local MEASURED scan, and it is not a license to stamp LIVE.

## When not to load this skill

- Ordinary TypeScript / static-typing work
- Inventing a new product origin or flagship
- Publishing Hub cards as source of truth
- Closing P0s from a 200 OK alone
