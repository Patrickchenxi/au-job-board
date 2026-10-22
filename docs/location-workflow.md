# Locations and human records

The panel supports Australian regions and postcode areas using bundled offline
reference data. It keeps the source text, reference version and precision.
A city is not its CBD postcode; a point is not an office address. Unknown and
coarse results remain visible in separate groups. A clear mismatch is hidden
only for the current filter. Clearing filters recovers the source records.
See [data provenance and limitations](location-data.md).

Use Region for a state, city, postcode or unambiguous locality. Work mode is
separate: Remote, Hybrid or Onsite. Each source location owns its own mode;
Remote in one state cannot establish Remote eligibility in another. Unknown
modes remain uncertain rather than being guessed. Full-time/part-time is not
an office/remote mode. Suburb-to-metropolitan-area membership is not inferred
from postcode prefixes or approximate coordinates.

Without a region/mode filter, the existing group summary remains compatible.
Inside a specific source/location, actions, priority, qualification corrections
and notes belong to that stable location. Old group records remain separately
visible as historical reference, with their original scope unconfirmed. They
are not copied into a different location's current judgment. A location can
therefore be unconfirmed even if the historical group was processed.

Choose a location in the detail pane before editing. The default in a filtered
list is a matching location. Switching location waits for in-flight edits and
protects drafts, including when the source UID stays the same. A source spelling
change creates/retains a distinct location when identity cannot be proved;
annotated historical locations remain reachable in the selector. Reordering
source locations does not move the human records.

Location corrections are explicit and reversible. They override parsed data;
ordinary upserts refresh only derived values, not the correction or human
state. Original text and correction history remain available. Unknown source
locations can be corrected to a known Australian place. Ambiguous corrections
must be made more specific; they are not silently accepted as precise.

`label --export` retains the legacy CSV/Markdown files and also writes
`location-records.json`: stable location identity, fields including explicit
null/false, location corrections and audit events. These are private runtime
exports, not public fixtures. The panel's unfiltered Labelled view also retains
sources with location records so removing the region filter does not make
those edits unreachable. The existing CLI edit commands continue to address
legacy UID records; use the panel for location-specific edits.

## Upgrade and recovery

The database version is 2. Opening a schema-1 installation adds location
identities and empty independent scope records in one transaction; it does not
replay the earlier label conversion or assign guessed location scopes to old
human records. Schema 0 runs its existing protected label upgrade first. A
failed upgrade rolls back the schema additions and version publication. Reopen
is idempotent. Versions newer than the program are rejected.

Back up the database consistently before an upgrade, including committed WAL
contents through SQLite's backup API. Keep the old immutable snapshot and the
matching old program. An older program must not write a version-2 database.
After new human edits, preserve the upgraded database and new exports before
any recovery; never overwrite them with a pre-upgrade snapshot. The older
program can be used only against a separate matching old snapshot. These are
recovery constraints, not authorization to operate a production installation.
