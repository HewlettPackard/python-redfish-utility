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

from redfish.ris.resp_handler import ResponseHandler

try:
    from rdmc_helper import (
        ReturnCodes,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        FirmwareUpdateError,
        NoContentsFoundForOperationError,
        Encryption,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        ReturnCodes,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        FirmwareUpdateError,
        NoContentsFoundForOperationError,
        Encryption,
    )


class FirmwareUpdateCommand:
    """Reboot server that is currently logged in"""

    def __init__(self):
        self.ident = {
            "name": "firmwareupdate",
            "usage": None,
            "description": "Apply a firmware "
            "update to the current logged in server.\n\texample: "
            "firmwareupdate <url/hostname>/images/image.bin",
            "summary": "Perform a firmware update on the currently logged in server.",
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
            if not line or line[0] == "help":
                self.parser.print_help()
                return ReturnCodes.SUCCESS
        except (InvalidCommandLineErrorOPTS, SystemExit):
            if ("-h" in line) or ("--help" in line):
                return ReturnCodes.SUCCESS
            else:
                raise InvalidCommandLineErrorOPTS("")

        if len(args) == 1:
            self.firmwareupdatevalidation(options)
        else:
            raise InvalidCommandLineError(
                "Invalid number of parameters."
                " Firmware update takes exactly 1 parameter."
            )

        if args[0].startswith('"') and args[0].endswith('"'):
            args[0] = args[0][1:-1]

        action = None
        uri = "FirmwareURI"

        select = self.rdmc.app.typepath.defs.hpilofirmwareupdatetype
        results = self.rdmc.app.select(selector=select)

        try:
            results = results[0]
        except:
            pass

        if results:
            update_path = results.resp.request.path
        else:
            raise NoContentsFoundForOperationError("Unable to find %s" % select)

        bodydict = results.resp.dict

        try:
            for item in bodydict["Actions"]:
                if self.rdmc.app.typepath.defs.isgen10:
                    if "SimpleUpdate" in item:
                        action = item.split("#")[-1]

                    uri = "ImageURI"
                    options.tpmenabled = False
                elif "InstallFromURI" in item:
                    action = "InstallFromURI"

                if action:
                    put_path = bodydict["Actions"][item]["target"]
                    break
        except:
            put_path = update_path
            action = "Reset"

        if options.tpmenabled:
            body = {"Action": action, uri: args[0], "TPMOverrideFlag": True}
        else:
            body = {"Action": action, uri: args[0]}

        self.rdmc.app.post_handler(put_path, body, silent=True, service=True)

        self.rdmc.ui.printer("\nStarting upgrade process...\n\n")

        self.showupdateprogress(update_path)
        # logoutobj.run("")

        self.cmdbase.logout_routine(self, options)
        # Return code
        return ReturnCodes.SUCCESS

    def showupdateprogress(self, path):
        """handler function for updating the progress

        :param path: path to update service.
        :tyep path: str
        """
        counter = 0
        written = False
        uploadingpost = False
        spinner = ["|", "/", "-", "\\"]
        position = 0

        while True:
            if counter == 100:
                raise FirmwareUpdateError("Error occurred while updating the firmware.")
            else:
                counter += 1

            results = self.rdmc.app.get_handler(path, silent=True)
            results = results.dict
            try:
                results = results["Oem"]["Hpe"]
            except:
                pass

            if not results:
                raise FirmwareUpdateError(
                    "Unable to contact Update Service. " "Please re-login and try again."
                )

            if results["State"].lower().startswith("idle"):
                time.sleep(2)
            elif results["State"].lower().startswith("uploading"):
                counter = 0

                if not uploadingpost:
                    uploadingpost = True
                else:
                    if not written:
                        written = True
                        self.rdmc.ui.printer(
                            "iLO is uploading the necessary files. Please wait..."
                        )

                time.sleep(0.5)
            elif (
                results["State"]
                .lower()
                .startswith(("progressing", "updating", "verifying", "writing"))
            ):
                counter = 0

                for _ in range(2):
                    if position < 4:
                        self.rdmc.ui.printer("Updating: " + spinner[position] + "\r")
                        position += 1
                        time.sleep(0.1)
                    else:
                        position = 0
                        self.rdmc.ui.printer("Updating: " + spinner[position] + "\r")
                        position += 1
                        time.sleep(0.1)
            elif results["State"].lower().startswith("complete"):
                self.rdmc.ui.printer(
                    "\n\nFirmware update has completed and iLO"
                    " may reset. \nIf iLO resets the"
                    " session will be terminated.\nPlease wait"
                    " for iLO to initialize completely before"
                    " logging in again.\nA reboot may be required"
                    " for firmware changes to take effect.\n"
                )
                break
            elif results["State"].lower().startswith("error"):
                error = self.rdmc.app.get_handler(path, silent=True)
                self.printerrmsg(error)

    def printerrmsg(self, error):
        """raises and prints the detailed error message if possible"""
        output = "Error occurred while updating the firmware."

        try:
            error = error.dict["Oem"]["Hpe"]["Result"]["MessageId"].split(".")
            # TODO: Update to new ResponseHandler Method 'return_reg'
            errmessages = ResponseHandler(
                self.rdmc.app.validation_manager,
                self.rdmc.app.typepath.defs.messageregistrytype,
            ).get_error_messages()
            for messagetype in list(errmessages.keys()):
                if error[0] == messagetype:
                    if errmessages[messagetype][error[-1]]["NumberOfArgs"] == 0:
                        output = (
                            "Firmware update error. %s"
                            % errmessages[messagetype][error[-1]]["Message"]
                        )
                    else:
                        output = (
                            "Firmware update error. %s"
                            % errmessages[messagetype][error[-1]]["Description"]
                        )
                    break
        except:
            pass

        raise FirmwareUpdateError(output)

    def firmwareupdatevalidation(self, options):
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
            "--tpmenabled",
            dest="tpmenabled",
            action="store_true",
            help="Use this flag if the server you are currently logged into"
            " has a TPM chip installed.",
            default=False,
        )
