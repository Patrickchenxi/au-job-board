"""Offline location boundary tests: hand-written synthetic inputs, public seed.

Run: PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/test_locations.py
No job records, personal inputs, databases, HTTP servers or downloads are used.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import socket
import sqlite3
import sys
import unittest
from unittest.mock import patch
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from jobs.locations import classify, parse_locations, parse_target  # noqa: E402
from jobs import locations as location_module  # noqa: E402


def one(text, work_type=None):
    values = parse_locations(text, work_type)
    if len(values) != 1:
        raise AssertionError(f"Expected one location: {values!r}")
    return values[0]


class LocationTests(unittest.TestCase):
    def test_01_remote_does_not_leak_to_another_location(self):
        values = parse_locations("Remote NSW / Melbourne VIC Onsite")
        target = parse_target("VIC")
        self.assertEqual([classify(v, target, "remote") for v in values], ["hidden", "hidden"])
        self.assertEqual([v["work_mode"] for v in values], ["remote", "onsite"])

    def test_02_remote_at_second_location_is_not_hidden(self):
        values = parse_locations("Sydney NSW Hybrid / Melbourne VIC Remote")
        target = parse_target("VIC")
        self.assertEqual([classify(v, target, "remote") for v in values], ["hidden", "match"])
        # Parent selection must use these same per-location classifications.
        self.assertEqual([v["city"] for v in values if classify(v, target, "remote") == "match"], ["Melbourne"])
        self.assertEqual([classify(v, parse_target("NSW"), "hybrid") for v in values], ["match", "hidden"])

    def test_unknown_mode_is_related_not_borrowed_remote(self):
        values = parse_locations("Remote NSW / Melbourne VIC")
        self.assertEqual([classify(v, parse_target("VIC"), "remote") for v in values], ["hidden", "related"])
        self.assertEqual(values[1]["work_mode"], "unknown")

    def test_generic_work_type_is_only_a_fallback(self):
        for work_type, mode in [("Full-time", "unknown"), ("Part-time", "unknown"),
                                ("Full-time, Remote", "remote"), ("Hybrid", "hybrid")]:
            with self.subTest(work_type=work_type):
                values = parse_locations("Sydney NSW / Melbourne VIC Onsite", work_type)
                self.assertEqual([v["work_mode"] for v in values], [mode, "onsite"])
        self.assertEqual(one("Melbourne Remote", "Hybrid")["work_mode"], "remote")

    def test_location_restricted_work_type_is_not_generic(self):
        for work_type in ["Remote NSW", "Hybrid Sydney", "Remote except VIC", "Remote within NSW"]:
            with self.subTest(work_type=work_type):
                loc = one("Melbourne VIC", work_type)
                self.assertEqual(loc["work_mode"], "unknown")
                self.assertEqual(classify(loc, parse_target("VIC"), "remote"), "related")
        self.assertEqual(one("Melbourne", "Fully Remote, Full-time")["work_mode"], "remote")

    def test_explicit_conflicting_or_negated_modes_stay_unknown(self):
        for text in ["Melbourne (Remote / Hybrid)", "Melbourne not remote", "Melbourne no remote"]:
            with self.subTest(text=text):
                loc = one(text, "Remote")
                self.assertEqual(loc["work_mode"], "unknown")
                self.assertIn("work_mode_uncertain", loc["reason"])
        self.assertEqual(one("Melbourne", "Remote / Hybrid")["work_mode"], "unknown")

    def test_mode_spelling_and_no_assumed_onsite(self):
        for phrase, mode in [("On-site", "onsite"), ("on site", "onsite"), ("ONSITE", "onsite"),
                             ("WFH", "remote"), ("Work from home", "remote"), ("Hybrid", "hybrid")]:
            with self.subTest(phrase=phrase):
                self.assertEqual(one("Melbourne " + phrase)["work_mode"], mode)
        self.assertEqual(one("Melbourne")["work_mode"], "unknown")

    def test_remote_state_restriction(self):
        loc = one("Remote NSW")
        self.assertEqual(classify(loc, parse_target("VIC"), "remote"), "hidden")
        self.assertEqual(classify(loc, parse_target("NSW"), "remote"), "match")
        self.assertEqual(classify(loc, parse_target("2000"), "remote"), "related")
        self.assertEqual(classify(one("Remote"), parse_target("VIC"), "remote"), "unknown")

    def test_country_and_no_geography(self):
        loc = one("Remote (Australia only)")
        self.assertEqual(loc["precision"], "country")
        self.assertNotIn("state", loc)
        self.assertEqual(classify(loc, parse_target("VIC"), "remote"), "related")
        self.assertEqual(one("Australia-wide")["precision"], "country")
        for text in [None, "", " ", "Auckland NZ", "Atlantis"]:
            with self.subTest(text=text):
                self.assertEqual(one(text)["precision"], "unknown")

    def test_leading_zero_and_unsupported_postcodes(self):
        loc = one("0800")
        self.assertEqual((loc["postcode"], loc["state"]), ("0800", "NT"))
        self.assertEqual(parse_target("0800")["postcode"], "0800")
        for text in ["800", "9999", "0000", "12345"]:
            with self.subTest(text=text):
                self.assertEqual(one(text)["precision"], "unknown")
                with self.assertRaisesRegex(ValueError, "unsupported|valid"):
                    parse_target(text)

    def test_real_seed_cross_border_relations_not_prefixes(self):
        for pc, states in [("2620", ["ACT", "NSW"]), ("0872", ["NT", "SA", "WA"]),
                           ("3691", ["NSW", "VIC"])]:
            with self.subTest(postcode=pc):
                loc = one(pc)
                self.assertEqual(loc["state"], states)
                self.assertEqual(classify(loc, parse_target(pc)), "match")
                self.assertEqual(classify(loc, parse_target(states[0])), "related")
        self.assertEqual(one("2620 ACT")["state"], "ACT")
        self.assertEqual(one("2620 NSW")["state"], "NSW")
        self.assertEqual(classify(one("2620 ACT"), parse_target("2620 NSW")), "hidden")
        self.assertEqual(classify(one("2620"), parse_target("2620 ACT")), "related")
        self.assertEqual(classify(one("0872"), parse_target("VIC")), "hidden")

    def test_ambiguous_locality_and_disambiguation(self):
        ambiguous = one("Richmond")
        self.assertEqual(ambiguous["precision"], "unknown")
        self.assertEqual(ambiguous["reason"], "ambiguous_locality")
        self.assertEqual(classify(ambiguous, parse_target("VIC")), "unknown")
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            parse_target("Richmond")
        for text in ["Richmond VIC", "Richmond, Victoria", "Richmond VIC 3121"]:
            with self.subTest(text=text):
                target = parse_target(text)
                self.assertEqual((target["postcode"], target["state"]), ("3121", "VIC"))
        # Even a state may leave several GeoNames locality/postcode candidates.
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            parse_target("Springfield VIC")

    def test_known_city_is_coarser_than_postcode(self):
        loc = one("Melbourne VIC")
        self.assertEqual(loc["precision"], "city")
        self.assertNotIn("postcode", loc)
        self.assertEqual(classify(loc, parse_target("3000")), "related")
        self.assertEqual(classify(loc, parse_target("Melbourne")), "match")
        self.assertEqual(classify(loc, parse_target("Sydney")), "hidden")
        self.assertEqual(one("Darwin")["state"], "NT")
        self.assertNotIn("postcode", one("Darwin"))

    def test_locality_and_metro_membership_is_unknown(self):
        loc = one("Richmond VIC")
        self.assertEqual(loc["precision"], "locality")
        self.assertEqual(classify(loc, parse_target("Melbourne")), "related")
        self.assertEqual(classify(one("3008"), parse_target("Melbourne")), "related")
        self.assertEqual(classify(one("Melbourne"), parse_target("Richmond VIC")), "related")
        # An asserted city/suburb relationship absent from the seed is not invented.
        self.assertEqual(one("Melbourne VIC 3008")["precision"], "unknown")

    def test_locality_filter_retains_postcode_breadth(self):
        target = parse_target("Richmond VIC")
        self.assertEqual(classify(one("Richmond VIC"), target), "match")
        self.assertEqual(classify(one("3121"), target), "related")
        self.assertEqual(classify(one("3000"), target), "hidden")
        self.assertEqual(classify(one("VIC"), target), "related")

    def test_conflicts_are_unknown_and_target_errors_are_explicit(self):
        for text in ["Melbourne NSW", "0800 VIC", "Richmond VIC 2000", "Melbourne VIC NSW",
                     "Richmond NT", "3000 2000"]:
            with self.subTest(text=text):
                loc = one(text)
                self.assertEqual(loc["precision"], "unknown")
                self.assertEqual(classify(loc, parse_target("VIC")), "unknown")
                with self.assertRaises(ValueError):
                    parse_target(text)

    def test_unresolved_place_preserves_only_explicit_state_evidence(self):
        loc = one("Atlantis VIC")
        self.assertEqual(loc["precision"], "state")
        self.assertEqual(loc["reason"], "unresolved_place_state_only")
        self.assertNotIn("locality", loc)
        self.assertEqual(classify(loc, parse_target("3000")), "related")
        with self.assertRaises(ValueError):
            parse_target("Atlantis VIC")

    def test_state_full_names_do_not_collide_with_place_names(self):
        for text, state in [("Victoria", "VIC"), ("Western Australia", "WA"),
                            ("South Australia", "SA"), ("Northern Territory", "NT"),
                            ("Australian Capital Territory", "ACT"), ("New South Wales", "NSW")]:
            with self.subTest(text=text):
                self.assertEqual(parse_target(text)["state"], state)
        self.assertEqual(one("Victoria Park WA")["state"], "WA")
        self.assertEqual(one("Victoria Park WA")["locality"], "Victoria Park")
        self.assertEqual(one("Perth TAS")["state"], "TAS")
        self.assertEqual(one("Perth TAS")["precision"], "locality")

    def test_split_alternatives_and_keep_comma_qualifiers(self):
        for separator in [" / ", "; ", " | ", " and ", " & ", "\n", ", "]:
            with self.subTest(separator=separator):
                values = parse_locations("Sydney NSW Hybrid" + separator + "Melbourne VIC Remote")
                self.assertEqual([v["city"] for v in values], ["Sydney", "Melbourne"])
                self.assertEqual([v["work_mode"] for v in values], ["hybrid", "remote"])
        self.assertEqual(one("Sydney, NSW, Australia")["city"], "Sydney")
        self.assertEqual(one("Richmond, VIC, 3121")["postcode"], "3121")
        self.assertEqual([v["state"] for v in parse_locations("NSW, VIC")], ["NSW", "VIC"])

    def test_raw_is_preserved_and_results_do_not_share_mutable_state(self):
        text = "  Sydney,NSW, Australia  "
        self.assertEqual(one(text)["raw"], text)
        self.assertEqual(parse_target(text)["raw"], text)
        self.assertEqual(parse_locations("Sydney,NSW / Melbourne,VIC")[0]["raw"], "Sydney,NSW")
        loc = one("0872")
        loc["state"].append("VIC")
        self.assertEqual(one("0872")["state"], ["NT", "SA", "WA"])

    def test_mixed_precision_is_kept_per_location(self):
        values = parse_locations("3000 / Melbourne / VIC / Australia / Atlantis")
        self.assertEqual([v["precision"] for v in values], ["postcode", "city", "state", "country", "unknown"])
        self.assertEqual([classify(v, parse_target("3000")) for v in values],
                         ["match", "related", "related", "related", "unknown"])

    def test_clear_all_filters_returns_match_even_for_unknown(self):
        for loc in parse_locations("0800 / Melbourne Remote / Atlantis"):
            with self.subTest(location=loc):
                self.assertEqual(classify(loc), "match")
                self.assertEqual(classify(loc, None, "any"), "match")
                self.assertEqual(classify(loc, {}, "any"), "match")
        loc = one("Melbourne Hybrid")
        self.assertEqual(classify(loc, None, "remote"), "hidden")
        self.assertEqual(classify(loc, None, "any"), "match")
        self.assertEqual(classify(one("Atlantis"), None, "remote"), "related")

    def test_a_style_geographic_target_dictionaries(self):
        self.assertEqual(classify(one("Melbourne"), {"state": "VIC"}), "match")
        self.assertEqual(classify(one("Melbourne"), {"city": "melbourne", "state": "VIC"}), "match")
        self.assertEqual(classify(one("Melbourne"), {"postcode": "3000", "state": "VIC"}), "related")
        self.assertEqual(classify(one("3000"), {"postcode": "3000"}), "match")
        self.assertEqual(classify(one("Atlantis"), {"state": "VIC"}), "unknown")

    def test_broken_reference_fails_visibly(self):
        location_module._reference.cache_clear()
        try:
            with patch.object(Path, "read_bytes", return_value=b"corrupt reference"):
                with self.assertRaisesRegex(ValueError, "reference is invalid"):
                    parse_locations("Melbourne")
            with patch.object(Path, "read_bytes", side_effect=FileNotFoundError("missing reference")):
                with self.assertRaises(FileNotFoundError):
                    parse_locations("Melbourne")
        finally:
            location_module._reference.cache_clear()

    def test_invalid_targets_and_modes_fail_readably(self):
        for text in [None, "", " ", "Australia", "Melbourne / Sydney", "Remote NSW"]:
            with self.subTest(text=text):
                with self.assertRaises(ValueError) as error:
                    parse_target(text)
                self.assertGreater(len(str(error.exception)), 25)
        with self.assertRaisesRegex(ValueError, "Work mode"):
            classify(one("Melbourne"), work_mode="full-time")

    def test_result_schema_and_reference_version(self):
        required = {"raw", "precision", "work_mode", "source", "reference_version", "reason"}
        allowed = required | {"state", "postcode", "locality", "city"}
        for value in parse_locations("Melbourne / 0872 / Richmond / Australia / Atlantis"):
            with self.subTest(value=value):
                self.assertTrue(required <= value.keys() <= allowed)
                self.assertTrue(value["source"])
                self.assertRegex(value["reference_version"], r"^geonames-au-[0-9a-f]{16}$")
                self.assertTrue(all(item is not None for item in value.values()))

    def test_public_reference_integrity_and_actual_relations(self):
        folder = ROOT / "jobs" / "data"
        metadata = json.loads((folder / "location-reference.json").read_text(encoding="utf-8"))
        payload = (folder / "au-postcodes.tsv").read_bytes()
        self.assertEqual(hashlib.sha256(payload).hexdigest(), metadata["seed"]["sha256"])
        rows = list(csv.reader(payload.decode("utf-8").splitlines(), delimiter="\t"))
        self.assertEqual(rows[0], ["postcode", "locality", "state"])
        self.assertEqual(len(rows) - 1, metadata["seed"]["rows"])
        self.assertEqual(len(rows) - 1, len({tuple(row) for row in rows[1:]}))
        self.assertEqual(rows[1:], sorted(rows[1:]))
        self.assertTrue(all(len(row) == 3 for row in rows))  # no coordinates
        self.assertIn(["0800", "Darwin", "NT"], rows)
        self.assertIn(["2620", "Queanbeyan", "NSW"], rows)
        self.assertIn(["2620", "Hume", "ACT"], rows)
        self.assertIn(["3121", "Richmond", "VIC"], rows)
        self.assertEqual(metadata["license"], "CC BY 4.0")
        for name in ["AU.zip", "readme.txt"]:
            self.assertEqual(metadata["resources"][name]["url"], "https://download.geonames.org/export/zip/" + name)
            self.assertRegex(metadata["resources"][name]["sha256"], r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    # A warm reference cache cannot conceal networking or DB access in tests.
    with patch.object(socket, "socket", side_effect=AssertionError("No network")), \
         patch.object(socket, "create_connection", side_effect=AssertionError("No network")), \
         patch.object(urllib.request, "urlopen", side_effect=AssertionError("No downloads")), \
         patch.object(sqlite3, "connect", side_effect=AssertionError("No database")):
        unittest.main(verbosity=2)
