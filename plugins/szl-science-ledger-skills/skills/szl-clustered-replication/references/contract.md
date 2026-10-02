# Paired cluster contract

Input has exactly `plan` and `rows`. The plan fields are:

- `schema`: `szl.clustered-replication.v1`.
- `experimental_unit`, `observational_unit`, `unit`: bounded identifiers. Clusters must identify
  the actual experimental unit chosen for the question and intervention, not a convenient label.
- `expected_cases`: complete list of `{id, cluster}` pairs. Every id must occur exactly once
  in outcomes, assigned to that same cluster. Missing, extra, duplicate and reassigned rows fail.
- `reported_n`: the N reported for the paired inference; differences from cluster count are flagged.
- `independent_clusters_declared`: true only if there is separate evidence for independent units.
- `sign_flip_basis`: `paired_randomization`, `symmetric_cluster_differences` or `undeclared`.
  Paired randomization means an independent fair within-cluster swap of the two conditions was
  actually used and supports the sharp null. Symmetry means independent differences have a joint
  null distribution invariant to independent sign flips. Neither is verified by this helper.
- `min_clusters`: 2–16, `alpha`: strictly between 0 and 1, `minimum_improvement`: nonnegative.

Each row is `{id, cluster, unit, baseline_loss, candidate_loss}`. Losses must be finite nonnegative
numbers no larger than 10^12; improvement is baseline minus candidate. All rows use the one
declared unit. There is no implicit normalization or pooling of unlike measurements.

The plan digest is SHA-256 over UTF-8 contract JSON, sorted keys, compact separators, Unicode
unescaped and nonfinite values forbidden. It is not RFC 8785 and is not a signature. JSON numeric
types matter to this commitment. The separately provided expected digest is matched before
conditional inference. Matching says nothing about timing, author, input consumption, model
identity or rights. The observations receive their own digest in the report.
The CLI also records the raw input and loaded helper file digests. Its decoder rejects nonfinite
numbers, duplicate keys, invalid Unicode, excessive depth and overflow/underflow to float
infinity/zero. Supported fractional JSON tokens use Python binary floats; rational arithmetic
is exact over those parsed values, not over an arbitrary-precision decimal interpretation.
Reports use finite binary floats. If a nonzero exact cluster, overall, row-weighted or
leave-one-out mean would be displayed as zero, the result is INPUT_ERROR without inference.
This avoids a zero effect summary contradicting a positive exact-effect decision.

The cluster effect is the arithmetic mean of the paired improvements in that cluster. The
reported main effect is the unweighted mean of those cluster means, so a large cluster does
not receive more inferential weight. This targets equal experimental units; it may not be the
estimand the scientist needs. Raw row weighting is also reported as a descriptive comparison.
Duplicating every observation within a cluster leaves its mean and conditional p value unchanged.

Under the declared assumptions, enumerate every one of the 2^K sign vectors for the K cluster
means, including zeros. Compare the absolute signed sum to the observed absolute sum; ties
count as extreme. p = extreme vectors / 2^K. Arithmetic is exact over rational representations
of the parsed JSON numbers, avoiding tolerance choices in the tail count. No random sampling,
normal approximation, optional stopping or added pseudocount is used. Thresholds apply to this
conditional calculation only; failure findings remain visible regardless of its p value.

Leave-one-cluster-out means show whether a positive effect or declared minimum effect survives
each omission. They are descriptive sensitivity checks: no second set of p values, automatic
exclusions, multiplicity claim or external replication is produced. At K=1 this list is empty
and the result is descriptive. The method does not repair a poor experimental design or replace
mixed models for nested/crossed designs or sampling-dependent cluster sizes.

Methodological sources, summarized rather than copied:

- [Lazic, Clarke-Williams and Munafò, What exactly is N?](https://journals.plos.org/plosbiology/article?id=10.1371%2Fjournal.pbio.2005282): distinguish experimental from observational units.
- [Jordan, Population sampling affects pseudoreplication](https://journals.plos.org/plosbiology/article?id=10.1371%2Fjournal.pbio.2007054): averaging does not resolve every dependence structure or estimand.
- [Winkler et al., Permutation inference for the general linear model](https://pmc.ncbi.nlm.nih.gov/articles/PMC4010955/): sign flipping requires suitable invariance and independence assumptions.

This is an original implementation of this restricted contract. No source code from those papers
is included. Local synthetic tests establish behavior of the calculation, not agent efficacy,
scientific validity, biological mechanism or general superiority over statistical packages.
