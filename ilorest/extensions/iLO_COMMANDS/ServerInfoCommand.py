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
""" Server Info Command for rdmc """
import re
import sys
from collections import OrderedDict

import jsonpath_rw

try:
    from rdmc_helper import (
        UI,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        ReturnCodes,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        UI,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        ReturnCodes,
    )


class ServerInfoCommand:
    """Show details of a server"""

    def __init__(self):
        self.ident = {
            "name": "serverinfo",
            "usage": None,
            "description": "Shows all information.\n\tExample: serverinfo\n\t\t"
            "serverinfo --all\n\n\t"
            "Show enabled fan, processor, and thermal information.\n\texample: "
            "serverinfo --fans --processors --thermals --proxy\n\n\tShow all memory "
            "and fan information, including absent locations in json format.\n\t"
            "example: serverinfo --proxy --firmware --software --memory --fans --showabsent -j\n",
            "summary": "Shows aggregate health status and details of the currently logged in server.",
            "aliases": ["health", "serverstatus", "systeminfo"],
            "auxcommands": [],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """Main serverinfo function.

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
        except (InvalidCommandLineErrorOPTS, SystemExit):
            if ("-h" in line) or ("--help" in line):
                return ReturnCodes.SUCCESS
            else:
                raise InvalidCommandLineErrorOPTS("")

        if args:
            raise InvalidCommandLineError("serverinfo command takes no " "arguments.")

        self.serverinfovalidation(options)

        self.optionsvalidation(options)

        info = self.gatherinfo(options)

        if not info:
            raise InvalidCommandLineError("Please verify the commands entered " "and try again.")
        if "proxy" in info and info["proxy"]:
            if "WebProxyConfiguration" in info["proxy"]["Oem"]["Hpe"]:
                info["proxy"] = info["proxy"]["Oem"]["Hpe"]["WebProxyConfiguration"]

        if options.json:
            if options.processors and options.json and self.rdmc.app.typepath.defs.isgen9:
                pass
            elif options.memory and self.rdmc.app.typepath.defs.isgen9:
                pass
            else:
                self.build_json_out(info, options.showabsent)
        else:
            self.prettyprintinfo(info, options.showabsent)

        self.cmdbase.logout_routine(self, options)
        # Return code
        return ReturnCodes.SUCCESS

    def gatherinfo(self, options):
        """Gather info to printout based on options

        :param options: command line options
        :type options: list.
        """
        info = {}
        path = self.rdmc.app.typepath.defs.systempath
        if path == "/rest/v1/Systems/1" or "/redfish/v1/Systems/1/":
            path = "/redfish/v1/Systems/"
        else:
            pass
        if options.system:
            info["system"] = OrderedDict()
            csysresults = self.rdmc.app.get_handler(path, service=True, silent=True).dict
            # csysresults = self.rdmc.app.select(selector="ComputerSystemCollection")
            # csysresults = csysresults[0].dict
            members = csysresults["Members"]
            for id in members:
                for mem_id in id.values():
                    if path in mem_id:
                        csysresults = self.rdmc.app.get_handler(mem_id, service=True, silent=True).dict
                try:
                    csysresults = csysresults[0].dict
                except:
                    pass
                if csysresults:
                    info["system"]["Model"] = "%s %s" % (
                        csysresults["Manufacturer"],
                        csysresults["Model"],
                    )
                    info["system"]["Bios Version"] = csysresults["BiosVersion"]

                biosresults = self.rdmc.app.select(selector=self.rdmc.app.typepath.defs.biostype)

                try:
                    biosresults = biosresults[0].dict
                except:
                    pass

                if biosresults:
                    try:
                        info["system"]["Serial Number"] = biosresults["Attributes"]["SerialNumber"]
                    except:
                        if "SerialNumber" in biosresults:
                            info["system"]["Serial Number"] = biosresults["SerialNumber"]
                ethresults = None
                getloc = self.rdmc.app.getidbytype("EthernetInterfaceCollection.")
                if getloc:
                    for loc in getloc:
                        if "/systems/1/" in loc.lower():
                            ethresults = self.rdmc.app.getcollectionmembers(loc)
                            break
                    if ethresults:
                        niccount = 0
                        info["system"]["ethernet"] = OrderedDict()
                        for eth in ethresults:
                            niccount += 1
                            if eth["Name"] == "":
                                if "MACAddress" in eth:
                                    info["system"]["ethernet"][niccount] = eth["MACAddress"]
                                else:
                                    info["system"]["ethernet"][niccount] = eth["PermanentMACAddress"]
                            elif eth["Name"] != "":
                                if "MACAddress" in eth:
                                    info["system"]["ethernet"][eth["Name"]] = eth["MACAddress"]
                                else:
                                    info["system"]["ethernet"][eth["Name"]] = eth["PermanentMACAddress"]
                        info["system"]["NICCount"] = niccount
        if options.thermals or options.fans:
            data = None
            if not self.rdmc.app.typepath.defs.isgen9:
                getloc = self.rdmc.app.getidbytype("Thermal.")
            else:
                getloc = self.rdmc.app.getidbytype("ThermalMetrics.")
            if getloc:
                data = self.rdmc.app.get_handler(getloc[0], silent=True, service=True)
            if options.thermals:
                if not getloc:
                    info["thermals"] = None
                else:
                    info["thermals"] = data.dict["Temperatures"]
            if options.fans:
                if not getloc:
                    info["fans"] = None
                else:
                    info["fans"] = data.dict["Fans"]
        if options.memory:
            data = None
            if self.rdmc.app.typepath.defs.isgen9:
                mem_path = "/redfish/v1/Systems/1/Memory/" + "?$expand=."
                getloc = self.rdmc.app.get_handler(mem_path, silent=True, service=True).dict
                collectiondata = getloc["Oem"][self.rdmc.app.typepath.defs.oemhp]
                if collectiondata and not options.json:
                    sys.stdout.write("---------------------------------\n")
                    sys.stdout.write("Memory/DIMM Board Information:\n")
                    sys.stdout.write("---------------------------------\n")
                    memory_status = "Advanced Memory Protection Status: %s \n" % collectiondata["AmpModeStatus"]
                    sys.stdout.write(memory_status)
                    sys.stdout.write("AmpModeActive: %s \n" % collectiondata["AmpModeActive"])
                    sys.stdout.write("AmpModeSupported: %s \n" % collectiondata["AmpModeSupported"])
                    sys.stdout.write("Type: %s \n" % collectiondata["Type"])
                if collectiondata and options.json:
                    tmp = dict()
                    tmp["Memory"] = dict()
                    tmp["Memory"]["Advanced Memory Protection Status"] = collectiondata["AmpModeStatus"]
                    tmp["Memory"]["AmpModeActive"] = collectiondata["AmpModeActive"]
                    tmp["Memory"]["AmpModeSupported"] = collectiondata["AmpModeSupported"]
                    tmp["Memory"]["Type"] = collectiondata["Type"]
                    UI().print_out_json(tmp)
            getloc = self.rdmc.app.getidbytype("MemoryCollection.")
            if getloc:
                data = self.rdmc.app.getcollectionmembers(getloc[0], fullresp=True)[0]
                info["memory"] = data
            else:
                info["memory"] = None
        if options.proxy:
            data = None
            getloc = self.rdmc.app.getidbytype("NetworkProtocol.")
            if getloc:
                data = self.rdmc.app.getcollectionmembers(getloc[0], fullresp=True)[0]
                info["proxy"] = data
            else:
                info["proxy"] = None
        if options.processors:
            data = None
            if not self.rdmc.app.typepath.defs.isgen9:
                getloc = self.rdmc.app.getidbytype("ProcessorCollection.")
            else:
                # getloc = self.rdmc.app.getidbytype("ProcessorCollection.")
                getloc = self.rdmc.app.getidbytype("Processor.")
                tot_proc = []
                if getloc == "/rest/v1/Systems/1/Processors/1" or "/rest/v1/Systems/1/Processors/2":
                    getloc = "/redfish/v1/Systems/1/Processors/"
                    get_p = self.rdmc.app.get_handler(getloc, service=True, silent=True).dict["Members"]
                    output = ""
                    if get_p and not options.json:
                        sys.stdout.write("------------------------------------------------\n")
                        sys.stdout.write("Processor:\n")
                        sys.stdout.write("------------------------------------------------\n")
                        for pp in get_p:
                            dd = pp["@odata.id"]
                            data = self.rdmc.app.get_handler(dd, service=True, silent=True).dict
                            output += "Processor %s:\n" % data["Id"]
                            output += "\tModel: %s\n" % data["Model"]
                            output += "\tStep: %s\n" % data["ProcessorId"]["Step"]
                            output += "\tSocket: %s\n" % data["Socket"]
                            output += "\tMax Speed: %s MHz\n" % data["MaxSpeedMHz"]
                            try:
                                output += (
                                    "\tSpeed: %s MHz\n"
                                    % data["Oem"][self.rdmc.app.typepath.defs.oemhp]["RatedSpeedMHz"]
                                )
                            except KeyError:
                                pass
                            output += "\tCores: %s\n" % data["TotalCores"]
                            output += "\tThreads: %s\n" % data["TotalThreads"]
                            try:
                                for cache in data["Oem"][self.rdmc.app.typepath.defs.oemhp]["Cache"]:
                                    output += "\t%s: %s KB\n" % (
                                        cache["Name"],
                                        cache["InstalledSizeKB"],
                                    )
                            except KeyError:
                                pass
                            try:
                                output += "\tHealth: %s\n" % data["Status"]["Health"]
                            except KeyError:
                                pass
                        self.rdmc.ui.printer(output, verbose_override=True)
                    if get_p and options.json:
                        for pp in get_p:
                            dd = pp["@odata.id"]
                            data = self.rdmc.app.get_handler(dd, service=True, silent=True).dict
                            process = "Processor %s" % data["Id"]
                            tmp = dict()
                            tmp[process] = dict()
                            tmp[process]["Processor"] = data["Id"]
                            tmp[process]["Model"] = data["Model"]
                            tmp[process]["Step"] = data["ProcessorId"]["Step"]
                            tmp[process]["Socket"] = data["Socket"]
                            tmp[process]["Max Speed"] = data["MaxSpeedMHz"]
                            try:
                                tmp[process].update(
                                    {
                                        "Speed": "%s MHz"
                                        % data["Oem"][self.rdmc.app.typepath.defs.oemhp]["RatedSpeedMHz"]
                                    }
                                )
                            except KeyError:
                                pass
                            tmp[process].update({"Cores": data["TotalCores"]})
                            tmp[process].update({"Threads": data["TotalThreads"]})
                            UI().print_out_json(tmp)
                else:
                    pass
            if getloc and not self.rdmc.app.typepath.defs.isgen9:
                data = self.rdmc.app.getcollectionmembers(getloc[0])

                info["processor"] = data
            else:
                info["processor"] = None
        if options.power:
            data = None
            if not self.rdmc.app.typepath.defs.isgen9:
                getloc = self.rdmc.app.getidbytype("Power.")
            else:
                getloc = self.rdmc.app.getidbytype("PowerMetrics.")
            if getloc:
                data = self.rdmc.app.get_handler(getloc[0], silent=True, service=True)
                info["power"] = data.dict
            else:
                info["power"] = None
        if options.firmware:
            data = None
            if not self.rdmc.app.typepath.defs.isgen10:
                getloc = self.rdmc.app.getidbytype("FwSwVersionInventory")
            else:
                getloc = self.rdmc.app.getidbytype("SoftwareInventoryCollection.")

            for gloc in getloc:
                if "FirmwareInventory" in gloc:
                    data = self.rdmc.app.getcollectionmembers(gloc)
                    # if not self.rdmc.app.typepath.defs.isgen10:
                    #    data1 = list(data)
            info["firmware"] = data
        if options.software:
            data = None
            if not self.rdmc.app.typepath.defs.isgen10:
                getloc = self.rdmc.app.getidbytype("SoftwareInventory")
            else:
                getloc = self.rdmc.app.getidbytype("SoftwareInventoryCollection.")
            data_list = list()
            for gloc in getloc:
                if "SoftwareInventory" in gloc:
                    if not self.rdmc.app.typepath.defs.isgen10:
                        data = self.rdmc.app.getcollectionmembers(gloc)
                        data_list.append(data.dict)
                    else:
                        data = self.rdmc.app.getcollectionmembers(gloc)
            if not self.rdmc.app.typepath.defs.isgen10:
                info["software"] = data_list
            else:
                info["software"] = data
        if not options.showabsent:
            jsonpath_expr = jsonpath_rw.parse("$..State")
            matches = jsonpath_expr.find(info)
            matches.reverse()

            for match in matches:
                if match.value.lower() == "absent":
                    arr = None
                    statepath = "/" + str(match.full_path).replace(".", "/")
                    arr = re.split("[[]]", statepath)
                    if arr:
                        removedict = None
                        start = arr[0].split("/")
                        for key in start:
                            if key:
                                if not removedict:
                                    removedict = info[key]
                                else:
                                    removedict = removedict[key]
                        del removedict[int(arr[1])]
        return info

    def build_json_out(self, info, absent):
        headers = list(info.keys())
        content = dict()
        if "power" in headers and info["power"]:
            data = info["power"]
            if data is not None:
                for control in data["PowerControl"]:
                    if "PowerCapacityWatts" in control:
                        power_cap = {"Total Power Capacity": "%s W" % control["PowerCapacityWatts"]}
                    if "PowerConsumedWatts" in control:
                        power_cap.update({"Total Power Consumed": "%s W" % control["PowerConsumedWatts"]})
                    if "PowerMetrics" in control:
                        if "AverageConsumedWatts" in control["PowerMetrics"]:
                            power_mertic = {"Average Power": "%s W" % control["PowerMetrics"]["AverageConsumedWatts"]}
                        if "MaxConsumedWatts" in control["PowerMetrics"]:
                            power_mertic.update(
                                {"Max Consumed Power": "%s W" % control["PowerMetrics"]["MaxConsumedWatts"]}
                            )
                        if "MinConsumedWatts" in control["PowerMetrics"]:
                            power_mertic.update(
                                {"Minimum Consumed Power": "%s W" % control["PowerMetrics"]["MinConsumedWatts"]}
                            )
                        if "IntervalInMin" in control["PowerMetrics"]:
                            powercontent = (
                                "Power Metrics on %s min. Intervals" % control["PowerMetrics"]["IntervalInMin"]
                            )
                    test = {powercontent: power_mertic}
                    content = {"power": power_cap}
                    content["power"].update(test)
                try:
                    powersuplies = []
                    for supply in data["PowerSupplies"]:
                        power_supply = "Power Supply %s" % supply["Oem"][self.rdmc.app.typepath.defs.oemhp]["BayNumber"]
                        powersupply = {}
                        if "PowerCapacityWatts" in supply:
                            powersupply = {"Power Capacity": "%s W" % supply["PowerCapacityWatts"]}
                        if "LastPowerOutputWatts" in supply:
                            powersupply.update({"Last Power Output": "%s W" % supply["LastPowerOutputWatts"]})
                        if "LineInputVoltage" in supply:
                            powersupply.update({"Input Voltage": "%s V" % supply["LineInputVoltage"]})
                        if "LineInputVoltageType" in supply:
                            powersupply.update({"Input Voltage Type": supply["LineInputVoltageType"]})
                        if "HotplugCapable" in supply["Oem"][self.rdmc.app.typepath.defs.oemhp]:
                            powersupply.update(
                                {"Hotplug Capable": supply["Oem"][self.rdmc.app.typepath.defs.oemhp]["HotplugCapable"]}
                            )
                        if "iPDUCapable" in supply["Oem"][self.rdmc.app.typepath.defs.oemhp]:
                            powersupply.update(
                                {"iPDU Capable": supply["Oem"][self.rdmc.app.typepath.defs.oemhp]["iPDUCapable"]}
                            )
                        try:
                            if "Health" in supply["Status"]:
                                powersupply.update({"Health": supply["Status"]["Health"]})
                        except KeyError:
                            pass
                        # if absent:
                        try:
                            if "State" in supply["Status"]:
                                powersupply.update({"State": supply["Status"]["State"]})
                        except KeyError:
                            pass
                        # powerdetails = {power_supply: powersupply}
                        powersuplies.append(powersupply)
                        content["power"].update({"PowerSupplies": powersuplies})
                    for redundancy in data["Redundancy"]:
                        redund_name = redundancy["Name"]
                        redundancy_dict = {"Redundancy Mode": redundancy["Mode"]}
                        try:
                            redundancy_dict.update({"Redundancy Health": redundancy["Status"]["Health"]})
                            redundancy_dict.update({"Redundancy State": redundancy["Status"]["State"]})
                            content.update({redund_name: redundancy_dict})
                        except KeyError:
                            pass
                except KeyError:
                    pass

        if "firmware" in headers and info["firmware"]:
            firmware_info = []
            data = info["firmware"]
            if data is not None:
                if not self.rdmc.app.typepath.defs.isgen10:
                    for key, fw in data.items():
                        for fw_gen9 in fw:
                            fw_str = fw_gen9["Name"] + ": " + fw_gen9["VersionString"]
                            firmware_info.append(fw_str)
                else:
                    for fw in data:
                        fw_str = fw["Name"] + ": " + fw["Version"]
                        firmware_info.append(fw_str)
            content.update({"firmware": firmware_info})

        if "software" in headers and info["software"]:
            output = ""
            software_info = {}
            data = info["software"]
            if data is not None:
                if isinstance(data, dict) or isinstance(data, list):
                    for sw in data:
                        software_info.update({sw["Name"]: sw["Version"]})
                else:
                    # if not options.json:
                    software_info = "No information available for the server\n"
                    self.rdmc.ui.printer(software_info, verbose_override=True)
            content.update({"software": software_info})

        if "memory" in headers and info["memory"]:
            data = info["memory"]
            count = 1
            if data is not None:
                collectiondata = data["Oem"][self.rdmc.app.typepath.defs.oemhp]
                output = "Memory/DIMM Board Information"

                memory_status = "Advanced Memory Protection Status: %s" % collectiondata["AmpModeStatus"]
                memorylist = {}
                for board in collectiondata["MemoryList"]:
                    board_detail = "Board CPU: %s" % board["BoardCpuNumber"]
                    memory_info = {"Total Memory Size": "%s MiB" % board["BoardTotalMemorySize"]}
                    memory_info.update({"Board Memory Frequency": "%s MHz" % board["BoardOperationalFrequency"]})
                    memory_info.update({"Board Memory Voltage": "%s MiB" % board["BoardOperationalVoltage"]})
                    memorylist.update({board_detail: memory_info})
                memorystatus = {memory_status: memorylist}
                memoryinfo = {output: memorystatus}

                for dimm in data[self.rdmc.app.typepath.defs.collectionstring]:
                    memoryconfig = {"Location": dimm["DeviceLocator"]}
                    try:
                        memoryconfig.update(
                            {
                                "Memory Type": "%s %s"
                                % (
                                    dimm["MemoryType"],
                                    dimm["MemoryDeviceType"],
                                )
                            }
                        )
                    except KeyError:
                        memoryconfig.update({"Memory Type": dimm["MemoryType"]})
                    memoryconfig.update({"Capacity": "%s MiB" % dimm["CapacityMiB"]})
                    try:
                        memoryconfig.update({"Speed": "%s MHz" % dimm["OperatingSpeedMhz"]})
                        memoryconfig.update({"Status": dimm["Oem"][self.rdmc.app.typepath.defs.oemhp]["DIMMStatus"]})
                        memoryconfig.update({"Health": dimm["Status"]["Health"]})
                    except KeyError:
                        pass

                    if absent:
                        try:
                            memoryconfig.update({"State": dimm["Status"]["State"]})
                        except KeyError:
                            pass

                    memory_config = "Memory/DIMM Configuration" + " " + str(count)
                    memoryinfo.update({memory_config: memoryconfig})
                    content.update({"memory": memoryinfo})
                    count = count + 1

        if "fans" in headers and info["fans"]:
            fan_output = {}
            fan_details = {}
            if info["fans"] is not None:
                for fan in info["fans"]:
                    fan_name = ""
                    if not self.rdmc.app.typepath.defs.isgen9:
                        fan_name = "%s" % fan["Name"]
                    else:
                        fan_name = "%s" % fan["FanName"]
                    fan_output.update({"Location": fan["Oem"][self.rdmc.app.typepath.defs.oemhp]["Location"]})
                    if "Reading" in fan:
                        fan_output.update({"Reading": "%s%%" % fan["Reading"]})
                        fan_output.update({"Redundant": fan["Oem"][self.rdmc.app.typepath.defs.oemhp]["Redundant"]})
                        fan_output.update(
                            {"Hot Pluggable": fan["Oem"][self.rdmc.app.typepath.defs.oemhp]["HotPluggable"]}
                        )
                    try:
                        if "Health" in fan["Status"]:
                            fan_output.update({"Health": fan["Status"]["Health"]})
                    except KeyError:
                        pass

                    # if absent:
                    try:
                        fan_output.update({"State": fan["Status"]["State"]})
                    except KeyError:
                        pass
                    fan_details.update({fan_name: fan_output})
                    content.update({"fans": fan_details})

        if "thermals" in headers and info["thermals"]:
            if info["thermals"] is not None:
                sensor = ""
                thermal_detail = {}
                for temp in info["thermals"]:
                    if "SensorNumber" in temp:
                        sensor = "Sensor #%s:" % temp["SensorNumber"]
                    if "PhysicalContext" in temp:
                        thermal_info = {"Location": temp["PhysicalContext"]}
                    thermal_info.update({"Current Temp": "%s C" % temp["ReadingCelsius"]})
                    if "UpperThresholdCritical" in temp:
                        thermal_info.update({"Critical Threshold": "%s C" % temp["UpperThresholdCritical"]})
                    else:
                        thermal_info.update({"Critical Threshold": "-"})
                    if "UpperThresholdFatal" in temp:
                        thermal_info.update({"Fatal Threshold": "%s C" % temp["UpperThresholdFatal"]})
                    else:
                        thermal_info.update({"Fatal Threshold": "-"})
                    try:
                        if "Health" in temp["Status"]:
                            thermal_info.update({"Health": temp["Status"]["Health"]})
                    except KeyError:
                        pass
                    if absent:
                        try:
                            thermal_info.update({"State": temp["Status"]["State"]})
                        except KeyError:
                            pass
                    thermal_detail.update({sensor: thermal_info})
                    content.update({"thermals": thermal_detail})

        if "processor" in headers and info["processor"]:
            data = info["processor"]
            processor_info = {}
            if data is not None:
                if not self.rdmc.app.typepath.defs.isgen9:
                    for processor in data:
                        process = "Processor %s" % processor["Id"]
                        processor_date = {"Model": processor["Model"]}
                        processor_date.update({"Step": processor["ProcessorId"]["Step"]})
                        processor_date.update({"Socket": processor["Socket"]})
                        processor_date.update({"Max Speed": "%s MHz" % processor["MaxSpeedMHz"]})
                        try:
                            processor_date.update(
                                {
                                    "Speed": "%s MHz"
                                    % processor["Oem"][self.rdmc.app.typepath.defs.oemhp]["RatedSpeedMHz"]
                                }
                            )
                        except KeyError:
                            pass
                        processor_date.update({"Cores": processor["TotalCores"]})
                        processor_date.update({"Threads": processor["TotalThreads"]})
                        try:
                            for cache in processor["Oem"][self.rdmc.app.typepath.defs.oemhp]["Cache"]:
                                processor_date.update({cache["Name"]: "%s KB" % cache["InstalledSizeKB"]})
                        except KeyError:
                            pass
                        try:
                            processor_date.update({"Health": processor["Status"]["Health"]})
                        except KeyError:
                            pass
                        if absent:
                            try:
                                processor_date.update({"State": processor["Status"]["State"]})
                            except KeyError:
                                pass
                        processor_info.update({process: processor_date})
                else:
                    data = data.dict
                    # for processor in data:
                    process = "Processor %s" % data["Id"]
                    processor_date = {"Model": data["Model"]}
                    processor_date.update({"Step": data["ProcessorId"]["Step"]})
                    processor_date.update({"Socket": data["Socket"]})
                    processor_date.update({"Max Speed": "%s MHz" % data["MaxSpeedMHz"]})
                    try:
                        processor_date.update(
                            {"Speed": "%s MHz" % data["Oem"][self.rdmc.app.typepath.defs.oemhp]["RatedSpeedMHz"]}
                        )
                    except KeyError:
                        pass
                    processor_date.update({"Cores": data["TotalCores"]})
                    processor_date.update({"Threads": data["TotalThreads"]})
                    try:
                        for cache in data["Oem"][self.rdmc.app.typepath.defs.oemhp]["Cache"]:
                            processor_date.update({cache["Name"]: "%s KB" % cache["InstalledSizeKB"]})
                    except KeyError:
                        pass
                    try:
                        processor_date.update({"Health": data["Status"]["Health"]})
                    except KeyError:
                        pass
                    if absent:
                        try:
                            processor_date.update({"State": data["Status"]["State"]})
                        except KeyError:
                            pass
                    processor_info.update({process: processor_date})
                content.update({"processor": processor_info})

        if "proxy" in headers and info["proxy"]:
            proxy_info = {}
            data = info["proxy"]
            try:
                if data is not None:
                    for k, v in data.items():
                        proxy_info.update({k: v})
            except KeyError:
                pass
            content.update({"proxy": proxy_info})

        if "system" in headers:
            data = info["system"]
            system = {}
            if data is not None:
                for key, val in list(data.items()):
                    if key == "ethernet":
                        embedded_nic = {"Embedded NIC Count": data["NICCount"]}
                        system.update(embedded_nic)
                        for name in sorted(data["ethernet"]):
                            mac_name = str(name) + " " + "MAC"
                            mac = {mac_name: data["ethernet"][name]}
                            system.update(mac)
                    elif not key == "NICCount":
                        nic = {key: val}
                        system.update(nic)
            content.update({"system": system})

        UI().print_out_json(content)

    def prettyprintinfo(self, info, absent):
        """Print info in human readable form from json

        :param info: info data collected
        :type info: dict.
        :param absent: flag to show or hide absent components
        :type absent: bool.
        """
        output = ""
        headers = list(info.keys())
        if "system" in headers:
            data = info["system"]
            output = "------------------------------------------------\n"
            output += "System:\n"
            output += "------------------------------------------------\n"
            if data is not None:
                for key, val in list(data.items()):
                    if key == "ethernet":
                        output += "Embedded NIC Count: %s\n" % data["NICCount"]
                        for name in sorted(data["ethernet"]):
                            output += "%s MAC: %s\n" % (name, data["ethernet"][name])
                    elif not key == "NICCount":
                        output += "%s: %s\n" % (key, val)
            self.rdmc.ui.printer(output, verbose_override=True)

        if "firmware" in headers and info["firmware"]:
            data = info["firmware"]
            output = "------------------------------------------------\n"
            output += "Firmware: \n"
            output += "------------------------------------------------\n"
            if data is not None:
                if not self.rdmc.app.typepath.defs.isgen10:
                    for key, fw in data.items():
                        for fw_gen9 in fw:
                            output += "%s : %s\n" % (
                                fw_gen9["Name"],
                                fw_gen9["VersionString"],
                            )
                else:
                    for fw in data:
                        output += "%s : %s\n" % (fw["Name"], fw["Version"])
            self.rdmc.ui.printer(output, verbose_override=True)

        if "software" in headers and info["software"]:
            output = ""
            data = info["software"]
            if not isinstance(data, dict) and not isinstance(data, list):
                data = data.dict
            output = "------------------------------------------------\n"
            output += "Software: \n"
            output += "------------------------------------------------\n"
            if data is not None:
                if isinstance(data, dict) or isinstance(data, list):
                    for sw in data:
                        output += "%s : %s\n" % (sw["Name"], sw["Version"])
                else:
                    output = "No information available for the server\n"
            self.rdmc.ui.printer(output, verbose_override=True)

        if "proxy" in headers and info["proxy"]:
            output = ""
            data = info["proxy"]
            output = "------------------------------------------------\n"
            output += "Proxy: \n"
            output += "------------------------------------------------\n"
            try:
                if data is not None:
                    for k, v in data.items():
                        output += "%s : %s\n" % (k, v)
            except KeyError:
                pass
            self.rdmc.ui.printer(output, verbose_override=True)

        if "processor" in headers and info["processor"]:
            output = ""
            data = info["processor"]
            output = "------------------------------------------------\n"
            output += "Processor:\n"
            output += "------------------------------------------------\n"
            if data is not None:
                if not self.rdmc.app.typepath.defs.isgen9:
                    for processor in data:
                        output += "Processor %s:\n" % processor["Id"]
                        output += "\tModel: %s\n" % processor["Model"]
                        output += "\tStep: %s\n" % processor["ProcessorId"]["Step"]
                        output += "\tSocket: %s\n" % processor["Socket"]
                        output += "\tMax Speed: %s MHz\n" % processor["MaxSpeedMHz"]
                        try:
                            output += (
                                "\tSpeed: %s MHz\n"
                                % processor["Oem"][self.rdmc.app.typepath.defs.oemhp]["RatedSpeedMHz"]
                            )
                        except KeyError:
                            pass
                        output += "\tCores: %s\n" % processor["TotalCores"]
                        output += "\tThreads: %s\n" % processor["TotalThreads"]
                        try:
                            for cache in processor["Oem"][self.rdmc.app.typepath.defs.oemhp]["Cache"]:
                                output += "\t%s: %s KB\n" % (
                                    cache["Name"],
                                    cache["InstalledSizeKB"],
                                )
                        except KeyError:
                            pass
                        try:
                            output += "\tHealth: %s\n" % processor["Status"]["Health"]
                        except KeyError:
                            pass
                        if absent:
                            try:
                                output += "\tState: %s\n" % processor["Status"]["State"]
                            except KeyError:
                                pass
                    self.rdmc.ui.printer(output, verbose_override=True)
                else:
                    data = data.dict
                    output += "Processor %s:\n" % data["Id"]
                    output += "\tModel: %s\n" % data["Model"]
                    output += "\tStep: %s\n" % data["ProcessorId"]["Step"]
                    output += "\tSocket: %s\n" % data["Socket"]
                    output += "\tMax Speed: %s MHz\n" % data["MaxSpeedMHz"]
                    try:
                        output += "\tSpeed: %s MHz\n" % data["Oem"][self.rdmc.app.typepath.defs.oemhp]["RatedSpeedMHz"]
                    except KeyError:
                        pass
                    output += "\tCores: %s\n" % data["TotalCores"]
                    output += "\tThreads: %s\n" % data["TotalThreads"]
                    try:
                        for cache in data["Oem"][self.rdmc.app.typepath.defs.oemhp]["Cache"]:
                            output += "\t%s: %s KB\n" % (
                                cache["Name"],
                                cache["InstalledSizeKB"],
                            )
                    except KeyError:
                        pass
                    try:
                        output += "\tHealth: %s\n" % data["Status"]["Health"]
                    except KeyError:
                        pass
                    if absent:
                        try:
                            output += "\tState: %s\n" % data["Status"]["State"]
                        except KeyError:
                            pass
                    self.rdmc.ui.printer(output, verbose_override=True)

        if "memory" in headers and info["memory"]:
            data = info["memory"]
            if data is not None:
                collectiondata = data["Oem"][self.rdmc.app.typepath.defs.oemhp]
                output = "------------------------------------------------\n"
                output += "Memory/DIMM Board Information:\n"
                output += "------------------------------------------------\n"
                output += "Advanced Memory Protection Status: %s\n" % collectiondata["AmpModeStatus"]
                for board in collectiondata["MemoryList"]:
                    output += "Board CPU: %s \n" % board["BoardCpuNumber"]
                    output += "\tTotal Memory Size: %s MiB\n" % board["BoardTotalMemorySize"]
                    output += "\tBoard Memory Frequency: %s MHz\n" % board["BoardOperationalFrequency"]
                    output += "\tBoard Memory Voltage: %s MiB\n" % board["BoardOperationalVoltage"]
                output += "------------------------------------------------\n"
                output += "Memory/DIMM Configuration:\n"
                output += "------------------------------------------------\n"
                for dimm in data[self.rdmc.app.typepath.defs.collectionstring]:
                    output += "Location: %s\n" % dimm["DeviceLocator"]
                    try:
                        output += "Memory Type: %s %s\n" % (
                            dimm["MemoryType"],
                            dimm["MemoryDeviceType"],
                        )
                    except KeyError:
                        output += "Memory Type: %s\n" % dimm["MemoryType"]
                    output += "Capacity: %s MiB\n" % dimm["CapacityMiB"]
                    try:
                        output += "Speed: %s MHz\n" % dimm["OperatingSpeedMhz"]

                        output += "Status: %s\n" % dimm["Oem"][self.rdmc.app.typepath.defs.oemhp]["DIMMStatus"]
                        output += "Health: %s\n" % dimm["Status"]["Health"]
                    except KeyError:
                        pass
                    if absent:
                        try:
                            output += "State: %s\n" % dimm["Status"]["State"]
                        except KeyError:
                            pass
                    output += "\n"
            self.rdmc.ui.printer(output, verbose_override=True)

        if "power" in headers and info["power"]:
            data = info["power"]
            output = "------------------------------------------------\n"
            output += "Power:\n"
            output += "------------------------------------------------\n"
            if data is not None:
                for control in data["PowerControl"]:
                    output += "Total Power Capacity: %s W\n" % control["PowerCapacityWatts"]
                    output += "Total Power Consumed: %s W\n" % control["PowerConsumedWatts"]
                    output += "\n"
                    output += "Power Metrics on %s min. Intervals:\n" % control["PowerMetrics"]["IntervalInMin"]
                    output += "\tAverage Power: %s W\n" % control["PowerMetrics"]["AverageConsumedWatts"]
                    output += "\tMax Consumed Power: %s W\n" % control["PowerMetrics"]["MaxConsumedWatts"]
                    output += "\tMinimum Consumed Power: %s W\n" % control["PowerMetrics"]["MinConsumedWatts"]
                try:
                    for supply in data["PowerSupplies"]:
                        output += "------------------------------------------------\n"
                        output += "Power Supply %s:\n" % supply["Oem"][self.rdmc.app.typepath.defs.oemhp]["BayNumber"]
                        output += "------------------------------------------------\n"
                        if "PowerCapacityWatts" in supply:
                            output += "Power Capacity: %s W\n" % supply["PowerCapacityWatts"]
                        if "LastPowerOutputWatts" in supply:
                            output += "Last Power Output: %s W\n" % supply["LastPowerOutputWatts"]
                        if "LineInputVoltage" in supply:
                            output += "Input Voltage: %s V\n" % supply["LineInputVoltage"]
                        if "LineInputVoltageType" in supply:
                            output += "Input Voltage Type: %s\n" % supply["LineInputVoltageType"]
                        if "HotplugCapable" in supply["Oem"][self.rdmc.app.typepath.defs.oemhp]:
                            output += (
                                "Hotplug Capable: %s\n"
                                % supply["Oem"][self.rdmc.app.typepath.defs.oemhp]["HotplugCapable"]
                            )
                        if "iPDUCapable" in supply["Oem"][self.rdmc.app.typepath.defs.oemhp]:
                            output += (
                                "iPDU Capable: %s\n" % supply["Oem"][self.rdmc.app.typepath.defs.oemhp]["iPDUCapable"]
                            )
                        try:
                            if "Health" in supply["Status"]:
                                output += "Health: %s\n" % supply["Status"]["Health"]
                        except KeyError:
                            pass

                        try:
                            if "State" in supply["Status"]:
                                output += "State: %s\n" % supply["Status"]["State"]
                        except KeyError:
                            pass
                    for redundancy in data["Redundancy"]:
                        output += "------------------------------------------------\n"
                        output += "%s\n" % redundancy["Name"]
                        output += "------------------------------------------------\n"
                        output += "Redundancy Mode: %s\n" % redundancy["Mode"]
                        try:
                            output += "Redundancy Health: %s\n" % redundancy["Status"]["Health"]
                            output += "Redundancy State: %s\n" % redundancy["Status"]["State"]
                        except KeyError:
                            pass
                except KeyError:
                    pass
            self.rdmc.ui.printer(output, verbose_override=True)

        if "fans" in headers and info["fans"]:
            output = "------------------------------------------------\n"
            output += "Fan(s):\n"
            output += "------------------------------------------------\n"
            if info["fans"] is not None:
                for fan in info["fans"]:
                    if not self.rdmc.app.typepath.defs.isgen9:
                        output += "%s:\n" % fan["Name"]
                    else:
                        output += "%s:\n" % fan["FanName"]
                    output += "\tLocation: %s\n" % fan["Oem"][self.rdmc.app.typepath.defs.oemhp]["Location"]
                    if "Reading" in fan:
                        output += "\tReading: %s%%\n" % fan["Reading"]
                        output += "\tRedundant: %s\n" % fan["Oem"][self.rdmc.app.typepath.defs.oemhp]["Redundant"]
                        output += (
                            "\tHot Pluggable: %s\n" % fan["Oem"][self.rdmc.app.typepath.defs.oemhp]["HotPluggable"]
                        )
                    try:
                        if "Health" in fan["Status"]:
                            output += "\tHealth: %s\n" % fan["Status"]["Health"]
                    except KeyError:
                        pass

                    try:
                        output += "\tState: %s\n" % fan["Status"]["State"]
                    except KeyError:
                        pass
            self.rdmc.ui.printer(output, verbose_override=True)

        if "thermals" in headers and info["thermals"]:
            output = "------------------------------------------------\n"
            output += "Thermal:\n"
            output += "------------------------------------------------\n"
            if info["thermals"] is not None:
                for temp in info["thermals"]:
                    if "SensorNumber" in temp:
                        output += "Sensor #%s:\n" % temp["SensorNumber"]
                    if "PhysicalContext" in temp:
                        output += "\tLocation: %s\n" % temp["PhysicalContext"]
                    output += "\tCurrent Temp: %s C\n" % temp["ReadingCelsius"]
                    if "UpperThresholdCritical" in temp:
                        output += "\tCritical Threshold: %s C\n" % temp["UpperThresholdCritical"]
                    else:
                        output += "\tCritical Threshold: -\n"
                    if "UpperThresholdFatal" in temp:
                        output += "\tFatal Threshold: %s C\n" % temp["UpperThresholdFatal"]
                    else:
                        output += "\tFatal Threshold: -\n"
                    try:
                        if "Health" in temp["Status"]:
                            output += "\tHealth: %s\n" % temp["Status"]["Health"]
                    except KeyError:
                        pass
                    if absent:
                        try:
                            output += "\tState: %s\n" % temp["Status"]["State"]
                        except KeyError:
                            pass
            self.rdmc.ui.printer(output, verbose_override=True)

    def serverinfovalidation(self, options):
        """serverinfo method validation function.

        :param options: command line options
        :type options: list.
        """
        self.cmdbase.login_select_validation(self, options)

    def optionsvalidation(self, options):
        """Checks/updates options.
        :param options: command line options
        :type options: list
        """
        optlist = [
            options.proxy,
            options.firmware,
            options.software,
            options.memory,
            options.thermals,
            options.fans,
            options.power,
            options.processors,
            options.system,
        ]

        if not any(optlist):
            self.setalloptionstrue(options)
        if options.all:
            self.setalloptionstrue(options)
        return options

    def setalloptionstrue(self, options):
        """Updates all selector options values to be True.
        :param options: command line options
        :type options: list
        """
        options.memory = True
        options.thermals = True
        options.firmware = True
        options.software = True
        options.fans = True
        options.processors = True
        options.power = True
        options.system = True
        options.proxy = True
        options.showabsent = True

    def definearguments(self, customparser):
        """Wrapper function for new command main function

        :param customparser: command line input
        :type customparser: parser.
        """
        if not customparser:
            return

        self.cmdbase.add_login_arguments_group(customparser)

        customparser.add_argument(
            "-all",
            "--all",
            dest="all",
            action="store_true",
            help="Add information for all types.",
            default=False,
        )
        customparser.add_argument(
            "-fw",
            "--firmware",
            dest="firmware",
            action="store_true",
            help="Add firmware information to the output.",
            default=False,
        )
        customparser.add_argument(
            "-sw",
            "--software",
            dest="software",
            action="store_true",
            help="Add software information to the output.",
            default=False,
        )
        customparser.add_argument(
            "-memory",
            "--memory",
            dest="memory",
            action="store_true",
            help="Add memory DIMM information to the output.",
            default=False,
        )
        customparser.add_argument(
            "-fans",
            "--fans",
            dest="fans",
            action="store_true",
            help="Add fans information to the output.",
            default=False,
        )
        customparser.add_argument(
            "-processors",
            "--processors",
            dest="processors",
            action="store_true",
            help="Add processor(s) information to the output.",
            default=False,
        )
        customparser.add_argument(
            "-thermals",
            "--thermals",
            dest="thermals",
            action="store_true",
            help="Add thermal information to the output.",
            default=False,
        )
        customparser.add_argument(
            "-power",
            "--power",
            dest="power",
            action="store_true",
            help="Add power information to the output.",
            default=False,
        )
        customparser.add_argument(
            "-system",
            "--system",
            dest="system",
            action="store_true",
            help="Add basic system information to the output.",
            default=False,
        )
        customparser.add_argument(
            "--showabsent",
            dest="showabsent",
            action="store_true",
            help="Include information on absent components in the output.",
            default=False,
        )
        customparser.add_argument(
            "-proxy",
            "--proxy",
            dest="proxy",
            action="store_true",
            help="Add proxy information to the output",
            default=False,
        )
        customparser.add_argument(
            "-j",
            "--json",
            dest="json",
            action="store_true",
            help="Optionally include this flag if you wish to change the"
            " displayed output to JSON format. Preserving the JSON data"
            " structure makes the information easier to parse.",
            default=False,
        )
