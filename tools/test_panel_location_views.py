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
                        # No collapsed sections: related/unknown remain directly reachable.
                        self.assertFalse(any('hidden' in n for n in groups))
            finally:
                conn.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
