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
"""Shared persistent cache for the iLO generation (and security state).

Why this exists
---------------
Detecting the iLO generation in-band requires opening a CHIF channel. Closing
that channel costs ~1 second because of an unconditional ``Sleep(1000)`` inside
``libhpsrv``'s ``ChifClose()``. The iLO generation is a hardware constant that
never changes for a given server, so caching it lets every subsequent command
skip the pre-login probe and avoid one CHIF open/close cycle (~1 s) per run.

The cache is intentionally shared between the login path
(``extensions/COMMANDS/LoginCommand.py``) and the raw-command path
(``extensions/RAW_COMMANDS/RawCommandBase.py``) so both read and write the same
``ilo_generation.json`` file with consistent semantics.

Cache location: ``<rdmc cachedir>/ilo_generation.json`` when available, else
``~/.iLORest/cache/ilo_generation.json``.

Cache lifetime: indefinite (hardware constant; never expires or becomes stale
for a given server).  The cache is only invalidated by deleting the file
manually or by removing the rdmc cache directory with ``ilorest logout`` / the
``--nocache`` flag on the login command.

``--nocache`` and this cache
----------------------------
This cache is intentionally **not** bypassed by ``--nocache``.  The ``--nocache``
flag prevents schema/resource-tree caching (which may be stale between firmware
upgrades), but the iLO *generation* is a fixed hardware property — it never
changes for a given server, so re-probing it on every ``--nocache`` run would
waste the ~1 s CHIF open/close cycle for zero benefit.

If you need to force a fresh generation probe (e.g. after replacing the system
board), delete ``ilo_generation.json`` from the rdmc cache directory manually.
"""

import json
import logging
import os

LOGGER = logging.getLogger(__name__)

#: File name for the persistent iLO generation cache.
CACHE_FILE_NAME = "ilo_generation.json"


def get_cache_file_path(cachedir=None):
    """Resolve the path to the iLO generation cache file.

    Args:
        cachedir: Preferred cache directory (typically ``rdmc.app.cachedir``).
            Falls back to ``~/.iLORest/cache`` when not usable.

    Returns:
        The absolute path to the cache file, or ``None`` if no writable
        location could be determined.
    """
    if cachedir and os.path.isdir(cachedir):
        return os.path.join(cachedir, CACHE_FILE_NAME)

    fallback_dir = os.path.join(os.path.expanduser("~"), ".iLORest", "cache")
    try:
        os.makedirs(fallback_dir, mode=0o700, exist_ok=True)
    except OSError as exc:
        LOGGER.debug("Could not create cache directory %s: %s", fallback_dir, exc)
        return None
    return os.path.join(fallback_dir, CACHE_FILE_NAME)


def read_cached_generation(cachedir=None):
    """Read the cached iLO generation.

    Args:
        cachedir: Preferred cache directory (typically ``rdmc.app.cachedir``).

    Returns:
        The cached generation as a float (e.g. ``6.0``), or ``None`` when no
        valid cache exists.
    """
    try:
        cache_file = get_cache_file_path(cachedir)
        if not cache_file or not os.path.exists(cache_file):
            return None
        with open(cache_file, "r") as handle:
            cache_data = json.load(handle)
        generation = cache_data.get("ilo_generation")
        if generation is None:
            return None
        return float(generation)
    except (OSError, ValueError, TypeError) as exc:
        LOGGER.debug("Failed to read iLO generation cache: %s", exc)
        return None


def write_cached_generation(version, cachedir=None, security_state=None):
    """Persist the iLO generation (merging with any existing cached values).

    Existing keys (such as ``security_state``) are preserved so that writers on
    the login path do not clobber data written by the raw-command path.

    Args:
        version: The iLO generation/version to persist (coerced to ``int``).
        cachedir: Preferred cache directory (typically ``rdmc.app.cachedir``).
        security_state: Optional security state to persist alongside.

    Returns:
        ``True`` on success, ``False`` otherwise.
    """
    try:
        cache_file = get_cache_file_path(cachedir)
        if not cache_file:
            return False

        cache_data = {}
        if os.path.exists(cache_file):
            try:
                with open(cache_file, "r") as handle:
                    existing = json.load(handle)
                if isinstance(existing, dict):
                    cache_data.update(existing)
            except (OSError, ValueError):
                # Corrupt/unreadable cache is simply overwritten below.
                pass

        cache_data["ilo_generation"] = int(version)
        if security_state is not None:
            cache_data["security_state"] = int(security_state)

        with open(cache_file, "w") as handle:
            json.dump(cache_data, handle)
        return True
    except (OSError, ValueError, TypeError) as exc:
        LOGGER.debug("Failed to write iLO generation cache: %s", exc)
        return False
