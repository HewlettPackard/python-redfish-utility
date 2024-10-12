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
""" RawPut Command for rdmc """

import json
import re
import sys
from collections import OrderedDict

try:
    from rdmc_helper import (
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        InvalidFileFormattingError,
        InvalidFileInputError,
        ReturnCodes,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        InvalidFileFormattingError,
        InvalidFileInputError,
        ReturnCodes,
    )


class RawPutCommand:
    """Raw form of the put command"""

    def __init__(self):
        self.ident = {
            "name": "rawput",
            "usage": None,
            "description": "Run to send a post from "
            "the data in the input file.\n\tMultiple PUTs can be performed in sequence by "
            "\n\tadding more path/body key/value pairs.\n"
            "\n\texample: rawput rawput."
            'txt\n\n\tExample input file:\n\t{\n\t    "/redfish/'
            'v1/systems/(system ID)/bios/Settings/":\n\t    {\n\t'
            '\t"Attributes": {\n\t\t'
            '  "BaseConfig": "default"\n\t\t}\n\t    }\n\t}',
            "summary": "Raw form of the PUT command.",
            "aliases": [],
            "auxcommands": [],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """Main raw put worker function

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
        results = []

        if hasattr(options, "sessionid") and options.sessionid:
            self.sessionvalidation(options)
        else:
            self.putvalidation(options)

        contentsholder = None

        try:
            with open(options.path, "r") as _if:
                contentsholder = json.loads(_if.read(), object_pairs_hook=OrderedDict)
        except IOError:
            raise InvalidFileInputError(
                "File '%s' doesn't exist. " "Please create file by running 'save' command." % options.path
            )
        except ValueError:
            raise InvalidFileFormattingError("Input file '%s' was not " "formatted properly." % options.path)

        if options.headers:
            extraheaders = options.headers.split(",")

            for item in extraheaders:
                header = item.split(":")

                try:
                    headers[header[0]] = header[1]
                except:
                    raise InvalidCommandLineError("Invalid format for --headers option.")

        if "path" in contentsholder and "body" in contentsholder:
            results.append(
                self.rdmc.app.put_handler(
                    contentsholder["path"],
                    contentsholder["body"],
                    headers=headers,
                    silent=options.silent,
                    optionalpassword=options.biospassword,
                    service=options.service,
                )
            )
        elif all([re.match("^/(S+/?)+$", key) for key in contentsholder]):
            for path, body in contentsholder.items():
                results.append(
                    self.rdmc.app.put_handler(
                        path,
                        body,
                        headers=headers,
                        silent=options.silent,
                        optionalpassword=options.biospassword,
                        service=options.service,
                    )
                )
        else:
            raise InvalidFileFormattingError("Input file '%s' was not " "formatted properly." % options.path)

        returnresponse = False

        if options.response or options.getheaders:
            returnresponse = True

        if results and returnresponse:
            for result in results:
                if options.getheaders:
                    sys.stdout.write(json.dumps(dict(result.getheaders())) + "\n")

                if options.response:
                    if isinstance(result.read, bytes):
                        sys.stdout.write(result.read.decode("utf-8"))
                    else:
                        sys.stdout.write(result.read)
                    sys.stdout.write("\n")

        self.cmdbase.logout_routine(self, options)
        # Return code
        return ReturnCodes.SUCCESS

    def putvalidation(self, options):
        """Raw put validation function

        :param options: command line options
        :type options: list.
        """
        self.rdmc.login_select_validation(self, options, skipbuild=True)

    def sessionvalidation(self, options):
        """Raw put session validation function

        :param options: command line options
        :type options: list.
        """

        url = None
        if options.user or options.password or options.url:
            if options.url:
                url = options.url
        else:
            if getattr(self.rdmc.app.redfishinst, "base_url", False):
                url = self.rdmc.app.redfishinst.base_url
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
            help="Path to the JSON file containing the data to be patched.",
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
