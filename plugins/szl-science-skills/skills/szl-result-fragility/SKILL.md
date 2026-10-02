---
name: szl-result-fragility
description: "Computes the fragility index of a two-arm binary result: Fisher's exact p on the 2x2 table, the smallest number of participants whose outcome would have to change for significance to disappear, the fragility quotient, and a FRAGILE / ROBUST judgment against the number lost to follow-up; for non-significant results, the reverse fragility index. Exact arithmetic, stdlib only. Use when a trial or A/B result 'reached significance' on a handful of events, when a reviewer asks how fragile a finding is, when comparing a result with its dropout count, or when the user says 'how many patients away from p = 0.05 is this'. Not an effect-size or design assessment."
license: Apache-2.0
---

# Result fragility

A result with p = 0.03 and seven participants lost to follow-up can be two outcome changes away
from p = 0.05. The fragility index (Walsh et al. 2014) counts those changes; comparing it with
the number lost to follow-up is the single most useful sanity check on a binary endpoint, and
reviewers increasingly ask for it. Stdlib only, exact arithmetic with `math.comb`, offline.

## When you would use this

- A two-arm trial, cohort comparison or A/B test reports a significant difference in a binary outcome.
- The dropout or missing-outcome count is about the size of the event difference.
- A systematic review wants the fragility of each included result stated the same way.
- A non-significant result is being described as "no effect" and you want to know how far it is from significance.

## Ten seconds

```
python scripts/run.py assets/example.json
```

Treatment 12/100 events versus control 25/100, seven lost to follow-up. Expected result:
`FRAGILE`; Fisher two-sided p 0.0279, fragility index 2 (two non-events becoming events in the
treatment arm removes significance), fragility quotient 0.01, reason "fragility index 2 <= 7
lost to follow-up". Change `lost_to_follow_up` to 1 and the status becomes `ROBUST` with the
same index: the index is the measurement, the status is the comparison you asked for.

## Definitions

- Fisher's exact test, two-sided, summing all tables at least as extreme (probability no larger than the observed).
- Fragility index: starting from the arm with fewer events, change one non-event to an event at a time until p >= alpha; the count is the index.
- Fragility quotient: index divided by total sample size.
- Reverse fragility index (non-significant results): the smallest number of single-participant outcome changes, in either arm and either direction, that makes p < alpha.

## Status

`FRAGILE` when the index is at most `lost_to_follow_up` or at most `fragile_if_index_at_most`;
`ROBUST` when it is above both declared comparators, or when flipping every non-event never
removes significance; `SIGNIFICANT_UNJUDGED` when the result is significant but no comparator was
declared (the index is still reported); `NOT_SIGNIFICANT` with the reverse index; `ERROR` for malformed counts.

## What it will not tell you

- Whether the effect is large enough to matter; see the risk difference and risk ratio it reports, then judge.
- Anything about adjusted, stratified or time-to-event analyses; this is the raw 2x2 table.
- Why participants were lost. Flipping outcomes is a thought experiment, not a model of attrition.
