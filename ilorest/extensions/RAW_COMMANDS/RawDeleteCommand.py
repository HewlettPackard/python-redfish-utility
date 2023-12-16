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
""" RawDelete Command for rdmc """

import sys

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


class RawDeleteCommand:
    """Raw form of the delete command"""

    def __init__(self):
        self.ident = {
            "name": "rawdelete",
            "usage": None,
            "description": "Run to to delete data from"
            ' the passed in path.\n\texample: rawdelete "/redfish/v1/'
            'Sessions/(session ID)"\n',
            "summary": "Raw form of the DELETE command.",
            "aliases": [],
            "auxcommands": [],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """Main raw delete worker function

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
                raise InvalidCommandLineErrorOPTS("")

        headers = {}

        if hasattr(options, "sessionid") and options.sessionid:
            self.sessionvalidation(options)
        else:
            self.deletevalidation(options)

        if options.path.startswith('"') and options.path.endswith('"'):
            options.path = options.path[1:-1]

        if options.expand:
            options.path = options.path + "?$expand=."

        try:
            currentsess = self.rdmc.app.current_client.session_location
        except:
            currentsess = None

        if options.headers:
            extraheaders = options.headers.split(",")

            for item in extraheaders:
                header = item.split(":")

                try:
                    headers[header[0]] = header[1]
                except:
                    InvalidCommandLineError("Invalid format for --headers option.")

        if currentsess and (options.path in currentsess):
            self.rdmc.app.logout()
            self.rdmc.ui.printer(
                "Your session has been terminated (deleted).\nPlease log " "back in if you wish to continue.\n"
            )
        else:
            returnresponse = False

            if options.response or options.getheaders:
                returnresponse = True

            results = self.rdmc.app.delete_handler(
                options.path,
                headers=headers,
                silent=options.silent,
                service=options.service,
            )

            if returnresponse and results:
                if options.getheaders:
                    self.rdmc.ui.print_out_json(dict(results.getheaders()))

                if options.response:
                    sys.stdout.write(results.read)
                    self.rdmc.ui.printer("\n")
            elif results.status == 404:
                return ReturnCodes.NO_CONTENTS_FOUND_FOR_OPERATION
            elif results.status != 200:
                return ReturnCodes.UI_CLI_USAGE_EXCEPTION

        self.cmdbase.logout_routine(self, options)
        # Return code
        return ReturnCodes.SUCCESS

    def deletevalidation(self, options):
        """Raw delete validation function

        :param options: command line options
        :type options: list.
        """
        self.rdmc.login_select_validation(self, options, skipbuild=True)

    def sessionvalidation(self, options):
        """Raw delete session validation function

        :param options: command line options
        :type options: list.
        """

        url = None
        if options.user or options.password or options.url:
            if options.url:
                url = options.url
        else:
            if self.rdmc.app.config.get_url():
                url = self.rdmc.app.config.get_url()
        if url and "https://" not in url:
            url = "https://" + url

        return url

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
            help="Uri on iLO to be deleted.",
        )
        customparser.add_argument(
            "--response",
            dest="response",
            action="store_true",
            help="Use this flag to return the iLO response body.",
            default=False,
        )
        customparser.add_argument(
            "--getheaders",
            dest="getheaders",
            action="store_true",
            help="Use this flag to return the iLO response headers.",
            default=False,
        )
        customparser.add_argument(
            "--headers",
            dest="headers",
            help="Use this flag to add extra headers to the request."
            "\t\t\t\t\t Usage: --headers=HEADER:VALUE,HEADER:VALUE",
            default=None,
        )
        customparser.add_argument(
            "--silent",
            dest="silent",
            action="store_true",
            help="""Use this flag to silence responses""",
            default=False,
        )
        customparser.add_argument(
            "--service",
            dest="service",
            action="store_true",
            help="""Use this flag to enable service mode and increase the function speed""",
            default=False,
        )
        customparser.add_argument(
            "--expand",
            dest="expand",
            action="store_true",
            help="""Use this flag to expand the path specified using the """ """expand notation '?$expand=.'""",
            default=False,
        )
