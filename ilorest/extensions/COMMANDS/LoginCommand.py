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
"""Login Command for RDMC"""

import getpass
import json
import os
import platform
import socket
import warnings
from argparse import SUPPRESS

import redfish.ris
import urllib3
import urllib3.util
from redfish.hpilo.vnichpilo import AppAccount
from redfish.rest.connections import ChifDriverMissingOrNotFound, VnicNotEnabledError

try:
    from tpm_lock import TpmFileLock, retry_with_backoff
except ImportError:
    from ilorest.tpm_lock import TpmFileLock, retry_with_backoff

try:
    from ilo_generation_cache import read_cached_generation, write_cached_generation
except ImportError:
    from ilorest.ilo_generation_cache import (
        read_cached_generation,
        write_cached_generation,
    )

try:
    from rdmc_helper import (
        LOGGER,
        AppAccountExistsError,
        Encryption,
        GenBeforeLoginError,
        InactiveAppAccountTokenError,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        NoAppAccountError,
        PathUnavailableError,
        ReturnCodes,
        UsernamePasswordRequiredError,
        VnicExistsError,
        VnicLoginError,
    )
except ModuleNotFoundError:
    from ilorest.rdmc_helper import (
        ReturnCodes,
        LOGGER,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        PathUnavailableError,
        Encryption,
        UsernamePasswordRequiredError,
        VnicExistsError,
        VnicLoginError,
        InactiveAppAccountTokenError,
        NoAppAccountError,
        GenBeforeLoginError,
        AppAccountExistsError,
    )

from redfish.rest.v1 import ServerDownOrUnreachableError

try:
    from security.pqc import _PQC_STRICT_MIN_GENERATION, build_ssl_context, resolve_mode_from_env
except ImportError:
    from ilorest.security.pqc import _PQC_STRICT_MIN_GENERATION, build_ssl_context, resolve_mode_from_env


