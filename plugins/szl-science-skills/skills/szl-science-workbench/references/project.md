# Project and retained runs

`project.json` has schema `szl.science-project.v1`, a question, an input_scope
(SYNTHETIC, EXTERNAL or MIXED), unique artifacts and ordered checks. Each artifact declares
id, kind, title and a canonical relative path. Each check declares id, type, input and
depends_on artifact/check ids. Supported types are dataset, binary-model, categorical-model,
math, kernel, calibration-benchmark and paired. Inputs are bounded JSON documents;
categorical-model additionally names prediction and held-out JSONL artifacts explicitly.
Dataset inputs can name a rows_file JSONL artifact instead of embedding rows.
The implemented field is rows_files: each selection declares artifact and split, and can
declare columns mapping output column names to arrays of nested input field names. No field
is inferred: a missing path becomes null and is reported as missing. The triage adapter maps
training row.input and held-out prompt to the same selected prompt feature while preserving
the original files and their hashes. This projection is retained in the dataset input plan.

The graph has schema `szl.research-anatomy.v1`. Input-file nodes and selected implementation
nodes have hashes observed from bytes. Each result depends on its selected artifacts and
the corresponding implementation node. The overall run depends on all check nodes, and
the recorded conclusion depends on the run. `check` compares against the newest completed
run snapshot and propagates invalidation through this graph. Code changes count as source
changes. Deleted/unsafe inputs are recorded as unavailable and invalidate their descendants.

Each `runs/<UTC>-<uuid>/` contains report.json, graph.json, anatomy.json,
implementations.json, capsule.json and the individual reports. Files are created
exclusively. The complete capsule covers project.json, graph.json, explicitly named inputs
and retained outputs. A process-level project lock rejects concurrent writers; after an
abrupt crash, inspect the retained incomplete run before manually clearing the lock.
An incomplete run is never selected as the newest successful run.

Prior assessments are retained before graph corrections. Subsequent run snapshots use
szl_anatomy_update to preserve previous nodes and persistent downstream recheck flags.
Only check and overall-run nodes just executed are re-recorded as current. A scientist's
claims keep their recheck flag until the scientist records the relevant new evidence.

The stock conclusion is a workflow record with claim_state UNKNOWN; it is not a scientific
finding. Numeric pass flags, matching files and caller-entered MEASURED labels do not
establish truth. Missing provenance, reuse permissions, model binding and independent
verification remain unresolved fields even when the workflow executes successfully.

There is no SQLite service, background daemon, automatic network refresh or dependency
installation. Files remain inspectable by the scientist and can be versioned using their
existing repository. Do not put personal records in a public project or release artifact.
