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
""" Exit Command for rdmc """

import sys

try:
    from rdmc_helper import InvalidCommandLineErrorOPTS, ReturnCodes
except ImportError:
    from ilorest.rdmc_helper import InvalidCommandLineErrorOPTS, ReturnCodes


class ExitCommand:
    """Exit class to handle exiting from interactive mode"""

    def __init__(self):
        self.ident = {
            "name": "exit",
            "usage": None,
            "description": "Run to exit from the interactive shell\n\texample: exit",
            "summary": "Exits from the interactive shell.",
            "aliases": ["quit"],
            "auxcommands": ["LogoutCommand"],
        }
        # self.rdmc = rdmcObj
        # self.logoutobj = rdmcObj.commands_dict["LogoutCommand"](rdmcObj)

        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """If an argument is present, print help else exit

        :param line: command line input
        :type line: string.
        """
        if help_disp:
            self.parser.print_help()
            return ReturnCodes.SUCCESS
        try:
            (_, args) = self.rdmc.rdmc_parse_arglist(self, line)
        except (InvalidCommandLineErrorOPTS, SystemExit):
            if ("-h" in line) or ("--help" in line):
                return ReturnCodes.SUCCESS
            else:
                raise InvalidCommandLineErrorOPTS("")

        if not args or not line:
            self.auxcommands["logout"].run("")

            # System exit
            sys.exit(ReturnCodes.SUCCESS)
        else:
            self.rdmc.ui.error("Exit command does not take any parameters.\n")
            raise InvalidCommandLineErrorOPTS("Invalid command line arguments.")

    def definearguments(self, customparser):
        """Wrapper function for new command main function

        :param customparser: command line input
        :type customparser: parser.
        """
        if not customparser:
            return
