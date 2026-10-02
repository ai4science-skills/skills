# Cross-implementation contract

Sides `a` and `b`: `{label?, implementation?, input_sha256?, results: object}`. `results` is flattened to
dotted keys (`effect.estimate`, `coefs[0]`).

Numeric comparison: CONSISTENT when `|a-b| <= max(atol, rtol*max(|a|,|b|))`, else DIVERGENT. Strings and
booleans: exact. One-sided, non-finite or mixed-type values: INCOMPARABLE. Per-quantity tolerances override
the global ones by flattened key.

Overall: DIVERGENT > INCOMPARABLE > CONSISTENT, and differing declared input digests force INCOMPARABLE
even when every quantity agrees. `document_sha256` is the canonical digest of the comparison document.
