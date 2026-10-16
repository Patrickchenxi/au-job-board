# Fetch settings and manual updates

Open **Settings → Fetching & updates** to inspect the search terms, source
switches, locations and fetch limits. This is a read-only view of the configuration
file used to start the panel. Refresh the settings page after editing that file.
Source defaults are shown explicitly, including sources enabled by default when
their section is omitted.

The **Profile used by the last successful analysis** is separate. Editing the
configuration does not reprocess the jobs already on screen.

## Update from the panel

**Update jobs** runs the existing `fetch → details → analyze → report` pipeline
in a background process. It contacts the configured sources and writes to your
database and report directory. Opening the panel, viewing settings or checking
status does not fetch anything. The standalone synthetic demo disables this
button; it never falls back to a real configuration.

The panel rereads and validates the configuration before starting an update,
then writes a private snapshot for that run. Later edits to the configuration
file do not change an update already in progress. The rules and skill vocabulary
remain files read by the existing pipeline; do not edit them during an update.

If the database, report directory or vocabulary target changes, reload the panel
with the intended configuration before updating. This prevents the panel from
displaying one database while the worker updates another. Explicit CLI
`--config`, `--rules` and `--skills` paths are retained.

You can browse and save labels or notes during an update. The page does not
automatically reload or replace the detail editor. Use **Refresh results** when
ready; it reloads the current view and filters. Save your note before choosing
that link, just as before any manual page refresh.

## Understand the result

| Status | Meaning |
|---|---|
| Running | A background update is active; its current step is shown. |
| Completed | All steps finished without a failure detected by the adapters or pipeline. |
| Partially completed | A source/query failed or some queued details were not filled; the remaining steps completed. Some data may have been written. |
| Failed | A step failed or the worker did not produce a valid completion result. Completed earlier steps may already have written data. |
| Timed out | The update exceeded its 30-minute limit. Earlier writes are retained. |
| Another update is running | The shared full-pipeline lock is held, including by a scheduled run. This attempt did not run concurrently; retry later. |
| Interrupted | A recorded update has no live worker lock or trustworthy completion result. Check the data before retrying. |

Counts distinguish listings returned, new records, existing records updated and
details filled. They are not the total number of jobs in the database or a
guarantee that every source returned every matching job. An upstream library may
return an empty result without exposing its own internal failure; the panel can
only report failures visible to this project's adapters.

The same checkout's manual and scheduled full `run` commands share the existing
`data/run.lock`. Separate checkouts and individual `fetch`, `details` or
`analyze` commands are not covered by that lock; avoid running those concurrently.
There is no queue, cancel button, automatic retry or whole-database rollback.
Manual labels and notes are not rebuilt by analysis.

## Process and local storage

Refreshing or closing a browser tab does not stop the worker. A restarted panel
can observe the inherited worker lock and its recorded result. If the panel
process crashes, the existing worker may continue until it exits or reaches its
own CLI timeout; restarting the panel does not promise to resume or restart it.
The active panel also enforces a deadline and reaps its worker on timeout.

Private state and the temporary configuration snapshot live beside the database
in `.<database-filename>.panel-update/`. The directory is created only when an
update is requested, with owner-only permissions. The snapshot is normally
removed after the worker exits; a panel crash may leave it behind. Treat this
directory as private alongside the database, especially if you put the database
outside the ignored `data/` directory. Do not add it to Git or a public archive.

This implementation retains the existing macOS/POSIX lock and signal behavior.
The panel still has no authentication; keep it on loopback. The update endpoint
requires JSON and checks the request host and browser origin. That check is not
authentication and does not extend to the older label/skill endpoints. See
[safety-and-sources.md](safety-and-sources.md).
