# Coverage

130 original PNGs: 68 desktop, 58 phone, 4 tablet; 74 English, 56 Chinese;
71 light, 59 dark. All show application source
`eb56c4fef036daebd48e0723acf4f7468cc2e0f3` on synthetic data.

## A. Main views — 40

Recommended, All, New, Excluded and Labelled × en/zh × light/dark × desktop
1440x1000 / phone 390x844. These are first-screen viewport captures. Full-page
companions were unnecessary: the list/detail panes scroll internally, so a
full-page capture would equal the viewport shot.

## B. Settings — 32

Skills, Display, Fetching & updates, and Eligibility & rules × en/zh ×
light/dark × desktop/phone. Display includes keyboard shortcut profiles;
rule settings shows the last analysis configuration and next-run rule controls.
Fetching settings shows a valid synthetic configuration with all sources disabled.
Long pages are captured at their first viewport, not as full-page documentation.

## C. Job detail — 21

Retained (`linkedin:DEMO-013`), excluded (`indeed:MOCK-106`) and labelled
(`seek:MOCK-101`) examples in both languages and desktop/phone layouts, plus
six scrolled-to-description companions. Extras cover applied status, clearance
exclusion and a posting without a captured description. Evidence text remains
original English; labels, status, priority and translated note tags use the
current panel. Phone labels stay in the drawer, separately captured in group E.

## D. Interactions and edge cases — 25

Search hit/no results, combined To apply + Python filters, expanded filters,
independent priority queue, long title/detail, skill search, four tablet views,
English/Chinese note suggestions, picking/saving notes, multi-tag notes before
and after reload, To apply/Skipped states, the updated Labelled list, and adding
one synthetic skill. Skipped is a neutral progress state, not an eligibility
verdict. Saved note text does not create a priority star.

Skill alias editing and every scroll position are not separate scenes.
Missing salary and long-note examples are included in ordinary views/details.

## E. Location search and phone drawers — 12

Melbourne capital search, postcode 2000 search, invalid-location guidance and
location suggestions, each on an English/light desktop and Chinese/dark phone;
then filter and label drawers on English/light and Chinese/dark phones. The
label drawer shows progress, priority, notes and the optional correction area.

## Checks and limits

- Every original's SHA256, byte count, PNG integrity and expected pixel dimensions
  were checked; all 130 have matching thumbnails. Ten contact sheets cover the set.
- Document-level horizontal overflow is false for all 130 captures; no page script
  errors were recorded. All contact sheets were visually reviewed and selected
  originals were inspected at full size.
- The header reads current synthetic batch/terminal-state fields, with a matching
  generation. This is a seeded success scenario, not a real collection run.
- Captures use the normal panel, with no Demo banner. Writes affect only the mock.
- Phone/tablet are viewport emulations, not physical devices. Screenshots are
  presentation evidence; they do not establish all interaction races, live source
  access, other browsers or production deployment.
