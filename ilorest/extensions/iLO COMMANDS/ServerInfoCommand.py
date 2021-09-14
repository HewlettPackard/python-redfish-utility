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

from argparse import ArgumentParser, SUPPRESS
from collections import OrderedDict

import jsonpath_rw

from ilorest.rdmc_helper import ReturnCodes, InvalidCommandLineError, InvalidCommandLineErrorOPTS, UI

class ServerInfoCommand():
    """ Show details of a server """
    def __init__(self):
        self.ident = {
            'name':'serverinfo',
            'usage': None,
            'description': 'Shows all information.\n\tExample: serverinfo\n\t\t'
                    ' serverinfo --all\n\n\t'
                    'Show enabled fan, processor, and thermal information.\n\texample: '
                    'serverinfo --fans --processors --thermals --proxy\n\n\tShow all memory '
                    'and fan information, including absent locations in json format.\n\t'
                    'example: serverinfo --proxy --firmware --software --memory --fans --showabsent -j',
            'summary':'Shows aggregate health status and details of the currently logged in server.',
            'aliases': ['health', 'serverstatus', 'systeminfo'],
            'auxcommands': []
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """ Main serverinfo function.

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

        if args:
            raise InvalidCommandLineError("serverinfo command takes no "
                                          "arguments.")

        self.serverinfovalidation(options)

        self.optionsvalidation(options)

        info = self.gatherinfo(options)

        if not info:
            raise InvalidCommandLineError("Please verify the commands entered "
                                          "and try again.")

        if options.json:
            UI().print_out_json(info)
        else:
            self.prettyprintinfo(info, options.showabsent)

        self.cmdbase.logout_routine(self, options)
        #Return code
        return ReturnCodes.SUCCESS

    def gatherinfo(self, options):
        """ Gather info to printout based on options

        :param options: command line options
        :type options: list.
        """
        info = {}
        if options.system:
            info['system'] = OrderedDict()
            csysresults = self.rdmc.app.select(selector="ComputerSystem.")

            try:
                csysresults = csysresults[0].dict
            except:
                pass
            if csysresults:
                info['system']['Model'] = "%s %s" % (csysresults['Manufacturer'],
                                                     csysresults['Model'])
                info['system']['Bios Version'] = csysresults['BiosVersion']

            biosresults = self.rdmc.app.select(selector=self.rdmc.app.typepath.defs.biostype)

            try:
                biosresults = biosresults[0].dict
            except:
                pass

            if biosresults:
                try:
                    info['system']['Serial Number'] = biosresults['Attributes']['SerialNumber']
                except:
                    if 'SerialNumber' in biosresults:
                        info['system']['Serial Number'] = biosresults['SerialNumber']

            getloc = self.rdmc.app.getidbytype("EthernetInterfaceCollection.")
            if getloc:
                for loc in getloc:
                    if "/systems/1/" in loc.lower():
                        ethresults = self.rdmc.app.getcollectionmembers(loc)
                        break
                if ethresults:
                    niccount = 0
                    info['system']['ethernet'] = OrderedDict()
                    for eth in ethresults:
                        niccount += 1
                        info['system']['ethernet'][eth['Name']] = eth['MACAddress']
                    info['system']['NICCount'] = niccount
        if options.thermals or options.fans:
            getloc = self.rdmc.app.getidbytype('Thermal.')
            if getloc:
                data = self.rdmc.app.get_handler(getloc[0], silent=True, service=True)
            if options.thermals:
                if not getloc:
                    info['thermals'] = None
                else:
                    info['thermals'] = data.dict['Temperatures']
                    info['thermals']
            if options.fans:
                if not data:
                    info['fans'] = None
                else:
                    info['fans'] = data.dict['Fans']
        if options.memory:
            getloc = self.rdmc.app.getidbytype('MemoryCollection.')
            if getloc:
                data = self.rdmc.app.getcollectionmembers(getloc[0], fullresp=True)[0]
            else:
                info['memory'] = None
            info['memory'] = data
        if options.proxy:
            getloc = self.rdmc.app.getidbytype('NetworkProtocol.')
            if getloc:
                data = self.rdmc.app.getcollectionmembers(getloc[0], fullresp=True)[0]
            else:
                info['proxy'] = None
            info['proxy'] = data
        if options.processors:
            getloc = self.rdmc.app.getidbytype('ProcessorCollection.')
            if getloc:
                data = self.rdmc.app.getcollectionmembers(getloc[0])
            else:
                info['processor'] = None
            info['processor'] = data
        if options.power:
            getloc = self.rdmc.app.getidbytype('Power.')
            if getloc:
                data = self.rdmc.app.get_handler(getloc[0], silent=True, service=True)
            else:
                info['power'] = None
            info['power'] = data.dict
        if options.firmware:
            data = None
            getloc = self.rdmc.app.getidbytype('SoftwareInventoryCollection.')
            for gloc in getloc:
                if 'FirmwareInventory' in gloc:
                    data = self.rdmc.app.getcollectionmembers(gloc)
            info['firmware'] = data
        if options.software:
            data = None
            getloc = self.rdmc.app.getidbytype('SoftwareInventoryCollection.')
            for gloc in getloc:
                if 'SoftwareInventory' in gloc:
                    data = self.rdmc.app.getcollectionmembers(gloc)
            info['software'] = data
        if not options.showabsent:
            jsonpath_expr = jsonpath_rw.parse('$..State')
            matches = jsonpath_expr.find(info)
            matches.reverse()

            for match in matches:
                if match.value.lower() == "absent":
                    arr = None
                    statepath = '/' + str(match.full_path).replace('.', '/')
                    arr = re.split("[\[\]]", statepath)
                    if arr:
                        removedict = None
                        start = arr[0].split('/')
                        for key in start:
                            if key:
                                if not removedict:
                                    removedict = info[key]
                                else:
                                    removedict = removedict[key]
                        del removedict[int(arr[1])]

        return info

    def prettyprintinfo(self, info, absent):
        """ Print info in human readable form from json

        :param info: info data collected
        :type info: dict.
        :param absent: flag to show or hide absent components
        :type absent: bool.
        """
        output = ""
        headers = list(info.keys())
        if 'system' in headers:
            data = info['system']
            output = '------------------------------------------------\n'
            output += 'System Information:\n'
            output += '------------------------------------------------\n'
            for key, val in list(data.items()):
                if key == 'ethernet':
                    output += "Embedded NIC Count: %s\n" % data['NICCount']
                    for name in sorted(data['ethernet']):
                        output += "%s MAC: %s\n" % (name, data['ethernet'][name])
                elif not key == "NICCount":
                    output += "%s: %s\n" % (key, val)
            self.rdmc.ui.printer(output, verbose_override=True)

        if 'firmware' in headers:
            output = ""
            data = info['firmware']
            output = '------------------------------------------------\n'
            output += 'Firmware Information\n'
            output += '------------------------------------------------\n'
            for fw in data:
                output += "%s : %s\n" % (fw['Name'], fw['Version'])
            self.rdmc.ui.printer(output, verbose_override=True)

        if 'software' in headers:
            output = ""
            data = info['software']
            output = '------------------------------------------------\n'
            output += 'Software Information\n'
            output += '------------------------------------------------\n'
            for sw in data:
                output += "%s : %s\n" % (sw['Name'], sw['Version'])
            self.rdmc.ui.printer(output, verbose_override=True)

        if 'proxy' in headers:
            output = ""
            data = info['proxy']
            output = '------------------------------------------------\n'
            output += 'Proxy Information\n'
            output += '------------------------------------------------\n'
            try:
                proxy_info = data['Oem']['Hpe']['WebProxyConfiguration']
                for k,v in proxy_info.items():
                    output += "%s : %s\n" % (k, v)
            except KeyError:
                pass
            self.rdmc.ui.printer(output, verbose_override=True)

        if 'processor' in headers:
            output = ""
            data = info['processor']
            for processor in data:
                output = '------------------------------------------------\n'
                output += "Processor %s:\n" % processor['Id']
                output += '------------------------------------------------\n'
                output += "Model: %s\n" % processor['Model']
                output += "Step: %s\n" % processor['ProcessorId']['Step']
                output += "Socket: %s\n" % processor['Socket']
                output += "Max Speed: %s MHz\n" % processor['MaxSpeedMHz']
                try:
                    output += "Speed: %s MHz\n" % processor['Oem']\
                                [self.rdmc.app.typepath.defs.oemhp]['RatedSpeedMHz']
                except KeyError:
                    pass
                output += "Cores: %s\n" % processor['TotalCores']
                output += "Threads: %s\n" % processor['TotalThreads']
                try:
                    for cache in processor['Oem'][self.rdmc.app.typepath.defs.oemhp]['Cache']:
                        output += "%s: %s KB\n" % (cache['Name'], cache['InstalledSizeKB'])
                except KeyError:
                    pass
                output += "Health: %s\n" % processor['Status']['Health']
                if absent:
                    try:
                        output += "State: %s\n" % processor['Status']['State']
                    except KeyError:
                        pass
                self.rdmc.ui.printer(output, verbose_override=True)

        if 'memory' in headers:
            data = info['memory']
            collectiondata = data['Oem'][self.rdmc.app.typepath.defs.oemhp]
            output = '------------------------------------------------\n'
            output += "Memory/DIMM Board Information:\n"
            output += '------------------------------------------------\n'
            output += "Advanced Memory Protection Status: %s\n" % collectiondata['AmpModeStatus']
            for board in collectiondata['MemoryList']:
                output += "Board CPU: %s \n" % board['BoardCpuNumber']
                output += "\tTotal Memory Size: %s MiB\n" % board['BoardTotalMemorySize']
                output += "\tBoard Memory Frequency: %s MHz\n" % board['BoardOperationalFrequency']
                output += "\tBoard Memory Voltage: %s MiB\n" % board['BoardOperationalVoltage']
            output += '------------------------------------------------\n'
            output += "Memory/DIMM Configuration:\n"
            output += '------------------------------------------------\n'
            for dimm in data[self.rdmc.app.typepath.defs.collectionstring]:
                output += "Location: %s\n" % dimm['DeviceLocator']
                try:
                    output += "Memory Type: %s %s\n" % (dimm['MemoryType'],
                                                        dimm['MemoryDeviceType'])
                except KeyError:
                    output += "Memory Type: %s\n" % dimm['MemoryType']
                output += "Capacity: %s MiB\n" % dimm['CapacityMiB']
                try:
                    output += "Speed: %s MHz\n" % dimm['OperatingSpeedMhz']
                except KeyError:
                    pass
                output += "Status: %s\n" % dimm['Oem'][self.rdmc.app.typepath.defs.oemhp]\
                                                                                    ['DIMMStatus']
                output += "Health: %s\n" % dimm['Status']['Health']
                if absent:
                    output += "State: %s\n" % dimm['Status']['State']
                output += '\n'
            self.rdmc.ui.printer(output, verbose_override=True)

        if 'power' in headers:
            data = info['power']
            output = '------------------------------------------------\n'
            output += "Power Information:\n"
            output += '------------------------------------------------\n'
            for control in data['PowerControl']:
                output += 'Total Power Capacity: %s W\n' % control['PowerCapacityWatts']
                output += 'Total Power Consumed: %s W\n' % control['PowerConsumedWatts']
                output += '\n'
                output += 'Power Metrics on %s min. Intervals:\n' % control['PowerMetrics']\
                                                                        ['IntervalInMin']
                output += '\tAverage Power: %s W\n' % control['PowerMetrics']\
                                                        ['AverageConsumedWatts']
                output += '\tMax Consumed Power: %s W\n' % control['PowerMetrics']\
                                                        ['MaxConsumedWatts']
                output += '\tMinimum Consumed Power: %s W\n' % control['PowerMetrics']\
                                                        ['MinConsumedWatts']
            try:
                for supply in data['PowerSupplies']:
                    output += '------------------------------------------------\n'
                    output += "Power Supply %s:\n" % supply['Oem']\
                                    [self.rdmc.app.typepath.defs.oemhp]['BayNumber']
                    output += '------------------------------------------------\n'

                    output += 'Power Capacity: %s W\n' % supply['PowerCapacityWatts']
                    output += 'Last Power Output: %s W\n' % supply['LastPowerOutputWatts']
                    output += 'Input Voltage: %s V\n' % supply['LineInputVoltage']
                    output += 'Input Voltage Type: %s\n' % supply['LineInputVoltageType']
                    output += "Hotplug Capable: %s\n" % supply['Oem']\
                                        [self.rdmc.app.typepath.defs.oemhp]['HotplugCapable']
                    output += "iPDU Capable: %s\n" % supply['Oem']\
                                        [self.rdmc.app.typepath.defs.oemhp]['iPDUCapable']

                    output += "Health: %s\n" % supply['Status']['Health']
                    output += "State: %s\n" % supply['Status']['State']

                for redundancy in data['Redundancy']:
                    output += '------------------------------------------------\n'
                    output += '%s\n' % redundancy['Name']
                    output += '------------------------------------------------\n'
                    output += 'Redundancy Mode: %s\n' % redundancy['Mode']
                    output += 'Redundancy Health: %s\n' % redundancy['Status']['Health']
                    output += 'Redundancy State: %s\n' % redundancy['Status']['State']
            except KeyError:
                pass
            self.rdmc.ui.printer(output, verbose_override=True)

        if 'fans' in headers:
            output = '------------------------------------------------\n'
            output += "Fan(s) Information:\n"
            output += '------------------------------------------------\n'
            for fan in info['fans']:
                output += '%s:\n' % fan['Name']
                output += '\tLocation: %s\n' % fan['Oem'][self.rdmc.app.typepath.defs.oemhp]\
                                                            ['Location']
                output += '\tReading: %s%%\n' % fan['Reading']
                output += '\tRedundant: %s\n' % fan['Oem'][self.rdmc.app.typepath.defs.oemhp]\
                                                            ['Redundant']
                output += '\tHot Pluggable: %s\n' % fan['Oem'][self.rdmc.app.typepath.defs.oemhp]\
                                                            ['HotPluggable']
                try:
                    output += '\tHealth: %s\n' % fan['Status']['Health']
                except KeyError:
                    pass

                if absent:
                    output += "\tState: %s\n" % fan['Status']['State']
            self.rdmc.ui.printer(output, verbose_override=True)

        if 'thermals' in headers:
            output = '------------------------------------------------\n'
            output += "Thermal Information:\n"
            output += '------------------------------------------------\n'
            for temp in info['thermals']:
                output += 'Sensor #%s:\n' % temp['SensorNumber']
                output += '\tLocation: %s\n' % temp['PhysicalContext']
                output += '\tCurrent Temp: %s C\n' % temp['ReadingCelsius']
                if temp['UpperThresholdCritical']:
                    output += '\tCritical Threshold: %s C\n' % temp['UpperThresholdCritical']
                else:
                    output += '\tCritical Threshold: -\n'
                if temp['UpperThresholdFatal']:
                    output += '\tFatal Threshold: %s C\n' % temp['UpperThresholdFatal']
                else:
                    output += '\tFatal Threshold: -\n'
                try:
                    output += '\tHealth: %s\n' % temp['Status']['Health']
                except KeyError:
                    pass
                if absent:
                    output += "\tState: %s\n" % temp['Status']['State']
            self.rdmc.ui.printer(output, verbose_override=True)

    def serverinfovalidation(self, options):
        """ serverinfo method validation function.

        :param options: command line options
        :type options: list.
        """
        self.cmdbase.login_select_validation(self, options)

    def optionsvalidation(self, options):
        """ Checks/updates options.
        :param options: command line options
        :type options: list
        """
        optlist = [options.proxy, options.firmware, options.software, options.memory, options.thermals, options.fans,
                   options.power, options.processors, options.system, options.showabsent]
        if not any(optlist):
            self.setalloptionstrue(options)
        if options.all:
            self.setalloptionstrue(options)
        return options

    def setalloptionstrue(self, options):
        """ Updates all selector options values to be True
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
        """ Wrapper function for new command main function

        :param customparser: command line input
        :type customparser: parser.
        """
        if not customparser:
            return

        self.cmdbase.add_login_arguments_group(customparser)

        customparser.add_argument(
            '-all',
            '--all',
            dest='all',
            action="store_true",
            help="Add information for all types.",
            default=False
        )
        customparser.add_argument(
            '-fw',
            '--firmware',
            dest='firmware',
            action="store_true",
            help="Add firmware information to the output.",
            default=False,
        )
        customparser.add_argument(
            '-sw',
            '--software',
            dest='software',
            action="store_true",
            help="Add software information to the output.",
            default=False,
        )
        customparser.add_argument(
            '-memory',
            '--memory',
            dest='memory',
            action="store_true",
            help="Add memory DIMM information to the output.",
            default=False,
        )
        customparser.add_argument(
            '-fans',
            '--fans',
            dest='fans',
            action="store_true",
            help="Add fans information to the output.",
            default=False,
        )
        customparser.add_argument(
            '-processors',
            '--processors',
            dest='processors',
            action="store_true",
            help="Add processor(s) information to the output.",
            default=False,
        )
        customparser.add_argument(
            '-thermals',
            '--thermals',
            dest='thermals',
            action="store_true",
            help="Add thermal information to the output.",
            default=False,
        )
        customparser.add_argument(
            '-power',
            '--power',
            dest='power',
            action="store_true",
            help="Add power information to the output.",
            default=False,
        )
        customparser.add_argument(
            '-system',
            '--system',
            dest='system',
            action="store_true",
            help="Add basic system information to the output.",
            default=False,
        )
        customparser.add_argument(
            '--showabsent',
            dest='showabsent',
            action="store_true",
            help="Include information on absent components in the output.",
            default=False,
        )
        customparser.add_argument(
            '-proxy',
            '--proxy',
            dest='proxy',
            action="store_true",
            help="Add proxy information to the output",
            default=False,
        )
        customparser.add_argument(
            '-j',
            '--json',
            dest='json',
            action="store_true",
            help="Optionally include this flag if you wish to change the"\
            " displayed output to JSON format. Preserving the JSON data"\
            " structure makes the information easier to parse.",
            default=False
        )
