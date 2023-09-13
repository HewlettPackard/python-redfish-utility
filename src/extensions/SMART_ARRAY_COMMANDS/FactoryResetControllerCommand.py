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
""" Factory Reset Controller Command for rdmc """


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


class FactoryResetControllerCommand:
    """Factory reset controller command"""

    def __init__(self):
        self.ident = {
            "name": "factoryresetcontroller",
            "usage": None,
            "description": "Run without "
            "arguments for the current controller options.\n\texample: "
            "factoryresetcontroller\n\n\tTo factory reset a controller "
            "by index.\n\texample: factoryresetcontroller --controller=2"
            '\n\texample: factoryresetcontroller --controller="Slot 1" \n\n'
            "\tTo factory reset a controller on Gen11 server\n"
            "\texample: factoryresetcontroller --reset_type resetall --storageid DE000100\n"
            "\texample: factoryresetcontroller --reset_type preservevolumes --storageid DE000100\n",
            "summary": "Factory resets a controller by index or location.",
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

        self.frcontrollervalidation(options)

        ilo_ver = self.rdmc.app.getiloversion()
        if ilo_ver >= 6.110:
            if not options.storageid:
                raise InvalidCommandLineError(
                    "--storageid option is mandatory for iLO6 along with --controller option.\n"
                )
            if (
                (options.controller is not None)
                and (options.storageid is not None)
                and (options.reset_type is not None)
            ):
                raise InvalidCommandLineError("--controller is not supported in iLO6.")

            elif (options.storageid is not None) and (options.reset_type is not None):
                st_content = []
                self.auxcommands["select"].selectfunction("StorageCollection.")
                get_content = self.rdmc.app.getprops()
                for st_controller in get_content:
                    path = st_controller["Members"]
                    for mem in path:
                        for val in mem.values():
                            if "DE" in val and options.storageid in val:
                                getval = self.rdmc.app.get_handler(val, silent=True, service=True).dict
                                if options.storageid:
                                    if getval["Id"] == options.storageid:
                                        st_content.append(getval)
                                    else:
                                        raise InvalidCommandLineError(
                                            "Selected storage id not found in the current inventory " "list."
                                        )
                                else:
                                    st_content.append(getval)
                for st_controller in st_content:
                    path = st_controller["Actions"]["#Storage.ResetToDefaults"]["target"]

                    if options.reset_type.lower() == "resetall":
                        actionitem = "ResetAll"
                        body = {"ResetType": actionitem}
                    elif options.reset_type.lower() == "preservevolumes":
                        actionitem = "PreserveVolumes"
                        body = {"ResetType": actionitem}
                    else:
                        raise InvalidCommandLineError("Invalid command.")

                    # self.rdmc.ui.printer(
                    #    "FactoryReset path and payload: %s, %s\n"
                    #    % (path, body)
                    # )
                    self.rdmc.app.post_handler(path, body)
                    self.cmdbase.logout_routine(self, options)
                # Return code
                return ReturnCodes.SUCCESS

            elif (options.storageid is None) or (options.reset_type is None):
                raise InvalidCommandLineError("Invalid command\n" "--reset_type and --storageid is required")

        else:
            self.auxcommands["select"].selectfunction("SmartStorageConfig.")
            content = self.rdmc.app.getprops()
            if options.controller and options.reset_type is None and options.storageid is None:
                controllist = []

                try:
                    if options.controller and options.controller.isdigit():
                        slotlocation = self.get_location_from_id(options.controller)
                        if slotlocation:
                            slotcontrol = slotlocation.lower().strip('"').split("slot")[-1].lstrip()
                            for control in content:
                                if slotcontrol.lower() == control["Location"].lower().split("slot")[-1].lstrip():
                                    controllist.append(control)
                    # else:
                    #    self.parser.print_help()
                    #    return ReturnCodes.SUCCESS
                    if not controllist:
                        raise InvalidCommandLineError("")
                except InvalidCommandLineError:
                    raise InvalidCommandLineError("Selected controller not found in the current inventory " "list.")
                for controller in controllist:
                    contentsholder = {
                        "Actions": [{"Action": "FactoryReset"}],
                        "DataGuard": "Disabled",
                    }
                    self.rdmc.ui.printer(
                        "FactoryReset path and payload: %s, %s\n" % (controller["@odata.id"], contentsholder)
                    )
                    self.rdmc.app.patch_handler(controller["@odata.id"], contentsholder)

            elif options.controller and (options.reset_type is not None) or (options.storageid is not None):
                raise InvalidCommandLineError(
                    "Invalid command\n" "--reset_type and --storageid is not supported in iLO5"
                )

            for idx, val in enumerate(content):
                self.rdmc.ui.printer("[%d]: %s\n" % (idx, val["Location"]))

            self.cmdbase.logout_routine(self, options)
            # Return code
            return ReturnCodes.SUCCESS

    def get_location_from_id(self, controller_id):
        for sel in self.rdmc.app.select("SmartStorageArrayController", path_refresh=True):
            if "Collection" not in sel.maj_type:
                controller = sel.dict
                if controller["Id"] == str(controller_id):
                    return controller["Location"]
        return None

    def frcontrollervalidation(self, options):
        """Factory reset controller validation function

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

        customparser.add_argument(
            "--reset_type",
            dest="reset_type",
            help="Use this flag to pass the reset type for storage controller  in iLO6 ",
            default=None,
        )

        customparser.add_argument(
            "--storageid",
            dest="storageid",
            help="Use this flag to select the corresponding storage id in iLO6",
            default=None,
        )
