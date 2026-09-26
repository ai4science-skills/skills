---
name: szl-governed-decision
description: >
  Make decisions that carry their own evidence. Wrap any classifier, policy engine or System
  One model in a fail-closed record that names why it refused, cites a digest rather than the
  text, and never asserts a number without a receipt on disk. Use when a decision must survive
  audit, when a model's output should be advisory rather than authoritative, or when a claim
  needs a state - MEASURED, BLOCKED, UNVERIFIED, UNAVAILABLE, NOT_CLAIMED - instead of a
  confident sentence. Complements typed-primitive skills: they produce the judgement, this
  governs what the judgement is allowed to do.
---

# Governed decision

A decision is not a label. It is a record: what was decided, by which path, on what evidence,
and what remains unproven.

## The four refusal paths

Every decision reports exactly one.

- `PRE_AGGREGATION` — a guard fired before any score existed. Sub-reason required:
  `INJECTION_GUARD` (adversarial pattern matched a versioned policy list, the model was not
  consulted), `META_CUE` (an enumerated handling cue), or `UNIDENTIFIED`.
- `ZERO_PINNED` — scores were computed and one was exactly zero, so the weighted geometric
  aggregate is zero. Weakest-link, not average.
- `BELOW_THRESHOLD` — all scores positive, aggregate under the floor.
- `NONE` — a confident decision was issued.

`UNIDENTIFIED` is not a fallback for convenience. If a refusal happens and no known guard
explains it, record `UNIDENTIFIED` and go find the guard. Naming a mechanism you have not
located in the code is a guess wearing a label.

## Never default a missing score

Asking for a score vector on a decision that computed no scores must raise, not return zeros.
In a zero-pinned aggregate, a substituted zero is indistinguishable from a genuine veto — it
manufactures the exact condition the system treats as fatal.

## The model provider contract

A model attached to this kind of decision may:

- lower one axis, never raise it — take the minimum, never the maximum;
- justify a lowering with a span that occurs **literally** in the input, verified before the
  score is honoured;
- return nothing at all, in which case the axis is untouched and the reason is recorded.

It may not return a label. Under zero-pinning this makes a bad provider incapable of causing a
confident error: the worst it achieves is over-refusal, which shows up immediately as churn
against a control corpus.

Consult the provider only on decisions that reach the aggregator. A decision already refused by
a guard must never be credited to the provider.

## Claim states

Attach one to every assertion, and generate prose from the states rather than writing prose and
hoping it matches.

| state | meaning |
|---|---|
| MEASURED | a receipt exists on disk and the number was read from it |
| UNRATIFIED | rests on labels no human has ratified |
| DEGRADED | works, below the standard you hold yourself to |
| BLOCKED | a negative result, recorded rather than omitted |
| UNVERIFIED | unmeasured; a probability is a claim until calibration measures it |
| UNAVAILABLE | no evidence exists; never rendered as health |
| NOT_CLAIMED | a deliberate refusal to assert |

## Rules that hold without exception

1. Carry `sha256(input)`, never the input, into any receipt, span or telemetry attribute.
2. Never fabricate a measurement you did not take. Energy is `null`, not `0`.
3. An unsigned receipt says `signed: false`. It renders as UNAVAILABLE, never as a pass.
4. Derive ids from content, not from clocks or randomness, so re-running produces no churn.
5. Pin model versions. A moving `-latest` silently changes answers under a tuned threshold.
6. Fix acceptance criteria before running the experiment, so they cannot be rewritten to match
   the result.
7. When a claim turns out wrong, add a correction with its receipt. Do not edit the old one
   away.

## Scripts

- `scripts/decide.py` — classify text, print the governed record and a receipt payload.
- `scripts/check_claims.py` — verify every claim in a ledger cites a file that exists.