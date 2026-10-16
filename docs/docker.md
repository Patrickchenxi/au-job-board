# Optional Docker installation

**macOS users should prefer the [source installation](install.md).** It is the
primary macOS workflow and retains the optional launchd templates. Docker is an
alternative for people who already use a Docker Engine and Compose v2. It does
not replace source installation or add a scheduler. The image is built locally;
this repository does not require a published container image.

The verification record in [installation-verification.md](installation-verification.md)
states the container architecture actually tested. Do not assume Windows, other
architectures or native Linux source installations have been verified from a
container check. Docker Desktop on macOS runs Linux containers in a VM.

## Build and start

From a new source checkout with Docker Engine running:

```bash
docker compose build
docker compose up -d
docker compose logs panel
# Open http://127.0.0.1:8090/ and /settings
```

Building downloads the Python base image and dependencies. Starting the panel
does **not** fetch listings. On the first start the entrypoint copies only the
public example configuration and skill vocabulary into the persistent config
volume. Existing files are never replaced, including invalid files that need
repair. Confirm your own keywords, locations, sources and rule profile in
Settings before starting an update. Saving settings applies to the next run;
it does not fetch or recompute existing results.

The panel has no authentication. Compose publishes only `127.0.0.1:8090`.
The container explicitly opts in to listening on `0.0.0.0` **inside its network
namespace** with `JOBS_CONTAINER=1`. Source launches keep the wildcard-address
guard. Do not change the host publish address to a wildcard, use host networking
or expose the container port publicly without your own protected access layer.
Keep the host and container ports equal: the local write endpoints validate the
request port against the listener. To use another port, change both the Compose
port mapping and its panel command together.

## Run commands and stop

The entrypoint supplies the persistent config and vocabulary to the normal
`jobs.cli`. One-off commands share the panel's volumes and run lock:

```bash
docker compose run --rm panel status       # offline
docker compose run --rm panel analyze      # offline; keeps manual labels/notes
docker compose run --rm panel report       # offline
docker compose run --rm panel run          # NETWORK: fetch/details/analyze/report
docker compose stop                       # stop the panel
docker compose up -d                      # start it again
```

Choose explicitly whether to run a network update. The panel's update icon also
starts the full pipeline. Do not use `docker compose run --service-ports` for
one-off commands. No cron/launchd/container scheduler is installed. If you choose
your own scheduler later, use the same Compose project and volumes so scheduled
and manual updates coordinate through the shared lock.

Compose uses an init process and the entrypoint `exec`s Python, so stop signals
reach the application. `docker compose stop` stops the panel and its container;
a separately started `compose run` worker is a different container and must be
stopped separately. Wait for updates to finish before routine upgrades/backups.
An interrupted update is not proof of full success; inspect the latest task in
Settings before deciding to rerun it.

## Persistence and permissions

| Named volume | Container directory | Contents |
|---|---|---|
| `configuration` | `/app/config` | `config.yaml`, `skills.yaml`, `skills.local.yaml`, settings save files |
| `data` | `/app/data` | SQLite database **and WAL/SHM**, `.jobs.db.panel-update/` with shared `run.lock`, task state and private config snapshots |
| `reports` | `/app/out` | Generated reports |

The entire configuration directory is mounted, allowing atomic config
replacement. The entire data directory is mounted, keeping SQLite sidecars,
the CLI lock and panel state together. Mounting only `jobs.db` or only
`config.yaml` breaks these guarantees. Keep the default database/report/skills
paths, or ensure any replacement paths also live in persistent writable mounts.

The process runs as non-root `10001:10001`. New named volumes inherit writable
directories from the image. If you replace them with bind mounts, create the
directories first and grant that UID/GID write access (including the parent
directories needed for atomic config saves). Do not solve a permission error
with world-writable permissions. Source-installed paths and container paths
are different; an existing host config must be adapted before use in a container.

For uncommon fields that Settings does not expose, export the config to an
ignored local directory, edit it, then copy it back as the application user.
Stop all updates first; keep a backup and do not edit simultaneously in Settings.

```bash
mkdir -p out/docker-backup
docker compose cp panel:/app/config/config.yaml out/docker-backup/config.yaml
# Edit out/docker-backup/config.yaml; keep /app/data, /app/out and /app/config paths.
docker compose exec -T panel python -c 'from pathlib import Path; import sys; Path("/app/config/config.yaml").write_bytes(sys.stdin.buffer.read())' < out/docker-backup/config.yaml
docker compose restart panel
```

That direct maintenance write is not the browser's validated save endpoint;
validate your YAML and preserve private unknown fields. The settings form itself
checks versions, validates allowed fields and writes atomically.

## Upgrade and backup

```bash
# After updates have finished, update your source checkout as appropriate.
docker compose build
docker compose up -d --force-recreate
```

Recreating containers keeps the named volumes. `docker compose down` also keeps
them; **`docker compose down -v` deletes them**, including your manual notes.
Do not use it as an upgrade step. Keep the same Compose project name/directory,
or explicitly retain its volume names, to reuse existing data.

Before backing up, stop the panel and **all** one-off/scheduled worker
containers that share the volumes. Then copy all three directories from the
stopped panel container before removing it:

```bash
docker compose stop
mkdir -p out/docker-backup
docker compose cp panel:/app/config out/docker-backup/config
docker compose cp panel:/app/data out/docker-backup/data
docker compose cp panel:/app/out out/docker-backup/reports
```

Use a fresh backup directory for each backup. Preserve the DB, sidecars and
manual notes together; protect these files as private. Restore into writable
volumes owned by UID/GID 10001:10001 before starting any process. Test a restored
copy before relying on a backup. Exporting container data is not a deployment
or migration instruction for another machine.

## Offline synthetic verification

For contributors, `tools/test_docker.py` builds the local image and exercises
synthetic jobs with the network disabled at container runtime. It uses its own
temporary volumes/containers, checks the panel, persistence and shared lock,
then removes only its generated resources. This is separate from a real fetch
and from the public source tests. Read its output for the tested architecture
and any failed check; it never reads your normal Compose volumes.

The strict `.dockerignore` allowlist excludes personal config, databases,
reports, `.git`, screenshots and tests from the build context. Runtime volumes
are private data and are not image content. Never publish them with the image.
