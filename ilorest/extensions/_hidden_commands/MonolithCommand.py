###
# Copyright 2016 Hewlett Packard Enterprise, Inc. All rights reserved.
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
""" Monolith Command for rdmc """

import json

try:
    from rdmc_helper import UI, InvalidCommandLineErrorOPTS, ReturnCodes
except ImportError:
    from ilorest.rdmc_helper import UI, InvalidCommandLineErrorOPTS, ReturnCodes
from redfish.rest.containers import JSONEncoder
from redfish.ris import UndefinedClientError


class MonolithCommand:
    """Monolith class command"""

    def __init__(self):
        self.ident = {
            "name": "monolith",
            "usage": None,
            "description": "Displays entire cached data structure available",
            "summary": "displays entire cached data structure available",
            "aliases": ["mono"],
            "auxcommands": [],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """Main monolith worker function

        :param line: string of arguments passed in
        :type line: str.
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

        if hasattr(self.rdmc.app, "config") and self.rdmc.app.config._ac__format.lower() == "json":
            options.json = True

        if self.rdmc.app.current_client:
            results = self.rdmc.app.monolith.capture(redmono=options.redmono)
        else:
            raise UndefinedClientError()

        if options.filename:
            with open(options.filename[0], "w") as monolith:
                if options.json:
                    json.dump(results, monolith, indent=2, cls=JSONEncoder)
                else:
                    monolith.write(str(results))

        elif options.json:
            UI().print_out_json(results)  # .reduce())
        else:
            UI().print_out_human_readable(results)  # .reduce())

        # Return code
        return ReturnCodes.SUCCESS

    def definearguments(self, customparser):
        """Wrapper function for new command main function

        :param customparser: command line input
        :type customparser: parser.
        """
        if not customparser:
            return

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
        customparser.add_argument(
            "-f",
            "--filename",
            dest="filename",
            help="Use this flag if you wish to save the monolith" " into a file with the given filename.",
            action="append",
            default=None,
        )
        customparser.add_argument(
            "-r",
            "--reduced",
            dest="redmono",
            action="store_true",
            help="Use this flag if you wish to save the reduced monolith" " into a file with the given filename.",
            default=False,
        )
