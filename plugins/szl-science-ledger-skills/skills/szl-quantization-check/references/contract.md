# Contract: szl.quantization-check.v1

Input: `{"kind": "logits" | "embeddings" (default logits), "reference": [[number...]...], "candidate": [[number...]...], "ids": [str...] (optional),
"temperature": positive number (default 1.0, logits only), "tolerances": {min_cosine, max_fraction_below_cosine, max_kl, min_top1_agreement}}`.
Rows are compared position by position; all values must be finite; both matrices must have the same shape.

Per row: `cosine` (clamped to [-1, 1]); for logits `kl` = KL(softmax(reference/T) || softmax(candidate/T)) with a 1e-12 floor, `top1_reference`,
`top1_candidate`, `top1_agree` (ties resolve to the lowest index).

Output: `{"status": WITHIN_TOLERANCE | DEGRADED | INCOMPARABLE | ERROR, "aggregate": {rows, width, kind, cosine_mean, cosine_min, [kl_mean, kl_max,
top1_agreement, temperature], [fraction_below_min_cosine]}, "tolerances_evaluated", "tolerances_failed", "worst_rows" (up to five ids by cosine),
"per_row", "limits"}`. Exit 0 = ran, 2 = ERROR.
