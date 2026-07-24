###
# Copyright 2016-2026 Hewlett Packard Enterprise, Inc. All rights reserved.
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
###

# -*- coding: utf-8 -*-
"""Cross-process file lock for serializing TPM/semaphore operations.

The native TPMUtility uses a named POSIX semaphore to serialize TPM access.
When multiple ilorest processes run concurrently, one process's sem_unlink
during disconnect destroys the semaphore for all others, causing 'Access denied'
failures on subsequent login attempts.

This module provides a file-based advisory lock that ilorest processes acquire
BEFORE touching any TPM operation (token_exists, vnic_login, delete_token,
generate_save_token). This ensures only one ilorest process interacts with
the TPM semaphore at a time, preventing the race condition.

Usage as a context manager:
    with TpmFileLock():
        app.token_exists(app_obj)
        app.vnic_login(...)
"""

import logging
import os
import sys
import tempfile
import time

LOGGER = logging.getLogger(__name__)

# Lock file path — placed in /var/run on Linux (writable by root) or temp on Windows
if sys.platform == "win32":
    _LOCK_DIR = os.environ.get("TEMP", tempfile.gettempdir())
else:
    # Prefer /var/run for root processes (typical ilorest usage), fall back to /tmp
    _LOCK_DIR = "/var/run" if os.path.isdir("/var/run") and os.access("/var/run", os.W_OK) else "/tmp"

_LOCK_FILE_PATH = os.path.join(_LOCK_DIR, ".ilorest_tpm.lock")

# Retry configuration for acquiring the file lock
_LOCK_ACQUIRE_TIMEOUT = 30  # seconds
_LOCK_POLL_INTERVAL = 0.1  # seconds between poll attempts


class TpmFileLock:
    """Cross-process advisory file lock for TPM operations.

    Ensures that only one ilorest process at a time performs TPM-backed
    authentication (token_exists, vnic_login, generate_save_token, delete_token).
    This prevents the race condition where concurrent sem_unlink calls destroy
    the named semaphore out from under other processes.

    This is an advisory lock — it only serializes cooperating ilorest processes.
    It does not prevent other programs from accessing the TPM directly.
    """

    def __init__(self, timeout=_LOCK_ACQUIRE_TIMEOUT):
        """Initialize the file lock.

        Args:
            timeout: Maximum seconds to wait for the lock before giving up.
        """
        self._timeout = timeout
        self._lock_fd = None

    def acquire(self):
        """Acquire the cross-process file lock, blocking until available or timeout.

        Raises:
            TimeoutError: If the lock cannot be acquired within the timeout period.
            OSError: If the lock file cannot be created.
        """
        # Release any previously held lock to avoid self-deadlock on double acquire
        if self._lock_fd is not None:
            self.release()

        start_time = time.monotonic()
        LOGGER.debug("Acquiring TPM file lock: %s (timeout=%ds)", _LOCK_FILE_PATH, self._timeout)

        # Open (or create) the lock file
        try:
            self._lock_fd = open(_LOCK_FILE_PATH, "w")
        except OSError as exc:
            LOGGER.warning("Cannot create TPM lock file '%s': %s. Proceeding without lock.", _LOCK_FILE_PATH, exc)
            self._lock_fd = None
            return

        if sys.platform == "win32":
            self._acquire_windows(start_time)
        else:
            self._acquire_posix(start_time)

        elapsed = time.monotonic() - start_time
        LOGGER.debug("TPM file lock acquired in %.3fs", elapsed)

    def _acquire_posix(self, start_time):
        """Acquire lock using fcntl.flock on POSIX systems."""
        import fcntl

        while True:
            try:
                fcntl.flock(self._lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except (IOError, OSError):
                elapsed = time.monotonic() - start_time
                if elapsed >= self._timeout:
                    self._cleanup_fd()
                    raise TimeoutError(
                        f"Could not acquire TPM file lock within {self._timeout}s. "
                        f"Another ilorest process may be holding it."
                    )
                time.sleep(_LOCK_POLL_INTERVAL)

    def _acquire_windows(self, start_time):
        """Acquire lock using msvcrt.locking on Windows."""
        import msvcrt

        while True:
            try:
                # Lock the first byte of the file (advisory)
                msvcrt.locking(self._lock_fd.fileno(), msvcrt.LK_NBLCK, 1)
                return
            except (IOError, OSError):
                elapsed = time.monotonic() - start_time
                if elapsed >= self._timeout:
                    self._cleanup_fd()
                    raise TimeoutError(
                        f"Could not acquire TPM file lock within {self._timeout}s. "
                        f"Another ilorest process may be holding it."
                    )
                time.sleep(_LOCK_POLL_INTERVAL)

    def release(self):
        """Release the cross-process file lock."""
        if self._lock_fd is None:
            return

        try:
            if sys.platform == "win32":
                import msvcrt

                try:
                    msvcrt.locking(self._lock_fd.fileno(), msvcrt.LK_UNLCK, 1)
                except (IOError, OSError, ValueError):
                    pass
            else:
                import fcntl

                try:
                    fcntl.flock(self._lock_fd.fileno(), fcntl.LOCK_UN)
                except (IOError, OSError, ValueError):
                    pass
        finally:
            self._cleanup_fd()

        LOGGER.debug("TPM file lock released")

    def _cleanup_fd(self):
        """Close the lock file descriptor."""
        if self._lock_fd is not None:
            try:
                self._lock_fd.close()
            except (IOError, OSError):
                pass
            self._lock_fd = None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
        return False  # Do not suppress exceptions


def retry_with_backoff(func, max_attempts=3, base_delay=1.0, backoff_factor=2.0, retryable_exceptions=None):
    """Execute a function with exponential backoff retry on transient failures.

    Args:
        func: Callable to execute (no arguments — use a lambda or partial).
        max_attempts: Maximum number of attempts before giving up.
        base_delay: Initial delay in seconds before the first retry.
        backoff_factor: Multiplier applied to delay after each failure.
        retryable_exceptions: Tuple of exception types that should trigger a retry.
            If None, retries on all exceptions except KeyboardInterrupt and SystemExit.

    Returns:
        The return value of func() on success.

    Raises:
        The last exception raised by func() if all attempts fail.
    """
    if retryable_exceptions is None:
        retryable_exceptions = (Exception,)

    last_exception = None
    delay = base_delay

    for attempt in range(1, max_attempts + 1):
        try:
            return func()
        except retryable_exceptions as exc:
            last_exception = exc
            if attempt == max_attempts:
                LOGGER.error(
                    "All %d attempts failed. Last error: %s: %s",
                    max_attempts,
                    type(exc).__name__,
                    exc,
                )
                raise
            LOGGER.warning(
                "Attempt %d/%d failed (%s: %s). Retrying in %.1fs...",
                attempt,
                max_attempts,
                type(exc).__name__,
                exc,
                delay,
            )
            time.sleep(delay)
            delay *= backoff_factor

    raise last_exception  # Should not reach here, but safety net

