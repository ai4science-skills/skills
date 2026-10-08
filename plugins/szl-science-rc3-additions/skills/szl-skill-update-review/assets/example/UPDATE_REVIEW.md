# Skill package update review

Status: **CHANGES_REVIEW_REQUIRED**

Package: synthetic-review
Old revision: 1111111111111111111111111111111111111111
New revision: 2222222222222222222222222222222222222222
Retained lock SHA-256: 2ab9ed2008a31a97a4de306bf7f911d6ebb33d74c0d854217bdb6023d9a24833

## Skill changes

- added_skills: []
- added_skill_declarations: []
- removed_skills: []
- removed_skill_declarations: []
- equal_byte_rename_candidates: []
- modified_skills: [{"declarations": {"declared_credentials": {"added": ["LAB_TOKEN"], "removed": []}, "declared_external_hosts": {"added": ["api.example.org"], "removed": []}, "dynamic_destinations_change": {"new": true, "old": false}, "license_change": null, "referenced_files": {"added": [], "removed": []}}, "documentation_only": false, "files": {"added": [], "changed": ["scripts/helper.py"], "removed": []}, "helper_bytes_changed": true, "name": "demo", "path": "skills/demo"}]

## Package files

{"added": [], "changed": ["skills/demo/scripts/helper.py"], "removed": []}

License or notice artifacts changed: []

## Declared and literal evidence

Declared hosts, credentials, and licenses are metadata claims. URL hosts and credential marker names are partial static observations; values are omitted. Dynamic destinations are UNKNOWN.

{"new": {"dynamic_destinations": "UNKNOWN", "literal_credential_markers": [], "literal_url_hosts": [{"files": ["skills/demo/scripts/helper.py"], "host": "api.example.org"}]}, "old": {"dynamic_destinations": "UNKNOWN", "literal_credential_markers": [], "literal_url_hosts": []}}

## Evidence and tests to revisit

- demo (changed skill): review changed instructions and declarations; rerun skill contract and behavior tests; invalidate prior helper-bound receipts; rerun affected evidence and replay tests; review newly declared external access before any use
- package (package file set or bytes changed): rerun package registration, inventory, and integration checks

## Limits

- Declared capabilities and licenses are claims in local metadata, not verified permissions or rights.
- URL hosts and credential marker names are partial static observations; values are omitted.
- Dynamic destinations remain UNKNOWN; no package code was executed.
- Byte matches do not establish code safety, scientific validity, approval, or installability.
- The lock must be independently retained; its own SHA-256 is not a signature.
