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
""" Logout Command for RDMC """

try:
    from rdmc_helper import InvalidCommandLineErrorOPTS, ReturnCodes
except ImportError:
    from ilorest.rdmc_helper import InvalidCommandLineErrorOPTS, ReturnCodes


class LogoutCommand:
    """Constructor"""

    def __init__(self):
        self.ident = {
            "name": "logout",
            "usage": None,
            "description": "Run to end the current session and disconnect" " from the server\n\tExample: logout",
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
            (_, _) = self.rdmc.rdmc_parse_arglist(self, line)
        except (InvalidCommandLineErrorOPTS, SystemExit):
            if ("-h" in line) or ("--help" in line):
                return ReturnCodes.SUCCESS
            else:
                raise InvalidCommandLineErrorOPTS("")

        self.rdmc.app.logout("")

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
