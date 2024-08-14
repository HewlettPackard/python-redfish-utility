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
""" IscsiConfig Command for rdmc """

import json
import re
import time

import redfish.ris

try:
    from rdmc_helper import (
        BootOrderMissingEntriesError,
        Encryption,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        NicMissingOrConfigurationError,
        ReturnCodes,
    )
except:
    from ilorest.rdmc_helper import (
        BootOrderMissingEntriesError,
        Encryption,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        NicMissingOrConfigurationError,
        ReturnCodes,
    )


class IscsiConfigCommand:
    """Changes the iscsi configuration for the server that is currently logged in"""

    def __init__(self):
        self.ident = {
            "name": "iscsiconfig",
            "usage": None,
            "description": "Run without"
            " arguments for available NIC sources for iSCSI"
            " configuration.\n\texample: iscsiconfig\n\n\tDisplay"
            " the current iSCSI configuration:\n\texample: "
            "iscsiconfig --list\n\n\tSaving current iSCSI "
            "configuration to a file:\n\texample: iscsiconfig "
            "--list -f output.txt\n\n\tLoading iSCSI "
            "configurations from a file:\n\texample: iscsiconfig "
            "--modify output.txt\n\n\tIn order to add a NIC "
            'source to an iSCSI boot attempt you must run \n\t"'
            'iscsiconfig" without any paramters. This will '
            "display a list of NIC\n\tsources which are currently"
            " present in the system.\n\tAdding an iSCSI boot "
            "attempt:\n\texample: iscsiconfig --add 1\n\n\tIn "
            "order to delete an iSCSI boot attempt you must run"
            '\n\t"iscsiconfig --list" to view the currently '
            "configured attempts.\n\tOnce you find the attempt "
            "you want to delete simply pass the attempt\n\tnumber"
            " to the iSCSI delete function.\n\tDeleting an iSCSI "
            "boot attempt:\n\texample: iscsiconfig --delete 1",
            "summary": "Displays and configures the current iscsi settings.",
            "aliases": [],
            "auxcommands": [
                "GetCommand",
                "SetCommand",
                "SelectCommand",
                "RebootCommand",
                "LogoutCommand",
            ],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """Main iscsi configuration worker function

        :param line: string of arguments passed in
        :type line: str.
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

        self.iscsiconfigurationvalidation(options)

        if self.rdmc.app.typepath.defs.isgen10:
            iscsipath = self.gencompatpaths(selector="HpeiSCSISoftwareInitiator.", rel=False)
            if "/settings" not in iscsipath:
                iscsisettingspath = iscsipath + "settings"
            else:
                iscsisettingspath = iscsipath
            bootpath = self.gencompatpaths(selector="HpeServerBootSettings.")
            bootpath = bootpath.replace("/settings", "")
        else:
            # TODO: update gencompats to handle the nesting of these links within the gen 9 version.
            if self.rdmc.app.typepath.defs.biospath[-1] == "/":
                iscsipath = self.rdmc.app.typepath.defs.biospath + "iScsi/"
                iscsisettingspath = self.rdmc.app.typepath.defs.biospath + "iScsi/settings/"
                bootpath = self.rdmc.app.typepath.defs.biospath + "Boot/"
            else:
                iscsipath = self.rdmc.app.typepath.defs.biospath + "/iScsi"
                iscsisettingspath = self.rdmc.app.typepath.defs.biospath + "/iScsi/settings"
                bootpath = self.rdmc.app.typepath.defs.biospath + "/Boot"

        if options.list:
            self.listoptionhelper(options, iscsipath, iscsisettingspath, bootpath)
        elif options.modify:
            self.modifyoptionhelper(options, iscsisettingspath)
        elif options.add:
            self.addoptionhelper(options, iscsipath, iscsisettingspath, bootpath)
        elif options.delete:
            self.deleteoptionhelper(options, iscsisettingspath)
        elif not args:
            self.defaultsoptionhelper(options, iscsipath, bootpath)
        else:
            if len(args) < 2:
                self.iscsiconfigurationvalidation(options)
            else:
                raise InvalidCommandLineError(
                    "Invalid number of parameters. " "Iscsi configuration takes a maximum of 1 parameter."
                )

        if options.reboot:
            self.auxcommands["reboot"].run(options.reboot)

        self.cmdbase.logout_routine(self, options)
        # Return code
        return ReturnCodes.SUCCESS

    def gencompatpaths(self, selector=None, rel=False):
        """Helper function for finding gen compatible paths

        :param selector: the type selection for the get operation
        :type selector: str.
        :param rel: flag to tell select function to reload selected instance
        :type rel: boolean.
        :returns: returns urls
        """

        self.rdmc.app.select(selector=selector, path_refresh=rel)
        props = self.rdmc.app.getprops(skipnonsetting=False)
        for prop in props:
            name = prop.get("Name")
            if "current" in name.lower() or "pending" in name.lower():
                try:
                    path = prop.get("@odata.id")
                except:
                    self.rdmc.ui.error("URI path could not be found.")
        return path

    def get_enabled_only(self):
        enable_disable = dict()
        enable_nic_only = list()
        enable_nic = dict()
        final_enabled_list = list()
        import re

        bios = "/redfish/v1/systems/1/bios/"
        bios_dict = self.rdmc.app.get_handler(bios, silent=True, service=True).dict
        if "Attributes" in bios_dict:
            bios_dict_attributes = bios_dict["Attributes"].items()
        else:
            bios_dict_attributes = bios_dict.items()
        for attr, val in bios_dict_attributes:
            if "NetworkBoot" in str(val):
                enable_disable[attr] = val
        # Enabled NIC only listing
        for k, v in enable_disable.items():
            enable_nic_only.append(k)
            nics = re.findall("\\d+", k)
            enable_nic[k] = nics
            final_enabled_list.append(nics)

        return final_enabled_list

    def addoptionhelper(self, options, iscsipath, iscsisettingspath, bootpath):
        """Helper function to add option for iscsi

        :param options: command line options
        :type options: list.
        :param iscsipath: current iscsi path
        :type iscsipath: str.
        :param iscsisettingspath: current iscsi settings path
        :type iscsisettingspath: str.
        :param bootpath: current boot path
        :type bootpath: str.
        """
        devicealloc = list()
        self.auxcommands["select"].selectfunction("HpeBiosMapping.")
        pcisettingsmap = self.auxcommands["get"].getworkerfunction(
            "BiosPciSettingsMappings", options, results=True, uselist=True
        )

        for item in pcisettingsmap[0]["BiosPciSettingsMappings"]:
            if "Associations" in item:
                if "EmbNicEnable" in item["Associations"] or "EmbNicConfig" in item["Associations"]:
                    _ = [devicealloc.append(x) for x in item["Subinstances"]]

                if (
                    re.match("FlexLom[0-9]+Enable", item["Associations"][0])
                    or re.match("PciSlot[0-9]+Enable", item["Associations"][0])
                    or re.match("Slot[0-9]+NicBoot[0-9]+", item["Associations"][0])
                ):
                    _ = [devicealloc.append(x) for x in item["Subinstances"]]

        foundlocation = False
        iscsibootsources = self.rawdatahandler(action="GET", silent=True, jsonflag=True, path=iscsisettingspath)
        count = 0
        attemptinstancenumber = self.bootattemptcounter(iscsibootsources[self.rdmc.app.typepath.defs.iscsisource])
        if self.rdmc.app.typepath.defs.isgen10:
            newpcilist = []
            self.auxcommands["select"].selectfunction("HpeServerPciDeviceCollection")
            pcideviceslist = next(
                iter(self.auxcommands["get"].getworkerfunction("Members", options, results=True, uselist=False)),
                None,
            )
            for device in pcideviceslist["Members"]:
                newpcilist.append(self.rdmc.app.get_handler(device["@odata.id"], silent=True).dict)
            pcideviceslist = newpcilist
        else:
            self.auxcommands["select"].selectfunction(["Collection."])
            pcideviceslist = next(
                iter(
                    self.auxcommands["get"].getworkerfunction(
                        "Items",
                        options,
                        results=True,
                        uselist=False,
                        filtervals=("MemberType", "HpServerPciDevice.*"),
                    )
                ),
                None,
            )["Items"]

        self.pcidevicehelper(devicealloc, iscsipath, bootpath, pcideviceslist)

        devicealloc_final = self.make_final_list(devicealloc, pcideviceslist)

        print_flag = False
        iscsi_list = self.listoptionhelper(options, iscsipath, iscsisettingspath, bootpath, print_flag)
        refined_list = list()
        for s in iscsi_list:
            for key, val in s.items():
                if key != "Not Added":
                    for k, v in val.items():
                        refined_list.append(v["iSCSINicSource"])
        enabled_only_bootsource = self.get_enabled_only()
        refined_devicealloc = list()
        for d in devicealloc:
            if "PreBootNetwork" in d["Associations"][0]:
                nic = d["Associations"][1]
            else:
                nic = d["Associations"][0]
            if "Storage" in nic:
                continue
            nics = re.findall("\\d+", nic)
            if nics in enabled_only_bootsource:
                refined_devicealloc.append(d)

        for item in iscsibootsources[self.rdmc.app.typepath.defs.iscsisource]:
            try:
                if not item[self.rdmc.app.typepath.defs.iscsiattemptinstance]:
                    nicsourcedata = refined_devicealloc[int(options.add) - 1]["Associations"]
                    if "PreBootNetwork" in nicsourcedata[0]:
                        nic_getting_added = nicsourcedata[1]
                    else:
                        nic_getting_added = nicsourcedata[0]
                    if nic_getting_added in refined_list:
                        self.rdmc.ui.printer("Warning: This NIC is already added to existing attempt\n")
                    iscsibootsources[self.rdmc.app.typepath.defs.iscsisource][count]["iSCSINicSource"] = (
                        nicsourcedata[1] if isinstance(nicsourcedata[0], dict) else nicsourcedata[0]
                    )

                    iscsibootsources[self.rdmc.app.typepath.defs.iscsisource][count][
                        self.rdmc.app.typepath.defs.iscsiattemptinstance
                    ] = attemptinstancenumber
                    iscsibootsources[self.rdmc.app.typepath.defs.iscsisource][count][
                        self.rdmc.app.typepath.defs.iscsiattemptname
                    ] = str(attemptinstancenumber)
                    foundlocation = True
                    break
            except Exception:
                raise NicMissingOrConfigurationError("Invalid input value for configuring NIC.")
            count += 1

        if foundlocation:
            self.rdmc.app.patch_handler(
                iscsisettingspath,
                iscsibootsources,
                optionalpassword=options.biospassword,
            )
        else:
            raise NicMissingOrConfigurationError("Failed to add NIC. All NICs" " have already been configured.")

    def make_final_list(self, devicealloc, pcideviceslist):
        final_devicealloc = []
        for item in devicealloc:
            if isinstance(item["Associations"][0], dict):
                listval = 1
            else:
                listval = 0
            if "Storage" not in item["Associations"][listval]:
                for pcidevice in pcideviceslist:
                    # if item["CorrelatableID"] == pcidevice["UEFIDevicePath"]:
                    final_devicealloc.append(item)
        return final_devicealloc

    def bootattemptcounter(self, bootsources):
        """Helper function to count the current boot entries for iscsi

        :param bootsources: current iscsi boot sources
        :type bootsources: list.
        """
        size = 0
        count = list()

        for item in bootsources:
            size += 1

            if item[self.rdmc.app.typepath.defs.iscsiattemptinstance]:
                count.append(int(item[self.rdmc.app.typepath.defs.iscsiattemptinstance]))

        if size == len(count):
            raise NicMissingOrConfigurationError("Failed to add NIC. All " "NICs have already been configured.")

        count.sort(key=None, reverse=False)

        if len(count) > 0:
            iterate = 0

            for i in range(1, size + 1, 1):
                if iterate < len(count) and i == count[iterate]:
                    iterate += 1
                else:
                    return iterate + 1
        else:
            return int(1)

    def deleteoptionhelper(self, options, iscsisettingspath):
        """Helper function to delete option for iscsi

        :param options: command line options
        :type options: list.
        :param iscsisettingspath: current iscsi settings path
        :type iscsisettingspath: string.
        """
        patch = None

        self.auxcommands["select"].selectfunction("HpBaseConfigs.")
        contents = self.rdmc.app.getprops(selector="BaseConfigs")

        for content in contents:
            for key in content["BaseConfigs"][0]["default"]:
                if key == self.rdmc.app.typepath.defs.iscsisource:
                    patch = content["BaseConfigs"][0]["default"][key]

        if not patch:
            raise NicMissingOrConfigurationError("Could not access Base Configurations.")

        self.validateinput(options=options, deleteoption=True)

        foundlocation = False
        iscsibootsources = self.rawdatahandler(action="GET", silent=True, jsonflag=False, path=iscsisettingspath)
        holdetag = iscsibootsources.getheader("etag")
        iscsibootsources = json.loads(iscsibootsources.read)

        try:
            count = 0
            for item in iscsibootsources[self.rdmc.app.typepath.defs.iscsisource]:
                if item[self.rdmc.app.typepath.defs.iscsiattemptinstance] == int(options.delete):
                    iscsibootsources[self.rdmc.app.typepath.defs.iscsisource][count] = patch[count]
                    foundlocation = True

                count += 1
        except Exception:
            raise NicMissingOrConfigurationError(
                "The NIC targeted for delete" " does not exist. The request for " "delete could not be completed."
            )

        if foundlocation:
            self.rdmc.app.put_handler(
                iscsisettingspath,
                iscsibootsources,
                optionalpassword=options.biospassword,
                headers={"if-Match": holdetag},
            )
            self.rdmc.app.get_handler(iscsisettingspath, silent=True)
        else:
            raise NicMissingOrConfigurationError("The given attempt instance does not exist.")

    def listoptionhelper(self, options, iscsipath, iscsisettingspath, bootpath, print_flag=True):
        """Helper function to list options for iscsi

        :param options: command line options
        :type options: list.
        :param iscsipath: current iscsi path
        :type iscsipath: str.
        :param iscsisettingspath: current iscsi settings path
        :type iscsisettingspath: str.
        :param bootpath: current boot path
        :type bootpath: str.
        """
        self.auxcommands["select"].selectfunction("HpeBiosMapping.")
        pcisettingsmap = self.auxcommands["get"].getworkerfunction(
            "BiosPciSettingsMappings", options, results=True, uselist=True
        )

        devicealloc = list()
        for item in pcisettingsmap[0]["BiosPciSettingsMappings"]:
            if "Associations" in item:
                if "EmbNicEnable" in item["Associations"] or "EmbNicConfig" in item["Associations"]:
                    _ = [devicealloc.append(x) for x in item["Subinstances"]]

                if (
                    re.match("FlexLom[0-9]+Enable", item["Associations"][0])
                    or re.match("PciSlot[0-9]+Enable", item["Associations"][0])
                    or re.match("Slot[0-9]+NicBoot[0-9]+", item["Associations"][0])
                ):
                    _ = [devicealloc.append(x) for x in item["Subinstances"]]

        if self.rdmc.app.typepath.defs.isgen10:
            newpcilist = []

            self.auxcommands["select"].selectfunction("HpeServerPciDeviceCollection")
            pcideviceslist = next(
                iter(self.auxcommands["get"].getworkerfunction("Members", options, results=True, uselist=False)),
                None,
            )

            for device in pcideviceslist["Members"]:
                newpcilist.append(self.rdmc.app.get_handler(device["@odata.id"], silent=True).dict)

            pcideviceslist = newpcilist
        else:
            self.auxcommands["select"].selectfunction(["Collection."])
            pcideviceslist = next(
                iter(
                    self.auxcommands["get"].getworkerfunction(
                        "Items",
                        options,
                        results=True,
                        uselist=False,
                        filtervals=("MemberType", "HpServerPciDevice.*"),
                    )
                ),
                None,
            )["Items"]
        i = 0
        iscsibootsources = ""
        while i < 4:
            self.auxcommands["select"].selectfunction("HpiSCSISoftwareInitiator.")
            iscsibootsources = self.rawdatahandler(action="GET", silent=True, jsonflag=True, path=iscsisettingspath)
            if not ("error" in iscsibootsources):
                break
            time.sleep(10)
            i = i + 1
            self.rdmc.ui.printer("Retrying ...\n\n")
        structeredlist = list()

        self.pcidevicehelper(devicealloc, iscsipath, bootpath, pcideviceslist)
        if not ("error" in iscsibootsources):
            for item in iscsibootsources[self.rdmc.app.typepath.defs.iscsisource]:
                if item["iSCSINicSource"]:
                    for device in devicealloc:
                        it = device["CorrelatableID"]
                        it = it.split(",")
                        del it[-1]
                        it = ",".join(it)
                        if not isinstance(device["Associations"][0], list):
                            listval = 1 if isinstance(device["Associations"][0], dict) else 0
                        else:
                            listval = 0
                        if item["iSCSINicSource"] == device["Associations"][listval]:
                            for pcidevice in pcideviceslist:
                                pcid = pcidevice["UEFIDevicePath"]
                                pcid = pcid.split(",")
                                del pcid[-1]
                                pcid = ",".join(pcid)
                                if (device["CorrelatableID"] == pcidevice["UEFIDevicePath"]) or (
                                    "Embedded" not in pcidevice["DeviceType"] and (pcid == it)
                                ):
                                    if "Storage" not in pcidevice["DeviceType"]:
                                        inputstring = (
                                            pcidevice["DeviceType"]
                                            + " "
                                            + str(pcidevice["DeviceInstance"])
                                            + " Port "
                                            + str(device["Subinstance"])
                                            + " : "
                                            + pcidevice.get("Name", "")
                                        )
                                        structeredlist.append(
                                            {
                                                inputstring: {
                                                    str(
                                                        "Attempt "
                                                        + str(item[self.rdmc.app.typepath.defs.iscsiattemptinstance])
                                                    ): item
                                                }
                                            }
                                        )

                else:
                    structeredlist.append({"Not Added": {}})

        try:
            if iscsibootsources is None:
                raise BootOrderMissingEntriesError("No entries found for iscsi boot sources \n\n")
            elif "error" in iscsibootsources:
                raise BootOrderMissingEntriesError(
                    "/redfish/v1/systems/1/bios/oem/hpe/iscsi/settings URI seems to be not reachable even after"
                    " 4 retry attempts , kindly retry the command after some time \n\n"
                )
            elif not options.filename and print_flag:
                self.print_iscsi_config_helper(structeredlist, "Current iSCSI Attempts: \n")
        except Exception as excp:
            raise excp

        if structeredlist is None:
            self.rdmc.ui.error("No entries found for iscsi boot sources.\n\n")
        elif options.filename:
            output = json.dumps(structeredlist, indent=2, cls=redfish.ris.JSONEncoder, sort_keys=True)
            filehndl = open(options.filename[0], "w")
            filehndl.write(output)
            filehndl.close()

            self.rdmc.ui.printer("Results written out to '%s'\n" % options.filename[0])
        return structeredlist

    def defaultsoptionhelper(self, options, iscsipath, bootpath):
        """Helper function for default options for iscsi

        :param options: command line options
        :type options: list.
        :param iscsipath: current iscsi path
        :type iscsipath: str.
        :param bootpath: current boot path
        :type bootpath: str.
        """
        self.auxcommands["select"].selectfunction("HpBiosMapping.")
        pcisettingsmap = self.auxcommands["get"].getworkerfunction(
            "BiosPciSettingsMappings", options, results=True, uselist=True
        )

        devicealloc = list()
        for item in pcisettingsmap[0]["BiosPciSettingsMappings"]:
            if "Associations" in item:
                # self.rdmc.ui.printer("Assoc 1 : %s\n" % (item["Associations"]))
                # self.rdmc.ui.printer("Sub 1 : %s\n" % (item["Subinstances"]))
                if "EmbNicEnable" in item["Associations"] or "EmbNicConfig" in item["Associations"]:
                    _ = [devicealloc.append(x) for x in item["Subinstances"]]

                try:
                    item["Associations"][0]
                    # self.rdmc.ui.printer("Assoc 2 : %s\n" % (item["Associations"][0]))
                    if (
                        re.match("FlexLom[0-9]+Enable", item["Associations"][0])
                        or re.match("PciSlot[0-9]+Enable", item["Associations"][0])
                        or re.match("Slot[0-9]+NicBoot[0-9]+", item["Associations"][0])
                    ):
                        _ = [devicealloc.append(x) for x in item["Subinstances"]]
                except IndexError:
                    pass
            # self.rdmc.ui.printer("Device alloc : %s\n" % devicealloc)

        if self.rdmc.app.typepath.defs.isgen10:
            newpcilist = []
            self.auxcommands["select"].selectfunction("HpeServerPciDeviceCollection")
            pcideviceslist = self.auxcommands["get"].getworkerfunction("Members", options, results=True, uselist=False)
            pcideviceslist = pcideviceslist[0]
            for device in pcideviceslist["Members"]:
                newpcilist.append(self.rdmc.app.get_handler(device["@odata.id"], silent=True).dict)
            pcideviceslist = newpcilist
        else:
            self.auxcommands["select"].selectfunction(["Collection."])
            pcideviceslist = self.auxcommands["get"].getworkerfunction(
                "Items",
                options,
                results=True,
                uselist=False,
                filtervals=("MemberType", "HpServerPciDevice.*"),
            )[0]["Items"]

        self.auxcommands["select"].selectfunction(self.rdmc.app.typepath.defs.hpiscsisoftwareinitiatortype)
        iscsiinitiatorname = self.auxcommands["get"].getworkerfunction(
            "iSCSIInitiatorName", options, results=True, uselist=True
        )

        disabledlist = self.pcidevicehelper(devicealloc, iscsipath, bootpath, pcideviceslist)

        self.print_out_iscsi_configuration(iscsiinitiatorname[0], devicealloc, pcideviceslist)

        if disabledlist:
            self.print_out_iscsi_configuration(iscsiinitiatorname[0], disabledlist, pcideviceslist, disabled=True)

    def modifyoptionhelper(self, options, iscsisettingspath):
        """Helper function to modify options for iscsi

        :param options: command line options
        :type options: list.
        :param iscsisettingspath: current iscsi settings path
        :type iscsisettingspath: str.
        """
        try:
            inputfile = open(options.modify, "r")
            contentsholder = json.loads(inputfile.read())
        except Exception as excp:
            raise InvalidCommandLineError("%s" % excp)

        iscsibootsources = self.rawdatahandler(action="GET", silent=True, jsonflag=True, path=iscsisettingspath)

        count = 0
        resultsdict = list()

        for item in contentsholder:
            for entry in item.values():
                enteredsection = False

                for key, value in entry.items():
                    enteredsection = True
                    resultsdict.append(
                        self.modifyfunctionhelper(
                            key,
                            value,
                            iscsibootsources[self.rdmc.app.typepath.defs.iscsisource],
                        )
                    )

                if not enteredsection:
                    resultsdict.append(iscsibootsources[self.rdmc.app.typepath.defs.iscsisource][count])

                count += 1

        contentsholder = {self.rdmc.app.typepath.defs.iscsisource: resultsdict}

        self.rdmc.app.patch_handler(iscsisettingspath, contentsholder, optionalpassword=options.biospassword)
        self.rdmc.app.get_handler(iscsisettingspath, silent=True)
        self.rdmc.ui.printer("Please reboot the server for changes to take effect\n")

    def modifyfunctionhelper(self, key, value, bootsources):
        """Helper function to modify the entries for iscsi

        :param key: key to be used for attempt
        :type key: string.
        :param value: value to apply to attempt
        :type value: str.
        :param bootsources: current boot sources
        :type bootsources: list.
        """
        foundoption = False

        for bootsource in bootsources:
            if bootsource[self.rdmc.app.typepath.defs.iscsiattemptinstance] == int(key[-1:]):
                foundoption = True
                break
            else:
                return value
        if foundoption:
            return value

    def pcidevicehelper(self, devicealloc, iscsipath, bootpath, pcideviceslist=None, options=None):
        """Helper function to check for extra pci devices / identify disabled devices

        :param devicealloc: list of devices allocated
        :type devicealloc: list.
        :param iscsipath: current iscsi path
        :type iscsipath: str.
        :param bootpath: current boot path
        :type bootpath: str.
        :param pcideviceslist: current pci device list
        :type pcideviceslist: list.
        :param options: command line options
        :type options: list.
        """
        if not pcideviceslist:
            if self.rdmc.app.typepath.defs.isgen10:
                newpcilist = []
                self.auxcommands["select"].selectfunction("HpeServerPciDeviceCollection")
                pcideviceslist = next(
                    iter(self.auxcommands["get"].getworkerfunction("Members", options, results=True, uselist=False)),
                    None,
                )

                for device in pcideviceslist["Members"]:
                    newpcilist.append(self.rdmc.app.get_handler(device["@odata.id"], silent=True).dict)

                pcideviceslist = newpcilist
            else:
                self.auxcommands["select"].selectfunction(["Collection."])
                pcideviceslist = next(
                    iter(
                        self.auxcommands["get"].getworkerfunction(
                            "Items",
                            options,
                            results=True,
                            uselist=False,
                            filtervals=("MemberType", "HpServerPciDevice.*"),
                        )
                    ),
                    None,
                )["Items"]
        try:
            self.rawdatahandler(action="GET", silent=True, jsonflag=True, path=iscsipath)["iSCSINicSources"]
        except:
            raise NicMissingOrConfigurationError("No iSCSI nic sources available.")

        _ = [x["UEFIDevicePath"] for x in pcideviceslist]
        removal = list()

        bios = self.rawdatahandler(action="GET", silent=True, jsonflag=True, path=bootpath)

        for item in devicealloc:
            if isinstance(item["Associations"][0], dict):
                if "PreBootNetwork" in list(item["Associations"][0].keys()):
                    if item["Associations"] and item["Associations"][0]["PreBootNetwork"] in list(bios.keys()):
                        if bios[item["Associations"][0]["PreBootNetwork"]] == "Disabled":
                            removal.append(item)
            else:
                if item["Associations"] and item["Associations"][0] in list(bios.keys()):
                    if bios[item["Associations"][0]] == "Disabled":
                        removal.append(item)

        _ = [devicealloc.remove(x) for x in removal]

        return removal

    def print_out_iscsi_configuration(self, iscsiinitiatorname, devicealloc, pcideviceslist, disabled=False):
        """Convert content to human readable and print out to std.out

        :param iscsiinitiatorname: iscsi initiator name
        :type iscsiinitiatorname: str.
        :param devicealloc: list of devices allocated
        :type devicealloc: list.
        :param pcideviceslist: current pci device list
        :type pcideviceslist: list.
        :param disabled: command line options
        :type disabled: boolean.
        """
        try:
            if iscsiinitiatorname is None:
                BootOrderMissingEntriesError("No entry found for the iscsi initiator name.\n\n")
            elif disabled:
                pass
            else:
                self.print_iscsi_config_helper(iscsiinitiatorname["iSCSIInitiatorName"], "\nIscsi Initiator Name: ")
        except Exception as excp:
            raise excp

        try:
            tot_instance = []
            final_device_list = list()
            enable_disable = dict()
            enable_val = list()
            import re

            bios = "/redfish/v1/systems/1/bios/"
            bios_dict = self.rdmc.app.get_handler(bios, silent=True, service=True).dict
            if "Attributes" in bios_dict:
                bios_dict_items = bios_dict["Attributes"].items()
            else:
                bios_dict_items = bios_dict.items()
            for attr, val in bios_dict_items:
                if "NetworkBoot" in str(val):
                    nics = re.findall("\\d+", attr)
                    enable_disable[attr] = nics
                    enable_val.append(nics)
            if devicealloc and pcideviceslist:
                if disabled:
                    self.rdmc.ui.printer("\nDisabled iSCSI Boot Network Interfaces: \n")
                    count = "Disabled"
                else:
                    self.rdmc.ui.printer("Available iSCSI Boot Network Interfaces: \n")
                    count = 1
                for pcidevice in pcideviceslist:
                    pcid = pcidevice["UEFIDevicePath"]
                    pcid = pcid.split(",")
                    del pcid[-1]
                    pcid = ",".join(pcid)
                    for item in devicealloc:
                        it = item["CorrelatableID"]
                        it = it.split(",")
                        del it[-1]
                        it = ",".join(it)
                        if pcid == it:
                            if "Storage" not in pcidevice["DeviceType"]:
                                device = (
                                    pcidevice["DeviceType"]
                                    + " "
                                    + str(pcidevice["DeviceInstance"])
                                    + " Port "
                                    + str(item["Subinstance"])
                                )
                                if device not in final_device_list:
                                    final_device_list.append(device)
                                    temp = dict()
                                    temp["Device"] = device
                                    if "Name" not in pcidevice:
                                        temp["Name"] = pcidevice["StructuredName"]
                                    else:
                                        temp["Name"] = pcidevice["Name"]
                                    tot_instance.append(temp)
                count = 0
                enable_nic = dict()
                # enb_val = list()
                for t in tot_instance:
                    nic = t["Device"]
                    nics = re.findall("\\d+", nic)
                    enable_nic[nic] = nics
                    if "Embedded LOM" in t["Device"]:
                        nics.remove("1")
                    for i in enable_val:
                        if i == nics:
                            count = count + 1
                            self.rdmc.ui.printer(
                                "[%s] %s : %s\n"
                                % (
                                    count,
                                    t["Device"],
                                    t["Name"],
                                )
                            )
            else:
                raise BootOrderMissingEntriesError("No entries found for" " iscsi configurations devices.\n")
        except Exception as excp:
            raise excp

    def print_iscsi_config_helper(self, content, outstring, indent=0):
        """Print iscsi configuration helper

        :param content: current content to be output
        :type content: string.
        :param outstring: current output string
        :type outstring: str.
        :param indent: current iscsi settings path
        :type indent: str.
        """
        self.rdmc.ui.printer("\t" * indent + outstring)

        if content:
            self.rdmc.ui.print_out_json(content)
        else:
            self.rdmc.ui.error("\t" * indent + "No entries currently configured.\n")

        self.rdmc.ui.printer("\n\n")

    def rawdatahandler(self, action="None", path=None, silent=True, jsonflag=False):
        """Helper function to get and put the raw data

        :param action: current rest action
        :type action: list.
        :param path: current path
        :type path: str.
        :param silent: flag to determine silent mode
        :type silent: boolean.
        :param jsonflag: flag to determine json output
        :type jsonflag: boolean.
        """
        if action == "GET":
            rawdata = self.rdmc.app.get_handler(get_path=path, silent=silent)

        if jsonflag is True:
            rawdata = json.loads(rawdata.read)

        return rawdata

    def validateinput(self, deviceallocsize=None, options=None, deleteoption=False):
        """Helper function to validate that the input is correct

        :param deviceallocsize: current device allocated size
        :type deviceallocsize: str.
        :param options: command line options
        :type options: list.
        :param deleteoption: flag to delete option
        :type deleteoption: boolean.
        """
        if deviceallocsize:
            try:
                if int(options.add) - 1 >= deviceallocsize:
                    raise NicMissingOrConfigurationError("Please verify the " "given input value for configuring NIC.")
            except Exception:
                raise NicMissingOrConfigurationError("Please verify the " "given input value for configuring NIC.")
        if deleteoption:
            try:
                if int(options.delete) == 0:
                    raise NicMissingOrConfigurationError(
                        "Invalid input value." "Please give valid attempt for instance values."
                    )
            except Exception:
                raise NicMissingOrConfigurationError(
                    "Invalid input value." "Please give valid attempt for instance values."
                )

    def iscsiconfigurationvalidation(self, options):
        """iscsi configuration method validation function

        :param options: command line options
        :type options: list.
        """
        self.cmdbase.login_select_validation(self, options)

        if options.encode:
            options.biospassword = Encryption.decode_credentials(options.biospassword)
            if isinstance(options.biospassword, bytes):
                options.biospassword = options.biospassword.decode("utf-8")

    def definearguments(self, customparser):
        """Wrapper function for new command main function

        :param customparser: command line input
        :type customparser: parser.
        """
        if not customparser:
            return

        self.cmdbase.add_login_arguments_group(customparser)

        customparser.add_argument(
            "-f",
            "--filename",
            dest="filename",
            help="Use this flag if you wish to use a different"
            " filename than the default one. The default filename is"
            " ilorest.json.",
            action="append",
            default=None,
        )
        customparser.add_argument(
            "--add",
            dest="add",
            help="Use this iSCSI configuration option to add an iSCSI" " configuration option.",
            default=None,
        )
        customparser.add_argument(
            "--delete",
            dest="delete",
            help="Use this iSCSI configuration option to delete an iSCSI" " configuration option.",
            default=None,
        )
        customparser.add_argument(
            "--modify",
            dest="modify",
            help="Use this iSCSI configuration option to modify an iSCSI" " configuration option.",
            default=None,
        )
        customparser.add_argument(
            "--list",
            dest="list",
            action="store_true",
            help="Use this iSCSI configuration option to list the details" " of the different iSCSI configurations.",
            default=None,
        )
        customparser.add_argument(
            "--reboot",
            dest="reboot",
            help="Use this flag to perform a reboot command function after"
            " completion of operations.  For help with parameters and"
            " descriptions regarding the reboot flag, run help reboot.",
            default=None,
        )
