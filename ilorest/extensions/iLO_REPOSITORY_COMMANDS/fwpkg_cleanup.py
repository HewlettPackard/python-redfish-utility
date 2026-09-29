# ##
# Copyright 2016-2021 Hewlett Packard Enterprise, Inc. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ##

# -*- coding: utf-8 -*-
"""Resilient temporary-directory cleanup helpers for fwpkg upload/flash flows.

On Windows the extracted fwpkg files (for example the ``sum\\tmp...`` staging
directory) can still be locked by the OS, an antivirus scanner, or the SUM
component immediately after a successful upload. A plain :func:`shutil.rmtree`
then raises ``PermissionError: [WinError 5]`` and turns an otherwise successful
upload into a failure. This module centralizes a retry-then-tolerate cleanup so
a transient lock never fails the command. Cleanup failures are recorded at DEBUG
level only (log file), so stdout/stderr output is never changed.
"""

import os
import platform
import shutil
import stat
import tempfile
import time

try:
    from rdmc_helper import LOGGER
except ImportError:
    from ilorest.rdmc_helper import LOGGER

# NOTE: Defaults chosen to give the OS/antivirus/SUM a brief window to release
# file handles without noticeably slowing down the happy path.
DEFAULT_CLEANUP_RETRIES = 3
DEFAULT_CLEANUP_DELAY = 0.5

# ESXi reports "VMkernel" as its OS name (os.uname().sysname / platform.system()).
ESXI_SYSNAME = "VMkernel"
# Persistent, writable scratch area on ESXi. Using a dir iLORest owns avoids
# nesting the fwpkg staging tree inside SUM's inherited $TMPDIR (which lives on
# a locked VMFS/vfat mount where an in-use subtree cannot be removed).
ESXI_SCRATCH_TMP = "/scratch/hpe_ilorest/tmp"


def _is_esxi():
    """Return True when running on VMware ESXi (VMkernel), else False."""
    try:
        return platform.system() == ESXI_SYSNAME
    except OSError:
        # Reason: platform.system() can fail in exotic environments; treat any
        # failure as "not ESXi" so temp-dir selection degrades to the default.
        return False


def create_fwpkg_tempdir():
    """Create a temporary directory for fwpkg extraction, ESXi-aware.

    On ESXi, prefer a directory iLORest owns under the persistent, writable
    ``/scratch`` partition instead of inheriting SUM's ``$TMPDIR`` (which
    resolves to a locked VMFS/vfat mount whose in-use subtrees cannot be
    removed). On every other platform, and whenever the ESXi scratch area is
    unavailable or not writable, fall back to the standard temp location.

    Returns:
        Absolute path to a newly created temporary directory. The caller owns
        the directory and is responsible for removing it (see
        :func:`safe_rmtree`).
    """
    if _is_esxi():
        try:
            os.makedirs(ESXI_SCRATCH_TMP, exist_ok=True)
            if os.access(ESXI_SCRATCH_TMP, os.W_OK):
                return tempfile.mkdtemp(dir=ESXI_SCRATCH_TMP)
            LOGGER.debug(
                "ESXi scratch temp dir '%s' is not writable; using default temp location.",
                ESXI_SCRATCH_TMP,
            )
        except OSError as exc:
            # Reason: /scratch may be read-only or missing on some ESXi hosts;
            # fall back silently (DEBUG only) so behavior is never worse than
            # the previous default.
            LOGGER.debug(
                "Could not prepare ESXi scratch temp dir '%s': %s. Using default temp location.",
                ESXI_SCRATCH_TMP,
                exc,
            )
    return tempfile.mkdtemp()


def _clear_readonly_and_retry(func, path, _exc_info):
    """``onerror`` handler for :func:`shutil.rmtree`.

    Makes the failed path removable and retries the operation once. This covers
    two cross-platform cases:

    * **Windows** - a read-only file is reported as access-denied; clearing the
      read-only bit lets it be unlinked.
    * **POSIX (RHEL/SLES/Ubuntu/Debian/macOS)** - a directory missing its owner
      write/execute bits cannot be traversed or removed.

    The owner read/write/execute bits are OR-ed onto the *existing* mode rather
    than overwriting it, so a directory never loses its execute (traverse) bit -
    overwriting with a write-only mode would break recursion on POSIX. Any
    remaining error is re-raised for the caller's retry loop to handle.

    Args:
        func: The operation that failed (``os.unlink``, ``os.rmdir``, etc.).
        path: The path the operation was attempting to remove.
        _exc_info: Unused exception info tuple provided by ``shutil.rmtree``.
    """
    try:
        current_mode = os.stat(path).st_mode
        os.chmod(path, current_mode | stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
    except OSError:
        # Reason: if stat itself fails, fall back to the Windows read-only fix.
        os.chmod(path, stat.S_IWRITE)
    func(path)


def safe_rmtree(path, retries=DEFAULT_CLEANUP_RETRIES, delay=DEFAULT_CLEANUP_DELAY):
    """Remove a directory tree without letting cleanup failures raise.

    Retries a few times to let a transient file lock (antivirus, SUM, or the
    OS) release, clearing the read-only bit on the way. If the tree still
    cannot be removed, the failure is recorded at DEBUG level (log file only,
    never stdout/stderr) and ``False`` is returned instead of propagating the
    exception, so a locked temp file never fails an otherwise successful upload
    or flash and never alters command output.

    Args:
        path: Directory tree to remove. ``None`` or a missing path is a no-op.
        retries: Number of removal attempts before giving up.
        delay: Seconds to wait between attempts.

    Returns:
        ``True`` if the path was removed (or did not exist), ``False`` if it
        could not be removed after all retries.
    """
    if not path or not os.path.exists(path):
        return True

    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            shutil.rmtree(path, onerror=_clear_readonly_and_retry)
            return True
        except OSError as exc:
            # Reason: PermissionError (WinError 5) is the observed failure, but
            # any OSError during cleanup should be tolerated rather than fail
            # the command. Logged at DEBUG only so stdout/stderr are unchanged.
            last_exc = exc
            LOGGER.debug(
                "Attempt %d/%d to remove temporary path '%s' failed: %s",
                attempt,
                retries,
                path,
                exc,
            )
            if attempt < retries:
                time.sleep(delay)

    LOGGER.debug(
        "Unable to remove temporary path '%s' after %d attempts: %s. " "Continuing without failing the operation.",
        path,
        retries,
        last_exc,
    )
    return False
