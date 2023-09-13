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
""" SendTest Command for rdmc """

try:
    from rdmc_helper import (
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        NoContentsFoundForOperationError,
        ReturnCodes,
    )
except:
    from ilorest.rdmc_helper import (
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        NoContentsFoundForOperationError,
        ReturnCodes,
    )


class SendTestCommand:
    """Send syslog test to the logged in server"""

    def __init__(self):
        self.ident = {
            "name": "sendtest",
            "usage": None,
            "description": "Send syslog test to the "
            "current logged in server.\n\tExample: sendtest syslog\n\n"
            "\tSend alert mail test to the current logged in server.\n\t"
            "sendtest alertmail\n\n\tSend SNMP test alert "
            "to the current logged in server.\n\texample: sendtest snmpalert",
            "summary": "Command for sending various tests to iLO.",
            "aliases": [],
            "auxcommands": [],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """Main SentTestCommand function

        :param line: string of arguments passed in
        :type line: str.
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

        if not len(args) == 1:
            raise InvalidCommandLineError("sendtest command takes only one argument.")

        body = None
        path = None
        actionitem = None

        self.sendtestvalidation(options)

        if args[0].lower() == "snmpalert":
            select = self.rdmc.app.typepath.defs.snmpservice
            actionitem = "SendSNMPTestAlert"
        elif args[0].lower() == "alertmail":
            select = self.rdmc.app.typepath.defs.managernetworkservicetype
            actionitem = "SendTestAlertMail"
        elif args[0].lower() == "syslog":
            select = self.rdmc.app.typepath.defs.managernetworkservicetype
            actionitem = "SendTestSyslog"
        else:
            raise InvalidCommandLineError("sendtest command does not have " "parameter %s." % args[0])

        results = self.rdmc.app.select(selector=select)

        try:
            results = results[0]
        except:
            pass

        if results:
            path = results.resp.request.path
        else:
            raise NoContentsFoundForOperationError("%s not found.It may not " "be available on this system." % select)

        bodydict = results.resp.dict

        try:
            if "Actions" in bodydict:
                for item in bodydict["Actions"]:
                    if actionitem in item:
                        if self.rdmc.app.typepath.defs.isgen10:
                            actionitem = item.split("#")[-1]

                        path = bodydict["Actions"][item]["target"]
                        break
            else:
                for item in bodydict["Oem"][self.rdmc.app.typepath.defs.oemhp]["Actions"]:
                    if actionitem in item:
                        if self.rdmc.app.typepath.defs.isgen10:
                            actionitem = item.split("#")[-1]

                        path = bodydict["Oem"][self.rdmc.app.typepath.defs.oemhp]["Actions"][item]["target"]
                        break

            body = {"Action": actionitem}
        except:
            body = {"Action": actionitem, "Target": "/Oem/Hp"}

        self.rdmc.app.post_handler(path, body)

        self.cmdbase.logout_routine(self, options)
        # Return code
        return ReturnCodes.SUCCESS

    def sendtestvalidation(self, options):
        """sendtestvalidation method validation function

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
