# Contract: szl.result-fragility.v1

Input: `{"arms": {"treatment": {"events": int, "total": int}, "control": {"events": int, "total": int}}, "alpha": (0,1) default 0.05,
"lost_to_follow_up": int (optional), "fragile_if_index_at_most": int (optional), "label": str}`. Events must not exceed totals; totals positive.

Output: `{"status": FRAGILE | ROBUST | SIGNIFICANT_UNJUDGED | NOT_SIGNIFICANT | ERROR, "n", "alpha", "fisher_p_two_sided", "risk_treatment", "risk_control",
"risk_difference", "risk_ratio", "lost_to_follow_up", "reasons", "limits"}` plus, when significant: `fragility_index` (null if exhausted), `fragility_quotient`,
`arm_modified`, `p_after`, `exhausted`; when not significant: `reverse_fragility_index`, `arm_modified`, `direction`, `p_after` (or a note when unreachable).

Fisher two-sided p sums the hypergeometric probabilities of all tables with probability <= observed (relative tolerance 1e-9). Exit 0 = ran, 2 = ERROR.
