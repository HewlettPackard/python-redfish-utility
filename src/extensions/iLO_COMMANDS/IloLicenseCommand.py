###
# Copyright 2016-2022 Hewlett Packard Enterprise, Inc. All rights reserved.
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
""" Add License Command for rdmc """

try:
    from rdmc_helper import (
        IncompatibleiLOVersionError,
        InvalidCommandLineErrorOPTS,
        PathUnavailableError,
        ReturnCodes,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        ReturnCodes,
        InvalidCommandLineErrorOPTS,
        PathUnavailableError,
        IncompatibleiLOVersionError,
    )

from redfish.ris import rmc_helper


class IloLicenseCommand:
    """Add an iLO license to the server"""

    def __init__(self):
        self.ident = {
            "name": "ilolicense",
            "usage": None,
            "description": "Set an iLO license on the current logged in server.\n\t",
            "summary": "Adds an iLO license key to the currently logged in server.",
            "aliases": [],
            "auxcommands": [],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """Main ilolicense Function

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
                raise InvalidCommandLineErrorOPTS("Provide required argument")

        self.addlicensevalidation(options)

        code = self.ilolicenseworkerfunction(options, args)

        self.cmdbase.logout_routine(self, options)
        # Return code
        return code

    def ilolicenseworkerfunction(self, options, args):
        """
        Ilolicense worker function. It calls appropriate function.
        :param options: command line options
        :type options: list.
        :param args: command line args
        :type args: string.
        """
        path = self.rdmc.app.typepath.defs.addlicensepath
        if options.check_license:
            self.check_license(options, path)
            return ReturnCodes.SUCCESS
        if options.check_state:
            if self.rdmc.app.typepath.defs.isgen10:
                result = self.get_license(options, path)
                state = result.dict["ConfirmationRequest"]["EON"]["State"]
                self.rdmc.ui.print_out_json("State: " + state)
                if state == "confirmed":
                    self.rdmc.ui.printer("License is confirmed\n")
                if state == "unconfirmed":
                    self.rdmc.ui.printer("License is not confirmed\n")
                if state == "unlicensed":
                    self.rdmc.ui.printer("Server is unlicensed\n")
                if state == "evaluation":
                    self.rdmc.ui.printer("Server is in evaluation mode\n")
                return ReturnCodes.SUCCESS
            else:
                self.rdmc.ui.printer("Feature supported only for Gen 10 and above\n")
                return ReturnCodes.SUCCESS
        if options.license_key:
            return_code = self.license_key(options, path, args)
            return return_code
        if options.uninstall_license:
            return_code = self.uninstall_license(options, path)
            return return_code
        if (
            len(args) == 0
            and options.license_key is None
            and options.check_license is None
            and options.check_state is False
            and options.uninstall_license is False
        ):
            result = self.get_license(options, path)
            self.print_license_info(result.dict)
            return ReturnCodes.SUCCESS
        if (
            len(args) == 1
            and options.license_key is None
            and options.check_license is None
            and options.check_state is False
            and options.uninstall_license is False
        ):
            return_code = self.license_key(options, path, args)
            return return_code

    def print_license_info(self, results):
        """
        Prints the license info
        """
        for key, value in results.items():
            if "@odata" not in key:
                if type(value) is dict:
                    self.print_license_info(value)
                else:
                    self.rdmc.ui.printer(key + ":" + str(value) + "\n")

    def uninstall_license(self, options, path):
        """
        Deletes the license
        """
        if self.rdmc.app.typepath.defs.isgen10:
            path = path + "1/"
        else:
            path = path + "/1"
        try:
            results = self.rdmc.app.delete_handler(path, silent=True)
            if results.status == 404:
                raise PathUnavailableError("License is not installed")
                # return ReturnCodes.SUCCESS
            if results.status == 403:
                self.rdmc.ui.error("Insufficient Privilege to uninstall license")
                return ReturnCodes.RIS_MISSING_ID_TOKEN
            if results.status == 400:
                self.rdmc.ui.printer("There is no license available to uninstall\n")
                return ReturnCodes.SUCCESS
            if results.status == 200:
                self.rdmc.ui.printer("Uninstalled license successfully\n")
                return ReturnCodes.SUCCESS
        except rmc_helper.IloLicenseError:
            self.rdmc.ui.error("Error Occured while Uninstall")
            return ReturnCodes.ILO_LICENSE_ERROR
        except IncompatibleiLOVersionError:
            self.rdmc.ui.error("iLO FW version on this server doesnt support this operation")
            return ReturnCodes.INCOMPATIBLE_ILO_VERSION_ERROR

    def license_key(self, options, path, args):
        """
        Installs the license
        """
        if options.license_key is not None:
            if options.license_key[0] is not None:
                body = {"LicenseKey": "%s" % options.license_key[0]}
            else:
                self.rdmc.ui.printer("Provide license key to install\n")
        if len(args) == 1 and options.license_key is None:
            body = {"LicenseKey": "%s" % args[0]}
        try:
            results = self.rdmc.app.post_handler(path, body)
            if results.status == 201:
                return ReturnCodes.SUCCESS
        except rmc_helper.IloLicenseError:
            self.rdmc.ui.error("Error Occured while install")
            return ReturnCodes.ILO_LICENSE_ERROR
        except rmc_helper.IdTokenError:
            self.rdmc.ui.error("Insufficient Privilege to update license")
            return ReturnCodes.RIS_MISSING_ID_TOKEN

    def check_license(self, options, path):
        """
        Checks and Displays the license
        """
        if self.rdmc.app.typepath.defs.isgen10:
            if options.check_license[0] is not None:
                result = self.get_license(options, path)

                if result.dict["ConfirmationRequest"]["EON"]["LicenseKey"] == options.check_license[0]:
                    self.rdmc.ui.printer("Matched. Provided key is installed on this server\n")
                else:
                    self.rdmc.ui.printer("Provided key is not installed on this server\n")
            else:
                self.rdmc.ui.printer("Provide license key to check\n")
        else:
            self.rdmc.ui.printer("Feature supported only on gen 10 and above\n")

    def get_license(self, options, path):
        """
        Gets the license
        """
        if self.rdmc.app.typepath.defs.isgen10:
            path = path + "1/"
        else:
            path = path + "/1"
        results = self.rdmc.app.get_handler(path, silent=True)
        if results.status == 200:
            return results

    def addlicensevalidation(self, options):
        """ilolicense validation function

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
            "--install",
            dest="license_key",
            action="append",
            help="""Installs the given normal or premium license""",
            default=None,
        )
        customparser.add_argument(
            "--uninstall",
            help="""Deletes the installed license""",
            action="store_true",
            dest="uninstall_license",
        )
        customparser.add_argument(
            "--check",
            dest="check_license",
            help="""Lists the specified license""",
            action="append",
            default=None,
        )
        customparser.add_argument(
            "--check_confirm",
            dest="check_state",
            action="store_true",
            help="Checks the confirmed state and displays it",
        )
