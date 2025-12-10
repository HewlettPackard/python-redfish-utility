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
"""ExportAllConfig Command for rdmc"""

import json

try:
    from rdmc_helper import InvalidCommandLineErrorOPTS, ReturnCodes
except ImportError:
    from ilorest.rdmc_helper import InvalidCommandLineErrorOPTS, ReturnCodes
from redfish.ris import UndefinedClientError


class ExportAllConfigCommand:
    """exportallconfig class command"""

    def __init__(self):
        self.ident = {
            "name": "exportallconfig",
            "usage": None,
            "description": "Saves all the config on to json file",
            "summary": "Saves all the config on to json file. Usage: exportallconfig -f filename.json",
            "aliases": ["allconfig"],
            "auxcommands": [],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """Main exportallconfig worker function

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
        if not options.excludeurl:
            options.excludeurl = "nothing to exclude"

        if self.rdmc.app.current_client:
            results = self.rdmc.app.monolith.captureallconfig(exclueurl=options.excludeurl[0])
        else:
            raise UndefinedClientError()

        filepath = options.filename[0] if options.filename else "AllConfig.json"

        with open(filepath, "w") as allconfig:
            json.dump(results, allconfig, indent=2)
            self.rdmc.ui.printer("File is loaded successfully.\n")

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
            "-f",
            "--filename",
            dest="filename",
            help="Use this flag if you wish to save the content to a file, "
            "if no file given it will get saved to AllConfig.json",
            action="append",
            default=None,
        )
        customparser.add_argument(
            "-e",
            "--excludeurl",
            dest="excludeurl",
            action="append",
            help="Use this flag is given with a url that url will be skipped",
            default=None,
        )
