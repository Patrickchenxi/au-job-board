"""Location-aware panel selection. No writes, no new scoring/dedupe algorithm."""
from __future__ import annotations
from . import locations, location_store, labels as labels_mod, report, skills

GEO_KEYS = ('geo', 'mode')


def enabled(filters):
    return bool(filters.get('geo') or filters.get('mode') in ('remote', 'hybrid', 'onsite'))


def options(conn, uid):
    return location_store.locations_for(conn, uid)


def choose(items, filters):
    target = locations.parse_target(filters['geo']) if filters.get('geo') else None
    mode = filters.get('mode') or 'any'
    matches = [(locations.classify(item, target, mode), item) for item in items if item['active']]
    for kind in ('match', 'related', 'unknown'):
        selected = next(((k, item) for k, item in matches if k == kind), None)
        if selected:
            return selected
    return None


def decorate(conn, row, legacy_labels, index, selected=None, kind=None):
    row = report.decorate([dict(row)], legacy_labels, index)[0]
    row['_locations'] = options(conn, row['uid'])
    row['_legacy_label'] = dict(row.get('_label') or {})
    row['_scoped_records'] = conn.execute('SELECT COUNT(DISTINCT location_id) FROM location_labels WHERE uid=?', (row['uid'],)).fetchone()[0]
    row['_location'] = selected
    row['location_scope'] = selected is not None
    if selected is not None:
        current = location_store.label_for(conn, row['uid'], selected['location_id'])
        row['_label'] = current
        row['_geo_match'] = kind or 'match'
        row['priority'] = current.get('priority')
        row['label_priority'] = current.get('priority')
        row['processed'] = bool(current.get('action'))
        row['qualification'] = labels_mod.qualification(row, current)
        for key in ('eligibility', 'interest', 'action', 'note'):
            row['label_' + key] = current.get(key) or ''
    return row


def find(conn, config, uid, location_id=None, filters=None):
    kept, excluded, legacy, index = report.load(conn, config, deduplicate=False)
    row = next((r for r in kept + excluded if r['uid'] == uid), None)
    if row is None:
        return None
    filters = filters or {}
    selected, kind = None, None
    items = options(conn, uid)
    if location_id:
        selected = next((i for i in items if i['location_id'] == location_id), None)
        if selected is None:
            raise ValueError('Unknown location for this source record')
        target = locations.parse_target(filters['geo']) if filters.get('geo') else None
        kind = locations.classify(selected, target, filters.get('mode') or 'any')
    elif enabled(filters):
        match = choose(items, filters)
        if match:
            kind, selected = match
        else:
            # A saved deep link remains readable even outside the current filter.
            selected = next((i for i in items if i['active']), None)
            kind = 'hidden'
    return decorate(conn, row, legacy, index, selected, kind)


def query(conn, config, view, offset, limit, filters, since, skills_cfg, *, candidate_uids=None):
    from . import db, panel_data
    kept, excluded, legacy, index = report.load(conn, config, deduplicate=False)
    raw = (excluded if view == 'excluded' else kept if view == 'recommend' else kept + excluded)
    if candidate_uids is not None:
        raw = [r for r in raw if r['uid'] in candidate_uids]
    # Select source candidates before choosing display representatives.
    if view == 'new':
        batch = db.last_batch_started_at(conn)
        raw = [r for r in raw if batch and (r.get('first_seen_at') or '') >= batch]
    rows = []
    target = locations.parse_target(filters['geo']) if filters.get('geo') else None
    terms = skills.search_terms(filters['q'], skills_cfg or {}) if filters.get('q') else []
    for row in raw:
        candidates = []
        for selected in options(conn, row['uid']):
            if not selected['active']:
                continue
            kind = locations.classify(selected, target, filters.get('mode') or 'any')
            if kind == 'hidden':
                continue
            item = decorate(conn, row, legacy, index, selected, kind)
            current = item['_label']
            if view == 'recommend':
                frozen = location_store.label_for(conn, row['uid'], selected['location_id'], since)
                if frozen.get('action') or panel_data.is_stale(row):
                    continue
                item['_scope_identity_owned'] = frozen.get('_has_record_at', False)
            else:
                item['_scope_identity_owned'] = current.get('_has_record', False)
            has_record = current.get('_has_record') or report.has_labels(row, legacy, index)
            if view == 'labelled' and not has_record:
                continue
            if terms and not all(rx.search(panel_data._search_text(item, current)) for rx, _, _ in terms):
                continue
            if not panel_data.passes_filters(item, current, filters, has_record):
                continue
            candidates.append(item)
        # Choose only after each location's status filters. One card per source;
        # all its other locations remain explicitly selectable in the detail.
        if view == 'labelled':
            candidates.sort(key=lambda r: not r['_label'].get('_has_record'))
        for kind in ('match', 'related', 'unknown'):
            item = next((r for r in candidates if r['_geo_match'] == kind), None)
            if item is not None:
                rows.append(item)
                break
    rows = panel_data._ordered(rows, view, filters, config)
    # Retain ordinary grouping, but never collapse a distinct place into another.
    # Records with a human scoped edit remain independently reachable.
    grouped = []
    seen = set()
    for row in rows:
        loc = row['_location']
        place = tuple(tuple(sorted(loc[k])) if isinstance(loc.get(k), list) else loc.get(k)
                      for k in ('precision', 'state', 'postcode', 'locality', 'city', 'work_mode'))
        if loc['precision'] == 'unknown' or row.get('_scope_identity_owned'):
            place = (row['uid'], loc['location_id'])
        key = (row.get('dedupe_group') or row['uid'], place)
        if key in seen:
            continue
        seen.add(key)
        grouped.append(row)
    rank = {'match': 0, 'related': 1, 'unknown': 2}
    grouped.sort(key=lambda r: rank[r['_geo_match']])
    return grouped[offset:offset + limit], len(grouped)
