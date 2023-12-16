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
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        NoContentsFoundForOperationError,
        ReturnCodes,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        NoContentsFoundForOperationError,
        ReturnCodes,
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
            "1I:1:1,1I:1:2 --controller=Slot 1 --mediatype=HDD "
            "if incorrect mediatype is specified, error will generated "
            "For iLO6, storage id need to be specified using --storageid=DE00E000 along with --controller=1\n"
            "Once drivesanitize function is performed in iLO6, It may take a while to complete.\n "
            "To check the status of Sanitization, perform to following command-\n"
            "drivesanitize 1I:1:1 --controller=1 --storageid=DE00900 --status\n"
            "Once the process in 100% complete, use the --drivereset tag to reset the drive. Example-\n"
            "drivesanitize 1I:1:1 --controller=1 --storageid=DE00900 --drivereset\n",
            "summary": "Erase/Sanitize physical drive(s)",
            "aliases": ["DriveEraseCommand"],
            "auxcommands": ["SelectCommand", "RebootCommand", "StorageControllerCommand"],
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
        except (InvalidCommandLineErrorOPTS, SystemExit):
            if ("-h" in line) or ("--help" in line):
                return ReturnCodes.SUCCESS
            else:
                raise InvalidCommandLineErrorOPTS("")

        self.drivesanitizevalidation(options)

        ilo_ver = self.rdmc.app.getiloversion()

        if ilo_ver < 6.110:
            try:
                controllers = self.auxcommands["storagecontroller"].controllers(options, single_use=True)
                if len(controllers) == 0:
                    if not options.storageid:
                        raise InvalidCommandLineError(
                            "--storageid option is mandatory. Please input storageid as well so that "
                            "controllers/volumes can be identified.\n"
                        )
                ilo_ver = 6.110
            except:
                if not options.storageid:
                    raise InvalidCommandLineError(
                        "--storageid option is mandatory. Please input storageid as well so that "
                        "controllers/volumes can be identified.\n"
                    )

        if ilo_ver >= 6.110:
            if not options.storageid:
                raise InvalidCommandLineError(
                    "--storageid option is mandatory for iLO6" " along with --controller option.\n"
                )
            self.auxcommands["select"].selectfunction("StorageController")
            content = self.rdmc.app.getprops()
            controllers = self.auxcommands["storagecontroller"].storagecontroller(options, single_use=True)
            if controllers:
                for controller in controllers:
                    if (
                        getattr(options, "controller", False) == controller
                        or controllers[controller]["Location"]["PartLocation"]["ServiceLabel"][-1]
                        == getattr(options, "controller", False)[-1]
                    ):
                        controller_physicaldrives = self.auxcommands["storagecontroller"].storagephysical_drives(
                            options,
                            options.controller,
                            options.storageid,
                            single_use=True,
                        )
        else:
            self.auxcommands["select"].selectfunction("SmartStorageConfig")
            content = self.rdmc.app.getprops()
            controllers = self.auxcommands["storagecontroller"].controllers(options, single_use=True)
            if controllers:
                for controller in controllers:
                    if int(controller) == int(options.controller):
                        controller_physicaldrives = self.auxcommands["storagecontroller"].physical_drives(
                            options, controllers[controller], single_use=True
                        )

        if not args and not options.all:
            raise InvalidCommandLineError("You must include a physical drive to sanitize.")
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
            if ilo_ver >= 6.110:
                if options.controller.isdigit():
                    slotlocation = self.storageget_location_from_id(options.controller, options.storageid)
                    if slotlocation:
                        slotcontrol = slotlocation.lower().strip('"').split("slot")[-1].lstrip().strip("=")
                        for control in controllers.values():
                            if "Location" in control and slotcontrol.lower() == control["Location"]["PartLocation"][
                                "ServiceLabel"
                            ].lower().split("slot")[-1].lstrip().strip("="):
                                controllist.append(control)
                elif "slot" in options.controller.lower():
                    slotlocation = options.controller
                    if slotlocation:
                        slotcontrol = slotlocation.lower().strip('"').split("slot")[-1].lstrip().strip("=")
                        for control in controllers.values():
                            if "Location" in control and slotcontrol.lower() == control["Location"]["PartLocation"][
                                "ServiceLabel"
                            ].lower().split("slot")[-1].lstrip().strip("="):
                                controllist.append(control)
                if not controllist:
                    raise InvalidCommandLineError("")
            else:
                if options.controller.isdigit():
                    slotlocation = self.get_location_from_id(options.controller)
                    if slotlocation:
                        slotcontrol = slotlocation.lower().strip('"').split("slot")[-1].lstrip()
                        for control in content:
                            if slotcontrol.lower() == control["Location"].lower().split("slot")[-1].lstrip():
                                controllist.append(control)
                if not controllist:
                    raise InvalidCommandLineError("")
        except InvalidCommandLineError:
            raise InvalidCommandLineError("Selected controller not found in the current inventory " "list.")

        if ilo_ver >= 6.110:
            if options.status:
                if options.all:
                    for drive in controller_physicaldrives.values():
                        pdrive_inilo = self.convertloc(drive["PhysicalLocation"]["PartLocation"]["ServiceLabel"])
                        if len(drive["Operations"]) != 0:
                            self.rdmc.ui.printer(
                                "The drive is in %s state, %s percent complete.\n"
                                % (
                                    drive["Operations"][0]["OperationName"],
                                    drive["Operations"][0]["PercentageComplete"],
                                )
                            )
                            if int(drive["Operations"][0]["PercentageComplete"]) == 100:
                                self.rdmc.ui.printer("You can reset %s using --drivereset now.\n" % (pdrive_inilo))
                        elif len(drive["Operations"]) == 0:
                            mr_ct = drive["Status"]["State"]
                            self.rdmc.ui.printer("Sanitization is completed and updated drive status = %s\n" % (mr_ct))
                        else:
                            self.rdmc.ui.printer("Sanitization failed for drive %s.\n" % (pdrive_inilo))
                else:
                    for drive in controller_physicaldrives.values():
                        pdrive_inilo = self.convertloc(drive["PhysicalLocation"]["PartLocation"]["ServiceLabel"])
                        for userdrive in physicaldrives:
                            if userdrive == pdrive_inilo:
                                if len(drive["Operations"]) != 0:
                                    self.rdmc.ui.printer(
                                        "The drive is in %s state, %s percent complete.\n"
                                        % (
                                            drive["Operations"][0]["OperationName"],
                                            drive["Operations"][0]["PercentageComplete"],
                                        )
                                    )
                                    if int(drive["Operations"][0]["PercentageComplete"]) == 100:
                                        self.rdmc.ui.printer("You can reset %s using --drivereset now.\n" % (userdrive))
                                elif len(drive["Operations"]) == 0:
                                    mr_ct = drive["Status"]["State"]
                                    self.rdmc.ui.printer(
                                        "Sanitization is completed and updated drive status = %s\n" % (mr_ct)
                                    )

                                else:
                                    self.rdmc.ui.printer("Sanitization failed for drive %s.\n" % (userdrive))
            elif options.drivereset:
                if options.all:
                    for drive in controller_physicaldrives.values():
                        pdrive_inilo = self.convertloc(drive["PhysicalLocation"]["PartLocation"]["ServiceLabel"])
                        if "Actions" in drive:
                            if "#Drive.Reset" in drive["Actions"]:
                                path = drive["@odata.id"] + "/Actions/Drive.Reset"
                                contentsholder = {"ResetType": "ForceOn"}
                                self.rdmc.ui.printer("DriveReset path and payload: %s, %s\n" % (path, contentsholder))
                                self.rdmc.app.post_handler(path, contentsholder)
                            else:
                                if len(drive["Operations"]) != 0:
                                    self.rdmc.ui.printer(
                                        "Sanitization is in progress for drive %s. Use --status to check it's status.\n"
                                        % (pdrive_inilo)
                                    )
                                else:
                                    self.rdmc.ui.printer(
                                        "Drive sanitization is not being performed on %s\n" % (pdrive_inilo)
                                    )
                        else:
                            self.rdmc.ui.printer("Drive sanitization is not being performed on %s\n" % (pdrive_inilo))
                else:
                    for drive in controller_physicaldrives.values():
                        pdrive_inilo = self.convertloc(drive["PhysicalLocation"]["PartLocation"]["ServiceLabel"])
                        for userdrive in physicaldrives:
                            if userdrive == pdrive_inilo:
                                if "Actions" in drive:
                                    if "#Drive.Reset" in drive["Actions"]:
                                        path = drive["@odata.id"] + "/Actions/Drive.Reset"
                                        contentsholder = {"ResetType": "ForceOn"}
                                        self.rdmc.ui.printer(
                                            "DriveReset path and payload: %s, %s\n" % (path, contentsholder)
                                        )
                                        self.rdmc.app.post_handler(path, contentsholder)
                                    else:
                                        if len(drive["Operations"]) != 0:
                                            self.rdmc.ui.printer(
                                                "Santization is in progress for drive %s. Use --status to check its "
                                                "status.\n" % (pdrive_inilo)
                                            )
                                        else:
                                            self.rdmc.ui.printer(
                                                "Drive sanitization is not being performed on %s\n" % (pdrive_inilo)
                                            )
                                else:
                                    self.rdmc.ui.printer(
                                        "Drive sanitization is not being performed on %s\n" % (pdrive_inilo)
                                    )
            else:
                if self.storagesanitizedrives(physicaldrives, controller_physicaldrives, options.all):
                    if options.reboot:
                        self.auxcommands["reboot"].run("ColdBoot")
                        self.rdmc.ui.printer("Preparing for sanitization...\n")
                        self.monitorsanitization()

        else:
            if options.status is True or options.drivereset is True:
                raise InvalidCommandLineError("--status and --drivereset options are not supported on iLO 5\n")
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
                    self.rdmc.ui.printer("Sanitization will occur on the next system reboot.\n")

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

    def storageget_location_from_id(self, controller_id, storage_id):
        for sel in self.rdmc.app.select("StorageController", path_refresh=True):
            if "Collection" not in sel.maj_type and storage_id in sel.dict["@odata.id"]:
                controller = sel.dict
                if controller["Id"] == str(controller_id):
                    return controller["Location"]["PartLocation"]["ServiceLabel"]
        return None

    def sanitizedrives(self, controllist, drivelist, controller_drives, mediatype, optall):
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
                                        " any volume(s) associated "
                                        "with drive %s and try again." % pdrive["Location"]
                                    )

                                # Validate Media Type
                                if not (self.validate_mediatype(erasedrive, mediatype, controller_drives)):
                                    raise InvalidCommandLineError(
                                        "One or more of the drives given does not match the "
                                        "mediatype %s which is specified" % mediatype
                                    )
                                self.rdmc.ui.printer(
                                    "Setting physical drive %s " "for sanitization\n" % pdrive["Location"]
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

                # self.rdmc.ui.printer(
                #    "DriveSanitize path and payload: %s, %s\n"
                #    % (controller["@odata.id"], contentsholder)
                # )
                patch_path = controller["@odata.id"]
                if "settings" not in patch_path:
                    patch_path = patch_path + "settings/"
                controller["@odata.id"] = patch_path

                self.rdmc.app.patch_handler(controller["@odata.id"], contentsholder)

        return changes

    def convertloc(self, servicelabel):
        loc = servicelabel.split(":")
        temp_str = str(loc[1].split("=")[1] + ":" + loc[2].split("=")[1] + ":" + loc[3].split("=")[1])
        return temp_str

    def storagesanitizedrives(self, drivelist, controller_drives, optall):
        sanitizedrivelist = []
        changes = False
        plocation = ""
        if len(controller_drives) != 0:
            for plist in controller_drives.values():
                logicaldrivelist = []
                logicaldrivelist.extend(plist["Links"]["Volumes"])
                plocation = self.convertloc(plist["PhysicalLocation"]["PartLocation"]["ServiceLabel"])

                if optall:
                    if logicaldrivelist:
                        self.rdmc.ui.printer(
                            "Unable to"
                            " sanitize drive %s. Remove"
                            " any volume(s) associated "
                            "with this drive and try again.\n" % plocation
                        )
                        break
                    sanitizedrivelist.append(plocation)
                else:
                    for erasedrive in drivelist:
                        try:
                            if erasedrive == plocation:
                                if logicaldrivelist:
                                    self.rdmc.ui.printer(
                                        "Unable to"
                                        " sanitize drive %s. Remove"
                                        " any volume(s) associated "
                                        "with this drive and try again.\n" % plocation
                                    )
                                self.rdmc.ui.printer("Setting physical drive %s " "for sanitization\n" % plocation)
                                sanitizedrivelist.append(plocation)
                                break
                        except KeyError as excp:
                            raise NoContentsFoundForOperationError(
                                "The property '%s' is missing " "or invalid.\n" % str(excp)
                            )

                if sanitizedrivelist:
                    changes = True
                    path = plist["@odata.id"] + "/Actions/Drive.SecureErase"
                    contentsholder = {}

                    self.rdmc.ui.printer("DriveSanitize path and payload: %s, %s\n" % (path, contentsholder))

                    self.rdmc.app.post_handler(path, contentsholder)
                    sanitizedrivelist = []
                    self.rdmc.ui.printer("You can check the sanitization status of %s using --status\n" % (plocation))

        return changes

    def validate_mediatype(self, erasedrive, mediatype, controller_drives):
        """validates media type as HDD or SSD"""
        for idx in list(controller_drives.keys()):
            phy_drive = controller_drives[idx]
            if phy_drive["Location"] == erasedrive and phy_drive["MediaType"] == mediatype:
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
            help="Use this flag to select the corresponding controller " "using either the slot number or index.",
            default=None,
        )
        customparser.add_argument(
            "--storageid",
            dest="storageid",
            help="Use this flag to select the corresponding storageid in iLO6 only.",
            default=None,
        )
        customparser.add_argument(
            "--mediatype",
            dest="mediatype",
            help="""Use this flag to select the mediatype of the hard disk """,
            default=None,
            required=True,
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
            help="""Use this flag to sanitize all physical drives on a """ """controller.""",
            action="store_true",
            default=False,
        )
        customparser.add_argument(
            "--drivereset",
            dest="drivereset",
            help="""Use this flag to reset physical drives on a """ """controller.""",
            action="store_true",
            default=False,
        )
        customparser.add_argument(
            "--status",
            dest="status",
            help="""Use this flag to check sanitization status of a """ """controller.""",
            action="store_true",
            default=False,
        )
