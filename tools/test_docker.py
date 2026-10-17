"""Opt-in Docker smoke test with fictional data and no runtime network.

Run from the repository: python3 tools/test_docker.py [--no-build]. Docker
Engine is required. This is intentionally separate from offline source tests.
The product image never includes this test or its source-adapter mock.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import uuid


def install_mock():
    """Installed through a read-only, test-only sitecustomize mount."""
    import jobs.sources
    from jobs.sources import blank_job

    def fetch(config, queries):
        delay = float(os.environ.get("JOBS_TEST_SLEEP", "0"))
        if delay:
            time.sleep(delay)
        job = blank_job("seek", "docker-fictional-1")
        job.update(title="Fictional Software Engineer", company="Example Test Company",
                   location="Melbourne VIC", url="https://example.invalid/docker-test",
                   description="Fictional Python engineer using SQL. Synthetic test only.")
        return [job]

    jobs.sources.iter_sources = lambda config: iter([("seek", fetch)])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-build", action="store_true")
    options = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    tag = "au-job-board:local"
    prefix = "au-jobs-smoke-" + uuid.uuid4().hex[:12]
    containers, volumes = [], []

    def docker(*args, check=True):
        result = subprocess.run(["docker", *args], cwd=root, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if check and result.returncode:
            raise AssertionError(f"docker {' '.join(args[:5])}: {result.stdout}")
        return result

    if not options.no_build:
        # Stream build progress; package installation may take several minutes.
        subprocess.run(["docker", "build", "-t", tag, "."], cwd=root, check=True)
    architecture = docker("image", "inspect", tag, "--format", "{{.Os}}/{{.Architecture}}").stdout.strip()
    print("Testing", architecture, flush=True)
    privacy = docker("run", "--rm", "--network", "none", "--entrypoint", "python", tag,
                     "-c", "import os; from pathlib import Path; assert os.getuid()==10001; "
                     "assert not Path('/app/.git').exists(); assert not Path('/app/config.yaml').exists(); "
                     "assert not Path('/app/skills.local.yaml').exists(); "
                     "assert not list(Path('/app/data').iterdir()); assert not list(Path('/app/config').iterdir()); "
                     "print('non-root, no personal config or runtime data')")
    print("PASS image boundary:", privacy.stdout.strip(), flush=True)
    with tempfile.TemporaryDirectory(prefix=prefix) as temp:
        mock = Path(temp)
        mock.chmod(0o755)  # Container UID 10001 must traverse the read-only test mount.
        (mock / "sitecustomize.py").write_text("import test_docker; test_docker.install_mock()\n")
        (mock / "test_docker.py").write_text(Path(__file__).read_text())
        mounts = ["-v", str(mock) + ":/mock:ro", "-e", "PYTHONPATH=/mock:/app"]
        try:
            for name, target in (("config", "/app/config"), ("data", "/app/data"), ("out", "/app/out")):
                volume = prefix + "-" + name
                docker("volume", "create", volume)
                volumes.append(volume)
                mounts += ["-v", volume + ":" + target]

            def once(*command, check=True):
                return docker("run", "--rm", "--network", "none", *mounts, tag, *command, check=check)

            def detached(suffix, *command, delay=None):
                name = prefix + "-" + suffix
                containers.append(name)
                args = ["run", "-d", "--network", "none", "--init", "--name", name, *mounts]
                if delay is not None:
                    args += ["-e", "JOBS_TEST_SLEEP=" + str(delay)]
                docker(*args, tag, *command)
                return name

            def inside(name, code):
                return docker("exec", name, "python", "-c", code).stdout.strip()

            def wait_for(fn, description, timeout=30):
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    try:
                        value = fn()
                        if value:
                            return value
                    except AssertionError:
                        pass
                    time.sleep(.2)
                raise AssertionError("Timed out waiting for " + description)

            once("status")  # Seeds only public config and skills into fresh volumes.
            once("run")     # Real CLI, sources replaced by fictional records.
            panel = detached("panel", "panel", "--host", "0.0.0.0", "--port", "8090")
            base = "http://127.0.0.1:8090"
            http_prefix = "import urllib.request,json; base=" + repr(base) + "; "

            def get(path):
                return inside(panel, http_prefix + "print(urllib.request.urlopen(base+" + repr(path) + ").read().decode())")

            wait_for(lambda: "Fictional" in get("/?view=all"), "synthetic panel")
            for path in ("/?lang=en", "/?lang=zh", "/settings"):
                assert get(path), path

            def post(path, payload, status=200):
                return inside(panel, http_prefix + "import urllib.error; req=urllib.request.Request(base+" + repr(path) + ",data=" +
                              repr(json.dumps(payload).encode()) + ",headers={'Content-Type':'application/json','Origin':base}); "
                              "\ntry: response=urllib.request.urlopen(req)"
                              "\nexcept urllib.error.HTTPError as error: response=error"
                              "\nassert response.status==" + str(status) + ",response.status"
                              "\nprint(response.read().decode())")

            post("/api/label", {"uid": "seek:docker-fictional-1", "field": "note", "value": "Synthetic durable note"})
            post("/api/skills", {"token": "DockerSmokeFictional", "action": "add"})
            settings = json.loads(get("/api/config-settings"))
            saved = json.loads(post("/api/config-settings", {"digest": settings["digest"],
                                   "changes": {"queries": ["fictional docker engineer"]}}))
            assert saved["values"]["queries"] == ["fictional docker engineer"], saved
            print("PASS panel, synthetic pipeline, note and skill edit", flush=True)

            # Same physical lock inode is shared across containers.
            slow = detached("lock-holder", "run", delay=60)
            wait_for(lambda: "running" in get("/api/update-state"), "shared running task")
            conflict = once("run", check=False)
            assert conflict.returncode == 4, conflict.stdout
            assert json.loads(post("/api/update", {}, status=409))["accepted"] is False
            docker("stop", "--time", "10", slow)
            stopped = docker("inspect", slow, "--format", "{{.State.Running}} {{.State.ExitCode}}").stdout.strip()
            assert stopped.startswith("false "), stopped
            once("run")  # Kernel released the terminated holder's shared lock.
            print("PASS concurrent run rejection, stop signal and lock release", flush=True)

            # Exercise real panel-launched subprocess, state and config snapshot.
            started = json.loads(post("/api/update", {}, status=202))
            assert started.get("accepted") is True, started
            state = wait_for(lambda: (lambda value: value if value.get("state") == "success" else None)(
                json.loads(get("/api/update-state"))), "panel update success")
            assert state.get("refresh_available") is True, state
            before = inside(panel, "from pathlib import Path; import hashlib,json; "
                            "print(json.dumps({str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in "
                            "[Path('/app/config/config.yaml'),Path('/app/config/skills.local.yaml')]}))")
            assert inside(panel, "from pathlib import Path; print(Path('/app/data/.jobs.db.panel-update/run.lock').exists())") == "True"
            assert inside(panel, "import sqlite3; from pathlib import Path; c=sqlite3.connect('/app/data/jobs.db'); "
                          "assert c.execute('pragma journal_mode').fetchone()[0]=='wal'; "
                          "c.execute(\"insert or replace into meta(key,value) values('docker-smoke','fictional')\"); "
                          "c.commit(); print(Path('/app/data/jobs.db-wal').exists())") == "True"
            docker("stop", "--time", "10", panel)
            docker("rm", panel)
            containers.remove(panel)
            panel = detached("panel-recreated", "panel", "--host", "0.0.0.0", "--port", "8090")
            wait_for(lambda: get("/settings"), "recreated panel")
            after = inside(panel, "from pathlib import Path; import hashlib,json; "
                           "print(json.dumps({str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in "
                           "[Path('/app/config/config.yaml'),Path('/app/config/skills.local.yaml')]}))")
            assert before == after
            assert json.loads(get("/api/config-settings"))["values"]["queries"] == ["fictional docker engineer"]
            note = inside(panel, "import sqlite3; conn=sqlite3.connect('/app/data/jobs.db'); "
                          "print(conn.execute(\"select note from labels where uid='seek:docker-fictional-1'\").fetchone()[0])")
            assert "Synthetic durable note" in note, note
            assert json.loads(get("/api/update-state"))["state"] == "success"
            print("PASS recreation keeps config, overlay, DB/manual note and task state", flush=True)
            print("Docker synthetic smoke passed:", architecture, flush=True)
        finally:
            for name in containers:
                docker("rm", "-f", name, check=False)
            for volume in volumes:
                docker("volume", "rm", volume, check=False)


if __name__ == "__main__":
    main()
