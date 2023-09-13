# ##
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
# ##

# -*- coding: utf-8 -*-
""" List Component Command for rdmc """

try:
    from rdmc_helper import (
        IncompatibleiLOVersionError,
        InvalidCommandLineErrorOPTS,
        ReturnCodes,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        IncompatibleiLOVersionError,
        InvalidCommandLineErrorOPTS,
        ReturnCodes,
    )


class ListComponentCommand:
    """Main download command class"""

    def __init__(self):
        self.ident = {
            "name": "listcomp",
            "usage": None,
            "description": "Run to list the components of " "the currently logged in system.\n\texample: listcomp",
            "summary": "Lists components/binaries from the iLO Repository.",
            "aliases": [],
            "auxcommands": [],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """Main listcomp worker function

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

        self.listcomponentvalidation(options)

        if self.rdmc.app.typepath.defs.isgen9:
            raise IncompatibleiLOVersionError("iLO Repository commands are " "only available on iLO 5.")

        comps = self.rdmc.app.getcollectionmembers("/redfish/v1/UpdateService/ComponentRepository/")

        if comps:
            self.printcomponents(comps, options)
        else:
            self.rdmc.ui.printer("No components found.\n")

        self.cmdbase.logout_routine(self, options)
        # Return code
        return ReturnCodes.SUCCESS

    def printcomponents(self, comps, options):
        """Print components function

        :param comps: list of components
        :type comps: list.
        """
        if options.json:
            jsonout = dict()
            for comp in comps:
                jsonout[comp["Id"]] = comp
            self.rdmc.ui.print_out_json(jsonout)
        else:
            for comp in comps:
                self.rdmc.ui.printer(
                    "Id: %s\nName: %s\nVersion: %s\nLocked:%s\nComponent "
                    "Uri:%s\nFile Path: %s\nSizeBytes: %s\n\n"
                    % (
                        comp["Id"],
                        comp["Name"],
                        comp["Version"],
                        "Yes" if comp["Locked"] else "No",
                        comp["ComponentUri"],
                        comp["Filepath"],
                        str(comp["SizeBytes"]),
                    )
                )

    def listcomponentvalidation(self, options):
        """listcomp validation function

        :param options: command line options
        :type options: list.
        """
        self.rdmc.login_select_validation(self, options)

    def definearguments(self, customparser):
        """Wrapper function for new command main function

        :param customparser: command line input
        :type customparser: parser.
        """
        if not customparser:
            return

        self.cmdbase.add_login_arguments_group(customparser)

        customparser.add_argument(
            "-j",
            "--json",
            dest="json",
            action="store_true",
            help="Optionally include this flag if you wish to change the"
            " displayed output to JSON format. Preserving the JSON data"
            " structure makes the information easier to parse.",
            default=False,
        )
