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
This command provides direct HTTP GET access to iLO Redfish endpoints
 with optimized performance and comprehensive authentication handling
 across different iLO generations.

The heavy lifting (authentication flow, in-band CHIF/VNIC handling,
iLO-generation caching, response formatting and the legacy-framework
fallback) lives in the shared ``RawCommandBase`` engine so that every raw
command (get/post/put/patch/delete/head) can extend ``RawCommandBase``
directly without depending on ``RawGetCommand``.

Authentication Flow:
1. Determine connection mode (out-of-band vs in-band)
2. For out-of-band (--url provided): Handle immediately without local iLO detection
   - Requires URL and credentials
   - Create HTTP session, get output, logout
3. Check for cached session (from prior login) - use if available without iLO detection
4. For in-band without cached session: Check if ilo_generation.json cache exists, create if not
5. Create temp session based on iLO version and mode.
"""

import json
import logging
import sys

import requests
from urllib.parse import urljoin
from redfish.rest.v1 import RestClient

# Get logger instance
LOGGER = logging.getLogger(__name__)

try:
    from rdmc_helper import ReturnCodes, LOGGER
except ImportError:
    from ilorest.rdmc_helper import ReturnCodes, LOGGER

try:
    from .RawCommandBase import RawCommandBase
except ImportError:
    from RawCommandBase import RawCommandBase


class RawGetCommand(RawCommandBase):
    """
    Raw form of the get command with optimized
    session and request handling
    """

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

        # Handle sessionid requests
        if getattr(options, "sessionid", False):
            headers = {"X-Auth-Token": options.sessionid}
            VNIC_IP = "16.1.15.1"

            if not options.url or (options.url and VNIC_IP in options.url):
                ilo_version = self._detect_ilo_version()
                LOGGER.debug(f"ilo_version: {ilo_version}")

                vnic_enabled = self._is_vnic_available()
                LOGGER.debug(f"Is VNIC enabled: {vnic_enabled}")

                if not vnic_enabled:
                    if (options.url and VNIC_IP in options.url) or (ilo_version and ilo_version >= 7):
                        # If vNIC is disabled & either vNIC IP provided in the --url or
                        #  iLO version is >=7 then display error message
                        sys.stderr.write("VNIC is disabled. Please enable it before making a request.\n")
                        return ReturnCodes.VNIC_NOT_ENABLED_ERROR

                    return self.handle_blobstore_request(
                        options,
                        headers,
                    )

            # HTTP GET request
            url = options.url if options.url else VNIC_IP
            if not url.startswith("https://"):
                url = f"https://{url}"

            path = urljoin(url, options.path)
            LOGGER.debug(f"HTTP request to {path}\n")
            LOGGER.debug(f"Headers: {self._mask_headers(headers)}\n")
            try:
                response = requests.get(
                    path,
                    headers=headers,
                    verify=False,
                )
                return self._handle_response(response, options)
            except requests.exceptions.Timeout as err:
                LOGGER.error(f"Connection timeout to {url}: {err}")
                sys.stderr.write(f"Error: Connection timeout to {url}.")
                sys.stderr.write("iLO may be resetting or unreachable.\n")
                return ReturnCodes.V1_SERVER_DOWN_OR_UNREACHABLE_ERROR
            except requests.exceptions.ConnectionError as err:
                LOGGER.error(f"Connection failed to {url}: {err}")
                sys.stderr.write(f"Error: Connection failed to {url}.")
                sys.stderr.write("iLO may be resetting or unreachable.\n")
                return ReturnCodes.V1_SERVER_DOWN_OR_UNREACHABLE_ERROR
            except Exception as err:
                LOGGER.error(f"Failed to complete request: {err}")
                sys.stderr.write(f"Error: Failed to complete operation - {err}\n")
                return ReturnCodes.GENERAL_ERROR

        # Execute the main authentication flow
        return self._execute_main_flow(options, headers, session_token_from_headers, path)

    def handle_blobstore_request(self, options, headers):
        """
        get details from blobstore
        """
        # If vNIC IP is not provided in the --url &
        # vNIC is disabled then proceed with blobstore request
        LOGGER.debug(f"blobstore request to {options.path}")
        username, password = self._get_cred(options)
        rest_obj = RestClient(
            sessionid=options.sessionid,
            username=username,
            password=password,
            base_url="blobstore://.",
        )
        response = rest_obj.get(options.path, headers=headers)
        return self._old_framework_handle_response(
            options,
            response,
        )

    def _old_framework_handle_response(self, options, response):
        """Handle the response and format output from get_handler()"""
        is_silent = getattr(options, "silent", False)

        if getattr(options, "filename", None):
            return self._write_response_into_file(response, options)

        if getattr(options, "binfile", None):
            return self._write_response_in_binary(response, options)

        body = response.dict if hasattr(response, "dict") else response
        status_msg = self._get_status_message_from_response(response, body)

        out = self._body_stream(options)
        # --silent suppresses only the status line, the JSON body is still written
        if not is_silent:
            out.write(f"[{response.status}] {status_msg}\n")

        show_headers = getattr(options, "getheaders", False)
        show_response = getattr(options, "response", False)

        if show_headers:
            if hasattr(response, "getheaders") and response.getheaders():
                headers = dict(response.getheaders())
                sys.stdout.write(f"{json.dumps(headers, separators=(',', ':'))},\n")

        if 200 <= response.status < 300:
            try:
                if show_response and body is not None:
                    sys.stdout.write(f"{json.dumps(body, separators=(',', ':'))}\n")
                elif getattr(options, "service", False) and not show_headers:
                    # Output as Python dict format (with single quotes)
                    sys.stdout.write(f"{body}\n")
                elif not show_headers and not show_response and body is not None:
                    sys.stdout.write(f"{json.dumps(body, indent=2, sort_keys=True, separators=(',', ':'))}\n")
                sys.stdout.flush()
                return ReturnCodes.SUCCESS
            except Exception as e:
                LOGGER.error(f"Response formatting failed: {e}")
                sys.stderr.write(f"Error: Response formatting failed: {str(e)}\n")
                return ReturnCodes.GENERAL_ERROR

        if body is not None:
            out.write(f"{json.dumps(body, separators=(',', ':'))}\n")
            out.flush()

        if response.status == 401:
            return ReturnCodes.RIS_SESSION_EXPIRED
        elif response.status >= 400:
            return ReturnCodes.RIS_ILO_RESPONSE_ERROR
        return ReturnCodes.GENERAL_ERROR

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
            help="Use this flag to suppress the HTTP status line (e.g. [200]) only. "
            "The response body is still printed.",
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
