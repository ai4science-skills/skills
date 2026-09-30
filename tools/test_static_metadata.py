"""Offline metadata checks; fixtures and canonical license text are data only."""

import hashlib
import json
from pathlib import Path
import unittest

from static_metadata import MAX_LICENSE_BYTES, detect_license, parse_frontmatter


class FrontmatterTests(unittest.TestCase):
    def parse(self, fields, newline="\n"):
        return parse_frontmatter(newline.join(["---", *fields, "---", "# Body", ""]))

    def test_exact_delimiter(self):
        _, _, problems = parse_frontmatter("---\nname: a\ndescription: d\n---bad\n")
        self.assertIn("unterminated-yaml-frontmatter", problems)

    def test_duplicate_key_is_error(self):
        metadata, _, problems = self.parse(["name: a", "name: b", "description: d"])
        self.assertEqual(metadata["name"], "a")
        self.assertTrue(any(problem.startswith("duplicate-yaml-key:name:") for problem in problems))

    def test_crlf(self):
        metadata, body, problems = self.parse(["name: a", "description: Do a when asked."], "\r\n")
        self.assertEqual(problems, [])
        self.assertEqual(metadata["name"], "a")
        self.assertEqual(body, "# Body\n")

    def test_empty_and_typed_values_remain_typed(self):
        for value, expected in [("", None), ("true", True), ("[x, y]", ["x", "y"]), ("42", 42)]:
            with self.subTest(value=value):
                metadata, _, problems = self.parse(["name: a", f"description: {value}"])
                self.assertEqual(problems, [])
                self.assertEqual(metadata["description"], expected)
                self.assertNotIsInstance(metadata["description"], str)

    def test_empty_quoted_description_remains_string(self):
        metadata, _, problems = self.parse(["description: ''"])
        self.assertEqual(problems, [])
        self.assertEqual(metadata["description"], "")

    def test_simple_list_and_quoted_commas(self):
        metadata, _, problems = self.parse(["allowed-tools:", "  - Bash", "  - Read", "description: 'Use it, when asked.'", 'other: ["a,b", true]'])
        self.assertEqual(problems, [])
        self.assertEqual(metadata["allowed-tools"], ["Bash", "Read"])
        self.assertEqual(metadata["other"], ["a,b", True])

    def test_single_quote_and_comment(self):
        metadata, _, problems = self.parse(["description: 'It''s useful # literally.' # outside", "name: a # comment"])
        self.assertEqual(problems, [])
        self.assertEqual(metadata["description"], "It's useful # literally.")
        self.assertEqual(metadata["name"], "a")

    def test_plain_apostrophe_does_not_hide_comment(self):
        metadata, _, problems = self.parse(["description: A user's tool # comment"])
        self.assertEqual(problems, [])
        self.assertEqual(metadata["description"], "A user's tool")

    def test_advanced_yaml_is_explicitly_unsupported(self):
        cases = [["description: >", "  folded text"], ["metadata:", "  author: someone"], ["description: &value text"], ["description: [x, [y]]"], ["description: 1e999"], ["description: - invalid"]]
        for fields in cases:
            with self.subTest(fields=fields):
                _, _, problems = self.parse(fields)
                self.assertTrue(any(problem.startswith("unsupported-yaml:") for problem in problems))


