# Fetch settings and updates

Open **Settings → Fetching & updates** to read and edit the configuration file
used to start this panel. The structured form supports search terms, source
switches, locations and existing fetch limits, the next-run rule profile, and
individual rule switches. `whv` uses the same rule defaults as `485`; it does not
automatically evaluate legal work rights or employer-duration conditions.

Fields marked **Default** are absent from the file and show the program default.
Rule switches can use their preset default, or explicitly enable/disable a rule.
Paths, credentials, listener settings and unknown configuration keys are not
editable through this form. Skill vocabulary edits still use the skills overlay.

Choose **Review changes**, inspect the before/after values, then save or cancel.
Saving writes the actual configuration file and reads it back. It does not fetch,
analyze, or change the profile shown for the **last successful analysis**. The
next explicitly started update or CLI analysis reads the saved configuration.
Refresh/reload the form to see external YAML edits. A stale form is rejected
instead of overwriting another tab or file edit; failed saves retain the input.
Unsaved changes prompt before leaving, and inputs are frozen while saving.

The editor preserves comments, unknown fields and file permissions, and replaces
the file atomically. It rejects invalid/duplicate YAML keys, aliases, merge keys
and custom tags rather than guessing their meaning. Fix such files manually
before using the form. Use a writable **directory** mount for Docker configuration;
a single-file bind mount cannot be replaced atomically. No configuration backups
or full personal YAML are returned to the browser.

## Update from the panel

The refresh icon beside **Last fetched…** starts the existing
`fetch → details → analyze → report` pipeline in a background process. The
settings page has the detailed update control and latest execution summary.
Opening a page or checking status never fetches. The standalone synthetic demo
keeps network updates and configuration editing disabled.

The panel and CLI take the same database-scoped execution lock before binding a
configuration snapshot. Settings cannot save while this lock is held. An
external YAML edit after startup does not change the parameters of that run.
Do not edit rule/skill files during execution. Changing DB, output or skill paths
requires restarting the panel with the intended configuration, so a displayed
database cannot silently differ from the updated database.

A new result generation automatically reloads a list with no open job. An open
job stays in place until you close it or navigate onward. Switching from A to B
loads the new results at B; page/settings links keep their full target URL.
Filters and pagination remain in the URL and a stable job anchors list scroll
where possible. If filtering removes that anchor or shortens the page count,
the list falls back to an available position. Unsaved notes and saves in progress
remain protected. Modified clicks and new tabs retain normal browser behavior.
Only the tab that started an update receives its completion toast; opening or
refreshing a page never replays an old completion message.

## Understand the result

The latest record is shared by manual updates, full CLI runs and independent
`fetch` commands. A full run's fetch/details/analyze/report steps are one task.
`analyze` or `report` alone does not change the last-fetch time. For an explicitly
identified scheduled invocation, use `run --trigger scheduled`; a plain command
is recorded as CLI, rather than guessing who invoked it. Historical DB records
without trustworthy terminal metadata show an unknown outcome/source.

| Status | Meaning |
|---|---|
| Running | The task is active; available stage and counters are shown. |
| Completed | All requested steps completed without a detected failure. |
| Partially completed | A source/query failed or queued details remain; usable results may exist. |
| Failed | A step failed; earlier writes may remain. |
| Timed out | The execution exceeded its deadline; earlier writes remain. |
| Interrupted | The task received a stop signal or no longer has a live execution lock. |
| Busy | Another task or configuration save holds the shared lock; retry later. |

A failure is never described as a complete fresh update. The summary includes
task identity, trigger, start/end times, outcome and available counts. It retains
the latest failed attempt rather than selecting only successes. Counters are
observations from adapters, not a guarantee that an upstream source returned all
matching jobs. An upstream library can return an empty result without exposing
its internal failure.

## Process and local storage

Closing a tab does not stop a worker. A restarted panel can read the same record.
There is no queue, cancel UI, automatic retry or whole-database rollback. Analysis
preserves manual notes and labels. The CLI's signal/deadline handling records an
interrupted/timed-out outcome when possible; after an abrupt kill, the next state
read identifies a stale running record as interrupted.

Private snapshots, the shared lock, latest task and result generation live beside
the DB in `.<database-filename>.panel-update/`. Preserve this whole directory with
the DB/WAL files; Docker mounts their parent data directory. Separate databases
have separate locks. Individual details/analyze commands do not acquire the
full-run lock; avoid running those manually alongside an update. A crash may
leave a private snapshot; keep this directory out of Git and public archives.

The panel has no authentication. Keep source deployment on loopback, and use the
Docker guide's localhost host binding. The update and configuration write APIs
check JSON, Host and Origin; this is a local browser boundary, not authentication.
See [safety-and-sources.md](safety-and-sources.md).