class LoginCommand:
    """Constructor"""

    def __init__(self):
        self.ident = {
            "name": "login",
            "usage": None,
            "description": "To login remotely run using iLO url and iLO credentials"
            "\n\texample: login <iLO url/hostname> -u <iLO username> "
            "-p <iLO password>\n\n\tTo login on a local server run without "
            "arguments\n\texample: login"
            "\n\n\tTo login through VNIC run using --force_vnic and iLO credentials "
            "\n\texample: login --force_vnic -u <iLO username> -p <iLO password>"
            "\n\nLogin using OTP can be done in 2 ways."
            "\n\n\t To login implicitly, use the tag --wait_for_otp."
            "\n\t\texample: login -u <iLO username> -p <iLO password> --wait_for_otp"
            "\n\n\n\t To login explicitly, use the tag -o/--otp and enter OTP after."
            "\n\t\texample: login -u <iLO username> -p <iLO password> -o <iLO OTP>"
            "\n\n\tNOTE: A [URL] can be specified with "
            "an IPv4, IPv6, or hostname address.",
            "summary": "Connects to a server, establishes a secure session," " and discovers data from iLO.",
            "aliases": [],
            "auxcommands": ["LogoutCommand"],
            "cert_data": {},
        }
        self.cmdbase = None
        self.rdmc = None
        self.url = None
        self.username = None
        self.password = None
        self.sessionid = None
        self.biospassword = None
        self.auxcommands = dict()
        self.cert_data = dict()
        self.login_otp = None
        self.ilo_gen = 6

    def run(self, line, help_disp=False):
        """wrapper function for main login function

        :param line: command line input
        :type line: string.
        :param help_disp: flag to determine to display or not
        :type help_disp: boolean
        """
        if help_disp:
            self.parser.print_help()
            return ReturnCodes.SUCCESS
        try:
            self.loginfunction(line)

            if ("-h" in line) or ("--help" in line):
                return ReturnCodes.SUCCESS

            if not self.rdmc.app.monolith._visited_urls:
                self.auxcommands["logout"].run("")
                raise PathUnavailableError("The path specified by the --path flag is unavailable.")
        except Exception:
            raise

        # Return code
        return ReturnCodes.SUCCESS

    def perform_login(self, options, skipbuild, user_ca_cert_data, args, app_obj):

        ilo_ver = self.ilo_gen
        # On iLO7+, in-band CHIF (--use_chif) is valid ONLY in factory mode, so the security
        # state is known to be factory (get_security_state() == 1) without probing. Passing it
        # lets the CHIF layer skip the ChifVerifyCredentials() and get_security_state() round
        # trips, restoring ~6.5s factory login timing. Left as None otherwise (iLO5/6 in-band
        # can be production/high-security), so the library still probes and rejects wrong
        # production passwords.
        #
        # Freshness/safety of this hint (why it is never stale-trusted):
        #   * `ilo_ver` is probed fresh for THIS login by get_ilover_beforelogin() (a live
        #     /redfish/v1 read or in-band probe), not read from a persisted cache.
        #   * A usable CHIF channel to an iLO7+ already implies factory mode (production/FIPS/
        #     CNSA are VNIC-only on iLO7+), so hint == 1 cannot point to factory on a server we
        #     are actually reaching in production over CHIF.
        #   * The library never trusts this hint as a security boundary: it acts on it only
        #     inside a live dll.ChifIsSecurityRequired() == "not required" gate, so a secure iLO
        #     always takes the full-verification path regardless of the hint. See
        #     BlobStore2.initializecreds() for the detailed guarantee.
        security_state = 1 if (options.usechif and ilo_ver and ilo_ver >= 7) else None
        if ilo_ver < 7 or (ilo_ver >= 7 and (options.usechif or options.noapptoken or args)):
            login_response = self.rdmc.app.login(
                username=self.username,
                password=self.password,
                sessionid=self.sessionid,
                base_url=self.url,
                path=options.path,
                skipbuild=skipbuild,
                includelogs=options.includelogs,
                biospassword=self.biospassword,
                is_redfish=self.rdmc.opts.is_redfish,
                proxy=self.rdmc.opts.proxy,
                user_ca_cert_data=user_ca_cert_data,
                json_out=self.rdmc.json,
                login_otp=self.login_otp,
                log_dir=self.rdmc.log_dir,
                ilo_generation=ilo_ver,
                security_state=security_state,
            )
        else:
            if options.hostappname or options.hostappid or options.salt:
                if not (options.hostappname and options.hostappid and options.salt):
                    raise InvalidCommandLineError("Please enter all the necessary host application information.\n")

            # Code to check if vnic is enabled.
            vnic_enabled = self.rdmc.app.vexists(app_obj)
            if not vnic_enabled:
                raise VnicExistsError(
                    "Unable to access iLO using virtual NIC. "
                    "Please ensure virtual NIC is enabled in iLO. "
                    "Ensure that virtual NIC in the host OS is "
                    "configured properly. Refer to documentation for more information.\n"
                )

            # Serialize TPM operations across concurrent ilorest processes.
            # The native TPMUtility uses a named POSIX semaphore that is globally
            # unlinked on disconnect, causing race conditions when multiple processes
            # perform login/logout concurrently. The file lock ensures only one process
            # touches the TPM semaphore at a time.
            with TpmFileLock() as _tpm_lock:
                login_response = self._perform_app_account_login(
                    app_obj, options, skipbuild, user_ca_cert_data, ilo_ver
                )

        if options.session_id and login_response and hasattr(login_response, "_auth_key"):
            self.rdmc.ui.printer(f"\nSessionID:{login_response._auth_key}\n\n")

        if options.session_loc and login_response and hasattr(login_response, "_session_location"):
            self.rdmc.ui.printer(f"Location:{login_response._session_location}\n\n")

    def _perform_app_account_login(self, app_obj, options, skipbuild, user_ca_cert_data, ilo_ver):
        """Perform the app-account token check and VNIC login with retry.

        This method is called while holding the TpmFileLock, ensuring only one
        ilorest process at a time interacts with the TPM semaphore. Additionally,
        it retries on transient failures (e.g., if a prior concurrent process
        left the semaphore in a bad state that recovers after a short delay).

        Args:
            app_obj: AppAccount object with host app credentials.
            options: Parsed command line options.
            skipbuild: Whether to skip monolith build.
            user_ca_cert_data: CA certificate data dict.
            ilo_ver: iLO generation (float/int) forwarded to vnic_login as
                ``ilo_generation``. Captured by the ``_do_login`` closure below.

        Returns:
            The login response object from vnic_login.

        Raises:
            AppAccountExistsError: If token_exists check fails.
            NoAppAccountError: If no app account is available.
            InactiveAppAccountTokenError: If the token is inactive/expired.
            VnicLoginError: If login fails after all retry attempts.
        """

        def _do_login():
            """Inner function encapsulating the token check + login for retry."""
            # Check if appaccount exists
            try:
                apptoken_exists = self.rdmc.app.token_exists(app_obj)
            except Exception as excp:
                LOGGER.error("token_exists() failed: %s: %s", type(excp).__name__, excp)
                raise AppAccountExistsError(
                    "Error occurred while checking if app account exists. "
                    f"Underlying error: {type(excp).__name__}: {excp}\n"
                )

            if not apptoken_exists:
                raise NoAppAccountError(
                    "The app account is not available for this host application. "
                    "Please retry using the --no_app_account option or generate "
                    "an application account using the appaccount create command.\n"
                )

            try:
                return self.rdmc.app.vnic_login(
                    app_obj=app_obj,
                    path=options.path,
                    skipbuild=skipbuild,
                    includelogs=options.includelogs,
                    json_out=self.rdmc.json,
                    base_url=self.url,
                    username=self.username,
                    password=self.password,
                    log_dir=self.rdmc.log_dir,
                    login_otp=self.login_otp,
                    is_redfish=self.rdmc.opts.is_redfish,
                    proxy=self.rdmc.opts.proxy,
                    user_ca_cert_data=user_ca_cert_data,
                    biospassword=self.biospassword,
                    sessionid=self.sessionid,
                    ilo_generation=ilo_ver,
                )
            except redfish.hpilo.vnichpilo.InactiveAppAccountTokenError:
                LOGGER.error("Login failed due to an inactive or expired App Account token.")
                raise InactiveAppAccountTokenError()
            except (AppAccountExistsError, NoAppAccountError, InactiveAppAccountTokenError):
                # Non-retryable errors — propagate immediately
                raise
            except (NameError, AttributeError, TypeError, SyntaxError, ImportError):
                # Programmer errors — do not retry, do not relabel as TPM issues.
                raise
            except Exception as excp:
                # Log the real exception so debug logs show the actual cause
                LOGGER.error(
                    "vnic_login() failed: %s: %s. This may be a transient TPM semaphore issue.",
                    type(excp).__name__,
                    excp,
                )
                error_msg = (
                    "Error occurred while performing login using app account.\n"
                    "                Check if application account exists using 'appaccount details' command.\n"
                    "                Otherwise, try with --no_app_account option.\n"
                    f"                Underlying error: {type(excp).__name__}: {excp}\n"
                )
                raise VnicLoginError(error_msg)

        # Retry transient failures — the semaphore race may self-heal after a short delay
        # if another process finishes its TPM teardown. Non-retryable exceptions
        # (NoAppAccountError, InactiveAppAccountTokenError) are excluded from retry.
        try:
            return retry_with_backoff(
                func=_do_login,
                max_attempts=3,
                base_delay=1.0,
                backoff_factor=2.0,
                retryable_exceptions=(VnicLoginError, AppAccountExistsError),
            )
        except (NoAppAccountError, InactiveAppAccountTokenError):
            raise
        except (VnicLoginError, AppAccountExistsError):
            raise

    def loginfunction(self, line, skipbuild=None, json_out=False):
        """Main worker function for login class

        :param line: entered command line
        :type line: list.
        :param skipbuild: flag to determine if monolith should be build
        :type skipbuild: boolean.
        :param json_out: flag to determine if json output neededd
        :type skipbuild: boolean.
        """
        try:
            options, args = self.rdmc.rdmc_parse_arglist(self, line)
        except (InvalidCommandLineErrorOPTS, SystemExit):
            if ("-h" in line) or ("--help" in line):
                return ReturnCodes.SUCCESS
            else:
                raise InvalidCommandLineError("Invalid command line arguments")

        if platform.system() == "Darwin":
            # Mac OS
            app_obj = None
            self.ilo_gen = 6
        else:
            app_obj = AppAccount(
                appname=options.hostappname,
                appid=options.hostappid,
                salt=options.salt,
                username=options.user,
                password=options.password,
                log_dir=self.rdmc.log_dir,
            )

            self.ilo_gen = self.get_ilover_beforelogin(args=args, app_obj=app_obj, options=options)

        self.loginvalidation(options=options, args=args, app_obj=app_obj)

        # if proxy server provided in command line as --useproxy, it will be used,
        # otherwise it will the environment variable setting.
        # else proxy will be set as None.
        if self.rdmc.opts.proxy:
            _ = self.rdmc.opts.proxy
        elif "https_proxy" in os.environ and os.environ["https_proxy"]:
            _ = os.environ["https_proxy"]
        elif "http_proxy" in os.environ and os.environ["http_proxy"]:
            _ = os.environ["http_proxy"]
        else:
            _ = self.rdmc.config.proxy

        no_bundle = False

        if getattr(options, "ca_cert_bundle", False):
            user_ca_cert_data = {"ca_certs": options.ca_cert_bundle}
        else:
            user_ca_cert_data = {}
        if getattr(options, "user_certificate", False):
            no_bundle = True
            user_ca_cert_data.update({"cert_file": options.user_certificate})
        if getattr(options, "user_root_ca_key", False):
            no_bundle = True
            user_ca_cert_data.update({"key_file": options.user_root_ca_key})
        if getattr(options, "user_root_ca_password", False):
            no_bundle = True
            user_ca_cert_data.update({"key_password": options.user_root_ca_password})

        if not no_bundle:
            if hasattr(user_ca_cert_data, "ca_certs"):
                user_ca_cert_data.pop("ca_certs")

        try:
            if getattr(options, "force_vnic", False):
                self.rdmc.ui.printer("\nAttempt to login with Vnic...\n")
            try:
                if args:
                    sock = socket.create_connection((args[0], 443))
                    if sock:
                        sock.close()
            except (socket.error, OSError) as exc:
                LOGGER.debug("Socket connection check failed: %s", exc)

            self.sessionid = options.sessionid
            self.login_otp = options.login_otp

            if self.url and "blobstore" in self.url and (options.waitforOTP or options.login_otp):
                options.waitforOTP = None
                options.login_otp = None
                self.rdmc.ui.printer(
                    "Warning: For local inband mode, TFA is not supported, options --wait_for_otp "
                    "and --otp will be ignored\n"
                )

            if options.waitforOTP:
                try:
                    self.perform_login(options, skipbuild, user_ca_cert_data, args, app_obj)
                except redfish.rest.connections.OneTimePasscodeError:
                    self.rdmc.ui.printer("One Time Passcode Sent to registered email.\n")
                    ans = input("Enter OTP: ")
                    self.login_otp = ans
                    self.perform_login(options, skipbuild, user_ca_cert_data, args, app_obj)
            else:
                self.perform_login(options, skipbuild, user_ca_cert_data, args, app_obj)
        except ServerDownOrUnreachableError as excp:
            self.rdmc.ui.printer("The following error occurred during login: '%s'\n" % str(excp.__class__.__name__))

        self.username = None
        self.password = None

        # Warning for cache enabled, since we save session in plain text
        if not self.rdmc.encoding:
            self.rdmc.ui.warn("Cache is activated. Session keys are stored in plaintext.")

        if self.rdmc.opts.debug:
            self.rdmc.ui.warn("Logger is activated. Logging is stored in plaintext.")

        if options.selector:
            try:
                self.rdmc.app.select(selector=options.selector)

                if self.rdmc.opts.verbose:
                    self.rdmc.ui.printer(("Selected option: '%s'\n" % options.selector))
            except Exception as excp:
                raise redfish.ris.InstanceNotFoundError(excp)

    def loginvalidation(self, options, args, app_obj):
        """Login helper function for login validations

        :param options: command line options
        :type options: list.
        :param args: command line arguments
        :type args: list.
        """
        # Fill user name/password from config file
        if not options.user:
            options.user = self.rdmc.config.username
        if not options.password:
            options.password = self.rdmc.config.password
        if not hasattr(options, "user_certificate"):
            options.user_certificate = self.rdmc.config.user_cert
        if not hasattr(options, "user_root_ca_key"):
            options.user_root_ca_key = self.rdmc.config.user_root_ca_key
        if not hasattr(options, "user_root_ca_password"):
            options.user_root_ca_password = self.rdmc.config.user_root_ca_password

        ilo_ver = self.ilo_gen

        if (
            options.user
            and not options.password
            and (
                not hasattr(options, "user_certificate")
                or not hasattr(options, "user_root_ca_key")
                or hasattr(options, "user_root_ca_password")
            )
        ):
            # Option for interactive entry of password
            tempinput = getpass.getpass().rstrip()
            if tempinput:
                options.password = tempinput
            else:
                raise InvalidCommandLineError("Empty or invalid password was entered.")

        if options.user:
            self.username = options.user

        if options.password:
            self.password = options.password

        if options.encode:
            self.username = Encryption.decode_credentials(self.username).decode("utf-8")
            self.password = Encryption.decode_credentials(self.password).decode("utf-8")

        if options.biospassword:
            self.biospassword = options.biospassword

        if ilo_ver >= 7:
            if not args:
                if self.username and self.password and not options.noapptoken and not options.usechif:
                    options.noapptoken = True
                if options.noapptoken:
                    if (
                        not self.username or not self.password
                    ):  # Add another check to see if username and password is present in environment variables
                        raise UsernamePasswordRequiredError(
                            "Please enter username and password in order to login without app account.\n"
                        )
                    options.force_vnic = True

        # Assignment of url in case no url is entered
        if getattr(options, "force_vnic", False):
            if not (getattr(options, "ca_cert_bundle", False) or getattr(options, "user_certificate", False)):
                if not (self.username and self.password) and not options.sessionid:
                    raise UsernamePasswordRequiredError("Please provide credentials to login with virtual NIC.\n")
            self.url = "https://16.1.15.1"
        else:
            if ilo_ver >= 7 and not options.usechif:
                # TO DO
                # self.url = self.rdmc.app.GetIPAddress()
                self.url = "https://16.1.15.1"
            else:
                self.url = "blobstore://."

        if args:
            # Any argument should be treated as an URL
            self.url = args[0]

            # Verify that URL is properly formatted for https://
            if "https://" not in self.url:
                self.url = "https://" + self.url

            if not (
                hasattr(options, "user_certificate")
                or hasattr(options, "user_root_ca_key")
                or hasattr(options, "user_root_ca_password")
            ):
                if not (options.user and options.password):
                    raise InvalidCommandLineError("Empty username or password was entered.")
        else:
            # Check to see if there is a URL in config file
            if self.rdmc.config.url:
                self.url = self.rdmc.config.url

    def _get_cachedir(self):
        """Return the rdmc app cache directory if available, else None."""
        try:
            if self.rdmc and self.rdmc.app and hasattr(self.rdmc.app, "cachedir"):
                return self.rdmc.app.cachedir
        except Exception:
            pass
        return None

    def _read_cached_ilo_generation(self):
        """Read the persisted iLO generation, or None if unavailable."""
        return read_cached_generation(self._get_cachedir())

    def _write_cached_ilo_generation(self, version):
        """Persist a freshly probed iLO generation for reuse by later commands."""
        try:
            write_cached_generation(version, self._get_cachedir())
        except (TypeError, ValueError):
            # Never let caching failures break login.
            LOGGER.debug("Skipping iLO generation cache write for value: %s", version)

    def get_ilover_beforelogin(self, args, app_obj, options):
        """Retrieve the iLO version before login.

        For out-of-band targets (args supplied) this makes a direct HTTPS GET to
        ``/redfish/v1`` to read the ``ManagerType`` / ``PRODGEN`` field. The request
        is made **directly** (proxy bypassed) so that:

        * Corporate TLS-inspection proxies (e.g. Zscaler) cannot intercept and hang
          the CNSA 2.0 / PQC TLS handshake.
        * The read timeout is not wasted waiting for a proxy that cannot complete a
          post-quantum key exchange.

        If the direct probe fails (SSL error or timeout), a retry is attempted with a
        longer timeout. If both fail, a :class:`GenBeforeLoginError` is raised with a
        clear diagnostic that includes the ``--url`` workaround.

        Args:
            args: List of command-line arguments; expects iLO IP/hostname at index 0.
            app_obj: AppAccount object for in-band fallback when args is empty.
            options: Parsed options; may carry ``force_vnic`` or ``usechif`` flags.

        Returns:
            iLO version as an integer (e.g. 7 or 8).

        Raises:
            GenBeforeLoginError: If the generation cannot be determined.
            VnicExistsError: If the VNIC path is unavailable.
        """
        ip = path = None  # avoid UnboundLocalError in exception handlers
        try:
            if args:
                ip = args[0]
                path = f"{ip}/redfish/v1"
                if ip and "https://" not in ip:
                    path = f"https://{ip}/redfish/v1"

                # Use urllib3 directly with an explicit PQC ssl_context so that the
                # correct KEM groups/sigalgs are applied regardless of whether
                # OPENSSL_CONF is set.  A plain PoolManager (no ProxyManager) is used
                # so corporate TLS-inspection proxies (e.g. Zscaler) that cannot
                # complete a CNSA 2.0 handshake are bypassed automatically.

                def _probe(timeout_s):
                    """Single direct GET attempt with explicit PQC ssl_context and proxy bypass."""
                    # The iLO generation is not yet known at probe time, so offer the
                    # widest KEM group set (Level-V MLKEM1024 groups first, then the
                    # Level-III hybrids and classical fallbacks).  A strict iLO8 rejects
                    # a Level-III-only ClientHello with a fatal handshake_failure, so
                    # without the Level-V groups the probe could never detect an iLO8.
                    ssl_ctx = build_ssl_context(
                        resolve_mode_from_env(), verify=False, generation=_PQC_STRICT_MIN_GENERATION
                    )
                    http = urllib3.PoolManager(
                        ssl_context=ssl_ctx,
                        timeout=urllib3.util.Timeout(connect=timeout_s[0], read=timeout_s[1]),
                    )
                    try:
                        return http.request("GET", path)
                    except Exception:
                        http.clear()
                        raise

                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", urllib3.exceptions.InsecureRequestWarning)

                    try:
                        response = _probe(timeout_s=(5, 10))  # (connect, read)
                    except (urllib3.exceptions.SSLError, urllib3.exceptions.HTTPError) as _first_exc:
                        # Retry once with a longer read timeout in case the PQC
                        # handshake takes longer than expected on first connection.
                        LOGGER.debug(
                            "Pre-login generation probe failed (%s: %s); retrying with extended timeout.",
                            type(_first_exc).__name__,
                            _first_exc,
                        )
                        try:
                            response = _probe(timeout_s=(5, 30))
                        except (urllib3.exceptions.SSLError, urllib3.exceptions.HTTPError):
                            raise  # re-raise for the outer handler

                # urllib3 does not have raise_for_status(); check the status manually.
                if response.status >= 400:
                    raise urllib3.exceptions.HTTPError(f"HTTP error {response.status} from {path}")

                try:
                    json_data = json.loads(response.data)
                    oem_data = json_data.get("Oem", {}).get("Hpe") or json_data.get("Oem", {}).get("Hp")
                    if not oem_data:
                        raise KeyError("Oem->Hpe or Oem->Hp block missing in response.")

                    manager = oem_data.get("Manager", [{}])[0]
                    manager_type = manager.get("ManagerType")

                    if manager_type:
                        ilo_ver = int(manager_type.split(" ")[1])
                    else:
                        moniker = oem_data.get("Moniker", {})
                        prodgen = moniker.get("PRODGEN")
                        if not prodgen:
                            raise KeyError("PRODGEN key not found in Moniker.")
                        ilo_ver = int(prodgen.split(" ")[1])
                except (KeyError, ValueError, IndexError) as e:
                    raise GenBeforeLoginError(
                        f"Failed to parse iLO version from response. Error: {e}\n"
                        "Ensure the iLO firmware is Redfish-compliant and responds correctly.\n"
                    )
            else:
                # Local in-band path: detecting the generation over CHIF costs a
                # full channel open/close, and the close incurs libhpsrv's ~1 s
                # Sleep(1000). The generation is a hardware constant, so reuse the
                # cached value when present and skip the probe entirely. This is
                # safe even under --nocache because the generation never changes.
                cached_gen = self._read_cached_ilo_generation()
                if cached_gen is not None:
                    LOGGER.debug(
                        "Using cached iLO generation (skipping pre-login CHIF probe): %s",
                        cached_gen,
                    )
                    return int(cached_gen)

                ilo_ver, _ = self.rdmc.app.getilover_beforelogin(app_obj)
                # Persist for subsequent commands so they avoid the probe too.
                self._write_cached_ilo_generation(ilo_ver)

            return ilo_ver

        except ChifDriverMissingOrNotFound:
            if getattr(options, "force_vnic", False):
                return 5
            raise

        except VnicNotEnabledError:
            if getattr(options, "usechif", False):
                return 7
            raise VnicExistsError(
                "Unable to access iLO using virtual NIC.\n"
                "Please ensure that virtual NIC is enabled in iLO and "
                "properly configured in the host OS.\n"
                "Refer to the documentation for setup instructions.\n"
            )

        except urllib3.exceptions.SSLError as e:
            raise GenBeforeLoginError(
                f"SSL/TLS Error: Unable to connect to {ip or '[unknown IP]'}.\n"
                f"Details: {e}\n"
                "If iLO is configured for CNSA 2.0 (PQC), ensure the iLORest build\n"
                "includes OpenSSL 3.5+ with CNSA 2.0 TLS defaults (openssl-cnsa2.cnf).\n"
                "See docs/PQC-troubleshooting.md for diagnostics.\n"
            )

        except urllib3.exceptions.HTTPError as e:
            # Provide a clear diagnostic when the probe times out or is refused.
            # Common causes: corporate proxy intercepting the direct connection,
            # firewall blocking HTTPS, or a PQC-incompatible TLS stack.
            _ilo_or_placeholder = ip or "<ilo-ip>"
            _hint = (
                "Tip: If a corporate proxy is blocking direct iLO access, set\n"
                f"  $env:no_proxy = '{ip}'\n"
                "and retry.  For CNSA 2.0 iLOs run:\n"
                f"  python pqc_probe.py {_ilo_or_placeholder}\n"
                "to diagnose the TLS handshake."
            )
            raise GenBeforeLoginError(
                f"Connection Error: Could not retrieve data from {path or '[unknown path]'}.\n"
                f"Details: {e}\n"
                f"{_hint}\n"
            )

        except Exception as e:
            raise GenBeforeLoginError(
                f"An unexpected error occurred while retrieving the iLO version.\n"
                f"Details: {e}\n"
                "Verify if virtual NIC is enabled for iLO7 or that the CHIF driver "
                "is installed for iLO5 and iLO6 based servers.\n"
            )

    def definearguments(self, customparser):
        """Wrapper function for new command main function

        :param customparser: command line input
        :type customparser: parser.
        """

        def remove_argument(parser, arg):
            for action in parser._actions:
                opts = action.option_strings
                if (opts and opts[0] == arg) or action.dest == arg:
                    parser._remove_action(action)
                    break

            for action in parser._action_groups:
                for group_action in action._group_actions:
                    opts = group_action.option_strings
                    if (opts and opts[0] == arg) or group_action.dest == arg:
                        action._group_actions.remove(group_action)
                        return

        if not customparser:
            return

        customparser.add_argument(
            "--wait_for_otp",
            dest="waitforOTP",
            help="Optionally include this flag to implicitly wait for OTP.",
            action="store_true",
            default=None,
        )
        self.cmdbase.add_login_arguments_group(customparser)
        remove_argument(customparser, "url")
        customparser.add_argument(
            "--selector",
            dest="selector",
            help="Optionally include this flag to select a type to run"
            " the current command on. Use this flag when you wish to"
            " select a type without entering another command, or if you"
            " wish to work with a type that is different from the one"
            " you currently have selected.",
            default=None,
        )
        customparser.add_argument(
            "--no_app_token",
            "--no_app_account",
            dest="noapptoken",
            help="Include this parameter in order to login to iLO7 and above with credentials and not app account.",
            default=None,
            action="store_true",
        )
        customparser.add_argument("--hostappid", dest="hostappid", help="Parameter to specify hostappid", default=None)
        customparser.add_argument(
            "--hostappname", dest="hostappname", help="Parameter to specify hostappname", default=None
        )
        customparser.add_argument(
            "--salt", dest="salt", help="Parameter to specify application owned salt", default=None
        )
        customparser.add_argument(
            "--use_chif",
            dest="usechif",
            help="Include this parameter in order to operate iLO7 and above using chif.",
            default=None,
            action="store_true",
        )
        customparser.add_argument(
            "--show_session_id",
            "-s",
            dest="session_id",
            help=SUPPRESS,
            default=None,
            action="store_true",
        )
        customparser.add_argument(
            "--show_session_loc",
            dest="session_loc",
            help=SUPPRESS,
            default=None,
            action="store_true",
        )
