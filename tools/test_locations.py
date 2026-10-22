#!/usr/bin/env python3
"""Synthetic offline location-search semantics; no personal or network data."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from jobs import locations  # noqa: E402


class LocationSearch(unittest.TestCase):
    def tier(self, raw, query):
        return locations.match_tier(
            locations.parse_listing(raw), locations.parse_target(query))

    def test_seed_and_supported_targets(self):
        metadata, places, postcodes, aliases, capitals = locations._reference()
        self.assertEqual(metadata["reference_version"], "geonames-au-011ef7d2b65ba2a0")
        self.assertEqual(metadata["seed"]["rows"], 18514)
        self.assertIn("carlton", places)
        self.assertIn("3053", postcodes)
        self.assertEqual(aliases["victoria"], "VIC")
        self.assertIn("melbourne", capitals)
        self.assertEqual(locations.parse_target("Australia")["precision"], "country")
        self.assertEqual(locations.parse_target("澳大利亚")["precision"], "country")
        self.assertEqual(locations.parse_target("Vic")["states"],
                         locations.parse_target("Victoria")["states"])

    def test_capital_and_cbd_postcode_are_distinct_listing_precisions(self):
        city = locations.parse_listing("Melbourne VIC")
        cbd = locations.parse_listing("Melbourne City Centre VIC")
        explicit = locations.parse_listing("Melbourne City Centre, VIC 3000")
        split_postcode = locations.parse_listing("Melbourne, VIC, 3000")
        region = locations.parse_listing("Melbourne Western Suburbs VIC")
        self.assertEqual(city["precision"], "city")
        self.assertEqual(city["states"], ["VIC"])
        self.assertEqual(region["precision"], "city")
        self.assertEqual(cbd["precision"], "postcode")
        self.assertEqual(cbd["postcodes"], ["3000"])
        self.assertEqual(explicit["precision"], "postcode")
        self.assertEqual(explicit["postcodes"], ["3000"])
        self.assertEqual(split_postcode["precision"], "postcode")
        self.assertEqual(split_postcode["postcodes"], ["3000"])
        for query in ("Melbourne", "Melbourne VIC", "3000"):
            self.assertEqual(self.tier("Melbourne City Centre VIC", query), "exact")
            self.assertEqual(self.tier("Melbourne VIC", query), "near")

    def test_ambiguous_locality_is_accepted_and_all_matches_are_kept(self):
        target = locations.parse_target("Carlton")
        self.assertEqual(target["precision"], "locality")
        self.assertEqual(target["localities"], {"carlton"})
        self.assertEqual(target["states"], {"NSW", "TAS", "VIC"})
        self.assertEqual(self.tier("Carlton VIC", "Carlton"), "exact")
        self.assertEqual(self.tier("Carlton NSW", "Carlton"), "exact")
        self.assertEqual(self.tier("Carlton TAS", "Carlton"), "exact")
        self.assertEqual(self.tier("Melbourne VIC", "Carlton"), "near")
        self.assertEqual(self.tier("Carlton NSW", "Carlton VIC"), "hidden")
        self.assertEqual(self.tier("Carlton NSW", "3053"), "hidden")
        self.assertEqual(self.tier("Queanbeyan NSW 2620", "2620 NSW"), "exact")
        self.assertEqual(self.tier("Hume ACT 2620", "2620 NSW"), "hidden")

    def test_postcode_block_then_coarse_same_state_then_unknown(self):
        expected = [
            ("Carlton VIC", "exact"),
            ("Carlton South VIC", "exact"),
            ("Melbourne VIC", "near"),
            ("Geelong VIC", "hidden"),
            ("Sydney NSW", "hidden"),
            ("Undisclosed", "unknown"),
        ]
        for listing, tier in expected:
            with self.subTest(listing=listing):
                self.assertEqual(self.tier(listing, "3053"), tier)

    def test_capital_other_victoria_then_unknown(self):
        expected = [
            ("Melbourne City Centre VIC", "exact"),
            ("Carlton VIC", "near"),
            ("Melbourne VIC", "near"),
            ("Sydney NSW", "hidden"),
            ("Undisclosed", "unknown"),
        ]
        for query in ("Melbourne", "3000"):
            for listing, tier in expected:
                with self.subTest(query=query, listing=listing):
                    self.assertEqual(self.tier(listing, query), tier)

    def test_state_country_and_first_location_only(self):
        self.assertEqual(self.tier("Carlton VIC", "VIC"), "exact")
        self.assertEqual(self.tier("Melbourne VIC", "Victoria"), "exact")
        self.assertEqual(self.tier("Sydney NSW", "VIC"), "hidden")
        self.assertEqual(self.tier("Undisclosed", "VIC"), "unknown")
        self.assertEqual(self.tier("Sydney NSW", "Australia"), "exact")
        self.assertEqual(self.tier("All Australia", "Australia"), "exact")
        self.assertEqual(locations.parse_target("All Australia")["precision"], "country")
        self.assertEqual(self.tier("Undisclosed", "Australia"), "unknown")
        first = locations.parse_listing("Sydney NSW Hybrid / Melbourne VIC Remote")
        self.assertEqual(first["states"], ["NSW"])
        self.assertEqual(first["city"], "Sydney")
        comma = locations.parse_listing("Sydney NSW, Melbourne VIC")
        self.assertEqual(comma["states"], ["NSW"])
        self.assertEqual(comma["city"], "Sydney")
        for raw in ("Sydney NSW and Melbourne VIC", "Sydney NSW & Melbourne VIC"):
            joined = locations.parse_listing(raw)
            self.assertEqual(joined["states"], ["NSW"])
            self.assertEqual(joined["city"], "Sydney")
        self.assertEqual(locations.parse_listing("Victoria Park, WA")["states"], ["WA"])
        self.assertEqual(locations.parse_listing("South Australia")["states"], ["SA"])
        self.assertEqual(locations.parse_listing("Western Australia")["states"], ["WA"])

    def test_missing_state_and_invalid_search_are_explicit(self):
        self.assertEqual(locations.parse_listing("Carlton")["precision"], "unknown")
        self.assertEqual(locations.parse_listing("2123")["states"], ["NSW"])
        airport = locations.parse_listing("Melbourne Airport VIC 3041")
        self.assertEqual(airport["precision"], "postcode")
        self.assertEqual(airport["postcodes"], ["3041"])
        self.assertEqual(airport["reason"], "postcode_locality_unverified")
        for value in ("Melbourne VIC / Sydney NSW", "Sydney NSW and Melbourne VIC",
                      "Melbourne VIC Remote", "Atlantis"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                locations.parse_target(value)

    def test_known_capital_prefix_suburbs_are_localities(self):
        cases = (
            ("Melbourne Airport VIC", "Melbourne Airport", {"3045"}),
            ("Sydney Olympic Park NSW", "Sydney Olympic Park", {"2127"}),
        )
        for raw, locality, postcodes in cases:
            parsed = locations.parse_listing(raw)
            target = locations.parse_target(raw)
            self.assertEqual(parsed["precision"], "locality")
            self.assertEqual(target["precision"], "locality")
            self.assertEqual(set(parsed["postcodes"]), postcodes)
            self.assertEqual(locations.match_tier(parsed, target), "exact")

    def test_country_only_is_unknown_for_narrow_geography(self):
        country = locations.parse_listing("Australia")
        for query in ("Melbourne", "3000", "3053", "Carlton", "VIC"):
            with self.subTest(query=query):
                self.assertEqual(self.tier("Australia", query), "unknown")

    def test_local_preference_is_pattern_driven(self):
        patterns = [r"\bVIC\b", "melbourne"]
        self.assertTrue(locations.is_local("Melbourne VIC", patterns))
        self.assertTrue(locations.is_local("Sydney NSW / Melbourne VIC", patterns))
        self.assertFalse(locations.is_local("Sydney NSW", patterns))
        self.assertFalse(locations.is_local("Melbourne VIC", [r"["]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
