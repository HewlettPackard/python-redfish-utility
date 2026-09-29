###
# Copyright 2016-2026 Hewlett Packard Enterprise, Inc. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy at
#  http://www.apache.org/licenses/LICENSE-2.0
###

# -*- coding: utf-8 -*-
"""RawPost Command for rdmc

Uses the same optimized in-band engine as RawCommandBase (direct CHIF/VNIC,
iLO-generation caching, session reuse) — only the HTTP verb and body differ.
"""

try:
    from rdmc_helper import (
        Encryption,
        ReturnCodes,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        Encryption,
        ReturnCodes,
    )

try:
    from .RawCommandBase import RawCommandBase
except ImportError:
    from RawCommandBase import RawCommandBase


class RawPostCommand(RawCommandBase):
    """Raw form of the POST command — shares the optimized engine from RawCommandBase."""

    # Declared at class level so the verb is known before run() executes; the
    # shared formatters use it to pick 7.3-compatible output and return codes.
    _raw_method = "POST"

    def __init__(self):
        super().__init__()
        self.ident = {
            "name": "rawpost",
            "usage": None,
            "description": (
                "Run to send a post from the data in the input file.\n"
                "\tMultiple POSTs can be performed in sequence by adding more "
                "path/body key/value pairs.\n"
                "\n\texample: rawpost rawpost.txt"
                "\n\n\tExample input file:\n\t{\n"
                '\t    "/redfish/v1/systems/(system ID)/Actions/ComputerSystem.Reset":\n'
                '\t    {\n\t        "ResetType": "ForceRestart"\n\t    }\n\t}'
            ),
            "summary": "Raw form of the POST command.",
            "aliases": [],
            "auxcommands": ["DetectiLOCommand", "AppAccountCommand"],
        }
        self.cmdbase = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """Main raw post worker function — uses the shared optimized engine."""
        if help_disp:
            self.parser.print_help()
            return ReturnCodes.SUCCESS

        options = self._parse_arguments(line)
        headers, _ = self._parse_headers(options)

        contentsholder = self._load_body_file(options.path)

        # Decode encoded credentials in body if requested
        if getattr(options, "encode", False):
            body = contentsholder.get("body", {})
            if "UserName" in body and "Password" in body and len(body) == 2:
                encobj = Encryption()
                body["UserName"] = encobj.decode_credentials(body["UserName"])
                body["Password"] = encobj.decode_credentials(body["Password"])

        pairs = self._extract_path_body_pairs(contentsholder, options.path)
        self._raw_method = "POST"

        if getattr(options, "no_auth", False):
            results = []
            for rpath, body in pairs:
                self._raw_body = body
                results.append(self._handle_no_auth_request(options, headers, rpath))
            self._raw_body = None
            return ReturnCodes.SUCCESS if all(r == ReturnCodes.SUCCESS for r in results) else ReturnCodes.GENERAL_ERROR

        if getattr(options, "sessionid", False):
            headers["X-Auth-Token"] = options.sessionid

        overall = ReturnCodes.SUCCESS
        for rpath, body in pairs:
            self._raw_body = body
            rc = self._execute_main_flow(options, headers, None, rpath)
            if rc != ReturnCodes.SUCCESS:
                overall = rc

        self._raw_body = None
        self.cmdbase.logout_routine(self, options)
        return overall

    def _invoke_framework_handler(self, path, headers, options):
        """Use post_handler for the high-security / legacy fallback path."""
        is_service = getattr(options, "service", False)
        return self.rdmc.app.post_handler(
            path,
            self._raw_body or {},
            headers=headers,
            silent=True,
            service=is_service,
        )

    def definearguments(self, customparser):
        if not customparser:
            return
        self.cmdbase.add_login_arguments_group(customparser)
        customparser.add_argument("path", help="Path to the JSON file containing the data to be posted.")
        customparser.add_argument(
            "--silent",
            dest="silent",
            action="store_true",
            default=False,
            help="Use this flag to suppress the HTTP status line (e.g. [200]) only. "
            "The response body is still printed.",
        )
        customparser.add_argument(
            "--response",
            dest="response",
            action="store_true",
            default=False,
            help="Use this flag to return the iLO response body.",
        )
        customparser.add_argument(
            "--getheaders",
            dest="getheaders",
            action="store_true",
            default=False,
            help="Use this flag to return the iLO response headers.",
        )
        customparser.add_argument(
            "--headers",
            dest="headers",
            default=None,
            help="Use this flag to add extra headers. Usage: --headers=HEADER:VALUE,HEADER:VALUE",
        )
        customparser.add_argument(
            "--service",
            dest="service",
            action="store_true",
            default=False,
            help="Use this flag to enable service mode and increase the function speed",
        )
        customparser.add_argument(
            "--no_auth",
            dest="no_auth",
            action="store_true",
            default=False,
            help="Use this flag to skip authentication for the request",
        )
