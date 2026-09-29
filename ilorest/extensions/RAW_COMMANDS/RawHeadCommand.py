###
# Copyright 2016-2026 Hewlett Packard Enterprise, Inc. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy at
#  http://www.apache.org/licenses/LICENSE-2.0
###

# -*- coding: utf-8 -*-
"""RawHead Command for rdmc

Uses the same optimized in-band engine as RawCommandBase (direct CHIF/VNIC,
iLO-generation caching, session reuse) — only the HTTP verb and output differ.
"""

import json
import logging
import sys

from redfish.ris import SessionExpired
from redfish.ris.rmc_helper import IloResponseError

LOGGER = logging.getLogger(__name__)

try:
    from rdmc_helper import ReturnCodes
except ImportError:
    from ilorest.rdmc_helper import ReturnCodes

try:
    from .RawCommandBase import RawCommandBase
except ImportError:
    from RawCommandBase import RawCommandBase


class RawHeadCommand(RawCommandBase):
    """Raw form of the HEAD command — shares the optimized engine from RawCommandBase."""

    # Declared at class level so the verb is known before run() executes; the
    # shared formatters use it to pick 7.3-compatible output and return codes.
    _raw_method = "HEAD"

    def __init__(self):
        super().__init__()
        self.ident = {
            "name": "rawhead",
            "usage": None,
            "description": (
                "Run to retrieve data from the passed in path\n"
                '\texample: rawhead "/redfish/v1/systems/(system ID)"\n'
            ),
            "summary": "Raw form of the HEAD command.",
            "aliases": [],
            "auxcommands": ["DetectiLOCommand", "AppAccountCommand"],
        }
        self.cmdbase = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """Main raw head worker function — uses the shared optimized engine."""
        if help_disp:
            self.parser.print_help()
            return ReturnCodes.SUCCESS

        options = self._parse_arguments(line)
        headers, _ = self._parse_headers(options)

        path = options.path
        if path.startswith('"') and path.endswith('"'):
            path = path[1:-1]
        options.path = path

        self._raw_method = "HEAD"
        self._raw_body = None

        rc = self._execute_main_flow(options, headers, None, path)
        self.cmdbase.logout_routine(self, options)
        return rc

    def _handle_response(self, response, options):
        """HEAD responses contain only headers — print status line + headers.

        Handles both new-engine responses (.status_code / .headers dict) and
        legacy old-framework responses (.status / ._http_response / ._headers).
        """
        # Support both new-engine (.status_code) and legacy (.status) objects
        status = self._response_status(response)

        # CCSE-152335: the status line must be emitted for EVERY outcome, before
        # any early return, so rawhead matches rawget/rawpost/... and so a failed
        # HEAD still reports its code (e.g. "[404] Resource not found.").
        self._emit_status_line(status, options)

        # Reason: a HEAD may legitimately answer with any 2xx (e.g. 204 No
        # Content); the previous strict "== 200" check misreported those as
        # failures. JIRA134308 established that the full 2xx range is success.
        if not isinstance(status, int):
            # No usable status at all — nothing came back to report on.
            return ReturnCodes.NO_CONTENTS_FOUND_FOR_OPERATION
        if not 200 <= status < 300:
            # Use the shared mapping so rawhead reports the SAME exit code as
            # rawget for an identical failure (e.g. 404 -> RIS_ILO_RESPONSE_ERROR).
            # Previously rawhead returned NO_CONTENTS_FOUND_FOR_OPERATION, which
            # disagreed with every other raw command.
            return self._status_error_return_code(status)

        tempdict = self._extract_head_headers(response)

        if getattr(options, "filename", None):
            import redfish

            output = json.dumps(tempdict, indent=2, cls=redfish.ris.JSONEncoder, sort_keys=True)
            with open(options.filename[0], "w") as fh:
                fh.write(output)
            self.rdmc.ui.printer(f"Results written out to '{options.filename[0]}'.\n")
            return ReturnCodes.SUCCESS

        if getattr(options, "service", False):
            self.rdmc.ui.printer(f"{tempdict}\n")
        else:
            self.rdmc.ui.print_out_json(tempdict)

        return ReturnCodes.SUCCESS

    def _extract_head_headers(self, response):
        """Extract response headers from either new-engine or legacy response object."""
        # New-engine: .headers is a mapping — a plain dict for in-band CHIF
        # (ChifResponse) or a requests.structures.CaseInsensitiveDict for the
        # out-of-band HTTP/VNIC path. CaseInsensitiveDict is NOT a dict subclass,
        # so accept any non-empty mapping and coerce it to a plain dict rather than
        # gating on isinstance(..., dict) (which silently dropped HTTP headers).
        headers = getattr(response, "headers", None)
        if headers:
            try:
                return dict(headers)
            except (TypeError, ValueError):
                pass
        # Legacy framework: prefers _http_response.getheaders() then ._headers
        if hasattr(response, "_http_response") and response._http_response:
            hdrs = response.getheaders()
            if hdrs:
                return dict(hdrs)
        if hasattr(response, "_headers") and response._headers:
            return dict(response._headers)
        if hasattr(response, "getheaders") and callable(response.getheaders):
            hdrs = response.getheaders()
            if hdrs:
                return dict(hdrs)
        return {}

    def _run_with_old_framework(self, options, headers, path):
        """Head-specific legacy-framework fallback — outputs response headers."""
        LOGGER.debug("Using legacy framework for rawhead")
        try:
            if not hasattr(self.rdmc.app, "redfishinst") or not self.rdmc.app.redfishinst:
                LOGGER.debug("Implicit login required for legacy HEAD framework")
                self.cmdbase.login_validation(self, options, skipbuild=True)

            results = self._invoke_framework_handler(path, headers, options)

            if not results:
                return ReturnCodes.NO_CONTENTS_FOUND_FOR_OPERATION

            # CCSE-152335: delegate every non-empty result (including non-2xx) to
            # _handle_response so the status line is printed on the failure path
            # too. It already knows how to extract headers from legacy responses.
            return self._handle_response(results, options)

        except SessionExpired:
            LOGGER.debug("Legacy HEAD session expired", exc_info=True)
            self._emit_status_line(401, options)
            return ReturnCodes.RIS_SESSION_EXPIRED
        except IloResponseError:
            # Reason: this exception need not carry the original HTTP response.
            LOGGER.error("Legacy HEAD failed with an iLO response error")
            return ReturnCodes.RIS_ILO_RESPONSE_ERROR
        except Exception as e:
            if self._is_credential_rejection_exception(e):
                LOGGER.debug("Legacy framework rawhead rejected the supplied credentials: %s", e)
                sys.stderr.write(self.INVALID_CREDENTIALS_MESSAGE)
                return ReturnCodes.V1_INVALID_CREDENTIALS_ERROR

            LOGGER.error("Legacy framework rawhead failed: %s", e)
            sys.stderr.write(f"Error: Legacy framework failed - {str(e)}\n")
            return ReturnCodes.INVALID_COMMAND_LINE_ERROR

    def _invoke_framework_handler(self, path, headers, options):
        """Use head_handler for the high-security / legacy fallback path."""
        is_service = getattr(options, "service", False)
        return self.rdmc.app.head_handler(
            path,
            # Reason: this command formats returned statuses, including errors.
            silent=True,
            service=is_service,
        )

    def definearguments(self, customparser):
        if not customparser:
            return
        self.cmdbase.add_login_arguments_group(customparser)
        customparser.add_argument("path", help="Uri on iLO to query HEAD.")
        customparser.add_argument(
            "--silent",
            dest="silent",
            action="store_true",
            default=None,
            help="Use this flag to suppress the HTTP status line (e.g. [200]) only.",
        )
        customparser.add_argument(
            "-f",
            "--filename",
            dest="filename",
            action="append",
            default=None,
            help="Use the provided filename to perform operations.",
        )
        customparser.add_argument(
            "--service",
            dest="service",
            action="store_true",
            default=False,
            help="Use this flag to enable service mode and increase the function speed",
        )
