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

"""  Command to Display Security State of Dimms """

# ---------Imports---------
from __future__ import absolute_import

from tabulate import tabulate

try:
    from rdmc_helper import (
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        NoContentsFoundForOperationError,
        ReturnCodes,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        ReturnCodes,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        NoContentsFoundForOperationError,
    )

from .lib.RestHelpers import RestHelpers

# ---------End of imports---------


class DisplaySecurityStateCommand:
    """Command to Display Security State of Dimms"""

    def __init__(self):
        self.ident = {
            "name": "pmmsecuritystate",
            "usage": None,
            "description": "Displaying the Security state of dimms\n\texample: pmmsecuritystate",
            "summary": "Displaying the Security state of dimms.",
            "aliases": [],
            "auxcommands": [],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()
        self._rest_helpers = None

    def display_SecurityState(self):
        resp = self._rest_helpers.retrieve_pmem_location()

        pmemLocation = []
        for item in resp["Members"]:
            if item["MemoryType"] == "IntelOptane":
                pmemLocation.append(item["Name"])

        securityState = []
        headers = ["Location", "State"]
        for i in pmemLocation:
            path = "/redfish/v1/Systems/1/Memory/" + i
            resp = self._rest_helpers.retrieve_security_state(path)
            state = resp["SecurityState"]
            securityState.append(state)

        merged_list = tuple(zip(pmemLocation, securityState))
        print(tabulate(merged_list, headers, tablefmt="psql"))

    def run(self, line, help_disp=False):
        """
        Wrapper function for new command main function
        :param line: command line input
        :type line: string.
        :param help_disp: display help flag
        :type line: bool.
        """
        if help_disp:
            self.parser.print_help()
            return ReturnCodes.SUCCESS
        try:
            (options, args) = self.rdmc.rdmc_parse_arglist(self, line)
        except (InvalidCommandLineErrorOPTS, SystemExit):
            if ("-h" in line) or ("--help" in line):
                return ReturnCodes.SUCCESS
            else:
                raise InvalidCommandLineError("Failed to parse options")
        if args:
            raise InvalidCommandLineError("Chosen flag doesn't expect additional arguments")

        # Raise exception if server is in POST
        self._rest_helpers = RestHelpers(rdmcObject=self.rdmc)
        if self._rest_helpers.in_post():
            raise NoContentsFoundForOperationError(
                "Unable to retrieve resources - " "server might be in POST or powered off"
            )

        self.display_SecurityState()

        return ReturnCodes.SUCCESS

    def definearguments(self, customparser):
        """Wrapper function for smbios command main function

        :param customparser: command line input
        :type customparser: parser.
        """
        if not customparser:
            return

        self.cmdbase.add_login_arguments_group(customparser)
