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
"""Bootstrap OpenSSL for CNSA 2.0 (post-quantum) TLS defaults.

A strict CNSA 2.0 iLO8 requires the 1024-bit ML-KEM hybrids
(``MLKEM1024`` / ``SecP384r1MLKEM1024``) and an ``ML-DSA-87`` certificate.
OpenSSL 3.5 ships those algorithms but, by default, only *offers* the 768-bit
hybrid and does not advertise ML-DSA signatures — and CPython's stdlib ``ssl``
exposes no API to pin groups or sigalgs. The portable fix is the OpenSSL
``[system_default]`` ``ssl_conf`` section, which OpenSSL applies to every
``SSL_CTX`` (including the one ``ssl`` / urllib3 use). Pointing ``OPENSSL_CONF``
at the bundled ``openssl-cnsa2.cnf`` therefore makes ``ilorest login`` negotiate
CNSA 2.0 natively with no application code change.

IMPORTANT: :func:`ensure_openssl_conf` must run **before** ``ssl`` (and anything
that imports it, e.g. ``urllib3`` / ``redfish``) is first imported, because
OpenSSL reads its configuration when the library initializes. Call it at the very
top of the process entry point.
"""

import logging
import os
import sys

LOGGER = logging.getLogger(__name__)

#: Name of the bundled OpenSSL configuration file.
CNF_NAME = "openssl-cnsa2.cnf"

#: Set to "1" in the environment to skip the automatic OpenSSL config bootstrap.
DISABLE_ENV_VAR = "ILOREST_DISABLE_PQC_OPENSSL_CONF"


def _candidate_dirs():
    """Yield directories that may contain the bundled ``openssl-cnsa2.cnf``.

    Covers a source checkout, the installed ``ilorest`` package, a PyInstaller
    frozen bundle (``sys._MEIPASS``), and common install roots.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    dirs = [here, os.path.dirname(here)]

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        dirs.append(meipass)
        dirs.append(os.path.join(meipass, "ilorest"))

    exe_dir = os.path.dirname(os.path.abspath(sys.argv[0])) if sys.argv and sys.argv[0] else ""
    if exe_dir:
        dirs.append(exe_dir)

    dirs.extend(["/opt/ilorest", "/opt/ilorest/bin", "/etc/ilorest"])
    return dirs


def find_cnsa_config():
    """Locate the bundled CNSA 2.0 OpenSSL config file.

    Returns:
        The absolute path to ``openssl-cnsa2.cnf`` if found, else "".
    """
    for directory in _candidate_dirs():
        try:
            path = os.path.join(directory, CNF_NAME)
            if os.path.isfile(path):
                return os.path.abspath(path)
        except Exception:  # pragma: no cover - defensive path handling
            continue
    return ""


def ensure_openssl_conf(environ=None, set_env=True):
    """Point ``OPENSSL_CONF`` at the bundled CNSA 2.0 config, if appropriate.

    The function is intentionally conservative:

    * An operator-supplied ``OPENSSL_CONF`` is **never** overridden.
    * Setting ``ILOREST_DISABLE_PQC_OPENSSL_CONF=1`` disables the bootstrap.
    * If the bundled config cannot be found, nothing is changed.

    Args:
        environ: Mapping to read/update (defaults to ``os.environ``).
        set_env: When True, actually set ``OPENSSL_CONF`` in *environ*.

    Returns:
        A ``(path, changed)`` tuple: the resolved config path (or "" / the
        existing value) and whether this call set the variable.
    """
    env = os.environ if environ is None else environ

    if str(env.get(DISABLE_ENV_VAR, "")).strip() in ("1", "true", "True", "yes"):
        return "", False

    existing = env.get("OPENSSL_CONF")
    if existing:
        # Respect an explicit operator/user override.
        LOGGER.debug("OPENSSL_CONF already set (%s); leaving unchanged.", existing)
        return existing, False

    path = find_cnsa_config()
    if not path:
        LOGGER.debug("Bundled %s not found; OpenSSL uses its built-in defaults.", CNF_NAME)
        return "", False

    if set_env:
        env["OPENSSL_CONF"] = path
        LOGGER.debug("OPENSSL_CONF set to bundled CNSA 2.0 config: %s", path)
    return path, bool(set_env)
