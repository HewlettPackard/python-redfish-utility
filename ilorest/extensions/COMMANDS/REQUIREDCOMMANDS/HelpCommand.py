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
""" Help Command for RDMC """

try:
    from rdmc_base_classes import RdmcCommandBase, RdmcOptionParser
except ImportError:
    from ilorest.rdmc_base_classes import RdmcCommandBase, RdmcOptionParser
try:
    from rdmc_helper import (
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        ReturnCodes,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        ReturnCodes,
    )


class HelpCommand(RdmcCommandBase):
    """Constructor"""

    def __init__(self):
        self.ident = {
            "name": "help",
            "usage": None,
            "description": "help [COMMAND]\n\tFor more detailed command descriptions"
            " use the help command feature\n\texample: help login\n",
            "summary": "Displays command line syntax and help menus for individual commands." " Example: help login\n",
            "aliases": [],
            "auxcommands": [],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """Wrapper function for help main function
        :param line: command line input
        :type line: string.
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
                raise InvalidCommandLineErrorOPTS("")

        if not args or not line:
            RdmcOptionParser().print_help()
            if self.rdmc:
                cmddict = self.rdmc.get_commands()
                sorted_keys = sorted(list(cmddict.keys()))

                for key in sorted_keys:
                    if key[0] == "_":
                        continue
                    else:
                        self.rdmc.ui.printer("\n%s\n" % key)
                    for cmd in cmddict[key]:
                        self.rdmc.ui.printer(
                            "%-25s - %s\n"
                            % (
                                self.rdmc.commands_dict[cmd].ident["name"],
                                self.rdmc.commands_dict[cmd].ident["summary"],
                            )
                        )
        else:
            if self.rdmc:
                cmddict = self.rdmc.get_commands()
                sorted_keys = list(cmddict.keys())

                for key in sorted_keys:
                    for cmd in cmddict[key]:
                        cmd_s = cmd.split("Command")
                        cmd_s = cmd_s[0]
                        if args[0].lower() == cmd_s.lower():
                            self.rdmc.ui.printer(self.rdmc.commands_dict[cmd].ident["description"] + "\n")
                            return ReturnCodes.SUCCESS
                raise InvalidCommandLineError("Command '%s' not found." % args[0])
        # Return code
        return ReturnCodes.SUCCESS

    def definearguments(self, customparser):
        """Wrapper function for new command main function

        :param customparser: command line input
        :type customparser: parser.
        """
        if not customparser:
            return
