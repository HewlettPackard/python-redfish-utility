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
""" Factory Defaults Command for rdmc """
import time
from collections import OrderedDict

import colorama
from six.moves import input

try:
    from rdmc_helper import (
        IncompatibleiLOVersionError,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        NoContentsFoundForOperationError,
        ReturnCodes,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        IncompatibleiLOVersionError,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        NoContentsFoundForOperationError,
        ReturnCodes,
    )

CURSOR_UP_ONE = "\x1b[1A"
ERASE_LINE = "\x1b[2K"


class OneButtonEraseCommand:
    """Backup and restore server using iLO's .bak file"""

    def __init__(self):
        self.ident = {
            "name": "onebuttonerase",
            "usage": None,
            "description": "Erase all iLO settings, Bios settings, User Data, and iLO Repository data."
            "\n\tExample: onebuttonerase\n\n\tSkip the confirmation before"
            " erasing system data.\n\texample: onebuttonerase --confirm\n\nWARNING: This "
            "command will erase user data! Use with extreme caution! Complete erase can take"
            " up to 24 hours to complete.",
            "summary": "Performs One Button Erase on a system.",
            "aliases": [],
            "auxcommands": ["RebootCommand"],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """Main onebuttonerase function

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

        if args:
            raise InvalidCommandLineError("onebuttonerase command takes no arguments.")

        self.onebuttonerasevalidation(options)

        select = "ComputerSystem."
        results = self.rdmc.app.select(selector=select)

        if self.rdmc.app.getiloversion() < 5.140:
            raise IncompatibleiLOVersionError("One Button Erase is only available on iLO 5 1.40 " "and greater.")
        try:
            results = results[0].dict
        except:
            raise NoContentsFoundForOperationError("Unable to find %s" % select)

        if (
            results["Oem"]["Hpe"]["SystemROMAndiLOEraseStatus"] == "Idle"
            and results["Oem"]["Hpe"]["UserDataEraseStatus"] == "Idle"
        ):
            post_path = None
            body_dict = {"SystemROMAndiLOErase": True, "UserDataErase": True}
            for item in results["Oem"]["Hpe"]["Actions"]:
                if "SecureSystemErase" in item:
                    post_path = results["Oem"]["Hpe"]["Actions"][item]["target"]
                    break

            if options.confirm:
                userresp = "erase"
            else:
                userresp = input(
                    'Please type "erase" to begin erase process. Any other input will'
                    " cancel the operation. If you wish to skip this prompt add the --confirm flag: "
                )

            if userresp == "erase":
                if post_path and body_dict:
                    self.rdmc.app.post_handler(post_path, body_dict)
                    self.rdmc.app.post_handler(
                        results["Actions"]["#ComputerSystem.Reset"]["target"],
                        {"ResetType": "ForceRestart"},
                    )
                    if not options.nomonitor:
                        self.monitor_erase(results["@odata.id"])
                    return ReturnCodes.SUCCESS
                else:
                    NoContentsFoundForOperationError("Unable to start One Button Erase.")
            else:
                self.rdmc.ui.printer("Canceling One Button Erase.\n")
                return ReturnCodes.SUCCESS
        else:
            self.rdmc.ui.warn("System is already undergoing a One Button Erase process...\n")
        if not options.nomonitor:
            self.monitor_erase(results["@odata.id"])

        self.cmdbase.logout_routine(self, options)
        # Return code
        return ReturnCodes.SUCCESS

    def monitor_erase(self, path):
        """Monitor the One Button Erase progress

        :param path: Path to the one button monitor path
        :type path: str.
        """
        print_dict = {
            "BIOSSettingsEraseStatus": "Bios Settings Erase:",
            "iLOSettingsEraseStatus": "iLO Settings Erase:",
            "ElapsedEraseTimeInMinutes": "Elapsed Time in Minutes:",
            "EstimatedEraseTimeInMinutes": "Estimated Remaining Time in Minutes:",
            "NVDIMMEraseStatus": "NVDIMM Erase:",
            "NVMeDrivesEraseStatus": "NVMe Drive Erase:",
            "SATADrivesEraseStatus": "SATA Drive Erase:",
            "TPMEraseStatus": "TPM Erase:",
            "SmartStorageEraseStatus": "Smart Storage Erase:",
            "SystemROMAndiLOEraseStatus": "Bios and iLO Erase:",
            "UserDataEraseStatus": "User Data Erase:",
        }
        colorama.init()

        self.rdmc.ui.printer("\tOne Button Erase Status\n")
        self.rdmc.ui.printer("==========================================================\n")
        results = self.rdmc.app.get_handler(path, service=True, silent=True)
        counter = 0
        eraselines = 0
        while True:
            if not (counter + 1) % 8:
                results = self.rdmc.app.get_handler(path, service=True, silent=True)
            print_data = self.gather_data(results.dict["Oem"]["Hpe"])

            self.reset_output(eraselines)

            for key in list(print_data.keys()):
                self.print_line(print_dict[key], print_data[key], counter)
            if counter == 7:
                counter = 0
            else:
                counter += 1
            if all(
                [
                    print_data[key].lower() in ["completedwithsuccess", "completedwitherrors", "failed"]
                    for key in list(print_data.keys())
                    if not key.lower() in ["elapsederasetimeinminutes", "estimatederasetimeinminutes"]
                ]
            ):
                break
            eraselines = len(list(print_data.keys()))
            time.sleep(0.5)
        colorama.deinit()
        options = {}
        self.cmdbase.logout_routine(self, options)

    def gather_data(self, resdict):
        """Gather information on current progress from response

        :param resdict: response dictionary to parse
        :type resdict: dict.
        """
        retdata = OrderedDict()
        data = [
            ("ElapsedEraseTimeInMinutes", None),
            ("EstimatedEraseTimeInMinutes", None),
            (
                "SystemROMAndiLOEraseComponentStatus",
                ["BIOSSettingsEraseStatus", "iLOSettingsEraseStatus"],
            ),
            (
                "UserDataEraseComponentStatus",
                [
                    "NVDIMMEraseStatus",
                    "NVMeDrivesEraseStatus",
                    "SATADrivesEraseStatus",
                    "SmartStorageEraseStatus",
                    "TPMEraseStatus",
                ],
            ),
        ]
        for key, val in data:
            if val:
                if key == "SystemROMAndiLOEraseComponentStatus":
                    try:
                        resdict[key]
                    except KeyError:
                        retdata["SystemROMAndiLOEraseStatus"] = resdict["SystemROMAndiLOEraseStatus"]
                elif key == "UserDataEraseComponentStatus":
                    try:
                        if not resdict[key]:
                            raise KeyError()
                    except KeyError:
                        retdata["UserDataEraseStatus"] = resdict["UserDataEraseStatus"]
                for item in val:
                    try:
                        retdata[item] = resdict[key][item]
                    except KeyError:
                        pass
            else:
                try:
                    retdata[key] = resdict[key]
                except KeyError:
                    pass

        return retdata

    def reset_output(self, numlines=0):
        """reset the output for the next print"""
        for _ in range(numlines):
            self.rdmc.ui.printer(CURSOR_UP_ONE)
            self.rdmc.ui.printer(ERASE_LINE)

    def print_line(self, pstring, value, ctr):
        """print the line from system monitoring"""
        pline = "%s %s" % (pstring, value)

        spinner = ["|", "/", "-", "\\"]
        if str(value).lower() in ["initiated", "inprogress"]:
            pline += "\t%s" % spinner[ctr % 4]
        pline += "\n"

        self.rdmc.ui.printer(pline)

    def onebuttonerasevalidation(self, options):
        """one button erase validation function

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
            "--nomonitor",
            dest="nomonitor",
            help="Optionally include this flag to skip monitoring of the one button erase process "
            "and simply trigger the operation.",
            action="store_true",
            default=False,
        )
        customparser.add_argument(
            "--confirm",
            dest="confirm",
            help="Optionally include this flag to skip the confirmation prompt before starting One"
            " Button Erase and begin the operation.",
            action="store_true",
            default=False,
        )
