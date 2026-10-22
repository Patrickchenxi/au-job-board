#!/usr/bin/env python3
"""Synthetic panel location presentation contracts; no personal config or DB."""
from __future__ import annotations

import copy
import json
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
        return [a for t, a in self.nodes if (tag is None or tag == t)
                and all(a.get(k.replace('_', '-')) == v for k, v in attrs.items())]


def row(**extra):
    a = dict(location_id='stable-sydney', raw='Sydney NSW', precision='city', state='NSW',
             postcode=None, locality=None, city='sydney', work_mode='onsite', source='Synthetic reference',
             reason='explicit_city', corrected=False, active=True)
    b = dict(a, location_id='stable-melbourne', raw='Melbourne VIC', state='VIC', city='melbourne',
             work_mode='hybrid')
    result = dict(uid='synthetic:multi', title='Synthetic Junior Engineer', company='Example Team',
                  location='Sydney NSW / Melbourne VIC', source='synthetic', total_score=5,
                  url='https://example.invalid/job', description='A wholly fictional role.', reasons='[]',
                  _locations=[a, b], _location=b, location_scope=True, _label={},
                  _legacy_label=dict(action='applied', interest='want', priority=True, note='Legacy synthetic note；'),
                  _geo_match='match')
    result.update(extra)
    return result


