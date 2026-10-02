---
name: szl-refutation-ledger
description: "Keeps an append-only, hash-chained ledger of replication attempts: claims with their dependencies, each attempt as REPLICATED / NOT_REPLICATED / INCONCLUSIVE with an optional receipt digest, and withdrawals; reports per-claim state (UNTESTED, REPLICATED, NOT_REPLICATED, CONTESTED, INCONCLUSIVE, WITHDRAWN) and whether a claim rests on a shaken foundation. Use when a replication failed and nobody wrote it down, when a lab or consortium wants a shared record of what has and has not reproduced, when a reviewer asks what a conclusion depends on, or when the user says 'log this failed replication'. Not a verdict on whether a claim is true."
license: Apache-2.0
---

# Refutation ledger

Negative results are the most under-served artifact in science: a failed replication is usually
an email, a lab-meeting slide, or nothing. This skill gives it a receipt and a place. The ledger
is append-only and hash-chained: each entry carries the SHA-256 of the previous one, so a record
cannot be quietly edited, and `verify` finds the first broken link. Stdlib only, offline.

## When you would use this

- A student could not reproduce a published effect and you want that recorded with the same weight as the original.
- Three labs tried the same protocol; two succeeded, one did not, and the group wants one honest state, not a vote.
- A reviewer asks what your conclusion rests on; the ledger answers with the dependency trace.
- A consortium wants a shared, tamper-evident record of replication outcomes that outlives any one member.

## Ten seconds

```
python scripts/run.py status assets/example.json
```

The example ledger has three claims in a chain (C rests on B rests on A) and four attempts.
Expected result: A is `CONTESTED` (one replicated, one not, one inconclusive), B is
`NOT_REPLICATED`, and C, which nobody has tested, has foundation `SHAKEN` because it rests on B.
One attempt carries no receipt; it is counted and flagged, never dropped.

```
python scripts/run.py status assets/example.json --claim C
```

prints one paragraph for a methods section or a reply to a reviewer.

## Recording

```
python scripts/run.py init ledger.json --title "Pathway P replications"
python scripts/run.py append ledger.json claim.json
python scripts/run.py append ledger.json assets/new_attempt.json
python scripts/run.py verify ledger.json
```

Record a claim before the attempts that test it and before any claim that depends on it; the
ledger refuses forward references so the dependency trace is always resolvable. An attempt
should name a receipt (a session receipt, a capsule, or any file whose SHA-256 you can state).
Attempts without a receipt are accepted and flagged as unreceipted.

## States

| State | Meaning in this ledger |
|---|---|
| UNTESTED | no attempt recorded |
| REPLICATED | at least one replicated, none not replicated |
| NOT_REPLICATED | at least one not replicated, none replicated |
| CONTESTED | both outcomes present; the ledger does not break ties |
| INCONCLUSIVE | only inconclusive attempts |
| WITHDRAWN | the claim's author withdrew it; attempts remain on record |

Foundation: `SOUND` when every dependency is replicated, `SHAKEN` when any dependency, directly or
transitively, is NOT_REPLICATED, CONTESTED or WITHDRAWN, `UNKNOWN` when a dependency is untested.

## What it will not tell you

- Whether the claim is true. A state summarises the attempts in this ledger and nothing else.
- Whether an attempt was competent. Record `n`, `preregistered` and the receipt so a reader can judge.
- Who to believe. The chain proves order and integrity of the record, not the honesty of any entry.

Related: szl-research-anatomy tracks supporting and contradicting observations inside one project
with expiry; this ledger is the cross-lab, append-only record of replication outcomes.
