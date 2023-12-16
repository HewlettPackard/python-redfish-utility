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
""" Clear Controller Configuration Command for rdmc """

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


class ClearControllerConfigCommand:
    """Drive erase/sanitize command"""

    def __init__(self):
        self.ident = {
            "name": "clearcontrollerconfig",
            "usage": None,
            "description": "To clear a controller"
            " config.\n\tExample: clearcontrollerconfig --controller=1"
            '\n\texample: clearcontrollerconfig --controller="Slot0"',
            "summary": "Clears smart array controller configuration.",
            "aliases": [],
            "auxcommands": ["SelectCommand"],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """Main disk inventory worker function

        :param line: command line input
        :type line: string.
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

        self.clearcontrollerconfigvalidation(options)

        ilo_ver = self.rdmc.app.getiloversion()
        if ilo_ver >= 6.110:
            self.rdmc.ui.printer(
                "ClearController option is not supported for this device."
                "\nUse factoryresetcontroller command to reset the controller,"
                "\tthe action does erase or sanitize data on the drives.\n"
            )
            self.cmdbase.logout_routine(self, options)
            # Return code
            return ReturnCodes.SUCCESS

        else:
            self.auxcommands["select"].selectfunction("SmartStorageConfig.")
            content = self.rdmc.app.getprops()

            if not options.controller:
                raise InvalidCommandLineError("You must include a controller to select.")
            if options.controller:
                controllist = []
                contentsholder = {
                    "LogicalDrives": [],
                    "Actions": [{"Action": "ClearConfigurationMetadata"}],
                    "DataGuard": "Disabled",
                }
                try:
                    if options.controller.isdigit():
                        slotlocation = self.get_location_from_id(options.controller)
                        if slotlocation:
                            slotcontrol = slotlocation.lower().strip('"').split("slot")[-1].lstrip()
                            for control in content:
                                if slotcontrol.lower() == control["Location"].lower().split("slot")[-1].lstrip():
                                    controllist.append(control)
                    elif "slot" in options.controller.lower():
                        controllerid = options.controller.strip("Slot ")
                        slotlocation = self.get_location_from_id(controllerid)
                        if slotlocation:
                            slotcontrol = slotlocation.lower().strip('"').split("slot")[-1].lstrip()
                            for control in content:
                                if slotcontrol.lower() == control["Location"].lower().split("slot")[-1].lstrip():
                                    controllist.append(control)
                    if not controllist:
                        raise InvalidCommandLineError("")
                except InvalidCommandLineError:
                    raise InvalidCommandLineError("Selected controller not found in the current " "inventory list.")
                for controller in controllist:
                    # self.rdmc.ui.printer(
                    #    "ClearController path and payload: %s, %s\n"
                    #    % (controller["@odata.id"], contentsholder)
                    # )
                    self.rdmc.app.put_handler(controller["@odata.id"], contentsholder)

            self.cmdbase.logout_routine(self, options)
            # Return code
            return ReturnCodes.SUCCESS

    def get_storage_location_from_id(self, storage_id):
        for sel in self.rdmc.app.select("StorageController", path_refresh=True):
            if "Collection" not in sel.maj_type:
                controller_storage = sel.dict
                if controller_storage["Id"] == str(storage_id):
                    return controller_storage["Location"]["PartLocation"]["ServiceLabel"]
        return None

    def get_location_from_id(self, controller_id):
        for sel in self.rdmc.app.select("SmartStorageArrayController", path_refresh=True):
            if "Collection" not in sel.maj_type:
                controller = sel.dict
                if controller["Id"] == str(controller_id):
                    return controller["Location"]
        return None

    def clearcontrollerconfigvalidation(self, options):
        """clear controller config validation function

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
            "--controller",
            dest="controller",
            help="Use this flag to select the corresponding controller " "using either the slot number or index.",
            default=None,
        )
