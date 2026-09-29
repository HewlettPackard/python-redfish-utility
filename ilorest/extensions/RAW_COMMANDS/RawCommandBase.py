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
"""Base class for Raw Commands - provides common functionality for chif/blobstore support

Core Functionality of RawCommandBase:
------------------------------------
This base class provides common functionality for RAW commands (like rawget, rawpost,
rawput, etc.) that interact with iLO hardware through different access methods:

Optimized for Performance: The class helps in faster execution of raw commands by
providing a way to bypass cache building. Raw commands typically access specific
endpoints directly without needing the full resource tree cached.

Multiple Access Methods:
1. Out-of-band (OOB) via HTTPS/network
2. In-band via CHIF driver (direct hardware access)
3. In-band via VNIC for iLO7+

Centralized Error Handling: Provides consistent error messages across all raw commands
through the ErrorMessages class.

iLO Generation Management: Includes caching mechanisms for iLO generation detection to
avoid repeated lookups.

Authentication Management: Handles credentials, session management, and security state
validation across different iLO versions and security modes.
"""

# REFACTOR: This module is ~2350 lines (project limit is 600). Split into
# focused submodules: raw_url, raw_auth, raw_cache, raw_crypto, raw_http.
import gzip
import json
import logging
import re
import sys
from urllib.parse import urljoin, urlparse

import requests
from redfish.rest.v1 import RestClient

try:
    from rdmc_helper import (
        Encryption,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        InvalidFileFormattingError,
        InvalidFileInputError,
        ReturnCodes,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        Encryption,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        InvalidFileFormattingError,
        InvalidFileInputError,
        ReturnCodes,
    )

try:
    from .smbios_helpers import (
        extract_numeric_status_code,
        extract_response_headers,
        extract_smbios_raw_payload,
        is_json_content_type,
        is_smbios_path,
        normalize_smbios_payload,
        unpack_smbios_data,
    )
except ImportError:
    from smbios_helpers import (
        extract_numeric_status_code,
        extract_response_headers,
        extract_smbios_raw_payload,
        is_json_content_type,
        is_smbios_path,
        normalize_smbios_payload,
        unpack_smbios_data,
    )

try:
    from tpm_lock import TpmFileLock
except ImportError:
    from ilorest.tpm_lock import TpmFileLock

try:
    from redfish.rest.connections import InvalidCredentialsError, SecurityStateError
except ImportError:
    # Define fallback classes if imports fail
    class SecurityStateError(Exception):
        pass

    class InvalidCredentialsError(Exception):
        pass


# PQC crypto-agility helpers. Optional: raw commands still function without it,
# so a missing module degrades gracefully to "no crypto-capability descriptor".
try:
    from ilorest.security import pqc
    from ilorest.security.pqc import _PQC_STRICT_MIN_GENERATION as _PQC_STRICT_MIN_GENERATION_RAW
except ImportError:
    try:
        from security import pqc
        from security.pqc import _PQC_STRICT_MIN_GENERATION as _PQC_STRICT_MIN_GENERATION_RAW
    except ImportError:  # pragma: no cover - defensive
        pqc = None
        _PQC_STRICT_MIN_GENERATION_RAW = 8


LOGGER = logging.getLogger(__name__)

# HTTP timeout constant
HTTP_TIMEOUT_SECONDS = 60

# Timeout (seconds) for the VNIC availability probe's socket connect + TLS
# handshake. Kept short since a genuine VNIC/redfish service responds almost
# immediately; bounds the worst case when VNIC is disabled (the default on
# iLO 5/6) instead of relying on the full HTTP_TIMEOUT_SECONDS.
VNIC_PROBE_TIMEOUT_SECONDS = 2

# iLO version constants.
# iLO5/6 use CHIF for in-band access.
# iLO7 uses VNIC + app accounts; PQC hybrid mode.
# iLO8 uses VNIC + app accounts; PQC strict mode + PQC certificate algorithms.
ILO_VERSION_6 = 6.0
ILO_VERSION_7 = 7.0
ILO_VERSION_8 = 8.0


class ErrorMessages:
    """Centralized error messages for consistency across RAW commands"""

    NO_URL = (
        "No URL available. Please:\n"
        "  - Provide --url <ilo_ip> for network access\n"
        "  - Or login first with: ilorest login <ilo_ip> -u <user> -p <password>"
    )
    NO_CREDENTIALS = "Authentication requires --user and --password"
    NO_CREDENTIALS_OOB = "Out-of-band mode requires credentials. Please provide --user and --password"
    NO_CREDENTIALS_ILO7 = "iLO7 or later without app account requires credentials. Please provide --user and --password"
    NO_CREDENTIALS_HIGH_SEC = "High security mode requires credentials. Please provide --user and --password"
    SESSION_EXPIRED = "Session expired. Provide credentials to retry: --user <user> --password <password>"
    CHIF_NOT_AVAILABLE = (
        "CHIF driver not available for in-band access. "
        "Please use out-of-band mode: --url <ilo_ip> --user <user> --password <password>"
    )
    VNIC_NOT_AVAILABLE = (
        "VNIC not available for iLO7 or later in-band access. "
        "Please use out-of-band mode: --url <ilo_ip> --user <user> --password <password>"
    )
    INVALID_URL = "Invalid URL format: {url}"
    SERVICE_MODE_NO_URL = "The --url parameter needs to be specified for the service mode"
    INSECURE_HTTP_NOT_ALLOWED = (
        "Insecure HTTP protocol is not allowed. Please use HTTPS for secure iLO connections: https://<ilo_ip>"
    )


