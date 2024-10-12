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
""" Create Volume Command for rdmc """

from argparse import RawDescriptionHelpFormatter

from redfish.ris import IdTokenError
from redfish.ris.rmc_helper import IloResponseError, InstanceNotFoundError

try:
    from rdmc_helper import (
        IloLicenseError,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        InvalidSmartArrayConfigurationError,
        ReturnCodes,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        IloLicenseError,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        InvalidSmartArrayConfigurationError,
        ReturnCodes,
    )


class CreateVolumeCommand:
    """Create volume command"""

    def __init__(self):
        self.ident = {
            "name": "createvolume",
            "usage": None,
            "description": "Creates volumes on compatible HPE SSA RAID controllers\nTo view "
            "help on specific sub-commands run: createvolume <sub-command> -h\n\n"
            "NOTE: Refer http://www.hpe.com/info/scmo for additional information "
            "on creating Volumes on Gen11 servers.\n\t"
            "Also, when you select multiple physicaldrives you can select by both\n\t"
            "physical drive name and by the location at the same time.\n\t"
            "You can also select controllers by slot number as well as index.\n\t"
            "For iLO6, storage id need to be specified using --storageid=DE00E000 "
            "along with --controller=1",
            "summary": "Creates a new volume on the selected controller.",
            "aliases": ["createlogicaldrive"],
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
            line.append("-h")
            try:
                (_, _) = self.rdmc.rdmc_parse_arglist(self, line)
            except:
                return ReturnCodes.SUCCESS
            return ReturnCodes.SUCCESS
        try:
            (options, _) = self.rdmc.rdmc_parse_arglist(self, line)
        except (InvalidCommandLineErrorOPTS, SystemExit):
            if ("-h" in line) or ("--help" in line):
                return ReturnCodes.SUCCESS
            else:
                raise InvalidCommandLineErrorOPTS("")

        self.createvolumevalidation(options)
        ilo_ver = self.rdmc.app.getiloversion()
        if ilo_ver < 6.110:
            try:
                self.auxcommands["select"].selectfunction("StorageController.")
                content = self.rdmc.app.getprops()
                if options.command == "quickdrive":
                    raise InvalidCommandLineError(
                        "This controller is not compatible with quickdrive option. "
                        "Please use customdrive or volume option\n"
                    )
                ilo_ver = 6.110
                options.command = "volume"
            except Exception:
                pass

        if ilo_ver >= 6.110:
            if options.command == "customdrive" or options.command == "quickdrive":
                raise InvalidCommandLineError("customdrive or quickdrive subcommand is not supported on iLO6(Gen11).\n")
            if not options.storageid:
                raise InvalidCommandLineError("--storageid option is mandatory for iLO6 or latest iLO5 onwards.\n")
        else:
            if options.command == "volume":
                raise InvalidCommandLineError("volume subcommand is not supported on iLO5(Gen10).\n")
        if options.controller:
            if ilo_ver >= 6.110:
                if options.storageid:
                    controllers = self.auxcommands["storagecontroller"].storagecontroller(options, single_use=True)
                else:
                    raise InvalidCommandLineError("--storageid option is mandatory for iLO6 onwards.\n")
            else:
                try:
                    controllers = self.auxcommands["storagecontroller"].controllers(options, single_use=True)
                    if len(controllers) == 0:
                        if not options.storageid:
                            raise InvalidCommandLineError(
                                "--storageid option is mandatory. Please input storageid as well so that "
                                "controllers/volumes can be identified.\n"
                            )
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
            try:
                # logical_drives = self.rdmc.app.get_handler(
                #     "/redfish/v1/Systems/1/Storage/" + options.storageid + "/Volumes/",
                #     silent=True,
                #     service=True,
                # ).dict["Members"]
                # for volume_list in logical_drives:
                #     volume = self.rdmc.app.get_handler(volume_list["@odata.id"], silent=True, service=True).dict
                #     if (
                #         ("Status" in volume)
                #         and (volume["Status"]["State"] == "Enabled")
                #         and ("RAIDType" in volume)
                #         and (volume["RAIDType"] == "None")
                #     ):
                # self.rdmc.app.delete_handler(volume["@odata.id"], {}, silent=True, service=True)

                controller = controllers[next(iter(controllers))]
                (create_flag, newdrive) = self.createvolume(options, controller)
                if create_flag:
                    if ilo_ver >= 6.110:
                        temp_odata = controller["@odata.id"]
                        volume_path = temp_odata.split("Controllers")[0] + "Volumes"
                        self.rdmc.ui.printer("CreateVolume path and payload: %s, %s\n" % (volume_path, newdrive))
                        result = self.rdmc.app.post_handler(volume_path, newdrive)

                        self.rdmc.ui.printer("Volume created successfully  \n")
                        if options.sparedrives:
                            controller["physical_drives"] = self.auxcommands[
                                "storagecontroller"
                            ].storagephysical_drives(options, controller, options.storageid, single_use=True)
                            array = options.disks.split(",")
                            set_spare = False
                            newdrive1 = {"Links": {"DedicatedSpareDrives": [{}]}}
                            volume_path1 = volume_path + result.session_location.split("Volumes")[1]

                            sparedrives = options.sparedrives.split(",")
                            s_array = []
                            if len(controller["physical_drives"]) > 0:
                                for p_id in controller["physical_drives"]:
                                    p_loc = self.convertloc(
                                        controller["physical_drives"][str(p_id)]["PhysicalLocation"]["PartLocation"][
                                            "ServiceLabel"
                                        ]
                                    )
                                    l_loc = p_loc.split(":")[1:]
                                    p_loc = ":".join(l_loc)

                                    for sdrive in sparedrives:
                                        if sdrive == p_loc and sdrive not in array:
                                            s_array.append(
                                                {
                                                    "@odata.id": controller["physical_drives"][str(p_id)]["@odata.id"],
                                                }
                                            )
                                            set_spare = True
                            newdrive1["Links"]["DedicatedSpareDrives"] = s_array
                            if not set_spare:
                                raise InvalidCommandLineError(
                                    "Invalid spare drive given, check whether given spare drive is different from "
                                    "disks given or check whether spare drive belongs to same controller"
                                )

                            self.rdmc.app.patch_handler(volume_path1, newdrive1)
                            self.rdmc.ui.printer("Successfully added the sparedrives %s\n" % (newdrive1))

                        return ReturnCodes.SUCCESS

                    else:
                        temp_odata = controller["@odata.id"]
                        payload_dict = dict()
                        payload_dict["DataGuard"] = "Disabled"
                        if "settings" not in temp_odata:
                            temp_odata = temp_odata + "settings/"
                        settings_controller = self.rdmc.app.get_handler(temp_odata, service=False, silent=True)
                        # Fix for multiple logical creation at single reboot
                        if self.rdmc.app.typepath.defs.isgen9:
                            payload_dict["logical_drives"] = dict()
                            payload_dict["logical_drives"]["new"] = newdrive
                        else:
                            payload_dict["LogicalDrives"] = settings_controller.dict["LogicalDrives"]
                            payload_dict["LogicalDrives"].append(newdrive)
                        self.rdmc.ui.printer("CreateVolume path and payload: %s, %s\n" % (temp_odata, payload_dict))
                        self.rdmc.app.put_handler(
                            temp_odata,
                            payload_dict,
                            headers={"If-Match": self.getetag(temp_odata)},
                        )
                        self.rdmc.app.download_path([temp_odata], path_refresh=True, crawl=False)
                        self.rdmc.ui.printer(
                            "One or more properties were changed and will not take effect " "until system is reset \n"
                        )
            except IloLicenseError:
                self.rdmc.ui.error("License Error Occured while creating volume\n")
                return ReturnCodes.ILO_LICENSE_ERROR
            except IdTokenError:
                self.rdmc.ui.error("Insufficient Privilege to create volume\n")
                return ReturnCodes.RIS_MISSING_ID_TOKEN
            except IloResponseError:
                self.rdmc.ui.error("iLO threw iLOResponseError\n")
                return ReturnCodes.RIS_ILO_RESPONSE_ERROR
            except StopIteration:
                self.rdmc.ui.error("Drive or Controller not exist, Please check drive or controller\n")
            except Exception as excp:
                self.rdmc.ui.error(excp)

        else:
            self.rdmc.ui.error("Provide the controller \n")

        self.cmdbase.logout_routine(self, options)
        # Return code
        return ReturnCodes.SUCCESS

    def convertloc(self, servicelabel):
        loc = servicelabel.split(":")
        temp_str = str(
            loc[0].split("=")[1] + ":" + loc[1].split("=")[1] + ":" + loc[2].split("=")[1] + ":" + loc[3].split("=")[1]
        )
        return temp_str

    def get_allowed_list(self, storage_id, attr):
        url = "/redfish/v1/Systems/1/Storage/" + storage_id + "/Volumes/Capabilities"
        attr_allowed_str = attr + "@Redfish.AllowableValues"

        results = self.rdmc.app.get_handler(url, service=True, silent=True).dict
        return results[attr_allowed_str]

    def createvolume(self, options, controller):
        """Create volume"""
        global p_loc
        ilo_ver = self.rdmc.app.getiloversion()
        if options.command == "volume":
            ilo_ver = 6.110
        if ilo_ver >= 6.110:
            try:
                raidlvllist = self.get_allowed_list(options.storageid, "RAIDType")
            except:
                raidlvllist = [
                    "Raid0",
                    "Raid1",
                    "Raid1ADM",
                    "Raid10",
                    "Raid10ADM",
                    "Raid5",
                    "Raid50",
                    "Raid6",
                    "Raid60",
                ]

        else:
            raidlvllist = [
                "Raid0",
                "Raid1",
                "Raid1ADM",
                "Raid10",
                "Raid10ADM",
                "Raid5",
                "Raid50",
                "Raid6",
                "Raid60",
            ]
        interfacetypelist = ["SAS", "SATA", "NVMe"]
        mediatypelist = ["SSD", "HDD"]
        sparetypelist = ["Dedicated", "Roaming"]
        acceltypelist = ["ControllerCache", "IOBypass", "None"]
        locationtypelist = ["Internal", "External"]
        legacylist = ["Primary", "Secondary", "All", "None"]
        paritylist = ["Default", "Rapid"]
        iOPerfModeEnabledlist = ["true", "false"]
        if ilo_ver >= 6.110:
            try:
                readCachePolicylist = self.get_allowed_list(options.storageid, "ReadCachePolicy")
                # writeCachePolicylist = self.get_allowed_list(options.storageid, "WriteCachePolicy")
                writeCachePolicylist = [
                    "Off",
                    "WriteThrough",
                    "ProtectedWriteBack",
                    "UnprotectedWriteBack",
                ]
            except:
                readCachePolicylist = ["Off", "ReadAhead"]
                writeCachePolicylist = [
                    "Off",
                    "WriteThrough",
                    "ProtectedWriteBack",
                    "UnprotectedWriteBack",
                ]
            # InitMethodlist = self.get_allowed_list(options.storageid, "InitializeMethod")
        WriteHoleProtectionPolicyList = ["Yes", "No"]
        sparedrives = []
        changes = False

        if ilo_ver >= 6.110:
            controller["physical_drives"] = self.auxcommands["storagecontroller"].storagephysical_drives(
                options, controller, options.storageid, single_use=True
            )
        else:
            try:
                controller["physical_drives"] = self.auxcommands["storagecontroller"].physical_drives(
                    options, controller, single_use=True
                )
            except:
                controller["physical_drives"] = self.auxcommands["storagecontroller"].storagephysical_drives(
                    options, controller, options.storageid, single_use=True
                )
        if ilo_ver >= 6.110:
            controller["logical_drives"] = self.auxcommands["storagecontroller"].storagelogical_drives(
                options, controller, options.storageid, single_use=True
            )
        else:
            try:
                controller["logical_drives"] = self.auxcommands["storagecontroller"].logical_drives(
                    options, controller, single_use=True
                )
            except:
                controller["logical_drives"] = self.auxcommands["storagecontroller"].storagelogical_drives(
                    options, controller, options.storageid, single_use=True
                )
        if controller.get("Links"):
            if ilo_ver >= 6.110:
                newdrive = {"Links": {"Drives": {}}}
            else:
                newdrive = {"Links": {"DataDrives": {}}}
        else:
            if ilo_ver >= 6.110:
                newdrive = {"Links": {"Drives": {}}}
            else:
                newdrive = {"links": {"DataDrives": {}}}

        changes = False
        itemadded = False

        for item in raidlvllist:
            if options.raid.lower() == item.lower():
                if options.command == "customdrive" or options.command == "volume":
                    drivecount = len(options.disks.replace(", ", ",").split(","))
                else:
                    try:
                        drivecount = int(options.disks)
                    except ValueError:
                        raise InvalidCommandLineError("Number of drives is not an integer.")
                if self.raidvalidation(item.lower(), drivecount, options):
                    itemadded = True
                    if ilo_ver >= 6.110:
                        newdrive["RAIDType"] = options.raid.upper()
                    else:
                        newdrive["Raid"] = item
                break

        if not itemadded:
            raise InvalidCommandLineError("Invalid raid type or configuration.")
        else:
            itemadded = False

        if options.command == "customdrive":
            if options.sparedrives:
                sparedrives = options.sparedrives.replace(", ", ",").split(",")
                newdrive["SpareDrives"] = []
                newdrive["SpareRebuildMode"] = "Dedicated"

            drives = options.disks.replace(", ", ",").split(",")
            newdrive["DataDrives"] = []

            if len(controller["physical_drives"]) > 0:
                for id in controller["physical_drives"]:
                    for drive in drives:
                        drv_id = controller["physical_drives"][str(id)]
                        if "Location" in drv_id:
                            drv_loc = drv_id["Location"]
                        else:
                            location = drv_id["PhysicalLocation"]["PartLocation"]["ServiceLabel"]
                            loc = location.split(":")
                            del loc[0]
                            if len(loc) == 3:
                                temp_str = str(
                                    loc[0].split("=")[1] + ":" + loc[1].split("=")[1] + ":" + loc[2].split("=")[1]
                                )
                                drv_loc = temp_str

                        if drive == drv_loc:
                            newdrive["DataDrives"].append(drive)

                    for sdrive in sparedrives:
                        drv_id = controller["SpareDrives"][str(id)]
                        if "Location" in drv_id:
                            drv_loc = drv_id["Location"]
                        else:
                            location = drv_id["PhysicalLocation"]["PartLocation"]["ServiceLabel"]
                            loc = location.split(":")
                            del loc[0]
                            if len(loc) == 3:
                                temp_str = str(
                                    loc[0].split("=")[1] + ":" + loc[1].split("=")[1] + ":" + loc[2].split("=")[1]
                                )
                                drv_loc = temp_str

                        if drive == drv_loc:
                            newdrive["DataDrives"].append(drive)
                        if sdrive == drv_id:
                            newdrive["SpareDrives"].append(sdrive)
            else:
                raise InvalidCommandLineError("No Physical Drives in this controller")

            if drivecount > len(newdrive["DataDrives"]):
                raise InvalidCommandLineError(
                    "Not all of the selected drives could " "be found in the specified locations."
                )

            if options.sparetype:
                itemadded = False
                for item in sparetypelist:
                    if options.sparetype.lower() == item.lower():
                        newdrive["SpareRebuildMode"] = item
                        itemadded = True
                        break

                if not itemadded:
                    raise InvalidCommandLineError("Invalid spare drive type.")

            if options.drivename:
                newdrive["LogicalDriveName"] = options.drivename

            if options.capacitygib:
                try:
                    capacitygib = int(options.capacitygib)
                except ValueError:
                    raise InvalidCommandLineError("Capacity is not an integer.")
                newdrive["CapacityGiB"] = capacitygib

            if options.acceleratortype:
                itemadded = False
                for item in acceltypelist:
                    if options.acceleratortype.lower() == item.lower():
                        newdrive["Accelerator"] = item
                        itemadded = True
                        break

                if not itemadded:
                    raise InvalidCommandLineError("Invalid accelerator type.")

            if options.legacyboot:
                itemadded = False
                for item in legacylist:
                    if options.legacyboot.lower() in item.lower():
                        newdrive["LegacyBootPriority"] = item
                        itemadded = True
                        break

                if not itemadded:
                    raise InvalidCommandLineError("Invalid legacy boot priority.")

            if options.capacityblocks:
                try:
                    capacityblocks = int(options.capacityblocks)
                except ValueError:
                    raise InvalidCommandLineError("Capacity is not an integer.")

                newdrive["CapacityBlocks"] = capacityblocks

            if options.paritygroup:
                try:
                    paritygroup = int(options.paritygroup)
                except ValueError:
                    raise InvalidCommandLineError("Parity group is not an integer.")

                newdrive["ParityGroupCount"] = paritygroup

            if options.paritytype:
                itemadded = False
                for item in paritylist:
                    if options.paritytype.lower() == item.lower():
                        newdrive["ParityInitializationType"] = item
                        itemadded = True
                        break

                if not itemadded:
                    raise InvalidCommandLineError("Invalid parity type")

            if options.blocksize:
                try:
                    blocksize = int(options.blocksize)
                except ValueError:
                    raise InvalidCommandLineError("Block size is not an integer.")

                newdrive["BlockSizeBytes"] = blocksize

            if options.stripsize:
                try:
                    stripsize = int(options.stripsize)
                except ValueError:
                    raise InvalidCommandLineError("Strip size is not an integer.")

                newdrive["StripSizeBytes"] = stripsize

            if options.stripesize:
                try:
                    stripesize = int(options.stripesize)
                except ValueError:
                    raise InvalidCommandLineError("Stripe size is not an integer.")

                newdrive["StripeSizeBytes"] = stripesize
        elif options.command == "quickdrive":
            try:
                numdrives = int(options.disks)
            except ValueError:
                raise InvalidCommandLineError("Number of drives is not an integer.")

            newdrive["DataDrives"] = {
                "DataDriveCount": numdrives,
                "DataDriveMinimumSizeGiB": 0,
            }
            for item in mediatypelist:
                if options.drivetype.lower() == item.lower():
                    newdrive["DataDrives"]["DataDriveMediaType"] = item
                    itemadded = True
                    break
            if not itemadded:
                raise InvalidCommandLineError("Invalid media type.")
            else:
                itemadded = False
            for item in interfacetypelist:
                if options.interfacetype.lower() == item.lower():
                    newdrive["DataDrives"]["DataDriveInterfaceType"] = item
                    itemadded = True
                    break
            if not itemadded:
                raise InvalidCommandLineError("Invalid interface type.")

            if options.locationtype:
                for item in locationtypelist:
                    if options.locationtype.lower() == item.lower():
                        newdrive["DataDrives"]["DataDriveLocation"] = item
                        break
            if options.minimumsize:
                try:
                    minimumsize = int(options.minimumsize)
                except ValueError:
                    raise InvalidCommandLineError("Minimum size is not an integer.")
                newdrive["DataDrives"]["DataDriveMinimumSizeGiB"] = minimumsize
                newdrive["CapacityGiB"] = minimumsize
        elif options.command == "volume":
            idval = []
            if len(controller["physical_drives"]) > 0:
                array = options.disks.split(",")
                DA = ["DA000000", "DA000001"]
                for p_id in controller["physical_drives"]:
                    if p_id not in DA:
                        p_loc = self.convertloc(
                            controller["physical_drives"][str(p_id)]["PhysicalLocation"]["PartLocation"]["ServiceLabel"]
                        )

                        for ar in array:
                            if ar in p_loc:
                                idval.append(controller["physical_drives"][str(p_id)]["@odata.id"])
            newdrive["Links"]["Drives"] = []
            if idval is not None:
                for id in idval:
                    newdrive["Links"]["Drives"].append(
                        {
                            "@odata.id": id,
                        }
                    )
            else:
                raise InvalidCommandLineError(
                    "Disk location given is invalid , Kindly recheck and provide valid location"
                )

            if "capacitygib" in options and options.capacitygib:
                options.capacitybytes = int(options.capacitygib) * 1024 * 1024 * 1024
            if "capacitybytes" in options and options.capacitybytes is not None:
                if options.capacitybytes:
                    try:
                        if isinstance(options.capacitybytes, list):
                            capacitybytes = int(options.capacitybytes[0])
                        else:
                            capacitybytes = int(options.capacitybytes)
                    except ValueError:
                        raise InvalidCommandLineError("Capacity is not an integer.")

                    newdrive["CapacityBytes"] = capacitybytes

            if "iOPerfModeEnabled" in options and options.iOPerfModeEnabled:
                for item in iOPerfModeEnabledlist:
                    if (
                        options.iOPerfModeEnabled[0].lower() == item.lower()
                        and options.iOPerfModeEnabled[0].lower() == "false"
                    ):
                        newdrive["IOPerfModeEnabled"] = eval(options.iOPerfModeEnabled[0])
                        itemadded = True
                        break
                    elif (
                        options.iOPerfModeEnabled[0].lower() == item.lower()
                        and options.iOPerfModeEnabled[0].lower() == "true"
                    ):
                        if "SSD" in controller["SupportedDeviceProtocols"]:
                            newdrive["IOPerfModeEnabled"] = eval(options.iOPerfModeEnabled[0])
                            itemadded = True
                            break
                        else:
                            raise InvalidCommandLineError(
                                " IOPerfModeEnabled can be true only when supported protocol is SSD"
                            )
                if not itemadded:
                    raise InvalidCommandLineError("Invalid IOPerfModeEnabled, Value should be either False or True")
                else:
                    itemadded = False

            if "ReadCachePolicy" in options and options.ReadCachePolicy is not None:
                for item in readCachePolicylist:
                    if options.ReadCachePolicy.lower() == item.lower():
                        newdrive["ReadCachePolicy"] = item
                        itemadded = True
                        break
                if not itemadded:
                    raise InvalidCommandLineError("Invalid ReadCachePolicy, Value should be 'Off' or 'ReadAhead'")
                else:
                    itemadded = False

            if "WriteCachePolicy" in options and options.WriteCachePolicy is not None:
                for item in writeCachePolicylist:
                    if options.WriteCachePolicy.lower() == item.lower():
                        newdrive["WriteCachePolicy"] = item
                        itemadded = True
                        break
                if not itemadded:
                    raise InvalidCommandLineError(
                        "Invalid WriteCachePolicy, Values should be 'Off', 'WriteThrough','ProtectedWriteBack',"
                        "'UnprotectedWriteBack'"
                    )
                else:
                    itemadded = False

            if "VROC" in controller["Model"]:
                if options.WriteHoleProtectionPolicy is not None:
                    for item in WriteHoleProtectionPolicyList:
                        if (
                            options.WriteHoleProtectionPolicy[0].lower() == item.lower()
                            and options.WriteHoleProtectionPolicy[0].lower() == "yes"
                        ):
                            newdrive["WriteHoleProtectionPolicy"] = "Journaling"
                            newdrive["Links"]["JournalingMedia"] = idval
                            itemadded = True
                            break
                    if not itemadded:
                        raise InvalidCommandLineError(
                            "Invalid WriteHoleProtectionPolicy, Values can be either Yes or No"
                        )
                    else:
                        itemadded = False
            if "drivename" in options and options.drivename:
                options.DisplayName = options.drivename
            if "DisplayName" in options and options.DisplayName is not None:
                newdrive["DisplayName"] = options.DisplayName

        if newdrive:
            if options.command == "quickdrive":
                newdrive_count = newdrive["DataDrives"]["DataDriveCount"]
            elif options.command == "customdrive":
                newdrive_count = len(newdrive["DataDrives"])
            elif options.command == "volume":
                newdrive_count = len(newdrive["Links"]["Drives"])

            if len(controller["physical_drives"]) >= newdrive_count:
                drives_avail = len(controller["physical_drives"])
                accepted_drives = 0
                for cnt, drive in enumerate(controller["physical_drives"]):
                    drivechecks = (False, False, False, False)
                    if drives_avail < newdrive_count:
                        raise InvalidSmartArrayConfigurationError(
                            "Unable to continue, requested "
                            "configuration not possible with current physical drive inventory.\n"
                        )
                    else:
                        drivechecks = (True, False, False, False)

                    if options.command == "quickdrive":
                        if (
                            controller["physical_drives"][drive]["InterfaceType"]
                            == newdrive["DataDrives"]["DataDriveInterfaceType"]
                        ):
                            drivechecks = (True, True, False, False)
                        else:
                            drives_avail -= 1
                            continue
                        if (
                            controller["physical_drives"][drive]["MediaType"]
                            == newdrive["DataDrives"]["DataDriveMediaType"]
                        ):
                            drivechecks = (True, True, True, False)
                        else:
                            drives_avail -= 1
                            continue
                    else:
                        drivechecks = (True, True, True, False)
                    in_use = False
                    if controller["logical_drives"] is not None:
                        for existing_logical_drives in controller["logical_drives"]:
                            _logical_drive = controller["logical_drives"][existing_logical_drives]
                            if _logical_drive.get("LogicalDrives"):
                                for _data_drive in _logical_drive["LogicalDrives"]["DataDrives"]:
                                    if drive == _logical_drive["LogicalDrives"]["DataDrives"][_data_drive]:
                                        in_use = True
                            elif _logical_drive.get("Links"):
                                if not ilo_ver >= 6.110:
                                    for _data_drive in _logical_drive["Links"]["DataDrives"]:
                                        if drive == _logical_drive["Links"]["DataDrives"][_data_drive]:
                                            in_use = True
                                else:
                                    for _data_drive in _logical_drive["Links"]["Drives"]:
                                        if drive == _data_drive:
                                            in_use = True
                            elif _logical_drive.get("links"):
                                for _data_drive in _logical_drive["links"]["DataDrives"]:
                                    if drive == _logical_drive["links"]["DataDrives"][_data_drive]:
                                        in_use = True
                    if in_use:
                        drives_avail -= 1
                        continue
                    else:
                        drivechecks = (True, True, True, True)
                    if drivechecks[0] and drivechecks[1] and drivechecks[2]:
                        if controller.get("Links"):
                            newdrive["Links"]["Drives"][int(drive)] = {
                                "@odata.id": controller["physical_drives"][drive]["@odata.id"]
                            }
                        else:
                            if not ilo_ver >= 6.110:
                                newdrive["links"]["DataDrives"][int(drive)] = controller["physical_drives"][drive]
                        accepted_drives += 1
                        changes = True
                        if accepted_drives == newdrive_count:
                            break
                    else:
                        drives_avail -= 1

            if changes:
                if self.rdmc.app.typepath.defs.isgen9:
                    controller["logical_drives"]["new"] = newdrive
                else:
                    if not ilo_ver >= 6.110:
                        try:
                            newdrive.pop("Links")
                        except KeyError:
                            newdrive.pop("links")
                    if not ilo_ver >= 6.110:
                        controller["LogicalDrives"].append(newdrive)
                    del controller["logical_drives"]
                    del controller["physical_drives"]

        return (changes, newdrive)

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

    def raidvalidation(self, raidtype, numdrives, options):
        """vaidation function for raid levels
        :param raidtype: raid type
        :type options: string.
        :param numdrives: number of drives
        :type numdrives: int.
        :param options: command line options
        :type options: list.
        """

        valid = True

        if raidtype == "raid5":
            if numdrives < 3:  # or options.stripsize:
                valid = False
        elif raidtype == "raid6":
            if numdrives < 4:  # or options.stripsize:
                valid = False
        elif raidtype == "raid50":
            if numdrives < 6:
                valid = False
        elif raidtype == "raid60":
            if numdrives < 8:
                valid = False

        return valid

    def createvolumevalidation(self, options):
        """Create volume validation function

        :param options: command line options
        :type options: list.
        """
        self.cmdbase.login_select_validation(self, options)

    @staticmethod
    def options_argument_group(parser):
        """Define optional arguments group

        :param parser: The parser to add the login option group to
        :type parser: ArgumentParser/OptionParser
        """
        group = parser.add_argument_group(
            "GLOBAL OPTIONS",
            "Options are available for all" "arguments within the scope of this command.",
        )

        group.add_argument(
            "--controller",
            dest="controller",
            help="Use this flag to select the corresponding controller "
            "using either the slot number or index.\nexample: --controller=Slot 0 OR "
            "--controller=1",
            default=None,
            required=True,
        )

    def definearguments(self, customparser):
        """Wrapper function for new command main function

        :param customparser: command line input
        :type customparser: parser.
        """
        if not customparser:
            return

        self.cmdbase.add_login_arguments_group(customparser)
        # self.options_argument_group(customparser)

        subcommand_parser = customparser.add_subparsers(dest="command")
        subcommand_parser.required = True
        qd_help = (
            "Create a volume with a minimal number of arguments (utilizes default "
            "values on the controller). This option is only for iLO5 or Gen10"
        )
        # quickdrive sub-parser
        qd_parser = subcommand_parser.add_parser(
            "quickdrive",
            help=qd_help,
            description=qd_help + "\n\texample: createvolume quickdrive "
            "<raid-level> <num-drives> <media-type> <interface-type> "
            "--locationtype=Internal  --minimumsize=0 --controller=1",
            formatter_class=RawDescriptionHelpFormatter,
        )
        qd_parser.add_argument(
            "raid",
            help="Specify the RAID level for the volume to be created.",
            metavar="Raid_Level",
        )
        qd_parser.add_argument(
            "disks",
            help="For quick drive creation, specify number of disks.",
            metavar="Drives",
        )
        qd_parser.add_argument(
            "drivetype",
            help="Specify the drive media type of the physical disk(s) (i.e. HDD or SSD)",
            metavar="Drive_Media_Type",
        )
        qd_parser.add_argument(
            "interfacetype",
            help="Specify the interface type of the physical disk(s) (i.e. SATA or SAS or NVMe)",
            metavar="Drive_Interface_Type",
        )
        qd_parser.add_argument(
            "--locationtype",
            dest="locationtype",
            help="Optionally specify the location of the physical disks(s) (i.e. Internal or External)",
            default=None,
        )
        qd_parser.add_argument(
            "--minimumsize",
            dest="minimumsize",
            help="""Optionally include to set the minimum size of the drive """
            """in GiB. (usable in quick creation only, use -1 for max size)""",
            default=None,
        )
        qd_parser.add_argument(
            "--controller",
            dest="controller",
            help="Use this flag to select the corresponding controller "
            "using either the slot number or index.\nexample: --controller=Slot 0 OR "
            "--controller=1",
            default=None,
            required=True,
        )
        qd_parser.add_argument(
            "--storageid",
            dest="storageid",
            help="Use this flag to select the corresponding storageid "
            "using either the slot number or index.\nexample: --storageid=DE123234",
            default=None,
            required=False,
        )
        self.cmdbase.add_login_arguments_group(qd_parser)
        # self.options_argument_group(qd_parser)

        cd_help = (
            "Create a customised volume using all available properties (as optional "
            "arguments) for creation. This option is only for iLO5 or Gen10"
        )
        # customdrive sub-parser
        cd_parser = subcommand_parser.add_parser(
            "customdrive",
            help=cd_help,
            description=cd_help + "\n\texample: createvolume customdrive "
            "<raid-level> <physicaldrivelocations> --controller=1 "
            "--name=drivename --spare-drives=1I:1:1,1I:1:3 "
            "--spare-type=Dedicated --capacitygib=10 "
            "--accelerator-type=None\n\n\tOPTIONS:\n\traid-level:\t\t"
            "Raid0, Raid1, Raid1ADM, Raid10, Raid10ADM, Raid5, Raid50, "
            "Raid6, Raid60\n\tphysicaldrivelocation(s):\tLocation, Drive-name\n\t"
            "media-type:\t\tSSD,HDD\n\tinterface-type:"
            "\t\tSAS, SATA, NVMe\n\tdrive-location:\t\tInternal, External\n\t"
            "--spare-type:\t\tDedicated, Roaming\n\t--accelerator-type:\t"
            "ControllerCache, IOBypass, None\n\t--paritytype:\t\tDefault, Rapid"
            "\n\t--capacitygib:\t\t-1 (for Max Size)\n\t--capacityblocks:\t"
            "-1 (for Max Size)\n\n\t",
            formatter_class=RawDescriptionHelpFormatter,
        )
        cd_parser.add_argument(
            "raid",
            help="Specify the RAID level for the volume to be created.",
            metavar="Raid_Level",
        )
        cd_parser.add_argument(
            "disks",
            help="For custom drive, specify a comma separated physical disk locations.",
            metavar="Drive_Indices",
        )
        cd_parser.add_argument(
            "-n",
            "--name",
            dest="drivename",
            help="""Optionally include to set the drive name (usable in """ """custom creation only).""",
            default=None,
        )
        cd_parser.add_argument(
            "--spare-drives",
            dest="sparedrives",
            help="""Optionally include to set the spare drives by the """
            """physical drive's location. (usable in custom creation only)""",
            default=None,
        )
        cd_parser.add_argument(
            "--capacitygib",
            dest="capacitygib",
            help="""Optionally include to set the capacity of the drive in """
            """GiB. (usable in custom creation only, use -1 for max """
            """size)""",
            default=None,
        )
        cd_parser.add_argument(
            "--accelerator-type",
            dest="acceleratortype",
            help="""Optionally include to choose the accelerator type.""",
            default=None,
        )
        cd_parser.add_argument(
            "--spare-type",
            dest="sparetype",
            help="""Optionally include to choose the spare drive type. """ """(usable in custom creation only)""",
            default=None,
        )
        cd_parser.add_argument(
            "--minimumsize",
            dest="minimumsize",
            help="""Optionally include to set the minimum size of the drive """
            """in GiB. (usable in quick creation only, use -1 for max size)""",
            default=None,
        )
        cd_parser.add_argument(
            "--legacy-boot",
            dest="legacyboot",
            help="""Optionally include to choose the legacy boot priority. """ """(usable in custom creation only)""",
            default=None,
        )
        cd_parser.add_argument(
            "--storageid",
            dest="storageid",
            help="Use this flag to select the corresponding storageid "
            "using either the slot number or index.\nexample: --storageid=DE123234",
            default=None,
            required=False,
        )
        cd_parser.add_argument(
            "--capacityblocks",
            dest="capacityblocks",
            help="""Optionally include to choose the capacity in blocks. """
            """(use -1 for max size, usable in custom creation only)""",
            default=None,
        )
        cd_parser.add_argument(
            "--paritygroupcount",
            dest="paritygroup",
            help="""Optionally include to include the number of parity """
            """groups to use. (only valid for certain RAID levels)""",
            default=None,
        )
        cd_parser.add_argument(
            "--paritytype",
            dest="paritytype",
            help="""Optionally include to choose the parity initialization"""
            """ type. (usable in custom creation only)""",
            default=None,
        )
        cd_parser.add_argument(
            "--block-size-bytes",
            dest="blocksize",
            help="""Optionally include to choose the block size of the disk"""
            """ drive. (usable in custom creation only)""",
            default=None,
        )
        cd_parser.add_argument(
            "--strip-size-bytes",
            dest="stripsize",
            help="""Optionally include to choose the strip size in bytes. """ """(usable in custom creation only)""",
            default=None,
        )
        cd_parser.add_argument(
            "--stripe-size-bytes",
            dest="stripesize",
            help="""Optionally include to choose the stripe size in bytes. """ """(usable in custom creation only)""",
            default=None,
        )
        cd_parser.add_argument(
            "--controller",
            dest="controller",
            help="Use this flag to select the corresponding controller "
            "using either the slot number or index.\nexample: --controller=Slot 0 OR "
            "--controller=1",
            default=None,
            required=True,
        )
        self.cmdbase.add_login_arguments_group(cd_parser)
        # self.options_argument_group(cd_parser)
        v_help = (
            "Create a volume using all available properties (as optional "
            "arguments) for creation on gen 11 or higher "
        )
        # volume sub-parser
        v_parser = subcommand_parser.add_parser(
            "volume",
            help=v_help,
            description=v_help + "\n\texample: createvolume volume "
            "<raid-level> <physicaldrivelocations> <displayname> "
            "<iOPerfModeEnabled> <readCachePolicy> "
            "<writeCachePolicy> <WriteHoleProtectionPolicy> --storageid=DE009000 --controller=0 "
            "<spare-drives> <capacitygib> "
            "\n\n\t",
            formatter_class=RawDescriptionHelpFormatter,
        )
        v_parser.add_argument(
            "raid",
            help="Specify the RAID level for the volume to be created.",
            metavar="Raid_Level",
        )
        v_parser.add_argument(
            "disks",
            help="For custom drive, specify a comma separated physical disk locations.",
            metavar="Drive_Indices",
        )
        v_parser.add_argument(
            "--storageid",
            dest="storageid",
            help="Use this flag to select the corresponding storageid "
            "using either the slot number or index.\nexample: --storageid=DE123234",
            default=None,
            required=True,
        )
        v_parser.add_argument(
            "--DisplayName",
            dest="DisplayName",
            help="""Optionally include to set the drive name """,
            default=None,
        )
        v_parser.add_argument(
            "--iOPerfModeEnabled",
            dest="iOPerfModeEnabled",
            help="""Optionally include to choose the IOPerfModeEnabled . Allowed values are 'True', 'False'""",
            default=None,
        )
        v_parser.add_argument(
            "--ReadCachePolicy",
            dest="ReadCachePolicy",
            help="""Optionally include to choose the ReadCachePolicy. """ """Allowed values are 'Off', 'ReadAhead'""",
            default=None,
        )
        v_parser.add_argument(
            "--WriteCachePolicy",
            dest="WriteCachePolicy",
            help="Optionally include to set the WriteCachePolicy "
            "Allowed values are 'Off', 'WriteThrough','ProtectedWriteBack','UnprotectedWriteBack'",
            default=None,
        )
        v_parser.add_argument(
            "--WriteHoleProtectionPolicy",
            dest="WriteHoleProtectionPolicy",
            help="""Optionally include to choose the WriteHoleProtectionPolicy """
            """this is applicable only for VROC, You can send either Yes or No as values""",
            default=None,
        )
        v_parser.add_argument(
            "--sparedrives",
            dest="sparedrives",
            help="""Optionally include to set the spare drives by the """
            """physical drive's location. (usable in custom creation only)""",
            action="append",
            default=None,
        )
        v_parser.add_argument(
            "--capacitybytes",
            dest="capacitybytes",
            help="""Optionally include to set the capacity of the drive in """
            """bytes. (usable in custom creation only, use -1 for max """
            """size)""",
            action="append",
            default=None,
        )
        v_parser.add_argument(
            "--controller",
            dest="controller",
            help="Use this flag to select the corresponding controller "
            "using either the slot number or index.\nexample: --controller=Slot 0 OR "
            "--controller=1",
            default=None,
            required=True,
        )

        self.cmdbase.add_login_arguments_group(v_parser)
        # self.options_argument_group(v_parser)
