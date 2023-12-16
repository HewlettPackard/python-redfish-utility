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
""" RawHead Command for rdmc """

import json

import redfish

try:
    from rdmc_helper import InvalidCommandLineErrorOPTS, ReturnCodes
except ImportError:
    from ilorest.rdmc_helper import InvalidCommandLineErrorOPTS, ReturnCodes


class RawHeadCommand:
    """Raw form of the head command"""

    def __init__(self):
        self.ident = {
            "name": "rawhead",
            "usage": None,
            "description": "Run to to retrieve data from the "
            'passed in path\n\texample: rawhead "/redfish/v1/systems/'
            '(system ID)"\n',
            "summary": "Raw form of the HEAD command.",
            "aliases": [],
            "auxcommands": [],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """Main raw head worker function

        :param line: command line input
        :type line: string.
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

        self.headvalidation(options)

        if options.path.startswith('"') and options.path.endswith('"'):
            options.path = options.path[1:-1]

        results = self.rdmc.app.head_handler(options.path, silent=options.silent, service=options.service)

        content = None
        tempdict = dict()

        if results and results.status == 200:
            if results._http_response:
                content = results.getheaders()
            else:
                content = results._headers

            tempdict = dict(content)

            if options.filename:
                output = json.dumps(tempdict, indent=2, cls=redfish.ris.JSONEncoder, sort_keys=True)
                filehndl = open(options.filename[0], "w")
                filehndl.write(output)
                filehndl.close()

                self.rdmc.ui.printer("Results written out to '%s'.\n" % options.filename[0])
            else:
                if options.service:
                    self.rdmc.ui.printer("%s\n" % tempdict)
                else:
                    self.rdmc.ui.print_out_json(tempdict)
        else:
            return ReturnCodes.NO_CONTENTS_FOUND_FOR_OPERATION

        self.cmdbase.logout_routine(self, options)
        # Return code
        return ReturnCodes.SUCCESS

    def headvalidation(self, options):
        """Raw head validation function

        :param options: command line options
        :type options: list.
        """
        self.rdmc.login_select_validation(self, options, skipbuild=True)

    def definearguments(self, customparser):
        """Wrapper function for new command main function

        :param customparser: command line input
        :type customparser: parser.
        """
        if not customparser:
            return

        self.cmdbase.add_login_arguments_group(customparser)

        customparser.add_argument(
            "path",
            help="Uri on iLO to query HEAD.",
        )
        customparser.add_argument(
            "--silent",
            dest="silent",
            action="store_true",
            help="""Use this flag to silence responses""",
            default=None,
        )
        customparser.add_argument(
            "-f",
            "--filename",
            dest="filename",
            help="""Use the provided filename to perform operations.""",
            action="append",
            default=None,
        )
        customparser.add_argument(
            "--service",
            dest="service",
            action="store_true",
            help="""Use this flag to enable service mode and increase the function speed""",
            default=False,
        )