class RawCommandBase:
    """Base class for all raw commands with shared chif/blobstore functionality

    This is a base class and should not be instantiated directly.
    """

    # Default iLO URL used for local host connections
    DEFAULT_ILO_URL = "https://16.1.15.1"

    # HTTP verb this command issues. Subclasses override it at class level so the
    # verb is correct even before run() executes. Behaviour is unchanged at runtime
    # (run() already set it before any request), but the shared formatters now read
    # the right verb in every context.
    _raw_method = "GET"

    # Class-level in-memory cache for iLO version (shared across all instances)
    # This avoids repeated file I/O for iLO generation lookup
    # iLO generation is hardware-based and never changes, so no expiry needed
    _ilo_version_memory_cache = None

    # Class-level in-memory cache for security state (shared across all instances)
    # Security state is obtained during version detection and should be reused
    _security_state_memory_cache = None

    # Class-level in-memory cache for the per-target crypto-capability descriptor.
    # Derived on demand from the cached iLO generation (PQC-TLS gate) plus the
    # cached security state. Intentionally NOT persisted to its own cache file:
    # the generation cache already survives restarts, and certificate algorithms
    # are read live from iLO after login.
    _crypto_caps_memory_cache = None

    # Prevent this base class from being loaded as a command
    # Use empty name to make command loader skip it

    @staticmethod
    def _safe_log_debug(message, *args, **kwargs):
        """Safe logging wrapper that handles BrokenPipeError

        When output is piped (e.g., to /dev/null or head), the pipe may close
        before logging completes, causing BrokenPipeError. This wrapper
        silently catches and ignores such errors.

        :param message: Log message
        :param args: Additional arguments for logger
        :param kwargs: Additional keyword arguments for logger
        """
        try:
            LOGGER.debug(message, *args, **kwargs)
        except (BrokenPipeError, IOError):
            # Silently ignore broken pipe errors when output stream is closed
            pass

    ident = {
        "name": "",
        "usage": None,
        "description": "Base class - not a command",
        "summary": "Base class - not a command",
        "aliases": [],
        "auxcommands": [],
    }

    def __init__(self):
        """Initialize the RawCommandBase instance"""
        self.rdmc = None  # Will be set by the command framework
        self._bs2_instance = None  # BlobStore2 instance for chif communication
        # Remove in-memory cache - use only persistent file cache
        # self._cached_ilo_version = None

        # HTTP verb and body used by the shared request engine. The verb comes from
        # the class-level ``_raw_method`` (see below) so subclasses such as
        # RawPatchCommand report the correct verb even before run() executes;
        # assigning it here would shadow that class attribute with "GET".
        self._raw_body = None
        # Response headers captured from the most recent raw CHIF/BlobStore2 exchange.
        # CHIF returns a raw HTTP response string, so headers are parsed out here to
        # keep --getheaders working for in-band requests. Reset before every request.
        self._last_chif_headers = {}
        # Memoized VNIC availability probe result for this invocation. The probe is a
        # blocking socket connect to 16.1.15.1 (up to 1 s when VNIC is disabled); a
        # multi-path rawpatch/rawpost/rawput would otherwise pay it once per path.
        # None = not yet probed; set to True/False by _is_vnic_available().
        self._vnic_available_cache = None
        # HTTP status code of the most recent VNIC/HTTP login attempt. Lets callers
        # distinguish a credential rejection (401/403) from other login failures so
        # a wrong -u/-p is reported as an invalid-credentials error rather than a
        # generic one. Reset at the start of every login attempt.
        self._last_login_status_code = None
        # Set True when explicitly-supplied -u/-p fail CHIF verification during an
        # in-band request, so the resulting 401 is reported as an invalid-credentials
        # error. Reset on every CHIF credential initialization.
        self._chif_invalid_credentials = False

    def _preserve_session(self):
        """Mark that a raw command executed so rdmc skips explicit logout only.

        Enhancement: If an existing RestClient instance possesses a session_key,
        set a `_skip_logout` attribute to instruct higher layers to avoid
        remote DELETE attempts for a reused session token.
        """
        if not (self.rdmc and self.rdmc.app):
            return

        self.rdmc.app._preserve_session_for_raw_command = True
        self._set_skip_logout_flag()
        LOGGER.debug("Raw command preservation flag set (logout skipped; save allowed)")

    def _set_skip_logout_flag(self):
        """Set _skip_logout on redfish instance if applicable"""
        inst = getattr(self.rdmc.app, "redfishinst", None)
        if inst and getattr(inst, "session_key", None):
            try:
                setattr(inst, "_skip_logout", True)
                LOGGER.debug("Raw command set redfishinst._skip_logout to avoid remote DELETE")
            except Exception:
                pass

    def _mask_url_credentials(self, url):
        """Mask any embedded credentials in URL for safe logging

        :param url: URL that may contain embedded credentials
        :type url: str or None
        :returns: URL with credentials masked
        :rtype: str
        """
        if not url or not isinstance(url, str):
            return url

        if "@" not in url or "://" not in url:
            return url

        try:
            return self._perform_credential_masking(url)
        except Exception:
            return "[URL with credentials - masked]"

    def _perform_credential_masking(self, url):
        """Perform the actual masking of credentials in URL"""
        protocol, rest = url.split("://", 1)
        if "@" not in rest:
            return url

        creds, host = rest.split("@", 1)
        masked_creds = self._mask_credentials_string(creds)
        return f"{protocol}://{masked_creds}@{host}"

    def _mask_credentials_string(self, creds):
        """Mask a credentials string (user:pass or just token)"""
        if ":" in creds:
            return self._mask_user_password_pair(creds)
        return self._mask_simple_token(creds)

    def _mask_user_password_pair(self, creds):
        """Fully mask a ``username:password`` pair.

        Both halves are redacted: a username is PII and a password prefix is a
        partial secret disclosure, so neither may reach a log file.
        """
        return "***:***"

    def _mask_simple_token(self, token):
        """Fully mask a credential value (password, session key, X-Auth-Token, ...).

        No prefix of the value is preserved: leaking the first characters of a secret
        or of a username is still a disclosure. Only whether a value was present is
        conveyed, which is all the debug logs need.

        :param token: The sensitive value (may be ``None``).
        :returns: ``"***"`` when a value is present, ``"<none>"`` when it is not.
        :rtype: str
        """
        return "***" if token else "<none>"

    def _mask_username(self, username):
        """Mask a username for logging.

        Usernames are PII (they identify an operator/account) and must never be
        written to the debug log in clear text.

        :param username: The username (may be ``None``).
        :returns: ``"***"`` when a username was supplied, ``"<none>"`` otherwise.
        :rtype: str
        """
        return "***" if username else "<none>"

    #: Request header names whose values authenticate the caller and must never
    #: be written to a log file in clear text.
    SENSITIVE_HEADERS = frozenset(
        {
            "authorization",
            "x-auth-token",
            "cookie",
            "set-cookie",
            "session",
            "sessionid",
            "session-key",
            "x-sessionkey",
        }
    )

    def _mask_headers(self, headers):
        """Return a copy of ``headers`` with every credential-bearing value redacted.

        Callers may pass ``--headers X-Auth-Token:<token>`` or an ``Authorization``
        header, so raw header dictionaries must not be logged.

        :param headers: Header mapping (may be ``None`` or a non-mapping).
        :returns: A mapping safe to log.
        :rtype: dict
        """
        if not isinstance(headers, dict):
            return headers
        return {key: ("***" if str(key).lower() in self.SENSITIVE_HEADERS else value) for key, value in headers.items()}

    def _get_url_from_session(self):
        """Extract base URL from the active session instance, normalized.

        Returns the raw blobstore URL for in-band CHIF sessions, or an
        ``https://`` prefixed URL for network sessions so that callers can
        reliably distinguish session type via a scheme check.

        :returns: URL string or None
        :rtype: str or None
        """
        try:
            if self.rdmc and self.rdmc.app:
                redfishinst = getattr(self.rdmc.app, "redfishinst", None)
                if redfishinst:
                    base_url = getattr(redfishinst, "base_url", None)
                    if base_url:
                        if "blobstore://" in base_url:
                            return base_url
                        elif base_url.startswith("https://"):
                            return base_url
                        else:
                            return f"https://{base_url}"
        except Exception as e:
            LOGGER.debug("Could not get URL from session: %s", e)

        return None

    def _build_url(self, options):
        """Build base URL from options

        :param options: command line options
        :type options: object
        :returns: base URL string
        """
        # Check if we should use inband/chif communication
        if self._should_use_inband(options):  # type: ignore[arg-type]
            return "blobstore://."

        url = self._determine_base_url(options)  # type: ignore[arg-type]

        self._validate_http_protocol(url)
        return self._normalize_url(url)

    def _determine_base_url(self, options):
        """Determine base URL from options or session"""
        # Priority 1: Explicit URL from command line options
        if hasattr(options, "url") and options.url:
            return options.url

        # Priority 2: Get from existing session
        url = self._get_url_from_session()

        # Priority 3: Fail if no URL is available
        if not url:
            raise InvalidCommandLineError(
                "No target URL specified. Please provide an iLO IP address using --url option, "
                "login to a session first, or use inband mode (chif driver required)."
            )
        return url

    def _validate_http_protocol(self, url):
        """Validate protocol constraints"""
        if url.startswith("http://"):
            raise InvalidCommandLineError(ErrorMessages.INSECURE_HTTP_NOT_ALLOWED)

    def _normalize_url(self, url):
        """Normalize URL with protocol and trailing slash removal"""
        # Ensure URL has protocol prefix (only https:// or blobstore://)
        if not any(protocol in url for protocol in ["blobstore://", "https://"]):
            url = "https://" + url

        # Remove trailing slash
        return url.rstrip("/")

    def _build_url_service_mode(self, options):
        """Build base URL for service mode - bypasses application layer to avoid excessive requests

        :param options: command line options
        :type options: object
        :returns: base URL string
        :raises InvalidCommandLineError: If service mode used without explicit URL
        """
        # Service mode optimization: bypass application layer completely
        if getattr(options, "service", False):
            LOGGER.debug("Service mode: bypassing application layer for optimal performance")
            return self._build_service_mode_url_optimized(options)  # type: ignore[arg-type]

        # Non-service mode: use standard build method
        return self._build_url(options)

    def _build_service_mode_url_optimized(self, options):
        """Build optimized URL for service mode"""
        # Check if we should use inband/chif communication
        if self._should_use_inband(options):  # type: ignore[arg-type]
            return "blobstore://."

        # For service mode, prioritize explicit URL (no session discovery)
        if not (hasattr(options, "url") and options.url):
            raise InvalidCommandLineError(ErrorMessages.SERVICE_MODE_NO_URL)

        url = options.url
        self._validate_http_protocol(url)
        url = self._normalize_url(url)

        # Validate normalized URL
        self._validate_url(url)
        return url

    def _get_cached_session_token(self, options=None):
        """Get cached session token from existing session with proper error handling

        :param options: Command options (optional, used to check --nocache flag)
        :type options: object or None
        :returns: Session token string or None
        :rtype: str or None
        """
        # Check nocache flag
        if self._should_skip_cached_session(options):  # type: ignore[arg-type]
            return None

        # Try to get session token
        try:
            return self._extract_session_token_from_rdmc()
        except AttributeError as e:
            LOGGER.debug("Attribute error accessing session: %s", e)
            return None
        except Exception as e:
            LOGGER.warning("Unexpected error retrieving cached session token: %s", e)
            return None

    def _should_skip_cached_session(self, options):
        """Check if cached session should be skipped"""
        if options and hasattr(options, "nocache") and options.nocache:
            LOGGER.debug("--nocache flag set, skipping cached session")
            return True
        return False

    def _extract_session_token_from_rdmc(self):
        """Extract session token from rdmc instance"""
        inst = self._get_redfish_instance()
        if not inst:
            return None

        # Get session token from primary attribute
        if hasattr(inst, "session_key") and inst.session_key:
            LOGGER.debug("Found cached session token")
            return inst.session_key

        return None

    def _get_cached_session_token_service_mode(self, options):
        """Get cached session token for service mode - bypasses application caching

        Service mode should not rely on application layer caching to avoid
        the excessive requests issue documented.

        :param options: Command options
        :returns: None (service mode creates its own sessions)
        """
        # Service mode optimization: don't use cached sessions from application layer
        # This avoids triggering the discovery and registry loading that causes
        # 341 requests instead of the required 4 requests
        if getattr(options, "service", False):
            LOGGER.debug("Service mode: bypassing cached session to avoid application layer dependencies")
            return None

        # Non-service mode: use standard cached session method
        return self._get_cached_session_token()

    def _validate_url(self, url):
        """Validate URL format

        :param url: URL to validate
        :type url: str
        :raises InvalidCommandLineError: If URL is invalid or uses insecure HTTP
        :returns: True if valid
        :rtype: bool
        """
        if not url:
            raise InvalidCommandLineError("URL cannot be empty")

        # Allow blobstore URLs
        if url.startswith("blobstore://"):
            return True

        # Security check: Block insecure HTTP connections
        if url.startswith("http://"):
            raise InvalidCommandLineError(ErrorMessages.INSECURE_HTTP_NOT_ALLOWED)

        # Validate network URLs - only allow HTTPS
        pattern = r"^https://[\w\-\.]+(:\d+)?(/.*)?$"
        if not re.match(pattern, url):
            raise InvalidCommandLineError(ErrorMessages.INVALID_URL.format(url=url))

        LOGGER.debug("URL validated: %s", self._mask_url_credentials(url))
        return True

    def _execute_request(self, method, path, headers=None, body=None, auth=None, timeout=HTTP_TIMEOUT_SECONDS):
        """Execute HTTP request with common settings

        :param method: HTTP method (GET, POST, PUT, PATCH, DELETE, HEAD)
        :type method: str
        :param path: Full URL path
        :type path: str
        :param headers: Request headers dict
        :type headers: dict or None
        :param body: Request body (for POST/PUT/PATCH)
        :type body: dict or str or None
        :param auth: Authentication tuple (username, password)
        :type auth: tuple or None
        :param timeout: Request timeout in seconds
        :type timeout: int
        :returns: requests.Response object
        :rtype: requests.Response
        """
        headers = self._prepare_request_headers(headers, body)
        kwargs = self._prepare_request_kwargs(headers, body, auth, timeout, method, path)

        LOGGER.debug("Executing %s request to %s", method, self._mask_url_credentials(path))

        session = self._get_requests_session_with_pqc(target_url=path)
        try:
            return session.request(method.upper(), path, **kwargs)
        finally:
            session.close()

    def _prepare_request_headers(self, headers, body):
        """Prepare request headers"""
        if headers is None:
            headers = {}

        if "Content-Type" not in headers and body:
            headers["Content-Type"] = "application/json"

        return headers

    def _prepare_request_kwargs(self, headers, body, auth, timeout, method, path=None):
        """Prepare keyword arguments for requests call"""
        kwargs = {"headers": headers, "verify": False, "timeout": timeout}

        if auth:
            kwargs["auth"] = auth  # type: ignore[assignment]

        if body and method.upper() in ["POST", "PUT", "PATCH"]:
            kwargs["data"] = json.dumps(body) if isinstance(body, dict) else body  # type: ignore[assignment]

        # For local in-band VNIC and loopback targets, bypass system proxy settings.
        # Proxy traversal can break 16.1.15.1 TLS handshake and cause raw timeouts.
        if self._should_bypass_proxies(path):
            kwargs["proxies"] = {"http": "", "https": ""}

        return kwargs

    def _get_request_method(self, method, requests_module):
        """Get the appropriate requests function for the method"""
        request_methods = {
            "GET": requests_module.get,
            "POST": requests_module.post,
            "PUT": requests_module.put,
            "PATCH": requests_module.patch,
            "DELETE": requests_module.delete,
            "HEAD": requests_module.head,
        }

        method_func = request_methods.get(method.upper())
        if not method_func:
            raise InvalidCommandLineError(f"Unsupported HTTP method: {method}")

        return method_func

    def _should_bypass_proxies(self, path):
        """Return True when request target should ignore proxy settings.

        Local VNIC endpoints like 16.1.15.1 should never go through system proxies.
        """
        if not path:
            return False

        try:
            parsed = urlparse(path)
            host = (parsed.hostname or "").lower()
        except Exception:
            return False

        return host in {"16.1.15.1", "localhost", "127.0.0.1", "::1"}

    def _build_pqc_ssl_context_for_target(self):
        """Build a PQC SSLContext appropriate for the detected iLO generation.

        Reads the in-memory crypto-capability cache (populated by
        :meth:`_get_crypto_capabilities`) to determine the recommended PQC
        mode for this target:

        * iLO5 / iLO6 -- returns ``None`` (no PQC).
        * iLO7 -- returns a hybrid-mode context.
        * iLO8+ -- attempts a strict-mode context, gracefully downgrading to
          hybrid when the runtime's OpenSSL build lacks group selection.

        Returns:
            An :class:`ssl.SSLContext` configured for PQC, or ``None`` when PQC
            is not applicable or unavailable.
        """
        if pqc is None:
            return None

        caps = self._get_crypto_capabilities()
        if caps is None or not caps.supports_pqc_tls():
            return None

        mode = caps.recommended_pqc_mode()
        if mode == pqc.PQC_MODE_OFF:
            return None

        # When the generation isn't cached, offer the widest group set (MLKEM1024
        # first) so the server can select its best supported group.  This mirrors
        # the login probe strategy and prevents a Level-III-only handshake from
        # being rejected by iLO8 before we have a chance to learn its generation.
        effective_gen = caps.ilo_generation if caps.ilo_generation is not None else _PQC_STRICT_MIN_GENERATION_RAW

        try:
            ctx = pqc.build_ssl_context(mode, generation=effective_gen)
            self._safe_log_debug("Built PQC SSL context for iLO%s (mode=%s)", effective_gen, mode)
            return ctx
        except pqc.PQCNotAvailableError:
            # iLO8 strict mode requested but OpenSSL/Python lacks group support;
            # downgrade to hybrid so the connection still succeeds with PQC where
            # available.
            LOGGER.warning(
                "PQC strict mode unavailable for iLO%s; downgrading to hybrid",
                effective_gen,
            )
            try:
                return pqc.build_ssl_context(pqc.PQC_MODE_HYBRID, generation=effective_gen)
            except Exception as exc:
                LOGGER.debug("Could not build hybrid PQC SSL context: %s", exc)
                return None
        except Exception as exc:
            LOGGER.debug("Could not build PQC SSL context for target: %s", exc)
            return None

    def _get_requests_session_with_pqc(self, target_url=None):
        """Return a ``requests.Session`` configured with PQC TLS when applicable.

        For iLO7 targets the session will prefer hybrid PQC key exchange.
        For iLO8+ targets the session will use strict PQC (falling back to
        hybrid when the runtime's OpenSSL cannot select TLS groups).
        For iLO5/6 or when the generation is unknown the returned session uses
        the default TLS stack — identical to the pre-PQC behavior.

        The session also bypasses environment proxies when *target_url* points
        to the local VNIC endpoint (16.1.15.1).

        Args:
            target_url: Optional URL of the target; used to determine whether
                proxy bypass is needed.

        Returns:
            A configured :class:`requests.Session`.
        """
        import requests
        from requests.adapters import HTTPAdapter

        session = requests.Session()
        session.trust_env = False  # Never use env-level proxy for iLO endpoints

        ssl_context = self._build_pqc_ssl_context_for_target()
        if ssl_context is not None:
            # Inject the custom SSL context into the urllib3 pool manager via
            # a subclassed HTTPAdapter.  This preserves all other adapter
            # settings (retries, timeouts) while adding PQC group selection.
            class _PQCAdapter(HTTPAdapter):
                """HTTPAdapter that forwards a custom ssl_context to urllib3."""

                def __init__(self, ctx, **kwargs):
                    self._ssl_context = ctx
                    super().__init__(**kwargs)

                def init_poolmanager(self, *args, **kwargs):
                    kwargs["ssl_context"] = self._ssl_context
                    super().init_poolmanager(*args, **kwargs)

                def proxy_manager_for(self, proxy, **proxy_kwargs):
                    proxy_kwargs["ssl_context"] = self._ssl_context
                    return super().proxy_manager_for(proxy, **proxy_kwargs)

            session.mount("https://", _PQCAdapter(ssl_context))

        return session

    def _detect_ilo_version(self):
        """Detect iLO version using three-tier caching strategy for optimal performance

        Caching tiers (checked in order, fastest to slowest):
        1. In-memory cache (class-level) - instant, shared across all instances in process
        2. Persistent file cache (~/.iLORest/cache/ilo_generation.json) - fast, survives process restarts
        3. Active detection via CHIF/VNIC - slow, only when no cache exists

        Cache persistence:
        - iLO generation is hardware-based and NEVER changes during server lifetime
        - Cache has NO expiration - valid until manually deleted or server hardware replaced
        - Only cleared by 'ilorest logout' (deletes entire cache directory) or manual deletion

        Performance optimization for --nocache:
        - --nocache skips session cache but still uses iLO generation caches (tiers 1 & 2)
        - This provides ~10-20x speedup vs. re-detection on every call
        - Memory cache eliminates file I/O overhead (50-200ms per call)

        Cache file location: ~/.iLORest/cache/ilo_generation.json
        Cache expiration: Never (iLO generation is hardware constant)

        :returns: iLO version as float or None
        :rtype: float or None
        """
        # Tier 0: Read generation from the active login session's typepath.
        # When 'ilorest login' was run before this raw command, rdmc.app.typepath
        # already carries the authoritative iLO generation (set during login).
        # Using it avoids a CHIF/VNIC re-probe that would produce a wrong
        # generation (e.g. iLO7 via VNIC when the server is actually iLO8),
        # which in turn would build the wrong PQC TLS group list.
        session_gen = self._get_generation_from_active_session()
        if session_gen is not None:
            RawCommandBase._ilo_version_memory_cache = session_gen
            self._safe_log_debug("Using iLO generation from active login session (Tier 0): %s", session_gen)
            return session_gen

        # Tier 1: Check in-memory cache first (fastest - no I/O)
        # iLO generation never changes, so no expiry check needed
        if RawCommandBase._ilo_version_memory_cache is not None:
            self._safe_log_debug(
                "Using in-memory cached iLO version (ultra-fast path): %s", RawCommandBase._ilo_version_memory_cache
            )
            return RawCommandBase._ilo_version_memory_cache

        # Tier 2: Try to load from persistent file cache (fast - one file read)
        cached_version = self._load_ilo_version_from_cache()
        if cached_version is not None:
            # Update in-memory cache for next call
            RawCommandBase._ilo_version_memory_cache = cached_version
            self._safe_log_debug("Loaded iLO version from file cache, updated memory cache: %s", cached_version)
            return cached_version

        try:
            # Tier 3: Perform actual detection (slow - first time only)
            self._safe_log_debug("No cache found - performing first-time iLO detection")
            version = self._do_version_detection()

            # Cache the result in both memory and file (persists indefinitely)
            if version:
                RawCommandBase._ilo_version_memory_cache = version
                self._save_ilo_version_to_cache(version)
                self._safe_log_debug("Detected and cached iLO version (memory + file): %s", version)

            return version

        except Exception as e:
            self._safe_log_debug("iLO version detection failed: %s", e)
            return None

    def _get_generation_from_active_session(self):
        """Read the iLO generation from the active login session's typepath.

        When ``ilorest login`` was run before this raw command, ``rdmc.app.typepath``
        carries the authoritative iLO generation that was resolved during login.
        This is the correct Tier-0 source: no CHIF probe, no VNIC round-trip,
        no possibility of returning the wrong generation via the VNIC fallback.

        Returns:
            iLO generation as a float (e.g. ``8.0``) or ``None`` when no active
            session is available or the generation cannot be read.
        """
        try:
            if not (self.rdmc and self.rdmc.app):
                return None

            # redfishinst must exist and have an active session for this to be valid.
            redfishinst = getattr(self.rdmc.app, "redfishinst", None)
            if not redfishinst or not getattr(redfishinst, "session_key", None):
                return None

            typepath = getattr(self.rdmc.app, "typepath", None)
            if typepath is None:
                return None

            # ilogen is the integer generation (5, 6, 7, 8, …).
            ilogen = getattr(typepath, "ilogen", None)
            if ilogen is not None:
                try:
                    return float(ilogen)
                except (TypeError, ValueError):
                    pass

            # iloversion is the full dot-version string e.g. "8.0"; fall back to it.
            iloversion = getattr(typepath, "iloversion", None)
            if iloversion is not None:
                try:
                    return float(str(iloversion).split(".")[0])
                except (TypeError, ValueError):
                    pass
        except Exception as exc:
            self._safe_log_debug("Could not read generation from active session: %s", exc)

        return None

    def _get_crypto_capabilities(self):
        """Build an in-memory crypto-capability descriptor for the target iLO.

        The descriptor is derived from the existing three-tier iLO generation
        cache: the PQC-TLS gate is a function of the generation (see
        ``CryptoCapabilities.from_generation``), and the already-cached security
        state is attached for completeness. No separate cache file is written -
        the generation cache already persists across restarts, and certificate
        algorithms are read live from iLO after login.

        The result is memoized on the class so repeated raw commands in the same
        process reuse it without re-running detection.

        Returns:
            A ``CryptoCapabilities`` descriptor, or ``None`` when the PQC helper
            is unavailable or the iLO generation cannot be determined.
        """
        # Tier 1: reuse the already-built descriptor (no I/O, no detection).
        if RawCommandBase._crypto_caps_memory_cache is not None:
            return RawCommandBase._crypto_caps_memory_cache

        if pqc is None:
            self._safe_log_debug("PQC helper unavailable; no crypto-capability descriptor built")
            return None

        # Reuse the generation cache (memory -> file -> detection). This is the
        # single source of truth for the pre-login PQC-TLS gate.
        version = self._detect_ilo_version()
        if version is None:
            self._safe_log_debug("iLO generation unknown; cannot build crypto-capability descriptor")
            return None

        generation = int(version)
        sec_state = RawCommandBase._security_state_memory_cache
        caps = pqc.CryptoCapabilities.from_generation(generation, sec_state=sec_state)
        RawCommandBase._crypto_caps_memory_cache = caps
        self._safe_log_debug(
            "Built crypto-capability descriptor: gen=%s, pqc_tls=%s, sec_state=%s",
            generation,
            caps.supports_pqc_tls(),
            sec_state,
        )
        return caps

    def _get_cache_file_path(self):
        """Get the path to the iLO generation cache file in ~/.iLORest/cache directory

        :returns: Path to cache file
        :rtype: str
        """
        import os

        # Try to use iLORest cache directory if available
        rdmc_cache = self._get_rdmc_cache_dir()
        if rdmc_cache:
            return os.path.join(rdmc_cache, "ilo_generation.json")

        # Fallback to home directory
        return self._get_default_cache_path()

    def _get_rdmc_cache_dir(self):
        """Get cache directory from RDMC app if available"""
        try:
            cache_dir = self._extract_rdmc_cachedir()
            if self._is_valid_cache_dir(cache_dir):
                return cache_dir
        except Exception:
            pass
        return None

    def _extract_rdmc_cachedir(self):
        """Extract cache directory from RDMC app"""
        if self.rdmc and self.rdmc.app and hasattr(self.rdmc.app, "cachedir"):
            return self.rdmc.app.cachedir
        return None

    def _is_valid_cache_dir(self, cache_dir):
        """Check if cache directory is valid"""
        import os

        return cache_dir and os.path.isdir(cache_dir)

    def _get_default_cache_path(self):
        """Get default cache path in home directory"""
        import os

        home_dir = os.path.expanduser("~")
        cache_dir = os.path.join(home_dir, ".iLORest", "cache")

        if not self._ensure_directory_exists(cache_dir):
            return None

        return os.path.join(cache_dir, "ilo_generation.json")

    def _ensure_directory_exists(self, directory):
        """Ensure a directory exists, creating if necessary"""
        import os

        try:
            if not os.path.exists(directory):
                os.makedirs(directory, mode=0o755)
            return True
        except Exception as e:
            LOGGER.debug("Could not create directory %s: %s", directory, e)
            return False

    def _load_ilo_version_from_cache(self):
        """Load iLO generation from persistent cache file in ~/.iLORest/cache

        Cache file is created by detectiLO command on first run and persists indefinitely.
        iLO generation is hardware-based and never changes during the server's lifetime.

        This allows rawget and other commands to bypass expensive detection operations
        by reading the cached generation value directly from disk.

        Cache format: JSON file with generation number (no expiration)
        Cache location: ~/.iLORest/cache/ilo_generation.json
        Cache lifetime: Indefinite (until manual deletion or server hardware replacement)

        :returns: Cached iLO generation as float or None
        :rtype: float or None
        """
        try:
            import json
            import os

            cache_file = self._get_cache_file_path()
            if not cache_file or not os.path.exists(cache_file):
                LOGGER.debug("No persistent cache file found - first run or cache cleared")
                return None

            # Read cache file
            with open(cache_file, "r") as f:
                cache_data = json.load(f)

            # Return cached generation (5, 6, or 7) as float
            # No expiration check - iLO generation never changes
            generation = cache_data.get("ilo_generation")
            if generation:
                self._safe_log_debug("Found valid cache: iLO %s (bypassed detection, no expiry)", generation)
                # Also restore security_state into memory cache so _is_high_security_mode()
                # and _get_security_state_from_cache() skip a second hardware detection call
                cached_sec_state = cache_data.get("security_state")
                if cached_sec_state is not None and RawCommandBase._security_state_memory_cache is None:
                    RawCommandBase._security_state_memory_cache = int(cached_sec_state)
                    self._safe_log_debug("Restored security state from file cache: %s", cached_sec_state)
                return float(generation)

        except Exception as e:
            self._safe_log_debug("Failed to load cache file: %s", e)

        return None

    def _save_ilo_version_to_cache(self, version):
        """Save iLO generation to persistent cache file in ~/.iLORest/cache

        This cache file is shared across all ilorest commands and processes,
        allowing detectiLO to run once and all subsequent commands to reuse the result.

        Cache persists indefinitely since iLO generation is hardware-based and never changes.
        Only cleared by 'ilorest logout' (deletes entire cache directory) or manual deletion.

        Cache file: ~/.iLORest/cache/ilo_generation.json
        Format: JSON with generation number (no timestamp needed)
        Permissions: 0o755 for directory, 0o644 for file
        Lifetime: Indefinite (until manual deletion or server hardware replacement)

        :param version: iLO version to cache (e.g., 5.0, 6.0, 7.0)
        :type version: float
        """
        try:
            import json
            import os

            cache_file = self._get_cache_file_path()
            if not cache_file:
                LOGGER.debug("Could not determine cache file path")
                return

            # Convert version to generation (5.0 -> 5, 6.0 -> 6, 7.0 -> 7)
            generation = int(version)

            # Prepare cache data (no timestamp - cache never expires)
            # Also persist security_state so it survives process restarts,
            # avoiding a redundant getilover_beforelogin() call on the next run
            cache_data = {"ilo_generation": generation}
            if RawCommandBase._security_state_memory_cache is not None:
                cache_data["security_state"] = RawCommandBase._security_state_memory_cache

            # Write cache file
            try:
                with open(cache_file, "w") as f:
                    json.dump(cache_data, f, indent=2)

                # Set readable permissions
                os.chmod(cache_file, 0o644)
            except (OSError, IOError) as e:
                LOGGER.debug("Could not save iLO version to cache file (permission issue?): %s", e)
        except Exception as e:
            LOGGER.debug("Failed to save iLO version to cache: %s", e)

    def _detect_ilo_version_chif(self):
        """Detect the iLO generation using getilover_beforelogin method.

        This method uses the cached detection wrapper which calls the same
        detection method as DetectiLOCommand (rdmc.app.getilover_beforelogin).

        This properly handles iLO5, iLO6, and iLO7 detection without directly
        calling dll.DetectILO().

        :returns: Detected iLO version as float or None if detection fails
        :rtype: float or None
        """
        # Use the cached wrapper which checks persistent file cache
        return self._detect_ilo_version()

    def _do_version_detection(self):
        """Perform actual iLO generation detection using getilover_beforelogin method.

        Uses the same detection method as DetectiLOCommand via rdmc.app.getilover_beforelogin().
        This method properly handles iLO5, iLO6, and iLO7 detection.

        :returns: Detected iLO version as float (5.0, 6.0, or 7.0)
        :rtype: float
        """
        LOGGER.debug("Performing iLO generation detection using getilover_beforelogin...")

        # Try primary detection method
        version = self._try_getilover_detection()
        if version:
            return version

        # Fallback to VNIC probe
        return self._fallback_vnic_probe_detection()

    def _try_getilover_detection(self):
        """Try to detect iLO version using getilover_beforelogin method"""
        try:
            return self._perform_getilover_detection()
        except Exception as e:
            return self._handle_getilover_exception(e)

    def _perform_getilover_detection(self):
        """Perform the actual getilover detection"""
        from redfish.hpilo.vnichpilo import AppAccount

        # Create AppAccount object (same as DetectiLOCommand)
        app_obj = AppAccount(log_dir=self.rdmc.log_dir if self.rdmc else None)

        # Use the same method as DetectiLOCommand
        if not self._check_getilover_availability():
            return None

        ilo_ver, sec_state = self.rdmc.app.getilover_beforelogin(app_obj)
        LOGGER.debug("Detected iLO%s via getilover_beforelogin (security state: %s)", ilo_ver, sec_state)

        # Cache security state to avoid redundant detection later
        # This is a significant performance optimization
        self._cached_security_state = sec_state
        RawCommandBase._security_state_memory_cache = sec_state

        # Normalize version string
        return self._normalize_ilo_version_string(ilo_ver)

    def _handle_getilover_exception(self, exception):
        """Handle exceptions from getilover detection"""
        from redfish.rest.connections import (
            ChifDriverMissingOrNotFound,
            VnicNotEnabledError,
        )

        if isinstance(exception, ChifDriverMissingOrNotFound):
            LOGGER.debug("CHIF driver missing, likely iLO7, using VNIC fallback")
        elif isinstance(exception, VnicNotEnabledError):
            LOGGER.debug("VNIC not enabled but detected iLO7")
            return ILO_VERSION_7
        else:
            LOGGER.debug("getilover_beforelogin failed: %s, using fallback", exception)

        return None

    def _check_getilover_availability(self):
        """Check if getilover_beforelogin is available"""
        if not (self.rdmc and self.rdmc.app and hasattr(self.rdmc.app, "getilover_beforelogin")):
            LOGGER.debug("rdmc.app.getilover_beforelogin not available, using fallback")
            return False
        return True

    def _normalize_ilo_version_string(self, ilo_ver):
        """Normalize iLO version string to float"""
        if isinstance(ilo_ver, str):
            parts = ilo_ver.split(".")
            if len(parts) > 2:
                ilo_ver = parts[0]
                LOGGER.debug("Detected patch version in iLO string; using major version only")
        return float(ilo_ver)

    def _fallback_vnic_probe_detection(self):
        """Fallback detection using VNIC probe to distinguish iLO7 from iLO5/6.

        WARNING: This heuristic only checks whether 16.1.15.1:443 is reachable.
        It cannot distinguish iLO7 from iLO8 — both expose VNIC.  When used
        without a prior ``ilorest login`` (Tier-0), the generation is reported
        as 7.0 even for iLO8, which may cause the wrong PQC TLS group list to
        be selected.  Run ``ilorest login`` first for accurate generation data.
        """
        LOGGER.warning(
            "VNIC probe fallback: cannot distinguish iLO7 from iLO8 — "
            "PQC TLS group selection may be suboptimal.  Run 'ilorest login' "
            "first for accurate generation detection."
        )

        try:
            import socket

            # Quick check if VNIC is accessible on default iLO URL port 443 (iLO7 indicator)
            vnic_host = self.DEFAULT_ILO_URL.replace("https://", "").replace("http://", "")

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex((vnic_host, 443))
            sock.close()

            if result == 0:
                LOGGER.debug("VNIC accessible - detected iLO7")
                return ILO_VERSION_7
            else:
                LOGGER.debug("VNIC not accessible - defaulting to iLO6")
                return ILO_VERSION_6

        except Exception as e:
            LOGGER.debug("VNIC probe failed: %s, defaulting to iLO6", e)
            return ILO_VERSION_6

    def _setup_authentication(self, options, url=None, use_inband=False):
        """Enhanced authentication setup with 6-scenario session management framework

        Supports all iLO modes:
        - iLO5 production/high security mode
        - iLO6 production/high security mode
        - iLO7 VNIC mode (both app account and no_app_account)

        :param options: Command options
        :param url: Target URL
        :param use_inband: Whether using inband communication
        :returns: tuple of (auth, session_token, need_logout, auth_type, fallback_auth)
        """
        auth_result = self._initialize_auth_result()
        nocache = self._check_nocache_flag(options)

        # Check high security mode
        if self._is_high_security_mode():
            return self._handle_high_security_auth(options, use_inband, auth_result)

        # Check iLO VNIC mode (iLO 6+)
        # vnic can be enabled in iLO6 also. but there is no concept of appaccount in iLO6.
        vnic_result = self._handle_vnic_mode_check(options, use_inband, auth_result)
        if vnic_result:
            return vnic_result

        # Try cached session (unless nocache, or explicit credentials were supplied).
        # Explicit -u/-p must always be honored and validated, so they take precedence
        # over any cached session rather than being silently short-circuited by it.
        if not nocache and not self._has_explicit_credentials(options):
            cached_result = self._try_cached_session_auth(options, auth_result)
            if cached_result:
                return cached_result

        # Fallback to credential-based auth
        return self._handle_credential_auth(options, use_inband, auth_result)

    def _handle_vnic_mode_check(self, options, use_inband, auth_result):
        """Check and handle VNIC authentication if applicable

        For iLO 6: Must distinguish between VNIC-enabled and CHIF-only modes
        For iLO 7: Always uses VNIC
        """
        if not use_inband:
            return None

        ilo_version = self._get_ilo_version()

        # iLO 7 always uses VNIC (with or without app account)
        if ilo_version and ilo_version >= 7:
            return self._handle_ilo7_vnic_auth(options, auth_result)

        # iLO 6 needs VNIC availability check
        if ilo_version and ilo_version >= 6:
            if self._is_vnic_available():
                # iLO 6 with VNIC enabled - use VNIC authentication
                LOGGER.debug("iLO 6 with VNIC enabled - using VNIC authentication")
                return self._handle_ilo7_vnic_auth(options, auth_result)
            else:
                # iLO 6 without VNIC - will fall through to use CHIF
                LOGGER.debug("iLO 6 without VNIC - will use CHIF authentication")
                return None

        return None

    def _initialize_auth_result(self):
        """Initialize default authentication result"""
        return {"auth": None, "session_token": None, "need_logout": False, "auth_type": "none", "fallback_auth": None}

    def _check_nocache_flag(self, options):
        """Check if nocache flag is set"""
        nocache = hasattr(options, "nocache") and options.nocache
        if nocache:
            LOGGER.debug("--nocache flag detected, forcing temporary session creation")
        return nocache

    def _get_independent_credentials(self, options):
        """Extract username and password from options

        :param options: Command options object
        :returns: Tuple of (username, password)
        :rtype: tuple
        """
        global_encode = getattr(options, "encode", False)
        username = getattr(options, "user", None)
        password = getattr(options, "password", None)

        if global_encode:
            if username:
                username = self._decode_credential(username)
            if password:
                password = self._decode_credential(password)

        return username, password

    def _decode_credential(self, credential):
        """Decode an encoded credential"""
        try:
            decoded = Encryption.decode_credentials(credential)
            if isinstance(decoded, bytes):
                decoded = decoded.decode("utf-8")
            return decoded
        except Exception as exc:
            LOGGER.debug("Failed to decode credential: %s", str(exc))
            # Return original if decoding fails
            return credential

    def _get_ilo_version(self):
        """Get iLO version (wrapper for _detect_ilo_version)"""
        return self._detect_ilo_version()

    def _is_vnic_available(self):
        """Check if VNIC is available for the current iLO

        This is critical for iLO 5/6 which may or may not have VNIC enabled
        (VNIC is disabled by default on iLO 5 and iLO 6):
        - iLO 5/6 with VNIC: Use VNIC authentication
        - iLO 5/6 without VNIC: Use CHIF authentication
        - iLO 7: Always uses VNIC

        A bare TCP ``connect_ex`` to 16.1.15.1:443 is not sufficient: on iLO
        5/6 with VNIC disabled (the default), something can still answer the
        TCP SYN at the OS/network level even though no HTTPS/redfish service
        is actually listening, which falsely reports VNIC as available. That
        false positive misleads customers (log claims VNIC is in use when it
        is not) and previously caused the caller to attempt a real VNIC login
        that stalled for up to ``HTTP_TIMEOUT_SECONDS`` (60s) before falling
        back to CHIF. To avoid both problems, this probe also completes a TLS
        handshake, which only succeeds when a genuine HTTPS/redfish service is
        actually listening.

        The probe result is memoized on the instance. A single raw-command
        invocation can consult VNIC availability many times — most notably a
        multi-path ``rawpatch``/``rawpost``/``rawput`` that loops
        ``_execute_main_flow`` once per path — and each probe is a blocking
        check against ``16.1.15.1`` that costs up to a couple seconds when
        VNIC is disabled. Caching it makes the probe happen once per
        invocation instead of once per path. VNIC availability cannot change
        within a single sub-second CLI run, so the cached value is always
        accurate.

        :returns: True if VNIC is available, False otherwise
        :rtype: bool
        """
        # Return the memoized result when this invocation already probed VNIC.
        if self._vnic_available_cache is not None:
            LOGGER.debug("Using memoized VNIC availability: %s", self._vnic_available_cache)
            return self._vnic_available_cache

        vnic_available = False
        sock = None
        try:
            # Quick probe to check if a real HTTPS/redfish service is listening
            # on the VNIC endpoint (not just a bare TCP responder).
            import socket
            import ssl

            vnic_host = self.DEFAULT_ILO_URL.replace("https://", "").replace("http://", "")
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(VNIC_PROBE_TIMEOUT_SECONDS)
            sock.connect((vnic_host, 443))

            # Wrap with TLS: on iLO 5/6 with VNIC disabled, a TCP-only
            # responder either resets the connection or never completes the
            # handshake, so this raises/times out instead of falsely
            # succeeding like a bare connect_ex would.
            context = ssl._create_unverified_context()
            tls_sock = context.wrap_socket(sock, server_hostname=vnic_host)
            tls_sock.close()
            sock = None  # already closed via tls_sock
            vnic_available = True
        except Exception as e:
            LOGGER.debug("VNIC availability check failed: %s, assuming not available", e)
            vnic_available = False
        finally:
            if sock is not None:
                sock.close()

        if vnic_available:
            LOGGER.debug("VNIC is available on this iLO")
        else:
            LOGGER.debug("VNIC is not available - will use CHIF")

        self._vnic_available_cache = vnic_available
        return vnic_available

    def _is_high_security_mode(self):
        """Check if iLO is in high security mode"""
        # Use cached security state if available to avoid a redundant getilover_beforelogin() call.
        # _security_state_memory_cache is populated by _perform_getilover_detection() during
        # iLO version detection, so checking it here avoids a second round-trip to iLO.
        if RawCommandBase._security_state_memory_cache is not None:
            sec_state = RawCommandBase._security_state_memory_cache
            LOGGER.debug("Using cached security state: %s", sec_state)
            return sec_state in [4, 5, 6]

        try:
            return self._check_security_state()
        except Exception as e:
            LOGGER.debug("Could not determine security mode: %s", e)
        return False

    def _check_security_state(self):
        """Check security state via getilover_beforelogin"""
        from redfish.hpilo.vnichpilo import AppAccount

        if not self._can_check_security_state():
            return False

        app_obj = AppAccount(log_dir=self.rdmc.log_dir if self.rdmc else None)
        _, sec_state = self.rdmc.app.getilover_beforelogin(app_obj)

        # Cache security state so subsequent calls (e.g. _is_high_security_mode) skip this call
        RawCommandBase._security_state_memory_cache = sec_state

        # States 4=HighSecurity, 5=FIPS, 6=SuiteB require credentials
        return sec_state in [4, 5, 6]

    def _can_check_security_state(self):
        """Check if we can query security state"""
        return self.rdmc and self.rdmc.app and hasattr(self.rdmc.app, "getilover_beforelogin")

    def _check_ilo7_app_account(self):
        """Check if iLO7 app account is available

        This method uses a two-tier approach:
        1. Try using the app layer's token_exists() method (fast, requires initialized app)
        2. Fallback to direct AppAccount check (works even without app initialization)

        :returns: True if app account exists, False otherwise
        :rtype: bool
        """
        # Tier 1: Try using app layer method (fast path when app is initialized)
        try:
            if self.rdmc and self.rdmc.app and hasattr(self.rdmc.app, "token_exists"):
                # Serialize TPM access across concurrent ilorest processes — token_exists
                # touches the global TPM named semaphore (see TpmFileLock docstring).
                with TpmFileLock():
                    result = self.rdmc.app.token_exists()
                if result:
                    LOGGER.debug("App account found via app layer token_exists()")
                    return True
        except Exception as e:
            LOGGER.debug("App layer token_exists() check failed: %s", e)

        # Tier 2: Fallback to direct AppAccount check (works in service mode)
        try:
            from redfish.hpilo.vnichpilo import AppAccount

            log_dir = self.rdmc.log_dir if (self.rdmc and hasattr(self.rdmc, "log_dir")) else None
            app_obj = AppAccount(log_dir=log_dir)

            # Set iLO generation explicitly if known to prevent CHIF detection
            ilo_version = self._detect_ilo_version()
            if ilo_version:
                app_obj.ilo_gen = int(ilo_version)

            # Try to check using app_obj directly with the rdmc.app method
            if self.rdmc and self.rdmc.app:
                # Serialize TPM access across concurrent ilorest processes.
                with TpmFileLock():
                    result = self.rdmc.app.token_exists(app_obj)
                if result:
                    LOGGER.debug("App account found via direct AppAccount check")
                    return True

        except Exception as e:
            LOGGER.debug("Direct AppAccount check failed: %s", e)

        LOGGER.debug("No app account found after all checks")
        return False

    def _handle_high_security_auth(self, options, use_inband, auth_result):
        """Handle authentication for high security mode"""
        LOGGER.debug("High security/production mode detected - explicit credentials required")
        username, password = self._get_independent_credentials(options)

        if username and password:
            auth_result["auth"] = (username, password)
            auth_result["auth_type"] = "credentials"
            auth_result["need_logout"] = not use_inband
            LOGGER.debug("Using explicit credentials for high security mode")
        else:
            LOGGER.debug("High security mode requires credentials but none provided")

        return tuple(auth_result.values())

    def _handle_ilo7_vnic_auth(self, options, auth_result):
        """Handle iLO 6/7 VNIC mode authentication.

        Credential precedence (customer requirement): on iLO7+, explicitly
        supplied ``-u``/``-p`` credentials always take precedence over app-account
        authentication. When credentials are present they are used directly and the
        app account is **never** validated (which would touch the TPM) before the
        raw operation. Only when no credentials are supplied do we fall back to the
        app account.
        """
        ilo_version = self._get_ilo_version()

        # iLO7+ credential precedence: resolve explicit credentials FIRST so no
        # app-account (TPM) validation runs before the raw operation.
        if ilo_version and ilo_version >= 7:
            username, password = self._get_independent_credentials(options)
            if username and password:
                LOGGER.debug(
                    "iLO7+ explicit credentials supplied - using credentials and " "bypassing app-account validation"
                )
                return self._use_vnic_credential_auth(options, auth_result)

        # Check app account (Only available in iLO 7+)
        if self._should_use_app_account(ilo_version):
            return self._use_app_account_auth(auth_result)

        # iLO 6/7 VNIC no_app_account mode (Fallback to credentials)
        return self._use_vnic_credential_auth(options, auth_result)

    def _should_use_app_account(self, ilo_version):
        """Check if app account authentication should be used"""
        if ilo_version and ilo_version >= 7:
            return self._check_ilo7_app_account()
        return False

    def _use_app_account_auth(self, auth_result):
        """Configure authentication result for app account"""
        auth_result["auth_type"] = "appaccount"
        auth_result["need_logout"] = False
        LOGGER.debug("Using iLO7 app account authentication")
        return tuple(auth_result.values())

    def _use_vnic_credential_auth(self, options, auth_result):
        """Configure authentication result for VNIC credential mode"""
        LOGGER.debug("iLO VNIC mode (no app account/iLO6) - explicit credentials required")
        username, password = self._get_independent_credentials(options)

        if username and password:
            auth_result["auth"] = (username, password)
            auth_result["auth_type"] = "credentials"
            auth_result["need_logout"] = False
            LOGGER.debug("Using credentials for iLO VNIC no_app_account mode")
            return tuple(auth_result.values())

        return None

    def _try_cached_session_auth(self, options, auth_result):
        """Try to use cached session for authentication"""
        session_token = self._get_cached_session_token(options)

        if not session_token:
            return None

        auth_result["session_token"] = session_token
        auth_result["need_logout"] = False
        auth_result["auth_type"] = "cached_session"
        LOGGER.debug("Using cached session token for RAW operation")

        # Prepare fallback credentials
        username, password = self._get_independent_credentials(options)
        if username and password:
            auth_result["fallback_auth"] = (username, password)
            LOGGER.debug("Fallback credentials prepared for cached session failure")

        return tuple(auth_result.values())

    def _handle_credential_auth(self, options, use_inband, auth_result):
        """Handle credential-based authentication"""
        username, password = self._get_independent_credentials(options)

        if not username or not password:
            return tuple(auth_result.values())

        auth_result["auth"] = (username, password)
        auth_result["auth_type"] = "credentials"

        if use_inband:
            auth_result["need_logout"] = False
            LOGGER.debug("Using credentials for inband authentication")
        else:
            auth_result["need_logout"] = True
            LOGGER.debug("Credentials available for network authentication")

        return tuple(auth_result.values())

    def _setup_authentication_service_mode(self, options, url=None, use_inband=False):
        """Enhanced authentication setup optimized for service mode operations

        This addresses the excessive requests issue by bypassing application layer
        dependencies when in service mode.

        :param options: Command options
        :param url: Target URL
        :param use_inband: Whether using inband communication
        :returns: tuple of (auth, session_token, need_logout, auth_type, fallback_auth)
        """
        is_service_mode = getattr(options, "service", False)

        if is_service_mode:
            LOGGER.debug("Service mode authentication: optimized for minimal requests")
            # Service mode: always create independent session, never use cached
            auth = None
            session_token = None
            need_logout = False
            auth_type = "none"
            fallback_auth = None

            # For service mode, we need credentials to create independent session
            username, password = self._get_independent_credentials(options)
            if username and password:
                auth = (username, password)
                auth_type = "credentials"
                need_logout = True  # Service mode sessions should be cleaned up
                LOGGER.debug("Service mode: using independent credentials")
            else:
                # Service mode requires explicit authentication
                LOGGER.debug("Service mode: no credentials available")

            return auth, session_token, need_logout, auth_type, fallback_auth
        else:
            # Non-service mode: use full 6-scenario framework
            return self._setup_authentication(options, url, use_inband)

    def _create_temp_session(self, url, credentials):
        """Create temporary session for network communication (Scenario 2)

        :param url: Base URL for session creation
        :param credentials: Tuple of (username, password)
        :returns: Tuple of (session_token, session_location) or (None, None)
        """
        return self._create_temporary_session(url, credentials, return_location=True)

    def _build_session_service_url(self, url):
        """Build SessionService URL from base URL

        :param url: Base URL
        :type url: str
        :returns: SessionService URL
        :rtype: str
        """
        return f"{url}/redfish/v1/SessionService/Sessions/"

    def _get_session_headers(self, response):
        """Extract session token and location from a session response

        :param response: HTTP response object
        :returns: Tuple of (session_token, session_location)
        :rtype: tuple
        """
        session_token = response.headers.get("X-Auth-Token")
        session_location = response.headers.get("Location")
        return session_token, session_location

    def _create_temporary_session(self, url, auth, return_location=False):
        """Create temporary session for network communication

        :param url: Base URL
        :param auth: Tuple of (username, password)
        :param return_location: Whether to also return the session location
        :returns: Session token or (session_token, session_location)
        :rtype: str or None or tuple
        """
        if not self._validate_temp_session_auth(auth):
            return (None, None) if return_location else None

        try:
            return self._perform_session_creation(url, auth, return_location)
        except Exception as e:
            LOGGER.error("Exception during temporary session creation: %s", e)
            return (None, None) if return_location else None

    def _validate_temp_session_auth(self, auth):
        """Validate authentication tuple for temporary session"""
        if not auth or len(auth) != 2:
            LOGGER.error("Invalid credentials for temporary session")
            return False
        return True

    def _perform_session_creation(self, url, auth, return_location):
        """Perform the HTTP request to create a session

        Uses a PQC-aware requests session so iLO7 connections benefit from
        hybrid PQC TLS and iLO8+ connections from strict PQC TLS.
        """
        username, password = auth
        session_url = self._build_session_service_url(url)
        session_data = {"UserName": username, "Password": password}

        session = self._get_requests_session_with_pqc(target_url=url)
        try:
            response = session.post(session_url, json=session_data, verify=False, timeout=HTTP_TIMEOUT_SECONDS)
        finally:
            session.close()

        if response.status_code in [200, 201]:
            return self._handle_successful_session_creation(response, return_location)

        LOGGER.error("Failed to create temporary session: HTTP %s", response.status_code)
        return (None, None) if return_location else None

    def _handle_successful_session_creation(self, response, return_location):
        """Extract tokens from successful session response"""
        session_token, session_location = self._get_session_headers(response)

        if session_token:
            LOGGER.debug("Temporary session created")
            if return_location:
                return session_token, session_location
            return session_token

        return (None, None) if return_location else None

    def _cleanup_session_if_needed(self, need_logout, session_location, auth_type):
        """Cleanup temporary sessions while preserving cached sessions (Scenario 6)

        :param need_logout: Whether logout is needed
        :param session_location: Session location URL for deletion
        :param auth_type: Type of authentication used
        """
        if need_logout and session_location and auth_type == "credentials":
            self._delete_session_location(session_location)

    def _logout_temp_session(self, session_location, session_token):
        """Logout temporary session created by RAW command (Scenario 6)

        :param session_location: Session location URL
        :param session_token: Session token for identification
        """
        if session_location:
            self._delete_session_location(session_location, session_token=session_token)

    def _delete_session_location(self, session_location, session_token=None, timeout=HTTP_TIMEOUT_SECONDS):
        """Delete a session using its location URL

        :param session_location: Session location URL
        :param session_token: Optional session token for authorization
        :param timeout: Request timeout in seconds
        :returns: True if delete succeeded or session missing, False otherwise
        :rtype: bool
        """
        if not session_location:
            return False

        try:
            headers = {"X-Auth-Token": session_token} if session_token else {}
            session = self._get_requests_session_with_pqc(target_url=session_location)
            try:
                response = session.delete(session_location, headers=headers, verify=False, timeout=timeout)
            finally:
                session.close()
            if response.status_code in [200, 204, 404]:
                LOGGER.debug("Temporary session successfully cleaned up")
                return True

            LOGGER.warning("Session cleanup returned status: %s", response.status_code)
            return False
        except Exception as e:
            LOGGER.warning("Session cleanup failed: %s", e)
            return False

    def _handle_cached_session_failure(self, url, fallback_auth, use_inband):
        """Handle cached session failure with fallback retry (Scenario 4)

        :param url: Base URL
        :param fallback_auth: Fallback credentials tuple
        :param use_inband: Whether using inband communication
        :returns: Tuple of (new_session_token, session_location, need_cleanup)
        """
        if not fallback_auth:
            LOGGER.debug("No fallback credentials available for retry")
            return None, None, False

        LOGGER.debug("Cached session failed with 401, attempting fallback")

        if not use_inband:
            # Create temporary session with fallback credentials (Scenario 4)
            temp_session_token, temp_session_location = self._create_temp_session(url, fallback_auth)
            if temp_session_token:
                LOGGER.debug("Created fallback session, ready for retry")
                return temp_session_token, temp_session_location, True

        return None, None, False

    def _build_http_request(self, method, path, auth_header, body_str=None):
        """Build HTTP/1.1 request string

        :param method: HTTP method
        :type method: str
        :param path: Request path
        :type path: str
        :param auth_header: Authorization header
        :type auth_header: str
        :param body_str: Optional request body
        :type body_str: str or None
        :returns: HTTP request string
        :rtype: str
        """
        req_data = f"{method.upper()} {path} HTTP/1.1\r\n"
        req_data += "Host: localhost\r\n"
        req_data += auth_header

        if body_str:
            req_data += "Content-Type: application/json\r\n"
            req_data += f"Content-Length: {len(body_str)}\r\n"
            req_data += "\r\n"
            req_data += body_str
        else:
            req_data += "Content-Length: 0\r\n"
            req_data += "\r\n"

        return req_data

    def _encode_request_data(self, req_data):
        """Encode request data to bytes

        :param req_data: Request data as string or bytearray
        :type req_data: str or bytearray
        :returns: Encoded request data as bytes
        :rtype: bytes
        """
        if isinstance(req_data, str):
            return req_data.encode("utf-8")
        elif isinstance(req_data, bytearray):
            return bytes(req_data)
        return req_data

    def _decode_response_data(self, response_data):
        """Decode response data from bytes to string

        CHIF/``rest_immediate`` responses for large payloads (e.g. big Redfish
        collections/registries) may be gzip-compressed by iLO even though the
        outgoing CHIF request never sent an ``Accept-Encoding`` header.
        Blindly UTF-8-decoding such a response fails with a
        ``UnicodeDecodeError`` on the first non-UTF8 byte of the compressed
        body (the gzip magic number ``\\x1f\\x8b``), which previously
        surfaced as a generic "CHIF rawget execution failed" 500 error. Split
        the raw bytes into headers/body first, and gunzip the body when
        ``Content-Encoding: gzip`` is present before decoding it as text.

        :param response_data: Response data as bytes, bytearray, or string
        :returns: Decoded response as string
        :rtype: str
        """
        if response_data is None:
            return ""
        if not isinstance(response_data, (bytes, bytearray)):
            return response_data

        response_bytes = bytes(response_data)
        header_sep = b"\r\n\r\n"
        if header_sep not in response_bytes:
            # No HTTP header section detected (e.g. plain JSON body); fall
            # back to the previous behavior.
            return response_bytes.decode("utf-8")

        header_bytes, _, body_bytes = response_bytes.partition(header_sep)
        header_str = header_bytes.decode("ascii")

        if re.search(r"(?im)^content-encoding:\s*gzip\s*$", header_str) and body_bytes:
            try:
                body_bytes = gzip.decompress(body_bytes)
            except OSError as gzip_err:
                LOGGER.error(
                    "Failed to gunzip CHIF response body (Content-Encoding: gzip): %s",
                    gzip_err,
                )
                # Fall through and attempt to decode the raw bytes anyway so
                # the caller at least gets *something* actionable logged.

        body_str = body_bytes.decode("utf-8", errors="replace")
        return header_str + "\r\n\r\n" + body_str

    def _extract_status_from_http(self, response_data):
        """Extract HTTP status code from response

        :param response_data: HTTP response string
        :type response_data: str
        :returns: Status code
        :rtype: int
        """
        if not (isinstance(response_data, str) and response_data.startswith("HTTP/")):
            return 200

        status_line = response_data.split("\r\n")[0]
        status_parts = status_line.split(" ", 2)

        if len(status_parts) >= 2:
            try:
                return int(status_parts[1])
            except (ValueError, TypeError):
                pass

        return 200

    def _parse_http_response(self, response_data):
        """Parse HTTP response to extract status and data

        :param response_data: Raw HTTP response string
        :type response_data: str
        :returns: Tuple of (status, data)
        :rtype: tuple
        """
        if not response_data:
            return (500, {"error": "Empty or null response received from server"})

        if self._is_raw_http_response(response_data):
            return self._parse_raw_http_string(response_data)

        return self._parse_json_response(response_data)

    def _is_raw_http_response(self, response_data):
        """Check if data looks like a raw HTTP response"""
        return isinstance(response_data, str) and "\r\n\r\n" in response_data

    def _parse_raw_http_string(self, response_data):
        """Parse raw HTTP response string and capture response headers."""
        parts = response_data.split("\r\n\r\n", 1)
        status = self._extract_status_from_http(parts[0])
        # Capture response headers so --getheaders works for in-band CHIF requests.
        self._last_chif_headers = self._extract_response_headers(parts[0])
        data = None
        if len(parts) > 1:
            data = self._try_parse_json(parts[1])
        return status, data

    def _extract_response_headers(self, header_section):
        """Parse HTTP response headers section into a dict, skipping the status line."""
        headers = {}
        for line in header_section.split("\r\n")[1:]:
            if ":" in line:
                key, _, val = line.partition(":")
                headers[key.strip()] = val.strip()
        return headers

    def _parse_json_response(self, response_data):
        """Parse JSON response data"""
        data = self._try_parse_json(response_data)
        return 200, data

    def _try_parse_json(self, text):
        """Try to parse text as JSON, return original text on failure"""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
        except TypeError:
            return text

    def _build_auth_header(self, username, password):
        """Build HTTP Basic Authentication header

        WARNING: Never log the returned header as it contains encoded credentials.
        While Base64 encoding is not encryption, the header can be easily decoded.

        :param username: Username
        :type username: str or None
        :param password: Password
        :type password: str or None
        :returns: Authorization header string
        :rtype: str
        """
        if not (username and password):
            return ""

        from ctypes import byref, c_char_p, create_string_buffer

        from redfish.hpilo import risblobstore2

        # Ensure credentials are strings
        username_str = username if isinstance(username, str) else str(username)
        password_str = password if isinstance(password, str) else str(password)

        credentials = f"{username_str}:{password_str}"

        # Use CHIF encode_credentials instead of base64
        lib = risblobstore2.BlobStore2.gethprestchifhandle()
        credbuff = create_string_buffer(credentials.encode("utf-8"))
        retbuff = create_string_buffer(128)

        lib.encode_credentials.argtypes = [c_char_p]
        lib.encode_credentials(credbuff, byref(retbuff))

        risblobstore2.BlobStore2.unloadchifhandle(lib)

        encoded_credentials = retbuff.value
        if isinstance(encoded_credentials, bytes):
            encoded_credentials = encoded_credentials.decode("utf-8")

        return f"Authorization: Basic {encoded_credentials}\r\n"

    def _decode_session_token(self, session_token):
        """Decode session token from cache if it was encoded

        iLORest encodes session tokens using CHIF DLL's encode_credentials when
        self.rdmc.encoding is True. This function decodes them using decode_credentials.

        :param session_token: Encoded or plain session token from cache
        :type session_token: str
        :returns: Decoded session token
        :rtype: str
        """
        if not session_token:
            return session_token

        # Try to decode using CHIF DLL's decode_credentials function
        try:
            from ctypes import byref, c_char_p, create_string_buffer

            from redfish.hpilo import risblobstore2

            lib = risblobstore2.BlobStore2.gethprestchifhandle()
            credbuff = create_string_buffer(session_token.encode("utf-8"))
            retbuff = create_string_buffer(128)

            lib.decode_credentials.argtypes = [c_char_p]
            lib.decode_credentials(credbuff, byref(retbuff))

            risblobstore2.BlobStore2.unloadchifhandle(lib)

            decoded = retbuff.value
            if isinstance(decoded, bytes):
                decoded = decoded.decode("utf-8", "ignore")

            if decoded:
                LOGGER.debug("Successfully decoded session token using CHIF DLL")
                return decoded
            else:
                # Decoding returned empty - use original
                LOGGER.debug("Decoding returned empty, using original token")
                return session_token

        except Exception as e:
            # If decoding fails, the token might already be in plain text (encoding disabled)
            LOGGER.debug("Could not decode with CHIF DLL (encoding may be disabled): %s", str(e))
            return session_token

    def _ensure_bytes(self, value):
        """Ensure a value is converted to bytes

        :param value: Value to convert (str, bytes, or other)
        :type value: str or bytes or any
        :returns: Value as bytes
        :rtype: bytes
        """
        if isinstance(value, bytes):
            return value
        if isinstance(value, str):
            return value.encode("utf-8")
        return str(value).encode("utf-8")

    def _handle_manual_chif_init(self, username, password, BlobStore2, BlobReturnCodes):
        """Handle manual CHIF initialization when standard init fails"""

        dll = BlobStore2.gethprestchifhandle()
        dll.ChifInitialize(None)

        sec_support = self._get_chif_security_support(dll)
        if sec_support <= 1:
            dll.ChifEnableSecurity()

        self._init_chif_credentials_low_level(dll, username, password)

        if sec_support <= 1:
            self._verify_chif_credentials_manual(dll, BlobStore2, BlobReturnCodes)

    def _get_chif_security_support(self, dll):
        """Get security support level"""
        try:
            return dll.ChifGetSecuritySupport()
        except Exception:
            return 0

    def _init_chif_credentials_low_level(self, dll, username, password):
        """Initialize credentials using low-level DLL calls"""
        from ctypes import POINTER, c_char_p, c_ubyte, create_string_buffer

        dll.initiate_credentials.argtypes = [c_char_p, c_char_p]
        # noinspection PyTypeChecker
        # pylint: disable=no-member
        dll.initiate_credentials.restype = POINTER(c_ubyte)  # type: ignore[assignment,misc]

        username_bytes = self._ensure_bytes(username)
        password_bytes = self._ensure_bytes(password)

        usernew = create_string_buffer(username_bytes)
        passnew = create_string_buffer(password_bytes)

        dll.initiate_credentials(usernew, passnew)

    def _verify_chif_credentials_manual(self, dll, BlobStore2, BlobReturnCodes):
        """Verify credentials manually"""
        credreturn = dll.ChifVerifyCredentials()
        if credreturn != 0:
            BlobStore2.unloadchifhandle(dll)
            if credreturn == BlobReturnCodes.CHIFERR_AccessDenied:
                raise Exception("Authentication failed: Invalid credentials for High Security mode")
            else:
                raise Exception(f"Chif credential validation failed with error code: {credreturn}")

    def _get_or_create_blobstore(self, risblobstore2):
        """Get existing or create new BlobStore2 instance

        :param risblobstore2: risblobstore2 module
        :returns: BlobStore2 instance
        """
        # 1. Check for persistent instance at module level (shared across instances)
        persistent_bs2 = self._get_module_blobstore(risblobstore2)
        if persistent_bs2:
            return persistent_bs2

        # 2. Check for instance variable (local to this instance)
        if self._has_valid_instance_blobstore():
            bs2 = self._bs2_instance
            self._set_module_blobstore(risblobstore2, bs2)
            return bs2

        # 3. Create new instance
        return self._create_new_blobstore(risblobstore2)

    def _get_module_blobstore(self, risblobstore2):
        """Get persistent BlobStore2 instance from module"""
        persistent_instance = getattr(risblobstore2, "_persistent_bs2_instance", None)  # pylint: disable=no-member
        if persistent_instance is not None:
            if not hasattr(self, "_bs2_instance"):
                self._bs2_instance = persistent_instance
            return persistent_instance
        return None

    def _has_valid_instance_blobstore(self):
        """Check if self has a valid BlobStore2 instance"""
        return hasattr(self, "_bs2_instance") and self._bs2_instance is not None

    def _set_module_blobstore(self, risblobstore2, bs2):
        """Set persistent BlobStore2 instance on module"""
        if not hasattr(risblobstore2, "_persistent_bs2_instance"):
            setattr(risblobstore2, "_persistent_bs2_instance", bs2)  # pylint: disable=no-member

    def _create_new_blobstore(self, risblobstore2):
        """Create a new BlobStore2 instance and register it"""
        bs2 = risblobstore2.BlobStore2()
        self._bs2_instance = bs2
        setattr(risblobstore2, "_persistent_bs2_instance", bs2)  # pylint: disable=no-member
        return bs2

    def _extract_status_from_exception(self, exception):
        """Extract HTTP status code from exception message

        :param exception: Exception object
        :returns: HTTP status code
        :rtype: int
        """
        error_str = str(exception)

        # Try regex extraction first
        status = self._try_regex_status_extraction(error_str)
        if status:
            return status

        # Try common status code detection
        status = self._detect_common_status_codes(error_str)
        if status:
            return status

        # Default to 500
        return 500

    def _try_regex_status_extraction(self, error_str):
        """Try to extract status code using regex"""
        import re

        if "status" not in error_str.lower():
            return None

        status_match = re.search(r"status[:\s]+(\d+)", error_str, re.IGNORECASE)
        if status_match:
            try:
                return int(status_match.group(1))
            except ValueError:
                pass

        return None

    def _detect_common_status_codes(self, error_str):
        """Detect common HTTP status codes from error message"""
        error_lower = error_str.lower()

        # Map error patterns to status codes
        status_patterns = [
            (("404", "not found"), 404),
            (("401", "unauthorized"), 401),
            (("403", "forbidden"), 403),
            (("400", "bad request"), 400),
            (("500", "internal server error"), 500),
            (("503", "service unavailable"), 503),
        ]

        for patterns, status_code in status_patterns:
            if any(pattern in error_str or pattern in error_lower for pattern in patterns):
                return status_code

        return None

    def _read_cached_session_from_file(self):
        """Read cached session token from file/cache

        Only returns a session if it's from an actively logged-in instance.
        Does not return expired/stale sessions.

        Checks two sources:
        1. In-memory rdmc.app.redfishinst (fastest)
        2. Persistent cache file (survives process restarts)

        :returns: Tuple of (session_token, is_chif)
        :rtype: tuple
        """
        # Try in-memory cache first
        result = self._try_inmemory_session_cache()
        if result[0]:
            return result

        # Try persistent file cache
        result = self._try_persistent_session_cache()
        if result[0]:
            return result

        # No active session found
        LOGGER.debug("No cached session found")
        return None, False

    def _try_inmemory_session_cache(self):
        """Try to get session from in-memory rdmc app cache"""
        try:
            inst = self._get_redfish_instance()
            if not inst:
                return None, False

            # Check for CHIF session
            chif_result = self._check_for_chif_session(inst)
            if chif_result[0]:
                return chif_result

            # Check for HTTP session
            http_result = self._check_for_http_session(inst)
            if http_result[0]:
                return http_result

            LOGGER.debug("Found redfishinst but no active session markers")
            return None, False

        except Exception as e:
            LOGGER.debug("Failed to read cached session from rdmc app: %s", e)
            return None, False

    def _get_redfish_instance(self):
        """Get Redfish instance from RDMC app"""
        if not (self.rdmc and self.rdmc.app and hasattr(self.rdmc.app, "redfishinst")):
            return None
        return self.rdmc.app.redfishinst

    def _check_for_chif_session(self, inst):
        """Check if instance has an active CHIF session"""
        if not (hasattr(inst, "base_url") and inst.base_url):
            return None, False

        base_url = str(inst.base_url)
        if "blobstore" in base_url:
            LOGGER.debug("Found active CHIF session from rdmc app (blobstore URL)")
            return "CHIF_SESSION", True

        return None, False

    def _check_for_http_session(self, inst):
        """Check if instance has an active HTTP session"""
        if not (hasattr(inst, "session_key") and hasattr(inst, "_session_location")):
            return None, False

        token = inst.session_key
        session_loc = inst._session_location

        if token and session_loc:
            LOGGER.debug("Found active cached session token from rdmc app")
            return token, False

        LOGGER.debug("Found redfishinst but session is not active (missing token or location)")
        return None, False

    def _try_persistent_session_cache(self):
        """Try to get session from persistent file cache"""
        try:
            session_token = self._load_session_from_cache_file()
            if session_token:
                LOGGER.debug("Found session token in persistent cache file")
                return session_token, False
        except Exception as e:
            LOGGER.debug("Failed to read session from cache file: %s", e)

        return None, False

    def _get_session_cache_file_path(self):
        """Get the path to the session cache directory

        :returns: Path to cache directory or None
        :rtype: str or None
        """

        # Try to use iLORest cache directory if available
        rdmc_cache = self._get_rdmc_cache_dir()
        if rdmc_cache:
            return rdmc_cache

        # Fallback to home directory
        return self._get_default_session_cache_path()

    def _get_default_session_cache_path(self):
        """Get default session cache path in home directory"""
        import os

        home_dir = os.path.expanduser("~")
        cache_dir = os.path.join(home_dir, ".iLORest", "cache")

        # Create directory with secure permissions
        try:
            if not os.path.exists(cache_dir):
                os.makedirs(cache_dir, mode=0o700)  # Secure permissions
            return cache_dir
        except Exception as e:
            LOGGER.debug("Could not create session cache directory: %s", e)
            return None

    def _load_session_from_cache_file(self):
        """Load encrypted session token from persistent cache file

        Reads from cache index file and session data files.
        Returns None if cache expired or invalid.

        :returns: Session token or None
        :rtype: str or None
        """
        try:
            cache_dir = self._get_session_cache_file_path()
            if not cache_dir:
                return None

            # Load session entry from index
            cache_file_name = self._load_session_entry_from_index(cache_dir)
            if not cache_file_name:
                return None

            # Load session data from cache file
            session_data = self._load_session_data_from_file(cache_dir, cache_file_name)
            if not session_data:
                return None

            # Validate and return session
            return self._validate_and_decode_session(session_data, cache_dir, cache_file_name)

        except Exception as e:
            LOGGER.debug("Failed to load session from cache: %s", e)
            return None

    def _load_session_entry_from_index(self, cache_dir):
        """Load session entry from cache index file"""
        import json
        import os

        index_file = os.path.join(cache_dir, "index")
        if not os.path.exists(index_file):
            LOGGER.debug("Session cache index file not found")
            return None

        with open(index_file, "r") as f:
            index_data = json.load(f)

        if not isinstance(index_data, list) or len(index_data) == 0:
            LOGGER.debug("Session cache index empty or invalid")
            return None

        session_entry = index_data[0]
        cache_file_name = session_entry.get("href")

        if not cache_file_name:
            LOGGER.debug("No session cache file reference in index")
            return None

        return cache_file_name

    def _load_session_data_from_file(self, cache_dir, cache_file_name):
        """Load session data from cache file"""
        import json
        import os

        cache_file = os.path.join(cache_dir, cache_file_name)
        if not os.path.exists(cache_file):
            LOGGER.debug("Session cache file not found: %s", cache_file_name)
            return None

        with open(cache_file, "r") as f:
            cache_data = json.load(f)

        login_data = cache_data.get("login", {})
        session_key = login_data.get("session_key")
        session_time = login_data.get("timestamp", 0)

        if not session_key:
            LOGGER.debug("No session key in cache file")
            return None

        return {"session_key": session_key, "timestamp": session_time, "cache_file": cache_file}

    def _validate_and_decode_session(self, session_data, cache_dir, cache_file_name):
        """Validate session expiration and decode token"""
        import time

        session_key = session_data["session_key"]
        session_time = session_data["timestamp"]
        cache_file = session_data["cache_file"]

        # Check expiration (30 minutes)
        current_time = time.time()
        session_age = current_time - session_time

        if session_age > 1800:
            LOGGER.debug("Cached session expired (age: %ss)", format(session_age, ".0f"))
            self._cleanup_expired_cache(cache_dir, cache_file_name, cache_file)
            return None

        # Decrypt/decode session token
        return self._decode_cached_session_key(session_key, session_age)

    def _cleanup_expired_cache(self, cache_dir, cache_file_name, cache_file):
        """Clean up expired cache files"""
        import os

        try:
            os.remove(cache_file)
            index_file = os.path.join(cache_dir, "index")
            os.remove(index_file)
        except Exception:
            pass

    def _decode_cached_session_key(self, session_key, session_age):
        """Decode cached session key using CHIF decode_credentials"""
        from ctypes import byref, c_char_p, create_string_buffer

        from redfish.hpilo import risblobstore2

        try:
            lib = risblobstore2.BlobStore2.gethprestchifhandle()
            credbuff = create_string_buffer(session_key.encode("utf-8"))
            retbuff = create_string_buffer(128)

            lib.decode_credentials.argtypes = [c_char_p]
            lib.decode_credentials(credbuff, byref(retbuff))

            risblobstore2.BlobStore2.unloadchifhandle(lib)

            decoded_token = retbuff.value
            if isinstance(decoded_token, bytes):
                decoded_token = decoded_token.decode("utf-8")

            if decoded_token:
                LOGGER.debug("Loaded valid session from cache (age: %ss)", format(session_age, ".0f"))
                return decoded_token
            else:
                # Decoding returned empty (CHIF unavailable or not encoded) — use original
                LOGGER.debug("Decoding returned empty, using original session key")
                return session_key
        except Exception:
            LOGGER.debug("Loaded session from cache (age: %ss)", format(session_age, ".0f"))
            return session_key

    def _save_session_to_cache_file(self, session_token, url=None):
        """Save encrypted session token to persistent cache file

        :param session_token: Session token to cache
        :type session_token: str
        :param url: URL associated with session (defaults to DEFAULT_ILO_URL)
        :type url: str
        """
        import hashlib
        import json
        import os
        import time
        from ctypes import byref, c_char_p, create_string_buffer

        from redfish.hpilo import risblobstore2

        # Use default iLO URL if not provided
        if url is None:
            url = self.DEFAULT_ILO_URL

        try:
            cache_dir = self._get_session_cache_file_path()
            if not cache_dir:
                LOGGER.debug("Could not determine cache directory")
                return

            # Generate cache file name from URL hash
            url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
            cache_file_name = f"{url_hash}.json"
            cache_file = os.path.join(cache_dir, cache_file_name)

            # Encrypt session token using CHIF encode_credentials
            try:
                lib = risblobstore2.BlobStore2.gethprestchifhandle()
                credbuff = create_string_buffer(session_token.encode("utf-8"))
                retbuff = create_string_buffer(128)

                lib.encode_credentials.argtypes = [c_char_p]
                lib.encode_credentials(credbuff, byref(retbuff))

                risblobstore2.BlobStore2.unloadchifhandle(lib)

                encrypted_token = retbuff.value
                if isinstance(encrypted_token, bytes):
                    encrypted_token = encrypted_token.decode("utf-8")
            except Exception:
                encrypted_token = session_token

            # Prepare cache data
            cache_data = {"login": {"session_key": encrypted_token, "url": url, "timestamp": time.time()}}

            # Write session cache file
            with open(cache_file, "w") as f:
                json.dump(cache_data, f)

            # Set secure permissions
            os.chmod(cache_file, 0o600)

            # Update index file
            index_file = os.path.join(cache_dir, "index")
            index_data = [{"href": cache_file_name, "url": url}]

            with open(index_file, "w") as f:
                json.dump(index_data, f)

            os.chmod(index_file, 0o600)

            LOGGER.debug("Saved session to cache file: %s", cache_file_name)

        except Exception as e:
            LOGGER.debug("Failed to save session to cache: %s", e)

    def _execute_chif_rawget(self, path, session_token=None, username=None, password=None, method="GET", body=None):
        """Execute a raw request via CHIF/BlobStore2

        Despite the historical ``rawget`` name, this executes any HTTP verb over
        CHIF. It defaults to ``GET`` with no body so existing GET callers are
        unaffected; RawPatchCommand passes ``method="PATCH"`` and a ``body``.

        :param path: Redfish path
        :param session_token: Optional session token (not used for CHIF)
        :param username: Optional username for high security mode
        :param password: Optional password for high security mode
        :param method: HTTP verb to send over CHIF (default "GET")
        :type method: str
        :param body: Optional request body for POST/PUT/PATCH (dict or str)
        :type body: dict or str or None
        :returns: Response data dict for success, or tuple (status_code, data) for all responses
        :rtype: dict or tuple(int, dict) or None
        """
        try:
            # Initialize CHIF session
            bs2 = self._initialize_chif_session(username, password)

            # Handle error responses from initialization
            if isinstance(bs2, tuple):
                # Tuple means error response (status_code, error_data)
                return bs2

            if not bs2:
                LOGGER.error("CHIF session initialization failed - BlobStore2 instance is None")
                return (
                    500,
                    {"error": {"message": "CHIF session initialization failed. System may require credentials."}},
                )

            # Build and execute request
            response_data = self._execute_chif_request(bs2, path, method=method, body=body)
            if not response_data:
                LOGGER.error("CHIF request returned no data")
                return (
                    500,
                    {
                        "error": {
                            "message": "CHIF request failed. System may be in high security mode requiring credentials."
                        }
                    },
                )

            # Parse and return response
            return self._process_chif_response(response_data, path)

        except Exception as e:
            LOGGER.error("CHIF rawget execution failed: %s", e)
            import traceback

            LOGGER.debug(traceback.format_exc())
            return (500, {"error": {"message": "CHIF rawget execution failed"}})

    def _initialize_chif_session(self, username, password):
        """Initialize CHIF session with credentials"""
        from redfish.hpilo.risblobstore2 import BlobStore2

        # Destroy existing instance for fresh state
        self._destroy_existing_blobstore()

        # Initialize credentials
        LOGGER.debug(
            "Calling initialize chif credentials with: username=%s, password=%s",
            self._mask_username(username),
            self._mask_simple_token(password),
        )
        cred_result = self._initialize_chif_credentials(username, password)
        if cred_result is False:
            return None
        if isinstance(cred_result, tuple):  # Error response
            return cred_result

        # Create BlobStore2 instance
        try:
            LOGGER.debug("Creating BlobStore2 instance")
            self._bs2_instance = BlobStore2()
            LOGGER.info("BlobStore2 instance created successfully")
            return self._bs2_instance
        except Exception as e:
            LOGGER.error("Failed to create BlobStore2 instance: %s", e)
            return None

    def _destroy_existing_blobstore(self):
        """Destroy existing BlobStore2 instance"""
        if self._bs2_instance:
            LOGGER.debug("Destroying existing BlobStore2 instance before initialization")
            try:
                del self._bs2_instance
            except Exception:
                pass
            self._bs2_instance = None

    def _initialize_chif_credentials(self, username, password):
        """Initialize CHIF credentials using BlobStore2.initializecreds"""

        # Reset the per-request invalid-credentials flag so it reflects only this
        # attempt (a prior request's rejection must not leak into this one).
        self._chif_invalid_credentials = False

        try:
            if username and password:
                LOGGER.debug(
                    "Calling high security credentials with username=%s, password=%s",
                    self._mask_username(username),
                    self._mask_simple_token(password),
                )
                return self._init_high_security_credentials(username, password)
            else:
                LOGGER.debug("Calling production mode credentials")
                return self._init_production_mode_credentials()
        except Exception as init_ex:
            LOGGER.error("BlobStore2.initializecreds raised exception: %s", init_ex)
            import traceback

            LOGGER.debug("initializecreds exception: %s", traceback.format_exc())
            return False

    def _init_high_security_credentials(self, username, password):
        """Initialize AND verify explicit credentials for a CHIF request.

        ``BlobStore2.initializecreds`` already performs the credential check itself:
        it calls ``initiate_credentials`` followed by ``ChifVerifyCredentials`` while
        security is still enabled, and only then calls ``ChifDisableSecurity`` in
        production mode. Re-running ``ChifVerifyCredentials`` here would query a fresh
        CHIF handle on which no credentials were ever initiated and for which security
        has already been disabled, so it would reject even valid credentials.

        A ``False`` return means the in-band pre-check rejected the supplied
        credentials, and it is always treated as a hard failure: when ``-u``/``-p`` are
        given they must be proven valid before the request runs, in every security mode.
        Accepting them here would hand the request to the passwordless blob path, which
        runs as the dynamic ``systemadministrator`` account and would let a wrong
        password silently succeed.

        Valid credentials never reach this fail-closed branch: an explicit-credential
        CHIF request first goes through :meth:`_perform_authenticated_chif_request`,
        whose ``RestClient`` blobstore login resolves the factory-vs-production
        ambiguity of the in-band pre-check (CCSE-148119) and succeeds. This method is
        only consulted on the fallback path, where no authenticated session could be
        established and therefore nothing can vouch for the credentials.

        :returns: ``True`` when the credentials are valid, or a ``(401, error_data)``
            tuple when they are invalid (surfaced as ``[401]`` to the caller).
        :rtype: bool or tuple
        """
        from redfish.hpilo.risblobstore2 import BlobStore2

        LOGGER.debug(
            "Calling BlobStore2.initializecreds(username=%s password=%s)",
            self._mask_username(username),
            self._mask_simple_token(password),
        )
        result = BlobStore2.initializecreds(username, password)

        if result is False:
            LOGGER.error("BlobStore2.initializecreds returned False - credentials invalid")
            self._chif_invalid_credentials = True
            return self._invalid_chif_credentials_response()

        LOGGER.info("CHIF credentials initialized and verified successfully")
        return True

    def _invalid_chif_credentials_response(self):
        """Build the canonical ``(401, error_data)`` response for invalid CHIF creds."""
        return (
            401,
            {
                "error": {
                    "code": "iLO.0.10.ExtendedInfo",
                    "message": "Invalid credentials. Unable to authenticate to iLO.",
                    "@Message.ExtendedInfo": [{"MessageId": "Base.1.18.InsufficientPrivilege"}],
                }
            },
        )

    def _init_production_mode_credentials(self):
        """Initialize credentials for production mode without credentials"""
        from redfish.hpilo.risblobstore2 import BlobStore2

        LOGGER.debug("Calling BlobStore2.initializecreds() without credentials")
        result = BlobStore2.initializecreds()

        if result is False:
            LOGGER.error("High security mode detected but no credentials provided")
            error_data = {
                "error": {
                    "code": "iLO.0.10.ExtendedInfo",
                    "message": "High security mode requires credentials on every command",
                    "@Message.ExtendedInfo": [{"MessageId": "Base.1.18.NoValidSession"}],
                }
            }
            return (401, error_data)

        LOGGER.info("CHIF initialized successfully (production mode)")
        LOGGER.warning("Note: If CHIF requests fail, the system may be in high security mode requiring credentials")
        return True

    def _execute_chif_request(self, bs2, path, method="GET", body=None):
        """Execute CHIF request and return response data

        Builds a raw HTTP request for the given verb over CHIF. GET requests keep
        the original ``Content-Length: 0`` no-body form; POST/PUT/PATCH include the
        serialized JSON body and matching Content-Length/Content-Type headers.

        :param bs2: BlobStore2 instance
        :param path: Redfish path
        :param method: HTTP verb (default "GET")
        :type method: str
        :param body: Optional request body (dict or str)
        :type body: dict or str or None
        :returns: Raw response data from CHIF, or None on empty response
        """
        method = (method or "GET").upper()

        # Serialize the body (if any) so we can compute an accurate Content-Length.
        body_bytes = b""
        if body is not None:
            body_str = body if isinstance(body, str) else json.dumps(body, separators=(",", ":"))
            body_bytes = body_str.encode("utf-8")

        request_headers = f"Host: localhost\r\nContent-Length: {len(body_bytes)}\r\n"
        if body_bytes:
            request_headers += "Content-Type: application/json\r\n"

        http_request = f"{method} {path} HTTP/1.1\r\n{request_headers}\r\n"
        req_data = http_request.encode("utf-8") + body_bytes

        # Execute via CHIF
        LOGGER.debug("Calling rest_immediate (%s) with req_data and rsp_namespace='volatile'", method)
        response_data = bs2.rest_immediate(req_data=req_data, rsp_namespace="volatile")

        if not response_data:
            LOGGER.error("CHIF rest_immediate returned empty response")
            LOGGER.error(
                "This may indicate: 1) High security mode requires credentials, "
                "2) CHIF communication failure, 3) iLO not responding"
            )
            LOGGER.error("Try providing credentials: -u <username> -p <password>")
            return None

        return response_data

    def _process_chif_response(self, response_data, path):
        """Process CHIF response and return result in the canonical two-form contract.

        Returns:
            * A **bare dict** (the parsed body) when the HTTP status is exactly 200.
              This is the only case that produces a non-tuple result; callers
              (``RawGetCommand._process_chif_result``) rely on this invariant to
              distinguish 200 OK from all other statuses without re-reading the code.
            * A **tuple** ``(status_code, data)`` for *every* non-200 status, including
              401, 404, 500, etc.  Callers must use ``isinstance(result, tuple)`` to
              detect non-200 responses; they must **not** infer the status from payload
              keys such as ``"error"``.
        """
        # Decode response
        response_str = self._decode_response_data(response_data)

        # Parse HTTP response
        status, data = self._parse_http_response(response_str)

        if status == 200:
            LOGGER.debug("CHIF GET successful for path: %s", path)
            return data
        else:
            LOGGER.warning("CHIF GET returned status %s for path: %s", status, path)
            return (status, data)

    def _do_chif_login_temp(self, username=None, password=None):
        """Temporary CHIF login without caching

        :param username: Username for authentication
        :param password: Password for authentication
        :returns: True if login successful
        :rtype: bool
        :raises SecurityStateError: If credentials required but not provided
        :raises InvalidCredentialsError: If credentials are invalid
        """
        try:
            import redfish.hpilo.risblobstore2 as risblobstore2
            from redfish.hpilo.risblobstore2 import Blob2SecurityError

            return self._perform_chif_login(risblobstore2, username, password)

        except (SecurityStateError, InvalidCredentialsError):
            raise
        except Blob2SecurityError:
            LOGGER.error("CHIF login failed: Blob2SecurityError (invalid credentials)")
            raise InvalidCredentialsError(0)
        except Exception as e:
            LOGGER.error("CHIF login failed: %s", e)
            import traceback

            LOGGER.debug(traceback.format_exc())
            return False

    def _perform_chif_login(self, risblobstore2, username, password):
        """Perform the CHIF login steps"""
        # Prepare credentials
        use_username, use_password = self._prepare_chif_credentials(username, password)

        # Initialize credentials
        correctcreds = self._initialize_chif_creds(use_username, use_password)

        # Get BlobStore2 instance
        bs2 = self._ensure_blobstore_instance(risblobstore2)
        if not bs2:
            return False

        # Handle authentication based on credentials validity
        if not correctcreds:
            return self._handle_invalid_credentials(bs2, username, password)

        LOGGER.debug("CHIF login with valid credentials successful")
        return True

    def _prepare_chif_credentials(self, username, password):
        """Prepare credentials for CHIF login"""
        use_username = username if username else "nousername"
        use_password = password if password else "nopassword"

        if isinstance(use_username, bytes):
            use_username = use_username.decode("utf-8")
        if isinstance(use_password, bytes):
            use_password = use_password.decode("utf-8")

        return use_username, use_password

    def _initialize_chif_creds(self, username, password):
        """Initialize CHIF credentials"""
        from redfish.hpilo.risblobstore2 import BlobStore2

        log_dir = self.rdmc.log_dir if self.rdmc else ""
        return BlobStore2.initializecreds(username=username, password=password, log_dir=log_dir)

    def _ensure_blobstore_instance(self, risblobstore2):
        """Ensure BlobStore2 instance exists"""
        if not self._bs2_instance:
            self._bs2_instance = self._get_or_create_blobstore(risblobstore2)

        bs2 = self._bs2_instance
        if not bs2:
            LOGGER.error("BlobStore2 instance not available")

        return bs2

    def _handle_invalid_credentials(self, bs2, username, password):
        """Handle authentication when credentials are not valid"""
        security_state = int(bs2.get_security_state())
        LOGGER.debug("CHIF login: correctcreds=False, security_state=%s", security_state)

        # Check if credentials are optional (factory or production mode)
        if security_state in (1, 3):
            return self._handle_optional_credentials_mode(security_state)

        # High security mode requires credentials
        return self._handle_required_credentials_mode(security_state, username, password)

    def _handle_optional_credentials_mode(self, security_state):
        """Handle factory or production mode where credentials are optional"""
        mode_name = "factory" if security_state == 1 else "production"
        LOGGER.debug("CHIF login in %s mode (security state %s) - no credentials needed", mode_name, security_state)
        return True

    def _handle_required_credentials_mode(self, security_state, username, password):
        """Handle high security mode where credentials are required"""
        # Check if credentials were provided
        if not username or not password or username == "nousername" or password == "nopassword":
            LOGGER.error("CHIF login failed: credentials required in security state %s", security_state)
            raise SecurityStateError(security_state)

        # Verify credentials for high security mode
        return self._verify_high_security_credentials()

    def _verify_high_security_credentials(self):
        """Verify credentials for high security mode"""
        from redfish.hpilo.risblobstore2 import BlobStore2

        LOGGER.info("Verifying credentials for high security mode")
        try:
            dll = BlobStore2.gethprestchifhandle()
            credreturn = dll.ChifVerifyCredentials()
            BlobStore2.unloadchifhandle(dll)

            if credreturn != 0:
                LOGGER.error("Credential verification failed with error code: %s", credreturn)
                raise InvalidCredentialsError(credreturn)

            LOGGER.debug("Credentials verified successfully for high security mode")
            return True
        except Exception as e:
            LOGGER.error("Credential verification failed: %s", e)
            raise InvalidCredentialsError(0)

    def _create_high_security_chif_session(self, username, password):
        """Create a high security CHIF session with credentials

        :param username: Username for authentication
        :type username: str
        :param password: Password for authentication
        :type password: str
        :returns: True if successful
        :rtype: bool
        """
        try:
            import redfish.hpilo.risblobstore2 as risblobstore2
            from redfish.hpilo.risblobstore2 import BlobStore2

            LOGGER.info("Creating high security CHIF session")

            # Get CHIF DLL handle
            dll = BlobStore2.gethprestchifhandle()

            # Initialize CHIF and create channel
            fhandle = self._initialize_chif_channel(dll)

            # Initialize and verify credentials
            self._setup_chif_credentials(dll, fhandle, username, password)

            LOGGER.info("High security CHIF session created and credentials verified successfully")

            # Store the handle for use in operations
            self._high_security_dll = dll
            self._high_security_fhandle = fhandle

            # Create/update BlobStore2 instance to use this channel
            if not self._bs2_instance:
                self._bs2_instance = self._get_or_create_blobstore(risblobstore2)

            return True

        except Exception as e:
            LOGGER.error("Failed to create high security CHIF session: %s", e)
            import traceback

            LOGGER.debug("Traceback: %s", traceback.format_exc())
            raise

    def _initialize_chif_channel(self, dll):
        """Initialize CHIF and create a channel"""
        from ctypes import byref, c_uint32, c_void_p

        from redfish.hpilo.risblobstore2 import BlobStore2
        from redfish.hpilo.rishpilo import (
            BlobReturnCodes,
            HpIloInitialError,
            HpIloNoChifDriverError,
        )

        LOGGER.debug("Calling ChifInitialize")
        dll.ChifInitialize(None)

        LOGGER.debug("Enabling security")
        dll.ChifEnableSecurity()

        fhandle = c_void_p()
        dll.ChifCreate.argtypes = [c_void_p]
        dll.ChifCreate.restype = c_uint32

        LOGGER.debug("Creating CHIF channel")
        status = dll.ChifCreate(byref(fhandle))

        if status != BlobReturnCodes.SUCCESS:
            BlobStore2.unloadchifhandle(dll)
            if status == BlobReturnCodes.CHIFERR_NoDriver:
                raise HpIloNoChifDriverError(
                    f"Error {status} - No Chif Driver occurred while trying to create a channel."
                )
            else:
                raise HpIloInitialError(f"Error {status} occurred while trying to create a channel.")

        LOGGER.debug("CHIF channel created with handle: %s", fhandle)
        return fhandle

    def _setup_chif_credentials(self, dll, fhandle, username, password):
        """Initialize and verify CHIF credentials"""
        from ctypes import POINTER, c_char_p, c_ubyte, create_string_buffer

        from redfish.hpilo.risblobstore2 import BlobStore2
        from redfish.hpilo.rishpilo import (
            BlobReturnCodes,
            HpIloChifAccessDeniedError,
            HpIloInitialError,
        )

        dll.initiate_credentials.argtypes = [c_char_p, c_char_p]
        dll.initiate_credentials.restype = POINTER(c_ubyte)

        usernew = create_string_buffer(username.encode("utf-8"))
        passnew = create_string_buffer(password.encode("utf-8"))

        LOGGER.debug("Initiating credentials")
        dll.initiate_credentials(usernew, passnew)

        self._verify_chif_channel(
            dll, fhandle, BlobStore2, BlobReturnCodes, HpIloInitialError, HpIloChifAccessDeniedError
        )

    def _verify_chif_channel(
        self, dll, fhandle, BlobStore2, BlobReturnCodes, HpIloInitialError, HpIloChifAccessDeniedError
    ):
        """Verify credentials on the CHIF channel.

        NOTE: ChifPing was intentionally removed — it added ~1.5 s of latency
        per call with no additional safety beyond what ChifVerifyCredentials
        already provides.
        """
        # Set receive timeout
        LOGGER.debug("Setting receive timeout")
        dll.ChifSetRecvTimeout(fhandle, 60000)

        # Verify credentials
        LOGGER.debug("Verifying credentials")
        credreturn = dll.ChifVerifyCredentials()

        if credreturn != BlobReturnCodes.SUCCESS:
            dll.ChifClose(fhandle)
            BlobStore2.unloadchifhandle(dll)
            if credreturn == BlobReturnCodes.CHIFERR_AccessDenied:
                raise HpIloChifAccessDeniedError(
                    f"Error {credreturn} - Chif Access Denied occurred while trying "
                    "to open a channel to iLO. Verify iLO Credentials passed."
                )
            else:
                raise HpIloInitialError(f"Error {credreturn} occurred while trying to open a channel to iLO")

    def _do_vnic_login_temp(self, user=None, password=None, no_app_account=False):
        """Temporary VNIC login for iLO7 without caching

        :param user: Optional username
        :param password: Optional password
        :param no_app_account: True if no app account exists
        :returns: Tuple of (session_token, session_location) or (None, None)
        :rtype: tuple
        """
        # Reset so the recorded status reflects only this login attempt.
        self._last_login_status_code = None
        try:
            # Serialize TPM access across concurrent ilorest processes. VNIC login
            # (app-account token check + vnic_login) touches the global TPM named
            # semaphore; a concurrent process's sem_unlink on disconnect would
            # otherwise destroy it mid-login, causing "Access denied"/file-access
            # failures. This mirrors the locking done by the login/logout commands.
            with TpmFileLock():
                # For app account login, use the proper rdmc.app.vnic_login method
                if not no_app_account:
                    return self._perform_app_account_vnic_login()
                else:
                    return self._perform_vnic_login(user, password, no_app_account)
        except Exception as e:
            LOGGER.error("VNIC login failed: %s", e)
            return None, None

    def _perform_app_account_vnic_login(self):
        """Perform VNIC login using app account via rdmc.app.vnic_login

        For iLO7, we use rdmc.app.vnic_login with explicit base_url to ensure
        HTTP-based authentication over VNIC (avoiding any CHIF fallback).

        :returns: Tuple of (session_token, session_location) or (None, None)
        :rtype: tuple
        """
        try:
            from redfish.hpilo.vnichpilo import AppAccount

            # Create AppAccount object for self-registered account
            log_dir = self.rdmc.log_dir if (self.rdmc and hasattr(self.rdmc, "log_dir")) else None
            app_obj = AppAccount(log_dir=log_dir)

            # Set iLO generation explicitly to prevent any CHIF detection attempts
            ilo_version = self._detect_ilo_version()
            if ilo_version:
                app_obj.ilo_gen = int(ilo_version)

            # Use rdmc.app.vnic_login with explicit base_url to force HTTP over VNIC
            if self.rdmc and self.rdmc.app and hasattr(self.rdmc.app, "vnic_login"):
                LOGGER.debug("Performing app account VNIC login with explicit base_url")

                try:
                    # Call vnic_login with base_url to ensure HTTP-based auth
                    login_response = self.rdmc.app.vnic_login(
                        app_obj=app_obj,
                        path=None,
                        skipbuild=True,
                        includelogs=False,
                        json_out=False,
                        base_url=self.DEFAULT_ILO_URL,  # Force HTTP over VNIC
                        username=None,
                        password=None,
                        log_dir=log_dir,
                        login_otp=None,
                        is_redfish=True,
                        proxy=None,
                        user_ca_cert_data=None,
                        biospassword=None,
                        sessionid=None,
                    )

                    # Extract session token and location from redfishinst
                    if self.rdmc.app.redfishinst and hasattr(self.rdmc.app.redfishinst, "session_key"):
                        session_token = self.rdmc.app.redfishinst.session_key
                        session_location = None
                        if hasattr(self.rdmc.app.redfishinst, "_session_location"):
                            session_location = self.rdmc.app.redfishinst._session_location

                        if session_token:
                            LOGGER.debug("VNIC app account login successful, location: %s", session_location)
                            return session_token, session_location

                except Exception as login_err:
                    LOGGER.debug("rdmc.app.vnic_login failed: %s", login_err)
                    # Fall through to try direct HTTP method

            # Fallback: Direct HTTP login if vnic_login not available or failed
            LOGGER.debug("Trying direct HTTP session creation for app account")
            return self._perform_direct_app_account_login(app_obj)

        except Exception as e:
            LOGGER.error("App account VNIC login failed: %s", e)
            import traceback

            LOGGER.debug(traceback.format_exc())
            return None, None

    def _perform_direct_app_account_login(self, app_obj):
        """Perform direct HTTP login for app account as fallback

        This is used when rdmc.app.vnic_login is not available or fails.
        It attempts to create a session using the app account's credentials
        via direct HTTP POST to SessionService.

        For iLO8+ targets the POST uses a strict PQC TLS context (downgrading
        to hybrid when unavailable), ensuring PQC is used on all raw commands.

        :returns: Tuple of (session_token, session_location) or (None, None)
        :rtype: tuple
        """
        try:
            # Try to get username/password from app_obj if available
            app_username = None
            app_password = None

            # Check for various attribute names that might store credentials
            if hasattr(app_obj, "username") and app_obj.username:
                app_username = app_obj.username
            if hasattr(app_obj, "password") and app_obj.password:
                app_password = app_obj.password

            # If no explicit credentials, try to generate session key
            if not (app_username and app_password):
                if hasattr(app_obj, "app_id") and hasattr(app_obj, "get_session_key"):
                    try:
                        session_key = app_obj.get_session_key()
                        if session_key:
                            # For app account, the session key might be usable directly
                            LOGGER.debug("Got session key from app_obj.get_session_key()")
                            return session_key, None
                    except Exception as key_err:
                        LOGGER.debug("get_session_key failed: %s", key_err)

            if not (app_username and app_password):
                LOGGER.error("Cannot determine app account credentials for direct login")
                return None, None

            # Perform direct HTTP login using PQC-aware session.
            session_url = self._build_session_service_url(self.DEFAULT_ILO_URL)
            session_data = {"UserName": app_username, "Password": app_password}

            LOGGER.debug("Performing direct HTTP login with app account credentials")

            # Use PQC-aware session: bypasses proxies and applies PQC SSL for iLO7+.
            session = self._get_requests_session_with_pqc(target_url=self.DEFAULT_ILO_URL)
            try:
                response = session.post(
                    session_url,
                    json=session_data,
                    verify=False,
                    timeout=HTTP_TIMEOUT_SECONDS,
                    proxies={"http": "", "https": ""},
                )
            finally:
                session.close()

            if response.status_code in [200, 201]:
                session_token, session_location = self._get_session_headers(response)
                if session_token:
                    LOGGER.debug("Direct HTTP app account login successful, location: %s", session_location)
                    return session_token, session_location

            self._last_login_status_code = response.status_code
            LOGGER.error("Direct app account HTTP login failed with status %s", response.status_code)
            return None, None

        except Exception as e:
            LOGGER.error("Direct app account login failed: %s", e)
            return None, None

    def _perform_vnic_login(self, user, password, no_app_account):
        """Perform the actual VNIC login request

        For iLO7 targets the session uses hybrid PQC TLS; for iLO8+ targets
        strict PQC TLS is preferred (downgrading to hybrid when unavailable).

        :returns: Tuple of (session_token, session_location) or (None, None)
        :rtype: tuple
        """
        url = self.DEFAULT_ILO_URL
        session_url = self._build_session_service_url(url)

        session_data = self._prepare_vnic_session_data(user, password, no_app_account)
        if session_data is None:
            return None, None

        # Use PQC-aware session: iLO7 gets hybrid, iLO8+ gets strict PQC.
        session = self._get_requests_session_with_pqc(target_url=url)
        try:
            response = session.post(
                session_url,
                json=session_data,
                verify=False,
                timeout=HTTP_TIMEOUT_SECONDS,
                proxies={"http": "", "https": ""},
            )
            return self._handle_vnic_login_response(response)
        finally:
            session.close()

    def _prepare_vnic_session_data(self, user, password, no_app_account):
        """Prepare session data for VNIC login"""
        if no_app_account:
            if not user or not password:
                LOGGER.error("VNIC login requires credentials when no app account exists")
                return None
            return {"UserName": user, "Password": password}
        return {}

    def _handle_vnic_login_response(self, response):
        """Handle VNIC login response

        :returns: Tuple of (session_token, session_location) or (None, None)
        :rtype: tuple
        """
        if response.status_code in [200, 201]:
            session_token, session_location = self._get_session_headers(response)
            if session_token:
                LOGGER.debug("VNIC login successful, session_location: %s", session_location)
                return session_token, session_location

        # Record the status so callers can tell a credential rejection (401/403)
        # from other failures and surface the correct error to the user.
        self._last_login_status_code = response.status_code
        LOGGER.debug("VNIC login failed with status %s", response.status_code)
        return None, None

    def _is_invalid_credentials_status(self):
        """Return True when the last login attempt was rejected for bad credentials.

        iLO answers a VNIC/HTTP session-create with ``401 Unauthorized`` when the
        supplied username/password are wrong. A ``403 Forbidden`` is deliberately
        excluded: it means the credentials were accepted but lack privilege for the
        operation, so it must not be reported as an invalid-credentials error.
        """
        return getattr(self, "_last_login_status_code", None) == 401

    # ------------------------------------------------------------------
    # Shared request engine (used by all raw commands: get/post/put/patch/
    # delete/head). Previously these lived on RawGetCommand and were reached
    # by the other raw commands only through inheritance from RawGetCommand.
    # They now live here so every raw command can extend RawCommandBase
    # directly, removing the interdependency with rawget.
    # ------------------------------------------------------------------

    def _execute_main_flow(self, options, headers, session_token_from_headers, path):
        """Execute the main authentication and request flow

        Flow:
        1. Determine connection mode - handle out-of-band immediately (no iLO detection needed)
        2. Check for cached session (from prior login) - use if available (no iLO detection needed)
        3. For in-band without cached session: Check/create ilo_generation.json cache
        4. Create temp session based on iLO version and mode
        5. Execute request and handle response
        6. Cleanup temp session if created
        """
        # Step 1: Determine connection mode early
        is_outofband = bool(getattr(options, "url", None))

        LOGGER.debug("Connection mode: %s", "Out-of-band" if is_outofband else "In-band")

        # Out-of-band handling (same for all iLO versions)
        # Handle immediately - no need for local iLO version detection
        if is_outofband:
            return self._handle_outofband_request(options, headers, path)

        # Step 2: Check for cached session BEFORE iLO detection
        # A cached session from a prior 'ilorest login --url ...' means we
        # already have a valid remote session and don't need local iLO detection.
        LOGGER.debug("Step 2: Checking for cached session")
        cached_session = self._get_cached_session_if_valid(options)
        if cached_session:
            LOGGER.debug("Using cached session")
            return self._execute_with_cached_session(options, headers, path, cached_session)

        # Step 3: Get iLO version and security state in ONE efficient call (in-band only)
        # Only reached when there is no cached session, so we need local detection
        # This avoids multiple CHIF library initializations
        LOGGER.debug("Step 3: Checking ilo_generation.json cache")
        ilo_version, security_state = self._get_ilo_info_cached()

        has_credentials = bool(getattr(options, "user", None) and getattr(options, "password", None))

        LOGGER.debug("iLO version: %s, Has credentials: %s", ilo_version, has_credentials)

        # Step 4: Create temp session based on scenario
        LOGGER.debug("Step 4: Creating temp session")

        # In-band handling (varies by iLO version)
        if ilo_version and ilo_version >= 7:
            LOGGER.debug("Calling ilo7 inband request")
            return self._handle_ilo7_inband_request(options, headers, path)
        elif ilo_version and ilo_version >= 5:
            # Pass security_state to avoid redundant detection
            LOGGER.debug("Calling ilo5_6 inband request")
            return self._handle_ilo5_6_inband_request(options, headers, path, ilo_version, security_state)
        else:
            # Unknown iLO version - try legacy framework
            LOGGER.warning("Unknown iLO version: %s, using legacy framework", ilo_version)
            return self._run_with_old_framework(options, headers, path)

    def _get_ilo_info_cached(self):
        """Get iLO version and security state efficiently with caching

        This combines version detection and security state into one operation
        to minimize CHIF library initialization overhead.

        Returns:
            tuple: (ilo_version, security_state)
        """
        # Check if we have cached values in memory
        if hasattr(self, "_cached_ilo_version") and hasattr(self, "_cached_security_state"):
            return (self._cached_ilo_version, self._cached_security_state)

        # Get iLO version (uses file cache if available)
        ilo_version = self._detect_ilo_version()

        # Get security state - this is obtained during version detection
        # so we can reuse the cached value from _detect_ilo_version
        if hasattr(self, "_cached_security_state"):
            security_state = self._cached_security_state
        else:
            # Only call if not already cached
            security_state = self._get_security_state_from_cache()

        # Cache in memory for this session
        self._cached_ilo_version = ilo_version
        self._cached_security_state = security_state

        return (ilo_version, security_state)

    def _get_security_state_from_cache(self):
        """Get security state from cache or actively detect it

        Security state MUST be accurate - defaulting to production mode (3)
        would silently skip FIPS/HighSecurity/CNSA routing, causing CHIF
        failures in those modes.
        """
        # Check instance-level cache first
        if hasattr(self, "_cached_security_state") and self._cached_security_state is not None:
            return self._cached_security_state

        # Check class-level cache (set during version detection in RawCommandBase)
        if RawCommandBase._security_state_memory_cache is not None:
            return RawCommandBase._security_state_memory_cache

        # Security state was not cached (e.g. iLO version loaded from file cache).
        # Actively detect it - defaulting to 3 would hide FIPS/HighSecurity modes.
        security_state = self._get_security_state()
        self._cached_security_state = security_state
        RawCommandBase._security_state_memory_cache = security_state
        return security_state

    def _get_cached_session_if_valid(self, options):
        """Check if there's a valid cached session to use

        Explicit credentials always win: when ``-u``/``-p`` are supplied on the raw
        command they MUST be validated, so any cached session is bypassed entirely.
        Reusing a cached session would authenticate as whoever created it and let a
        wrong username/password silently succeed — the exact customer-reported defect.

        Session sources (in priority order), used only when no credentials were given:
        1. In-memory active session from rdmc.app.redfishinst (from prior login command)
           - This is ALWAYS checked, even with --nocache
           - Represents an active, verified session
        2. File-based persistent cache (~/.iLORest/cache/)
           - Only checked if --nocache is NOT specified
           - May be stale or expired

        The --nocache flag only skips the file-based cache, not the in-memory session.
        """
        # Explicit credentials must be honored and validated — never masked by a
        # pre-existing session. Applies to every raw verb via this shared base class.
        if self._has_explicit_credentials(options):
            LOGGER.debug("Explicit credentials supplied - bypassing cached session so they are validated")
            return None

        # Priority 1: Always check for in-memory active session from rdmc.app
        # This session was created by a prior 'ilorest login' command and is known to be valid
        inmemory_session = self._get_active_inmemory_session()
        if inmemory_session:
            LOGGER.debug("Found active in-memory session from prior login")
            return {"session_token": inmemory_session, "is_cached": True, "source": "inmemory"}

        # Priority 2: Check file-based cache (skip if --nocache is specified)
        if getattr(options, "nocache", False):
            LOGGER.debug("--nocache flag set, skipping file-based session cache")
            return None

        # Check for file-cached session token
        session_token = self._get_cached_session_token(options)
        if session_token:
            LOGGER.debug("Found valid session in file cache")
            return {"session_token": session_token, "is_cached": True, "source": "file"}

        return None

    def _has_explicit_credentials(self, options):
        """Return True when the user supplied both ``-u`` and ``-p`` on the command line.

        Used to enforce "explicit credentials always win": whenever credentials are
        available they must drive (and be validated by) the request, rather than being
        short-circuited by a cached or in-memory session.

        :param options: Parsed command options.
        :returns: True when a non-empty username *and* password were supplied.
        :rtype: bool
        """
        return bool(getattr(options, "user", None) and getattr(options, "password", None))

    def _get_active_inmemory_session(self):
        """Get active session token from rdmc.app.redfishinst if available

        This represents a session created by a prior 'ilorest login' command.
        It should always be used when available, regardless of --nocache flag.

        :returns: Session token string or None
        :rtype: str or None
        """
        try:
            if not (self.rdmc and self.rdmc.app and hasattr(self.rdmc.app, "redfishinst")):
                return None

            inst = self.rdmc.app.redfishinst
            if not inst:
                return None

            # Check if we have an active session key
            if hasattr(inst, "session_key") and inst.session_key:
                LOGGER.debug("Found active session from rdmc.app.redfishinst")
                return inst.session_key

            return None
        except Exception as e:
            LOGGER.debug("Could not check in-memory session: %s", e)
            return None

    def _execute_with_cached_session(self, options, headers, path, cached_session):
        """Execute request using cached session"""
        is_inband = not getattr(options, "url", None)

        # Get the actual session URL to determine connection type
        # This respects the actual cached session type (blobstore vs HTTP)
        session_url = self._get_url_from_session()

        # Determine if we should use CHIF based on the actual cached session type
        # If session_url contains "blobstore://", it's a CHIF session
        is_blobstore_session = session_url and "blobstore://" in session_url

        if is_blobstore_session:
            # In high security/FIPS/CNSA mode, direct CHIF rawget fails because
            # it cannot properly re-initialize credentials per request.
            # Route through the legacy framework which handles this correctly.
            security_state = self._get_security_state_from_cache()
            if security_state in [4, 5, 6]:
                LOGGER.debug("Cached blobstore session in high security/FIPS mode - using legacy framework")
                return self._run_with_old_framework(options, headers, path)

            # Production mode blobstore session - use direct CHIF
            use_chif = True
            LOGGER.debug("Cached session is blobstore type - using CHIF")
        elif not is_inband:
            # Out-of-band (remote) session via explicit --url - use HTTP
            use_chif = False
            LOGGER.debug("Cached out-of-band session to %s - using HTTP", session_url)
        elif session_url and session_url.startswith("https://"):
            # Session URL indicates an HTTPS/OOB session from a prior login,
            # even though --url was not provided on this rawget command - use HTTP
            use_chif = False
            LOGGER.debug("Cached session URL is HTTPS (%s) - using HTTP", session_url)
        else:
            # In-band without cached session URL - determine by iLO version
            # Only detect iLO version here where it's actually needed
            ilo_version = self._detect_ilo_version()
            # iLO7+ can use HTTP (VNIC), iLO5/6 use CHIF
            use_chif = ilo_version is None or ilo_version < 7
            # For iLO7 in-band without explicit session URL, use VNIC default
            if not use_chif and not session_url:
                session_url = self.DEFAULT_ILO_URL
                LOGGER.debug("iLO7 in-band without session URL - using VNIC default")

        auth_info = {
            "auth": None,
            "session_token": cached_session["session_token"],
            "needs_logout": False,
            "auth_type": "cached_session",
            "fallback_auth": None,
            "url": session_url,
            "use_chif_method": use_chif,
            "use_cached_session": True,
            "temp_session_created": False,
            "session_location": None,
        }

        # Prepare fallback credentials in case cached session fails
        username, password = self._get_cred(options)
        if username and password:
            auth_info["auth"] = (username, password)

        LOGGER.debug("Calling with cached session:execute_with_auth_info")
        return self._execute_with_auth_info(options, headers, path, auth_info)

    def _get_cred(self, options):
        global_encode = getattr(options, "encode", False)  # Check for global encode
        username = getattr(options, "user", None)
        password = getattr(options, "password", None)

        if global_encode:
            if username:
                username = self._decode_credential(username)
            if password:
                password = self._decode_credential(password)
        return username, password

    def _handle_outofband_request(self, options, headers, path):
        """Handle out-of-band request (same for all iLO versions)

        When a session token is already present in ``headers`` (from the
        ``--headers X-Auth-Token:…`` option) we can skip credential-based
        login entirely and issue the request directly.  Otherwise credentials
        are required to create a temp session.
        """
        url = getattr(options, "url", None)

        if not url:
            sys.stderr.write("Error: Out-of-band mode requires --url parameter.\n")
            sys.stderr.write("  Example: rawget /redfish/v1/systems/1 --url <ilo_ip> -u <user> -p <pass>\n")
            return ReturnCodes.INVALID_COMMAND_LINE_ERROR

        # If an X-Auth-Token was supplied via --headers, use it directly —
        # no separate credential login is needed.
        session_token_in_headers = headers.get("X-Auth-Token") if isinstance(headers, dict) else None
        if session_token_in_headers:
            LOGGER.debug("X-Auth-Token present in headers — skipping credential check for out-of-band request")
            auth_info = {
                "auth": None,
                "session_token": session_token_in_headers,
                "needs_logout": False,
                "auth_type": "token",
                "fallback_auth": None,
                "url": self._normalize_url(url),
                "use_chif_method": False,
                "use_cached_session": False,
                "temp_session_created": False,
                "session_location": None,
            }
            return self._execute_with_auth_info(options, headers, path, auth_info)

        # Resolve credentials only when a token was not supplied — the token
        # branch above returns early, so skip _get_cred (and its decoding) otherwise.
        username, password = self._get_cred(options)
        if not username or not password:
            sys.stderr.write("Error: Out-of-band mode requires credentials.\n")
            sys.stderr.write("  Example: rawget /redfish/v1/systems/1 --url <ilo_ip> -u <user> -p <pass>\n")
            return ReturnCodes.INVALID_COMMAND_LINE_ERROR

        # Create temp HTTP session
        LOGGER.debug("Creating out-of-band temp session to %s", url)

        auth_info = {
            "auth": (username, password),
            "session_token": None,
            "needs_logout": True,
            "auth_type": "credentials",
            "fallback_auth": None,
            "url": self._normalize_url(url),
            "use_chif_method": False,
            "use_cached_session": False,
            "temp_session_created": True,
            "session_location": None,
        }

        LOGGER.debug("Calling outofband request: execute with auth info")
        return self._execute_with_auth_info(options, headers, path, auth_info)

    def _handle_ilo7_inband_request(self, options, headers, path):
        """Handle iLO7 in-band request.

        Credential precedence ("explicit credentials must win"):

        1. If ``-u``/``-p`` are supplied they are honored **mandatorily**: they are
           validated via a direct VNIC login and used for the request, regardless of
           app-account state. A wrong username/password fails immediately with
           ``V1_INVALID_CREDENTIALS_ERROR`` — it is never silently ignored because a
           healthy app account happens to exist, and there is no fallback to the app
           account.
        2. Otherwise, use the self app account when present.
        3. Otherwise, credentials are required.

        NOTE: If the iLO app account was removed (for example by an iLO factory reset)
        the stale TPM token is deliberately **not** deleted or recreated. Recovering
        the app account is left to the customer (``ilorest appaccount create``); raw
        commands simply use the supplied credentials when they are valid.
        """
        LOGGER.debug("Handling iLO7 in-band request")

        username, password = self._get_cred(options)
        if username and password:
            LOGGER.debug("iLO7: explicit credentials supplied — validating them (they take precedence)")
            return self._execute_ilo7_with_credentials(options, headers, path, username, password)

        # No explicit credentials: fall back to the self app account when it exists.
        if self._check_ilo7_app_account():
            LOGGER.debug("iLO7: App account exists, using app account authentication")
            return self._execute_ilo7_with_app_account(options, headers, path)

        LOGGER.debug("iLO7: No app account and no credentials")
        sys.stderr.write("Error: iLO7 without app account requires credentials.\n")
        sys.stderr.write("  Create app account: ilorest appaccount create\n")
        sys.stderr.write("  Or provide credentials: rawget <path> -u <user> -p <pass>\n")
        return ReturnCodes.INVALID_COMMAND_LINE_ERROR

    def _execute_ilo7_with_credentials(self, options, headers, path, username, password):
        """Honor explicitly supplied credentials for an iLO7 in-band request.

        The credentials are validated via a direct VNIC login and drive the request.
        A wrong username or password is rejected immediately with
        ``V1_INVALID_CREDENTIALS_ERROR`` even when a healthy app account exists that
        could otherwise authenticate — there is no fallback to the app account, and
        no TPM app-account state is created, deleted, or repaired on this path.

        Args:
            options: Parsed command options.
            headers: Request headers dict.
            path: Redfish resource path for the raw command.
            username: Explicit iLO username.
            password: Explicit iLO password.

        Returns:
            A ``ReturnCodes`` value for the request.
        """
        # Explicit credentials are mandatory once supplied: validate and use them, and
        # fail fast when iLO rejects them. No app-account probing or self-healing.
        return self._execute_ilo7_without_app_account(options, headers, path, username, password)

    def _execute_ilo7_with_app_account(self, options, headers, path):
        """Execute iLO7 request using app account (VNIC).

        Only reached when no explicit credentials were supplied. If the app-account
        login fails (for example because an iLO factory reset removed the account
        while the host TPM still holds its token) the error is surfaced as-is: the
        TPM token is intentionally left untouched for the customer to resolve.
        """
        # Use VNIC with app account
        auth_info = {
            "auth": None,
            "session_token": None,
            "needs_logout": True,
            "auth_type": "appaccount",
            "fallback_auth": None,
            "url": self.DEFAULT_ILO_URL,
            "use_chif_method": False,  # VNIC uses HTTP over internal network
            "use_cached_session": False,
            "temp_session_created": True,
            "session_location": None,
        }

        # Perform VNIC login with app account
        try:
            session_token, session_location = self._do_vnic_login_temp(no_app_account=False)
            if session_token:
                auth_info["session_token"] = session_token
                auth_info["session_location"] = session_location
                LOGGER.debug("Calling ilo7 with app account: execute with auth info")
                return self._execute_with_auth_info(options, headers, path, auth_info)

            # The app account could not authenticate (e.g. iLO no longer has the
            # account after a factory reset). Report it and let the customer recreate
            # the app account or supply -u/-p; never mutate the TPM automatically.
            LOGGER.error("Failed to create VNIC session with app account")
            sys.stderr.write("Error: Failed to create session with app account.\n")
            sys.stderr.write("  Recreate app account: ilorest appaccount create\n")
            sys.stderr.write("  Or provide credentials: rawget <path> -u <user> -p <pass>\n")
            return ReturnCodes.INVALID_COMMAND_LINE_ERROR
        except Exception as e:
            LOGGER.error("VNIC login with app account failed: %s", e)
            sys.stderr.write(f"Error: App account login failed - {str(e)}\n")
            return ReturnCodes.INVALID_COMMAND_LINE_ERROR

    def _execute_ilo7_without_app_account(self, options, headers, path, username, password):
        """Execute iLO7 request without app account (requires credentials)"""
        auth_info = {
            "auth": (username, password),
            "session_token": None,
            "needs_logout": True,
            "auth_type": "credentials",
            "fallback_auth": None,
            "url": self.DEFAULT_ILO_URL,
            "use_chif_method": False,  # VNIC uses HTTP
            "use_cached_session": False,
            "temp_session_created": True,
            "session_location": None,
        }

        # Perform VNIC login without app account (using credentials)
        try:
            session_token, session_location = self._do_vnic_login_temp(
                user=username, password=password, no_app_account=True
            )
            if session_token:
                auth_info["session_token"] = session_token
                auth_info["session_location"] = session_location
                LOGGER.debug("Calling ilo7 without app account: execute with auth info")
                return self._execute_with_auth_info(options, headers, path, auth_info)
            else:
                # iLO rejected the supplied username/password — report a proper
                # invalid-credentials error instead of a generic command-line error.
                # A 403 (privilege failure) is excluded by _is_invalid_credentials_status.
                if self._is_invalid_credentials_status():
                    return self._emit_credential_rejection(self._last_login_status_code)
                LOGGER.error("Failed to create VNIC session with credentials")
                sys.stderr.write("Error: Failed to create session with provided credentials.\n")
                return ReturnCodes.INVALID_COMMAND_LINE_ERROR
        except Exception as e:
            # A credential rejection raised as an exception must still fail fast with
            # the invalid-credentials return code, not a generic command-line error.
            if self._is_credential_rejection_exception(e):
                LOGGER.debug("iLO rejected the supplied credentials during VNIC login: %s", e)
                return self._emit_credential_rejection(self._last_login_status_code or 401)
            LOGGER.error("VNIC login with credentials failed: %s", e)
            sys.stderr.write(f"Error: Credential login failed - {str(e)}\n")
            return ReturnCodes.INVALID_COMMAND_LINE_ERROR

    def _handle_ilo5_6_inband_request(self, options, headers, path, ilo_version, security_state=None):
        """Handle iLO5/6 in-band request

        Flow:
        1. Check security mode (production=3 vs high security=4,5,6)
        2. For high security/FIPS/CNSA: Use legacy framework
        3. For production mode:
           - If VNIC enabled AND credentials provided: VNIC login
           - Otherwise: CHIF login (with or without credentials)
        """
        LOGGER.debug("Handling iLO%s in-band request", int(ilo_version))

        username, password = self._get_cred(options)
        has_credentials = bool(username and password)

        # Use passed security_state to avoid redundant CHIF detection
        if security_state is None:
            security_state = self._get_security_state()

        is_high_security = security_state in [4, 5, 6]  # 4=HighSecurity, 5=FIPS, 6=CNSA/SuiteB

        LOGGER.debug("Security state: %s, High security: %s", security_state, is_high_security)

        # For high security/FIPS/CNSA mode, use legacy framework
        if is_high_security:
            LOGGER.debug("High security mode detected, using legacy framework")
            if not has_credentials:
                sys.stderr.write("Error: High security mode requires credentials.\n")
                sys.stderr.write("  Example: rawget <path> -u <user> -p <pass>\n")
                return ReturnCodes.INVALID_COMMAND_LINE_ERROR
            # For iLO6 FIPS mode, CHIF direct can fail, but legacy framework (rdmc.app)
            # handles internal retries and proper login mapping.
            return self._run_with_old_framework(options, headers, path)

        # Production mode (security_state == 3)
        # Only probe VNIC when we could actually use it: iLO5/6 VNIC login requires
        # credentials. Skipping the probe on the common credential-less in-band path
        # avoids a blocking (up to 1s) socket connect to 16.1.15.1 whose result would
        # be discarded anyway, going straight to the direct CHIF request.
        if has_credentials and self._is_vnic_available():
            LOGGER.debug("Production mode with VNIC enabled and credentials - using VNIC")
            return self._execute_with_vnic_credentials(options, headers, path, username, password)

        # Use CHIF (with or without credentials based on mode)
        LOGGER.debug("Production mode - using CHIF")
        return self._execute_with_chif(options, headers, path, username, password)

    def _get_security_state(self):
        """Get the security state of the iLO

        Returns:
            int: Security state (3=Production, 4=HighSecurity, 5=FIPS, 6=CNSA/SuiteB)
        """
        try:
            from redfish.hpilo.vnichpilo import AppAccount

            if self.rdmc and self.rdmc.app and hasattr(self.rdmc.app, "getilover_beforelogin"):
                app_obj = AppAccount(log_dir=self.rdmc.log_dir if self.rdmc else None)
                _, sec_state = self.rdmc.app.getilover_beforelogin(app_obj)
                LOGGER.debug("Security state: %s", sec_state)
                return sec_state
        except Exception as e:
            LOGGER.debug("Could not determine security state: %s", e)

        # Default to production mode if we can't determine
        LOGGER.debug("Default Security state: 3")
        return 3

    def _execute_with_vnic_credentials(self, options, headers, path, username, password):
        """Execute request using VNIC with credentials (iLO6 with VNIC enabled).

        Explicit credentials must fail fast in every mode: when iLO rejects the
        supplied ``-u``/``-p`` the request is NOT retried over CHIF, because the
        in-band CHIF path can run unauthenticated and would let a wrong password
        silently succeed. The CHIF fallback is reserved for VNIC being unusable.
        """
        auth_info = {
            "auth": (username, password),
            "session_token": None,
            "needs_logout": True,
            "auth_type": "credentials",
            "fallback_auth": None,
            "url": self.DEFAULT_ILO_URL,
            "use_chif_method": False,
            "use_cached_session": False,
            "temp_session_created": True,
            "session_location": None,
        }

        try:
            session_token, session_location = self._do_vnic_login_temp(
                user=username, password=password, no_app_account=True
            )
            if session_token:
                auth_info["session_token"] = session_token
                auth_info["session_location"] = session_location
                LOGGER.debug("Calling with vnic credentials: execute with auth info")
                return self._execute_with_auth_info(options, headers, path, auth_info)

            # iLO answered 401: the credentials are wrong. Never fall back to CHIF.
            if self._is_invalid_credentials_status():
                return self._emit_credential_rejection(self._last_login_status_code)

            # VNIC itself is unusable (not a credential problem) - fall back to CHIF.
            LOGGER.debug("VNIC login failed, falling back to CHIF")
            return self._execute_with_chif(options, headers, path, username, password)
        except Exception as e:
            if self._is_credential_rejection_exception(e):
                LOGGER.debug("iLO rejected the supplied credentials during VNIC login: %s", e)
                return self._emit_credential_rejection(self._last_login_status_code or 401)
            LOGGER.debug("VNIC login failed: %s, falling back to CHIF", e)
            return self._execute_with_chif(options, headers, path, username, password)

    def _execute_with_chif(self, options, headers, path, username, password):
        """Execute request using CHIF (iLO5/6 in-band production mode)"""
        LOGGER.debug("Executing CHIF request for path: %s", path)

        auth_info = {
            "auth": (username, password) if username and password else None,
            "session_token": None,
            "needs_logout": False,
            "auth_type": "chif",
            "fallback_auth": None,
            "url": None,
            "use_chif_method": True,
            "use_cached_session": False,
            "temp_session_created": False,
            "session_location": None,
        }

        LOGGER.debug("CHIF auth_info prepared, use_chif_method=%s", auth_info["use_chif_method"])
        return self._execute_with_auth_info(options, headers, path, auth_info)

    def _parse_arguments(self, line):
        """Parse command line arguments"""
        try:
            options, _ = self.rdmc.rdmc_parse_arglist(self, line)
            return options
        except (InvalidCommandLineErrorOPTS, SystemExit):
            if ("-h" in line) or ("--help" in line):
                return ReturnCodes.SUCCESS
            else:
                raise InvalidCommandLineErrorOPTS("")

    def _parse_headers(self, options):
        """Parse headers and extract session token"""
        headers = {}
        session_token_from_headers = None

        # Use getattr so commands that don't define --headers don't crash.
        raw_headers = getattr(options, "headers", None)
        if raw_headers:
            extraheaders = raw_headers.split(",")
            for item in extraheaders:
                # Split on first colon only to preserve colons in values
                header = item.split(":", 1)
                try:
                    key = header[0].strip()
                    value = header[1].strip()
                    headers[key] = value
                    if key.lower() in ["x-auth-token", "x-authn-token"]:
                        session_token_from_headers = value
                        LOGGER.debug("Found X-Auth-Token in custom headers")
                        # NOTE: do NOT break — continue to collect remaining headers
                except Exception:
                    InvalidCommandLineError("Invalid format for --headers option.")

        return headers, session_token_from_headers

    def _handle_no_auth_request(self, options, headers, path):
        """Handle requests with no authentication, using the instance verb/body."""
        options_url = getattr(options, "url", None)
        url = self._normalize_url(options_url) if options_url else self.DEFAULT_ILO_URL
        full_path = urljoin(url, path.lstrip("/"))

        try:
            response = self._execute_request(self._raw_method, full_path, headers=headers, body=self._raw_body)
            return self._handle_response(response, options)
        except requests.exceptions.Timeout as excp:
            LOGGER.error("Connection timeout to %s: %s", url, excp)
            sys.stderr.write(f"Error: Connection timeout to {url}. iLO may be resetting or unreachable.\n")
            return ReturnCodes.V1_SERVER_DOWN_OR_UNREACHABLE_ERROR
        except requests.exceptions.ConnectionError as excp:
            LOGGER.error("Connection failed to %s: %s", url, excp)
            sys.stderr.write(f"Error: Connection failed to {url}. iLO may be resetting or unreachable.\n")
            return ReturnCodes.V1_SERVER_DOWN_OR_UNREACHABLE_ERROR
        except Exception as excp:
            LOGGER.error("Failed to complete no-auth request: %s", excp)
            sys.stderr.write(f"Error: Failed to complete operation - {excp}\n")
            return ReturnCodes.GENERAL_ERROR

    def _execute_with_auth_info(self, options, headers, path, auth_info):
        """Execute request with authentication info"""
        url = self._build_request_url(options, auth_info)
        full_path = self._build_full_path(url, path)

        LOGGER.debug("Executing request: url=%s, path=%s, use_chif=%s", url, full_path, auth_info["use_chif_method"])

        try:
            response = self._perform_request(options, auth_info, full_path, headers)
            self._capture_temp_session_for_cleanup(response, auth_info)
            LOGGER.debug("Request completed, response status: %s", response.status_code if response else "None")
            # A 401/403 from a fresh Basic-Auth (credential) request means the
            # supplied -u/-p were rejected. Surface it uniformly as an invalid-
            # credentials error (matching the iLO7 in-band path) instead of the
            # generic session-expired code.
            credential_rejection = self._check_credential_rejection(response, auth_info)
            if credential_rejection is not None:
                return credential_rejection
            return self._handle_response(response, options)
        except requests.exceptions.ConnectionError as e:
            import traceback

            err_text = str(e).lower()
            if "connection aborted" in err_text and "filenotfounderror" in err_text:
                LOGGER.debug(
                    "RawGet connection aborted with FileNotFoundError "
                    "(emitting user-friendly output, rc=33). "
                    "request_url=%s, request_path=%s, exception=%s",
                    url,
                    full_path,
                    repr(e),
                )
                LOGGER.debug(traceback.format_exc())
                return ReturnCodes.V1_SERVER_DOWN_OR_UNREACHABLE_ERROR

            LOGGER.error("Request execution failed: %s", e)
            LOGGER.debug(traceback.format_exc())
            sys.stderr.write(f"Error: Request failed - {str(e)}\n")
            return ReturnCodes.V1_SERVER_DOWN_OR_UNREACHABLE_ERROR
        except requests.exceptions.Timeout as e:
            LOGGER.error("Request execution failed: %s", e)
            import traceback

            LOGGER.debug(traceback.format_exc())
            sys.stderr.write(f"Error: Request failed - {str(e)}\n")
            return ReturnCodes.V1_SERVER_DOWN_OR_UNREACHABLE_ERROR
        except Exception as e:
            LOGGER.error("Request execution failed: %s", e)
            import traceback

            LOGGER.debug(traceback.format_exc())
            sys.stderr.write(f"Error: Request failed - {str(e)}\n")
            return ReturnCodes.GENERAL_ERROR
        finally:
            self._cleanup_session(auth_info)

    def _check_credential_rejection(self, response, auth_info):
        """Detect an iLO rejection of explicitly supplied ``-u``/``-p`` credentials.

        A fresh Basic-Auth (credential) request that comes back ``401 Unauthorized``
        means the supplied username/password were wrong. This surfaces uniformly as
        ``V1_INVALID_CREDENTIALS_ERROR`` with the same "Invalid credentials" message
        as the iLO7 in-band path, rather than the generic session-expired code
        produced by the normal response formatter.

        A ``403 Forbidden`` is intentionally **not** treated as a credential
        rejection: it means the credentials were accepted but the account lacks the
        privilege required for the resource, so it is left to the normal formatter
        (which renders ``[403] Access forbidden.``) rather than being mislabeled as
        an authentication failure.

        The check is deliberately narrow so it only fires for a genuine credential
        rejection:

        * ``auth_type`` is ``"credentials"`` (explicit ``-u``/``-p`` were supplied),
        * there is no pre-created ``session_token`` (a set token means login already
          succeeded, so a later 401 is a session/token issue, not a bad password),
        * the request is not using a cached session (``use_cached_session``), and
        * the request is an HTTP request, not a CHIF/in-band one (``use_chif_method``).

        For in-band CHIF requests (``use_chif_method``), a generic 401 is a resource
        privilege/session issue, so it is *not* treated as a credential rejection.
        The exception is an explicit ``-u``/``-p`` that failed CHIF verification —
        flagged via ``_chif_invalid_credentials`` by ``_init_high_security_credentials``
        — which must be surfaced as invalid credentials even in production mode (where
        CHIF otherwise permits credential-less access).

        Args:
            response: The HTTP response object returned by the request.
            auth_info: The authentication/session bookkeeping dict for the request.

        Returns:
            ``ReturnCodes.V1_INVALID_CREDENTIALS_ERROR`` when the credentials were
            rejected, otherwise ``None`` (let the normal formatter handle it).
        """
        status_code = getattr(response, "status_code", None)

        # In-band CHIF: only an explicit-credential verification failure counts as a
        # credential rejection (flagged during CHIF credential initialization); CHIF
        # synthesizes a 401 for that case.
        if auth_info.get("use_chif_method"):
            if status_code == 401 and getattr(self, "_chif_invalid_credentials", False):
                return self._emit_credential_rejection(status_code)
            return None

        # Out-of-band HTTP: only a genuine 401 means a wrong username/password. A 403
        # is an authorization (privilege) failure, not an authentication one.
        if status_code != 401:
            return None
        if auth_info.get("auth_type") != "credentials":
            return None
        if auth_info.get("session_token") or auth_info.get("use_cached_session"):
            return None

        return self._emit_credential_rejection(status_code)

    #: Matches the wording written by ``rdmc_helper.UI.invalid_credentials`` (the
    #: message shown for a rejected ``ilorest login``), so a wrong ``-u``/``-p``
    #: reports identically whether the user ran ``login`` or a raw command.
    INVALID_CREDENTIALS_MESSAGE = (
        "Invalid credentials. Unable to authenticate to iLO. \n"
        "Please ensure to specify correct username and password.\n"
    )

    def _emit_credential_rejection(self, status_code):
        """Surface an invalid-credentials rejection uniformly across raw commands.

        No request ever reached iLO on this short-circuit path, so there is no
        response to report: the ``[status] message`` line is written to the debug
        log rather than stdout, leaving only the human-readable guidance on stderr
        plus the invalid-credentials return code.

        :param status_code: The HTTP status code that indicated the rejection.
        :returns: ``ReturnCodes.V1_INVALID_CREDENTIALS_ERROR``.
        """
        LOGGER.debug("iLO rejected the supplied credentials (HTTP %s)", status_code)
        LOGGER.debug("[%s] %s", status_code, self._get_status_message(status_code))
        sys.stderr.write(self.INVALID_CREDENTIALS_MESSAGE)
        return ReturnCodes.V1_INVALID_CREDENTIALS_ERROR

    def _build_request_url(self, options, auth_info):
        """Build the request URL"""
        # For CHIF requests, URL is not used - return a marker
        if auth_info["use_chif_method"]:
            return "blobstore://."

        if auth_info["url"]:
            return auth_info["url"]

        options_url = getattr(options, "url", None)
        if options_url:
            return self._normalize_url(options_url)

        # Safely access redfishinst.base_url with multiple null checks
        try:
            if self.rdmc and self.rdmc.app:
                redfishinst = getattr(self.rdmc.app, "redfishinst", None)
                if redfishinst:
                    base_url = getattr(redfishinst, "base_url", None)
                    if base_url:
                        if "blobstore://" in base_url:
                            return base_url
                        return self._normalize_url(base_url)
        except Exception as e:
            LOGGER.debug("Could not get base_url from redfishinst: %s", e)

        return self.DEFAULT_ILO_URL

    def _build_full_path(self, url, path):
        """Build the full request path"""
        if url and "blobstore://" in url:
            return path
        return urljoin(url.rstrip("/"), path.lstrip("/"))

    def _perform_request(self, options, auth_info, full_path, headers):
        """Perform the actual HTTP/CHIF request"""
        if auth_info["use_chif_method"]:
            LOGGER.debug("Performing chif request")
            return self._perform_chif_request(options, full_path, auth_info, headers)
        else:
            LOGGER.debug("Performing http request")
            return self._perform_http_request(full_path, headers, auth_info)

    def _perform_chif_request(self, options, path, auth_info, headers=None):
        """Perform CHIF request with fallback handling"""
        username = auth_info["auth"][0] if auth_info["auth"] else None
        password = auth_info["auth"][1] if auth_info["auth"] else None

        LOGGER.debug("Performing CHIF request to path: %s", path)
        LOGGER.debug("username: %s, password:%s", self._mask_username(username), self._mask_simple_token(password))

        # SMBIOS is a GET-only binary endpoint whose payload must not be forced
        # through JSON decode. Only rawget (method GET) targets it, mirroring the
        # original single-file behaviour where this path lived on RawGetCommand.
        if self._raw_method == "GET" and self._is_smbios_path(path):
            smbios_response = self._perform_smbios_chif_request(options, path, username, password, headers)
            if smbios_response is not None:
                return smbios_response

        # CCSE-150273: When the user explicitly supplies credentials, run the
        # in-band request under an authenticated user session instead of the
        # passwordless BlobStore2 path. In production (non-high-security) mode the
        # library validates the password but then calls ChifDisableSecurity(), so
        # blob operations proceed as the dynamic "systemadministrator" account and
        # the caller's identity is lost (breaking e.g. RecoverySet privilege
        # operations). Establishing a real session honours the specified user.
        #
        # Explicit credentials win even when a blobstore session is cached: reusing
        # the cached (typically "systemadministrator") session would defeat the
        # purpose. If the authenticated session cannot be built we fall back to the
        # passwordless CHIF path below, which for a cached session still retains its
        # 401-retry-after-login resilience. When no credentials are supplied the
        # fast passwordless path is preserved unchanged.
        if self._should_use_authenticated_chif(username, password):
            authenticated_response = self._perform_authenticated_chif_request(
                options, path, username, password, headers
            )
            if authenticated_response is not None:
                return authenticated_response
            LOGGER.debug("Authenticated CHIF path unavailable; falling back to passwordless CHIF")

        result = self._execute_chif_rawget(
            path,
            None,
            username=username,
            password=password,
            method=self._raw_method,
            body=self._raw_body,
        )
        LOGGER.debug("CHIF result type: %s, is_none: %s", type(result), result is None)

        if result is None:
            LOGGER.error("CHIF execution returned None")
            return self._create_error_response(500, "CHIF execution failed")

        return self._process_chif_result(result, auth_info, username, password, path)

    def _should_use_authenticated_chif(self, username, password):
        """Return True when explicit credentials must drive an authenticated CHIF session.

        CCSE-150273: In production/normal security mode the CHIF library validates the
        supplied password but then disables security, so subsequent blob operations run
        under the dynamic ``systemadministrator`` account rather than the specified user.
        When the caller supplies both a username and a password we must instead establish
        a genuine authenticated session as that user. The passwordless fast path is kept
        for the common no-credential case.

        :param username: Username supplied on the command line (or None).
        :param password: Password supplied on the command line (or None).
        :returns: True when both credentials are present and non-empty.
        :rtype: bool
        """
        return bool(username and password)

    def _perform_authenticated_chif_request(self, options, path, username, password, headers):
        """Execute an in-band request as an authenticated user over blobstore.

        Creates a ``RestClient`` blobstore session and performs an explicit
        session ``login()`` so the request runs under the supplied user's identity
        instead of the passwordless dynamic ``systemadministrator`` account
        (CCSE-150273). The session is always released via ``logout()`` in a
        ``finally`` block unless the caller reuses an existing ``sessionid``.

        :param options: Command options (consulted for an existing ``sessionid``).
        :param path: Redfish resource path.
        :param username: Username to authenticate as.
        :param password: Password to authenticate with.
        :param headers: Optional request headers.
        :returns: A ChifResponse-like object on success, or ``None`` so the caller
            can fall back to the passwordless CHIF path when a session cannot be
            established.
        """
        method = (self._raw_method or "GET").upper()
        body = self._raw_body
        reuse_session = getattr(options, "sessionid", None)
        rest_obj = None
        try:
            rest_obj = RestClient(
                username=username,
                password=password,
                base_url="blobstore://.",
                sessionid=reuse_session,
            )
            # Only create a fresh session when we are not reusing an existing one.
            if not reuse_session:
                rest_obj.login()
            response = self._dispatch_authenticated_verb(rest_obj, method, path, body, headers)
        except Exception as exc:
            # A credential rejection must fail fast: falling back to the passwordless
            # CHIF path would run the request as the dynamic "systemadministrator"
            # account, so a wrong -u/-p would silently succeed. Only non-credential
            # failures (no session could be established) may fall back.
            if self._is_credential_rejection_exception(exc):
                LOGGER.debug("iLO rejected the supplied credentials during authenticated CHIF login: %s", exc)
                self._chif_invalid_credentials = True
                status, error_data = self._invalid_chif_credentials_response()
                return self._create_chif_response(error_data, status)
            LOGGER.debug("Authenticated CHIF request failed: %s", exc)
            return None
        finally:
            # Always tear down a session we created; never log out a reused one.
            if rest_obj is not None and not reuse_session:
                try:
                    rest_obj.logout()
                except Exception:  # noqa: BLE001 - cleanup must never mask the result
                    LOGGER.debug("Authenticated CHIF session cleanup failed")

        status_code = self._extract_numeric_status_code(response)
        if status_code is None:
            LOGGER.error("Authenticated CHIF request returned no status code")
            return self._create_error_response(500, "CHIF request failed")

        response_headers = self._extract_smbios_response_headers(response)
        body_data = getattr(response, "dict", None)
        return self._create_chif_response(body_data, status_code, headers=response_headers)

    def _is_credential_rejection_exception(self, exc):
        """Return True when an exception means iLO rejected the supplied ``-u``/``-p``.

        Used to keep the passwordless CHIF fallback reserved for "no session could be
        established" failures. A genuine credential rejection must never fall back,
        because the passwordless path authenticates as the dynamic
        ``systemadministrator`` account and would let a wrong password succeed.

        :param exc: The exception raised while establishing/using the authenticated
            blobstore session.
        :rtype: bool
        """
        rejection_types = [InvalidCredentialsError]

        try:
            from redfish.hpilo.risblobstore2 import Blob2SecurityError

            rejection_types.append(Blob2SecurityError)
        except ImportError:
            LOGGER.debug("Blob2SecurityError unavailable for credential rejection check")

        try:
            from redfish.hpilo.rishpilo import HpIloChifAccessDeniedError

            rejection_types.append(HpIloChifAccessDeniedError)
        except ImportError:
            LOGGER.debug("HpIloChifAccessDeniedError unavailable for credential rejection check")

        # Guard against a non-exception placeholder (e.g. a stubbed module attribute),
        # which would make isinstance() raise instead of classifying the error.
        valid_types = tuple(t for t in rejection_types if isinstance(t, type) and issubclass(t, BaseException))
        return isinstance(exc, valid_types) if valid_types else False

    def _dispatch_authenticated_verb(self, rest_obj, method, path, body, headers):
        """Dispatch a raw HTTP verb over an authenticated blobstore ``RestClient``.

        :param rest_obj: A logged-in ``RestClient`` instance.
        :param method: HTTP verb (upper-cased).
        :param path: Redfish resource path.
        :param body: Request body for write verbs (dict/str) or None.
        :param headers: Optional request headers.
        :returns: The transport response object.
        :raises ValueError: If the verb is not supported over CHIF.
        """
        if method == "GET":
            return rest_obj.get(path, headers=headers)
        if method == "HEAD":
            return rest_obj.head(path, headers=headers)
        if method == "DELETE":
            return rest_obj.delete(path, headers=headers)

        payload = body if body is not None else {}
        if method == "POST":
            return rest_obj.post(path, body=payload, headers=headers)
        if method == "PUT":
            return rest_obj.put(path, body=payload, headers=headers)
        if method == "PATCH":
            return rest_obj.patch(path, body=payload, headers=headers)

        raise ValueError(f"Unsupported CHIF method: {method}")

    def _is_smbios_path(self, path):
        """Return True when the request targets the SMBIOS endpoint."""
        return is_smbios_path(path)

    def _perform_smbios_chif_request(self, options, path, username, password, headers):
        """Handle SMBIOS CHIF requests without forcing the payload through JSON decode."""
        rest_obj = None
        try:
            rest_obj = RestClient(
                sessionid=getattr(options, "sessionid", None),
                username=username,
                password=password,
                base_url="blobstore://.",
            )
            response = rest_obj.get(path, headers=headers)
        except Exception as exc:
            # Explicit credentials must fail fast in every mode: a rejection here is
            # returned as 401 rather than falling through to a path that could run
            # the request unauthenticated.
            if self._is_credential_rejection_exception(exc):
                LOGGER.debug("iLO rejected the supplied credentials during SMBIOS blobstore login: %s", exc)
                self._chif_invalid_credentials = True
                status, error_data = self._invalid_chif_credentials_response()
                return self._create_chif_response(error_data, status)
            LOGGER.debug("SMBIOS blobstore request fallback failed")
            return None
        finally:
            if rest_obj and not getattr(options, "sessionid", None):
                try:
                    rest_obj.logout()
                except Exception:
                    LOGGER.debug("SMBIOS blobstore session cleanup failed")

        status_code = self._extract_numeric_status_code(response)
        if status_code is None:
            LOGGER.error("SMBIOS blobstore request returned no status code")
            return self._create_error_response(500, "SMBIOS request failed")

        response_headers = self._extract_smbios_response_headers(response)
        if status_code < 200 or status_code >= 300:
            error_body = getattr(response, "dict", None)
            if error_body is None:
                error_body = {"error": {"message": self._get_status_message(status_code)}}
            return self._create_chif_response(error_body, status_code, headers=response_headers)

        raw_payload = self._extract_smbios_raw_payload(response)
        if raw_payload is None:
            payload = getattr(response, "dict", None)
            if payload is None:
                LOGGER.error("SMBIOS response did not contain a raw payload or parsed body")
                return self._create_error_response(500, "SMBIOS response was empty")
            return self._create_chif_response(payload, status_code, headers=response_headers)

        parsed_payload = self._normalize_smbios_payload(raw_payload)
        return self._create_chif_response(
            parsed_payload,
            status_code,
            raw_content=raw_payload,
            headers=response_headers,
        )

    def _extract_smbios_response_headers(self, response):
        """Normalize response headers from legacy and requests-style SMBIOS responses."""
        return extract_response_headers(response)

    def _extract_numeric_status_code(self, response):
        """Return the first concrete integer status code exposed by a response object."""
        return extract_numeric_status_code(response)

    def _extract_smbios_raw_payload(self, response):
        """Extract the raw SMBIOS payload from a legacy blobstore response."""
        return extract_smbios_raw_payload(response)

    def _normalize_smbios_payload(self, raw_payload):
        """Convert raw SMBIOS bytes into the JSON structure expected by rawget output."""
        return normalize_smbios_payload(raw_payload)

    def _unpack_smbios_data(self, data):
        """Decode an SMBIOS byte stream into a record list."""
        return unpack_smbios_data(data)

    def _perform_http_request(self, full_path, headers, auth_info):
        """Perform HTTP request using the verb and body set on the instance."""
        if auth_info["session_token"]:
            headers["X-Auth-Token"] = auth_info["session_token"]
        response = self._execute_request(
            self._raw_method,
            full_path,
            headers=headers,
            body=self._raw_body,
            auth=auth_info["auth"],
        )

        # SMBIOS payloads are binary and GET-only; normalize just like the CHIF path.
        if self._raw_method == "GET" and self._is_smbios_path(full_path):
            return self._normalize_smbios_http_response(response)

        return response

    def _normalize_smbios_http_response(self, response):
        """Convert raw SMBIOS HTTP payloads into the JSON structure expected by rawget."""
        status_code = self._extract_numeric_status_code(response)
        if status_code is None or status_code < 200 or status_code >= 300:
            return response

        raw_payload = self._extract_smbios_raw_payload(response)
        if not raw_payload:
            return response

        if is_json_content_type(response):
            return response

        try:
            parsed_payload = self._normalize_smbios_payload(raw_payload)
        except Exception as exc:
            LOGGER.debug("Failed to normalize SMBIOS HTTP payload: %s", exc)
            return response

        response_headers = self._extract_smbios_response_headers(response)
        return self._create_chif_response(
            parsed_payload,
            status_code,
            raw_content=raw_payload,
            headers=response_headers,
        )

    def _process_chif_result(self, result, auth_info, username, password, path):
        """Process CHIF result and handle fallback if needed.

        ``_execute_chif_rawget`` → ``_process_chif_response`` returns results in two forms:
        * **tuple** ``(status_code, data)`` — for **any** non-200 HTTP status, including 401.
          This is the *only* path through which a real 401 arrives.
        * **bare dict** — exclusively for HTTP 200 (``_process_chif_response`` returns
          ``data`` without wrapping it when ``status == 200``).

        Inferring 401 from the *presence of an "error" key* in a bare dict was therefore
        wrong: a 200 response from iLO may carry informational
        ``@Message.ExtendedInfo`` objects (e.g. ``iLO.2.37.SystemResetRequired``) that
        contain an ``"error"`` wrapper, yet the HTTP status is still 200.  The old
        inference produced false ``[401]`` output for those responses.
        """
        if isinstance(result, tuple):
            # Reason: all non-200 HTTP statuses (including real 401 Unauthorized)
            # are delivered as (status_code, data) tuples from _process_chif_response.
            status_code, data = result
        else:
            # Reason: bare dict means HTTP 200.  Do NOT infer 401 from an "error" key
            # — the key may be present in informational ExtendedInfo bodies on 200 OK.
            data = result
            status_code = 200

        response = self._create_chif_response(data, status_code)

        # Handle 401 fallback.
        # Reason: real 401s always arrive via the tuple branch above, so this
        # condition is only reachable when _execute_chif_rawget explicitly returned
        # a (401, ...) tuple — never triggered by a bare-dict 200+ExtendedInfo response.
        if status_code == 401 and auth_info["use_cached_session"] and username and password:
            return self._handle_chif_fallback(username, password, path) or response

        return response

    def _handle_chif_fallback(self, username, password, path):
        """Handle CHIF 401 fallback retry"""
        LOGGER.debug("Attempting CHIF fallback retry")
        try:
            if self._do_chif_login_temp(username, password):
                retry_result = self._execute_chif_rawget(path, None, username=username, password=password)
                if retry_result:
                    if isinstance(retry_result, tuple):
                        status, data = retry_result
                    else:
                        data, status = retry_result, 200
                    return self._create_chif_response(data, status)
        except Exception as e:
            LOGGER.debug("Fallback failed: %s", e)
        return None

    def _create_chif_response(self, data, status_code, raw_content=None, headers=None):
        """Create a response object for CHIF results, including captured response headers.

        :param data: parsed JSON body (or None).
        :param status_code: HTTP status code.
        :param raw_content: optional raw bytes payload (e.g. SMBIOS) to expose as
            ``.content`` without re-encoding ``data``; ``.json()`` still returns ``data``.
        :param headers: optional explicit response headers (e.g. from a SMBIOS blobstore
            GET). When omitted, headers captured from the raw in-band HTTP response
            (``self._last_chif_headers``) are used so ``--getheaders`` keeps working.
        """
        if headers is not None:
            resp_headers = dict(headers)
        else:
            # Use headers captured from the raw HTTP response (populated by
            # RawCommandBase._parse_raw_http_string) so --getheaders works in-band.
            resp_headers = dict(self._last_chif_headers) if self._last_chif_headers else {}
        if "Content-Type" not in resp_headers:
            resp_headers["Content-Type"] = "application/json"

        class ChifResponse:
            def __init__(self, data, status_code, raw_content, resp_headers):
                self.status_code = status_code
                self._json_body = data
                json_text = json.dumps(data, separators=(",", ":")) if data is not None else ""
                self.content = raw_content if raw_content is not None else json_text.encode("utf-8")
                self.text = json_text
                self.headers = resp_headers

            def json(self):
                if self._json_body is not None:
                    return self._json_body
                return json.loads(self.content) if self.content else {}

        return ChifResponse(data, status_code, raw_content, resp_headers)

    def _create_error_response(self, status_code, message):
        """Create an error response"""
        error_data = {"error": {"message": message}}
        return self._create_chif_response(error_data, status_code)

    def _handle_response(self, response, options):
        """Handle the response and format output"""

        return_response = getattr(options, "response", False) or getattr(options, "getheaders", False)

        if getattr(options, "filename", None):
            return self._write_response_into_file(response, options)

        if getattr(options, "binfile", None):
            return self._write_response_in_binary(response, options)

        if return_response:
            return self._format_response_output(response, options)
        else:
            return self._format_json_output(response, options)

    def _body_stream(self, options):
        """Return the stream to write the response body to.

        Normally this is stdout so that the HTTP status line (stderr) and the
        JSON body (stdout) can be separated by the caller.  When --stderr_flag
        is set both streams go to stderr, which matches the legacy v4.0
        behaviour and lets tooling that only captures stderr receive the full
        output in one stream.
        """
        if getattr(options, "stderr_flag", False):
            return sys.stderr
        return sys.stdout

    @staticmethod
    def _response_status(response):
        """Return the HTTP status of a new-engine or legacy response object.

        Reason: a response may expose a ``status_code`` attribute that is not a
        usable integer (legacy objects, or test doubles that auto-create
        attributes). Each candidate is therefore accepted only when it is an int,
        so a legacy ``status`` is still found when ``status_code`` is unusable.

        :param response: Response exposing ``status_code`` (new engine) or
            ``status`` (legacy framework).
        :returns: The status code as an int, or None when neither is usable.
        """
        for attribute in ("status_code", "status"):
            value = getattr(response, attribute, None)
            # Reason: bool is an int subclass in Python; a stray True/False from an
            # auto-speccing test double must not be mistaken for a status code.
            if isinstance(value, int) and not isinstance(value, bool):
                return value
        return None

    def _emit_status_line(self, status, options):
        """Print the ``[<code>] <message>`` line, honouring --silent/--stderr_flag.

        Used by the file-output paths so they report status exactly like the
        normal output path does.

        :param status: HTTP status code (int) or None.
        :param options: Parsed CLI options.
        """
        if getattr(options, "silent", False):
            return
        out = self._body_stream(options)
        out.write(f"[{status}] {self._get_status_message(status)}\n")
        out.flush()

    def _write_response_into_file(self, response, options=None):
        """
        Write the response to the specified file.
        """
        try:
            import redfish

            status = self._response_status(response)

            # Full 2xx range counts as success (JIRA134308 established that a
            # 201/204 must not be reported as a failure) and the status line is
            # emitted for BOTH the new-engine and legacy branches.
            if status is not None and 200 <= status < 300:
                self._emit_status_line(status, options)
                if isinstance(getattr(response, "status_code", None), int):
                    # Reason: 204 and other empty successes have no JSON to decode.
                    data = response.json() if response.content else None
                else:
                    # status from legacy old framework
                    data = response.dict
            else:
                self._emit_status_line(status, options)
                # Use the shared error mapping so `-f` reports the same exit code
                # as a plain request (JIRA144231: a 4xx must be 63, not 255).
                return self._status_error_return_code(status) if status is not None else ReturnCodes.GENERAL_ERROR

            output = json.dumps(
                data,
                indent=2,
                cls=redfish.ris.JSONEncoder,
                sort_keys=True,
            )

            with open(options.filename[0], "w") as file_hndl:
                file_hndl.write(output)

            self.rdmc.ui.printer(f"Results written out to '{options.filename[0]}'.\n")
            return ReturnCodes.SUCCESS
        except Exception as e:
            LOGGER.error("Response writing into file failed: %s", e)
            sys.stderr.write(f"Error: Failed to write response into file - {str(e)}\n")
            return ReturnCodes.GENERAL_ERROR

    def _write_response_in_binary(self, response, options=None):
        """
        Write the response to the specified file in binary.
        """
        try:
            status = self._response_status(response)

            # Mirrors _write_response_into_file: full 2xx range is success, the
            # status line is emitted for both response shapes, and errors use the
            # shared exit-code mapping.
            if status is not None and 200 <= status < 300:
                self._emit_status_line(status, options)
                if isinstance(getattr(response, "status_code", None), int):
                    data = response.content
                else:
                    # status from legacy old framework
                    data = json.dumps(response.dict, separators=(",", ":")).encode("utf-8")
            else:
                self._emit_status_line(status, options)
                return self._status_error_return_code(status) if status is not None else ReturnCodes.GENERAL_ERROR

            with open(options.binfile[0], "wb") as file_hndl:
                file_hndl.write(data)

            self.rdmc.ui.printer(f"Results written out to '{options.binfile[0]}'\n")
            return ReturnCodes.SUCCESS
        except Exception as e:
            LOGGER.error("Response writing into binary file failed: %s", e)
            sys.stderr.write(f"Error: Failed to write a response into binary - {str(e)}\n")
            return ReturnCodes.GENERAL_ERROR

    def _format_response_output(self, response, options=None):
        """Format response with headers and body

        Output format:
        - stdout (or stderr if --stderr_flag): [<status_code>] <status_message or MessageId>
        - stdout: headers (if --getheaders) — pretty-printed for write verbs
          (POST/PUT/PATCH/DELETE) to match 7.3, compact JSON for GET
        - stdout: body (if --response) — raw iLO body text for write verbs to match
          7.3 (result.ori), compact JSON for GET
        """
        try:
            body = response.json() if response.content else None
            status_msg = self._status_line_message(response, body)
            is_silent = getattr(options, "silent", False) if options else False

            out = self._body_stream(options)
            # --silent suppresses only the status line, not the body
            if not is_silent:
                out.write(f"[{response.status_code}] {status_msg}\n")
            show_headers = getattr(options, "getheaders", False) if options else True
            show_body = getattr(options, "response", False) if options else True

            is_write_verb = getattr(self, "_raw_method", "GET") in self._WRITE_VERBS
            if show_headers:
                if is_write_verb:
                    # 7.3 write verbs pretty-printed headers (ui.print_out_json).
                    sys.stdout.write(f"{json.dumps(dict(response.headers), indent=2, sort_keys=True)}\n")
                else:
                    sys.stdout.write(f"{json.dumps(dict(response.headers), separators=(',', ':'))}\n")
            if show_body and body is not None:
                if is_write_verb:
                    # 7.3 write verbs echoed the raw iLO response body (result.ori)
                    # rather than a re-serialized compact JSON. Prefer the raw text
                    # when available (out-of-band HTTP); fall back to compact JSON.
                    raw_text = getattr(response, "text", None)
                    if raw_text:
                        sys.stdout.write(f"{raw_text}\n")
                    else:
                        sys.stdout.write(f"{json.dumps(body, separators=(',', ':'))}\n")
                else:
                    sys.stdout.write(f"{json.dumps(body, separators=(',', ':'))}\n")
            sys.stdout.flush()

            if 200 <= response.status_code < 300:
                return ReturnCodes.SUCCESS
            return self._status_error_return_code(response.status_code, response_output=True)
        except Exception as e:
            LOGGER.error("Response formatting failed: %s", e)
            sys.stderr.write(f"Error: Failed to format response - {str(e)}\n")
            return ReturnCodes.GENERAL_ERROR

    def _get_status_message_from_response(self, response, body=None):
        """Get status message, extracting MessageId from error responses

        For error responses (4xx, 5xx), extracts the MessageId from the
        @Message.ExtendedInfo array in the error response body.

        :param response: HTTP response object
        :param body: Pre-parsed response body (optional, to avoid double parsing)
        :returns: Status message string
        """
        # For error responses, try to extract MessageId from the response body
        if hasattr(response, "status_code"):
            status_code = response.status_code
            resp_data = response.json() if response.content else None
        else:
            status_code = getattr(response, "status", None)
            resp_data = response.dict if hasattr(response, "dict") else response

        if status_code and status_code >= 400:
            try:
                data = body if body else resp_data
                if data and "error" in data:
                    ext_info = data["error"].get("@Message.ExtendedInfo", [])
                    if ext_info and len(ext_info) > 0:
                        message_id = ext_info[0].get("MessageId", "")
                        if message_id:
                            return message_id
            except Exception:
                pass

        # Fall back to generic status messages
        return self._get_status_message(status_code)

    def _get_status_message(self, status_code):
        """Get human-readable status message for HTTP status code"""
        if status_code is None:
            # Reason: avoid the confusing "[None] HTTP None" line when no status
            # was ever obtained (e.g. transport failure before a response arrived).
            return "No HTTP status received."
        status_messages = {
            200: "The operation completed successfully.",
            201: "Resource created successfully.",
            202: "Request accepted for processing.",
            204: "No content.",
            400: "Bad request.",
            401: "Authentication required.",
            403: "Access forbidden.",
            404: "Resource not found.",
            405: "Method not allowed.",
            409: "Conflict.",
            500: "Internal server error.",
            503: "Service unavailable.",
        }
        return status_messages.get(status_code, f"HTTP {status_code}")

    # HTTP verbs that mutate state. In 7.3 these were dispatched through the
    # iLOrest library handlers (post/put/patch/delete_handler), which printed the
    # generic "The operation completed successfully." for ANY 2xx result, whereas
    # GET used the code-specific table above (e.g. 201 -> "Resource created
    # successfully."). _WRITE_VERBS lets the shared formatter reproduce that split.
    _WRITE_VERBS = ("POST", "PUT", "PATCH", "DELETE")

    def _status_line_message(self, response, body=None):
        """Return the status-line message that matches legacy 7.3 wording.

        For a successful (2xx) write verb the generic library message
        ("The operation completed successfully.") is used regardless of the exact
        code, matching how 7.3 rendered rawpost/rawput/rawpatch/rawdelete. All
        other cases (GET, and every error response) fall back to the code-specific
        table / MessageId extraction in _get_status_message_from_response.

        NOTE: The generic wording for 2xx write verbs is deliberate and was
        introduced by JIRA149247 — do not substitute the iLO
        ``@Message.ExtendedInfo`` text here without re-validating that ticket.

        :param response: HTTP/CHIF response object.
        :param body: pre-parsed response body (optional, avoids double parsing).
        :returns: status message string.
        """
        status_code = getattr(response, "status_code", None)
        if status_code is None:
            status_code = getattr(response, "status", None)
        is_write_verb = getattr(self, "_raw_method", "GET") in self._WRITE_VERBS
        if is_write_verb and status_code is not None and 200 <= status_code < 300:
            return "The operation completed successfully."
        return self._get_status_message_from_response(response, body)

    def _status_error_return_code(self, status_code: int, *, response_output: bool = False) -> int:
        """Map a non-2xx status without changing existing 7.4 exit codes.

        Args:
            status_code: HTTP status code from the transport.
            response_output: Whether --response or --getheaders selected the
                response formatter. In 7.4 this mode reports 3xx as RC 63,
                whereas normal, file and HEAD output report 3xx as RC 255.

        Returns:
            Session expired for 401, iLO response error for 4xx/5xx (and 3xx
            in response mode), or general error otherwise. Silent output never
            changes the result.
        """
        if status_code == 401:
            return ReturnCodes.RIS_SESSION_EXPIRED
        if status_code >= 400 or (response_output and status_code >= 300):
            return ReturnCodes.RIS_ILO_RESPONSE_ERROR
        return ReturnCodes.GENERAL_ERROR

    def _format_json_output(self, response, options=None):
        """Format JSON output"""
        body = response.json() if response.content else None
        status_msg = self._status_line_message(response, body)
        is_silent = getattr(options, "silent", False) if options else False

        out = self._body_stream(options)
        # --silent suppresses only the status line, not the body
        if not is_silent:
            out.write(f"[{response.status_code}] {status_msg}\n")
        if 200 <= response.status_code < 300:
            try:
                # Only GET-style raw commands emit the response body by default.
                # Write verbs (POST/PUT/PATCH/DELETE) print just the status line
                # to match the legacy 7.3 behaviour; their body remains available
                # on demand via the --response flag (handled by
                # _format_response_output).
                if body is not None and getattr(self, "_raw_method", "GET") == "GET":
                    if options and getattr(options, "service", False):
                        # Output as Python dict format (with single quotes)
                        sys.stdout.write(f"{repr(body)}\n")
                    else:
                        sys.stdout.write(f"{json.dumps(body, indent=2, sort_keys=True, separators=(',', ':'))}\n")
                out.flush()
                return ReturnCodes.SUCCESS
            except Exception as e:
                LOGGER.error("JSON parsing failed: %s", e)
                sys.stderr.write(f"Error: JSON parsing failed - {str(e)}\n")
                return ReturnCodes.INVALID_COMMAND_LINE_ERROR
        else:
            if body is not None:
                out.write(f"{json.dumps(body, separators=(',', ':'))}\n")
                out.flush()

        return self._status_error_return_code(response.status_code)

    def _handle_error_response(self, response):
        """Handle error responses"""
        try:
            error_data = response.json()
            if "error" in error_data:
                error_msg = error_data["error"].get("message", "Unknown error")
                sys.stderr.write(f"Error: {error_msg}\n")
            else:
                sys.stderr.write(f"Error: HTTP {response.status_code}\n")
        except Exception:
            sys.stderr.write(f"Error: HTTP {response.status_code}\n")

    def _capture_temp_session_for_cleanup(self, response, auth_info):
        """Capture an iLO-created Basic-Auth session so cleanup can delete it.

        When an out-of-band request authenticates with HTTP Basic Auth, iLO
        creates a transient Redfish session for that single request and returns
        its URI in the response ``Location`` header (and the token in
        ``X-Auth-Token``). iLORest never created this session explicitly, so
        without capturing these headers the session is never deleted and leaks
        on iLO until it times out. This completes the ``temp_session_created`` /
        ``needs_logout`` contract that ``_cleanup_session`` relies on.

        Only temporary sessions created by credential (Basic) auth are captured.
        Cached/persistent sessions (``use_cached_session``), CHIF/in-band
        requests (``use_chif_method``) and already-tracked explicit sessions
        (``session_location`` already set, e.g. a VNIC login) are left untouched
        so they are never accidentally deleted.

        :param response: HTTP response object returned by the request
        :param auth_info: authentication/session bookkeeping dict (mutated in place)
        """
        if not (auth_info.get("temp_session_created") and auth_info.get("needs_logout")):
            return
        if auth_info.get("use_cached_session") or auth_info.get("use_chif_method"):
            return
        if auth_info.get("session_location"):
            # An explicit session (e.g. VNIC login) is already tracked for cleanup.
            return
        if auth_info.get("auth_type") != "credentials":
            return

        try:
            resp_headers = getattr(response, "headers", None) or {}
            location = resp_headers.get("Location") or resp_headers.get("location")
            token = resp_headers.get("X-Auth-Token") or resp_headers.get("x-auth-token")
            if location:
                auth_info["session_location"] = location
                if token and not auth_info.get("session_token"):
                    auth_info["session_token"] = token
                LOGGER.debug("Captured iLO Basic-Auth session location for cleanup")
        except Exception as e:
            LOGGER.debug("Could not capture temp session from response headers: %s", e)

    def _cleanup_session(self, auth_info):
        """Cleanup temporary sessions"""
        if auth_info.get("temp_session_created") and auth_info.get("needs_logout"):
            session_location = auth_info.get("session_location")
            session_token = auth_info.get("session_token")
            if session_location:
                try:
                    self._logout_temp_session(session_location, session_token)
                    LOGGER.debug("Temporary session cleaned up successfully")
                except Exception as e:
                    LOGGER.debug("Session cleanup failed: %s", e)
            else:
                LOGGER.debug("No session location available for cleanup")

    def _run_with_old_framework(self, options, headers, path):
        """Fallback to old framework for compatibility (high security mode)

        Uses get_handler() which returns a response object with .dict, .status,
        and .getheaders() — unlike get() which only returns a parsed dict and
        loses response headers and status code information.
        """
        LOGGER.debug("Using legacy framework for backward compatibility")

        try:
            # Ensure framework is initialized for implicit login.
            # Call login_validation directly instead of getvalidation because
            # getvalidation skips login when --service is set, but the legacy
            # framework always needs an initialized client to work.
            if not hasattr(self.rdmc.app, "redfishinst") or not self.rdmc.app.redfishinst:
                LOGGER.debug("Implicit login required for legacy framework")
                try:
                    self.cmdbase.login_validation(self, options, skipbuild=True)
                except Exception as login_ex:
                    # Wrong -u/-p is an authentication failure, not a session
                    # initialization failure: report it uniformly and never print the
                    # raw exception text (InvalidCredentialsError stringifies to its
                    # retry delay, e.g. "0", which is meaningless to the user).
                    if self._is_credential_rejection_exception(login_ex):
                        LOGGER.debug("Legacy framework login rejected the supplied credentials: %s", login_ex)
                        sys.stderr.write(self.INVALID_CREDENTIALS_MESSAGE)
                        return ReturnCodes.V1_INVALID_CREDENTIALS_ERROR

                    LOGGER.error("Login validation failed: %s", login_ex)
                    import traceback

                    LOGGER.debug(traceback.format_exc())
                    sys.stderr.write(f"Error: Failed to initialize session - {str(login_ex)}\n")
                    try:
                        import redfish.hpilo.rishpilo as rishpilo

                        if isinstance(login_ex, rishpilo.HpIloChifPacketExchangeError):
                            LOGGER.debug("Detected CHIF packet exchange error - iLO unreachable during login")
                            return ReturnCodes.RIS_ILO_CHIF_PACKET_EXCHANGE_ERROR
                        elif isinstance(login_ex, rishpilo.HpIloChifAccessDeniedError):
                            LOGGER.debug("Detected CHIF access denied error during login")
                            return ReturnCodes.V1_INVALID_CREDENTIALS_ERROR
                        elif isinstance(login_ex, rishpilo.HpIloInitialError):
                            LOGGER.debug("Detected iLO initialization error - iLO unreachable during login")
                            return ReturnCodes.RIS_ILO_CHIF_PACKET_EXCHANGE_ERROR
                    except (ImportError, AttributeError, TypeError):
                        LOGGER.debug(
                            "ImportError, AttributeError or TypeError while checking for iLO exceptions "
                            "during login validation"
                        )
                        pass

                    # Runtime initialization failures are not command-line errors.
                    return ReturnCodes.INVALID_COMMAND_LINE_ERROR

            if not hasattr(self.rdmc.app, "get_handler"):
                sys.stderr.write("Error: Legacy framework not available\n")
                return ReturnCodes.INVALID_COMMAND_LINE_ERROR

            is_silent = getattr(options, "silent", False)
            is_service = getattr(options, "service", False)

            username, password = self._get_cred(options)

            results = self._invoke_framework_handler(path, headers, options)

            if not results or not (200 <= results.status < 300):
                status = results.status if results else 500

                # Handle 401 Unauthorized - cached session expired, retry with fresh login
                if status == 401 and getattr(options, "user", None) and getattr(options, "password", None):
                    LOGGER.debug("Received 401 Unauthorized, cached session expired - forcing re-login")

                    # Force logout to clear the stale session
                    try:
                        if hasattr(self.rdmc.app, "logout"):
                            LOGGER.debug("Logging out stale session")
                            self.rdmc.app.logout()
                    except Exception as logout_ex:
                        LOGGER.debug("Logout failed (expected): %s", logout_ex)

                    # Force fresh login with provided credentials
                    LOGGER.debug("Performing fresh login with credentials")
                    try:
                        self.cmdbase.login_validation(self, options, skipbuild=True)
                    except Exception as login_ex:
                        LOGGER.error("Re-login validation failed: %s", login_ex)
                        import traceback

                        LOGGER.debug(traceback.format_exc())

                        try:
                            import redfish.hpilo.rishpilo as rishpilo

                            if isinstance(login_ex, rishpilo.HpIloChifPacketExchangeError):
                                LOGGER.debug("Detected CHIF packet exchange error - iLO unreachable during re-login")
                                return ReturnCodes.RIS_ILO_CHIF_PACKET_EXCHANGE_ERROR
                            elif isinstance(login_ex, rishpilo.HpIloChifAccessDeniedError):
                                LOGGER.debug("Detected CHIF access denied error during re-login")
                                return ReturnCodes.V1_INVALID_CREDENTIALS_ERROR
                            elif isinstance(login_ex, rishpilo.HpIloInitialError):
                                LOGGER.debug("Detected iLO initialization error - iLO unreachable during re-login")
                                return ReturnCodes.RIS_ILO_CHIF_PACKET_EXCHANGE_ERROR
                        except (ImportError, AttributeError):
                            LOGGER.debug(
                                "ImportError or AttributeError while checking for iLO exceptions "
                                "during relogin validation"
                            )
                            pass

                        sys.stderr.write(f"Error: Re-login failed - {str(login_ex)}\n")
                        return ReturnCodes.INVALID_COMMAND_LINE_ERROR

                    # Retry the request with fresh session
                    LOGGER.debug("Retrying request with fresh session")
                    results = self._invoke_framework_handler(path, headers, options)

                    # Check if retry succeeded
                    if results and 200 <= results.status < 300:
                        LOGGER.info("Retry after re-login successful")
                    else:
                        retry_status = results.status if results else 500
                        LOGGER.error("Retry after re-login failed with status: %s", retry_status)
                        if not is_silent:
                            sys.stdout.write(f"[{retry_status}] {self._get_status_message(retry_status)}\n")
                        if retry_status == 401:
                            return ReturnCodes.RIS_SESSION_EXPIRED
                        elif retry_status >= 400:
                            return ReturnCodes.RIS_ILO_RESPONSE_ERROR
                        return ReturnCodes.GENERAL_ERROR
                else:
                    if not is_silent:
                        sys.stdout.write(f"[{status}] {self._get_status_message(status)}\n")
                    if status == 401:
                        return ReturnCodes.RIS_SESSION_EXPIRED
                    elif status >= 400:
                        return ReturnCodes.RIS_ILO_RESPONSE_ERROR
                    return ReturnCodes.GENERAL_ERROR

            return_response = getattr(options, "response", False) or getattr(options, "getheaders", False)

            if getattr(options, "filename", None):
                return self._write_response_into_file(results, options)

            if getattr(options, "binfile", None):
                return self._write_response_in_binary(results, options)

            # Print status line (suppressed by --silent), matching other handlers
            if not is_silent:
                status = results.status if results else 200
                out = self._body_stream(options)
                out.write(f"[{status}] {self._get_status_message(status)}\n")

            if return_response:
                if getattr(options, "getheaders", False):
                    resp_headers = {}
                    if hasattr(results, "getheaders") and results.getheaders():
                        resp_headers = dict(results.getheaders())
                    elif hasattr(results, "_headers") and results._headers:
                        resp_headers = dict(results._headers)
                    sys.stdout.write(f"{json.dumps(resp_headers, separators=(',', ':'))}\n")
                if getattr(options, "response", False):
                    body = results.dict if hasattr(results, "dict") else {}
                    sys.stdout.write(f"{json.dumps(body, separators=(',', ':'))}\n")
                sys.stdout.flush()
            else:
                body = results.dict if hasattr(results, "dict") else results
                if isinstance(body, (dict, list)):
                    if is_service:
                        sys.stdout.write(f"{json.dumps(body, separators=(',', ':'))}\n")
                    else:
                        sys.stdout.write(f"{json.dumps(body, indent=2, sort_keys=True, separators=(',', ':'))}\n")
                else:
                    sys.stdout.write(f"{body}\n")
                sys.stdout.flush()

            return ReturnCodes.SUCCESS

        except Exception as e:
            # A credential rejection is not a framework failure: report it as the
            # canonical invalid-credentials error instead of leaking the raw
            # exception text (e.g. InvalidCredentialsError's retry delay, "0").
            if self._is_credential_rejection_exception(e):
                LOGGER.debug("Legacy framework rejected the supplied credentials: %s", e)
                sys.stderr.write(self.INVALID_CREDENTIALS_MESSAGE)
                return ReturnCodes.V1_INVALID_CREDENTIALS_ERROR

            LOGGER.error("Legacy framework execution failed: %s", e)
            import traceback

            LOGGER.debug(traceback.format_exc())
            error_msg = str(e) if str(e) else "Unknown error occurred"
            sys.stderr.write(f"Error: Legacy framework failed - {error_msg}\n")
            try:
                import redfish.hpilo.rishpilo as rishpilo
                import redfish.ris as ris

                if isinstance(e, (rishpilo.HpIloChifPacketExchangeError, rishpilo.HpIloInitialError)):
                    return ReturnCodes.RIS_ILO_CHIF_PACKET_EXCHANGE_ERROR
                if isinstance(e, rishpilo.HpIloChifAccessDeniedError):
                    return ReturnCodes.V1_INVALID_CREDENTIALS_ERROR
                if isinstance(e, ris.SessionExpired):
                    return ReturnCodes.RIS_SESSION_EXPIRED
            except (ImportError, AttributeError, TypeError):
                LOGGER.debug(
                    "ImportError, AttributeError or TypeError while checking for iLO exceptions "
                    "during legacy framework execution"
                )
                pass

            return ReturnCodes.INVALID_COMMAND_LINE_ERROR

    def _invoke_framework_handler(self, path, headers, options):
        """Invoke the legacy rdmc.app GET handler.

        Subclasses override this to call their verb-specific handler
        (patch_handler, post_handler, put_handler, delete_handler, head_handler).
        """
        is_service = getattr(options, "service", False)
        username, password = self._get_cred(options)
        return self.rdmc.app.get_handler(
            path,
            headers=headers,
            silent=True,
            service=is_service,
            username=username,
            password=password,
        )

    # ------------------------------------------------------------------
    # Shared helpers for body-having commands (PATCH / POST / PUT)
    # ------------------------------------------------------------------

    def _load_body_file(self, file_path):
        """Load and parse a JSON body file.

        :param file_path: Path to the JSON input file
        :returns: Parsed OrderedDict
        :raises InvalidFileInputError: file not found
        :raises InvalidFileFormattingError: invalid JSON
        """
        from collections import OrderedDict

        try:
            with open(file_path, "r") as fh:
                return json.loads(fh.read(), object_pairs_hook=OrderedDict)
        except IOError:
            raise InvalidFileInputError(
                f"File '{file_path}' doesn't exist. " "Please create file by running 'save' command."
            )
        except ValueError:
            raise InvalidFileFormattingError(f"Input file '{file_path}' was not formatted properly.")

    def _extract_path_body_pairs(self, contentsholder, filename):
        """Extract (redfish_path, body) pairs from parsed body file.

        Supports two file formats:
        1. ``{"path": "/redfish/...", "body": {...}}``  — single pair
        2. ``{"/redfish/...": {...}, ...}``             — multiple pairs

        :raises InvalidFileFormattingError: on unrecognised format
        """
        if "path" in contentsholder and "body" in contentsholder:
            return [(contentsholder["path"], contentsholder["body"])]
        if contentsholder and all(re.match(r"^/(\S+/?)+$", k) for k in contentsholder):
            return list(contentsholder.items())
        raise InvalidFileFormattingError(f"Input file '{filename}' was not formatted properly.")
