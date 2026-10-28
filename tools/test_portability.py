"""Offline checks for jobs.portability: locks, fchmod and lock hand-off to a child.

Runs on POSIX and Windows; only temporary files, no network.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from jobs import portability  # noqa: E402


class Portability(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="portability-")
        self.addCleanup(self.directory.cleanup)
        self.lock_path = Path(self.directory.name) / "run.lock"

    def open(self):
        handle = self.lock_path.open("a+")
        self.addCleanup(handle.close)
        return handle

    def test_second_handle_cannot_take_a_held_lock(self):
        first = self.open()
        portability.lock_exclusive(first, blocking=False)
        second = self.open()
        with self.assertRaises(BlockingIOError):
            portability.lock_exclusive(second, blocking=False)
        first.close()
        portability.lock_exclusive(second, blocking=False)

    def test_fchmod_accepts_a_real_descriptor(self):
        handle = self.open()
        portability.fchmod(handle.fileno(), 0o600)   # no-op where os.fchmod is missing

    def test_lock_handed_to_child_stays_held(self):
        held = self.open()
        portability.lock_exclusive(held, blocking=False)
        value, spawn = portability.inheritable_lock_arg(held)
        spawn.pop("start_new_session", None)
        script = """
import sys
sys.path.insert(0, sys.argv[1])
from jobs import portability
inherited = portability.open_inherited_lock(int(sys.argv[2]))
other = open(sys.argv[3], 'a+')
try:
    portability.lock_exclusive(other, blocking=False)
except BlockingIOError:
    print('held')
else:
    print('free')
inherited.close()
"""
        child = subprocess.run([sys.executable, "-B", "-c", script, str(ROOT), value, str(self.lock_path)],
                               capture_output=True, text=True, timeout=15,
                               env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, **spawn)
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertEqual(child.stdout.strip(), "held")


if __name__ == "__main__":
    unittest.main()
