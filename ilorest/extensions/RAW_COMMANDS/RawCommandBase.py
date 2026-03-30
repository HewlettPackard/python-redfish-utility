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

import json
import logging
import re

try:
    from rdmc_helper import InvalidCommandLineError, Encryption
except ImportError:
    from ilorest.rdmc_helper import InvalidCommandLineError, Encryption

try:
    from redfish.rest.connections import SecurityStateError, InvalidCredentialsError
except ImportError:
    # Define fallback classes if imports fail
    class SecurityStateError(Exception):
        pass

    class InvalidCredentialsError(Exception):
        pass


LOGGER = logging.getLogger(__name__)

# HTTP timeout constant
HTTP_TIMEOUT_SECONDS = 30

# iLO version constants
ILO_VERSION_6 = 6.0
ILO_VERSION_7 = 7.0


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

    # Class-level in-memory cache for iLO version (shared across all instances)
    # This avoids repeated file I/O for iLO generation lookup
    # iLO generation is hardware-based and never changes, so no expiry needed
    _ilo_version_memory_cache = None

    # Class-level in-memory cache for security state (shared across all instances)
    # Security state is obtained during version detection and should be reused
    _security_state_memory_cache = None

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
        """Mask username:password credentials"""
        username = creds.split(":", 1)[0]
        if len(username) > 3:
            return f"{username[:3]}***:***"
        return "***:***"

    def _mask_simple_token(self, token):
        """Mask a simple token credential"""
        if token and len(token) > 3:
            return f"{token[:3]}***"
        return "***"

    def _get_url_from_session(self):
        """Extract base URL from existing session

        :returns: URL string or None
        :rtype: str or None
        """
        inst = self._get_redfish_instance()
        if not inst:
            return None

        # Get base URL from primary attribute
        if hasattr(inst, "base_url") and inst.base_url:
            return getattr(inst, "base_url")

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
            LOGGER.debug(f"Attribute error accessing session: {str(e)}")
            return None
        except Exception as e:
            LOGGER.warning(f"Unexpected error retrieving cached session token: {str(e)}")
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

        LOGGER.debug(f"URL validated: {self._mask_url_credentials(url)}")
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
        import requests

        headers = self._prepare_request_headers(headers, body)
        kwargs = self._prepare_request_kwargs(headers, body, auth, timeout, method)

        method_func = self._get_request_method(method, requests)
        LOGGER.debug(f"Executing {method} request to {self._mask_url_credentials(path)}")

        return method_func(path, **kwargs)

    def _prepare_request_headers(self, headers, body):
        """Prepare request headers"""
        if headers is None:
            headers = {}

        if "Content-Type" not in headers and body:
            headers["Content-Type"] = "application/json"

        return headers

    def _prepare_request_kwargs(self, headers, body, auth, timeout, method):
        """Prepare keyword arguments for requests call"""
        kwargs = {"headers": headers, "verify": False, "timeout": timeout}

        if auth:
            kwargs["auth"] = auth  # type: ignore[assignment]

        if body and method.upper() in ["POST", "PUT", "PATCH"]:
            kwargs["data"] = json.dumps(body) if isinstance(body, dict) else body  # type: ignore[assignment]

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
        # Tier 1: Check in-memory cache first (fastest - no I/O)
        # iLO generation never changes, so no expiry check needed
        if RawCommandBase._ilo_version_memory_cache is not None:
            self._safe_log_debug(
                f"Using in-memory cached iLO version (ultra-fast path): {RawCommandBase._ilo_version_memory_cache}"
            )
            return RawCommandBase._ilo_version_memory_cache

        # Tier 2: Try to load from persistent file cache (fast - one file read)
        cached_version = self._load_ilo_version_from_cache()
        if cached_version is not None:
            # Update in-memory cache for next call
            RawCommandBase._ilo_version_memory_cache = cached_version
            self._safe_log_debug(f"Loaded iLO version from file cache, updated memory cache: {cached_version}")
            return cached_version

        try:
            # Tier 3: Perform actual detection (slow - first time only)
            self._safe_log_debug("No cache found - performing first-time iLO detection")
            version = self._do_version_detection()

            # Cache the result in both memory and file (persists indefinitely)
            if version:
                RawCommandBase._ilo_version_memory_cache = version
                self._save_ilo_version_to_cache(version)
                self._safe_log_debug(f"Detected and cached iLO version (memory + file): {version}")

            return version

        except Exception as e:
            self._safe_log_debug(f"iLO version detection failed: {str(e)}")
            return None

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
            LOGGER.debug(f"Could not create directory {directory}: {e}")
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
            import os
            import json

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
                self._safe_log_debug(f"Found valid cache: iLO {generation} (bypassed detection, no expiry)")
                # Also restore security_state into memory cache so _is_high_security_mode()
                # and _get_security_state_from_cache() skip a second hardware detection call
                cached_sec_state = cache_data.get("security_state")
                if cached_sec_state is not None and RawCommandBase._security_state_memory_cache is None:
                    RawCommandBase._security_state_memory_cache = int(cached_sec_state)
                    self._safe_log_debug(f"Restored security state from file cache: {cached_sec_state}")
                return float(generation)

        except Exception as e:
            self._safe_log_debug(f"Failed to load cache file: {e}")

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
            import os
            import json

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
                LOGGER.debug(f"Could not save iLO version to cache file (permission issue?): {e}")
        except Exception as e:
            LOGGER.debug(f"Failed to save iLO version to cache: {e}")

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
        LOGGER.debug(f"Detected iLO{ilo_ver} via getilover_beforelogin (security state: {sec_state})")

        # Cache security state to avoid redundant detection later
        # This is a significant performance optimization
        self._cached_security_state = sec_state
        RawCommandBase._security_state_memory_cache = sec_state

        # Normalize version string
        return self._normalize_ilo_version_string(ilo_ver)

    def _handle_getilover_exception(self, exception):
        """Handle exceptions from getilover detection"""
        from redfish.rest.connections import ChifDriverMissingOrNotFound, VnicNotEnabledError

        if isinstance(exception, ChifDriverMissingOrNotFound):
            LOGGER.debug("CHIF driver missing, likely iLO7, using VNIC fallback")
        elif isinstance(exception, VnicNotEnabledError):
            LOGGER.debug("VNIC not enabled but detected iLO7")
            return ILO_VERSION_7
        else:
            LOGGER.debug(f"getilover_beforelogin failed: {exception}, using fallback")

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
        """Fallback detection using VNIC probe to distinguish iLO7 from iLO5/6"""
        LOGGER.debug("Using VNIC probe fallback for version detection...")

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
            LOGGER.debug(f"VNIC probe failed: {e}, defaulting to iLO6")
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

        # Try cached session (unless nocache)
        if not nocache:
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

        This is critical for iLO 6 which may or may not have VNIC enabled.
        - iLO 6 with VNIC: Use VNIC authentication
        - iLO 6 without VNIC: Use CHIF authentication
        - iLO 7: Always uses VNIC

        :returns: True if VNIC is available, False otherwise
        :rtype: bool
        """
        try:
            # Quick probe to check if VNIC endpoint is accessible
            import socket

            vnic_host = self.DEFAULT_ILO_URL.replace("https://", "").replace("http://", "")
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)  # Short timeout for quick check
            result = sock.connect_ex((vnic_host, 443))
            sock.close()

            vnic_available = result == 0
            if vnic_available:
                LOGGER.debug("VNIC is available on this iLO")
            else:
                LOGGER.debug("VNIC is not available - will use CHIF")

            return vnic_available
        except Exception as e:
            LOGGER.debug(f"VNIC availability check failed: {e}, assuming not available")
            return False

    def _is_high_security_mode(self):
        """Check if iLO is in high security mode"""
        # Use cached security state if available to avoid a redundant getilover_beforelogin() call.
        # _security_state_memory_cache is populated by _perform_getilover_detection() during
        # iLO version detection, so checking it here avoids a second round-trip to iLO.
        if RawCommandBase._security_state_memory_cache is not None:
            sec_state = RawCommandBase._security_state_memory_cache
            LOGGER.debug(f"Using cached security state: {sec_state}")
            return sec_state in [4, 5, 6]

        try:
            return self._check_security_state()
        except Exception as e:
            LOGGER.debug(f"Could not determine security mode: {e}")
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
                result = self.rdmc.app.token_exists()
                if result:
                    LOGGER.debug("App account found via app layer token_exists()")
                    return True
        except Exception as e:
            LOGGER.debug(f"App layer token_exists() check failed: {e}")

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
                result = self.rdmc.app.token_exists(app_obj)
                if result:
                    LOGGER.debug("App account found via direct AppAccount check")
                    return True

        except Exception as e:
            LOGGER.debug(f"Direct AppAccount check failed: {e}")

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
        """Handle iLO 6/7 VNIC mode authentication"""
        ilo_version = self._get_ilo_version()

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
            LOGGER.error(f"Exception during temporary session creation: {e}")
            return (None, None) if return_location else None

    def _validate_temp_session_auth(self, auth):
        """Validate authentication tuple for temporary session"""
        if not auth or len(auth) != 2:
            LOGGER.error("Invalid credentials for temporary session")
            return False
        return True

    def _perform_session_creation(self, url, auth, return_location):
        """Perform the HTTP request to create a session"""
        import requests

        username, password = auth
        session_url = self._build_session_service_url(url)
        session_data = {"UserName": username, "Password": password}

        response = requests.post(session_url, json=session_data, verify=False, timeout=30)

        if response.status_code in [200, 201]:
            return self._handle_successful_session_creation(response, return_location)

        LOGGER.error(f"Failed to create temporary session: HTTP {response.status_code}")
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

    def _delete_session_location(self, session_location, session_token=None, timeout=30):
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
            import requests

            headers = {"X-Auth-Token": session_token} if session_token else {}
            response = requests.delete(session_location, headers=headers, verify=False, timeout=timeout)
            if response.status_code in [200, 204, 404]:
                LOGGER.debug("Temporary session successfully cleaned up")
                return True

            LOGGER.warning(f"Session cleanup returned status: {response.status_code}")
            return False
        except Exception as e:
            LOGGER.warning(f"Session cleanup failed: {e}")
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

        :param response_data: Response data as bytes, bytearray, or string
        :returns: Decoded response as string
        :rtype: str
        """
        if response_data is None:
            return ""
        if isinstance(response_data, (bytes, bytearray)):
            return response_data.decode("utf-8")
        return response_data

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
        """Parse raw HTTP response string"""
        parts = response_data.split("\r\n\r\n", 1)
        status = self._extract_status_from_http(parts[0])

        data = None
        if len(parts) > 1:
            data = self._try_parse_json(parts[1])

        return status, data

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

        from redfish.hpilo import risblobstore2
        from ctypes import create_string_buffer, byref, c_char_p

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
            from redfish.hpilo import risblobstore2
            from ctypes import create_string_buffer, byref, c_char_p

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
        from ctypes import c_char_p, c_ubyte, POINTER, create_string_buffer

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
            LOGGER.debug(f"Failed to read cached session from rdmc app: {e}")
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
            LOGGER.debug(f"Failed to read session from cache file: {e}")

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
            LOGGER.debug(f"Could not create session cache directory: {e}")
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
            LOGGER.debug(f"Failed to load session from cache: {e}")
            return None

    def _load_session_entry_from_index(self, cache_dir):
        """Load session entry from cache index file"""
        import os
        import json

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
        import os
        import json

        cache_file = os.path.join(cache_dir, cache_file_name)
        if not os.path.exists(cache_file):
            LOGGER.debug(f"Session cache file not found: {cache_file_name}")
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
            LOGGER.debug(f"Cached session expired (age: {session_age:.0f}s)")
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
        from redfish.hpilo import risblobstore2
        from ctypes import create_string_buffer, byref, c_char_p

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

            LOGGER.debug(f"Loaded valid session from cache (age: {session_age:.0f}s)")
            return decoded_token
        except Exception:
            LOGGER.debug(f"Loaded session from cache (age: {session_age:.0f}s)")
            return session_key

    def _save_session_to_cache_file(self, session_token, url=None):
        """Save encrypted session token to persistent cache file

        :param session_token: Session token to cache
        :type session_token: str
        :param url: URL associated with session (defaults to DEFAULT_ILO_URL)
        :type url: str
        """
        import os
        import json
        import time
        import hashlib
        from redfish.hpilo import risblobstore2
        from ctypes import create_string_buffer, byref, c_char_p

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

            LOGGER.debug(f"Saved session to cache file: {cache_file_name}")

        except Exception as e:
            LOGGER.debug(f"Failed to save session to cache: {e}")

    def _execute_chif_rawget(self, path, session_token=None, username=None, password=None):
        """Execute a GET request via CHIF/BlobStore2

        :param path: Redfish path
        :param session_token: Optional session token (not used for CHIF)
        :param username: Optional username for high security mode
        :param password: Optional password for high security mode
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
            response_data = self._execute_chif_request(bs2, path)
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
            LOGGER.error(f"CHIF rawget execution failed: {e}")
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
            "Calling initialize chif credentials with: username"
            f"={username}, password={self._mask_simple_token(password)}"
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
            LOGGER.error(f"Failed to create BlobStore2 instance: {e}")
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

        try:
            if username and password:
                LOGGER.debug(
                    "Calling high security credentials with username="
                    f"{username}, password={self._mask_simple_token(password)}"
                )
                return self._init_high_security_credentials(username, password)
            else:
                LOGGER.debug("Calling production mode credentials")
                return self._init_production_mode_credentials()
        except Exception as init_ex:
            LOGGER.error(f"BlobStore2.initializecreds raised exception: {init_ex}")
            import traceback

            LOGGER.debug(f"initializecreds exception: {traceback.format_exc()}")
            return False

    def _init_high_security_credentials(self, username, password):
        """Initialize credentials for high security mode"""
        from redfish.hpilo.risblobstore2 import BlobStore2

        LOGGER.debug(
            f"Calling BlobStore2.initializecreds(username={username} password={self._mask_simple_token(password)}"
        )
        result = BlobStore2.initializecreds(username, password)

        if result is False:
            LOGGER.error("BlobStore2.initializecreds returned False - credentials invalid")
            return False

        LOGGER.info("CHIF credentials initialized and verified successfully (high security mode)")
        return True

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

    def _execute_chif_request(self, bs2, path):
        """Execute CHIF request and return response data"""
        # Build HTTP GET request
        http_request = f"GET {path} HTTP/1.1\r\nHost: localhost\r\nContent-Length: 0\r\n\r\n"
        req_data = http_request.encode("utf-8")

        # Execute via CHIF
        LOGGER.debug("Calling rest_immediate with req_data and rsp_namespace='volatile'")
        response_data = bs2.rest_immediate(req_data=req_data, rsp_namespace="volatile")

        if not response_data:
            LOGGER.error("CHIF rest_immediate returned empty response")
            LOGGER.error(
                "This may indicate: 1) High security mode requires credentials, "
                "2) CHIF communication failure, 3) iLO not responding"
            )
            LOGGER.error("Try providing credentials: rawget <path> -u <username> -p <password>")
            return None

        return response_data

    def _process_chif_response(self, response_data, path):
        """Process CHIF response and return appropriate result"""
        # Decode response
        response_str = self._decode_response_data(response_data)

        # Parse HTTP response
        status, data = self._parse_http_response(response_str)

        if status == 200:
            LOGGER.debug(f"CHIF GET successful for path: {path}")
            return data
        else:
            LOGGER.warning(f"CHIF GET returned status {status} for path: {path}")
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
            LOGGER.error(f"CHIF login failed: {e}")
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
        LOGGER.debug(f"CHIF login: correctcreds=False, security_state={security_state}")

        # Check if credentials are optional (factory or production mode)
        if security_state in (1, 3):
            return self._handle_optional_credentials_mode(security_state)

        # High security mode requires credentials
        return self._handle_required_credentials_mode(security_state, username, password)

    def _handle_optional_credentials_mode(self, security_state):
        """Handle factory or production mode where credentials are optional"""
        mode_name = "factory" if security_state == 1 else "production"
        LOGGER.debug(f"CHIF login in {mode_name} mode (security state {security_state}) - no credentials needed")
        return True

    def _handle_required_credentials_mode(self, security_state, username, password):
        """Handle high security mode where credentials are required"""
        # Check if credentials were provided
        if not username or not password or username == "nousername" or password == "nopassword":
            LOGGER.error(f"CHIF login failed: credentials required in security state {security_state}")
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
                LOGGER.error(f"Credential verification failed with error code: {credreturn}")
                raise InvalidCredentialsError(credreturn)

            LOGGER.debug("Credentials verified successfully for high security mode")
            return True
        except Exception as e:
            LOGGER.error(f"Credential verification failed: {e}")
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
            LOGGER.error(f"Failed to create high security CHIF session: {e}")
            import traceback

            LOGGER.debug(f"Traceback: {traceback.format_exc()}")
            raise

    def _initialize_chif_channel(self, dll):
        """Initialize CHIF and create a channel"""
        from redfish.hpilo.risblobstore2 import BlobStore2
        from redfish.hpilo.rishpilo import BlobReturnCodes, HpIloInitialError, HpIloNoChifDriverError
        from ctypes import c_void_p, c_uint32, byref

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

        LOGGER.debug(f"CHIF channel created with handle: {fhandle}")
        return fhandle

    def _setup_chif_credentials(self, dll, fhandle, username, password):
        """Initialize and verify CHIF credentials"""
        from redfish.hpilo.risblobstore2 import BlobStore2
        from redfish.hpilo.rishpilo import BlobReturnCodes, HpIloInitialError, HpIloChifAccessDeniedError
        from ctypes import c_char_p, c_ubyte, POINTER, create_string_buffer

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
        """Ping iLO and verify credentials on the channel"""
        # Ping iLO to verify channel
        LOGGER.debug("Pinging iLO")
        status = dll.ChifPing(fhandle)
        if status != BlobReturnCodes.SUCCESS:
            dll.ChifClose(fhandle)
            BlobStore2.unloadchifhandle(dll)
            raise HpIloInitialError(f"Error {status} occurred while trying to ping iLO.")

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
        try:
            # For app account login, use the proper rdmc.app.vnic_login method
            if not no_app_account:
                return self._perform_app_account_vnic_login()
            else:
                return self._perform_vnic_login(user, password, no_app_account)
        except Exception as e:
            LOGGER.error(f"VNIC login failed: {e}")
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
                            LOGGER.debug(f"VNIC app account login successful, location: {session_location}")
                            return session_token, session_location

                except Exception as login_err:
                    LOGGER.debug(f"rdmc.app.vnic_login failed: {login_err}")
                    # Fall through to try direct HTTP method

            # Fallback: Direct HTTP login if vnic_login not available or failed
            LOGGER.debug("Trying direct HTTP session creation for app account")
            return self._perform_direct_app_account_login(app_obj)

        except Exception as e:
            LOGGER.error(f"App account VNIC login failed: {e}")
            import traceback

            LOGGER.debug(traceback.format_exc())
            return None, None

    def _perform_direct_app_account_login(self, app_obj):
        """Perform direct HTTP login for app account as fallback

        This is used when rdmc.app.vnic_login is not available or fails.
        It attempts to create a session using the app account's credentials
        via direct HTTP POST to SessionService.

        :returns: Tuple of (session_token, session_location) or (None, None)
        :rtype: tuple
        """
        import requests

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
                        LOGGER.debug(f"get_session_key failed: {key_err}")

            if not (app_username and app_password):
                LOGGER.error("Cannot determine app account credentials for direct login")
                return None, None

            # Perform direct HTTP login
            session_url = self._build_session_service_url(self.DEFAULT_ILO_URL)
            session_data = {"UserName": app_username, "Password": app_password}

            LOGGER.debug("Performing direct HTTP login with app account credentials")
            response = requests.post(session_url, json=session_data, verify=False, timeout=30)

            if response.status_code in [200, 201]:
                session_token, session_location = self._get_session_headers(response)
                if session_token:
                    LOGGER.debug(f"Direct HTTP app account login successful, location: {session_location}")
                    return session_token, session_location

            LOGGER.error(f"Direct app account HTTP login failed with status {response.status_code}")
            return None, None

        except Exception as e:
            LOGGER.error(f"Direct app account login failed: {e}")
            return None, None

    def _perform_vnic_login(self, user, password, no_app_account):
        """Perform the actual VNIC login request

        :returns: Tuple of (session_token, session_location) or (None, None)
        :rtype: tuple
        """
        import requests

        url = self.DEFAULT_ILO_URL
        session_url = self._build_session_service_url(url)

        session_data = self._prepare_vnic_session_data(user, password, no_app_account)
        if session_data is None:
            return None, None

        response = requests.post(session_url, json=session_data, verify=False, timeout=30)
        return self._handle_vnic_login_response(response)

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
                LOGGER.debug(f"VNIC login successful, session_location: {session_location}")
                return session_token, session_location

        LOGGER.error(f"VNIC login failed with status {response.status_code}")
        return None, None
