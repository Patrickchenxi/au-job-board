# Offline Australian location reference

`jobs.locations` parses location text using bundled public reference data. It
does not fetch data at runtime, open a database or assert that a place is an
office. The input examples and regression tests are hand-written synthetic
strings; the geographical seed is public reference data, not job data.

## Source, license and snapshot

Contains data from [GeoNames](https://www.geonames.org/), licensed under
[Creative Commons Attribution 4.0](https://creativecommons.org/licenses/by/4.0/).
The [official postal-code readme](https://download.geonames.org/export/zip/readme.txt)
identifies this license and states that accuracy, timeliness and completeness
are not guaranteed. Attribution must accompany redistributed data. GeoNames is
the publisher of this reference, not an Australian postal authority.

- Source: [AU.zip](https://download.geonames.org/export/zip/AU.zip), downloaded
  2026-10-22 UTC together with the official readme.
- Archive SHA-256:
  `fc6264334dab43ac67e3b6950bcd733918681b0158e65412448e59fcec054ded`.
- Readme SHA-256:
  `fff60148da20f4d182859d926518efa5b0f3949f3c3273a284901325f1f8f008`.
- `AU.txt` contains 18,521 source rows; 18,514 distinct triples remain after
  projection to `postcode`, `locality`, `state`, deduplication and sorting.
- Seed SHA-256:
  `011ef7d2b65ba2a06af66f43e8ab4f1522e7083b33f5702826681b4b1a0f45ce`.
- Reference version: `geonames-au-011ef7d2b65ba2a0` (seed hash prefix).

The machine-readable [manifest](../jobs/data/location-reference.json) records
URLs, download timestamp, Last-Modified headers, byte counts, hashes, source
row count, transformation, attribution and seed schema. The
[TSV](../jobs/data/au-postcodes.tsv) has exactly three columns. All coordinates,
coordinate accuracy and lower administrative fields have been removed. Neither
the source archive nor source job text is shipped in this seed.

Postal codes remain four-character strings, including `0800`. The relationship
is many-to-many: `2620` has ACT and NSW entries; `0872` has NT, SA and WA entries.
These are GeoNames associations, not inferred legal boundaries. Even entries
for external territories retain the publisher's state associations. No state
is guessed from a postcode prefix, and no metro area is guessed from a point.

The manifest also contains a small, hand-maintained semantic list of eight
state/territory capitals: Adelaide, Brisbane, Canberra, Darwin, Hobart,
Melbourne, Perth and Sydney. This list recognizes city-level inputs; it is not
a metro boundary dataset. Other supported place names use GeoNames locality
precision. With an explicit other state, a capital name can instead resolve to
a supported locality (for example `Perth TAS`).

## API contract

```python
from jobs.locations import parse_locations, parse_target, classify

locations = parse_locations("Sydney NSW Hybrid / Melbourne VIC Remote")
target = parse_target("VIC")
matching_locations = [loc for loc in locations
                      if classify(loc, target, "remote") == "match"]
assert [loc["city"] for loc in matching_locations] == ["Melbourne"]
```

`parse_locations(raw: str | None, work_type: str | None = None) -> list[dict]`
returns at least one item. Missing text yields an unknown item. Each item has
`raw`, `precision`, `work_mode`, `source`, `reference_version` and `reason`.
Applicable geographical fields are `state`, `postcode`, `locality` and `city`;
absent fields are omitted. `state` is one uppercase code or a sorted list of
possible codes. Unknown/conflicting inputs keep their raw evidence and reason;
an observed unsupported postcode may remain on an item with unknown precision.
An unresolved name with a clearly stated state retains only state-level
precision and reason `unresolved_place_state_only`.

`precision` is one of `postcode`, `locality`, `city`, `state`, `country`,
`unknown`. An explicit supported postcode provides postcode precision. A
locality resolves only when its name and optional state yield one distinct
postcode/state relation. Several relations remain ambiguous, including several
postcodes within one state; this seed does not identify whether those rows
describe one locality or namesakes. An explicit postcode can disambiguate a
supported name. A name inconsistent with the postcode remains unknown rather
than inventing a metro relationship. `Melbourne` alone has city precision and
does not become postcode `3000`.

`raw` preserves the input for one unsplit item; alternative segments retain
their original interior text, with surrounding whitespace/separators removed.
Alternatives split on `/`, `;`, `|`, newlines, `and` and `&` outside parentheses.
Comma-separated recognized places split, while `Richmond, VIC, 3121` remains
one location. The parser intentionally supports a small structured-text grammar,
not arbitrary prose or street addresses. Unsupported residue is kept in raw
text and may reduce precision.

`work_mode` is `remote`, `hybrid`, `onsite` or `unknown`. Explicit mode markers
belong to their own segment. `Remote NSW / Melbourne VIC Onsite` therefore
has no VIC+remote match. `Sydney NSW Hybrid / Melbourne VIC Remote` does have
one. Missing modes never borrow another segment's Remote marker. `on-site`,
`on site`, `WFH` and `work from home` are recognized. Conflicting or simply
negated markers remain unknown and cannot be replaced by a generic fallback.
This is not a general natural-language negation parser.

An independent generic `work_type` can supply a missing mode. Supported generic
text consists of mode markers, punctuation and optional employment words:
`full time`, `part time`, `fixed term`, `contract`, `casual`, `permanent`,
`temporary`, `internship`, `fully`. Thus `Full-time` supplies no mode;
`Full-time, Remote` supplies remote; `Remote NSW` supplies no generic mode
because it has a geographic restriction. Explicit per-location modes win.

`parse_target(text) -> dict` accepts one supported postcode, state abbreviation
or full name, known city or unique locality, including optional qualifiers. It
includes the original `raw`, precision and reference provenance. Blank input,
unsupported postcodes, conflicting fields, ambiguous localities, countries,
work-mode markers and multiple locations raise a user-readable `ValueError`.
To clear geography, pass `target=None` to `classify`; a blank target is an
input error rather than silently clearing the user's filter.

`classify(location, target=None, work_mode='any') -> str` classifies exactly
one item. Parent code must select matching locations before aggregating jobs
or choosing an action scope. Work mode must be `any`, `remote`, `hybrid` or
`onsite`; other values raise `ValueError`. A-style dictionaries containing
only `state`, `postcode` or `city` are accepted as targets; an empty target
dictionary also clears geography.

- `match`: sufficient geographic evidence and a compatible explicit mode if
  one was requested. With no geographic or mode filter every item is `match`,
  including unknown items.
- `related`: geography is compatible but coarser, metro membership is unknown,
  a cross-state set only partly overlaps, or the mode is unknown on an
  otherwise matching item. A bare postcode is broader than a target locality.
- `unknown`: location evidence is unresolved, ambiguous or conflicting under
  an active geographic filter. Raw evidence remains available.
- `hidden`: an established state/postcode/name or explicit mode excludes this
  item. An explicit incompatible mode also hides unknown geography.

A city is broader than a postcode; a locality and a same-state city remain
related without verified metro membership. Remote mode does not remove stated
state restrictions. Clearing geography while retaining a mode still applies
that mode; clearing both returns `match` for every item. The A aggregation
order for the parent is `match`, `related`, `unknown`, then `hidden` only when
all locations are hidden. A job-level aggregate must not supply the location
scope for an edit.

## Reproducing the seed

The following in-memory transformation reproduces the TSV for the same upstream
bytes. It writes no files. GeoNames changes over time: compare archive/readme
hashes with the manifest before treating a new download as the same snapshot.
A deliberate refresh must update provenance, seed hash, version and tests
together. Runtime loading checks the bundled seed hash and schema; a broken
installation raises rather than silently becoming an empty reference.

```python
import csv, hashlib, io, urllib.request, zipfile

base = "https://download.geonames.org/export/zip/"
with urllib.request.urlopen(base + "AU.zip", timeout=45) as response:
    archive = response.read()
with urllib.request.urlopen(base + "readme.txt", timeout=45) as response:
    readme = response.read()
print("AU.zip", hashlib.sha256(archive).hexdigest())
print("readme.txt", hashlib.sha256(readme).hexdigest())
source = zipfile.ZipFile(io.BytesIO(archive)).read("AU.txt")
rows = list(csv.reader(io.StringIO(source.decode("utf-8")), delimiter="\t"))
states = {"ACT", "NSW", "NT", "QLD", "SA", "TAS", "VIC", "WA"}
assert all(len(r) == 12 and r[0] == "AU" and r[4] in states
           and len(r[1]) == 4 and r[1].isascii() and r[1].isdigit()
           for r in rows)
triples = sorted({(r[1], r[2], r[4]) for r in rows})
seed = ("postcode\tlocality\tstate\n" +
        "".join("\t".join(row) + "\n" for row in triples)).encode("utf-8")
print("seed", len(triples), hashlib.sha256(seed).hexdigest())
```

## Verification and delivery

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/test_locations.py
```

The tests block network/downloads and SQLite access. Inputs are newly written
synthetic strings; assertions against the bundled GeoNames seed check public
reference relations and integrity. Coverage includes both A Remote failures,
unknown/fallback modes, geographic restrictions in work type, ambiguity,
leading zeros, unsupported/conflicting targets, cross-state postcodes, mixed
precision, raw preservation, comma grouping, filter clearing, A-style target
compatibility, broken-reference failure and per-location selection. They do not
establish accuracy for arbitrary job prose, completeness
of GeoNames, actual office locations, street-address geocoding, metro boundaries,
distance, production data or end-to-end UI/API behavior.

The module has no persistence, schema, query, HTTP or UI responsibilities.
Those are covered separately by the location state, HTTP and panel checks in
the explicit [public runner](public-tests.md). See the
[location workflow](location-workflow.md) for storage and upgrade behavior.
The Git and Docker allowlists explicitly include only the two bundled reference
files under `jobs/data/`; runtime databases and private exports stay excluded.
