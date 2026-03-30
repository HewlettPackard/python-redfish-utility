###
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
###

# -*- coding: utf-8 -*-
"""RawGet Command for rdmc

Core Functionality of RawGetCommand:
-----------------------------------
This command provides direct HTTP GET access to iLO Redfish endpoints with optimized
performance and comprehensive authentication handling across different iLO generations.

Authentication Flow:
1. Check if ilo_generation.json cache exists, create if not
2. Check for cached session - if available, use it
3. Otherwise, create temp session based on iLO version and mode:

   For iLO5/6 (Inband):
   - Check security mode (production=3 vs high security=4,5,6)
   - If production mode AND VNIC enabled AND credentials provided: VNIC login
   - Otherwise: CHIF login (with or without credentials based on security mode)
   - For high security/FIPS/CNSA: Use legacy framework

   For iLO7 (Inband):
   - Check if app account exists
   - If app account exists: Do ilorest login, get output, logout
   - If no app account: Require credentials, login with --no_app_account, get output, logout

   For Out-of-band (any iLO version):
   - Requires URL and credentials
   - Create HTTP session, get output, logout

Key Features:
1. Multi-Protocol Support: HTTP/HTTPS (network) and CHIF/BlobStore2 (in-band)
2. Smart Authentication with session caching and temp session management
3. Performance Optimizations with iLO generation caching
4. Robust Error Handling with clear user messages
"""

import json
import logging
import sys

import requests
from urllib.parse import urljoin

# Get logger instance
LOGGER = logging.getLogger(__name__)

try:
    from rdmc_helper import (
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        ReturnCodes,
        LOGGER, Encryption,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        ReturnCodes,
        LOGGER, Encryption,
    )

try:
    from .RawCommandBase import RawCommandBase
except ImportError:
    from RawCommandBase import RawCommandBase


