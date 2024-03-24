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
""" iLO Reset Command for rdmc """

from redfish.ris.rmc_helper import IloResponseError

try:
    from rdmc_helper import (
        InvalidCommandLineErrorOPTS,
        NoContentsFoundForOperationError,
        ReturnCodes,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        InvalidCommandLineErrorOPTS,
        NoContentsFoundForOperationError,
        ReturnCodes,
    )


class IloResetCommand:
    """Reset iLO on the server that is currently logged in"""

    def __init__(self):
        self.ident = {
            "name": "iloreset",
            "usage": None,
            "description": "Reset iLO on the current logged in" " server.\n\tExample: iloreset",
            "summary": "Reset iLO on the current logged in server.",
            "aliases": [],
            "auxcommands": [],
        }

        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """Main iLO reset worker function

        :param line: string of arguments passed in
        :type line: str.
        :param help_disp: display help flag
        :type line: bool.
        """
        if help_disp:
            self.parser.print_help()
            return ReturnCodes.SUCCESS
        try:
            (options, _) = self.rdmc.rdmc_parse_arglist(self, line)
        except (InvalidCommandLineErrorOPTS, SystemExit):
            if ("-h" in line) or ("--help" in line):
                return ReturnCodes.SUCCESS
            else:
                raise InvalidCommandLineErrorOPTS("")

        self.iloresetvalidation(options)

        self.rdmc.ui.warn(
            "\nAfter iLO resets, the session will be terminated."
            "\nPlease wait for iLO to initialize completely before logging "
            "in again.\nThis process may take up to 3 minutes to complete.\n\n"
        )

        select = "/redfish/v1/Managers/1/"
        results = self.rdmc.app.get_handler(select, silent=True, service=True).dict
        try:
            results = results
        except:
            pass

        if results:
            post_path = results["Actions"]["#Manager.Reset"]["target"]
        else:
            raise NoContentsFoundForOperationError("Unable to find %s" % select)

        bodydict = results

        try:
            for item in bodydict["Actions"]:
                if "Reset" in item:
                    if self.rdmc.app.typepath.defs.isgen10:
                        action = item.split("#")[-1]
                    else:
                        action = "Reset"

                    post_path = bodydict["Actions"][item]["target"]
                    break
        except:
            action = "Reset"

        body = {"Action": action}

        postres = self.rdmc.app.post_handler(post_path, body, silent=True, service=True)
        if postres.status == 200:
            self.rdmc.ui.printer("A management processor reset is in progress.\n")
        else:
            self.rdmc.ui.error("An error occured during iLO reset.\n")
            raise IloResponseError("")

        self.cmdbase.logout_routine(self, options)
        # Return code
        return ReturnCodes.SUCCESS

    def iloresetvalidation(self, options):
        """reboot method validation function

        :param options: command line options
        :type options: list.
        """
        self.cmdbase.login_select_validation(self, options)

    def definearguments(self, customparser):
        """Wrapper function for new command main function

        :param customparser: command line input
        :type customparser: parser.
        """
        if not customparser:
            return

        self.cmdbase.add_login_arguments_group(customparser)
