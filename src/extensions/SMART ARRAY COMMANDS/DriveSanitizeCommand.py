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
""" Drive Erase/ Sanitize Command for rdmc """

try:
    from rdmc_helper import (
        ReturnCodes,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        Encryption,
        NoContentsFoundForOperationError,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        ReturnCodes,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        Encryption,
        NoContentsFoundForOperationError,
    )

class DriveSanitizeCommand:
    """Drive erase/sanitize command"""

    def __init__(self):
        self.ident = {
            "name": "drivesanitize",
            "usage": None,
            "description": "To sanitize a physical drive "
            'by index.\n\texample: drivesanitize "1I:1:1" --controller=1\n\n\tTo'
            " sanitize multiple drives by specifying location.\n\texample: "
            "drivesanitize 1I:1:1,1I:1:2 --controller=1 --mediatype HDD/SSD\n\texample: drivesanitize "
            '1I:1:1,1I:1:2 --controller="Slot 1" --mediatype="HDD" '
            "if incorrect mediatype is specified, error will generated",
            "summary": "Erase/Sanitize physical drive(s)",
            "aliases": [],
            "auxcommands": ["SelectCommand", "RebootCommand", "SmartArrayCommand"],
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
            (options, args) = self.rdmc.rdmc_parse_arglist(self, line)
            if not line or line[0] == "help":
                self.parser.print_help()
                return ReturnCodes.SUCCESS
        except (InvalidCommandLineErrorOPTS, SystemExit):
            if ("-h" in line) or ("--help" in line):
                return ReturnCodes.SUCCESS
            else:
                raise InvalidCommandLineErrorOPTS("")

        self.drivesanitizevalidation(options)

        self.auxcommands["select"].selectfunction("SmartStorageConfig.")
        content = self.rdmc.app.getprops()

        controllers = self.auxcommands["smartarray"].controllers(options, single_use=True)
        if controllers:
            for controller in controllers:
                if int(controller) == int(options.controller):
                    controller_physicaldrives = self.auxcommands[
                        "smartarray"
                    ].physical_drives(options, controllers[controller], single_use=True)

        if not args and not options.all:
            raise InvalidCommandLineError(
                "You must include a physical drive to sanitize."
            )
        elif not options.controller:
            raise InvalidCommandLineError("You must include a controller to select.")
        else:
            if len(args) > 1:
                physicaldrives = args
            elif len(args) == 1:
                physicaldrives = args[0].replace(", ", ",").split(",")
            else:
                physicaldrives = None

            controllist = []

        try:
            if options.controller.isdigit():
                slotlocation = self.get_location_from_id(options.controller)
                if slotlocation:
                    slotcontrol = (
                        slotlocation.lower().strip('"').split("slot")[-1].lstrip()
                    )
                    for control in content:
                        if (
                            slotcontrol.lower()
                            == control["Location"].lower().split("slot")[-1].lstrip()
                        ):
                            controllist.append(control)
            if not controllist:
                raise InvalidCommandLineError("")
        except InvalidCommandLineError:
            raise InvalidCommandLineError(
                "Selected controller not found in the current inventory " "list."
            )

        if self.sanitizedrives(
            controllist,
            physicaldrives,
            controller_physicaldrives,
            options.mediatype,
            options.all,
        ):
            if options.reboot:
                self.auxcommands["reboot"].run("ColdBoot")
                self.rdmc.ui.printer("Preparing for sanitization...\n")
                self.monitorsanitization()
            else:
                self.rdmc.ui.printer(
                    "Sanitization will occur on the next system reboot.\n"
                )

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

    def sanitizedrives(
        self, controllist, drivelist, controller_drives, mediatype, optall
    ):
        """Gets drives ready for sanitization

        :param controllist: list of controllers
        :type controllist: list.
        :param drivelist: physical drives to sanitize
        :type drivelist: list.
        :param optall: flag for sanitizing all drives
        :type optall: bool.
        """
        sanitizedrivelist = []
        logicaldrivelist = []
        changes = False

        for controller in controllist:
            pdrivelist = [x["DataDrives"] for x in controller["LogicalDrives"]]

            for plist in pdrivelist:
                for drive in plist:
                    logicaldrivelist.append(drive)

            if optall:
                sanitizedrivelist = [x["Location"] for x in controller["PhysicalDrives"]]
            else:
                for erasedrive in drivelist:
                    try:
                        for idx, pdrive in enumerate(controller["PhysicalDrives"]):
                            if erasedrive == pdrive["Location"]:
                                if pdrive["Location"] in logicaldrivelist:
                                    raise InvalidCommandLineError(
                                        "Unable to"
                                        " sanitize configured drive. Remove"
                                        " any logical drive(s) associated "
                                        "with drive %s and try again."
                                        % pdrive["Location"]
                                    )

                                # Validate Media Type
                                if not (
                                    self.validate_mediatype(
                                        erasedrive, mediatype, controller_drives
                                    )
                                ):
                                    raise InvalidCommandLineError(
                                        "One or more of the drives given does not match the "
                                        "mediatype %s which is specified" % mediatype
                                    )
                                self.rdmc.ui.printer(
                                    "Setting physical drive %s "
                                    "for sanitization\n" % pdrive["Location"]
                                )
                                sanitizedrivelist.append(pdrive["Location"])
                                break
                    except KeyError as excp:
                        raise NoContentsFoundForOperationError(
                            "The property '%s' is missing " "or invalid." % str(excp)
                        )

            if sanitizedrivelist:
                changes = True
                if mediatype == "SSD":
                    erase_pattern_string = "SanitizeRestrictedBlockErase"
                else:
                    erase_pattern_string = "SanitizeRestrictedOverwrite"

                contentsholder = {
                    "Actions": [
                        {
                            "Action": "PhysicalDriveErase",
                            "ErasePattern": erase_pattern_string,
                            "PhysicalDriveList": sanitizedrivelist,
                        }
                    ],
                    "DataGuard": "Disabled",
                }

                self.rdmc.ui.printer(
                    "DriveSanitize path and payload: %s, %s\n"
                    % (controller["@odata.id"], contentsholder)
                )

                self.rdmc.app.patch_handler(controller["@odata.id"], contentsholder)

        return changes

    def validate_mediatype(self, erasedrive, mediatype, controller_drives):
        """validates media type as HDD or SSD"""
        for idx in list(controller_drives.keys()):
            phy_drive = controller_drives[idx]
            if (
                phy_drive["Location"] == erasedrive
                and phy_drive["MediaType"] == mediatype
            ):
                return True
        return False

    def monitorsanitization(self):
        """monitors sanitization percentage"""
        # TODO: Add code to give updates on sanitization

    def drivesanitizevalidation(self, options):
        """drive sanitize validation function

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
            help="Use this flag to select the corresponding controller "
            "using either the slot number or index.",
            default=None,
        )
        customparser.add_argument(
            "--mediatype",
            dest="mediatype",
            help="""Use this flag to select the mediatype of the hard disk """,
            default=None,
        )
        customparser.add_argument(
            "--reboot",
            dest="reboot",
            help="Include this flag to perform a coldboot command "
            "function after completion of operations and monitor "
            "sanitization.",
            action="store_true",
            default=False,
        )
        customparser.add_argument(
            "--all",
            dest="all",
            help="""Use this flag to sanitize all physical drives on a """
            """controller.""",
            action="store_true",
            default=False,
        )