class RawGetCommand(RawCommandBase):
    """Raw form of the get command with optimized session and request handling"""

    def __init__(self):
        super().__init__()
        self.ident = {
            "name": "rawget",
            "usage": None,
            "description": "Run to to retrieve data from "
            'the passed in path.\n\tExample: rawget "/redfish/v1/'
            'systems/(system ID)"',
            "summary": "Raw form of the GET command.",
            "aliases": [],
            "auxcommands": ["DetectiLOCommand", "AppAccountCommand"],
        }
        self.cmdbase = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """Main raw get worker function with optimized flow"""
        if help_disp:
            self.parser.print_help()
            return ReturnCodes.SUCCESS

        options = self._parse_arguments(line)
        headers, session_token_from_headers = self._parse_headers(options)
        path = self._process_path(options)

        # Handle no-auth requests (public endpoints)
        if getattr(options, "no_auth", False):
            return self._handle_no_auth_request(options, headers, path)

        # Execute the main authentication flow
        return self._execute_main_flow(options, headers, session_token_from_headers, path)

    def _execute_main_flow(self, options, headers, session_token_from_headers, path):
        """Execute the main authentication and request flow

        Flow:
        1. Check/create ilo_generation.json cache
        2. Check for cached session -> use if available
        3. Otherwise create temp session based on iLO version and mode
        4. Execute request and handle response
        5. Cleanup temp session if created
        """
        # Step 1: Get iLO version and security state in ONE efficient call
        # This avoids multiple CHIF library initializations
        LOGGER.debug("Step 1: Checking ilo_generation.json cache")
        ilo_version, security_state = self._get_ilo_info_cached()

        # Determine connection mode
        is_outofband = bool(getattr(options, "url", None))
        # is_inband = not is_outofband
        has_credentials = bool(getattr(options, "user", None) and getattr(options, "password", None))

        LOGGER.debug(
            f"Connection mode: {'Out-of-band' if is_outofband else 'In-band'}, "
            f"iLO version: {ilo_version}, Has credentials: {has_credentials}"
        )

        # Step 2: Check for cached session
        LOGGER.debug("Step 2: Checking for cached session")
        cached_session = self._get_cached_session_if_valid(options)
        if cached_session:
            LOGGER.debug("Using cached session")
            return self._execute_with_cached_session(options, headers, path, cached_session)

        # Step 3: Create temp session based on scenario
        LOGGER.debug("Step 3: Creating temp session")

        # Out-of-band handling (same for all iLO versions)
        if is_outofband:
            return self._handle_outofband_request(options, headers, path)

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
            LOGGER.warning(f"Unknown iLO version: {ilo_version}, using legacy framework")
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

        Session sources (in priority order):
        1. In-memory active session from rdmc.app.redfishinst (from prior login command)
           - This is ALWAYS checked, even with --nocache
           - Represents an active, verified session
        2. File-based persistent cache (~/.iLORest/cache/)
           - Only checked if --nocache is NOT specified
           - May be stale or expired

        The --nocache flag only skips the file-based cache, not the in-memory session.
        """
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
            LOGGER.debug(f"Could not check in-memory session: {e}")
            return None

    def _execute_with_cached_session(self, options, headers, path, cached_session):
        """Execute request using cached session"""
        is_inband = not getattr(options, "url", None)
        ilo_version = self._detect_ilo_version()

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
            LOGGER.debug(f"Cached out-of-band session to {session_url} - using HTTP")
        elif session_url and session_url.startswith("https://"):
            # Session URL indicates an HTTPS/OOB session from a prior login,
            # even though --url was not provided on this rawget command - use HTTP
            use_chif = False
            LOGGER.debug(f"Cached session URL is HTTPS ({session_url}) - using HTTP")
        else:
            # In-band without cached session URL - determine by iLO version
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
        username , password = self._get_cred(options)
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

    def _get_url_from_session(self):
        """Get URL from active session instance

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
            LOGGER.debug(f"Could not get URL from session: {e}")

        return None

    def _handle_outofband_request(self, options, headers, path):
        """Handle out-of-band request (same for all iLO versions)

        Requires URL and credentials for temp session creation
        """
        url = getattr(options, "url", None)
        username , password = self._get_cred(options)

        if not url:
            sys.stderr.write("Error: Out-of-band mode requires --url parameter.\n")
            sys.stderr.write("  Example: rawget /redfish/v1/systems/1 --url <ilo_ip> -u <user> -p <pass>\n")
            return ReturnCodes.INVALID_COMMAND_LINE_ERROR

        if not username or not password:
            sys.stderr.write("Error: Out-of-band mode requires credentials.\n")
            sys.stderr.write("  Example: rawget /redfish/v1/systems/1 --url <ilo_ip> -u <user> -p <pass>\n")
            return ReturnCodes.INVALID_COMMAND_LINE_ERROR

        # Create temp HTTP session
        LOGGER.debug(f"Creating out-of-band temp session to {url}")

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
        """Handle iLO7 in-band request

        Flow:
        1. Check if app account exists
        2. If yes: login with app account, get output, logout
        3. If no: require credentials, login with --no_app_account, get output, logout
        """
        LOGGER.debug("Handling iLO7 in-band request")

        username , password = self._get_cred(options)

        # Check if app account exists
        has_app_account = self._check_ilo7_app_account()

        if has_app_account:
            LOGGER.debug("iLO7: App account exists, using app account authentication")
            return self._execute_ilo7_with_app_account(options, headers, path)
        else:
            LOGGER.debug("iLO7: No app account, requires credentials")
            if not username or not password:
                sys.stderr.write("Error: iLO7 without app account requires credentials.\n")
                sys.stderr.write("  Create app account: ilorest appaccount create\n")
                sys.stderr.write("  Or provide credentials: rawget <path> -u <user> -p <pass>\n")
                return ReturnCodes.INVALID_COMMAND_LINE_ERROR

            return self._execute_ilo7_without_app_account(options, headers, path, username, password)

    def _execute_ilo7_with_app_account(self, options, headers, path):
        """Execute iLO7 request using app account (VNIC)"""
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
            else:
                LOGGER.error("Failed to create VNIC session with app account")
                sys.stderr.write("Error: Failed to create session with app account.\n")
                return ReturnCodes.INVALID_COMMAND_LINE_ERROR
        except Exception as e:
            LOGGER.error(f"VNIC login with app account failed: {e}")
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
                LOGGER.error("Failed to create VNIC session with credentials")
                sys.stderr.write("Error: Failed to create session with provided credentials.\n")
                return ReturnCodes.INVALID_COMMAND_LINE_ERROR
        except Exception as e:
            LOGGER.error(f"VNIC login with credentials failed: {e}")
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
        LOGGER.debug(f"Handling iLO{int(ilo_version)} in-band request")

        username , password = self._get_cred(options)
        has_credentials = bool(username and password)

        # Use passed security_state to avoid redundant CHIF detection
        if security_state is None:
            security_state = self._get_security_state()

        is_high_security = security_state in [4, 5, 6]  # 4=HighSecurity, 5=FIPS, 6=CNSA/SuiteB

        LOGGER.debug(f"Security state: {security_state}, High security: {is_high_security}")

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
        # Check if VNIC is available (iLO6 can have VNIC enabled)
        vnic_available = self._is_vnic_available()

        if vnic_available and has_credentials:
            LOGGER.debug("Production mode with VNIC enabled and credentials - using VNIC")
            return self._execute_with_vnic_credentials(options, headers, path, username, password)
        else:
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
                LOGGER.debug(f"Security state: {sec_state}")
                return sec_state
        except Exception as e:
            LOGGER.debug(f"Could not determine security state: {e}")

        # Default to production mode if we can't determine
        LOGGER.debug("Default Security state: 3")
        return 3

    def _execute_with_vnic_credentials(self, options, headers, path, username, password):
        """Execute request using VNIC with credentials (iLO6 with VNIC enabled)"""
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
            else:
                # Fallback to CHIF
                LOGGER.debug("VNIC login failed, falling back to CHIF")
                return self._execute_with_chif(options, headers, path, username, password)
        except Exception as e:
            LOGGER.debug(f"VNIC login failed: {e}, falling back to CHIF")
            return self._execute_with_chif(options, headers, path, username, password)

    def _execute_with_chif(self, options, headers, path, username, password):
        """Execute request using CHIF (iLO5/6 in-band production mode)"""
        LOGGER.debug(f"Executing CHIF request for path: {path}")

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

        LOGGER.debug(f"CHIF auth_info prepared, use_chif_method={auth_info['use_chif_method']}")
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

        if options.headers:
            extraheaders = options.headers.split(",")
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
                        break
                except Exception:
                    InvalidCommandLineError("Invalid format for --headers option.")

        return headers, session_token_from_headers

    def _process_path(self, options):
        """Process and normalize the request path"""
        path = options.path

        if path.endswith("?=."):
            strip = path[:-3]
            path = strip + "?$expand=."

        if path.startswith('"') and path.endswith('"'):
            path = path[1:-1]

        if options.expand:
            path = path + "?$expand=."

        options.path = path
        return path

    def _handle_no_auth_request(self, options, headers, path):
        """Handle requests with no authentication"""
        options_url = getattr(options, "url", None)
        url = self._normalize_url(options_url) if options_url else self.DEFAULT_ILO_URL
        full_path = urljoin(url, path.lstrip("/"))

        try:
            response = self._execute_request("GET", full_path, headers=headers)
            return self._handle_response(response, options)
        except requests.exceptions.Timeout as excp:
            LOGGER.error(f"Connection timeout to {url}: {excp}")
            sys.stderr.write(f"Error: Connection timeout to {url}. iLO may be resetting or unreachable.\n")
            return ReturnCodes.V1_SERVER_DOWN_OR_UNREACHABLE_ERROR
        except requests.exceptions.ConnectionError as excp:
            LOGGER.error(f"Connection failed to {url}: {excp}")
            sys.stderr.write(f"Error: Connection failed to {url}. iLO may be resetting or unreachable.\n")
            return ReturnCodes.V1_SERVER_DOWN_OR_UNREACHABLE_ERROR
        except Exception as excp:
            LOGGER.error(f"Failed to complete no-auth request: {excp}")
            sys.stderr.write(f"Error: Failed to complete operation - {excp}\n")
            return ReturnCodes.GENERAL_ERROR

    def _execute_with_auth_info(self, options, headers, path, auth_info):
        """Execute request with authentication info"""
        url = self._build_request_url(options, auth_info)
        full_path = self._build_full_path(url, path)

        LOGGER.debug(f"Executing request: url={url}, path={full_path}, use_chif={auth_info['use_chif_method']}")

        try:
            response = self._perform_request(options, auth_info, full_path, headers)
            LOGGER.debug(f"Request completed, response status: {response.status_code if response else 'None'}")
            return self._handle_response(response, options)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            LOGGER.error(f"Request execution failed: {e}")
            import traceback

            LOGGER.debug(traceback.format_exc())
            sys.stderr.write(f"Error: Request failed - {str(e)}\n")
            return ReturnCodes.V1_SERVER_DOWN_OR_UNREACHABLE_ERROR
        except Exception as e:
            LOGGER.error(f"Request execution failed: {e}")
            import traceback

            LOGGER.debug(traceback.format_exc())
            sys.stderr.write(f"Error: Request failed - {str(e)}\n")
            return ReturnCodes.GENERAL_ERROR
        finally:
            self._cleanup_session(auth_info)

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
            LOGGER.debug(f"Could not get base_url from redfishinst: {e}")

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
            return self._perform_chif_request(options, full_path, auth_info)
        else:
            LOGGER.debug("Performing http request")
            return self._perform_http_request(full_path, headers, auth_info)

    def _perform_chif_request(self, options, path, auth_info):
        """Perform CHIF request with fallback handling"""
        username = auth_info["auth"][0] if auth_info["auth"] else None
        password = auth_info["auth"][1] if auth_info["auth"] else None

        LOGGER.debug(f"Performing CHIF request to path: {path}")
        LOGGER.debug(f"username: {username}, password:{self._mask_simple_token(password)}")
        result = self._execute_chif_rawget(path, None, username=username, password=password)
        LOGGER.debug(f"CHIF result type: {type(result)}, is_none: {result is None}")

        if result is None:
            LOGGER.error("CHIF execution returned None")
            return self._create_error_response(500, "CHIF execution failed")

        return self._process_chif_result(result, auth_info, username, password, path)

    def _perform_http_request(self, full_path, headers, auth_info):
        """Perform HTTP request"""
        if auth_info["session_token"]:
            headers["X-Auth-Token"] = auth_info["session_token"]

        return self._execute_request("GET", full_path, headers=headers, auth=auth_info["auth"])

    def _process_chif_result(self, result, auth_info, username, password, path):
        """Process CHIF result and handle fallback if needed"""
        if isinstance(result, tuple):
            status_code, data = result
        else:
            data = result
            status_code = 200 if not (isinstance(data, dict) and "error" in data) else 401

        response = self._create_chif_response(data, status_code)

        # Handle 401 fallback
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
            LOGGER.debug(f"Fallback failed: {e}")
        return None

    def _create_chif_response(self, data, status_code):
        """Create a response object for CHIF results"""

        class ChifResponse:
            def __init__(self, data, status_code):
                self.status_code = status_code
                self.content = json.dumps(data).encode("utf-8") if data else b""
                self.text = json.dumps(data) if data else ""
                self.headers = {"Content-Type": "application/json"}

            def json(self):
                return json.loads(self.content) if self.content else {}

        return ChifResponse(data, status_code)

    def _create_error_response(self, status_code, message):
        """Create an error response"""
        error_data = {"error": {"message": message}}
        return self._create_chif_response(error_data, status_code)

    def _handle_response(self, response, options):
        """Handle the response and format output"""
        if getattr(options, "silent", False):
            if response.status_code >= 200 and response.status_code < 300:
                return ReturnCodes.SUCCESS
            else:
                return ReturnCodes.GENERAL_ERROR

        return_response = getattr(options, "response", False) or getattr(options, "getheaders", False)

        if options.filename:
            return self._write_response_into_file(response, options)

        if options.binfile:
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

    def _write_response_into_file(self, response, options=None):
        """
        Write the response to the specified file.
        """
        try:
            import redfish

            if hasattr(response, "status_code") and response.status_code == 200:
                self.rdmc.ui.printer("[200] The operation completed successfully.\n")
                data = response.json()
            elif hasattr(response, "status") and response.status == 200:
                # status from legacy old framework
                data = response.dict
            else:
                response_code = None
                if hasattr(response, "status_code"):
                    response_code = response.status_code
                elif hasattr(response, "status"):
                    response_code = response.status

                self.rdmc.ui.printer(f"[{response_code}] {self._get_status_message(response_code)}\n")
                return ReturnCodes.GENERAL_ERROR

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
            LOGGER.error(f"Response writing into file failed: {e}")
            sys.stderr.write(f"Error: Failed to write response into file - {str(e)}\n")
            return ReturnCodes.GENERAL_ERROR

    def _write_response_in_binary(self, response, options=None):
        """
        Write the response to the specified file in binary.
        """
        try:
            if hasattr(response, "status_code") and response.status_code == 200:
                self.rdmc.ui.printer("[200] The operation completed successfully.\n")
                data = response.content
            elif hasattr(response, "status") and response.status == 200:
                # status from legacy old framework
                data = json.dumps(response.dict).encode("utf-8")
            else:
                response_code = None
                if hasattr(response, "status_code"):
                    response_code = response.status_code
                elif hasattr(response, "status"):
                    response_code = response.status

                self.rdmc.ui.printer(f"[{response_code}] {self._get_status_message(response_code)}\n")
                return ReturnCodes.GENERAL_ERROR

            with open(options.binfile[0], "wb") as file_hndl:
                file_hndl.write(data)

            self.rdmc.ui.printer(f"Results written out to '{options.binfile[0]}'\n")
            return ReturnCodes.SUCCESS
        except Exception as e:
            LOGGER.error(f"Response writing into binary file failed: {e}")
            sys.stderr.write(f"Error: Failed to write a response into binary - {str(e)}\n")
            return ReturnCodes.GENERAL_ERROR

    def _format_response_output(self, response, options=None):
        """Format response with headers and body

        Output format (same for both success and error responses):
        - stderr: [<status_code>] <status_message or MessageId>
        - stdout (or stderr if --stderr_flag): headers JSON (if --getheaders)
        - stdout (or stderr if --stderr_flag): body JSON (if --response)
        """
        try:
            body = response.json() if response.content else None
            status_msg = self._get_status_message_from_response(response, body)

            out = self._body_stream(options)
            out.write(f"[{response.status_code}] {status_msg}\n")
            show_headers = getattr(options, "getheaders", False) if options else True
            show_body = getattr(options, "response", False) if options else True

            if show_headers:
                sys.stdout.write(f"{json.dumps(dict(response.headers))}\n")
            if show_body and body is not None:
                sys.stdout.write(f"{json.dumps(body)}\n")
            sys.stdout.flush()

            if 200 <= response.status_code < 300:
                return ReturnCodes.SUCCESS
            elif response.status_code == 401:
                return ReturnCodes.RIS_SESSION_EXPIRED
            elif response.status_code > 299:
                return ReturnCodes.RIS_ILO_RESPONSE_ERROR
            else:
                return ReturnCodes.GENERAL_ERROR
        except Exception as e:
            LOGGER.error(f"Response formatting failed: {e}")
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
        if response.status_code >= 400:
            try:
                data = body if body else (response.json() if response.content else None)
                if data and "error" in data:
                    ext_info = data["error"].get("@Message.ExtendedInfo", [])
                    if ext_info and len(ext_info) > 0:
                        message_id = ext_info[0].get("MessageId", "")
                        if message_id:
                            return message_id
            except Exception:
                pass

        # Fall back to generic status messages
        return self._get_status_message(response.status_code)

    def _get_status_message(self, status_code):
        """Get human-readable status message for HTTP status code"""
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

    def _format_json_output(self, response, options=None):
        """Format JSON output"""
        body = response.json() if response.content else None
        status_msg = self._get_status_message_from_response(response, body)

        out = self._body_stream(options)
        out.write(f"[{response.status_code}] {status_msg}\n")
        if 200 <= response.status_code < 300:
            try:
                if body is not None:
                    if options and getattr(options, "service", False):
                        # Output as Python dict format (with single quotes)
                        sys.stdout.write(f"{repr(body)}\n")
                    else:
                        sys.stdout.write(f"{json.dumps(body, indent=2, sort_keys=True)}\n")
                out.flush()
                return ReturnCodes.SUCCESS
            except Exception as e:
                LOGGER.error(f"JSON parsing failed: {e}")
                sys.stderr.write(f"Error: JSON parsing failed - {str(e)}\n")
                return ReturnCodes.INVALID_COMMAND_LINE_ERROR
        else:
            if body is not None:
                out.write(f"{json.dumps(body)}\n")
                out.flush()

        if response.status_code == 401:
            return ReturnCodes.RIS_SESSION_EXPIRED
        elif response.status_code > 299:
            return ReturnCodes.RIS_ILO_RESPONSE_ERROR
        else:
            return ReturnCodes.GENERAL_ERROR

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
                    LOGGER.debug(f"Session cleanup failed: {e}")
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
                    LOGGER.error(f"Login validation failed: {login_ex}")
                    import traceback

                    LOGGER.debug(traceback.format_exc())
                    sys.stderr.write(f"Error: Failed to initialize session - {str(login_ex)}\n")
                    return ReturnCodes.INVALID_COMMAND_LINE_ERROR

            if not hasattr(self.rdmc.app, "get_handler"):
                sys.stderr.write("Error: Legacy framework not available\n")
                return ReturnCodes.INVALID_COMMAND_LINE_ERROR

            is_silent = getattr(options, "silent", False)
            is_service = getattr(options, "service", False)

            username , password = self._get_cred(options)

            results = self.rdmc.app.get_handler(
                path,
                headers=headers,
                silent=is_silent,
                service=is_service,
                username=username,
                password=password,
            )

            if is_silent:
                if results and results.status == 200:
                    return ReturnCodes.SUCCESS
                return ReturnCodes.GENERAL_ERROR

            if not results or results.status != 200:
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
                        LOGGER.debug(f"Logout failed (expected): {logout_ex}")

                    # Force fresh login with provided credentials
                    LOGGER.debug("Performing fresh login with credentials")
                    self.cmdbase.login_validation(self, options, skipbuild=True)

                    # Retry the request with fresh session
                    LOGGER.debug("Retrying request with fresh session")
                    results = self.rdmc.app.get_handler(
                        path,
                        headers=headers,
                        silent=is_silent,
                        service=is_service,
                        username=username,
                        password=password,
                    )

                    # Check if retry succeeded
                    if results and results.status == 200:
                        LOGGER.info("Retry after re-login successful")
                    else:
                        retry_status = results.status if results else 500
                        LOGGER.error(f"Retry after re-login failed with status: {retry_status}")
                        sys.stderr.write(f"[{retry_status}] {self._get_status_message(retry_status)}\n")
                        return ReturnCodes.GENERAL_ERROR
                else:
                    sys.stderr.write(f"[{status}] {self._get_status_message(status)}\n")
                    return ReturnCodes.GENERAL_ERROR

            return_response = getattr(options, "response", False) or getattr(options, "getheaders", False)

            if options.filename:
                return self._write_response_into_file(results, options)

            if options.binfile:
                return self._write_response_in_binary(results, options)

            if return_response:
                if getattr(options, "getheaders", False):
                    resp_headers = {}
                    if hasattr(results, "getheaders") and results.getheaders():
                        resp_headers = dict(results.getheaders())
                    elif hasattr(results, "_headers") and results._headers:
                        resp_headers = dict(results._headers)
                    sys.stdout.write(f"{json.dumps(resp_headers)}\n")
                if getattr(options, "response", False):
                    body = results.dict if hasattr(results, "dict") else {}
                    sys.stdout.write(f"{json.dumps(body)}\n")
                sys.stdout.flush()
            else:
                body = results.dict if hasattr(results, "dict") else results
                if isinstance(body, (dict, list)):
                    if is_service:
                        sys.stdout.write(f"{json.dumps(body)}\n")
                    else:
                        sys.stdout.write(f"{json.dumps(body, indent=2, sort_keys=True)}\n")
                else:
                    sys.stdout.write(f"{body}\n")
                sys.stdout.flush()

            return ReturnCodes.SUCCESS

        except Exception as e:
            LOGGER.error(f"Legacy framework execution failed: {e}")
            import traceback

            LOGGER.debug(traceback.format_exc())
            error_msg = str(e) if str(e) else "Unknown error occurred"
            sys.stderr.write(f"Error: Legacy framework failed - {error_msg}\n")
            return ReturnCodes.INVALID_COMMAND_LINE_ERROR

    def getvalidation(self, options):
        """Raw get validation function

        For service mode: Skip all validation to minimize requests
        For non-service mode: Perform minimal login validation to enable implicit login

        :param options: command line options
        :type options: list.
        """
        if getattr(options, "service", False):
            LOGGER.debug("Service mode: Skipping framework validation")
            return

        LOGGER.debug("Raw command: Performing minimal login validation")
        self.cmdbase.login_validation(self, options, skipbuild=True)

    def definearguments(self, customparser):
        """Wrapper function for new command main function

        :param customparser: command line input
        :type customparser: parser.
        """
        if not customparser:
            return

        self.cmdbase.add_login_arguments_group(customparser)

        customparser.add_argument("path", help="Uri on iLO")
        customparser.add_argument(
            "--response",
            dest="response",
            action="store_true",
            help="Use this flag to return the iLO response body.",
            default=False,
        )
        customparser.add_argument(
            "--getheaders",
            dest="getheaders",
            action="store_true",
            help="Use this flag to return the iLO response headers.",
            default=False,
        )
        customparser.add_argument(
            "--headers",
            dest="headers",
            default=None,
            help="Use this flag to add extra headers to the request. example: --headers=HEADER:VALUE,HEADER:VALUE",
        )
        customparser.add_argument(
            "--silent",
            dest="silent",
            action="store_true",
            help="Use this flag to silence responses",
            default=False,
        )
        customparser.add_argument(
            "-f",
            "--filename",
            dest="filename",
            action="append",
            default=None,
            help="Write results to the specified file.",
        )
        customparser.add_argument(
            "-b",
            "--writebin",
            dest="binfile",
            action="append",
            default=None,
            help="Write the results to the specified file in binary.",
        )
        customparser.add_argument(
            "--service",
            dest="service",
            action="store_true",
            default=False,
            help="Use this flag to enable service mode and increase the function speed",
        )
        customparser.add_argument(
            "--expand",
            dest="expand",
            action="store_true",
            default=False,
            help="Use this flag to expand the path specified using the expand notation '?$expand=.'",
        )
        customparser.add_argument(
            "--no_auth",
            dest="no_auth",
            action="store_true",
            default=False,
            help="Use this flag to skip authentication requirements for the request",
        )
        customparser.add_argument(
            "--stderr_out",
            "--stderr_flag",
            dest="stderr_flag",
            action="store_true",
            default=False,
            help="Use this flag to write the response body to stderr instead of stdout. "
            "Both the HTTP status line and the JSON body will appear on stderr, "
            "matching the legacy v4.0 behaviour and making it easy for tooling "
            "that captures only stderr to receive the complete output.",
        )
