# Contract: szl.skill-update-review.v1

Supply two **immutable local package roots**, an inventory for each, and a separately retained lock. Keep inventories and lock outside the roots. Revision pins are caller-supplied full lowercase 40- or 64-hex values; the helper cannot verify their origin offline.

## Inventory

UTF-8 inventory shape:

```json
{
  "schema": "szl.skill-package-inventory.v1",
  "package": "study-skills",
  "revision": "1111111111111111111111111111111111111111",
  "complete": true,
  "files": [
    {"path": "skills/demo/SKILL.md", "sha256": "<64 lowercase hex digits>", "size": 72}
  ],
  "skills": [
    {
      "path": "skills/demo",
      "name": "demo",
      "referenced_files": [],
      "declared_external_hosts": [],
      "declared_credentials": [],
      "declared_license": "Apache-2.0",
      "declared_dynamic_destinations": false
    }
  ]
}
```

Calculate SHA-256 over exact bytes of **every** package file. Sort file entries by canonical relative POSIX path and skills by path. Name and license must agree with `SKILL.md` frontmatter. The accepted frontmatter subset has one plain scalar key and value per line; nested forms and quoted keys are `INCOMPLETE`. List every skill-relative referenced file, including paths used outside the entrypoint. Declare visible local Markdown links and code-quoted paths under `assets/`, `docs/`, `references/` or `scripts/`. Supported links are single-line inline, full/collapsed reference, and defined shortcut forms. Destinations can use angle brackets and a separated single-quoted, double-quoted or parenthesized title. Local percent escapes are decoded once; malformed, double-encoded, unresolved or ambiguous references are `INCOMPLETE`. Host, credential and license declarations are caller claims.

Unsafe or noncanonical paths, links/reparse points, collisions, duplicate JSON keys, missing/extra files, hash or frontmatter mismatches, and unlisted visible references yield `INCOMPLETE`. Limits: 2 MiB inventory, 64 KiB lock, 4,096 files, 256 skills, 8 MiB/file, 32 MiB total. Completeness here does not establish real-world capability coverage.

## Separately retained lock

UTF-8 lock shape:

```json
{
  "schema": "szl.skill-update-lock.v1",
  "snapshots": {
    "old": {"package": "study-skills", "revision": "1111111111111111111111111111111111111111", "inventory_sha256": "<SHA-256 of exact old inventory bytes>"},
    "new": {"package": "study-skills", "revision": "2222222222222222222222222222222222222222", "inventory_sha256": "<SHA-256 of exact new inventory bytes>"}
  }
}
```

Retain the lock independently. If both inventory and lock can be replaced, matching hashes do not establish authenticity. The reported lock hash is not a signature.

## Output and reruns

`UPDATE_REVIEW.json` (`szl.skill-update-review.v1`) reports revisions, hashes, changes, reruns and observations. Changed LICENSE/NOTICE/COPYING artifacts include extensions. `helper_bytes_changed` includes referenced non-document files with unknown suffixes; revisit file-bound evidence. Invalid input returns `INCOMPLETE`. Markdown renders the review.

`NO_RECORDED_CHANGE` means bytes and declarations agree, even if revision labels differ. This only compares locked inputs. The helper does not execute package code, verify rights, approve installation or establish scientific validity. URL hosts and credential marker names are partial static observations with file paths; values are omitted. Dynamic destinations remain `UNKNOWN`.
