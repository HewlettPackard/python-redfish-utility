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
""" Firmware Update Command for rdmc """

import time

try:
    from rdmc_helper import (
        IloLicenseError,
        IncompatibleiLOVersionError,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        ReturnCodes,
        TimeOutError,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        IloLicenseError,
        IncompatibleiLOVersionError,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        ReturnCodes,
        TimeOutError,
    )


class FirmwareIntegrityCheckCommand:
    """Reboot server that is currently logged in"""

    def __init__(self):
        self.ident = {
            "name": "fwintegritycheck",
            "usage": None,
            "description": "Perform a firmware "
            "integrity check on the current logged in server.\n\t"
            "example: fwintegritycheck\n\n\tPerform a firmware integrity check and "
            "return results of the check.\n\texmaple: fwintegritycheck --results",
            "summary": "Perform a firmware integrity check on the currently logged in server.",
            "aliases": [],
            "auxcommands": [],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """Main firmware update worker function

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
            raise InvalidCommandLineError("fwintegritycheck command takes no arguments")

        self.firmwareintegritycheckvalidation(options)
        if self.rdmc.app.typepath.defs.isgen9:
            raise IncompatibleiLOVersionError("fwintegritycheck command is " "only available on iLO 5.")

        licenseres = self.rdmc.app.select(selector="HpeiLOLicense.")
        try:
            licenseres = licenseres[0]
        except:
            pass
        if not licenseres.dict["LicenseFeatures"]["FWScan"]:
            raise IloLicenseError("This command is not available with this iLO license.\n")

        select = self.rdmc.app.typepath.defs.hpilofirmwareupdatetype
        results = self.rdmc.app.select(selector=select)

        try:
            results = results[0]
        except:
            pass

        bodydict = results.resp.dict

        path = bodydict["Oem"]["Hpe"]["Actions"]["#HpeiLOUpdateServiceExt.StartFirmwareIntegrityCheck"]["target"]

        self.rdmc.app.post_handler(path, {})

        if options.results:
            results_string = "Awaiting results of firmware integrity check..."
            self.rdmc.ui.printer(results_string)
            polling = 50
            found = False
            while polling > 0:
                if not polling % 5:
                    self.rdmc.ui.printer(".")
                get_results = self.rdmc.app.get_handler(bodydict["@odata.id"], service=True, silent=True)
                if get_results:
                    curr_time = time.strptime(bodydict["Oem"]["Hpe"]["CurrentTime"], "%Y-%m-%dT%H:%M:%SZ")
                    scan_time = time.strptime(
                        get_results.dict["Oem"]["Hpe"]["FirmwareIntegrity"]["LastScanTime"],
                        "%Y-%m-%dT%H:%M:%SZ",
                    )

                    if scan_time > curr_time:
                        self.rdmc.ui.printer(
                            "\nScan Result: %s\n"
                            % get_results.dict["Oem"]["Hpe"]["FirmwareIntegrity"]["LastScanResult"]
                        )
                        found = True
                        break

                    polling -= 1
                    time.sleep(1)
            if not found:
                self.rdmc.ui.error("\nPolling timed out before scan completed.\n")
                TimeOutError("")

        self.cmdbase.logout_routine(self, options)
        # Return code
        return ReturnCodes.SUCCESS

    def firmwareintegritycheckvalidation(self, options):
        """Firmware update method validation function

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
            "--results",
            dest="results",
            help="Optionally include this flag to show results of firmware integrity check.",
            default=False,
            action="store_true",
        )
