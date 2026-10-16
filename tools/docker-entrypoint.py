"""Seed a new container's persistent directories, then exec the ordinary CLI.

Only public examples are copied. Existing files, including empty or invalid
configuration, are left for the user to repair rather than silently replaced.
"""
from pathlib import Path
import os
import sys
import tempfile
from io import StringIO

from ruamel.yaml import YAML


def create_if_absent(path, content):
    """Publish a complete private file without overwriting a concurrent seed."""
    descriptor, temporary = tempfile.mkstemp(prefix=".seed-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
        try:
            os.link(temporary, path)
        except FileExistsError:
            pass
    finally:
        os.unlink(temporary)


def main():
    root = Path("/app")
    config_dir = root / "config"
    config_path = config_dir / "config.yaml"
    skills_path = config_dir / "skills.yaml"
    try:
        for name in ("config", "data", "out"):
            (root / name).mkdir(exist_ok=True)
        if not skills_path.exists():
            create_if_absent(skills_path, (root / "skills.yaml").read_text(encoding="utf-8"))
        if not config_path.exists():
            yaml = YAML(typ="rt")
            config = yaml.load((root / "config.example.yaml").read_text(encoding="utf-8"))
            config["db_path"] = "/app/data/jobs.db"
            config["report"]["out_dir"] = "/app/out"
            config["skills_path"] = str(skills_path)
            stream = StringIO()
            yaml.dump(config, stream)
            create_if_absent(config_path, stream.getvalue())
    except OSError:
        print("Cannot initialize /app/config, /app/data or /app/out. "
              "Volumes must be writable by UID:GID 10001:10001; existing files "
              "were not replaced.", file=sys.stderr)
        return 1
    args = sys.argv[1:] or ["panel", "--host", "0.0.0.0", "--port", "8090"]
    os.execvp(sys.executable, [sys.executable, "-m", "jobs.cli", "--config",
                             str(config_path), "--skills", str(skills_path), *args])


if __name__ == "__main__":
    raise SystemExit(main())
