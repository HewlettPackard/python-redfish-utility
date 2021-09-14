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

import re
import json

from argparse import ArgumentParser, SUPPRESS

import redfish.ris

from ilorest.rdmc_helper import ReturnCodes, InvalidCommandLineError, InvalidCommandLineErrorOPTS, \
                NicMissingOrConfigurationError, BootOrderMissingEntriesError, Encryption

class IscsiConfigCommand():
    """ Changes the iscsi configuration for the server that is currently logged in """
    def __init__(self):
        self.ident = {
            'name':'iscsiconfig',
            'usage': None,
            'description':'Run without'
                    ' arguments for available NIC sources for iSCSI'
                    ' configuration.\n\texample: iscsiconfig\n\n\tDisplay'
                    ' the current iSCSI configuration:\n\texample: '
                    'iscsiconfig --list\n\n\tSaving current iSCSI '
                    'configuration to a file:\n\texample: iscsiconfig '
                    '--list -f output.txt\n\n\tLoading iSCSI '
                    'configurations from a file:\n\texample: iscsiconfig '
                    '--modify output.txt\n\n\tIn order to add a NIC '
                    'source to an iSCSI boot attempt you must run \n\t"'
                    'iscsiconfig" without any paramters. This will '
                    'display a list of NIC\n\tsources which are currently'
                    ' present in the system.\n\tAdding an iSCSI boot '
                    'attempt:\n\texample: iscsiconfig --add [1]\n\n\tIn '
                    'order to delete an iSCSI boot attempt you must run'
                    '\n\t"iscsiconfig --list" to view the currently '
                    'configured attempts.\n\tOnce you find the attempt '
                    'you want to delete simply pass the attempt\n\tnumber'
                    ' to the iSCSI delete function.\n\tDeleting an iSCSI '
                    'boot attempt:\n\texample: iscsiconfig --delete 1',
            'summary':'Displays and configures the current iscsi settings.',
            'aliases': [],
            'auxcommands': ["GetCommand", "SetCommand", "SelectCommand",
                            "RebootCommand", "LogoutCommand"]
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """ Main iscsi configuration worker function

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
                # self.rdmc.ui.printer(self.ident['usage'])
                return ReturnCodes.SUCCESS
            else:
                raise InvalidCommandLineErrorOPTS("")

        self.iscsiconfigurationvalidation(options)

        if self.rdmc.app.typepath.defs.isgen10:
            iscsipath = self.gencompatpaths(selector="HpeiSCSISoftwareInitiator.", rel=False)
            iscsisettingspath = iscsipath + 'settings'
            bootpath = self.gencompatpaths(selector="HpeServerBootSettings.")
        else:
            #TODO: update gencompats to handle the nesting of these links within the gen 9 version.
            if self.rdmc.app.typepath.defs.biospath[-1] == '/':
                iscsipath = self.rdmc.app.typepath.defs.biospath + 'iScsi/'
                iscsisettingspath = self.rdmc.app.typepath.defs.biospath + 'iScsi/settings/'
                bootpath = self.rdmc.app.typepath.defs.biospath + 'Boot/'
            else:
                iscsipath = self.rdmc.app.typepath.defs.biospath + '/iScsi'
                iscsisettingspath = self.rdmc.app.typepath.defs.biospath + '/iScsi/settings'
                bootpath = self.rdmc.app.typepath.defs.biospath + '/Boot'

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
                raise InvalidCommandLineError("Invalid number of parameters. "
                                              "Iscsi configuration takes a maximum of 1 parameter.")

        if options.reboot:
            self.auxcommands['reboot'].run(options.reboot)

        self.cmdbase.logout_routine(self, options)
        #Return code
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
            name = prop.get('Name')
            if 'current' in name.lower():
                try:
                    path = prop.get('@odata.id')
                except:
                    self.rdmc.ui.error('URI path could not be found.')
        return path

    def addoptionhelper(self, options, iscsipath, iscsisettingspath, bootpath):
        """ Helper function to add option for iscsi

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
        self.auxcommands['select'].selectfunction("HpBiosMapping.")
        pcisettingsmap = next(iter(self.auxcommands['get'].getworkerfunction(
            "BiosPciSettingsMappings", options, results=True, uselist=True)), None)

        for item in pcisettingsmap["BiosPciSettingsMappings"]:
            if "Associations" in item:
                if "EmbNicEnable" in item["Associations"] or "EmbNicConfig" in item["Associations"]:
                    _ = [devicealloc.append(x) for x in item["Subinstances"]]

                if (re.match("FlexLom[0-9]+Enable", item["Associations"][0]) or re.match(
                        "PciSlot[0-9]+Enable", item["Associations"][0]) or
                        re.match("Slot[0-9]+NicBoot[0-9]+", item["Associations"][0])):
                    _ = [devicealloc.append(x) for x in item["Subinstances"]]


        foundlocation = False
        iscsibootsources = self.rawdatahandler(action="GET", silent=True,
                                               jsonflag=True, path=iscsisettingspath)
        count = 0
        attemptinstancenumber = self.bootattemptcounter(iscsibootsources \
                                                            [self.rdmc.app.typepath.defs.iscsisource])
        if self.rdmc.app.typepath.defs.isgen10:
            newpcilist = []
            self.auxcommands['select'].selectfunction("HpeServerPciDeviceCollection")
            pcideviceslist = next(iter(self.auxcommands['get'].getworkerfunction("Members", options, results=True, uselist=False)), None)
            for device in pcideviceslist["Members"]:
                newpcilist.append(self.rdmc.app.get_handler(device['@odata.id'], silent=True).dict)
            pcideviceslist = newpcilist
        else:
            self.auxcommands['select'].selectfunction(["Collection."])
            pcideviceslist = next(iter(self.auxcommands['get'].getworkerfunction("Items", options, results=True, uselist=False,
                                                                filtervals=("MemberType","HpServerPciDevice.*"))),None)["Items"]

        disabledlist = self.pcidevicehelper(devicealloc, iscsipath, bootpath, pcideviceslist)

        devicealloc_final = self.make_final_list(devicealloc, pcideviceslist)

        for item in iscsibootsources[self.rdmc.app.typepath.defs.iscsisource]:
            try:
                if not item[self.rdmc.app.typepath.defs.iscsiattemptinstance]:
                    nicsourcedata = devicealloc_final[int(options.add)-1]["Associations"]

                    iscsibootsources[self.rdmc.app.typepath.defs.iscsisource][count]\
                    ["iSCSINicSource"] = nicsourcedata[1] if \
                        isinstance(nicsourcedata[0], dict) else nicsourcedata[0]

                    iscsibootsources[self.rdmc.app.typepath.defs.iscsisource][count]\
                            [self.rdmc.app.typepath.defs.iscsiattemptinstance] = attemptinstancenumber
                    iscsibootsources[self.rdmc.app.typepath.defs.iscsisource][count]\
                        [self.rdmc.app.typepath.defs.iscsiattemptname] = str(attemptinstancenumber)
                    foundlocation = True
                    break
            except Exception:
                raise NicMissingOrConfigurationError("Invalid input value for configuring NIC.")
            count += 1

        if foundlocation:
            self.rdmc.app.patch_handler(iscsisettingspath, iscsibootsources,
                                        optionalpassword=options.biospassword)
        else:
            raise NicMissingOrConfigurationError("Failed to add NIC. All NICs"
                                                 " have already been configured.")

    def make_final_list(self,devicealloc, pcideviceslist):
        final_devicealloc = []
        for item in devicealloc:
            for pcidevice in pcideviceslist:
                if item["CorrelatableID"] == pcidevice["UEFIDevicePath"]:
                    final_devicealloc.append(item)
        return final_devicealloc

    def bootattemptcounter(self, bootsources):
        """ Helper function to count the current boot entries for iscsi

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
            raise NicMissingOrConfigurationError("Failed to add NIC. All "
                                                 "NICs have already been configured.")

        count.sort(key=None, reverse=False)

        if len(count) > 0:
            iterate = 0

            for i in range(1, size+1, 1):
                if iterate < len(count) and i == count[iterate]:
                    iterate += 1
                else:
                    return iterate+1
        else:
            return int(1)

    def deleteoptionhelper(self, options, iscsisettingspath):
        """ Helper function to delete option for iscsi

        :param options: command line options
        :type options: list.
        :param iscsisettingspath: current iscsi settings path
        :type iscsisettingspath: string.
        """
        patch = None

        self.auxcommands['select'].selectfunction("HpBaseConfigs.")
        contents = self.rdmc.app.getprops(selector="BaseConfigs")

        for content in contents:
            for key in content["BaseConfigs"][0]["default"]:
                if key == self.rdmc.app.typepath.defs.iscsisource:
                    patch = content["BaseConfigs"][0]["default"][key]

        if not patch:
            raise NicMissingOrConfigurationError("Could not access Base Configurations.")

        self.validateinput(options=options, deleteoption=True)

        foundlocation = False
        iscsibootsources = self.rawdatahandler(action="GET", silent=True,
                                               jsonflag=False, path=iscsisettingspath)
        holdetag = iscsibootsources.getheader('etag')
        iscsibootsources = json.loads(iscsibootsources.read)

        try:
            count = 0
            for item in iscsibootsources[self.rdmc.app.typepath.defs.iscsisource]:
                if item[self.rdmc.app.typepath.defs.iscsiattemptinstance] == int(options.delete):
                    iscsibootsources[self.rdmc.app.typepath.defs.iscsisource][count] = patch[count]
                    foundlocation = True

                count += 1
        except Exception:
            raise NicMissingOrConfigurationError("The NIC targeted for delete"
                                                 " does not exist. The request for "
                                                 "delete could not be completed.")

        if foundlocation:
            self.rdmc.app.put_handler(iscsisettingspath, iscsibootsources,
                                      optionalpassword=options.biospassword,
                                      headers={'if-Match':holdetag})
            self.rdmc.app.get_handler(iscsisettingspath, silent=True)
        else:
            raise NicMissingOrConfigurationError("The given attempt instance does not exist.")

    def listoptionhelper(self, options, iscsipath, iscsisettingspath, bootpath):
        """ Helper function to list options for iscsi

        :param options: command line options
        :type options: list.
        :param iscsipath: current iscsi path
        :type iscsipath: str.
        :param iscsisettingspath: current iscsi settings path
        :type iscsisettingspath: str.
        :param bootpath: current boot path
        :type bootpath: str.
        """
        self.auxcommands['select'].selectfunction("HpBiosMapping.")
        pcisettingsmap = next(iter(self.auxcommands['get'].getworkerfunction(
            "BiosPciSettingsMappings", options,
            results=True, uselist=True)), None)

        devicealloc = list()
        for item in pcisettingsmap["BiosPciSettingsMappings"]:
            if "Associations" in item:
                if "EmbNicEnable" in item["Associations"] or "EmbNicConfig" in item["Associations"]:
                    _ = [devicealloc.append(x) for x in item["Subinstances"]]

                if (re.match("FlexLom[0-9]+Enable", item["Associations"][0]) or
                        re.match("PciSlot[0-9]+Enable", item["Associations"][0]) or
                        re.match("Slot[0-9]+NicBoot[0-9]+", item["Associations"][0])):
                    _ = [devicealloc.append(x) for x in item["Subinstances"]]

        if self.rdmc.app.typepath.defs.isgen10:
            newpcilist = []

            self.auxcommands['select'].selectfunction("HpeServerPciDeviceCollection")
            pcideviceslist = next(iter(self.auxcommands['get'].getworkerfunction("Members", options,
                                                                                 results=True, uselist=False)), None)

            for device in pcideviceslist["Members"]:
                newpcilist.append(self.rdmc.app.get_handler(device['@odata.id'], silent=True).dict)

            pcideviceslist = newpcilist
        else:
            self.auxcommands['select'].selectfunction(["Collection."])
            pcideviceslist = next(iter(self.auxcommands['get'].getworkerfunction("Items", options,
                                                                                 results=True, uselist=False, filtervals=("MemberType",
                                                                                                                          "HpServerPciDevice.*"))), None)["Items"]

        self.auxcommands['select'].selectfunction("HpiSCSISoftwareInitiator.")
        iscsibootsources = self.rawdatahandler(action="GET", silent=True,
                                               jsonflag=True, path=iscsisettingspath)
        structeredlist = list()

        self.pcidevicehelper(devicealloc, iscsipath, bootpath, pcideviceslist)

        for item in iscsibootsources[self.rdmc.app.typepath.defs.iscsisource]:
            if item["iSCSINicSource"]:
                for device in devicealloc:
                    listval = 1 if isinstance(device["Associations"][0], dict) else 0
                    #self.rdmc.ui.printer("Compare1 '%s: %s'\n" % (item["iSCSINicSource"], device["Associations"][listval]))
                    if item["iSCSINicSource"] == device["Associations"][listval]:
                        for pcidevice in pcideviceslist:
                            #self.rdmc.ui.printer("Compare2 '%s: %s'\n" % (device["CorrelatableID"],pcidevice["UEFIDevicePath"]))
                            #self.rdmc.ui.printer("Modified '%s'\n" % (str(pcidevice["UEFIDevicePath"])[: -2] + str('1)')))
                            if device["CorrelatableID"] == pcidevice["UEFIDevicePath"]:
                                #self.rdmc.ui.printer("Match!!")
                                inputstring = pcidevice["DeviceType"] + " " + \
                                            str(pcidevice["DeviceInstance"]) + " Port " + \
                                            str(pcidevice["DeviceSubInstance"])\
                                            + " : " + pcidevice["Name"]
                                structeredlist.append({inputstring: {str("Attempt " + \
                                                str(item[self.rdmc.app.typepath.defs.iscsiattemptinstance])): item}})

            else:
                structeredlist.append({"Not Added": {}})
        try:
            if iscsibootsources is None:
                raise BootOrderMissingEntriesError('No entries found for iscsi boot sources.\n\n')
            elif not options.filename:
                self.print_iscsi_config_helper(structeredlist, "Current iSCSI Attempts: \n")
        except Exception as excp:
            raise excp

        if structeredlist is None:
            self.rdmc.ui.error('No entries found for iscsi boot sources.\n\n')
        elif options.filename:
            output = json.dumps(structeredlist, indent=2, cls=redfish.ris.JSONEncoder,
                                sort_keys=True)
            filehndl = open(options.filename[0], "w")
            filehndl.write(output)
            filehndl.close()

            self.rdmc.ui.printer("Results written out to '%s'\n" % options.filename[0])

    def defaultsoptionhelper(self, options, iscsipath, bootpath):
        """ Helper function for default options for iscsi

        :param options: command line options
        :type options: list.
        :param iscsipath: current iscsi path
        :type iscsipath: str.
        :param bootpath: current boot path
        :type bootpath: str.
        """
        self.auxcommands['select'].selectfunction("HpBiosMapping.")
        pcisettingsmap = next(iter(self.auxcommands['get'].getworkerfunction(
            "BiosPciSettingsMappings", options,
            results=True, uselist=True)), None)

        devicealloc = list()
        for item in pcisettingsmap["BiosPciSettingsMappings"]:
            if "Associations" in item:
                #self.rdmc.ui.printer("Assoc 1 : %s\n" % (item["Associations"]))
                #self.rdmc.ui.printer("Sub 1 : %s\n" % (item["Subinstances"]))
                if "EmbNicEnable" in item["Associations"] or "EmbNicConfig" in item["Associations"]:
                    _ = [devicealloc.append(x) for x in item["Subinstances"]]

                try:
                    item["Associations"][0]
                    #self.rdmc.ui.printer("Assoc 2 : %s\n" % (item["Associations"][0]))
                    if (re.match("FlexLom[0-9]+Enable", item["Associations"][0]) or re.match(
                            "PciSlot[0-9]+Enable", item["Associations"][0]) or
                            re.match("Slot[0-9]+NicBoot[0-9]+", item["Associations"][0])):
                        _ = [devicealloc.append(x) for x in item["Subinstances"]]
                except IndexError:
                    pass
            self.rdmc.ui.printer("Device alloc : %s\n" % (devicealloc))

        if self.rdmc.app.typepath.defs.isgen10:
            newpcilist = []
            self.auxcommands['select'].selectfunction("HpeServerPciDeviceCollection")
            pcideviceslist = next(iter(self.auxcommands['get'].getworkerfunction("Members", options,
                                                                                 results=True, uselist=False)), None)
            for device in pcideviceslist["Members"]:
                newpcilist.append(self.rdmc.app.get_handler(
                    device['@odata.id'], silent=True).dict)
            pcideviceslist = newpcilist
        else:
            self.auxcommands['select'].selectfunction(["Collection."])
            pcideviceslist = next(iter(self.auxcommands['get'].getworkerfunction("Items", options,
                                                                                 results=True, uselist=False, filtervals=("MemberType",
                                                                                                                          "HpServerPciDevice.*"))), None)["Items"]

        self.auxcommands['select'].selectfunction(
            self.rdmc.app.typepath.defs.hpiscsisoftwareinitiatortype)
        iscsiinitiatorname = next(iter(self.auxcommands['get'].getworkerfunction(
            "iSCSIInitiatorName", options,
            results=True, uselist=True)), None)

        disabledlist = self.pcidevicehelper(devicealloc, iscsipath, bootpath, pcideviceslist)

        self.print_out_iscsi_configuration(iscsiinitiatorname, devicealloc, pcideviceslist)

        if disabledlist:
            self.print_out_iscsi_configuration(iscsiinitiatorname,
                                               disabledlist, pcideviceslist, disabled=True)

    def modifyoptionhelper(self, options, iscsisettingspath):
        """ Helper function to modify options for iscsi

        :param options: command line options
        :type options: list.
        :param iscsisettingspath: current iscsi settings path
        :type iscsisettingspath: str.
        """
        try:
            inputfile = open(options.modify, 'r')
            contentsholder = json.loads(inputfile.read())
        except Exception as excp:
            raise InvalidCommandLineError("%s" % excp)

        iscsibootsources = self.rawdatahandler(action="GET", silent=True,
                                               jsonflag=True, path=iscsisettingspath)

        count = 0
        resultsdict = list()

        for item in contentsholder:
            for entry in item.values():
                enteredsection = False

                for key, value in entry.items():
                    enteredsection = True
                    resultsdict.append(self.modifyfunctionhelper(key, value,
                                                                 iscsibootsources[self.rdmc.app.typepath.defs.iscsisource]))

                if not enteredsection:
                    resultsdict.append(iscsibootsources[self.rdmc.app.typepath.defs.iscsisource][count])

                count += 1

        contentsholder = {self.rdmc.app.typepath.defs.iscsisource: resultsdict}

        self.rdmc.app.patch_handler(iscsisettingspath, contentsholder,
                                    optionalpassword=options.biospassword)
        self.rdmc.app.get_handler(iscsisettingspath, silent=True)

    def modifyfunctionhelper(self, key, value, bootsources):
        """ Helper function to modify the entries for iscsi

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

        if foundoption:
            return value

    def pcidevicehelper(self, devicealloc, iscsipath, bootpath, pcideviceslist=None, options=None):
        """ Helper function to check for extra pci devices / identify disabled devices

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
                self.auxcommands['select'].selectfunction("HpeServerPciDeviceCollection")
                pcideviceslist = next(iter(self.auxcommands['get'].getworkerfunction("Members",
                                                                                     options, results=True, uselist=False)), None)

                for device in pcideviceslist["Members"]:
                    newpcilist.append(self.rdmc.app.get_handler(
                        device['@odata.id'], silent=True).dict)

                pcideviceslist = newpcilist
            else:
                self.auxcommands['select'].selectfunction(["Collection."])
                pcideviceslist = next(iter(self.auxcommands['get'].getworkerfunction("Items",
                                                                                     options, results=True, uselist=False, filtervals=("MemberType",
                                                                                                                                       "HpServerPciDevice.*"))), None)["Items"]
        try:
            self.rawdatahandler(action="GET", silent=True,
                                jsonflag=True, path=iscsipath)['iSCSINicSources']
        except:
            raise NicMissingOrConfigurationError('No iSCSI nic sources available.')

        _ = [x['UEFIDevicePath'] for x in pcideviceslist]
        removal = list()

        bios = self.rawdatahandler(action="GET", silent=True, jsonflag=True, path=bootpath)

        for item in devicealloc:
            if isinstance(item['Associations'][0], dict):
                if 'PreBootNetwork' in list(item['Associations'][0].keys()):
                    if item['Associations'] and item['Associations'][0]['PreBootNetwork'] in list(bios.keys()):
                        if bios[item['Associations'][0]['PreBootNetwork']] == 'Disabled':
                            removal.append(item)
            else:
                if item['Associations'] and item['Associations'][0] in list(bios.keys()):
                    if bios[item['Associations'][0]] == 'Disabled':
                        removal.append(item)

        _ = [devicealloc.remove(x) for x in removal]

        return removal

    def print_out_iscsi_configuration(self, iscsiinitiatorname, devicealloc,
                                      pcideviceslist, disabled=False):
        """ Convert content to human readable and print out to std.out

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
                BootOrderMissingEntriesError('No entry found for the iscsi initiator name.\n\n')
            elif disabled:
                pass
            else:
                self.print_iscsi_config_helper(
                    iscsiinitiatorname["iSCSIInitiatorName"],
                    "\nIscsi Initiator Name: ")
        except Exception as excp:
            raise excp

        try:
            if devicealloc and pcideviceslist:
                if disabled:
                    self.rdmc.ui.printer("\nDisabled iSCSI Boot Network Interfaces: \n")
                    count = 'Disabled'
                else:
                    self.rdmc.ui.printer("Available iSCSI Boot Network Interfaces: \n")
                    count = 1

                for item in devicealloc:
                    for pcidevice in pcideviceslist:
                        if item["CorrelatableID"] == pcidevice["UEFIDevicePath"]:
                            self.rdmc.ui.printer("[%s] %s %s Port %s : %s\n" % \
                                (count, pcidevice["DeviceType"], pcidevice["DeviceInstance"],
                                 pcidevice["DeviceSubInstance"], pcidevice["Name"]))

                            if not disabled:
                                count += 1
            else:
                raise BootOrderMissingEntriesError('No entries found for'
                                                   ' iscsi configurations devices.\n')
        except Exception as excp:
            raise excp

    def print_iscsi_config_helper(self, content, outstring, indent=0):
        """ Print iscsi configuration helper

        :param content: current content to be output
        :type content: string.
        :param outstring: current output string
        :type outstring: str.
        :param indent: current iscsi settings path
        :type indent: str.
        """
        self.rdmc.ui.printer('\t' * indent + outstring)

        if content:
            self.rdmc.ui.print_out_json(content)
        else:
            self.rdmc.ui.error('\t' * indent + "No entries currently configured.\n")

        self.rdmc.ui.printer('\n\n')

    def rawdatahandler(self, action="None", path=None, silent=True, jsonflag=False):
        """ Helper function to get and put the raw data

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
            rawdata = self.rdmc.app.get_handler(put_path=path, silent=silent)

        if jsonflag is True:
            rawdata = json.loads(rawdata.read)

        return rawdata

    def validateinput(self, deviceallocsize=None, options=None, deleteoption=False):
        """ Helper function to validate that the input is correct

        :param deviceallocsize: current device allocated size
        :type deviceallocsize: str.
        :param options: command line options
        :type options: list.
        :param deleteoption: flag to delete option
        :type deleteoption: boolean.
        """
        if deviceallocsize:
            try:
                if int(options.add)-1 >= deviceallocsize:
                    raise NicMissingOrConfigurationError("Please verify the "
                                                         "given input value for configuring NIC.")
            except Exception:
                raise NicMissingOrConfigurationError("Please verify the "
                                                     "given input value for configuring NIC.")
        if deleteoption:
            try:
                if  int(options.delete) == 0:
                    raise NicMissingOrConfigurationError("Invalid input value."
                                                         "Please give valid attempt for instance values.")
            except Exception:
                raise NicMissingOrConfigurationError("Invalid input value."
                                                     "Please give valid attempt for instance values.")

    def iscsiconfigurationvalidation(self, options):
        """ iscsi configuration method validation function

        :param options: command line options
        :type options: list.
        """
        self.cmdbase.login_select_validation(self, options)

        if options.encode:
            options.biospassword = Encryption.decode_credentials(options.biospassword)
            if isinstance(options.biospassword, bytes):
                options.biospassword = options.biospassword.decode('utf-8')

    def definearguments(self, customparser):
        """ Wrapper function for new command main function

        :param customparser: command line input
        :type customparser: parser.
        """
        if not customparser:
            return

        self.cmdbase.add_login_arguments_group(customparser)

        customparser.add_argument(
            '-f',
            '--filename',
            dest='filename',
            help="Use this flag if you wish to use a different"\
            " filename than the default one. The default filename is" \
            " ilorest.json.",
            action="append",
            default=None,
        )
        customparser.add_argument(
            '--add',
            dest='add',
            help="Use this iSCSI configuration option to add an iSCSI"\
            " configuration option.",
            default=None,
        )
        customparser.add_argument(
            '--delete',
            dest='delete',
            help="Use this iSCSI configuration option to delete an iSCSI"\
            " configuration option.",
            default=None,
        )
        customparser.add_argument(
            '--modify',
            dest='modify',
            help="Use this iSCSI configuration option to modify an iSCSI"\
            " configuration option.",
            default=None,
        )
        customparser.add_argument(
            '--list',
            dest='list',
            action="store_true",
            help="Use this iSCSI configuration option to list the details"\
            " of the different iSCSI configurations.",
            default=None,
        )
        customparser.add_argument(
            '--reboot',
            dest='reboot',
            help="Use this flag to perform a reboot command function after"\
            " completion of operations.  For help with parameters and"\
            " descriptions regarding the reboot flag, run help reboot.",
            default=None,
        )