class LocationViews(unittest.TestCase):
    def test_selection_and_legacy_reference_are_separate_in_both_languages(self):
        for lang in i18n.LANGS:
            with self.subTest(lang=lang):
                html = panel_views._detail_html(row(), lang)
                nodes = Nodes(html)
                scope = nodes.find(data_location_id='stable-melbourne')[0]
                self.assertEqual(json.loads(scope['data-scope-label'])['action'], None)
                options = nodes.find('option')
                self.assertEqual([o['value'] for o in options[:3]], ['', 'stable-sydney', 'stable-melbourne'])
                self.assertIn('selected', options[2])
                actions = nodes.find('button', data_field='action')
                self.assertFalse(any('on' in b['class'].split() for b in actions))
                notes = nodes.find('input', data_uid='synthetic:multi')
                self.assertEqual(notes[0]['value'], '')
                self.assertIn('Legacy synthetic note', html)
                for key in ('location.scope', 'location.legacy_title', 'location.original', 'location.source', 'location.precision'):
                    self.assertIn(i18n.t(lang, key), html)
                self.assertIn('Synthetic reference', html)

    def test_legacy_summary_keeps_status_and_explicit_location_choices(self):
        sample = row(_location=None, location_scope=False, _label={'action': 'applied', 'note': 'Legacy；'})
        html = panel_views._detail_html(sample)
        nodes = Nodes(html)
        self.assertTrue(nodes.find('div', data_location_id=''))
        self.assertEqual(nodes.find('input', data_uid=sample['uid'])[0]['value'], 'Legacy；')
        self.assertIn('stable-melbourne', html)
        self.assertNotIn('id="location-raw"', html)
        self.assertTrue(any('on' in b['class'].split() for b in nodes.find('button', data_field='action', data_value='applied')))

    def test_card_identity_and_original_data_escape(self):
        sample = row()
        html = panel_views._card(sample)
        self.assertEqual(Nodes(html).find('div', data_uid=sample['uid'])[0]['data-location-id'], 'stable-melbourne')
        legacy = panel_views._card(row(_location=None, location_scope=False))
        self.assertEqual(Nodes(legacy).find('div', data_uid=sample['uid'])[0]['data-location-id'], '')
        sample['_location']['raw'] = '\"><img src=x onerror=alert(1)>'
        sample['location'] = '<script>unsafe()</script>'
        sample['_legacy_label']['note'] = '<img src=x onerror=alert(1)>'
        html = panel_views._detail_html(sample)
        self.assertFalse(Nodes(html).find('img'))
        self.assertFalse(Nodes(html).find('script'))
        self.assertIn('&lt;script&gt;', html)

    def test_copy_text_names_current_record_location(self):
        copied = Nodes(panel_views._detail_html(row(), 'en')).find('button', onclick='copyJob(this)')[0]['data-copy-text']
        self.assertIn('Location: Sydney NSW / Melbourne VIC\nCurrent record location: Melbourne VIC\n', copied)
        self.assertIn('A wholly fictional role.', copied)
        legacy = Nodes(panel_views._detail_html(row(_location=None), 'en')).find('button', onclick='copyJob(this)')[0]
        self.assertNotIn('Current record location', legacy['data-copy-text'])

    def test_correction_controls_and_historical_location(self):
        sample = row()
        sample['_location']['corrected'] = True
        sample['_locations'][0]['active'] = False
        html = panel_views._detail_html(sample, 'en')
        self.assertIn('Manual correction:', html)
        self.assertIn('Historical location', html)
        self.assertNotIn('disabled', Nodes(html).find('button', onclick='saveLocation(true)')[0])
        modes = [n['value'] for n in Nodes(html).find('option')][3:]
        self.assertEqual(modes, ['unknown', 'remote', 'hybrid', 'onsite'])
        sample['_location']['corrected'] = False
        self.assertIn('disabled', Nodes(panel_views._detail_html(sample)).find('button', onclick='saveLocation(true)')[0])

    def test_reading_path_folds_provenance_and_names_record_scope(self):
        for lang in i18n.LANGS:
            with self.subTest(lang=lang):
                html = panel_views._detail_html(row(), lang)
                nodes = Nodes(html)
                folds = [n.get('class') for n in nodes.find('details')]
                self.assertEqual(folds[:2], ['location-legacy', 'location-more'])
                # Nothing about provenance/correction is open on the reading path.
                self.assertFalse(any('open' in n for n in nodes.find('details')))
                legacy_summary = html.split('class="location-legacy"><summary>')[1].split('</summary>')[0]
                self.assertIn(panel_views._state_text({'action': 'applied', 'priority': True}, lang), legacy_summary)
                more = html.split('class="location-more">')[1].split('</details>')[0]
                for marker in ('id="location-raw"', 'id="location-mode"', 'saveLocation(false)',
                               i18n.t(lang, 'location.original'), 'Synthetic reference'):
                    self.assertIn(marker, more)
                chip = nodes.find('button', **{'class': 'scope-chip'})
                self.assertEqual(len(chip), 1)
                self.assertEqual(chip[0]['onclick'], 'focusLocationChoice()')
                self.assertIn(i18n.t(lang, 'location.record_at', name='Melbourne VIC'), html)
                # The chip sits inside the action step, before the action buttons.
                self.assertLess(html.index('scope-chip'), html.index('data-field="action"'))
                self.assertGreater(html.index('scope-chip'), html.index('label-sheet'))
                self.assertNotIn(i18n.t(lang, 'location.outside'), html)
                outside = panel_views._detail_html(row(_geo_match='hidden'), lang)
                self.assertIn(i18n.t(lang, 'location.outside'), outside)

    def test_legacy_summary_scope_chip_and_no_location_rows(self):
        legacy = panel_views._detail_html(row(_location=None, location_scope=False), 'en')
        self.assertIn(i18n.t('en', 'location.record_at', name=i18n.t('en', 'location.legacy_name')), legacy)
        self.assertNotIn('location-more', legacy)
        bare = panel_views._detail_html(row(_location=None, _locations=[], location_scope=False), 'en')
        self.assertNotIn('scope-chip', bare)

    def test_invalid_region_renders_guidance_without_querying(self):
        cases = {'Richmond': 'location.geo_error.ambiguous',
                 'Melbourne VIC, Sydney': 'location.geo_error.multiple',
                 'Atlantis': 'location.geo_error.unsupported'}
        self.assertIsNone(panel_views._geo_error('Melbourne VIC'))
        with tempfile.TemporaryDirectory(prefix='jobs-location-view-') as tmp:
            config = {'db_path': str(Path(tmp) / 'synthetic.db')}
            conn = db.connect(config['db_path'])
            try:
                for geo, key in cases.items():
                    self.assertEqual(panel_views._geo_error(geo), key)
                    for lang in i18n.LANGS:
                        with self.subTest(geo=geo, lang=lang), \
                             patch.object(panel_views, '_query', side_effect=AssertionError('queried')), \
                             patch.object(panel_views, '_resolve_since', return_value=None), \
                             patch.object(panel_views, '_last_run_note', return_value=''), \
                             patch('jobs.run_state.generation', return_value='synthetic-generation'):
                            html = panel_views.render_page(conn, config, 'all', 0, 10, filters={'geo': geo}, lang=lang)
                            nodes = Nodes(html)
                            self.assertEqual(nodes.find('input', data_fkey='geo')[0]['aria-invalid'], 'true')
                            self.assertTrue(nodes.find('div', id='geo-error', role='alert'))
                            self.assertIn(i18n.t(lang, key), html)
                            self.assertIn("removeFilter('geo')", html)
                            self.assertNotIn('<details class="location-filter-hint"', html)
            finally:
                conn.close()

    def test_controls_and_translations(self):
        for view in panel_data.VIEWS:
            allowed = panel_data.VIEW_FILTER_KEYS[view]
            # Parent owns the allowed-filter contract; fail if integration omits it.
            self.assertIn('geo', allowed)
            self.assertIn('mode', allowed)
            for lang in i18n.LANGS:
                bar = panel_views._filter_bar(view, {'geo': 'Melbourne VIC', 'mode': 'hybrid'}, {}, lang)
                nodes = Nodes(bar)
                geo = nodes.find('input', data_fkey='geo')
                self.assertEqual(len(geo), 1)
                self.assertEqual(geo[0]['oninput'], 'geoTyping()')
                self.assertEqual(len(nodes.find('select', data_fkey='mode')), 1)
                self.assertIn('geoKeys(event)', bar)
                self.assertIn(i18n.t(lang, 'location.apply'), bar)
                self.assertEqual(geo[0]['list'], 'geo-suggest')
                self.assertNotIn('aria-invalid', geo[0])
                suggestions = [n['value'] for n in nodes.find('option') if n.get('value') and ' ' in n['value'] or n.get('value') in ('VIC', 'NSW')]
                self.assertIn('Melbourne VIC', suggestions)
                self.assertIn('VIC', suggestions)
        self.assertFalse(panel_views._is_active('mode', {'mode': 'any'}))
        self.assertTrue(panel_views._is_active('mode', {'mode': 'remote'}))
        keys = {k for k in i18n.STRINGS['zh'] if k.startswith('location.')}
        self.assertEqual(keys, {k for k in i18n.STRINGS['en'] if k.startswith('location.')})
        for lang in i18n.LANGS:
            self.assertTrue(keys <= i18n.js_strings(lang).keys())

    def test_all_views_group_this_page_without_changing_order_or_page_count(self):
        with tempfile.TemporaryDirectory(prefix='jobs-location-view-') as tmp:
            config = {'db_path': str(Path(tmp) / 'synthetic.db')}
            conn = db.connect(config['db_path'])
            try:
                samples = [row(uid='related-1', _geo_match='related'), row(uid='match-1'),
                           row(uid='unknown-1', _geo_match='unknown'), row(uid='match-2')]
                for lang in i18n.LANGS:
                    for view in panel_data.VIEWS:
                        with patch.object(panel_views, '_query', return_value=(copy.deepcopy(samples), 9)), \
                             patch.object(panel_views, '_resolve_since', return_value=None), \
                             patch.object(panel_views, '_last_run_note', return_value=''), \
                             patch('jobs.run_state.generation', return_value='synthetic-generation'):
                            html = panel_views.render_page(conn, config, view, 0, 4,
                                                           filters={'geo': 'VIC'}, lang=lang)
                        groups = Nodes(html).find('section')
                        self.assertEqual([x['data-geo-match'] for x in groups if 'data-geo-match' in x],
                                         ['match', 'related', 'unknown'])
                        cards = [n['data-uid'] for n in Nodes(html).find('div') if 'card' in n.get('class', '').split()]
                        self.assertEqual(cards, ['match-1', 'match-2', 'related-1', 'unknown-1'])
                        self.assertIn('offset=4', html)
                        self.assertIn('geo=VIC', html)
                        self.assertIn(i18n.t(lang, 'location.filter_hint'), html)
                        self.assertIn(i18n.t(lang, 'location.filter_summary'), html)
                        self.assertIn(i18n.t(lang, 'location.group_hint.unknown'), html)
                        # No collapsed sections: related/unknown remain directly reachable.
                        self.assertFalse(any('hidden' in n for n in groups))
                with patch.object(panel_views, '_query', return_value=([row(uid='only-unknown', _geo_match='unknown')], 1)), \
                     patch.object(panel_views, '_resolve_since', return_value=None), \
                     patch.object(panel_views, '_last_run_note', return_value=''), \
                     patch('jobs.run_state.generation', return_value='synthetic-generation'):
                    html = panel_views.render_page(conn, config, 'all', 0, 4, filters={'mode': 'remote'})
                # Empty groups are omitted; the unknown result itself stays visible.
                self.assertEqual([x['data-geo-match'] for x in Nodes(html).find('section') if 'data-geo-match' in x], ['unknown'])
                self.assertIn('data-uid="only-unknown"', html)
            finally:
                conn.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
