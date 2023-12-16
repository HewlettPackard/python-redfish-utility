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
""" RawGet Command for rdmc """

import json

import redfish

try:
    from rdmc_helper import (
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        ResourceNotReadyError,
        ReturnCodes,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        ResourceNotReadyError,
        ReturnCodes,
    )


class RawGetCommand:
    """Raw form of the get command"""

    def __init__(self):
        self.ident = {
            "name": "rawget",
            "usage": None,
            "description": "Run to to retrieve data from "
            'the passed in path.\n\tExample: rawget "/redfish/v1/'
            'systems/(system ID)"',
            "summary": "Raw form of the GET command.",
            "aliases": [],
            "auxcommands": [],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """Main raw get worker function

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

        headers = {}

        if hasattr(options, "sessionid") and options.sessionid:
            _ = self.sessionvalidation(options)
        else:
            self.getvalidation(options)

        if options.path.endswith("?=."):
            path = options.path
            strip = path[:-3]
            options.path = strip + "?$expand=."

        if options.path.startswith('"') and options.path.endswith('"'):
            options.path = options.path[1:-1]

        if options.expand:
            options.path = options.path + "?$expand=."

        if options.headers:
            extraheaders = options.headers.split(",")
            for item in extraheaders:
                header = item.split(":")

                try:
                    headers[header[0]] = header[1]
                except:
                    InvalidCommandLineError("Invalid format for --headers " "option.")

        returnresponse = False
        if options.response or options.getheaders:
            returnresponse = True

        extra_path = None
        if "#" in options.path:
            path_list = options.path.split("#")
            options.path = path_list[0]
            extra_path = path_list[1]
            if "/" in extra_path:
                extra_path_list = extra_path.split("/")
                extra_path_list = list(filter(None, extra_path_list))

        results = self.rdmc.app.get_handler(
            options.path,
            sessionid=options.sessionid,
            headers=headers,
            silent=options.silent,
            service=options.service,
            username=options.user,
            password=options.password,
            base_url=options.url,
        )
        result = None
        if results.dict:
            if extra_path:
                result = results.dict
                for p in extra_path_list:
                    if p.isdigit():
                        p = int(p)
                    result = result[p]
            else:
                result = results.dict

        if results and results.status == 200 and options.binfile:
            output = results.read
            filehndl = open(options.binfile[0], "wb")
            filehndl.write(output)
            filehndl.close()
        elif results and returnresponse:
            if options.getheaders:
                self.rdmc.ui.printer(json.dumps(dict(results.getheaders())) + "\n")
            if options.response:
                self.rdmc.ui.printer(results.read + "\n")
        elif results and results.status == 200:
            if results.dict:
                if options.filename:
                    output = json.dumps(
                        result,
                        indent=2,
                        cls=redfish.ris.JSONEncoder,
                        sort_keys=True,
                    )

                    filehndl = open(options.filename[0], "w")
                    filehndl.write(output)
                    filehndl.close()

                    self.rdmc.ui.printer("Results written out to '%s'.\n" % options.filename[0])
                else:
                    if not result:
                        result = results.dict
                    if options.service:
                        self.rdmc.ui.printer("%s\n" % result)
                    else:
                        self.rdmc.ui.print_out_json(result)
        else:
            json_payload = json.loads(results._http_response.data)
            try:
                message_id = json_payload["error"]["@Message.ExtendedInfo"][0]["MessageId"]
                self.rdmc.ui.error("%s" % message_id)
                if "ResourceNotReadyRetry" in message_id:
                    raise ResourceNotReadyError("Resources are not ready in iLO, Please wait for some time and retry")
            except:
                self.rdmc.ui.error("An invalid or incomplete response was received: %s\n" % json_payload)
            return ReturnCodes.NO_CONTENTS_FOUND_FOR_OPERATION

        self.cmdbase.logout_routine(self, options)
        # Return code
        return ReturnCodes.SUCCESS

    def getvalidation(self, options):
        """Raw get validation function

        :param options: command line options
        :type options: list.
        """
        self.rdmc.login_select_validation(self, options, skipbuild=True)

    def sessionvalidation(self, options):
        """Raw patch session validation function

        :param options: command line options
        :type options: list.
        """

        url = None
        if options.user or options.password or options.url:
            if options.url:
                url = options.url
        else:
            if self.rdmc.app.redfishinst and self.rdmc.app.redfishinst.base_url:
                url = self.rdmc.app.redfishinst.base_url
        if url and "blobstore://" not in url and "https://" not in url:
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
            help="Uri on iLO",
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
            help="Use this flag to add extra headers to the request." " example: --headers=HEADER:VALUE,HEADER:VALUE",
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
            "-f",
            "--filename",
            dest="filename",
            help="""Write results to the specified file.""",
            action="append",
            default=None,
        )
        customparser.add_argument(
            "-b",
            "--writebin",
            dest="binfile",
            help="""Write the results to the specified file in binary.""",
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
        customparser.add_argument(
            "--expand",
            dest="expand",
            action="store_true",
            help="""Use this flag to expand the path specified using the """ """expand notation '?$expand=.'""",
            default=False,
        )
