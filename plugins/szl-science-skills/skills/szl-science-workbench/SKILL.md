---
name: szl-science-workbench
description: Run an integrated local research project with living anatomy, mathematical checks, dataset leakage checks, binary or categorical model evaluation, numerical kernel comparisons, paired qualification and file capsules. Use to connect these checks, resume a project, or invalidate conclusions after inputs change.
license: Apache-2.0
---

# SZL Science Workbench

Use this skill for a scientist-owned project that can be resumed from files. It includes
the seven underlying check implementations; it does not require sibling skill folders,
an inference service or a particular install name. Read `references/project.md` for the
project schema and evidence boundaries.

Start a small synthetic demonstration in a new directory:

```bash
python scripts/workbench.py init ./research-project
python scripts/workbench.py run ./research-project
python scripts/workbench.py check ./research-project
```

`run` reads only the selected project files and records a new immutable run directory.
Reports, actual file hashes, implementation hashes, a graph snapshot and a reproducibility
capsule are retained together. Scientific failures remain findings; an execution error
gives exit 2 and retains an ERROR record. `check` rereads the last run's inputs and code;
changed, missing or unsafe paths invalidate dependent runs and conclusions and give exit 1.
The newest run is selected by its retained UTC timestamp, never by a user-supplied latest
pointer. A retained capsule and graph cannot authenticate themselves against replacement.

To evaluate the actual pinned public SZL triage study without downloading model weights:

```bash
python scripts/workbench.py fetch-triage ./triage-project
python scripts/workbench.py run ./triage-project
python scripts/workbench.py check ./triage-project
```

This opt-in command contacts huggingface.co for the declared frozen train/held files and
saved baseline/seed-011 predictions, all at one exact revision. The data is synthetic;
saved predictions are real model outputs according to the study's unsigned declarations.
The categorical evaluator joins row ids to retained targets and recomputes correctness;
it ignores saved correctness flags and never invents probabilities. Download receipts
cover retrieved bytes, not model authenticity or data rights. No private second-brain
records are fetched. Network errors stop the fetch and leave a visible incomplete project.

In the synthetic demo, the kernel stage executes the pinned SZL calibration reference and
the adapted helper on identical inputs, checks numerical agreement, then measures both
on the local CPU. It records actual durations and code/input hashes. That measures these
implementations on this input; it does not establish a GPU, energy or general speed claim.
The paired stage retains its preregistration and independence declarations separately
from numerical qualification. An unregistered demonstration cannot qualify as research.

Change explicit inputs and run again to collect new evidence. Prior graph/run snapshots
remain on disk. To add a claim or paper, update the project's graph with dependency ids;
a rerun clears only the newly executed check nodes, never an unrelated claim's recheck flag.
Keep Lambda as Conjecture 1 (OPEN). No helper promotes, deploys, merges or marks truth verified.

Outside services: none during init/run/check; fetch-triage explicitly contacts
huggingface.co and its public artifact CDN. Credentials: none. Runtime: Python 3.10+,
standard library only. No packages, weights or arbitrary commands are installed or executed.
