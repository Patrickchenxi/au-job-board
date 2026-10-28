"""Small POSIX/Windows shims, so the rest of the package keeps one code path.

Only what the package actually uses is covered:

* ``lock_exclusive(handle, blocking)`` -- an exclusive advisory lock on an open
  file. POSIX uses ``fcntl.flock``; Windows locks byte 0 with ``msvcrt.locking``.
  Both are released when the handle is closed. A non-blocking attempt that finds
  the lock held raises ``BlockingIOError`` on every platform.
* ``fchmod(fd, mode)`` -- ``os.fchmod`` where it exists. Windows (Python < 3.13)
  has none, and POSIX permission bits do not apply there, so it is a no-op.
* ``inheritable_lock_arg`` / ``open_inherited_lock`` -- pass an open lock file to
  a child process: a file descriptor via ``pass_fds`` on POSIX, an inheritable OS
  handle on Windows (which has no ``pass_fds``).
* ``kill_process_tree(process)`` -- SIGKILL to the child's process group on POSIX
  (it is started with ``start_new_session``); ``Process.kill`` on Windows.
"""
from __future__ import annotations

import os
import signal
import subprocess
import time

WINDOWS = os.name == "nt"

if WINDOWS:
    import msvcrt
else:
    import fcntl


def lock_exclusive(handle, *, blocking: bool = True) -> None:
    if not WINDOWS:
        flags = fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB
        fcntl.flock(handle, flags)
        return
    fd = handle.fileno()
    # msvcrt.locking acts at the current file position; always lock byte 0.
    position = os.lseek(fd, 0, os.SEEK_CUR)
    os.lseek(fd, 0, os.SEEK_SET)
    try:
        while True:
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                return
            except OSError as error:
                if not blocking:
                    raise BlockingIOError(error.errno, "lock is held by another process") from None
                time.sleep(0.1)
    finally:
        os.lseek(fd, position, os.SEEK_SET)


def fchmod(fd: int, mode: int) -> None:
    if hasattr(os, "fchmod"):
        os.fchmod(fd, mode)


def has_alarm() -> bool:
    """SIGALRM / setitimer exist (POSIX only)."""
    return hasattr(signal, "SIGALRM") and hasattr(signal, "setitimer")


def inheritable_lock_arg(handle) -> tuple[str, dict]:
    """(command-line value, extra Popen kwargs) for handing ``handle`` to a child."""
    if not WINDOWS:
        return str(handle.fileno()), {"start_new_session": True, "pass_fds": (handle.fileno(),)}
    os_handle = msvcrt.get_osfhandle(handle.fileno())
    os.set_handle_inheritable(os_handle, True)
    return str(os_handle), {
        "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP,
        "startupinfo": subprocess.STARTUPINFO(lpAttributeList={"handle_list": [os_handle]}),
    }


def open_inherited_lock(value: int):
    """Child side of ``inheritable_lock_arg``: a new file object for the inherited lock."""
    fd = msvcrt.open_osfhandle(value, os.O_RDWR) if WINDOWS else os.dup(value)
    return os.fdopen(fd, "a+")


def kill_process_tree(process) -> None:
    if WINDOWS:
        process.kill()
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
