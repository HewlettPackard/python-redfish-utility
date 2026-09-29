###
# Copyright 2016-2026 Hewlett Packard Enterprise, Inc. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy at
#  http://www.apache.org/licenses/LICENSE-2.0
###

# -*- coding: utf-8 -*-
"""RawDelete Command for rdmc

Uses the same optimized in-band engine as RawCommandBase (direct CHIF/VNIC,
iLO-generation caching, session reuse) — only the HTTP verb differs and there
is no request body.
"""

try:
    from rdmc_helper import ReturnCodes
except ImportError:
    from ilorest.rdmc_helper import ReturnCodes

try:
    from .RawCommandBase import RawCommandBase
except ImportError:
    from RawCommandBase import RawCommandBase


class RawDeleteCommand(RawCommandBase):
    """Raw form of the DELETE command — shares the optimized engine from RawCommandBase.

    Extending ``RawCommandBase`` means this command reuses the same in-band
    (CHIF/VNIC) and out-of-band request engine.  The ``auxcommands`` list mirrors
    what the other raw commands declare so the extension loader wires the same
    helper commands (``DetectiLOCommand`` for in-band iLO-generation detection and
    ``AppAccountCommand`` for iLO7+ VNIC app-account flows) that the engine needs.
    Without these aux-command wires the optimized in-band path falls back to the
    legacy framework, which is slower and may not be available in all contexts.
    """

    # Declared at class level so the verb is known before run() executes; the
    # shared formatters use it to pick 7.3-compatible output and return codes.
    _raw_method = "DELETE"

    def __init__(self):
        super().__init__()
        self.ident = {
            "name": "rawdelete",
            "usage": None,
            "description": (
                "Run to delete data from the passed in path.\n"
                '\texample: rawdelete "/redfish/v1/Sessions/(session ID)"\n'
            ),
            "summary": "Raw form of the DELETE command.",
            "aliases": [],
            # NOTE: auxcommands must match the shared engine's requirements — the
            # optimized in-band engine (DetectiLOCommand for generation detection,
            # AppAccountCommand for iLO7+ VNIC) is provided by RawCommandBase and
            # needs both commands loaded.
            "auxcommands": ["DetectiLOCommand", "AppAccountCommand"],
        }
        self.cmdbase = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """Main raw delete worker function — uses the shared optimized engine.

        Authentication / login validation is handled inside ``_execute_main_flow``:

        * **In-band (CHIF/VNIC) paths** authenticate directly via CHIF or a temporary
          VNIC session — no pre-existing login session is required.
        * **Legacy / high-security path** (``_run_with_old_framework``) calls
          ``cmdbase.login_validation(self, options, skipbuild=True)`` internally before
          issuing the delete via ``delete_handler``.

        This replaces the old ``deletevalidation()`` →
        ``rdmc.login_select_validation(self, options, skipbuild=True)`` call.  The
        validation is still present; it has moved into the engine's legacy fallback
        branch where it is only invoked when the framework session is required.
        """
        if help_disp:
            self.parser.print_help()
            return ReturnCodes.SUCCESS

        options = self._parse_arguments(line)
        headers, _ = self._parse_headers(options)

        path = options.path
        if path.startswith('"') and path.endswith('"'):
            path = path[1:-1]
        if getattr(options, "expand", False):
            path = path + "?$expand=."
        options.path = path

        self._raw_method = "DELETE"
        self._raw_body = None

        # If deleting the current session, log out cleanly instead
        try:
            currentsess = self.rdmc.app.current_client.session_location
            is_current_session = bool(currentsess) and path in currentsess
        except Exception:
            is_current_session = False

        if is_current_session:
            self.rdmc.app.logout()
            self.rdmc.ui.printer(
                "Your session has been terminated (deleted).\n" "Please log back in if you wish to continue.\n"
            )
            return ReturnCodes.SUCCESS

        if getattr(options, "sessionid", False):
            headers["X-Auth-Token"] = options.sessionid

        rc = self._execute_main_flow(options, headers, None, path)
        self.cmdbase.logout_routine(self, options)
        return rc

    def _invoke_framework_handler(self, path, headers, options):
        """Use delete_handler for the high-security / legacy fallback path."""
        is_service = getattr(options, "service", False)
        return self.rdmc.app.delete_handler(
            path,
            headers=headers,
            silent=True,
            service=is_service,
        )

    def definearguments(self, customparser):
        if not customparser:
            return
        self.cmdbase.add_login_arguments_group(customparser)
        customparser.add_argument("path", help="Uri on iLO to be deleted.")
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
            "--expand",
            dest="expand",
            action="store_true",
            default=False,
            help="Use this flag to expand the path using the '?$expand=.' notation",
        )
