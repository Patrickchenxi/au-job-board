# Optional Docker installation

**macOS users should prefer the [source installation](install.md).** It is the
primary macOS workflow and retains the optional launchd templates. Docker is an
alternative for people who already use a Docker Engine and Compose v2. It does
not replace source installation or add a scheduler. You can use the public
`ghcr.io/skywingjam/au-job-board` image or build it locally.

The verification record in [installation-verification.md](installation-verification.md)
states the container architecture actually tested. Do not assume Windows, other
architectures or native Linux source installations have been verified from a
container check. Docker Desktop on macOS runs Linux containers in a VM.

## Pull a published image

The published image supports `linux/amd64` and `linux/arm64`. Docker selects the
matching platform. Use a version tag for a specific release (for example
`v1.2.2`), `sha-<full-main-commit>` for a specific main build, or `latest` for
the most recently published main build. A digest pins the exact image content.
Publication requires the synthetic container smoke test on each native platform;
it does not test real job sources or other operating systems.

From a source checkout, use the image overlay with the existing Compose file:

```bash
export AU_JOB_BOARD_IMAGE=ghcr.io/skywingjam/au-job-board:v1.2.2
docker compose -f compose.yaml -f compose.image.yaml pull
docker compose -f compose.yaml -f compose.image.yaml up -d --no-build
docker compose -f compose.yaml -f compose.image.yaml logs panel
# Open http://127.0.0.1:8090/ and /settings
```

The overlay only selects an image; it keeps the same service, ports, volumes
and Compose project. Continue using both `-f` arguments for image-based commands
and upgrades. `AU_JOB_BOARD_IMAGE` defaults to `latest` if unset. Anonymous pulls
require the GHCR package to have public visibility.

## Build locally and start

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

For a published-image installation, after updates have finished, select the
new version and recreate the panel without building:

```bash
export AU_JOB_BOARD_IMAGE=ghcr.io/skywingjam/au-job-board:v1.2.2
docker compose -f compose.yaml -f compose.image.yaml pull
docker compose -f compose.yaml -f compose.image.yaml up -d --no-build --force-recreate
```

For a local build, update the source checkout and rebuild:

```bash
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

## Maintainer image workflow

The `Docker image` GitHub Actions workflow automatically builds only on pushes
to `main`, including merged PRs. It does not build for PRs, `dev` or tag pushes.
Manual runs also require the `main` ref; other refs skip the Docker jobs.

With an empty `release_tag`, the workflow builds on native amd64 and arm64
Ubuntu runners, runs `tools/test_docker.py --no-build` with isolated synthetic
volumes and no runtime network, then publishes the tested platform images.
Only after both pass does it publish the combined `sha-<full-commit>` and
`latest` tags. Platform staging tags end in `-amd64` / `-arm64`.

To publish a version, first wait for that main build and the public source CI
to pass, create the matching Git tag/Release, then manually run `Docker image`
on `main` with `release_tag` set to the existing `vX.Y.Z` tag. The tag must
point to that exact main commit. This adds a version tag to the existing tested
multi-platform image without rebuilding or moving `latest`. Repeating the
operation accepts the same image but rejects replacing a different version image.

Authentication uses `GITHUB_TOKEN` with job-scoped `packages: write`; no Docker
Hub account or additional registry secret is needed. On first publication, GHCR
defaults the package to private: change the package visibility to public in its
GitHub package settings and verify an anonymous pull. Preserve that visibility
for later versions. See [GitHub's Container registry documentation](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry).

The workflow uses the public source context and the Dockerfile allowlist. It
does not deploy a service or migrate an existing source installation to Docker.
