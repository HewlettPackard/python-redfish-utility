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
""" Delete Volume Command for rdmc """

from six.moves import input

from redfish.ris import InstanceNotFoundError

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


class DeleteVolumeCommand:
    """Delete volume command"""

    def __init__(self):
        self.ident = {
            "name": "deletevolume",
            "usage": None,
            "description": "To delete a volume "
            "to a controller by index.\n\texample: deletevolume "
            "1 --controller=1\n\n\tTo delete multiple volumes by "
            "index.\n\tExample: deletevolume 1,2 --controller=1"
            "\n\n\tTo delete all volumes on a controller.\n\t"
            "deletevolume --controller=1 --all\n\n\t"
            'deletevolume --controller="Slot1" --all\n\n\tNOTE: '
            "You can also delete volumes by "
            '"VolumeUniqueIdentifier".\n\n\t'
            "For iLO6, storage id need to be specified using --storageid=DE00E000 along with --controller=1\n\n\t"
            "You can also delete volumes by VolumeName",
            "summary": "Deletes volumes from the selected controller.",
            "aliases": ["deletelogicaldrive"],
            "auxcommands": ["SelectCommand", "StorageControllerCommand"],
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

        self.deletevolumevalidation(options)
        ilo_ver = self.rdmc.app.getiloversion()
        if ilo_ver < 6.110:
            try:
                self.auxcommands["select"].selectfunction("StorageController.")
                content = self.rdmc.app.getprops()
                ilo_ver = 6.110
            except Exception:
                pass

        if ilo_ver >= 6.110:
            if not options.storageid:
                raise InvalidCommandLineError(
                    "--storageid option is mandatory for iLO6 along with --controller option.\n"
                )
            controller_logicaldrives = self.auxcommands["storagecontroller"].storagelogical_drives(
                options, options.controller, options.storageid, single_use=True
            )
            if len(controller_logicaldrives) == 0:
                raise InvalidCommandLineError("No Logical drives found.\n")
            get_contrller = []
            self.auxcommands["select"].selectfunction("StorageCollection.")
            st_content = self.rdmc.app.getprops()
            for st_controller in st_content:
                path = st_controller["Members"]
                for mem in path:
                    for val in mem.values():
                        if "DE" in val and options.storageid in val:
                            getval = self.rdmc.app.get_handler(val, silent=True, service=True).dict
                            controller = getval["Controllers"]
                            for ctl in controller.values():
                                ctl = ctl + "/0"
                                get_sel = self.rdmc.app.get_handler(ctl, silent=True, service=True)
                            get_contrller.append(get_sel)
        else:
            self.auxcommands["select"].selectfunction("SmartStorageConfig.")
            content = self.rdmc.app.getprops()

        if not args and not options.all:
            raise InvalidCommandLineError("You must include a logical drive to delete.")
        elif not options.controller:
            raise InvalidCommandLineError("You must include a controller to select.")
        else:
            if len(args) > 1:
                logicaldrives = args
            elif len(args) == 1:
                logicaldrives = args[0].replace(", ", ",").split(",")
            else:
                logicaldrives = None

        controllist = []

        try:
            if ilo_ver >= 6.110:
                if options.controller.isdigit():
                    slotlocation = self.storageget_location_from_id(options.controller, options.storageid)
                    if slotlocation:
                        slotcontrol = slotlocation.lower().strip('"').split("slot")[-1].lstrip().strip("=")
                        for control in get_contrller:
                            cont_temp = control.dict
                            temp = cont_temp["Location"]["PartLocation"]["ServiceLabel"]
                            if "Location" in cont_temp and slotcontrol.lower() == temp.lower().split("slot")[
                                -1
                            ].lstrip().strip("="):
                                controllist.append(cont_temp)
                elif "slot" in options.controller.lower():
                    slotlocation = options.controller
                    if slotlocation:
                        slotcontrol = slotlocation.lower().strip('"').split("slot")[-1].lstrip().strip("=")
                        for control in get_contrller:
                            cont_temp = control.dict
                            temp = cont_temp["Location"]["PartLocation"]["ServiceLabel"]
                            if "Location" in cont_temp and slotcontrol.lower() == temp.lower().split("slot")[
                                -1
                            ].lstrip().strip("="):
                                controllist.append(cont_temp)
                if not controllist:
                    raise InvalidCommandLineError("")
            else:
                try:
                    controllers = self.auxcommands["storagecontroller"].storagecontroller(options, single_use=True)
                    options.command = "volume"
                    ilo_ver = 6.110
                except InstanceNotFoundError:
                    if not options.storageid:
                        raise InvalidCommandLineError(
                            "--storageid option is mandatory. Please input storageid as well so that "
                            "controllers/volumes can be identified.\n"
                        )
                    controllers = self.auxcommands["storagecontroller"].storagecontroller(options, single_use=True)
                    options.command = "volume"
                    ilo_ver = 6.110
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
            self.storagedeletevolume(controller_logicaldrives, logicaldrives, options.all, options.force)
        else:
            self.deletevolume(controllist, logicaldrives, options.all, options.force)
            self.rdmc.ui.printer(
                "One or more properties were changed and will not take effect " "until system is reset \n"
            )

        self.cmdbase.logout_routine(self, options)
        # Return code
        return ReturnCodes.SUCCESS

    def get_location_from_id(self, controller_id):
        # self.rdmc.ui.printer("Controller ID: %s\n" % (controller_id))
        for sel in self.rdmc.app.select("SmartStorageArrayController", path_refresh=True):
            if "Collection" not in sel.maj_type:
                controller = sel.dict
                self.rdmc.ui.printer("Controller ID: %s\n" % (controller["Id"]))
                if controller["Id"] == str(controller_id):
                    self.rdmc.ui.printer("Controller Location: %s\n" % (controller["Location"]))
                    return controller["Location"]
        return None

    def storageget_location_from_id(self, controller_id, storageid):
        get_contrller = []
        # self.auxcommands["select"].selectfunction("StorageCollection.")
        st_content = self.rdmc.app.getprops()
        for st_controller in st_content:
            path = st_controller["Members"]
            for mem in path:
                for val in mem.values():
                    if "DE" in val and storageid in val:
                        getval = self.rdmc.app.get_handler(val, silent=True, service=True).dict
                        controller = getval["Controllers"]
                        for ctl in controller.values():
                            ctl = ctl + "/0"
                            get_sel = self.rdmc.app.get_handler(ctl, silent=True, service=True)
                        get_contrller.append(get_sel)
        for sel in get_contrller:
            if "Collection" not in sel.path:
                controller = sel.dict
                if controller["Id"] == str(controller_id):
                    return controller["Location"]["PartLocation"]["ServiceLabel"]
        return None

    def deletevolume(self, controllist, drivelist, allopt, force):
        """Gets volumes ready for deletion

        :param controllist: list of controllers
        :type controllist: list.
        :param drivelist: volumes to delete
        :type drivelist: list.
        :param allopt: flag for deleting all volumes
        :type allopt: bool.
        """

        for controller in controllist:
            changes = False

            numdrives = len(controller["LogicalDrives"])
            deletecount = 0

            if allopt:
                controller["LogicalDrives"] = []
                controller["DataGuard"] = "Disabled"
                if not force:
                    if not self.inputaccept(None):
                        return
                self.lastlogicaldrive(controller)
                changes = True
            else:
                for deldrive in drivelist:
                    found = False

                    if deldrive.isdigit():
                        deldrive = int(deldrive)

                    for idx, ldrive in enumerate(controller["LogicalDrives"]):
                        if deldrive == ldrive["LogicalDriveNumber"]:
                            if not force:
                                if not self.inputaccept(ldrive["LogicalDriveName"]):
                                    return

                            controller["LogicalDrives"][idx]["Actions"] = [{"Action": "LogicalDriveDelete"}]

                            controller["DataGuard"] = "Permissive"
                            deletecount += 1

                            changes = True
                            found = True

                            break

                    if not found:
                        raise NoContentsFoundForOperationError("Logical " "drive %s not found." % str(deldrive))

                if deletecount == numdrives:
                    self.lastlogicaldrive(controller)

            if changes:
                # self.rdmc.ui.printer(
                #    "DeleteVolume path and payload: %s, %s\n"
                #    % (controller["@odata.id"], controller)
                # )
                put_path = controller["@odata.id"]
                if "settings" not in put_path:
                    put_path = put_path + "settings/"
                controller["@odata.id"] = put_path
                self.rdmc.app.put_handler(
                    put_path,
                    controller,
                    headers={"If-Match": self.getetag(controller["@odata.id"])},
                )
                self.rdmc.app.download_path([controller["@odata.id"]], path_refresh=True, crawl=False)

    def lastlogicaldrive(self, controller):
        """Special case that sets required properties after last drive deletion

        :param controller: controller change settings on
        :type controller: dict.
        """
        changelist = [
            "PredictiveSpareRebuild",
            "SurfaceScanAnalysisPriority",
            "FlexibleLatencySchedulerSetting",
            "DegradedPerformanceOptimization",
            "CurrentParallelSurfaceScanCount",
            "SurfaceScanAnalysisDelaySeconds",
            "MonitorAndPerformanceAnalysisDelaySeconds",
            "InconsistencyRepairPolicy",
            "DriveWriteCache",
            "ExpandPriority",
            "EncryptionEULA",
            "NoBatteryWriteCache",
            "ReadCachePercent",
            "WriteCacheBypassThresholdKiB",
            "RebuildPriority",
            "QueueDepth",
            "ElevatorSort",
        ]

        for item in changelist:
            if item in list(controller.keys()):
                controller[item] = None

    def inputaccept(self, drivename):
        while True:
            if drivename is None:
                ans = input("Are you sure you would" " like to continue deleting all volumes" "? (y/n)")
            else:
                ans = input("Are you sure you would" " like to continue deleting volume" " %s? (y/n)" % drivename)

            if ans.lower() == "y":
                return 1
            elif ans.lower() == "n":
                self.rdmc.ui.printer("Stopping command without deleting volume/volumes.\n")
                return 0

    def storagedeletevolume(self, logical_drives, drivelist, allopt, force):
        if allopt:
            sorted_dict = sorted(logical_drives, reverse=True)
            if not force:
                if not self.inputaccept(None):
                    return
            for drive in sorted_dict:
                self.rdmc.app.delete_handler(logical_drives[drive]["@odata.id"], {})
        else:
            found = False
            sorted_dict = sorted(logical_drives, reverse=True)
            sorted_drivelist = sorted(drivelist, reverse=True)
            for deldrive in sorted_drivelist:
                found = False
                changes = False
                for drive in sorted_dict:
                    if logical_drives[drive]["Id"] == deldrive:
                        if not force:
                            if not self.inputaccept(logical_drives[drive]["Name"]):
                                return
                        self.rdmc.ui.printer("Setting volume %s " "for deletion\n" % logical_drives[drive]["Name"])
                        changes = True
                        found = True
                        break
                try:
                    if changes:
                        # self.rdmc.ui.printer(
                        #    "DeleteVolume path and payload: %s, %s\n"
                        #    % (logical_drives[drive]["@odata.id"], "{}")
                        # )
                        self.rdmc.app.delete_handler(logical_drives[drive]["@odata.id"], {})
                except:
                    self.rdmc.ui.printer(
                        "This volume cannot"
                        "be deleted without deleting "
                        "the higher volumes in the same Physical drive first.\n"
                    )
                    raise
            if not found:
                raise NoContentsFoundForOperationError("Logical " "drive not found.")

    def getetag(self, path):
        """get etag from path"""
        etag = None
        instance = self.rdmc.app.monolith.path(path)
        if instance:
            etag = (
                instance.resp.getheader("etag")
                if "etag" in instance.resp.getheaders()
                else instance.resp.getheader("ETag")
            )
        return etag

    def deletevolumevalidation(self, options):
        """delete volume validation function

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
            "--all",
            dest="all",
            help="""Use this flag to delete all volumes on a controller.""",
            action="store_true",
            default=False,
        )
        customparser.add_argument(
            "--force",
            dest="force",
            help="""Use this flag to override the "are you sure?" text when deleting a volume.""",
            action="store_true",
            default=False,
        )
