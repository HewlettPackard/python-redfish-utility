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
""" Results Command for rdmc """

from redfish.ris.resp_handler import ResponseHandler
from redfish.ris.rmc_helper import EmptyRaiseForEAFP

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


class ResultsCommand:
    """Monolith class command"""

    def __init__(self):
        self.ident = {
            "name": "results",
            "usage": None,
            "description": "Run to show the results of the last" " changes after a server reboot.\n\texample: results",
            "summary": "Show the results of changes which require a server reboot.",
            "aliases": [],
            "auxcommands": ["LoginCommand", "SelectCommand"],
        }

        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """Gather results of latest BIOS change

        :param line: string of arguments passed in
        :type line: str.
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

        if args:
            raise InvalidCommandLineError("Results command does not take any arguments.")
        self.resultsvalidation(options)
        results = {}
        if self.rdmc.app.typepath.defs.biospath[-1] == "/":
            iscsipath = self.rdmc.app.typepath.defs.biospath + "iScsi/"
            bootpath = self.rdmc.app.typepath.defs.biospath + "Boot/"
        else:
            iscsipath = self.rdmc.app.typepath.defs.biospath + "/iScsi"
            bootpath = self.rdmc.app.typepath.defs.biospath + "/Boot"

        try:
            self.auxcommands["select"].selectfunction("SmartStorageConfig")
            smartarray = self.rdmc.app.getprops()
            sapaths = [path["@odata.id"].split("settings")[0] for path in smartarray]
        except:
            sapaths = None

        biosresults = self.rdmc.app.get_handler(self.rdmc.app.typepath.defs.biospath, service=True, silent=True)
        iscsiresults = self.rdmc.app.get_handler(iscsipath, service=True, silent=True)
        bootsresults = self.rdmc.app.get_handler(bootpath, service=True, silent=True)
        saresults = []
        if sapaths:
            saresults = [self.rdmc.app.get_handler(path, service=True, silent=True) for path in sapaths]
        try:
            results.update({"Bios:": biosresults.dict[self.rdmc.app.typepath.defs.biossettingsstring]["Messages"]})
        except Exception:
            results.update({"Bios:": None})

        try:
            results.update({"Iscsi:": iscsiresults.dict[self.rdmc.app.typepath.defs.biossettingsstring]["Messages"]})
        except:
            results.update({"Iscsi:": None})

        try:
            results.update({"Boot:": bootsresults.dict[self.rdmc.app.typepath.defs.biossettingsstring]["Messages"]})
        except:
            results.update({"Boot:": None})
        try:
            for result in saresults:
                loc = "SmartArray"
                if saresults.index(result) > 0:
                    loc += " %d:" % saresults.index(result)
                else:
                    loc += ":"
                results.update({loc: result.dict[self.rdmc.app.typepath.defs.biossettingsstring]["Messages"]})
        except:
            results.update({"SmartArray:": None})

        self.rdmc.ui.printer("Results of the previous reboot changes:\n\n")

        for result in results:
            self.rdmc.ui.printer("%s\n" % result)
            try:
                for msg in results[result]:
                    _ = ResponseHandler(
                        self.rdmc.app.validationmanager,
                        self.rdmc.app.typepath.defs.messageregistrytype,
                    ).message_handler(response_data=msg, message_text="", verbosity=0, dl_reg=False)
                    pass
            except EmptyRaiseForEAFP as exp:
                raise EmptyRaiseForEAFP(exp)
            except Exception:
                self.rdmc.ui.error("No messages found for %s.\n" % result[:-1])

        self.cmdbase.logout_routine(self, options)
        return ReturnCodes.SUCCESS

    def resultsvalidation(self, options):
        """Results method validation function

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
