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

#: iLO generations at or above this value use the TPM-backed app-account/VNIC flow
#: and therefore require the cross-process TPM lock. iLO5/iLO6 do not use the TPM.
_MIN_TPM_GENERATION = 7


def _resolve_ilo_generation(rdmc):
    """Best-effort resolve the iLO generation as an int (e.g. 5, 6, 7).

    Resolution order (cheapest, most reliable first):
        1. ``rdmc.app.getiloversion()`` — available/cheap once a session exists.
        2. The shared persistent generation cache (``ilo_generation.json``),
           written by the login and raw-command paths.

    Args:
        rdmc: The RDMC/command object exposing ``app``.

    Returns:
        The iLO generation as an ``int``, or ``None`` when it cannot be determined.
    """
    app = getattr(rdmc, "app", None)

    # 1) Post-login / in-session: getiloversion() returns a float like 6.0 / 7.4.
    #    This is a best-effort probe — any failure (no session, transport error,
    #    unexpected type) simply falls through to the cache/default below.
    try:
        if app is not None and hasattr(app, "getiloversion"):
            version = app.getiloversion()
            if version:
                return int(float(version))
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.debug("getiloversion() unavailable for TPM-lock decision: %s", exc)

    # 2) Shared persistent generation cache (hardware constant; safe under --nocache).
    try:
        try:
            from ilorest.ilo_generation_cache import read_cached_generation
        except ImportError:
            from ilo_generation_cache import read_cached_generation

        cachedir = getattr(app, "cachedir", None)
        cached = read_cached_generation(cachedir)
        if cached:
            return int(cached)
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.debug("iLO generation cache unavailable for TPM-lock decision: %s", exc)

    return None


def is_tpm_lock_required(rdmc, app_account_flow=True):
    """Return ``True`` when the TPM file lock is needed for this iLO.

    The cross-process TPM lock only serializes operations that touch the TPM-backed
    app-account semaphore. It is unnecessary when either:

    * the iLO does not use the TPM at all (iLO5/iLO6), or
    * the current operation opts out of the app account (``--no_app_account`` /
      ``--no_app_token`` / ``--use_chif`` logins authenticate with plain credentials
      over VNIC/CHIF and never touch the TPM semaphore).

    When the generation cannot be determined, this defaults to ``True`` so the
    behavior stays safely serialized (matching the pre-existing behavior).

    Args:
        rdmc: The RDMC/command object exposing ``app``.
        app_account_flow: ``False`` when the operation does not use the app-account
            TPM flow (e.g. a ``--no_app_account``/``--use_chif`` login). Defaults to
            ``True``.

    Returns:
        ``True`` if locking is required (iLO7+ app-account flow or unknown),
        ``False`` for iLO5/iLO6 or any non-app-account flow.
    """
    if not app_account_flow:
        LOGGER.debug("Non-app-account flow (e.g. --no_app_account/--use_chif); TPM file lock not required.")
        return False

    generation = _resolve_ilo_generation(rdmc)
    if generation is None:
        # Unknown generation → keep the safe, serialized behavior.
        return True

    required = generation >= _MIN_TPM_GENERATION
    if not required:
        LOGGER.debug("iLO%d does not use the TPM; TPM file lock not required.", generation)
    return required


class TpmFileLock:
    """Cross-process advisory file lock for TPM operations.

    Ensures that only one ilorest process at a time performs TPM-backed
    authentication (token_exists, vnic_login, generate_save_token, delete_token).
    This prevents the race condition where concurrent sem_unlink calls destroy
    the named semaphore out from under other processes.

    This is an advisory lock — it only serializes cooperating ilorest processes.
    It does not prevent other programs from accessing the TPM directly.
    """

    def __init__(self, timeout=_LOCK_ACQUIRE_TIMEOUT, enabled=True):
        """Initialize the file lock.

        Args:
            timeout: Maximum seconds to wait for the lock before giving up.
            enabled: When ``False`` the lock becomes a no-op (``acquire``/``release``
                do nothing). Used to skip TPM serialization on iLO generations that
                do not use the TPM (iLO5/iLO6). Defaults to ``True``.
        """
        self._timeout = timeout
        self._enabled = enabled
        self._lock_fd = None
        # Tracks whether release() has been explicitly called. Once True, acquire()
        # raises RuntimeError to surface accidental reuse with a clear message instead
        # of silently re-acquiring or failing with an opaque NoneType error.
        self._released = False

    @classmethod
    def for_rdmc(cls, rdmc, timeout=_LOCK_ACQUIRE_TIMEOUT, app_account_flow=True):
        """Build a ``TpmFileLock`` enabled only when the operation uses the TPM.

        The lock is a no-op when the TPM is not involved — either because the iLO
        does not use the TPM (iLO5/iLO6) or because the operation opts out of the
        app account (``--no_app_account``/``--no_app_token``/``--use_chif`` logins
        authenticate with plain credentials and never touch the TPM semaphore).
        It is fully active only for an iLO7+ app-account flow.

        Args:
            rdmc: The RDMC/command object exposing ``app`` (used to resolve the
                iLO generation). ``None`` is tolerated and results in an active lock.
            timeout: Maximum seconds to wait for the lock before giving up.
            app_account_flow: ``False`` when the operation does not use the
                app-account TPM flow. Defaults to ``True``.

        Returns:
            A configured :class:`TpmFileLock` instance.
        """
        return cls(timeout=timeout, enabled=is_tpm_lock_required(rdmc, app_account_flow=app_account_flow))

    def acquire(self):
        """Acquire the cross-process file lock, blocking until available or timeout.

        Raises:
            RuntimeError: If this instance has already been explicitly released.
                Create a new :class:`TpmFileLock` instance instead of reusing one.
            TimeoutError: If the lock cannot be acquired within the timeout period.
            OSError: If the lock file cannot be created.
        """
        # iLO5/iLO6 (or unknown-but-disabled): the TPM is not used, so skip locking.
        if not self._enabled:
            LOGGER.debug("TPM file lock disabled (iLO does not use TPM); skipping acquire.")
            return

        if self._released:
            raise RuntimeError(
                "This TpmFileLock instance has already been released and cannot be reused. "
                "Create a new TpmFileLock instance to acquire the lock again."
            )

        # Release any previously held lock to avoid self-deadlock on double acquire.
        # Use the internal helper so that _released is NOT set — this is not a
        # user-facing release, just cleanup before re-acquisition.
        if self._lock_fd is not None:
            self._unlock_fd()

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
        """Release the cross-process file lock.

        After this call the instance is considered released; calling ``acquire()``
        again on the same instance will raise ``RuntimeError``. Create a new
        :class:`TpmFileLock` to acquire the lock a second time.
        """
        if not self._enabled:
            return
        if self._lock_fd is None:
            return

        try:
            self._unlock_fd()
        finally:
            # Mark released AFTER cleanup so the flag is always set even if
            # _unlock_fd raises (e.g. platform unlock error bubbling up).
            self._released = True

        LOGGER.debug("TPM file lock released")

    def _unlock_fd(self):
        """Unlock the OS-level advisory lock and close the file descriptor.

        This is the internal implementation used by both :meth:`release` and the
        double-acquire guard inside :meth:`acquire`. Keeping it separate ensures
        that ``_released`` is only set by the public :meth:`release` and never
        by internal cleanup paths.
        """
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
