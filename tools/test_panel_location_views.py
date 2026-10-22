#!/usr/bin/env python3
"""Synthetic panel contracts for the simplified location search."""
from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from jobs import db, i18n, panel_data, panel_views  # noqa: E402


class Nodes(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.nodes = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.nodes.append((tag, dict(attrs)))

    def find(self, tag=None, **attrs):
        return [a for t, a in self.nodes
                if (tag is None or t == tag)
                and all(a.get(k.replace("_", "-")) == v for k, v in attrs.items())]


def row(uid="synthetic:group", location="Melbourne VIC / Sydney NSW", **extra):
    result = {
        "uid": uid,
        "title": "Synthetic Junior Engineer",
        "company": "Example Team",
        "location": location,
        "source": "synthetic",
        "total_score": 5,
        "url": "https://example.invalid/job",
        "description": "A wholly fictional role.",
        "reasons": "[]",
        "_label": {"action": "saved", "priority": True, "note": "Synthetic note；"},
        "_geo_match": "near",
        "duplicate_count": 1,
        "duplicate_sources": "synthetic@Sydney NSW",
    }
    result.update(extra)
    return result


class LocationViews(unittest.TestCase):
    def test_detail_has_only_group_state_and_original_location(self):
        sample = row()
        for lang in i18n.LANGS:
            with self.subTest(lang=lang):
                html = panel_views._detail_html(sample, lang)
                nodes = Nodes(html)
                root = nodes.find("div", data_uid=sample["uid"])[0]
                self.assertIn("data-label-scope", root)
                self.assertFalse(nodes.find("select", id="location-choice"))
                self.assertFalse(nodes.find("input", id="location-raw"))
                self.assertFalse(nodes.find("button", onclick="saveLocation(false)"))
                self.assertFalse(nodes.find("button", **{"class": "scope-chip"}))
                self.assertIn("Melbourne VIC / Sydney NSW", html)
                self.assertIn("synthetic@Sydney NSW", html)
                for old in ("location.scope", "location.legacy_title", "location.filter_hint"):
                    self.assertNotIn(i18n.t(lang, old), html)
                self.assertTrue(nodes.find("button", data_field="action", data_value="saved"))

    def test_card_uses_group_identity_without_location_scope_metadata(self):
        sample = row()
        html = panel_views._card(sample)
        nodes = Nodes(html)
        card = nodes.find("div", data_uid=sample["uid"])[0]
        self.assertNotIn("data-location-id", card)
        self.assertNotIn(i18n.t("zh", "location.record_count", n=2), html)
        self.assertIn("Melbourne VIC / Sydney NSW", html)

    def test_copy_contains_one_original_location_and_no_location_record(self):
        copied = Nodes(panel_views._detail_html(row(), "en")).find(
            "button", onclick="copyJob(this)")[0]["data-copy-text"]
        self.assertIn("Location: Melbourne VIC / Sydney NSW\n", copied)
        self.assertNotIn("Current record location", copied)
        self.assertIn("A wholly fictional role.", copied)

    def test_escape_boundary(self):
        sample = row(location='<script>unsafe()</script>')
        sample["_label"]["note"] = '<img src=x onerror=alert(1)>'
        html = panel_views._detail_html(sample)
        self.assertFalse(Nodes(html).find("script"))
        self.assertFalse(Nodes(html).find("img"))
        self.assertIn("&lt;script&gt;", html)

    def test_filter_controls_are_one_location_box_and_no_work_mode(self):
        for view in panel_data.VIEWS:
            allowed = panel_data.VIEW_FILTER_KEYS[view]
            self.assertNotIn("mode", allowed)
            self.assertEqual("geo" in allowed, view != "recommend")
        bar = panel_views._filter_bar("all", {"geo": "Carlton"}, {}, "en")
        nodes = Nodes(bar)
        self.assertEqual(len(nodes.find("input", data_fkey="geo")), 1)
        self.assertFalse(nodes.find("select", data_fkey="mode"))
        self.assertFalse(nodes.find("select"))
        self.assertFalse(nodes.find("datalist"))
        self.assertNotIn('list="geo-suggest"', bar)
        self.assertTrue(nodes.find("button", data_fkey="tier"))
        self.assertTrue(nodes.find("div", role="listbox"))
        self.assertIn('value="Australia"', bar)
        self.assertIn('value="VIC"', bar)
        for lang in ("en", "zh"):
            self.assertEqual("Sydney / NSW / 2000...",
                             i18n.t(lang, "location.region_hint"))

    def test_ambiguous_locality_is_valid_but_bad_or_multiple_inputs_show_guidance(self):
        self.assertIsNone(panel_views._geo_error("Carlton"))
        self.assertEqual(panel_views._geo_error("Melbourne VIC / Sydney NSW"),
                         "location.geo_error.multiple")
        self.assertEqual(panel_views._geo_error("3000 3053"),
                         "location.geo_error.multiple")
        self.assertEqual(panel_views._geo_error("Atlantis"),
                         "location.geo_error.unsupported")
        with tempfile.TemporaryDirectory(prefix="jobs-location-view-") as tmp:
            config = {"db_path": str(Path(tmp) / "synthetic.db"), "location": {"local": ["VIC"]}}
            conn = db.connect(config["db_path"])
            try:
                for text, key in (("Melbourne VIC / Sydney NSW", "location.geo_error.multiple"),
                                  ("Atlantis", "location.geo_error.unsupported")):
                    with self.subTest(text=text), \
                         patch.object(panel_views, "_query", side_effect=AssertionError("queried")), \
                         patch.object(panel_views, "_resolve_since", return_value=None), \
                         patch.object(panel_views, "_last_run_note", return_value=""), \
                         patch("jobs.run_state.generation", return_value="synthetic-generation"):
                        html = panel_views.render_page(
                            conn, config, "all", 0, 10, filters={"geo": text}, lang="en")
                    self.assertIn(i18n.t("en", key), html)
                    self.assertIn("removeFilter('geo')", html)
            finally:
                conn.close()

    def test_blocks_render_as_separators_without_labels_or_explanations(self):
        samples = [
            row(uid="exact", _geo_match="exact"),
            row(uid="near", _geo_match="near"),
            row(uid="unknown", _geo_match="unknown"),
        ]
        with tempfile.TemporaryDirectory(prefix="jobs-location-view-") as tmp:
            config = {"db_path": str(Path(tmp) / "synthetic.db"), "location": {"local": ["VIC"]}}
            conn = db.connect(config["db_path"])
            try:
                for lang in i18n.LANGS:
                    with patch.object(panel_views, "_query",
                                      return_value=(copy.deepcopy(samples), 5)), \
                         patch.object(panel_views, "_resolve_since", return_value=None), \
                         patch.object(panel_views, "_last_run_note", return_value=""), \
                         patch("jobs.run_state.generation", return_value="synthetic-generation"):
                        html = panel_views.render_page(
                            conn, config, "all", 0, 3, filters={"geo": "3053"}, lang=lang)
                    nodes = Nodes(html)
                    self.assertEqual(len(nodes.find("hr", **{"class": "geo-divider"})), 2)
                    self.assertEqual(
                        [n["data-uid"] for n in nodes.find("div")
                         if "card" in n.get("class", "").split()],
                        ["exact", "near", "unknown"])
                    self.assertNotIn('class="location-filter-hint"', html)
                    self.assertNotIn('class="location-group"', html)
            finally:
                conn.close()

    def test_switching_to_recommended_drops_location_filter_from_links(self):
        with tempfile.TemporaryDirectory(prefix="jobs-location-view-") as tmp:
            config = {"db_path": str(Path(tmp) / "synthetic.db"), "location": {"local": ["VIC"]}}
            conn = db.connect(config["db_path"])
            try:
                with patch.object(panel_views, "_query", return_value=([], 0)), \
                     patch.object(panel_views, "_resolve_since", return_value=None), \
                     patch.object(panel_views, "_last_run_note", return_value=""), \
                     patch("jobs.run_state.generation", return_value="synthetic-generation"):
                    html = panel_views.render_page(
                        conn, config, "all", 0, 10,
                        filters={"geo": "Melbourne", "sort": "score"}, lang="en")
                links = [node["href"] for node in Nodes(html).find("a")
                         if "tab" in node.get("class", "").split()]
                recommended = next(href for href in links if "view=recommend" in href)
                self.assertNotIn("geo=", recommended)
                self.assertNotIn("sort=", recommended)
                all_view = next(href for href in links if "view=all" in href)
                self.assertIn("geo=Melbourne", all_view)
            finally:
                conn.close()

    def test_i18n_location_keys_match_and_are_available_to_js(self):
        keys = {key for key in i18n.STRINGS["zh"] if key.startswith("location.")}
        self.assertEqual(keys, {key for key in i18n.STRINGS["en"]
                                if key.startswith("location.")})
        for lang in i18n.LANGS:
            self.assertTrue(keys <= i18n.js_strings(lang).keys())


if __name__ == "__main__":
    unittest.main(verbosity=2)
