# Contract: `szl.multiplicity.plan.v1` / `szl.multiplicity.results.v1`

Two UTF-8 JSON files, each at most 1,000,000 bytes. Duplicate JSON keys and non-finite numbers
are errors. Up to 1,000 hypotheses and 1,000 result rows. Decimal strings are recommended for
alpha and p-values to retain exact input precision; values may have at most 80 characters
and decimal exponent magnitude at most 1,000. More extreme values are rejected rather
than risk arithmetic underflow changing a decision.

Plan:

```json
{"schema":"szl.multiplicity.plan.v1","family_id":"primary","alpha":"0.05","method":"holm","hypotheses":[{"id":"endpoint-a","description":"Predeclared endpoint A"}]}
```

`method` is `holm` or `bh`. BH also requires `dependence_assumption` equal to `independent` or
`positive_regression_dependency` (PRDS on the true-null test statistics). This is a caller
assertion, never inferred from data. Alpha
must be in (0, 1); raw p-values must be in [0, 1]. IDs use letters, digits, period, underscore
or hyphen and are at most 64 characters.

Results:

```json
{"schema":"szl.multiplicity.results.v1","family_id":"primary","plan_sha256":"<64 lowercase hex digits>","results":[{"id":"endpoint-a","p_value":"0.012"}],"extra_attempts":[]}
```

`plan_sha256` hashes the plan file's **literal bytes**, including line endings. A null or absent
`p_value` is missing. `extra_attempts` must be present, even if empty. A nonempty list records
additional analyses attempted, without selecting or correcting them. Any missing planned row,
duplicate row, extra row, missing p-value, plan/family mismatch, or extra attempt produces HOLD and
an empty adjusted list. Malformed schemas, identifiers or probabilities produce ERROR.

For sorted p-values p(1) ... p(m), Holm's step-down adjusted value at rank i is the cumulative
maximum through i of min(1, (m-j+1) p(j)). BH's step-up adjusted value at rank i is the reverse
cumulative minimum from i through m of min(1, m p(j) / j). Sort ties by id for reproducibility;
adjusted values for tied p-values remain equal. The family is the complete planned denominator m;
missing outcomes are never assigned an invented p-value.

`COMPLETE` means the supplied family could be calculated. It does not establish that the family
was truly preregistered, the raw p-values are valid, all actual tests were reported, dependence
assumptions hold, or the results are scientifically or clinically sound. HASH matching is an
integrity check on supplied bytes, not a signature or trusted timestamp. No network, credentials,
model inference, data cleaning or experiment execution occurs.

Method sources: Sture Holm, [A Simple Sequentially Rejective Multiple Test Procedure](https://www.jstor.org/stable/4615733), *Scandinavian Journal of Statistics* 6(2), 1979; Yoav Benjamini and Yosef Hochberg, [Controlling the False Discovery Rate](https://rss.onlinelibrary.wiley.com/doi/10.1111/j.2517-6161.1995.tb02031.x), *JRSS B* 57(1), 1995; and Yoav Benjamini and Daniel Yekutieli, [FDR control under dependency](https://doi.org/10.1214/aos/1013699998), *Annals of Statistics* 29(4), 2001. The implementation is original and the examples are synthetic.
