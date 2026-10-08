---
name: szl-skill-update-review
description: "Compare pinned local skill packages using inventories and a retained lock; report changed skills, files, declarations and reruns without approving safety or validity."
license: Apache-2.0
---

# Skill package update review

Compare immutable packages using SHA-256 inventories and an independent lock. Python 3.10+, standard library, offline.

## Run

```sh
python scripts/run.py OLD_INVENTORY NEW_INVENTORY --old-root OLD_PACKAGE --new-root NEW_PACKAGE --lock RETAINED_LOCK --output-dir NEW_REVIEW_DIR
```

Use a new output directory outside both roots. It receives JSON and Markdown. `INCOMPLETE` exits 2; complete reports exit 0. See the [contract](references/contract.md) and [provenance](references/provenance.md).

Replay the synthetic example:

```sh
python scripts/run.py assets/example/old-inventory.json assets/example/new-inventory.json --old-root assets/example/old-package --new-root assets/example/new-package --lock assets/example/retained-lock.json --output-dir review-output
```

The [specimen](assets/example/UPDATE_REVIEW.md) uses invented host, credential and helper changes.

## Interpret the review

- Hosts, credentials and licenses are declarations. URL hosts and credential markers are partial observations; values are omitted. Dynamic destinations remain `UNKNOWN`.
- Equal-byte moves are rename candidates. Changed helpers or referenced files require evidence and replay checks.
- Repair `INCOMPLETE` input. Retain the lock independently; nearby hashes cannot establish snapshot identity.

The tool does not fetch, execute package code, install, update or approve packages. `NO_RECORDED_CHANGE` means only checked bytes and declarations agree, not safety, rights or scientific validity.