class LicenseTests(unittest.TestCase):
    MIT = b'''MIT License
Copyright (c) Synthetic fixture authors
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
'''
    # Minimal synthetic section-presence skeleton. This is deliberately not a
    # claim that a scanner can prove completeness or legal validity of terms.
    APACHE = b'''Apache License, Version 2.0
TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION
1. Definitions.
2. Grant of Copyright License.
3. Grant of Patent License.
4. Redistribution.
5. Submission of Contributions.
6. Trademarks.
7. Disclaimer of Warranty.
8. Limitation of Liability.
9. Accepting Warranty or Additional Liability.
END OF TERMS AND CONDITIONS
'''

    def source(self, files, **claims):
        return json.dumps({"repo": "example/source", "sha": "a" * 40, "path": "skills", "files_sha256": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}, **claims}).encode("utf-8")

    def test_declaration_without_evidence_is_missing(self):
        result = detect_license({}, "skills/a", "MIT")
        self.assertEqual(result["evidence_status"], "MISSING")
        self.assertEqual(result["file_sha256"], "")
        self.assertNotIn("permissive", result)

    def test_root_evidence_is_hashed(self):
        result = detect_license({"LICENSE": self.MIT}, "skills/a", "MIT")
        self.assertEqual(result["evidence_status"], "DETECTED")
        self.assertEqual(result["detected"], "MIT")
        self.assertEqual(result["file_sha256"], hashlib.sha256(self.MIT).hexdigest())

    def test_nearest_ancestor_is_used(self):
        result = detect_license({"LICENSE": self.MIT, "skills/LICENSE": self.APACHE}, "skills/a", "Apache-2.0")
        self.assertEqual(result["file"], "skills/LICENSE")
        self.assertEqual(result["evidence_status"], "DETECTED")

    def test_unknown_local_license_does_not_fall_back(self):
        result = detect_license({"LICENSE": self.MIT, "skills/a/LICENSE": b"All rights reserved. No redistribution."}, "skills/a", "MIT")
        self.assertEqual(result["evidence_status"], "UNKNOWN")
        self.assertEqual(result["file"], "skills/a/LICENSE")
        self.assertEqual(result["detected"], "")

    def test_mismatch_and_multiple_licenses_are_conflicts(self):
        for snapshot, declared in [({"LICENSE": self.MIT}, "GPL-3.0"), ({"LICENSE": self.MIT + b"\nGNU GENERAL PUBLIC LICENSE\nVersion 3"}, ""), ({"LICENSE": self.MIT, "LICENSE.txt": b"Apache License, Version 2.0"}, "")]:
            with self.subTest(snapshot=snapshot, declared=declared):
                self.assertEqual(detect_license(snapshot, "skills/a", declared)["evidence_status"], "CONFLICT")

    def test_nonstring_declaration_is_unknown(self):
        self.assertEqual(detect_license({"LICENSE": self.MIT}, "skills/a", True)["evidence_status"], "UNKNOWN")

    def test_unreadable_evidence_is_unknown(self):
        for data in [b"\x00binary", b"\xff", b"x" * (MAX_LICENSE_BYTES + 1)]:
            with self.subTest(length=len(data)):
                result = detect_license({"LICENSE": self.MIT, "skills/a/LICENSE": data}, "skills/a", "MIT")
                self.assertEqual(result["evidence_status"], "UNKNOWN")
                self.assertEqual(result["file"], "skills/a/LICENSE")

    def test_paths_must_be_relative_and_contained(self):
        for skill_path in ["../outside", "/outside", "skills\\a", "skills/./a", "skills//a", "skills/a/", "C:/outside", "skills/\x00a", "skills/\ud800", None, "a/" * 33 + "b"]:
            with self.subTest(skill_path=skill_path):
                self.assertEqual(detect_license({"LICENSE": self.MIT}, skill_path, "MIT")["evidence_status"], "UNKNOWN")

    def test_plugin_license_controls_and_all_ancestors_retained(self):
        snapshot = {"LICENSE": self.MIT, "plugins/LICENSE": self.MIT, "plugins/p/LICENSE": self.APACHE, "plugins/p/skills/a/SKILL.md": b"skill", "NOTICE": b"Root provenance", "plugins/NOTICE": b"Intermediate provenance", "plugins/p/NOTICE": b"Plugin provenance"}
        result = detect_license(snapshot, "plugins/p/skills/a", "Apache-2.0")
        self.assertEqual(result["evidence_status"], "DETECTED")
        self.assertEqual(result["disposition"], "EVIDENCE_IDENTIFIED")
        self.assertEqual(result["human_approval"], "NOT_GRANTED")
        self.assertEqual(result["permission"], "NOT_ASSESSED")
        self.assertEqual(result["file"], "plugins/p/LICENSE")
        self.assertEqual(result["file_sha256"], hashlib.sha256(self.APACHE).hexdigest())
        self.assertEqual(result["applicable_scope"], "plugins/p")
        self.assertEqual(result["applicable_evidence_paths"], ["plugins/p/LICENSE"])
        self.assertEqual(result["ancestor_scopes"], ["plugins/p/skills/a", "plugins/p/skills", "plugins/p", "plugins", "."])
        evidence = {entry["file"]: entry for entry in result["evidence"]}
        self.assertEqual(set(evidence), set(snapshot) - {"plugins/p/skills/a/SKILL.md"})
        for key, entry in evidence.items():
            self.assertEqual(entry["file_sha256"], hashlib.sha256(snapshot[key]).hexdigest())
        self.assertEqual(evidence["LICENSE"]["relation"], "ancestor_license")
        self.assertEqual(evidence["LICENSE"]["scope"], ".")
        self.assertNotIn("permissive", result)

    def test_nested_custom_scope_is_review_without_replacing_main_license(self):
        custom = b"Custom license. Research use only."
        result = detect_license({"LICENSE": self.MIT, "skills/a/references/LICENSE": custom}, "skills/a", "MIT")
        self.assertEqual(result["file"], "LICENSE")
        self.assertEqual(result["detected"], "MIT")
        self.assertEqual(result["disposition"], "LICENSE_REVIEW")
        nested = next(entry for entry in result["evidence"] if entry["file"] == "skills/a/references/LICENSE")
        self.assertEqual(nested["relation"], "nested_license_override")
        self.assertEqual(nested["scope"], "skills/a/references")
        self.assertEqual(nested["file_sha256"], hashlib.sha256(custom).hexdigest())

    def test_nested_standard_different_scope_is_review(self):
        result = detect_license({"LICENSE": self.MIT, "skills/a/scripts/LICENSE": self.APACHE}, "skills/a", "MIT")
        self.assertIn("nested-license-scope-override:skills/a/scripts/LICENSE", result["reasons"])
        self.assertEqual(result["disposition"], "LICENSE_REVIEW")

    def test_same_scope_conflict_on_ancestor_is_retained(self):
        result = detect_license({"LICENSE": self.MIT, "LICENSE.txt": self.APACHE, "skills/a/LICENSE": self.MIT}, "skills/a", "MIT")
        self.assertEqual(result["file"], "skills/a/LICENSE")
        self.assertEqual(result["evidence_status"], "CONFLICT")
        self.assertIn("same-scope-license-conflict:.", result["reasons"])

    def test_custom_additions_to_standard_license_are_review(self):
        result = detect_license({"LICENSE": self.MIT + b"\nAdditional restrictions: research use only."}, "skills/a", "MIT")
        self.assertEqual(result["detected"], "MIT")
        self.assertEqual(result["disposition"], "LICENSE_REVIEW")

    def test_source_hash_bindings_are_relative_to_source_parent(self):
        files = {"LICENSE": self.APACHE, "skills/a/SKILL.md": b"static fixture"}
        snapshot = {"LICENSE": self.MIT, **{"plugins/p/" + key: data for key, data in files.items()}, "plugins/p/SOURCE.json": self.source(files)}
        result = detect_license(snapshot, "plugins/p/skills/a", "Apache-2.0")
        self.assertEqual(result["disposition"], "EVIDENCE_IDENTIFIED")
        source = next(entry for entry in result["evidence"] if entry["kind"] == "source")
        self.assertEqual(source["binding_status"], "VERIFIED")
        self.assertEqual(source["claims_status"], "UNSIGNED_HONEST")
        self.assertEqual(source["file_sha256"], hashlib.sha256(snapshot["plugins/p/SOURCE.json"]).hexdigest())
        self.assertEqual({binding["file"] for binding in source["bindings"]}, {"plugins/p/LICENSE", "plugins/p/skills/a/SKILL.md"})
        self.assertTrue(all(binding["status"] == "MATCH" for binding in source["bindings"]))

    def test_source_mismatch_missing_and_unreadable_bindings_fail_closed(self):
        files = {"LICENSE": self.MIT, "skills/a/SKILL.md": b"expected"}
        for observed in [b"changed", None, "not bytes"]:
            with self.subTest(observed=observed):
                snapshot = {"LICENSE": self.MIT, "SOURCE.json": self.source(files)}
                if observed is not None:
                    snapshot["skills/a/SKILL.md"] = observed
                result = detect_license(snapshot, "skills/a", "MIT")
                self.assertEqual(result["disposition"], "LICENSE_REVIEW")
                source = next(entry for entry in result["evidence"] if entry["kind"] == "source")
                self.assertEqual(source["binding_status"], "ERROR")
                self.assertEqual(source["bindings"][1]["status"], "MISMATCH" if observed == b"changed" else "MISSING_OR_UNREADABLE")

    def test_bad_source_json_and_hash_fields_fail_closed(self):
        samples = [b"{}", b"[]", b"{not json}", b'{"files_sha256":{},"files_sha256":{}}', b'{"files_sha256": {"LICENSE": NaN}}', b'{"files_sha256": []}', b'{"files_sha256": {"LICENSE": "bad"}}', b'{"files_sha256": {"../LICENSE": "' + b"a" * 64 + b'"}}', b'{"files_sha256": {"/LICENSE": "' + b"a" * 64 + b'"}}', b'{"files_sha256": {"x\\\\LICENSE": "' + b"a" * 64 + b'"}}', self.source({"LICENSE": self.MIT}, sha="not a pin"), self.source({"LICENSE": self.MIT}, path="../outside")]
        for data in samples:
            with self.subTest(data=data):
                self.assertEqual(detect_license({"LICENSE": self.MIT, "SOURCE.json": data}, "skills/a", "MIT")["disposition"], "LICENSE_REVIEW")

    def test_source_and_notice_read_encoding_and_bounds_fail_closed(self):
        for name in ["SOURCE.json", "NOTICE", "skills/a/references/NOTICE"]:
            for data in [None, b"\xff", b"\x00", b"x" * (MAX_LICENSE_BYTES + 1)]:
                with self.subTest(name=name, data_type=type(data).__name__):
                    result = detect_license({"LICENSE": self.MIT, name: data}, "skills/a", "MIT")
                    self.assertEqual(result["disposition"], "LICENSE_REVIEW")
                    entry = next(entry for entry in result["evidence"] if entry["file"] == name)
                    self.assertTrue(entry["problem"])

    def test_notice_derived_portions_only_hold_resolved_skill_scope(self):
        notice = b"skills/typesafe-ai is an overlay on the official TypeSafe agent skill, which is MIT licensed. Copyright and permission notices apply to portions derived from it."
        snapshot = {"LICENSE": self.MIT, "plugins/p/LICENSE": self.APACHE, "plugins/p/NOTICE": notice, "plugins/p/skills/szl-typesafe-ai/SKILL.md": b"typesafe", "plugins/p/skills/other/SKILL.md": b"other"}
        derived = detect_license(snapshot, "plugins/p/skills/szl-typesafe-ai", "Apache-2.0")
        self.assertEqual(derived["disposition"], "LICENSE_REVIEW")
        self.assertEqual(derived["detected"], "Apache-2.0")
        self.assertIn("notice-derived-portions-scope-review:plugins/p/NOTICE", derived["reasons"])
        entry = next(entry for entry in derived["evidence"] if entry["kind"] == "notice")
        self.assertEqual(entry["derived_scope_paths"], ["plugins/p/skills/szl-typesafe-ai"])
        self.assertFalse(entry["derived_scope_unresolved"])
        self.assertEqual(entry["file_sha256"], hashlib.sha256(notice).hexdigest())
        other = detect_license(snapshot, "plugins/p/skills/other", "Apache-2.0")
        self.assertEqual(other["disposition"], "EVIDENCE_IDENTIFIED")

    def test_unresolved_derived_notice_scope_is_review(self):
        for notice in [b"MIT permission applies to portions derived from it.", b"skills/missing is an overlay on another skill."]:
            result = detect_license({"LICENSE": self.MIT, "NOTICE": notice}, "skills/a", "MIT")
            self.assertEqual(result["disposition"], "LICENSE_REVIEW")

    def test_frontmatter_scope_and_cc_terms_cannot_be_cleared_by_root_mit(self):
        for declaration in ["CC-BY-4.0", "CC-BY-NC-4.0", "Noncommercial research use only", "Proprietary API terms", "Unknown", "MIT except dataset terms", "See LICENSE"]:
            with self.subTest(declaration=declaration):
                result = detect_license({"LICENSE": self.MIT}, "skills/a", declaration)
                self.assertEqual(result["disposition"], "LICENSE_REVIEW")
                self.assertEqual(result["effective"], declaration)

    def test_explicit_spdx_and_or_with_are_syntax_observations(self):
        for expression in ["MIT OR Apache-2.0", "MIT AND Apache-2.0", "( MIT OR Apache-2.0 ) AND BSD-3-Clause", "GPL-2.0-only WITH Classpath-exception-2.0"]:
            with self.subTest(expression=expression):
                data = ("SPDX-License-Identifier: " + expression + "\n").encode("utf-8")
                result = detect_license({"LICENSE": data}, "skills/a", expression)
                self.assertEqual(result["evidence_status"], "UNKNOWN")
                self.assertEqual(result["disposition"], "LICENSE_REVIEW")
                self.assertEqual(result["human_approval"], "NOT_GRANTED")
                self.assertFalse(result["declaration_expression"]["problem"])
                self.assertEqual(result["file_sha256"], hashlib.sha256(data).hexdigest())

    def test_custom_unsupported_and_invalid_spdx_are_review(self):
        expressions = ["LicenseRef-custom", "MIT OR LicenseRef-custom", "DocumentRef-foreign:LicenseRef-x", "MIT WITH Custom-exception", "MIT AND", "MIT Apache-2.0", "(MIT OR Apache-2.0", "(MIT) WITH LLVM-exception", "MIT and Apache-2.0", "( " * 33 + "MIT" + " )" * 33]
        for expression in expressions:
            with self.subTest(expression=expression):
                result = detect_license({"LICENSE": ("SPDX-License-Identifier: " + expression).encode("utf-8")}, "skills/a", expression)
                self.assertEqual(result["disposition"], "LICENSE_REVIEW")

    def test_explicit_spdx_does_not_hide_extra_unexpressed_license(self):
        data = b"SPDX-License-Identifier: MIT\nApache License, Version 2.0\n"
        self.assertEqual(detect_license({"LICENSE": data}, "skills/a", "MIT")["evidence_status"], "CONFLICT")

    def test_spdx_expression_conflict_is_not_reduced_to_id_union(self):
        snapshot = {"LICENSE": b"SPDX-License-Identifier: MIT OR Apache-2.0", "LICENSE.txt": b"SPDX-License-Identifier: MIT AND Apache-2.0"}
        self.assertEqual(detect_license(snapshot, "skills/a", "")["evidence_status"], "CONFLICT")

    def test_invalid_snapshot_keys_cannot_be_collapsed_into_license_evidence(self):
        for key in ["../LICENSE", "x/../LICENSE", "/LICENSE", "./LICENSE", "x//LICENSE", "x\\LICENSE", "x:LICENSE", "x/\ud800", 42]:
            with self.subTest(key=key):
                result = detect_license({"LICENSE": self.MIT, key: self.MIT}, "skills/a", "MIT")
                self.assertEqual(result["disposition"], "LICENSE_REVIEW")
                self.assertIn("invalid-snapshot-key", result["reasons"])

    def test_snapshot_size_and_nonbytes_fail_closed(self):
        result = detect_license({"LICENSE": self.MIT, "skills/a/data": None}, "skills/a", "MIT")
        self.assertEqual(result["disposition"], "LICENSE_REVIEW")
        self.assertIn("snapshot-content-not-bytes:skills/a/data", result["reasons"])
        oversized = {"file" + str(index): b"" for index in range(10_001)}
        self.assertEqual(detect_license(oversized, "skills/a", "MIT")["disposition"], "LICENSE_REVIEW")

    def test_unsafe_source_claims_are_not_copied_to_receipt(self):
        for field, value in [("repo", "https://user:secret@example.org/repo?token=private"), ("ref", "tag?token=secret"), ("repo", "example/\ud800"), ("repo", "example/name\nsecret")]:
            with self.subTest(field=field):
                source = self.source({"LICENSE": self.MIT}, **{field: value})
                result = detect_license({"LICENSE": self.MIT, "SOURCE.json": source}, "skills/a", "MIT")
                self.assertEqual(result["disposition"], "LICENSE_REVIEW")
                evidence = next(entry for entry in result["evidence"] if entry["kind"] == "source")
                self.assertNotIn(field, evidence.get("claims", {}))
                self.assertNotIn("secret", json.dumps(evidence))

    def test_source_json_unicode_depth_nonfinite_and_duplicate_nested_keys(self):
        source_files = '"files_sha256":{"LICENSE":"' + hashlib.sha256(self.MIT).hexdigest() + '"}'
        samples = ['{' + source_files + ',"extra":"\\ud800"}', '{' + source_files + ',"extra":1e999}', '{' + source_files + ',"extra":{"x":1,"x":2}}', '{' + source_files + ',"extra":' + '[' * 33 + '0' + ']' * 33 + '}']
        for sample in samples:
            with self.subTest(sample=sample[:60]):
                result = detect_license({"LICENSE": self.MIT, "SOURCE.json": sample.encode("utf-8")}, "skills/a", "MIT")
                self.assertEqual(result["disposition"], "LICENSE_REVIEW")
                source = next(entry for entry in result["evidence"] if entry["kind"] == "source")
                self.assertEqual(source["binding_status"], "ERROR")

    def test_nested_spdx_operator_override_is_not_reduced_to_id_union(self):
        snapshot = {"LICENSE": b"SPDX-License-Identifier: MIT OR Apache-2.0", "skills/a/references/LICENSE": b"SPDX-License-Identifier: MIT AND Apache-2.0"}
        result = detect_license(snapshot, "skills/a", "MIT OR Apache-2.0")
        self.assertEqual(result["disposition"], "LICENSE_REVIEW")
        self.assertIn("nested-license-scope-override:skills/a/references/LICENSE", result["reasons"])

    def test_explicit_gpl_variant_is_not_conflicted_by_generic_title(self):
        result = detect_license({"LICENSE": b"GNU GENERAL PUBLIC LICENSE\nVersion 3\nSPDX-License-Identifier: GPL-3.0-only"}, "skills/a", "GPL-3.0-only")
        self.assertEqual(result["evidence_status"], "UNKNOWN")
        self.assertEqual(result["detected"], "GPL-3.0-only")

    def test_nested_and_all_ancestor_provenance_are_bound(self):
        files = {"skills/a/SKILL.md": b"fixture"}
        snapshot = {"LICENSE": self.MIT, "SOURCE.json": self.source(files), **files, "skills/a/references/data": b"ref", "skills/a/references/SOURCE.json": self.source({"data": b"ref"}), "skills/NOTICE": b"Intermediate provenance"}
        result = detect_license(snapshot, "skills/a", "MIT")
        self.assertEqual(result["disposition"], "EVIDENCE_IDENTIFIED")
        sources = [entry for entry in result["evidence"] if entry["kind"] == "source"]
        self.assertEqual(len(sources), 2)
        self.assertTrue(all(entry["binding_status"] == "VERIFIED" for entry in sources))
        self.assertEqual({entry["relation"] for entry in sources}, {"ancestor_provenance", "nested_provenance"})

    def test_title_and_spdx_line_do_not_establish_complete_terms(self):
        for data, label in [(b"MIT License", "MIT"), (b"Apache License, Version 2.0", "Apache-2.0"), (b"SPDX-License-Identifier: MIT", "MIT")]:
            with self.subTest(label=label):
                result = detect_license({"LICENSE": data}, "skills/a", label)
                self.assertEqual(result["detected"], label)
                self.assertEqual(result["disposition"], "LICENSE_REVIEW")
                self.assertIn("incomplete-or-unverified-license-terms:LICENSE", result["reasons"])

    def test_source_scope_or_license_claim_is_hashed_and_reviewed(self):
        for fields in [{"license": "LicenseRef-Custom"}, {"scope": "proprietary content"}, {"metadata": {"rights": "custom secret permission"}}, {"metadata": [[{"license": "secret terms"}]]}]:
            result = detect_license({"LICENSE": self.MIT, "SOURCE.json": self.source({"LICENSE": self.MIT}, **fields)}, "skills/a", "MIT")
            self.assertEqual(result["disposition"], "LICENSE_REVIEW")
            source = next(entry for entry in result["evidence"] if entry["kind"] == "source")
            self.assertTrue(source["scope_claims"])
            self.assertTrue(all(len(claim["value_sha256"]) == 64 for claim in source["scope_claims"]))
            self.assertNotIn("secret", json.dumps(source))
            self.assertIn("source-license-or-scope-claim-review:SOURCE.json", result["reasons"])

    def test_missing_source_origin_claims_require_review_even_when_hashes_match(self):
        for field in ["repo", "sha", "path"]:
            manifest = json.loads(self.source({"LICENSE": self.MIT}))
            del manifest[field]
            result = detect_license({"LICENSE": self.MIT, "SOURCE.json": json.dumps(manifest).encode("utf-8")}, "skills/a", "MIT")
            self.assertEqual(result["disposition"], "LICENSE_REVIEW")
            self.assertIn("missing-source-provenance-claim:" + field + ":SOURCE.json", result["reasons"])

    def test_root_skill_uses_root_evidence_and_nested_scope_overrides(self):
        result = detect_license({"LICENSE": self.MIT, "SKILL.md": b"fixture"}, ".", "MIT")
        self.assertEqual(result["disposition"], "EVIDENCE_IDENTIFIED")
        self.assertEqual(result["file"], "LICENSE")
        self.assertEqual(result["ancestor_scopes"], ["."])
        nested = detect_license({"LICENSE": self.MIT, "SKILL.md": b"fixture", "refs/LICENSE": b"Research use only"}, ".", "MIT")
        self.assertEqual(nested["disposition"], "LICENSE_REVIEW")

    def test_applicable_license_scope_limitation_requires_review(self):
        result = detect_license({"LICENSE": self.MIT + b"\nThis license covers only tools/. Each skill keeps its own license."}, "skills/a", "MIT")
        self.assertEqual(result["disposition"], "LICENSE_REVIEW")
        self.assertIn("applicable-license-scope-clause-review:LICENSE", result["reasons"])

    def test_file_spdx_custom_and_different_licenses_are_scoped_review(self):
        for header in [b"# SPDX-License-Identifier: LicenseRef-Custom\n", b"/* SPDX-License-Identifier: Apache-2.0 */\n", b"<!-- SPDX-License-Identifier: MIT OR Apache-2.0 -->\n"]:
            with self.subTest(header=header):
                result = detect_license({"LICENSE": self.MIT, "skills/a/scripts/x.py": header}, "skills/a", "MIT")
                self.assertEqual(result["evidence_status"], "DETECTED")
                self.assertEqual(result["detected"], "MIT")
                self.assertEqual(result["disposition"], "LICENSE_REVIEW")
                file = next(entry for entry in result["evidence"] if entry["kind"] == "file_spdx")
                self.assertEqual(file["scope"], "skills/a/scripts/x.py")
                self.assertEqual(file["file_sha256"], hashlib.sha256(header).hexdigest())
                self.assertEqual(file["relation"], "file_license_scope")

    def test_matching_file_spdx_is_an_observation_and_does_not_grant_approval(self):
        result = detect_license({"LICENSE": self.MIT, "skills/a/scripts/x.py": b"/* SPDX-License-Identifier: MIT */\n"}, "skills/a", "MIT")
        self.assertEqual(result["disposition"], "EVIDENCE_IDENTIFIED")
        self.assertEqual(result["human_approval"], "NOT_GRANTED")
        self.assertTrue(result["license_header_coverage"]["complete"])

    def test_uninspected_file_license_scope_is_not_complete(self):
        result = detect_license({"LICENSE": self.MIT, "skills/a/data.bin": b"\xff"}, "skills/a", "MIT")
        self.assertEqual(result["disposition"], "LICENSE_REVIEW")
        self.assertFalse(result["license_header_coverage"]["complete"])
        self.assertEqual(result["license_header_coverage"]["uninspected_paths"], ["skills/a/data.bin"])

    def test_header_count_limit_cannot_claim_complete_scope_scan(self):
        result = detect_license({"LICENSE": self.MIT, "skills/a/script.py": b"# SPDX-License-Identifier: MIT\n" * 129}, "skills/a", "MIT")
        self.assertEqual(result["disposition"], "LICENSE_REVIEW")
        self.assertFalse(result["license_header_coverage"]["complete"])
        self.assertTrue(result["license_header_coverage"]["spdx_header_limit_hit"])

    def test_invalid_spdx_free_text_is_hashed_without_copying_text(self):
        data = b"# SPDX-License-Identifier: https://user:secret@host.invalid/license\n"
        result = detect_license({"LICENSE": self.MIT, "skills/a/script.py": data}, "skills/a", "MIT")
        self.assertEqual(result["disposition"], "LICENSE_REVIEW")
        evidence = next(entry for entry in result["evidence"] if entry["kind"] == "file_spdx")
        self.assertNotIn("secret", json.dumps(evidence))
        self.assertEqual(len(evidence["spdx_expressions"][0]["expression_sha256"]), 64)

    def test_provenance_hold_does_not_erase_identified_main_license(self):
        result = detect_license({"LICENSE": self.APACHE, "NOTICE": b"Unresolved third-party portions derived from another source."}, "skills/a", "Apache-2.0")
        self.assertEqual(result["detected"], "Apache-2.0")
        self.assertEqual(result["evidence_status"], "DETECTED")
        self.assertEqual(result["disposition"], "LICENSE_REVIEW")

    def test_canonical_apache_patent_contribution_and_notice_clauses_are_not_content_scope(self):
        canonical_clauses = b'''where such license applies only to those patent claims licensable
by such Contributor that are necessarily infringed by their Contribution(s).
excluding communication that is conspicuously marked or otherwise designated
in writing by the copyright owner as "Not a Contribution."
excluding those notices that do not pertain to any part of the Derivative Works.
'''
        result = detect_license({"LICENSE": self.APACHE + canonical_clauses}, "skills/a", "Apache-2.0")
        self.assertEqual(result["disposition"], "EVIDENCE_IDENTIFIED")
        self.assertEqual(result["evidence_status"], "DETECTED")
        self.assertFalse(result["evidence"][0]["scope_clauses_observed"])
        self.assertNotIn("applicable-license-scope-clause-review:LICENSE", result["reasons"])

    def test_exact_baseline_apache_license_has_no_false_content_scope_hold(self):
        # The reviewed canonical LICENSE is read as inert fixture bytes only.
        fixture = Path(__file__).resolve().parents[1] / "plugins" / "szl-evidence-skills" / "LICENSE"
        canonical = fixture.read_bytes()
        digest = hashlib.sha256(canonical).hexdigest()
        self.assertEqual(digest, "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4")
        snapshot = {"LICENSE": self.MIT, "plugins/p/LICENSE": canonical, "plugins/p/skills/a/SKILL.md": b"fixture"}
        result = detect_license(snapshot, "plugins/p/skills/a", "Apache-2.0")
        self.assertEqual(result["file"], "plugins/p/LICENSE")
        self.assertEqual(result["file_sha256"], digest)
        self.assertEqual(result["disposition"], "EVIDENCE_IDENTIFIED")
        self.assertEqual(result["evidence_status"], "DETECTED")

    def test_real_content_scope_exclusions_remain_review_held(self):
        clauses = [b"This license applies only to tools/.", b"Excluding skills/ and plugins/.", b"Except for references/ with separate rights.", b"Portions of this skill have a separate license."]
        for clause in clauses:
            with self.subTest(clause=clause):
                result = detect_license({"LICENSE": self.APACHE + b"\n" + clause}, "skills/a", "Apache-2.0")
                self.assertEqual(result["disposition"], "LICENSE_REVIEW")
                self.assertEqual(result["detected"], "Apache-2.0")
                self.assertIn("applicable-license-scope-clause-review:LICENSE", result["reasons"])


if __name__ == "__main__":
    unittest.main()
