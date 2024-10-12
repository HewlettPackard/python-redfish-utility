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
""" Storage Controller Command for rdmc """
import json
import sys
from argparse import RawDescriptionHelpFormatter

import redfish

try:
    from rdmc_helper import (
        UI,
        Encryption,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        InvalidFileInputError,
        ReturnCodes,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        ReturnCodes,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        UI,
        InvalidFileInputError,
        Encryption,
    )

from redfish.ris.resp_handler import ResponseHandler

# from redfish.ris.utils import iterateandclear

__config_file__ = "storagecontroller_config.json"

# from rdmc_base_classes import HARDCODEDLIST

__subparsers__ = ["load", "save", "state"]


class StorageControllerCommand:
    """Storage controller command"""

    def __init__(self):
        self.ident = {
            "name": "storagecontroller",
            "usage": None,
            "description": "\tTo Manage PLDM for RDE storage devices. For other storage devices (i.e NVMe),"
            "use the `select type/get/set` paradigm or raw commands.\n\n"
            "\tRun without arguments for the "
            "current list of Storage controllers.\n\texample: "
            "storagecontroller\n\n\tTo get more details on a specific controller "
            "select it by index Note: On ILO6, --storageid is mandatory along with --controller.\n\t"
            "example: storagecontroller --storageid=DE00E000 --controller=2"
            "\n\n\tTo get more details on a specific controller select "
            'it by location.\n\texample: storagecontroller --storageid=DE00E000 --controller "Slot 0"'
            "\n\n\tIn order to get a list of all physical drives for "
            "each controller.\n\texample: storagecontroller --physicaldrives"
            "\n\n\tTo obtain details about physical drives for a "
            "specific controller.\n\texample: storagecontroller --storageid=DE00E000 --controller=3 "
            "--physicaldrives\n\n\tTo obtain details about a specific "
            "physical drive for a specific controller.\n\texample: storagecontroller "
            "--storageid=DE00E000 --controller=3 --pdrive=1I:1:1\n\n\tIn order to get a list of "
            "all volumes for the each controller.\n\texample: "
            "storagecontroller --logicaldrives\n\n\tTo obtain details about "
            "volumes for a specific controller.\n\texample: "
            "storagecontroller --storageid=DE00E000 --controller=3 --logicaldrives\n\n\tTo obtain "
            "details about a specific volume for a specific "
            "controller.\n\texample: storagecontroller --storageid=DE00E000 --controller=3 --ldrive=1\n\n\tTo obtain "
            "details about a specific Storage id for a specific "
            "controllers.\n\texample: storagecontroller --storageid=DE00E000\n",
            "summary": "Discovers all storage controllers installed in the " "server and managed by the SmartStorage.",
            "aliases": ["smartarray"],
            "auxcommands": ["SelectCommand"],
        }
        self.config_file = None
        self.fdata = None
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def file_handler(self, filename, operation, options, data=None, sk=None):
        """
        Wrapper function to read or write data to a respective file

        :param data: data to be written to output file
        :type data: container (list of dictionaries, dictionary, etc.)
        :param file: filename to be written
        :type file: string (generally this should be self.clone_file or tmp_clone_file
        :param operation: file operation to be performed
        :type operation: string ('w+', 'a+', 'r+')
        :param sk: sort keys flag
        :type sk: boolean
        :param options: command line options
        :type options: attribute
        :returns: json file data
        """
        writeable_ops = ["w", "w+", "a", "a+"]
        fdata = None

        try:
            if operation in writeable_ops:
                if getattr(options, "encryption", False):
                    with open(filename, operation + "b") as outfile:
                        outfile.write(
                            Encryption().encrypt_file(
                                json.dumps(
                                    data,
                                    indent=2,
                                    cls=redfish.ris.JSONEncoder,
                                    sort_keys=sk,
                                ),
                                getattr(options, "encryption", False),
                            )
                        )
                else:
                    with open(filename, operation) as outfile:
                        outfile.write(
                            json.dumps(
                                data,
                                indent=2,
                                cls=redfish.ris.JSONEncoder,
                                sort_keys=sk,
                            )
                        )
            else:
                if getattr(options, "encryption", False):
                    with open(filename, operation + "b") as file_handle:
                        fdata = json.loads(
                            Encryption().decrypt_file(
                                file_handle.read(),
                                getattr(options, "encryption", False),
                            )
                        )
                else:
                    with open(filename, operation) as file_handle:
                        fdata = json.loads(file_handle.read())
                return fdata
        except Exception as excp:
            raise InvalidFileInputError(
                "Unable to open file: %s.\nVerify the file location " "and the file has a valid JSON format.\n" % excp
            )

    def controller_id(self, options):
        """
        Get iLO types from server and save storageclone URL get Controller
        :parm options: command line options
        :type options: attribute
        :returns: returns list
        """
        self.auxcommands["select"].selectfunction("StorageControllerCollection.")
        ctr_content = self.rdmc.app.getprops()
        ctrl_data = []
        all_ctrl = dict()
        for ct_controller in ctr_content:
            path = ct_controller["Members"]
            for i in path:
                res = i["@odata.id"]
                ctrl_data.append(res)
                ctrl_id_url = res + "?$expand=."
                get_ctr = self.rdmc.app.get_handler(ctrl_id_url, silent=True, service=True).dict
                _ = get_ctr["@odata.id"].split("/")
                get_ctr = self.rdmc.app.removereadonlyprops(get_ctr, False, True)
                all_ctrl[get_ctr["Name"]] = get_ctr
        return all_ctrl

    def get_volume(self, options):
        """
        Get iLO types from server and save storageclone URL get volumes
        :parm options: command line options
        :type options: attribute
        :returns: returns list
        """
        self.auxcommands["select"].selectfunction("VolumeCollection.")
        vol_content = self.rdmc.app.getprops()
        vol_data = []
        all_vol = dict()
        for st_volume in vol_content:
            path = st_volume["Members"]
            for i in path:
                res = i["@odata.id"]
                if self.rdmc.opts.verbose:
                    sys.stdout.write("Saving properties of type %s \t\n" % res)
                vol_data.append(res)
                vol_id_url = res + "?$expand=."
                get_vol = self.rdmc.app.get_handler(vol_id_url, silent=True, service=True).dict
                # print("Assigned drive", get_vol["Links"]["Drives"])
                get_vol = self.rdmc.app.removereadonlyprops(get_vol, False, True)
                all_vol[get_vol["Name"]] = get_vol
        return all_vol

    def run(self, line, help_disp=False):
        """Main sstorage controller worker function
        :param help_disp: command line input
        :type help_disp: bool.
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
            ident_subparser = False
            for cmnd in __subparsers__:
                if cmnd in line:
                    (options, args) = self.rdmc.rdmc_parse_arglist(self, line)
                    ident_subparser = True
                    break
            if not ident_subparser:
                (options, args) = self.rdmc.rdmc_parse_arglist(self, line, default=True)
        except (InvalidCommandLineErrorOPTS, SystemExit):
            if ("-h" in line) or ("--help" in line):
                return ReturnCodes.SUCCESS
            else:
                raise InvalidCommandLineErrorOPTS("")

        self.storagecontrollervalidation(options)
        ilo_ver = self.rdmc.app.getiloversion()

        if options.command == "state":
            if not options.storageid:
                raise InvalidCommandLineError("Please provide --storageid option.\n")
            if ilo_ver >= 6:
                storage_ctlr = self.storagecontroller(options, print_ctrl=False, single_use=True)
                for storage in storage_ctlr:
                    if storage_ctlr[storage].get("@Redfish.Settings"):
                        time = storage_ctlr[storage]["@Redfish.Settings"].get("Time", "Not Available")
                        sys.stdout.write("Last Configuration Attempt: %s\n" % str(time))
                        for message in storage_ctlr[storage]["@Redfish.Settings"].get("Messages", []):
                            ResponseHandler(
                                self.rdmc.app.validationmanager,
                                self.rdmc.app.typepath.defs.messageregistrytype,
                            ).message_handler(
                                response_data=message,
                                message_text="",
                                verbosity=2,
                                dl_reg=False,
                            )
                    else:
                        sys.stdout.write(
                            "Previous storage controller configuration status messages are "
                            "not available for controller '%s'\n" % (storage)
                        )
                        ctrl_data = dict()
                        ctrl_data.update({"Location": storage_ctlr[storage].get("Location", "Unknown")})
                        ctrl_data.update({"Model": storage_ctlr[storage].get("Model", "Unknown")})
                        UI().print_out_json(ctrl_data)

            else:
                controllers = self.controllers(options, print_ctrl=False, single_use=True)
                for controller in controllers:
                    if controllers[controller].get("@Redfish.Settings"):
                        time = controllers[controller]["@Redfish.Settings"].get("Time", "Not Available")
                        sys.stdout.write("Last Configuration Attempt: %s\n" % str(time))
                        for message in controllers[controller]["@Redfish.Settings"].get("Messages", []):
                            ResponseHandler(
                                self.rdmc.app.validationmanager,
                                self.rdmc.app.typepath.defs.messageregistrytype,
                            ).message_handler(
                                response_data=message,
                                message_text="",
                                verbosity=2,
                                dl_reg=False,
                            )
                    else:
                        sys.stdout.write(
                            "Previous storage controller configuration status messages are "
                            "not available for controller '%s'\n" % (controller)
                        )
                        ctrl_data = dict()
                        ctrl_data.update({"Location": controllers[controller].get("Location", "Unknown")})
                        ctrl_data.update({"Model": controllers[controller].get("Model", "Unknown")})
                        UI().print_out_json(ctrl_data)

        if options.command == "save":
            if ilo_ver >= 6.110:
                storage = {}
                all_stgcntrl = {}
                st_content = self.rdmc.app.get_handler("/redfish/v1/Systems/1/Storage/", silent=True, service=True).dict
                sel = st_content["Members"]
                for i in sel:
                    res = i["@odata.id"]
                    if "DE" in res:
                        break
                    else:
                        continue
                storage_id_url = res + "?$expand=."
                getval = self.rdmc.app.get_handler(storage_id_url, silent=True, service=True).dict
                vol = self.get_volume(options)
                ctr = self.controller_id(options)
                getval = self.rdmc.app.removereadonlyprops(getval, False, True)
                storage.update(getval)
                getval["Controllers"]["Members"].append(ctr)
                del getval["Controllers"]["Members"][0]
                getval["Volumes"]["Members"].append(vol)
                del getval["Volumes"]["Members"][0]
                all_stgcntrl[getval["Id"]] = getval
                self.file_handler(self.config_file, "w", options, all_stgcntrl, sk=True)
                sys.stdout.write("Storage Controller configuration saved to '%s'.\n" % self.config_file)
            else:
                st_content = self.rdmc.app.get_handler("/redfish/v1/Systems/1/Storage/", silent=True, service=True).dict
                sel = st_content["Members"]
                for i in sel:
                    res = i["@odata.id"]
                    if "DE" in res:
                        break
                    else:
                        continue
                storage = {}
                all_stgcntrl = {}
                storage_id_url = res + "?$expand=."
                getval = self.rdmc.app.get_handler(storage_id_url, silent=True, service=True).dict
                vol = self.get_volume(options)
                ctr = self.controller_id(options)
                getval = self.rdmc.app.removereadonlyprops(getval, False, True)
                storage.update(getval)
                getval["Controllers"]["Members"].append(ctr)
                del getval["Controllers"]["Members"][0]
                getval["Volumes"]["Members"].append(vol)
                del getval["Volumes"]["Members"][0]
                all_stgcntrl[getval["Id"]] = getval
                self.file_handler(self.config_file, "w", options, all_stgcntrl, sk=True)
                sys.stdout.write("Storage Controller configuration saved to '%s'.\n" % self.config_file)
                controllers = self.controllers(options, print_ctrl=False, single_use=True)
                for key, controller in controllers.items():
                    physical_drives = self.physical_drives(options, controller, print_ctrl=False, single_use=True)
                    logical_drives = self.logical_drives(options, controller, print_ctrl=False, single_use=True)
                    if self.rdmc.app.typepath.defs.isgen10:
                        for drivec_idx, drivec in enumerate(controller.get("PhysicalDrives", [])):
                            for drive in physical_drives:
                                if drivec["Location"] == physical_drives[drive]["Location"]:
                                    controller["PhysicalDrives"][drivec_idx].update(physical_drives[drive])
                                    break
                        for drivec_idx, drivec in enumerate(controller.get("LogicalDrives", [])):
                            for drive in logical_drives:
                                if drivec["LogicalDriveNumber"] == logical_drives[drive]["Id"]:
                                    controller["LogicalDrives"][drivec_idx].update(logical_drives[drive])
                                    break
                    if controller.get("Links"):
                        controller["Links"]["LogicalDrives"] = logical_drives
                        controller["Links"]["PhysicalDrives"] = physical_drives
                    else:
                        controller["links"]["LogicalDrives"] = logical_drives
                        controller["links"]["PhysicalDrives"] = physical_drives

                self.file_handler(self.config_file, "w", options, controllers, sk=True)
                sys.stdout.write("Storage Controller configuration saved to '%s'.\n" % self.config_file)

        if options.command == "load":
            if ilo_ver >= 6.110:
                storage_load = self.file_handler(self.config_file, operation="rb", options=options)
                controller_id = storage_load["Controllers"]
                logical_id = storage_load["Volumes"]
                physical_id = storage_load["Drives"]
                if controller_id:
                    for data in controller_id:
                        id_controller = controller_id[data].get("@odata.id")
                        controllers = self.rdmc.app.get_handler(id_controller, silent=True).dict
                        readonly_removed_controllers = self.storagecontrollerremovereadonly(controllers)
                        readonly_removed = storage_load["Controllers"]
                        for controller, val in readonly_removed.items():
                            for i in readonly_removed_controllers:
                                try:
                                    if (i in val) and (controllers[i] != val[i]):
                                        body = {str(i): val[i]}
                                        self.rdmc.app.patch_handler(id_controller, body)
                                except:
                                    sys.stdout.write("Unable to update the property " "for: '%s'.\n" % i)
                                    continue
                if logical_id:
                    for logical_data in logical_id:
                        id_logical = logical_id[logical_data].get("@odata.id")
                        logicals = self.rdmc.app.get_handler(id_logical, silent=True).dict
                        readonly_removed_logical = self.storagecontrollerremovereadonly(logicals)
                        readonly_logical = storage_load["Volumes"]
                        for logical, val in readonly_logical.items():
                            for lg in readonly_removed_logical:
                                try:
                                    if (lg in val) and (logicals[lg] != val[lg]):
                                        body = {str(lg): val[lg]}
                                        self.rdmc.app.patch_handler(id_logical, body)
                                except:
                                    sys.stdout.write("Unable to update the property " "for: '%s'.\n" % lg)
                                    continue
                if physical_id:
                    for physical_data in physical_id:
                        id_physical = physical_id[physical_data].get("@odata.id")
                        physicals = self.rdmc.app.get_handler(id_physical, silent=True).dict
                        readonly_removed_physical = self.storagecontrollerremovereadonly(physicals)
                        readonly_physical = storage_load["Drives"]
                        for logical, val in readonly_physical.items():
                            for lg in readonly_removed_physical:
                                try:
                                    if (lg in val) and (physicals[lg] != val[lg]):
                                        body = {str(lg): val[lg]}
                                        self.rdmc.app.patch_handler(id_physical, body)
                                except:
                                    sys.stdout.write("Unable to update the property " "for: '%s'.\n" % lg)
                                    continue
                sys.stdout.write(
                    "Storage Controller configuration loaded. Reboot the server to " "finalize the configuration.\n"
                )

            else:
                controllers = self.file_handler(self.config_file, operation="rb", options=options)

                for controller in controllers:
                    put_path = controllers[controller]["@Redfish.Settings"]["SettingsObject"]["@odata.id"]
                    if controllers[controller].get("DataGuard"):
                        controllers[controller]["DataGuard"] = "Disabled"
                        readonly_removed = self.rdmc.app.removereadonlyprops(controllers[controller])
                        readonly_removed["LogicalDrives"] = controllers[controller]["LogicalDrives"]
                        readonly_removed["PhysicalDrives"] = controllers[controller]["PhysicalDrives"]
                        # self.rdmc.app.put_handler(controllers[controller]["@odata.id"], readonly_removed)
                        self.rdmc.app.put_handler(put_path, readonly_removed)

                        sys.stdout.write(
                            "Storage Controller configuration loaded. Reboot the server to "
                            "finalize the configuration.\n"
                        )
        elif options.command == "default":
            if ilo_ver >= 6:
                if options.storageid and not options.controller:
                    self.storageid(options, print_ctrl=True, single_use=False)
                elif options.storageid and options.controller:
                    self.storagecontroller(options, print_ctrl=True, single_use=False)
                elif options.controller and not options.storageid:
                    raise InvalidCommandLineError(
                        "with --controller option, --storageid option is mandatory for 'iLO 6' and 'iLO 5'.\n"
                    )
                elif (
                    options.physicaldrives or options.pdrive or options.logicaldrives or options.ldrive
                ) and not options.storageid:
                    raise InvalidCommandLineError("--storageid option is mandatory for 'iLO 6' and 'iLO 5'.\n")
                elif (
                    not options.storageid
                    and not options.controller
                    and not options.physicaldrives
                    and not options.pdrive
                    and not options.logicaldrives
                    and not options.ldrive
                ):
                    self.list_all_storages(options, print_ctrl=True, single_use=False)
            else:
                self.controllers(options, print_ctrl=True, single_use=False)

        self.cmdbase.logout_routine(self, options)
        # Return code
        return ReturnCodes.SUCCESS

    def list_all_storages(self, options, print_ctrl=False, single_use=False):
        # self.auxcommands["select"].selectfunction("StorageCollection.")
        st_url = "/redfish/v1/Systems/1/Storage/"
        st_content = self.rdmc.app.get_handler(st_url, silent=True, service=True)
        if "error" not in st_content.dict:
            if st_content.dict["Members@odata.count"] == 0:
                raise InvalidCommandLineError("Redfish Enabled Controllers not found in this server.\n")
            if st_content.dict["Members"]:
                st_content = st_content.dict["Members"]

                if not options.json:
                    if self.rdmc.opts.verbose:
                        sys.stdout.write("---------------------------------\n")
                        sys.stdout.write("List of RDE storage devices\n")
                        sys.stdout.write("---------------------------------\n")
                if options.json:
                    outjson = dict()
                for st_controller in st_content:
                    for val in st_controller.values():
                        if "DE" in val:
                            st = self.rdmc.app.get_handler(val, silent=True, service=True).dict
                            health = ""
                            if "Health" in st["Status"]:
                                health = st["Status"]["Health"]
                            elif "HealthRollup" in st["Status"]:
                                health = st["Status"]["HealthRollup"]
                            if options.json:
                                outjson[st["Id"]] = dict()
                                outjson[st["Id"]]["Name"] = st["Name"]
                                outjson[st["Id"]]["Health"] = health
                                outjson[st["Id"]]["State"] = st["Status"]["State"]
                            else:
                                sys.stdout.write(
                                    "%s: %s: Health %s: %s\n" % (st["Id"], st["Name"], health, st["Status"]["State"])
                                )

                if options.json:
                    UI().print_out_json(outjson)
            else:
                raise InvalidCommandLineError(
                    "Storage controllers are not ready , Kindly re run the command after sometime\n"
                )
        else:
            raise InvalidCommandLineError(
                "Storage controllers are not ready , " "Kindly re run the command after sometime\n"
            )

    def storagecontrollerremovereadonly(self, controller):
        templist = [
            "Ports",
            "CacheSummary",
            "SupportedRAIDTypes",
            "PCIeInterface",
            "SupportedControllerProtocols",
            "SupportedDeviceProtocols",
            "SKU",
            "SpeedGbps",
            "SerialNumber",
            "PartNumber",
            "Model",
            "@odata.etag",
            "Status",
            "Manufacturer",
            "Location",
            "Identifiers",
            "FirmwareVersion",
            "Name",
            "Id",
            "@odata.type",
            "@odata.id",
            "Links",
        ]

        remove_data = self.rdmc.app.removereadonlyprops(controller, False, True, templist)
        return remove_data

    def odataremovereadonly(self, tmp):
        templist = [
            "@odata.etag",
            "@odata.type",
            "@odata.context",
        ]
        remove_data = self.rdmc.app.removereadonlyprops(tmp, False, True, templist)
        return remove_data

    def controllers(self, options, print_ctrl=False, single_use=False):
        """
        Identify/parse volumes (and child properties) of a parent array controller

        :param options: command line options (options.controller is a required attribute)
        :type options: object attributes
        :param print_ctrl: flag for console print enablement/disablement (default disabled)
        :type print_ctrl: bool
        :param single_use: singular usage - True or explore mode - False,
        returns dictionary of results to calling function (default disabled) - see returns.
        :type single_use: bool
        :returns: None, dictionary of all controllers identified by 'Id'
        """
        no_need_ilo5 = False
        if getattr(options, "controller", False):
            controller_ident = False

        if (
            not (getattr(options, "json", False))
            and not (getattr(options, "controller", False))
            and print_ctrl
            and (options.physicaldrives is None)
            and (options.pdrive is None)
            and (options.logicaldrives is None)
            and (options.ldrive is None)
        ):
            if not options.storageid and not options.controllers:
                sys.stdout.write("---------------------------------\n")
                sys.stdout.write("List of RDE storage devices\n")
                sys.stdout.write("---------------------------------\n")

        st_flag = False
        storage_data = {}
        get_contrller = []
        list_storageid = self.rdmc.app.get_handler("/redfish/v1/Systems/1/Storage/", silent=True, service=True)
        if "error" not in list_storageid.dict:
            if list_storageid.dict["Members@odata.count"] == 0:
                raise InvalidCommandLineError("Redfish Enabled Controllers not found in this server.\n")
            if len(list_storageid.dict["Members"]) > 0:
                list_storageid = list_storageid.dict["Members"]
                for val in list_storageid:
                    storageid_fromurl = val["@odata.id"]
                    # storageid_fromurl = val.split("/")[-2]
                    try:
                        stdout = "DE" in storageid_fromurl and options.storageid in storageid_fromurl
                    except:
                        stdout = "DE" in storageid_fromurl
                    if "DE" in storageid_fromurl and stdout:
                        st_flag = True
                        getval = self.rdmc.app.get_handler(storageid_fromurl, silent=True, service=True).dict
                        try:
                            controller = getval["Controllers"]
                            volumes = getval["Volumes"]
                            list_controllers = self.rdmc.app.get_handler(
                                controller["@odata.id"], silent=True, service=True
                            ).dict
                            list_volumes = self.rdmc.app.get_handler(
                                volumes["@odata.id"], silent=True, service=True
                            ).dict
                        except KeyError:
                            self.rdmc.ui.printer("Please check controller was Gen11.\n")
                            return ReturnCodes.NO_CONTENTS_FOUND_FOR_OPERATION

                        for ctl in list_controllers["Members"]:
                            ctl = ctl["@odata.id"]
                            get_sel = self.rdmc.app.get_handler(ctl, silent=True, service=True)
                            get_contrller.append(get_sel)
                    else:
                        continue
                if not st_flag:
                    raise InvalidCommandLineError(
                        "Storage ID {} not found or Storage ID is not Redfish enabled "
                        "and does not have DExxxxxx\n".format(options.storageid)
                    )
                    return
                no_need_ilo5 = True
                outjson = dict()
                for sel in get_contrller:
                    if "Collection" not in sel.path:
                        controller = sel.dict
                        storage_id = controller["@odata.id"].split("/")
                        storage_id = storage_id[6]
                        if getattr(options, "controller", False):
                            if (
                                getattr(options, "controller", False) == controller["Id"]
                                or getattr(options, "controller", False)[-1]
                                == controller["Location"]["PartLocation"]["ServiceLabel"][-1]
                            ):
                                controller_ident = True
                            else:
                                continue
                        if (
                            print_ctrl
                            and not getattr(options, "controller", False)
                            and not getattr(options, "physicaldrives", False)
                            and not getattr(options, "pdrive", False)
                            and not getattr(options, "ldrive", False)
                            and not getattr(options, "logicaldrives", False)
                            and options.storageid is None
                            and not options.json
                            and not getattr(options, "controllers", False)
                        ):
                            health = ""
                            if "Health" in controller["Status"]:
                                health = controller["Status"]["Health"]
                            elif "HealthRollup" in controller["Status"]:
                                health = controller["Status"]["HealthRollup"]
                            sys.stdout.write(
                                "%s: %s: Health %s: %s\n"
                                % (storage_id, controller["Model"], health, controller["Status"]["State"])
                            )
                        elif (
                            getattr(options, "json", False)
                            and (options.controller is None)
                            and (options.physicaldrives is None)
                            and (options.pdrive is None)
                            and (options.ldrive is None)
                            and (options.logicaldrives is None)
                            and options.storageid is None
                            and options.json
                            and not options.controllers
                        ):
                            tmp = dict()
                            tmp["Name"] = controller["Name"]
                            tmp["State"] = controller["Status"]["Health"]
                            tmp["Health"] = controller["Status"]["State"]
                            outjson[storage_id] = tmp

                        if (
                            not getattr(options, "json", False)
                            and options.storageid
                            and not getattr(options, "controllers", False)
                            and not getattr(options, "physicaldrives", False)
                            and not getattr(options, "logicaldrives", False)
                            and not getattr(options, "ldrive", False)
                            and not getattr(options, "pdrive", False)
                            and not getattr(options, "controller", False)
                            and options.command not in "state"
                        ):
                            sys.stdout.write("-----------------------------------\n")
                            sys.stdout.write("Details of Storage %s\n" % options.storageid)
                            sys.stdout.write("-----------------------------------\n")
                            sys.stdout.write("\tId: %s\n\t" % getval["Id"])
                            sys.stdout.write("Health: %s\n\t" % getval["Status"]["HealthRollup"])
                            sys.stdout.write("Name: %s\n\t" % getval["Name"])
                            sys.stdout.write("Number of Controllers: %s\n\t" % list_controllers["Members@odata.count"])
                            sys.stdout.write("Number of Volumes: %s\n\t" % list_volumes["Members@odata.count"])
                            sys.stdout.write("Number of Drives: %s\n\t\n" % getval["Drives@odata.count"])
                        if (
                            getattr(options, "json", False)
                            and options.storageid
                            and options.json
                            and not options.physicaldrives
                            and not options.logicaldrives
                            and not options.ldrive
                            and not options.pdrive
                            and not options.controller
                            and not options.controllers
                        ):
                            storage_data["Storage"] = dict()

                            storage_data["Storage"].update({"Id": getval["Id"]})
                            storage_data["Storage"].update({"Health": getval["Status"]["HealthRollup"]})
                            storage_data["Storage"].update({"Name": getval["Name"]})
                            storage_data["Storage"].update(
                                {"Number of Controllers": list_controllers["Members@odata.count"]}
                            )
                            storage_data["Storage"].update({"Number of Volumes": list_volumes["Members@odata.count"]})
                            storage_data["Storage"].update({"Number of Drives": getval["Drives@odata.count"]})
                            UI().print_out_json(storage_data)
                        elif (
                            # print_ctrl
                            getattr(options, "json", False)
                            and (options.controller is not None)
                            and (
                                (options.logicaldrives is not None)
                                or (options.physicaldrives is not None)
                                or (options.ldrive is not None)
                                or (options.pdrive is not None)
                            )
                        ):
                            pass

                        elif (
                            getattr(options, "json", False)
                            and (options.controller is not None)
                            and (
                                (options.logicaldrives is not None)
                                or (options.physicaldrives is not None)
                                or (options.ldrive is not None)
                                or (options.pdrive is not None)
                            )
                        ):
                            pass
                        # controllers code with json and without json
                        elif (
                            getattr(options, "controllers", False)
                            and options.storageid
                            and options.controllers
                            and options.json is None
                        ):
                            sys.stdout.write("---------------------------------------------------\n")
                            sys.stdout.write("List of Controllers in this Storage ID %s\n" % options.storageid)
                            sys.stdout.write("---------------------------------------------------\n")
                            list_ctr = list_controllers["Members"]
                            for lst in list_ctr:
                                l_data = lst["@odata.id"]
                                get_ctr = self.rdmc.app.get_handler(l_data, silent=True, service=True).dict
                                sys.stdout.write("\tId: %s\n\t" % get_ctr["Id"])
                                sys.stdout.write("Health: %s\n\t" % get_ctr["Status"]["Health"])
                                sys.stdout.write("Name: %s\n\t" % get_ctr["Name"])
                                sys.stdout.write("FirmwareVersion: %s\n\t" % get_ctr["FirmwareVersion"])
                                sys.stdout.write("SerialNumber: %s\n\t\n" % get_ctr["SerialNumber"])
                        elif (
                            getattr(options, "json", False)
                            and options.storageid
                            and print_ctrl
                            and options.json
                            and options.controllers
                        ):
                            # sys.stdout.write("---------------------------------------------------\n")
                            # sys.stdout.write("List of Controllers in this Storage ID %s\n" % options.storageid)
                            # sys.stdout.write("---------------------------------------------------\n")
                            list_ctr = list_controllers["Members"]
                            for lst in list_ctr:
                                l_data = lst["@odata.id"]
                                get_ctr = self.rdmc.app.get_handler(l_data, silent=True, service=True).dict
                                ctr_data = dict()
                                ctr_data["Controllers"] = dict()
                                ctr_data["Controllers"].update({"Id": get_ctr["Id"]})
                                ctr_data["Controllers"].update({"Health": get_ctr["Status"]["Health"]})
                                ctr_data["Controllers"].update({"Name": get_ctr["Name"]})
                                ctr_data["Controllers"].update({"FirmwareVersion": get_ctr["FirmwareVersion"]})
                                ctr_data["Controllers"].update({"SerialNumber": get_ctr["SerialNumber"]})
                                UI().print_out_json(ctr_data)

                        elif (
                            getattr(options, "controller", False)
                            and print_ctrl
                            and (options.controller is not None)
                            and options.json is None
                            and not options.physicaldrives
                            and not options.pdrive
                            and not options.logicaldrives
                            and not options.ldrive
                        ):
                            controller_info = "---------------------------------------------\n"
                            controller_info += "Controller {} Details on Storage Id {}" "\n".format(
                                options.controller, storage_id
                            )
                            controller_info += "---------------------------------------------\n"
                            controller_info += "Id: %s\n" % controller["Id"]
                            controller_info += "StorageId: %s\n" % storage_id
                            controller_info += "Name: %s\n" % controller["Name"]
                            controller_info += "FirmwareVersion: %s\n" % controller["FirmwareVersion"]
                            controller_info += "Manufacturer: %s\n" % controller["Manufacturer"]
                            controller_info += "Model: %s\n" % controller["Model"]
                            controller_info += "PartNumber: %s\n" % controller["PartNumber"]
                            controller_info += "SerialNumber: %s\n" % controller["SerialNumber"]
                            try:
                                controller_info += "SKU: %s\n" % controller["SKU"]
                            except KeyError:
                                pass
                            controller_info += "Status: %s\n" % controller["Status"]
                            try:
                                controller_info += (
                                    "SupportedDeviceProtocols: %s\n" % controller["SupportedDeviceProtocols"]
                                )
                            except KeyError:
                                pass
                            try:
                                controller_info += (
                                    "SupportedControllerProtocols: %s\n" % controller["SupportedControllerProtocols"]
                                )
                            except KeyError:
                                pass
                            self.rdmc.ui.printer(controller_info, verbose_override=True)

                        elif getattr(options, "json", False) and (options.controller is not None):
                            outjson_data = dict()
                            outjson_data.update({"Id": controller["Id"]})
                            outjson_data.update({"StorageId": storage_id})
                            outjson_data.update({"Name": controller["Name"]})
                            outjson_data.update({"FirmwareVersion": controller["FirmwareVersion"]})
                            outjson_data.update({"Manufacturer": controller["Manufacturer"]})
                            outjson_data.update({"Model": controller["Model"]})
                            outjson_data.update({"PartNumber": controller["PartNumber"]})
                            outjson_data.update({"SerialNumber": controller["SerialNumber"]})
                            try:
                                outjson_data.update({"SKU": controller["SKU"]})
                            except KeyError:
                                pass
                            outjson_data.update({"Status": controller["Status"]})
                            try:
                                outjson_data.update(
                                    {"SupportedDeviceProtocols": controller["SupportedDeviceProtocols"]}
                                )
                            except KeyError:
                                pass
                            try:
                                outjson_data.update(
                                    {"SupportedControllerProtocols": controller["SupportedControllerProtocols"]}
                                )
                            except KeyError:
                                pass
                            UI().print_out_json(outjson_data)

                        if getattr(options, "logicaldrives", False) or getattr(options, "ldrive", False) or single_use:
                            self.storagelogical_drives(options, controller, storage_id, print_ctrl)

                        if getattr(options, "physicaldrives", False) or getattr(options, "pdrive", False) or single_use:
                            self.storagephysical_drives(options, controller, storage_id, print_ctrl)

                        if single_use:
                            storage_data[controller["Id"]] = controller
                if getattr(options, "controller", False) and not controller_ident and print_ctrl:
                    raise InvalidCommandLineError(
                        "Controller in position '%s' was " "not found\n" % (getattr(options, "controller", False))
                    )
                if single_use:
                    return storage_data

                else:
                    if not no_need_ilo5:
                        controller_data = {}
                        for sel in self.rdmc.app.select("SmartStorageArrayController", path_refresh=True):
                            if "Collection" not in sel.maj_type:
                                controller = sel.dict
                                if getattr(options, "controller", False):
                                    if (
                                        getattr(options, "controller", False) == controller["Id"]
                                        or getattr(options, "controller", False) == controller["Location"]
                                    ):
                                        controller_ident = True
                                    else:
                                        continue

                                if self.rdmc.app.typepath.defs.isgen10:
                                    for g10controller in self.rdmc.app.select("SmartStorageConfig.", path_refresh=True):
                                        if g10controller.dict.get("Location") == controller.get("Location"):
                                            id = controller.get("Id")
                                            controller.update(g10controller.dict)
                                            if id:  # iLO Bug - overwrite the Id from collection
                                                controller["Id"] = id
                                            break

                                if (
                                    print_ctrl
                                    and (options.controller is None)
                                    and (options.physicaldrives is None)
                                    and (options.pdrive is None)
                                    and (options.ldrive is None)
                                    and (options.logicaldrives is None)
                                ):
                                    sys.stdout.write(
                                        "[%s]: %s - %s\n"
                                        % (
                                            controller["Id"],
                                            controller["Location"],
                                            controller["Model"],
                                        )
                                    )
                                elif (
                                    getattr(options, "json", False)
                                    and (options.controller is None)
                                    and (options.physicaldrives is None)
                                    and (options.pdrive is None)
                                    and (options.ldrive is None)
                                    and (options.logicaldrives is None)
                                ):
                                    outjson = dict()
                                    outjson["Controllers"] = dict()
                                    outjson["Controllers"][controller["Id"]] = dict()
                                    outjson["Controllers"][controller["Id"]]["Location"] = controller["Location"]
                                    outjson["Controllers"][controller["Id"]]["Model"] = controller["Model"]
                                    UI().print_out_json(outjson)

                                elif (
                                    print_ctrl
                                    and (options.controller is not None)
                                    and ((options.ldrive is not None) or options.pdrive is not None)
                                ):
                                    pass

                                elif (
                                    getattr(options, "json", False)
                                    and (options.controller is not None)
                                    and ((options.ldrive is not None) or (options.pdrive is not None))
                                ):
                                    pass

                                elif print_ctrl and (options.controller is not None) and options.json is None:
                                    controller_info = "------------------------------------------------\n"
                                    controller_info += "Controller Info \n"
                                    controller_info += "------------------------------------------------\n"
                                    controller_info += "Id: %s\n" % controller["Id"]
                                    controller_info += "AdapterType: %s\n" % controller["AdapterType"]
                                    controller_info += "DataGuard: %s\n" % controller["DataGuard"]
                                    controller_info += "Description: %s\n" % controller["Description"]
                                    controller_info += "FirmwareVersion: %s\n" % controller["FirmwareVersion"]
                                    controller_info += "Name: %s\n" % controller["Name"]
                                    controller_info += "Model: %s\n" % controller["Model"]
                                    controller_info += "Location: %s\n" % controller["Location"]
                                    # controller_info += "Links: %s\n" % controller["Links"]
                                    controller_info += "SerialNumber: %s\n" % controller["SerialNumber"]
                                    controller_info += "Status: %s\n" % controller["Status"]
                                    self.rdmc.ui.printer(controller_info, verbose_override=True)

                                elif getattr(options, "json", False) and (options.controller is not None):
                                    outjson_data = dict()
                                    outjson_data.update({"Id": controller["Id"]})
                                    outjson_data.update({"AdapterType": controller["AdapterType"]})
                                    outjson_data.update({"DataGuard": controller["DataGuard"]})
                                    outjson_data.update({"Description": controller["Description"]})
                                    outjson_data.update({"FirmwareVersion": controller["FirmwareVersion"]})
                                    outjson_data.update({"Name": controller["Name"]})
                                    outjson_data.update({"Model": controller["Model"]})
                                    outjson_data.update({"Location": controller["Location"]})
                                    # outjson_data.update({"Links": controller["Links"]})
                                    outjson_data.update({"SerialNumber": controller["SerialNumber"]})
                                    outjson_data.update({"Status": controller["Status"]})
                                    UI().print_out_json(outjson_data)

                                if (
                                    getattr(options, "logicaldrives", False)
                                    or getattr(options, "ldrive", False)
                                    or single_use
                                ):
                                    self.logical_drives(options, controller, print_ctrl)

                                if (
                                    getattr(options, "physicaldrives", False)
                                    or getattr(options, "pdrive", False)
                                    or single_use
                                ):
                                    self.physical_drives(options, controller, print_ctrl)

                                if single_use:
                                    controller_data[controller["Id"]] = controller

                    if getattr(options, "controller", False) and not controller_ident and print_ctrl:
                        raise InvalidCommandLineError(
                            "Controller in position '%s' was not found\n" % (getattr(options, "controller", False))
                        )
                    if getattr(options, "json", False) and not options.storageid:
                        if self.rdmc.opts.verbose:
                            sys.stdout.write("---------------------------------\n")
                            sys.stdout.write("List of RDE storage devices\n")
                            sys.stdout.write("---------------------------------\n")
                        UI().print_out_json(outjson)
                    if single_use:
                        return controller_data
            else:
                raise InvalidCommandLineError(
                    "Storage controller is not ready, Kindly re run the command after sometime\n"
                )
        else:
            raise InvalidCommandLineError("Storage controller is not ready, Kindly re run the command after sometime\n")

    def storagecontroller(self, options, print_ctrl=False, single_use=False):
        if getattr(options, "controller", False):
            controller_ident = False

        if (
            not (getattr(options, "json", False))
            and not (getattr(options, "controller", False))
            and print_ctrl
            and (options.physicaldrives is None)
            and (options.pdrive is None)
            and (options.logicaldrives is None)
            and (options.ldrive is None)
        ):
            sys.stdout.write("Controllers:\n")

        storage_data = {}
        get_contrller = []

        list_storageid = self.rdmc.app.get_handler("/redfish/v1/Systems/1/Storage/", silent=True, service=True).dict[
            "Members"
        ]
        for val in list_storageid:
            storageid_fromurl = val["@odata.id"]
            if "DE" in storageid_fromurl and options.storageid in storageid_fromurl:
                getval = self.rdmc.app.get_handler(storageid_fromurl, silent=True, service=True).dict
                try:
                    controller = getval["Controllers"]
                    list_controllers = self.rdmc.app.get_handler(
                        controller["@odata.id"], silent=True, service=True
                    ).dict
                except KeyError:
                    self.rdmc.ui.printer("Please check controller was Gen11.\n")
                    return ReturnCodes.NO_CONTENTS_FOUND_FOR_OPERATION

                for ctl in list_controllers["Members"]:
                    ctl = ctl["@odata.id"]
                    get_sel = self.rdmc.app.get_handler(ctl, silent=True, service=True)
                    get_contrller.append(get_sel)

        for sel in get_contrller:
            if "Collection" not in sel.path:
                controller = sel.dict
                storage_id = controller["@odata.id"].split("/")
                storage_id = storage_id[6]
                if getattr(options, "controller", False):
                    if (
                        getattr(options, "controller", False) == controller["Id"]
                        or getattr(options, "controller", False)[-1]
                        == controller["Location"]["PartLocation"]["ServiceLabel"][-1]
                    ):
                        controller_ident = True
                    else:
                        continue
                if (
                    print_ctrl
                    and (options.controller is None)
                    and (options.physicaldrives is None)
                    and (options.pdrive is None)
                    and (options.ldrive is None)
                    and (options.logicaldrives is None)
                ):
                    sys.stdout.write(
                        "StorageId:%s - ControllerId:%s - %s - %s\n"
                        % (
                            storage_id,
                            controller["Id"],
                            controller["Location"]["PartLocation"]["ServiceLabel"],
                            controller["Model"],
                        )
                    )

                elif (
                    getattr(options, "json", False)
                    and (options.controller is None)
                    and (options.physicaldrives is None)
                    and (options.pdrive is None)
                    and (options.ldrive is None)
                    and (options.logicaldrives is None)
                ):
                    outjson = dict()
                    outjson["Controllers"] = dict()
                    outjson["Controllers"][storage_id] = dict()
                    outjson["Controllers"][storage_id]["controllerid"] = controller["Id"]
                    outjson["Controllers"][storage_id]["controllerid"]["Location"] = controller["Location"][
                        "PartLocation"
                    ]["ServiceLabel"]
                    outjson["Controllers"][storage_id]["controllerid"]["Model"] = controller["Model"]
                    UI().print_out_json(outjson)

                elif (
                    print_ctrl
                    and (options.controller is not None)
                    and (
                        (options.logicaldrives is not None)
                        or (options.physicaldrives is not None)
                        or (options.ldrive is not None)
                        or (options.pdrive is not None)
                    )
                ):
                    pass

                elif (
                    getattr(options, "json", False)
                    and (options.controller is not None)
                    and (
                        (options.logicaldrives is not None)
                        or (options.physicaldrives is not None)
                        or (options.ldrive is not None)
                        or (options.pdrive is not None)
                    )
                ):
                    pass

                elif print_ctrl and (options.controller is not None) and options.json is None:
                    controller_info = "---------------------------------------------\n"
                    controller_info += "Controller {} Details on Storage Id {}\n".format(options.controller, storage_id)
                    controller_info += "---------------------------------------------\n"
                    controller_info += "Id: %s\n" % controller["Id"]
                    controller_info += "StorageId: %s\n" % storage_id
                    controller_info += "Name: %s\n" % controller["Name"]
                    controller_info += "FirmwareVersion: %s\n" % controller["FirmwareVersion"]
                    controller_info += "Manufacturer: %s\n" % controller["Manufacturer"]
                    controller_info += "Model: %s\n" % controller["Model"]
                    controller_info += "PartNumber: %s\n" % controller["PartNumber"]
                    controller_info += "SerialNumber: %s\n" % controller["SerialNumber"]
                    try:
                        controller_info += "SKU: %s\n" % controller["SKU"]
                    except KeyError:
                        pass
                    controller_info += "Status: %s\n" % controller["Status"]
                    try:
                        controller_info += "SupportedDeviceProtocols: %s\n" % controller["SupportedDeviceProtocols"]
                    except KeyError:
                        pass
                    try:
                        controller_info += (
                            "SupportedControllerProtocols: %s\n" % controller["SupportedControllerProtocols"]
                        )
                    except KeyError:
                        pass
                    self.rdmc.ui.printer(controller_info, verbose_override=True)

                elif getattr(options, "json", False) and (options.controller is not None):
                    outjson_data = dict()
                    outjson_data.update({"Id": controller["Id"]})
                    outjson_data.update({"StorageId": storage_id})
                    outjson_data.update({"Name": controller["Name"]})
                    outjson_data.update({"FirmwareVersion": controller["FirmwareVersion"]})
                    outjson_data.update({"Manufacturer": controller["Manufacturer"]})
                    outjson_data.update({"Model": controller["Model"]})
                    outjson_data.update({"PartNumber": controller["PartNumber"]})
                    outjson_data.update({"SerialNumber": controller["SerialNumber"]})
                    try:
                        outjson_data.update({"SKU": controller["SKU"]})
                    except KeyError:
                        pass
                    outjson_data.update({"Status": controller["Status"]})
                    try:
                        outjson_data.update({"SupportedDeviceProtocols": controller["SupportedDeviceProtocols"]})
                    except KeyError:
                        pass
                    try:
                        outjson_data.update(
                            {"SupportedControllerProtocols": controller["SupportedControllerProtocols"]}
                        )
                    except KeyError:
                        pass
                    UI().print_out_json(outjson_data)

                if getattr(options, "logicaldrives", False) or getattr(options, "ldrive", False) or single_use:
                    self.storagelogical_drives(options, controller, storage_id, print_ctrl)

                if getattr(options, "physicaldrives", False) or getattr(options, "pdrive", False) or single_use:
                    self.storagephysical_drives(options, controller, storage_id, print_ctrl)

                if single_use:
                    storage_data[controller["Id"]] = controller
        if getattr(options, "controller", False) and not controller_ident and print_ctrl:
            raise InvalidCommandLineError(
                "Controller in position '%s' was " "not found\n" % (getattr(options, "controller", False))
            )
        if single_use:
            return storage_data

    def storageid(self, options, print_ctrl=False, single_use=False):
        st_url = "/redfish/v1/Systems/1/Storage/"
        st_content = self.rdmc.app.get_handler(st_url, silent=True, service=True).dict["Members"]
        st_flag = False
        for st_controller in st_content:
            url = st_controller["@odata.id"]
            if options.storageid in url and "DE" in url:
                st_flag = True
                break
            else:
                continue
        if not st_flag:
            raise InvalidCommandLineError(
                "\nStorage ID {} not found or Storage ID is not Redfish enabled and does not have DExxxxxx\n".format(
                    options.storageid
                )
            )
            return

        res_dict = dict()
        res_dict["Storage"] = dict()

        storage_id_url = "/redfish/v1/Systems/1/Storage/" + options.storageid + "?$expand=."

        storage_resp = self.rdmc.app.get_handler(storage_id_url, silent=True, service=True).dict
        if not storage_resp:
            raise InvalidCommandLineError("\nStorage Id {} not found\n".format(options.storageid))
            return
        controllers = storage_resp["Controllers"]["Members"]
        volumes = storage_resp["Volumes"]["Members"]
        drives = storage_resp["Drives"]
        stg_data = []
        actual_no_drives = 0
        for d in storage_resp["Drives"]:
            if d["Status"]["State"] == "Enabled":
                actual_no_drives += 1
        if print_ctrl and storage_resp and options.json is None:
            if (
                options.storageid
                and not options.controllers
                and not options.physicaldrives
                and not options.logicaldrives
                and not options.ldrive
                and not options.pdrive
            ):
                sys.stdout.write("-----------------------------------\n")
                sys.stdout.write("Details of Storage %s\n" % options.storageid)
                sys.stdout.write("-----------------------------------\n")
                sys.stdout.write("\tId: %s\n\t" % storage_resp["Id"])
                sys.stdout.write("Health: %s\n\t" % storage_resp["Status"]["HealthRollup"])
                sys.stdout.write("Name: %s\n\t" % storage_resp["Name"])
                sys.stdout.write("Number of Controllers: %s\n\t" % storage_resp["Controllers"]["Members@odata.count"])
                sys.stdout.write("Number of Volumes: %s\n\t" % storage_resp["Volumes"]["Members@odata.count"])
                sys.stdout.write("Number of Drives: %s\n\t\n" % actual_no_drives)
            elif (
                options.storageid
                and not options.controllers
                and options.physicaldrives
                and not options.logicaldrives
                and not options.ldrive
                and not options.pdrive
            ):
                self.storagephysical_drives(options, options.controller, options.storageid, print_ctrl)
            elif (
                options.storageid
                and not options.controllers
                and not options.physicaldrives
                and options.logicaldrives
                and not options.ldrive
                and not options.pdrive
            ):
                self.storagelogical_drives(options, options.controller, options.storageid, print_ctrl)
            elif options.storageid and options.ldrive:
                self.storagelogical_drives(options, options.controller, options.storageid, print_ctrl)
            elif options.storageid and options.pdrive:
                self.storagephysical_drives(options, options.controller, options.storageid, print_ctrl)

        elif options.json is not None:
            if options.logicaldrives or options.ldrive:
                self.storagelogical_drives(options, options.controller, options.storageid, print_ctrl)
            if options.physicaldrives or options.pdrive:
                self.storagephysical_drives(options, options.controller, options.storageid, print_ctrl)

            storage_data = dict()
            storage_data.update({"Id": storage_resp["Id"]})
            storage_data.update({"Health": storage_resp["Status"]["HealthRollup"]})
            storage_data.update({"Name": storage_resp["Name"]})
            storage_data.update({"Number of Controllers": storage_resp["Controllers"]["Members@odata.count"]})
            storage_data.update({"Number of Volumes": storage_resp["Volumes"]["Members@odata.count"]})
            storage_data.update({"Number of Drives": actual_no_drives})
            stg_data.append(storage_data)

            _ = self.print_list_controllers(options, controllers, print_ctrl)
            _ = self.print_list_volumes(options, volumes, print_ctrl)
            _ = self.print_list_drives(options, drives, print_ctrl)

        # Append controller, volume and drive information to final dictionary
        if (
            not options.controllers
            and res_dict
            and options.json
            and not options.physicaldrives
            and not options.logicaldrives
            and not options.ldrive
            and not options.pdrive
        ):
            if (
                options.storageid
                and not options.controllers
                and not options.physicaldrives
                and not options.logicaldrives
                and not options.ldrive
                and not options.pdrive
            ):
                res_dict["Storage"].update(storage_data)
            UI().print_out_json(res_dict)

        elif options.controllers and options.storageid and options.json is None:
            sys.stdout.write("---------------------------------------------------\n")
            sys.stdout.write("List of Controllers in this Storage ID %s\n" % options.storageid)
            sys.stdout.write("---------------------------------------------------\n")
            list_ctr = controllers
            for lst in list_ctr:
                l_data = lst["@odata.id"]
                get_ctr = self.rdmc.app.get_handler(l_data, silent=True, service=True).dict
                sys.stdout.write("\tId: %s\n\t" % get_ctr["Id"])
                sys.stdout.write("Health: %s\n\t" % get_ctr["Status"]["Health"])
                sys.stdout.write("Name: %s\n\t" % get_ctr["Name"])
                sys.stdout.write("FirmwareVersion: %s\n\t" % get_ctr["FirmwareVersion"])
                sys.stdout.write("SerialNumber: %s\n" % get_ctr["SerialNumber"])

        elif options.controllers and print_ctrl and options.json:
            list_ctr = controllers
            for lst in list_ctr:
                l_data = lst["@odata.id"]
                get_ctr = self.rdmc.app.get_handler(l_data, silent=True, service=True).dict
                ctr_data = dict()
                ctr_data["Controllers"] = dict()
                ctr_data["Controllers"].update({"Id": get_ctr["Id"]})
                ctr_data["Controllers"].update({"Health": get_ctr["Status"]["Health"]})
                ctr_data["Controllers"].update({"Name": get_ctr["Name"]})
                ctr_data["Controllers"].update({"FirmwareVersion": get_ctr["FirmwareVersion"]})
                ctr_data["Controllers"].update({"SerialNumber": get_ctr["SerialNumber"]})
                UI().print_out_json(ctr_data)

    def print_list_controllers(self, options, controllers, print_ctrl):
        c_data = []
        if not options.json:
            sys.stdout.write("Controllers Details:\n")
            if not controllers:
                sys.stdout.write("\tNone:\n\n")
        for c in controllers:
            ctrlr = c["@odata.id"]
            getctrl = self.rdmc.app.get_handler(ctrlr, silent=True, service=True).dict
            if print_ctrl and getctrl and options.json is None:
                sys.stdout.write("\tId: %s\n\t" % getctrl["Id"])
                sys.stdout.write("Health: %s\n\t" % getctrl["Status"]["Health"])
                sys.stdout.write("Location: %s\n\t" % getctrl["Location"]["PartLocation"]["ServiceLabel"])
                sys.stdout.write("Name: %s\n\t\n" % getctrl["Name"])
            elif options.json is not None:
                ctrl_data = dict()
                ctrl_data.update({"Id": getctrl["Id"]})
                ctrl_data.update({"Health": getctrl["Status"]["Health"]})
                ctrl_data.update({"Location": getctrl["Location"]["PartLocation"]["ServiceLabel"]})
                ctrl_data.update({"Name": getctrl["Name"]})
                c_data.append(ctrl_data)
        return c_data

    def print_list_volumes(self, options, volumes, print_ctrl):
        v_data = []
        if options.json:
            vol_data = dict()
        if not options.json:
            sys.stdout.write("\nVolume Details:\n")
            if not volumes:
                sys.stdout.write("\tNone\n\n")
        for vol in volumes:
            volume = vol["@odata.id"]
            getvolumes = self.rdmc.app.get_handler(volume, silent=True, service=True).dict
            if print_ctrl and getvolumes and options.json is None:
                sys.stdout.write("\tId: %s\n\t" % getvolumes["Id"])
                sys.stdout.write("Name: %s\n\t" % getvolumes["Name"])
                sys.stdout.write("RAIDType: %s\n\t" % getvolumes["RAIDType"])
                sys.stdout.write("VolumeUniqueId: %s\n\t" % getvolumes["Identifiers"][0]["DurableName"])
                sys.stdout.write("Health: %s\n\n" % getvolumes["Status"]["Health"])
            elif options.json is not None:
                vol_data.update({"Id": getvolumes["Id"]})
                vol_data.update({"Name": getvolumes["Name"]})
                vol_data.update({"Health": getvolumes["Status"]["Health"]})
                vol_data.update({"RAIDType": getvolumes["RAIDType"]})
                vol_data.update({"VolumeUniqueId": getvolumes["Identifiers"][0]["DurableName"]})
                v_data.append(vol_data)
        return v_data

    def print_list_drives(self, options, drives, print_ctrl):
        d_data = []
        if not options.json:
            sys.stdout.write("Drive Details:\n\n")
            if not drives:
                sys.stdout.write("\tNone\n\n")
        for drive in drives:
            dve = drive["@odata.id"]
            getdrives = self.rdmc.app.get_handler(dve, silent=True, service=True).dict
            if print_ctrl and getdrives and options.json is None:
                sys.stdout.write("\tId: %s\n\t" % getdrives["Id"])
                sys.stdout.write("Location: %s\n\t" % getdrives["PhysicalLocation"]["PartLocation"]["ServiceLabel"])
                sys.stdout.write("Health: %s\n\t" % getdrives["Status"].get("Health", "NA"))
                sys.stdout.write("Name: %s\n\t" % getdrives["Name"])
                sys.stdout.write("Model: %s\n\t" % getdrives.get("Model", "NA"))
                sys.stdout.write("Revision: %s\n\t" % getdrives.get("Revision", "NA"))
                sys.stdout.write("Serial Number: %s\n\t" % getdrives.get("SerialNumber", "NA"))
                sys.stdout.write("Protocol: %s\n\t" % getdrives.get("Protocol", "NA"))
                sys.stdout.write("MediaType: %s\n\t" % getdrives.get("MediaType", "NA"))
                sys.stdout.write("CapacityBytes: %s\n\t\n" % getdrives.get("CapacityBytes", "NA"))

            elif options.json is not None:
                drives_data = dict()
                drives_data.update({"Id": getdrives["Id"]})
                drives_data.update({"Model": getdrives.get("Model", "NA")})
                drives_data.update({"Revision": getdrives.get("Revision", "NA")})
                drives_data.update({"Protocol": getdrives.get("Protocol", "NA")})
                drives_data.update({"MediaType": getdrives.get("MediaType", "NA")})
                drives_data.update({"CapacityBytes": getdrives.get("CapacityBytes", "NA")})
                drives_data.update({"Name": getdrives["Name"]})
                drives_data.update({"Health": getdrives["Status"].get("Health", "NA")})
                drives_data.update({"Serial Number": getdrives.get("SerialNumber", "NA")})
                drives_data.update({"Location": getdrives["PhysicalLocation"]["PartLocation"]["ServiceLabel"]})
                d_data.append(drives_data)
        return d_data

    def storagephysical_drives(self, options, controller, storage_id, print_ctrl=False, single_use=False):
        found_entries = False
        if not getattr(options, "json", False) and print_ctrl:
            sys.stdout.write("--------------------------------------------------\n")
            if not getattr(options, "pdrive", False):
                if controller:
                    sys.stdout.write("Drives on Controller %s and Storage %s\n" % (options.controller, storage_id))
                else:
                    sys.stdout.write("Drives on Storage %s\n" % storage_id)
            else:
                if controller:
                    sys.stdout.write(
                        "Drive %s on Controller %s and Storage %s\n" % (options.pdrive, options.controller, storage_id)
                    )
                else:
                    sys.stdout.write("Drive %s on Storage %s\n" % (options.pdrive, storage_id))
            sys.stdout.write("--------------------------------------------------\n")
        if getattr(options, "pdrive", False):
            pdrive_ident = False
        else:
            pdrive_ident = True
        if single_use:
            physicaldrives = {}
        if getattr(options, "json", False):
            outjson = dict()
            outjson["Drives"] = dict()
        print_drives = []
        storage_url = self.rdmc.app.typepath.defs.systempath + "Storage/" + storage_id
        dd_list = self.rdmc.app.get_handler(storage_url, silent=True).dict.get("Drives", {})
        if dd_list:
            found_entries = True
        for dd in dd_list:
            drive_url = dd["@odata.id"]
            drive_data = self.rdmc.app.get_handler(drive_url, silent=True).dict
            location = drive_data["PhysicalLocation"]["PartLocation"]["ServiceLabel"]
            loc = location.split(":")
            del loc[0]
            if len(loc) == 3:
                temp_str = str(loc[0].split("=")[1] + ":" + loc[1].split("=")[1] + ":" + loc[2].split("=")[1])
                location = temp_str
            else:
                pass

            if getattr(options, "pdrive", False):
                if options.pdrive != location:
                    continue
                else:
                    pdrive_ident = True
            if single_use:
                physicaldrives.update({drive_data["Id"]: drive_data})
            if (
                print_ctrl
                and pdrive_ident
                and options.pdrive is None
                and options.json is None
                and (location not in print_drives)
            ):
                sys.stdout.write(
                    "\t[%s]: %s, Model %s, Location %s, Type %s, Serial %s - %s Bytes\n"
                    % (
                        location,
                        drive_data.get("Name", "NA"),
                        drive_data.get("Model", "NA"),
                        location,
                        drive_data.get("MediaType", "NA"),
                        drive_data.get("SerialNumber", "NA"),
                        drive_data.get("CapacityBytes", "NA"),
                    )
                )
            elif (
                print_ctrl
                and pdrive_ident
                and options.pdrive
                and options.json is None
                and (location not in print_drives)
            ):
                sys.stdout.write(
                    "\tId: %s\n\t%s\n\tModel: %s\n\tLocation: %s\n\tType: %s\n\tSerial: %s\n\tCapacity: %s Bytes\n"
                    % (
                        drive_data["Id"],
                        drive_data["Name"],
                        drive_data.get("Model", "NA"),
                        location,
                        drive_data.get("MediaType", "NA"),
                        drive_data.get("SerialNumber", "NA"),
                        drive_data.get("CapacityBytes", "NA"),
                    )
                )
                break
            elif getattr(options, "json", False) and pdrive_ident and (location not in print_drives):
                outjson["Drives"][location] = dict()
                outjson["Drives"][location]["Id"] = drive_data["Id"]
                outjson["Drives"][location]["Name"] = drive_data["Name"]
                outjson["Drives"][location]["Model"] = drive_data.get("Model", "NA")
                outjson["Drives"][location]["Location"] = location
                outjson["Drives"][location]["MediaType"] = drive_data.get("MediaType", "NA")
                outjson["Drives"][location]["SerialNumber"] = drive_data.get("SerialNumber", "NA")
                outjson["Drives"][location]["CapacityBytes"] = drive_data.get("CapacityBytes", "NA")
                if options.pdrive:
                    break

            print_drives.append(location)
        if getattr(options, "json", False) and pdrive_ident:
            UI().print_out_json(outjson)
        if getattr(options, "pdrive", False) and not pdrive_ident and print_ctrl:
            raise InvalidCommandLineError("\tPhysical drive in position '%s' was not found\n" % options.pdrive)
        elif not found_entries and print_ctrl:
            sys.stdout.write("\tPhysical drives not found.\n")

        if single_use:
            return physicaldrives

    def storagelogical_drives(self, options, controller, storage_id, print_ctrl=False, single_use=False):
        found_entries = False
        printed = False
        if not getattr(options, "json", False) and print_ctrl:
            sys.stdout.write("--------------------------------------------------\n")
            if not getattr(options, "ldrive", False):
                sys.stdout.write("Volumes on Controller %s and Storage %s\n" % (options.controller, storage_id))
            else:
                if controller:
                    sys.stdout.write(
                        "Volume %s on Controller %s and Storage %s\n" % (options.ldrive, options.controller, storage_id)
                    )
                else:
                    sys.stdout.write("Volume %s on Storage %s\n" % (options.ldrive, storage_id))
            sys.stdout.write("--------------------------------------------------\n")
        if getattr(options, "ldrive", False):
            ldrive_ident = False
        else:
            ldrive_ident = True
        if single_use:
            logicaldrives = {}
        if getattr(options, "json", False):
            outjson = dict()
            outjson["volumes"] = dict()
        list_volumes = self.rdmc.app.get_handler(
            "/redfish/v1/Systems/1/Storage/" + storage_id + "/Volumes/",
            silent=True,
            service=True,
        ).dict["Members"]
        for tmp in list_volumes:
            tmp = tmp["@odata.id"]
            tmp = self.rdmc.app.get_handler(tmp, silent=True, service=True).dict
            try:
                std_v = options.storageid in tmp["@odata.id"]
            except:
                std_v = tmp["@odata.id"]
            if std_v:
                if getattr(options, "ldrive", False):
                    ldrive_ident = False
                else:
                    ldrive_ident = True
            if getattr(options, "ldrive", False):
                if options.ldrive != tmp["Id"]:
                    continue
                else:
                    ldrive_ident = True

            if "Identifiers" in tmp:
                durablename = tmp["Identifiers"]
                if durablename is not None:
                    d_name = [name["DurableName"] for name in durablename]
                found_entries = True

                drives = []
                d_data = tmp["Links"]["Drives"]
                for dd in d_data:
                    drive = dd["@odata.id"]
                    drive_data = self.rdmc.app.get_handler(drive, silent=True).dict
                    location = drive_data["PhysicalLocation"]["PartLocation"]["ServiceLabel"]
                    loc = location.split(":")
                    del loc[0]
                    if len(loc) == 3:
                        temp_str = str(loc[0].split("=")[1] + ":" + loc[1].split("=")[1] + ":" + loc[2].split("=")[1])
                        location = temp_str
                        drives.append(location)
                volumes = ", ".join(str(item) for item in drives)
                if print_ctrl and ldrive_ident and options.ldrive is None and not getattr(options, "json", False):
                    sys.stdout.write(
                        "\t[%s]: Name %s RAIDType %s VUID %s Capacity %s Bytes - Health %s\n"
                        % (
                            tmp["Id"],
                            tmp["Name"],
                            tmp["RAIDType"],
                            d_name[0],
                            tmp["CapacityBytes"],
                            tmp["Status"]["Health"],
                        )
                    )
                elif getattr(options, "json", False) and ldrive_ident:
                    outjson["volumes"][tmp["Id"]] = dict()
                    outjson["volumes"][tmp["Id"]]["VolumeName"] = tmp["Name"]
                    outjson["volumes"][tmp["Id"]]["RAIDType"] = tmp["RAIDType"]
                    outjson["volumes"][tmp["Id"]]["VolumeUniqueIdentifier"] = d_name[0]
                    # if options.ldrive:
                    #    outjson["volumes"][tmp["Id"]]["Drive Location"] = volumes
                    outjson["volumes"][tmp["Id"]]["Capacity"] = tmp["CapacityBytes"]
                    outjson["volumes"][tmp["Id"]]["Health"] = tmp["Status"]["Health"]
                    printed = True
                elif print_ctrl and ldrive_ident and options.ldrive is not None:
                    sys.stdout.write(
                        "\tId: %s\n\tName: %s\n\tRaidType: %s\n\tVolumeUniqueId: %s\n\tCapacity: %s Bytes\n\n"
                        % (
                            tmp["Id"],
                            tmp["Name"],
                            tmp["RAIDType"],
                            d_name[0],
                            tmp["CapacityBytes"],
                        )
                    )
                    printed = True
                if single_use:
                    logicaldrives.update({tmp["Id"]: tmp})
        if getattr(options, "json", False) and ldrive_ident:
            UI().print_out_json(outjson)
            printed = True
        if getattr(options, "ldrive", False) and not ldrive_ident:
            sys.stdout.write("\tVolume '%s' was not found.\n" % options.ldrive)
        elif not found_entries and print_ctrl:
            sys.stdout.write("\tVolumes not found.\n")
        if not getattr(options, "logicaldrives", False) and not printed:
            if getattr(options, "ldrive", False):
                raise InvalidCommandLineError("\tVolume '%s' does not exists.\n" % getattr(options, "ldrive", False))

        if single_use:
            return logicaldrives

    def get_storage_data_drives(self, options, drives, print_ctrl=False, single_use=False):
        if not (getattr(options, "json", False)) and print_ctrl:
            sys.stdout.write("\tData Drives:\n\n")
        if single_use:
            subsetdrives = {drives["Id"]: drives}
        found_entries = False
        if print_ctrl:
            self.tranverse_func(drives)
            found_entries = True

        elif getattr(options, "json", False):
            UI().print_out_json(drives)

        if not found_entries and print_ctrl:
            sys.stdout.write("\t\tComponent drives not found.\n")

        if single_use:
            return subsetdrives

    def tranverse_func(self, data, indent=0):
        for key, value in data.items():
            sys.stdout.write("\t %s :" % str(key))
            if isinstance(value, dict):
                self.tranverse_func(value, indent + 1)
            else:
                sys.stdout.write("%s \n" % str(value))

    def physical_drives(self, options, content, print_ctrl=False, single_use=False):
        """
        Identify/parse physical drives (and child properties) of a parent array controller

        :param options: command line options
        :type options: object attributes
        :param content: dictionary of physical drive href or @odata.id paths (expect @odata.type
        "SmartStorageArrayController", @odata.id /Systems/1/SmartStorage/ArrayControllers/X/)
        :type content: dict
        :param print_ctrl: flag for console print enablement/disablement (default disabled)
        :type print_ctrl: bool
        :param single_use: singular usage - True or explore mode - False,
        returns dictionary of results to calling function (default disabled) - see returns.
        :type single_use: bool
        :returns: None, dictionary of all physical drives identified by 'Id'
        """
        dd = ""
        confd = content.get("PhysicalDrives")
        try:
            dd = content["links"]["PhysicalDrives"][self.rdmc.app.typepath.defs.hrefstring]
        except:
            dd = content["Links"]["PhysicalDrives"][self.rdmc.app.typepath.defs.hrefstring]
        finally:
            if not getattr(options, "json", False) and print_ctrl:
                sys.stdout.write("Physical Drives:\n")
            if getattr(options, "pdrive", False):
                pdrive_ident = False
            else:
                pdrive_ident = True
            if single_use:
                physicaldrives = {}
            found_entries = False
            for data in self.rdmc.app.get_handler(dd, silent=True).dict.get("Members", {}):
                try:
                    tmp = data[self.rdmc.app.typepath.defs.hrefstring]
                except:
                    tmp = data[next(iter(data))]
                finally:
                    tmp = self.rdmc.app.get_handler(tmp, silent=True).dict
                    found_entries = True
                if confd:
                    for confdd in confd:
                        if confdd.get("Location") == tmp.get("Location"):
                            tmp.update(confdd)
                            break
                if getattr(options, "pdrive", False):
                    if options.pdrive != tmp["Location"]:
                        continue
                    else:
                        pdrive_ident = True
                if single_use:
                    physicaldrives[tmp["Id"]] = tmp
                if print_ctrl and pdrive_ident and options.pdrive is None:
                    sys.stdout.write(
                        "\t[%s]: Model %s, Location %s, Type %s, Serial %s - %s MiB\n"
                        % (
                            tmp["Location"],
                            tmp.get("Model", "NA"),
                            tmp.get("Location", "NA"),
                            tmp.get("MediaType", "NA"),
                            tmp.get("SerialNumber", "NA"),
                            tmp.get("CapacityMiB", "NA"),
                        )
                    )
                elif getattr(options, "json", False) and pdrive_ident and options.pdrive is None:
                    outjson = dict()
                    outjson["PhysicalDrives"] = dict()
                    outjson["PhysicalDrives"][tmp["Location"]] = dict()
                    outjson["PhysicalDrives"][tmp["Location"]]["Model"] = tmp.get("Model", "NA")
                    outjson["PhysicalDrives"][tmp["Location"]]["Location"] = tmp.get("Location", "NA")
                    outjson["PhysicalDrives"][tmp["Location"]]["MediaType"] = tmp.get("MediaType", "NA")
                    outjson["PhysicalDrives"][tmp["Location"]]["SerialNumber"] = tmp.get("SerialNumber", "NA")
                    outjson["PhysicalDrives"][tmp["Location"]]["CapacityMiB"] = tmp.get("CapacityMiB", "NA")
                    UI().print_out_json(outjson)

                elif print_ctrl and pdrive_ident and options.pdrive is not None:
                    ctl_logical = dict()
                    contoller_loc = content["Location"] + "-" + content["Model"]
                    ctl_logical.update({"Controller": contoller_loc})
                    remove_odata = self.odataremovereadonly(tmp)
                    ctl_logical.update(remove_odata)
                    location = ctl_logical["Location"]
                    if print_ctrl and ctl_logical and options.ldrive is None and not getattr(options, "json", False):
                        sys.stdout.write(
                            "\tId:\t%s\n\tModel:\t%s\n\tLocation:\t%s\n\tType:\t%s\n\tSerial:\t%s\n\tCapacity:\t%s "
                            "Bytes\n"
                            % (
                                ctl_logical["Id"],
                                ctl_logical["Model"],
                                ctl_logical["Location"],
                                ctl_logical["MediaType"],
                                ctl_logical["SerialNumber"],
                                ctl_logical["CapacityLogicalBlocks"],
                            )
                        )
                    elif getattr(options, "json", False) and ctl_logical:
                        outjson = dict()
                        outjson["Drives"] = dict()
                        outjson["Drives"][location] = dict()
                        outjson["Drives"][location]["Id"] = ctl_logical["Id"]
                        outjson["Drives"][location]["Model"] = ctl_logical["Model"]
                        outjson["Drives"][location]["Location"] = location
                        outjson["Drives"][location]["MediaType"] = ctl_logical["MediaType"]
                        outjson["Drives"][location]["SerialNumber"] = ctl_logical["SerialNumber"]
                        outjson["Drives"][location]["CapacityLogicalBlocks"] = ctl_logical["CapacityLogicalBlocks"]
                        UI().print_out_json(outjson)

                elif getattr(options, "json", False) and pdrive_ident and options.pdrive is not None:
                    ctl_logical = dict()
                    contoller_loc = content["Location"] + "-" + content["Model"]
                    ctl_logical.update({"Controller": contoller_loc})
                    remove_odata = self.odataremovereadonly(tmp)
                    ctl_logical.update(remove_odata)
                    UI().print_out_json(ctl_logical)

                if getattr(options, "pdrive", False) and pdrive_ident:
                    break
            if getattr(options, "pdrive", False) and not pdrive_ident and print_ctrl:
                raise InvalidCommandLineError("\tPhysical drive in position '%s' was not found \n" % options.pdrive)
            elif not found_entries and print_ctrl:
                sys.stdout.write("\tPhysical drives not found.\n")

            if single_use:
                return physicaldrives

    def logical_drives(self, options, storage_id, content, print_ctrl=False, single_use=False):
        """
        Identify/parse volumes (and child properties) of an associated array controller

        :param options: command line options
        :type options: object attributes
        :param content: dictionary of volume href or @odata.id paths (expect @odata.type
        "SmartStorageArrayController", @odata.id /Systems/1/SmartStorage/ArrayControllers/X/)
        :type content: dict
        :param print_ctrl: flag for console print enablement/disablement (default disabled)
        :type print_ctrl: bool
        :param single_use: singular usage - True or explore mode - False,
        returns dictionary of results to calling function (default disabled) - see returns.
        :type single_use: bool
        :returns: None, dictionary of all volumes identified by 'Id'
        """

        confd = content.get("LogicalDrives")
        try:
            _ = content["links"]["LogicalDrives"][self.rdmc.app.typepath.defs.hrefstring]
        except:
            _ = content["Links"]["LogicalDrives"][self.rdmc.app.typepath.defs.hrefstring]
        finally:
            if not getattr(options, "json", False) and print_ctrl:
                sys.stdout.write("Volumes:\n")
            if getattr(options, "ldrive", False):
                ldrive_ident = False
            else:
                ldrive_ident = True
            if single_use:
                logicaldrives = {}
            found_entries = False
            try:
                list_volumes = self.rdmc.app.get_handler(
                    "/redfish/v1/Systems/1/Storage/" + options.storageid + "/Volumes/",
                    silent=True,
                    service=True,
                ).dict["Members"]
            except:
                list_volumes = self.rdmc.app.get_handler(
                    "/redfish/v1/Systems/1/Storage/" + storage_id + "/Volumes/",
                    silent=True,
                    service=True,
                ).dict["Members"]
            for data in list_volumes:
                try:
                    tmp = data[self.rdmc.app.typepath.defs.hrefstring]
                except:
                    tmp = data[next(iter(data))]
                finally:
                    tmp = self.rdmc.app.get_handler(tmp, silent=True).dict
                    found_entries = True
                if confd:
                    for confdd in confd:
                        if confdd.get("LogicalDriveNumber") == tmp.get("LogicalDriveNumber"):
                            tmp.update(confdd)
                            break
                if getattr(options, "ldrive", False):
                    if options.ldrive != tmp["Id"]:
                        continue
                    else:
                        ldrive_ident = True
                if print_ctrl and ldrive_ident and options.ldrive is None:
                    sys.stdout.write(
                        "\t[%s]: Name %s Raid %s VUID %s - %s MiB\n"
                        % (
                            tmp["Id"],
                            tmp["LogicalDriveName"],
                            tmp["Raid"],
                            tmp["VolumeUniqueIdentifier"],
                            tmp["CapacityMiB"],
                        )
                    )
                elif getattr(options, "json", False) and ldrive_ident and options.ldrive is None:
                    outjson = dict()
                    outjson["LogicalDrives"] = dict()
                    outjson["LogicalDrives"][tmp["Id"]] = dict()
                    outjson["LogicalDrives"][tmp["Id"]]["LogicalDriveName"] = tmp["LogicalDriveName"]
                    outjson["LogicalDrives"][tmp["Id"]]["Raid"] = tmp["Raid"]
                    outjson["LogicalDrives"][tmp["Id"]]["VolumeUniqueIdentifier"] = tmp["VolumeUniqueIdentifier"]
                    outjson["LogicalDrives"][tmp["Id"]]["CapacityMiB"] = tmp["CapacityMiB"]
                    UI().print_out_json(outjson)
                elif print_ctrl and ldrive_ident and options.ldrive is not None:
                    ctl_logical = dict()
                    contoller_loc = content["Location"] + "-" + content["Model"]
                    ctl_logical.update({"Controller": contoller_loc})
                    remove_odata = self.odataremovereadonly(tmp)
                    ctl_logical.update(remove_odata)
                    id = ctl_logical["Id"]
                    if print_ctrl and ctl_logical and options.json is None:
                        sys.stdout.write("\tId: %s\n\t" % ctl_logical["Id"])
                        sys.stdout.write("Name: %s\n\t" % ctl_logical["LogicalDriveName"])
                        sys.stdout.write("RAIDType: %s\n\t" % ctl_logical["Raid"])
                        sys.stdout.write("VolumeUniqueId: %s\n\t" % ctl_logical["VolumeUniqueIdentifier"])
                        sys.stdout.write("Capacity: %s\n\t" % ctl_logical["CapacityBlocks"])
                        sys.stdout.write("Health: %s\n\n" % ctl_logical["Status"]["Health"])
                    # UI().print_out_json(ctl_logical)
                    elif getattr(options, "json", False) and ctl_logical:
                        outjson = dict()
                        outjson["Volumes"] = dict()
                        outjson["Volumes"][id] = dict()
                        # outjson["Volumes"][id]["Id"] = ctl_logical["Id"]
                        outjson["Volumes"][id]["VolumeName"] = ctl_logical["LogicalDriveName"]
                        outjson["Volumes"][id]["RAIDType"] = ctl_logical["Raid"]
                        outjson["Volumes"][id]["Health"] = ctl_logical["Status"]["Health"]
                        outjson["Volumes"][id]["Capacity"] = ctl_logical["CapacityBlocks"]
                        outjson["Volumes"][id]["VolumeUniqueIdentifier"] = ctl_logical["VolumeUniqueIdentifier"]
                        UI().print_out_json(outjson)
                elif getattr(options, "json", False) and ldrive_ident and options.ldrive is not None:
                    ctl_logical = dict()
                    contoller_loc = content["Location"] + "-" + content["Model"]
                    ctl_logical.update({"Controller": contoller_loc})
                    remove_odata = self.odataremovereadonly(tmp)
                    ctl_logical.update(remove_odata)
                    UI().print_out_json(ctl_logical)

                elif getattr(options, "json", False) and ldrive_ident:
                    UI().print_out_json(tmp)
                if single_use:
                    logicaldrives[tmp["Id"]] = tmp
                if getattr(options, "ldrive", False) and ldrive_ident:
                    break
            if getattr(options, "ldrive", False) and not ldrive_ident:
                sys.stdout.write("\tVolume '%s' was not found \n" % options.pdrive)
            elif not found_entries and print_ctrl:
                sys.stdout.write("\tVolumes not found.\n")

            if single_use:
                return logicaldrives

    def get_data_drives(self, options, drives, print_ctrl=False, single_use=False):
        """
        Identify/parse a physical component drive collection of a respective volume. The
        physical disk properties as well as some logical RAID parameters within each respective
        member.

        :param options: command line options
        :type options: object attributes
        :param content: collection of data drives href or @odata.id paths (as members) as attributed
        to a respective volume.
        :type content: dict
        :param print_ctrl: flag for console print enablement/disablement (default disabled)
        :type print_ctrl: bool
        :param single_use: singular usage, returns dictionary of results to calling function
        (default disabled)
        :type single_use: bool
        :returns: None, dictionary of all physical drives composing a parent volume,
        each instance identified by 'Id'
        """

        if not (getattr(options, "json", False)) and print_ctrl:
            sys.stdout.write("\tData Drives:\n\n")
        if single_use:
            subsetdrives = {}
        found_entries = False
        for member in drives.get("Members", {}):
            try:
                tmp = member[self.rdmc.app.typepath.defs.hrefstring]
            except:
                tmp = member[next(iter(member))]
            finally:
                tmp = self.rdmc.app.get_handler(tmp, silent=True).dict
                found_entries = True
            if single_use:
                subsetdrives[tmp["Id"]] = tmp
            if print_ctrl:
                self.tranverse_func(tmp)
            elif getattr(options, "json", False):
                UI().print_out_json(tmp)
        if not found_entries and print_ctrl:
            sys.stdout.write("\t\tComponent drives not found.\n")

        if single_use:
            return subsetdrives

    def storagecontrollervalidation(self, options):
        """Storage controller validation function

        :param options: command line options
        :type options: list.
        """
        if options.json:
            self.rdmc.json = True
        self.cmdbase.login_select_validation(self, options)

        if getattr(options, "sa_conf_filename", False):
            if options.command == "save":
                open(options.sa_conf_filename, "w+b")
            if options.command == "load":
                open(options.sa_conf_filename, "r+b")
            self.config_file = options.sa_conf_filename
        else:
            self.config_file = __config_file__

    def definearguments(self, customparser):
        """Wrapper function for new command main function

        :param customparser: command line input
        :type customparser: parser.
        """
        if not customparser:
            return

        self.cmdbase.add_login_arguments_group(customparser)
        subcommand_parser = customparser.add_subparsers(dest="command")

        default_parser = subcommand_parser.add_parser(
            "default",
            help="Running without any sub-command will return storage controller configuration data\n"
            "on the currently logged in server. Additional optional arguments will narrow the\n"
            "scope of returned data to individual controllers, physical or volumes",
        )
        default_parser.add_argument(
            "--controller",
            dest="controller",
            help="Use this flag to select the corresponding controller using either the slot "
            "number or index. \n\tExamples:\n\t1. To get more details on a specific "
            "controller, select it by index.\tstoragecontroller --controller=2"
            "\n\t2. To get more details on a specific controller select "
            "it by location.\tstoragecontroller --controller='Slot 0'",
            default=None,
        )
        default_parser.add_argument(
            "--storage_id",
            "--storageid",
            dest="storageid",
            help="Use this flag to select the corresponding controller using either the storageid "
            "id. \n\tExamples:\n\t1. To get more details on a specific "
            "controller, select it by storageid.\tstoragecontroller --storageid=DE00E000"
            "\n\t2. To get more details on a specific controller select "
            "it by location.\tstoragecontroller --storageid='DE00E000'",
            default=None,
        )
        default_parser.add_argument(
            "--controllers",
            dest="controllers",
            action="store_true",
            help="Use this flag to return the controllers for the storageid selected."
            "\n\tExamples:\n\t1. storagecontroller --controllers\n",
            default=None,
        )
        default_parser.add_argument(
            "--physicaldrives",
            "--drives",
            dest="physicaldrives",
            action="store_true",
            help="Use this flag to return the physical drives for the controller selected."
            "\n\tExamples:\n\t1. storagecontroller --drives\n\t2. To obtain details about "
            "physical drives for a specific controller.\tstoragecontroller --controller=3 "
            "--physicaldrives",
            default=None,
        )
        default_parser.add_argument(
            "--logicaldrives",
            "--volumes",
            dest="logicaldrives",
            action="store_true",
            help="Use this flag to return the volumes for the controller selected.\n\t "
            "\n\tExamples:\n\t1. storagecontroller --logicaldrives\n\t2. To obtain details about "
            "volumes for a specific controller.\tstoragecontroller --controller=3 "
            "--logicaldrives",
            default=None,
        )
        default_parser.add_argument(
            "--pdrive",
            "--drive",
            dest="pdrive",
            help="Use this flag to select the corresponding physical disk.\n\tExamples:\n\t "
            "1. To obtain details about a specific physical drive for a specific controller."
            "\tstoragecontroller --controller=3 --pdrive=1I:1:1",
            default=None,
        )
        default_parser.add_argument(
            "--ldrive",
            "--volume",
            dest="ldrive",
            help="Use this flag to select the corresponding logical disk.\n\tExamples:\n\t "
            "1. To obtain details about a specific physical drive for a specific controller."
            "\tstoragecontroller --controller=3 --ldrive=1",
            default=None,
        )
        default_parser.add_argument(
            "-j",
            "--json",
            dest="json",
            action="store_true",
            help="""Use this flag to output data in JSON format.""",
            default=None,
        )
        self.cmdbase.add_login_arguments_group(default_parser)

        state_help = "Print state/event information from @Redfish.Settings (if available)"
        state_parser = subcommand_parser.add_parser(
            "state",
            help=state_help,
            description=state_help + "\n\tExample: storagecontroller state",
            formatter_class=RawDescriptionHelpFormatter,
        )
        state_parser.add_argument(
            "--controller",
            dest="controller",
            help="Use this flag to select the corresponding controller using either the slot "
            "number or index. \n\tExamples:\n\t1. To get more details on a specific "
            "controller, select it by index.\tstoragecontroller state --controller=2"
            "\n\t2. To get more details on a specific controller select "
            "it by location.\tstoragecontroller state --controller='Slot 0'",
            default=None,
        )
        state_parser.add_argument(
            "--storage_id",
            "--storageid",
            dest="storageid",
            help="Use this flag to select the corresponding controller using either the storageid "
            "id. \n\tExamples:\n\t1. To get more details on a specific "
            "controller, select it by storageid.\tstoragecontroller state --storageid=DE00E000"
            "\n\t2. To get more details on a specific controller select "
            "it by location.\tstoragecontroller state --storageid='DE00E000'",
            default=None,
        )
        self.cmdbase.add_login_arguments_group(state_parser)
        json_save_help = (
            "Save a JSON file with all current configurations (all controllers, logical and \nphysical drives)."
        )
        # json save sub-parser
        json_save_parser = subcommand_parser.add_parser(
            "save",
            help=json_save_help,
            description=json_save_help + "\n\tExample: storagecontroller save -f <filename>",
            formatter_class=RawDescriptionHelpFormatter,
        )
        json_save_parser.add_argument(
            "-f",
            dest="sa_conf_filename",
            help="Specify a filename for saving the storagecontroller configuration. (Default: "
            "'storagecontroller_config.json')",
            default=None,
        )
        self.cmdbase.add_login_arguments_group(json_save_parser)
        json_load_help = (
            "Load a JSON file with modified storagecontroller configurations (All read-only "
            "properties\nare discarded)."
        )
        # json load sub-parser
        json_load_parser = subcommand_parser.add_parser(
            "load",
            help=json_load_help,
            description=json_load_help + "\n\tExample: storagecontroller load -f <filename>",
            formatter_class=RawDescriptionHelpFormatter,
        )
        json_load_parser.add_argument(
            "-f",
            dest="sa_conf_filename",
            help="Specify a filename for loading a storagecontroller configuration. (Default: "
            "'storagecontroller_config.json')",
            default=None,
        )
        self.cmdbase.add_login_arguments_group(json_load_parser)
