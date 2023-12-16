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
""" Types Command for RDMC """

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


class TypesCommand:
    """Constructor"""

    def __init__(self):
        self.ident = {
            "name": "types",
            "usage": None,
            "description": "Run to display currently " "available selectable types\n\tExample: types",
            "summary": "Displays all selectable types within the currently logged in server.",
            "aliases": [],
            "auxcommands": [],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def typesfunction(self, line, returntypes=False):
        """Main types worker function

        :param line: command line input
        :type line: string.
        :param returntypes: flag to determine if types should be printed
        :type returntypes: boolean.
        """
        try:
            (options, args) = self.rdmc.rdmc_parse_arglist(self, line)
        except (InvalidCommandLineErrorOPTS, SystemExit):
            if ("-h" in line) or ("--help" in line):
                return ReturnCodes.SUCCESS
            else:
                raise InvalidCommandLineErrorOPTS("")

        self.typesvalidation(options)

        if not args:
            typeslist = list()
            typeslist = sorted(set(self.rdmc.app.types(options.fulltypes)))

            if not returntypes:
                self.rdmc.ui.printer("Type options:\n")

                for item in typeslist:
                    self.rdmc.ui.printer("%s\n" % item)
            else:
                return typeslist
        else:
            raise InvalidCommandLineError("The 'types' command does not take any arguments.")

        self.cmdbase.logout_routine(self, options)

    def run(self, line, help_disp=False):
        """Wrapper function for types main function

        :param line: command line input
        :type line: string.
        """
        if help_disp:
            self.parser.print_help()
            return ReturnCodes.SUCCESS
        self.typesfunction(line)

        # Return code
        return ReturnCodes.SUCCESS

    def typesvalidation(self, options):
        """types method validation function

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

        customparser.add_argument(
            "--fulltypes",
            dest="fulltypes",
            action="store_true",
            help="Optionally include this flag if you would prefer to "
            "return the full type name instead of the simplified versions"
            " (Redfish only option).",
            default=None,
        )
