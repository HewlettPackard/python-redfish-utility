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
"""Logout Command for RDMC"""

from argparse import SUPPRESS

try:
    from rdmc_helper import (
        LOGGER,
        InvalidCommandLineErrorOPTS,
        ReturnCodes,
        UsernamePasswordRequiredError,
        Encryption,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        LOGGER,
        InvalidCommandLineErrorOPTS,
        ReturnCodes,
        UsernamePasswordRequiredError,
        Encryption,
    )

try:
    from tpm_lock import TpmFileLock
except ImportError:
    from ilorest.tpm_lock import TpmFileLock

try:
    from redfish.rest.connections import (
        InvalidCredentialsError,
        SecurityStateError,
    )
except ImportError:
    # Define fallback classes if imports fail
    class SecurityStateError(Exception):
        pass

    class InvalidCredentialsError(Exception):
        pass


from redfish.hpilo.risblobstore2 import Blob2SecurityError


class LogoutCommand:
    """Constructor"""

    def __init__(self):
        self.ident = {
            "name": "logout",
            "usage": None,
            "description": "Run to end the current session and disconnect "
            "from the server.\n\tExample: logout"
            "\n\n\tOn servers running in High Security/FIPS mode, the local "
            "(in-band) session cannot be removed from iLO without valid "
            "credentials, since the CHIF driver independently verifies them "
            "for every local channel operation. Include -u/-p to authenticate "
            "and remove the session from iLO immediately."
            "\n\tExample: logout -u <iLO username> -p <iLO password>",
            "summary": "Ends the current session and disconnects from the server.",
            "aliases": [],
            "auxcommands": [],
        }
        self.cmdbase = None
        self.rdmc = None

    def logoutfunction(self, line):
        """Main logout worker function

        :param line: command line input
        :type line: string.
        """
        try:
            options, _ = self.rdmc.rdmc_parse_arglist(self, line)
        except (InvalidCommandLineErrorOPTS, SystemExit):
            if ("-h" in line) or ("--help" in line):
                return ReturnCodes.SUCCESS
            else:
                raise InvalidCommandLineErrorOPTS("")

        # -u/-p must be supplied together: partial credentials cannot
        # authenticate to the local CHIF driver and would otherwise fail
        # silently deeper in the connection-restore logic.
        LOGGER.debug(
            "Note: In In-Band/Local mode using CHIF on a High Security mode "
            "server, credentials are optional for the logout command. "
            "However, valid credentials may be required if the session "
            "needs to be cleaned up from iLO as well. Credentials will "
            "be validated only when they are provided and should be "
            "passed only for sessions created through CHIF mode."
        )
        username = getattr(options, "user", None)
        password = getattr(options, "password", None)
        if username and not password:
            raise UsernamePasswordRequiredError(
                "Please also provide a password (-p) with the username.\n",
            )
        if password and not username:
            raise UsernamePasswordRequiredError(
                "Please also provide a username (-u) with the password.\n",
            )

        if options.encode and (not username or not password):
            raise UsernamePasswordRequiredError(
                "Please provide both -u and -p when using encode.\n",
            )

        # If credentials were supplied for a CHIF/local in-band session,
        # verify them against the CHIF driver *before* attempting logout so
        # bad credentials surface as a clear error instead of silently
        # failing to remove the session from iLO.
        if username and password:
            if options.encode:
                username = Encryption.decode_credentials(username)
                if isinstance(username, bytes):
                    username = username.decode("utf-8")
                password = Encryption.decode_credentials(password)
                if isinstance(password, bytes):
                    password = password.decode("utf-8")

                options.user = username
                options.password = password
            self._validate_chif_credentials(username, password)

        # Acquire the TPM file lock during logout to prevent concurrent
        # sem_unlink from destroying the semaphore while another process is mid-login.
        # iLO5/iLO6 do not use the TPM, so the lock is a no-op there (see for_rdmc).
        with TpmFileLock.for_rdmc(self.rdmc):
            self.rdmc.app.logout("")

    def _validate_chif_credentials(self, username, password):
        """Validate the given username/password against the CHIF driver when
        the current/cached session is local/in-band (blobstore). Remote
        (HTTP) sessions authenticate via the normal REST session mechanism
        and don't need this extra check.

        :param username: iLO username supplied on the command line.
        :type username: str.
        :param password: iLO password supplied on the command line.
        :type password: str.
        :raises InvalidCredentialsError: if the credentials are rejected by iLO
        :raises SecurityStateError: if High Security mode requires credentials
            that could not be verified.
        """
        redfishinst = getattr(self.rdmc.app, "redfishinst", None)
        base_url = str(getattr(redfishinst, "base_url", "") or "")

        if not base_url:
            # redfishinst can be empty here even for a blobstore session: if
            # the credentials used to restore() the cached client were wrong,
            # RestClient()/Blobstore2Connection construction raises inside
            # _uncache_client(), which swallows the exception and leaves
            # self.app.redfishinst as None (see rmc_helper.py). Fall back to
            # reading the cached session's URL directly (no live connection
            # needed) so validation still runs in exactly that scenario.
            get_cached_url = getattr(
                self.rdmc,
                "_get_cached_session_url",
                None,
            )
            if callable(get_cached_url):
                base_url = str(get_cached_url() or "")

        if "blobstore" not in base_url:
            # Not a local/in-band session; nothing to validate here.
            return

        try:
            from redfish.hpilo.risblobstore2 import BlobStore2

            log_dir = getattr(self.rdmc, "log_dir", "") or ""
            correctcreds = BlobStore2.initializecreds(
                username=username,
                password=password,
                log_dir=log_dir,
            )
            if not correctcreds:
                bs2 = BlobStore2(
                    log_dir=log_dir,
                    username=username,
                    password=password,
                )
                security_state = int(bs2.get_security_state())
                LOGGER.debug(
                    "logout: credential validation failed, security_state=%s",
                    security_state,
                )
                if security_state == 3:
                    if InvalidCredentialsError:
                        raise InvalidCredentialsError(0)
                    raise UsernamePasswordRequiredError(
                        "Invalid username or password provided.\n",
                    )
                if SecurityStateError:
                    raise SecurityStateError(security_state)
                raise UsernamePasswordRequiredError(
                    "Unable to validate credentials with iLO.\n",
                )
        except UsernamePasswordRequiredError as excp:
            LOGGER.debug("Error while validating credentials: %s", excp)
            raise
        except Blob2SecurityError as excp:
            LOGGER.debug("Error while validating credentials: %s", excp)
            raise InvalidCredentialsError(0)
        except Exception as excp:
            LOGGER.debug(
                "Error while validating credentials: %s",
                excp,
                exc_info=True,
            )
            if isinstance(excp, (InvalidCredentialsError, SecurityStateError)):
                raise
            LOGGER.debug("logout: error validating credentials: %s", excp)
            raise UsernamePasswordRequiredError(
                "Unable to validate the provided username/password with iLO.",
            )

    def run(self, line, help_disp=False):
        """Wrapper function for main logout function

        :param line: command line input
        :type line: string.
        """
        if help_disp:
            self.parser.print_help()
            return ReturnCodes.SUCCESS
        self.rdmc.ui.printer("Logging session out.\n")
        self.logoutfunction(line)

        # Return code
        return ReturnCodes.SUCCESS

    def definearguments(self, customparser):
        """Wrapper function for new command main function

        :param customparser: command line input
        :type customparser: parser.
        """
        if not customparser:
            return

        customparser.add_argument(
            "-u",
            "--user",
            dest="user",
            help="Optionally include this flag to specify the iLO username. "
            "Required (together with -p) to remove the local/in-band session "
            "from iLO immediately when the server is running in High "
            "Security/FIPS mode.",
            default=None,
        )
        customparser.add_argument(
            "-p",
            "--password",
            dest="password",
            help="Optionally include this flag to specify the iLO password. "
            "Required (together with -u) to remove the local/in-band session "
            "from iLO immediately when the server is running in High "
            "Security/FIPS mode.",
            default=None,
        )
        customparser.add_argument(
            "-e",
            "--enc",
            dest="encode",
            action="store_true",
            help=SUPPRESS,
            default=False,
        )
