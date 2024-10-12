###
# Copyright 2019 Hewlett Packard Enterprise, Inc. All rights reserved.
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
""" Certificates Command for rdmc """

import copy
import json
import re
from argparse import RawDescriptionHelpFormatter
from collections import OrderedDict

import redfish.ris
from redfish.ris.ris import RisInstanceNotFoundError
from redfish.ris.rmc_helper import (
    IloResponseError,
    IncompatibleiLOVersionError,
    InvalidPathError,
)
from redfish.ris.utils import diffdict, json_traversal, json_traversal_delete_empty

try:
    from rdmc_helper import (
        UI,
        Encryption,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        InvalidFileInputError,
        InvalidPropertyError,
        NoDifferencesFoundError,
        RdmcError,
        ReturnCodes,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        UI,
        Encryption,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        InvalidFileInputError,
        InvalidPropertyError,
        NoDifferencesFoundError,
        RdmcError,
        ReturnCodes,
    )

__eth_file__ = "eth.json"
__subparsers__ = ["save", "load"]


class EthernetCommand:
    """ Commands for Ethernet Management Controller and RDE supported NIC card \
        configuration on server """

    def __init__(self):
        self.ident = {
            "name": "ethernet",
            "usage": None,
            "description": "Save or load from a JSON formatted file containing "
            "properties pertaining to a system's iLO ethernet management controller. "
            "Additionally enable/disable individual management controller NICs (including VNIC), "
            "IPv4 and IPv6 addressing configuration and domain name servers."
            "\n\tBy default the JSON file will be named 'eth.json'.\n\t"
            "\n\t***Credentials for an iLO administrator level account must be provided as"
            " well as the iLO base URL.***"
            "\n\n\tSave ethernet management controller data.\n\texample: ethernet save "
            "\n\n\tLoad ethernet management controller data.\n\texample: ethernet load"
            "\n\n\tSave ethernet management controller data to a different file, silently\n\t"
            "ethernet save -f <filename> --silent"
            "\n\n\tLoad etherent management controller data from a different file, silently\n\t"
            "ethernet load -f <filename> --silent"
            "\n\n\tEnable network interfaces by listing each interface to be enabled. **Note**: "
            "Non-existent interfaces will be omitted from configuration.\n\t "
            "ethernet --enable_nic 1,2,3"
            "\n\n\tDisable network interfaces by listing each interface to be disabled. **Note**: "
            "Non-existent interfaces will be omitted from configuration.\n\t "
            "ethernet --disable_nic 1,2,3"
            "\n\n\tEnable virtual network interface of management network.\n\t"
            "ethernet --enable_vnic"
            "\n\n\tDisable virtual network interface of management network.\n\t  "
            "ethernet --disable_vnic"
            "\n\n\tEnable Enhanced Download Performance.\n\t"
            "ethernet --enable_enhanced_downloads"
            "\n\n\tDisable Enhanced Download Performance.\n\t  "
            "ethernet --disable_enhanced_downloads"
            "\n\n\tConfigure Domain Name Servers (DNS) in a list: <DNS1> <DNS2> <DNS3>\n\t"
            "ethernet --nameservers 8.8.8.8,1.1.1.1,2.2.2.2 OR ethernet --nameservers "
            "dns_resolver1.aws.com,dns_resolver2.aws.com"
            "\n\n\tConfigure Static IPv4 Settings. Provide a list of network settings\n\t"
            "ethernet --network_ipv4 <ipv4 address>,<ipv4 gateway>,<ipv4 network mask>"
            "\n\n\tConfigure Proxy Settings. Provide a proxy server and port\n\t"
            "ethernet --proxy http://proxy.company.net:8080"
            "\n\n\tClear Proxy Settings. \n\t"
            "ethernet --proxy None"
            "\n\n\tConfigure Static IPv6 Settings. Provide a list of network settings\n\t"
            "ethernet --network_ipv6 <ipv6 address>,<ipv6 gateway>,<ipv6 network mask>",
            "summary": "Command for configuring Ethernet Management Controller Interfaces and " "associated properties",
            "aliases": [],
            "auxcommands": ["IloResetCommand"],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()
        self.save = None
        self.load = None
        self.eth_file = None  # set in validation
        self.eth_args = None
        self.saved_inputline = None  # set in validation

    def run(self, line, help_disp=False):
        """Main Ethernet Management Controller Interfaces Run
        :param line: string of arguments passed in
        :type line: str.
        :param help_disp: display help flag
        :type line: bool.
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
        except:
            if ("-h" in line) or ("--help" in line):
                return ReturnCodes.SUCCESS
            else:
                raise InvalidCommandLineErrorOPTS("")

        self.ethernetvalidation(options)

        if "default" in options.command.lower():
            # flags are used to showing data with respect to enhance download
            flag = True
            return_flag = True
            if options.enable_enhanced_downloads or options.disable_enhanced_downloads:
                ilo_ver = self.rdmc.app.getiloversion()
                self.rdmc.ui.printer("iLO Version is " + str(ilo_ver) + "\n")
                if ilo_ver < 5.263:
                    raise IncompatibleiLOVersionError("Enhance download required minimum " "iLO Version iLO5.263")
                # net_path = self.rdmc.app.getidbytype('NetworkProtocol.')
                net_path = self.rdmc.app.typepath.defs.managerpath + "NetworkProtocol"
                results = self.rdmc.app.get_handler(net_path, silent=True, service=True).dict
                body = dict()
                body["Oem"] = {}
                body["Oem"]["Hpe"] = {}
                if options.enable_enhanced_downloads:
                    if results["Oem"]["Hpe"]["EnhancedDownloadPerformanceEnabled"]:
                        self.rdmc.ui.printer(
                            "Enhanced Download Performance " "already enabled!! \n",
                            verbose_override=True,
                        )
                        return_flag = False
                    else:
                        self.rdmc.ui.printer("Enabling enhanced " "downloads...\n", verbose_override=True)
                        body["Oem"]["Hpe"]["EnhancedDownloadPerformanceEnabled"] = True
                        flag = False
                else:
                    if not results["Oem"]["Hpe"]["EnhancedDownloadPerformanceEnabled"]:
                        self.rdmc.ui.printer(
                            "Enhanced Download Performance " "already disabled!!\n\n",
                            verbose_override=True,
                        )
                        return_flag = False
                    else:
                        self.rdmc.ui.printer("Disabling enhanced " "downloads...\n", verbose_override=True)
                        body["Oem"]["Hpe"]["EnhancedDownloadPerformanceEnabled"] = False
                        flag = False
                if options.enable_vnic or options.disable_vnic:
                    self.rdmc.app.patch_handler(net_path, body, service=False, silent=True)
                elif return_flag:
                    self.rdmc.app.patch_handler(net_path, body, service=False, silent=False)
            if options.enable_vnic or options.disable_vnic:
                results = self.rdmc.app.get_handler(
                    self.rdmc.app.typepath.defs.managerpath, service=True, silent=True
                ).dict
                body = dict()
                body["Oem"] = {}
                body["Oem"]["Hpe"] = {}
                if options.enable_vnic:
                    if results["Oem"]["Hpe"]["VirtualNICEnabled"]:
                        self.rdmc.ui.printer("Virtual NIC already enabled!!\n", verbose_override=True)
                        return ReturnCodes.SUCCESS
                    self.rdmc.ui.printer("Enabling Virtual NIC...\n", verbose_override=True)
                    body["Oem"]["Hpe"]["VirtualNICEnabled"] = True
                else:
                    if not results["Oem"]["Hpe"]["VirtualNICEnabled"]:
                        self.rdmc.ui.printer("Virtual NIC already disabled!!\n", verbose_override=True)
                        return ReturnCodes.SUCCESS
                    self.rdmc.ui.printer("Disabling Virtual NIC...\n", verbose_override=True)
                    body["Oem"]["Hpe"]["VirtualNICEnabled"] = False
                self.rdmc.app.patch_handler(
                    self.rdmc.app.typepath.defs.managerpath,
                    body,
                    service=False,
                    silent=False,
                )
                self.rdmc.ui.printer("Warning: Resetting iLO...\n")
                self.auxcommands["iloreset"].run("")
                self.rdmc.ui.printer("You will need to re-login to access this system...\n")
            elif flag and return_flag:
                data = self.get_data(options)
                get_data = True
                for inst in data:
                    if "ethernetinterface" in inst.lower() or "ethernetnetworkinterface" in inst.lower():
                        for path in data[inst]:
                            if (
                                "managers/1/ethernetinterfaces/1" in path.lower()
                                or "managers/1/ethernetnetworkinterfaces/1" in path.lower()
                            ):  # only process managers interfaces
                                if options.enable_nic or options.disable_nic:
                                    get_data = False
                                    self.enable_disable_nics(data[inst][path], options)

                                if (
                                    options.network_ipv4 or options.network_ipv6 or options.nameservers or options.proxy
                                ) and "virtual" not in data[inst][path]["Name"].lower():
                                    get_data = False
                                    self.configure_static_settings(data[inst][path], options)
                                    if options.proxy:
                                        return ReturnCodes.SUCCESS
                    if "networkprotocol" in inst.lower():
                        for path in data[inst]:
                            if "managers/1/networkprotocol" in path.lower():
                                if options.enable_enhanced_downloads or options.disable_enhanced_downloads:
                                    get_data = False
                if get_data:
                    self.output_data(data, options, get_data)
                else:
                    self.load_main_function(options, data)

        if "save" in options.command.lower():
            self.save = True
            self.load = False
            if "save" in options.command.lower() and not options.ethfilename:
                self.rdmc.ui.printer("Saving configurations to default file '%s'.\n" % self.eth_file)
            self.output_data(self.get_data(options), options, False)

        elif "load" in options.command.lower():
            self.save = False
            self.load = True
            if options.force_network_config:
                self.load_main_function(options)
            else:
                self.rdmc.ui.printer("Skipping network configurations as " "--force_network_config is not included.\n")

        return ReturnCodes.SUCCESS

    def get_data(self, options):
        """Obtain data for Ethernet Management Interfaces, Ethernet System Interfaces, \
           Manager Network Services and iLO Date Time Types and subsequently save to a dictionary \
        :param options: command line options
        :type options: attribute
        """

        network_data_collection = eth_iface = manager_network_services = ilo_date_time = OrderedDict()

        if self.rdmc.app.redfishinst.is_redfish:
            try:
                iface_results = self.rdmc.app.select(selector="ethernetinterface.")
            except RisInstanceNotFoundError:
                self.rdmc.ui.printer("Type 'EthernetInterface.' not available.\n")
        else:
            try:
                iface_results = self.rdmc.app.select(selector="ethernetnetworkinterface.")
            except RisInstanceNotFoundError:
                self.rdmc.ui.printer("Type 'EthernetNetworkInterface.' not available.\n")

        for inst in iface_results:
            try:
                eth_iface[inst.type].update({inst.path: inst.dict})
            except KeyError:
                eth_iface[inst.type] = {inst.path: inst.dict}
                continue
            except AttributeError:
                self.rdmc.ui.printer("Missing instance data for type '%s' : '%s'" % (inst.type, inst.path))
        if self.rdmc.app.typepath.defs.isgen9:
            selector_content = self.rdmc.app.select(selector="ManagerNetworkService.0.11.1.networkprotocol")
        else:
            selector_content = self.rdmc.app.select(selector="networkprotocol.")
        for inst in selector_content:
            try:
                manager_network_services[inst.type].update({inst.path: inst.dict})
            except KeyError:
                manager_network_services[inst.type] = {inst.path: inst.dict}
                continue
            except AttributeError:
                self.rdmc.ui.printer("Missing instance data for type '%s' : '%s'" % (inst.type, inst.path))

        for inst in self.rdmc.app.select(selector="datetime."):
            try:
                ilo_date_time[inst.type].update({inst.path: inst.dict})
            except KeyError:
                ilo_date_time[inst.type] = {inst.path: inst.dict}
                continue
            except AttributeError:
                self.rdmc.ui.printer("Missing instance data for type '%s' : '%s'" % (inst.type, inst.path))

        network_data_collection.update(eth_iface)
        network_data_collection.update(manager_network_services)
        network_data_collection.update(ilo_date_time)

        return network_data_collection

    def output_data(self, data, options, get_only=False):
        """ Output data in requested json file or on console
        :param data: dictionary containing ethernet configuration data:
        :type data: dictionary
        :param options: command line options
        :type options: attribute
        :param get_only: parameter to only output to console (do not save data to file). \
        Essentially a targeted \'get\' command.
        :type: boolean
        """

        outdata = list()

        outdata.append(self.rdmc.app.create_save_header())

        for _type in data:
            for path in data.get(_type):
                temp = dict()
                try:
                    temp[_type.split("#")[-1]].update({path: self.rdmc.app.removereadonlyprops(data[_type][path])})
                    outdata.append(temp)
                except KeyError:
                    temp[_type.split("#")[-1]] = {path: self.rdmc.app.removereadonlyprops(data[_type][path])}
                    outdata.append(temp)
                except Exception:
                    pass

        if self.eth_file and not get_only:
            if options.encryption:
                with open(self.eth_file, "wb") as outfile:
                    outfile.write(
                        Encryption().encrypt_file(
                            json.dumps(outdata, indent=2, cls=redfish.ris.JSONEncoder),
                            options.encryption,
                        )
                    )
            else:
                with open(self.eth_file, "w") as outfile:
                    outfile.write(json.dumps(outdata, indent=2, cls=redfish.ris.JSONEncoder))
        else:
            if options.json:
                self.rdmc.ui.print_out_json_ordered(outdata)
            else:
                UI().print_out_human_readable(outdata)

    def enable_disable_nics(self, data, options):
        if options.disable_nic:
            for ident in re.split("[, ]", options.disable_nic):
                try:
                    if int(data.get("Id")) == int(ident):
                        data.update({"InterfaceEnabled": False})
                        break
                except ValueError:
                    if data.get("Name") == ident:
                        data.update({"InterfaceEnabled": False})
                        break

        if options.enable_nic:
            for ident in re.split("[, ]", options.enable_nic):
                try:
                    if int(data.get("Id")) == int(ident):
                        data.update({"InterfaceEnabled": True})
                        break
                except ValueError:
                    if data.get("Name") == ident:
                        data.update({"InterfaceEnabled": True})
                        break

    def configure_static_settings(self, data, options):
        if options.network_ipv4:
            usr_data = re.split("[, ]", options.network_ipv4)
            if len(usr_data) > 2:
                data["IPv4Addresses"][0] = {
                    "Address": usr_data[0],
                    "Gateway": usr_data[1],
                    "SubnetMask": usr_data[2],
                }
                data["DHCPv4"].update({"DHCPEnabled": False})
                data["Oem"][self.rdmc.app.typepath.defs.oemhp]["DHCPv4"].update({"Enabled": False})
            else:
                raise InvalidCommandLineErrorOPTS(
                    "An invalid number of arguments provided to "
                    " quick networking configuration. Check '--network_ipv4' entry."
                )
        else:
            del data["IPv4Addresses"]

        if options.network_ipv6:
            usr_data = re.split("[, ]", options.network_ipv6)
            if len(usr_data) > 2:
                next(iter(data["IPv6Addresses"])).update({"Address": usr_data[0], "PrefixLength": usr_data[2]})
                data["IPv6DefaultGateway"] = options.network_ipv6[1]
                data["DHCPv6"].update({"DHCPEnabled": False})
                data["Oem"][self.rdmc.app.typepath.defs.oemhp]["DHCPv6"].update({"Enabled": False})
            else:
                raise InvalidCommandLineErrorOPTS(
                    "An invalid number of arguments provided to "
                    " quick networking configuration. Check '--network_ipv6' entry."
                )
        else:
            del data["IPv6Addresses"]

        if options.nameservers:
            usr_data = re.split("[, ]", options.nameservers)
            if len(usr_data) <= 3:
                ipv6_list = list()
                ipv4_list = list()
                static_list = list()
                for elem in usr_data:
                    oem_ipv4 = data["Oem"][self.rdmc.app.typepath.defs.oemhp]["IPv4"]
                    oem_ipv6 = data["Oem"][self.rdmc.app.typepath.defs.oemhp]["IPv6"]
                    if "::" in elem:
                        ipv6_list.append(elem)
                    elif "." in elem:
                        ipv4_list.append(elem)
                    static_list.append(elem)
                oem_ipv6["DNSServers"] = ipv6_list
                oem_ipv4["DNSServers"] = ipv4_list
                data["StaticNameServers"] = static_list
            else:
                raise InvalidCommandLineErrorOPTS("Name Servers argument has to be less than or equal to 2")
        else:
            del data["StaticNameServers"]
            del data["Oem"][self.rdmc.app.typepath.defs.oemhp]["IPv4"]["DNSServers"]
            del data["Oem"][self.rdmc.app.typepath.defs.oemhp]["IPv6"]["DNSServers"]

        if options.proxy and options.proxy != "None":
            body = dict()
            body["Oem"] = {}
            body["Oem"]["Hpe"] = {}
            body["Oem"]["Hpe"]["WebProxyConfiguration"] = {}
            proxy_body = body["Oem"]["Hpe"]["WebProxyConfiguration"]
            proxy_body["ProxyServer"] = None
            proxy_body["ProxyUserName"] = None
            proxy_body["ProxyPassword"] = None
            if "https" in options.proxy:
                proxy_body["ProxyPort"] = 443
            else:
                proxy_body["ProxyPort"] = 80
            if "@" in options.proxy:
                proxy = options.proxy.split("@")
                proxy_usr_pass = proxy[0]
                proxy_srv_port = proxy[1]
                if "//" in proxy_usr_pass:
                    proxy_usr_pass = proxy_usr_pass.split("//")[1]
                if ":" in proxy_srv_port:
                    proxy = proxy_srv_port.split(":")
                    proxy_body["ProxyServer"] = proxy[0]
                    proxy_body["ProxyPort"] = int(proxy[1])
                else:
                    proxy_body["ProxyServer"] = proxy_srv_port
                if ":" in proxy_usr_pass:
                    proxy = proxy_usr_pass.split(":")
                    proxy_body["ProxyPassword"] = proxy[1]
                    proxy_body["ProxyUserName"] = proxy[0]
                else:
                    proxy_body["ProxyUserName"] = proxy_usr_pass
            else:
                proxy_srv_port = options.proxy
                if "//" in proxy_srv_port:
                    proxy_srv_port = proxy_srv_port.split("//")[1]
                if ":" in proxy_srv_port:
                    proxy = proxy_srv_port.split(":")
                    proxy_body["ProxyServer"] = proxy[0]
                    proxy_body["ProxyPort"] = int(proxy[1])
                else:
                    proxy_body["ProxyServer"] = proxy_srv_port
            path = self.rdmc.app.getidbytype("NetworkProtocol.")

            if path and body:
                self.rdmc.ui.printer("Enabling Proxy configuration...\n", verbose_override=True)
                self.rdmc.app.patch_handler(path[0], body, service=False, silent=False)
        elif options.proxy and options.proxy == "None":
            body = dict()
            body["Oem"] = {}
            body["Oem"]["Hpe"] = {}
            body["Oem"]["Hpe"]["WebProxyConfiguration"] = {}
            proxy_body = body["Oem"]["Hpe"]["WebProxyConfiguration"]
            proxy_body["ProxyServer"] = ""
            proxy_body["ProxyPort"] = None
            proxy_body["ProxyUserName"] = ""
            proxy_body["ProxyPassword"] = None
            path = self.rdmc.app.getidbytype("NetworkProtocol.")

            if path and body:
                self.rdmc.ui.printer("Clearing Proxy configuration...\n", verbose_override=True)
                self.rdmc.app.patch_handler(path[0], body, service=False, silent=False)

        json_traversal_delete_empty(data, None, None)

    def load_main_function(self, options, data=None):
        """
        Load main function. Handles SSO and SSL/TLS Certificates, kickoff load
        helper, load of patch file, get server status and issues system reboot
        and iLO reset after completion of all post and patch commands.
        :param options: command line options
        :type options: attribute
        :param data: data
        :type data: optional
        """

        if self.rdmc.app.redfishinst.is_redfish:
            _ = "ethernetinterface."
        else:
            _ = "ethernetnetworkinterface."

        if not data:
            data = {}
            try:
                if options.encryption:
                    with open(self.eth_file, "rb") as file_handle:
                        data = json.loads(Encryption().decrypt_file(file_handle.read(), options.encryption))
                else:
                    with open(self.eth_file, "rb") as file_handle:
                        data = json.loads(file_handle.read())
            except:
                raise InvalidFileInputError(
                    "Invalid file formatting found. Verify the file has a " "valid JSON format."
                )
        if "load" in options.command.lower():
            for d in data:
                for ilotype, subsect in d.items():
                    _type = ilotype.split(".")[0]
                    for _path in subsect:
                        if not subsect[_path]:
                            continue
                        elif "ethernetinterface" in _type.lower() or "ethernetnetworkinterface" in _type.lower():
                            if "managers" in _path.lower():
                                self.load_ethernet_aux(_type, _path, d[ilotype][_path])
                            elif "systems" in _path.lower():
                                self.rdmc.ui.warn("Systems Ethernet Interfaces '%s' " "cannot be modified." % _path)
                                continue
                        elif "datetime" in _type.lower():
                            if "StaticNTPServers" in list(subsect.get(_path).keys()):
                                # must set NTP Servers to static in OEM then reset iLO for StaticNTPServers
                                # property to appear in iLODateTime
                                if self.rdmc.app.redfishinst.is_redfish:
                                    eth_config_type = "ethernetinterface"
                                else:
                                    eth_config_type = "ethernetnetworkinterface"
                                for key in list(data.keys()):
                                    if key.split(".")[0].lower() == eth_config_type:
                                        eth_config_type = key
                                        for _path in data[eth_config_type]:
                                            if "managers" in _path.lower():
                                                try:
                                                    oemhp = self.rdmc.app.typepath.defs.oemhp
                                                    data[eth_config_type][_path]["DHCPv4"]["UseNTPServers"] = True
                                                    data[eth_config_type][_path]["DHCPv6"]["UseNTPServers"] = True
                                                    data[eth_config_type][_path]["Oem"][oemhp]["DHCPv4"][
                                                        "UseNTPServers"
                                                    ] = True
                                                    data[eth_config_type][_path]["Oem"][oemhp]["DHCPv6"][
                                                        "UseNTPServers"
                                                    ] = True
                                                    self.load_ethernet_aux(
                                                        eth_config_type,
                                                        _path,
                                                        data[eth_config_type][_path],
                                                    )
                                                except KeyError:
                                                    self.rdmc.ui.printer(
                                                        "Unable to configure " "'UseNTPServers' for '%s'.\n" % _path
                                                    )
                                                self.rdmc.ui.printer(
                                                    "iLO must be reset in order for "
                                                    "changes to static network time protocol servers to "
                                                    "take effect.\n"
                                                )
        elif "default" in options.command.lower():
            for ilotype, subsect in data.items():
                _type = ilotype.split(".")[0]
                for _path in subsect:
                    if not subsect[_path]:
                        continue
                    elif "ethernetinterface" in _type.lower() or "ethernetnetworkinterface" in _type.lower():
                        if "managers" in _path.lower():
                            self.load_ethernet_aux(_type, _path, data[ilotype][_path])
                        elif "systems" in _path.lower():
                            self.rdmc.ui.warn("Systems Ethernet Interfaces '%s' " "cannot be modified." % _path)
                            continue
                    elif "datetime" in _type.lower():
                        if "StaticNTPServers" in list(subsect.get(_path).keys()):
                            # must set NTP Servers to static in OEM then reset iLO for StaticNTPServers
                            # property to appear in iLODateTime
                            if self.rdmc.app.redfishinst.is_redfish:
                                eth_config_type = "ethernetinterface"
                            else:
                                eth_config_type = "ethernetnetworkinterface"
                            for key in list(data.keys()):
                                if key.split(".")[0].lower() == eth_config_type:
                                    eth_config_type = key
                                    for _path in data[eth_config_type]:
                                        if "managers" in _path.lower():
                                            try:
                                                oemhp = self.rdmc.app.typepath.defs.oemhp
                                                data[eth_config_type][_path]["DHCPv4"]["UseNTPServers"] = True
                                                data[eth_config_type][_path]["DHCPv6"]["UseNTPServers"] = True
                                                data[eth_config_type][_path]["Oem"][oemhp]["DHCPv4"][
                                                    "UseNTPServers"
                                                ] = True
                                                data[eth_config_type][_path]["Oem"][oemhp]["DHCPv6"][
                                                    "UseNTPServers"
                                                ] = True
                                                self.load_ethernet_aux(
                                                    eth_config_type,
                                                    _path,
                                                    data[eth_config_type][_path],
                                                )
                                            except KeyError:
                                                self.rdmc.ui.printer(
                                                    "Unable to configure " "'UseNTPServers' for '%s'.\n" % _path
                                                )
                                            self.rdmc.ui.printer(
                                                "iLO must be reset in order for "
                                                "changes to static network time protocol servers to "
                                                "take effect.\n"
                                            )

    def load_ethernet_aux(self, _type, _path, ethernet_data):
        """helper function for parsing and bucketting ethernet properties.
        :param _type: Redfish type used for querying the current server data
        :type _type: string
        :param _path: URI path to be patched.
        :type _path: string
        :param ethernet_data: JSON containing the ethernet instance (and valid, associated
                         properties) to be patched.
        :type ethernet_data: JSON

        """

        support_ipv6 = True
        dhcpv4curr = dhcpv4conf = oem_dhcpv4conf = dict()
        _ = dhcpv6conf = oem_dhcpv6conf = dict()
        errors = []

        ident_eth = False
        if "EthernetInterface" in _type:
            for curr_sel in self.rdmc.app.select(
                _type.split(".")[0] + ".",
                (
                    self.rdmc.app.typepath.defs.hrefstring,
                    self.rdmc.app.typepath.defs.managerpath + "*",
                ),
                path_refresh=True,
            ):
                if curr_sel.path == _path:
                    ident_eth = True
                    break
            # 'links/self/href' required when using iLO 4 (rest).
        elif "EthernetNetworkInterface" in _type:
            for curr_sel in self.rdmc.app.select(
                _type.split(".")[0] + ".",
                (
                    "links/self/" + self.rdmc.app.typepath.defs.hrefstring,
                    self.rdmc.app.typepath.defs.managerpath + "*",
                ),
                path_refresh=True,
            ):
                if curr_sel.path == _path:
                    ident_eth = True
                    break
        else:
            raise Exception("Invalid type in management NIC load operation: '%s'" % _type)

        if not ident_eth:
            raise InvalidPathError("Path: '%s' is invalid/not identified on this server.\n" % _path)

        ident_name = curr_sel.dict.get("Name")
        ident_id = curr_sel.dict.get("Id")
        # ENABLING ETHERNET INTERFACE SECTION
        try:
            # Enable the Interface if called for and not already enabled
            if ethernet_data.get("InterfaceEnabled") and not curr_sel.dict.get("InterfaceEnabled"):
                self.rdmc.app.patch_handler(_path, {"InterfaceEnabled": True}, silent=True)
                self.rdmc.ui.printer("NIC Interface Enabled.\n")
            # Disable the Interface if called for and not disabled already
            # No need to do anything else, just return
            elif not ethernet_data.get("InterfaceEnabled") and not curr_sel.dict.get("InterfaceEnabled"):
                self.rdmc.app.patch_handler(_path, {"InterfaceEnabled": False}, silent=True)
                self.rdmc.ui.warn("NIC Interface Disabled. All additional configurations " "omitted.")
                return
        except (KeyError, NameError, TypeError, AttributeError):
            # check OEM for NICEnabled instead
            if (
                not curr_sel.dict["Oem"][self.rdmc.app.typepath.defs.oemhp]["NICEnabled"]
                and ethernet_data["Oem"][self.rdmc.app.typepath.defs.oemhp]["NICEnabled"]
            ):
                self.rdmc.app.patch_handler(
                    _path,
                    {"Oem": {self.rdmc.app.typepath.defs.oemhp: {"NICEnabled": True}}},
                    silent=True,
                )
                self.rdmc.ui.printer("NIC Interface Enabled.\n")
            elif (
                not curr_sel.dict["Oem"][self.rdmc.app.typepath.defs.oemhp]["NICEnabled"]
                and not ethernet_data["Oem"][self.rdmc.app.typepath.defs.oemhp]["NICEnabled"]
            ):
                self.rdmc.app.patch_handler(
                    _path,
                    {"Oem": {self.rdmc.app.typepath.defs.oemhp: {"NICEnabled": False}}},
                    silent=True,
                )
                self.rdmc.ui.printer("NIC Interface Disabled.\n")
                return
        # except IloResponseError should just be raised and captured by decorator. No point in
        # performing any other operations if the interface can not be set.

        # END ENABLING ETHERNET INTEFACE SECTION
        # ---------------------------------------
        # DETERMINE DHCPv4 and DHCPv6 States and associated flags

        if "NICSupportsIPv6" in list(curr_sel.dict["Oem"][self.rdmc.app.typepath.defs.oemhp].keys()):
            support_ipv6 = curr_sel.dict["Oem"][self.rdmc.app.typepath.defs.oemhp]["NICSupportsIPv6"]

        # obtain DHCPv4 Config and OEM
        try:
            if "DHCPv4" in list(curr_sel.dict.keys()) and "DHCPv4" in list(ethernet_data.keys()):
                dhcpv4curr = copy.deepcopy(curr_sel.dict["DHCPv4"])
                dhcpv4conf = copy.deepcopy(ethernet_data["DHCPv4"])
        except (KeyError, NameError, TypeError, AttributeError):
            errors.append("Unable to find Redfish DHCPv4 Settings.\n")
        finally:
            try:
                oem_dhcpv4conf = copy.deepcopy(ethernet_data["Oem"][self.rdmc.app.typepath.defs.oemhp]["DHCPv4"])

            except (KeyError, NameError):
                errors.append("Unable to find OEM Keys for DHCPv4 or IPv4")

        try:
            if support_ipv6:
                if "DHCPv6" in list(curr_sel.dict.keys()) and "DHCPv6" in list(ethernet_data.keys()):
                    dhcpv6conf = copy.deepcopy(ethernet_data["DHCPv6"])
            else:
                self.rdmc.ui.warn("NIC Does not support IPv6.")
        except (KeyError, NameError, TypeError, AttributeError):
            errors.append("Unable to find Redfish DHCPv6 Settings.\n")
        finally:
            try:
                oem_dhcpv6conf = copy.deepcopy(ethernet_data["Oem"][self.rdmc.app.typepath.defs.oemhp]["DHCPv6"])
            except (KeyError, NameError):
                errors.append("Unable to find OEM Keys for DHCPv6 or IPv6")

        try:
            # if DHCP Enable request but not currently enabled
            if dhcpv4conf.get("DHCPEnabled") and not curr_sel.dict["DHCPv4"]["DHCPEnabled"]:
                self.rdmc.app.patch_handler(_path, {"DHCPv4": {"DHCPEnabled": True}}, silent=True)
                self.rdmc.ui.printer("DHCP Enabled.\n")
            # if DHCP Disable request but currently enabled
            elif not dhcpv4conf["DHCPEnabled"] and curr_sel.dict["DHCPv4"]["DHCPEnabled"]:
                self.rdmc.app.patch_handler(_path, {"DHCPv4": {"DHCPEnabled": False}}, silent=True)
                dhcpv4conf["UseDNSServers"] = False
                dhcpv4conf["UseNTPServers"] = False
                dhcpv4conf["UseGateway"] = False
                dhcpv4conf["UseDomainName"] = False
                self.rdmc.ui.printer("DHCP Disabled.\n")
        except (KeyError, NameError, TypeError, AttributeError):
            # try with OEM
            try:
                if (
                    oem_dhcpv4conf.get("Enabled")
                    and not curr_sel.dict["Oem"][self.rdmc.app.typepath.defs.oemhp]["DHCPv4"]["Enabled"]
                ):
                    self.rdmc.app.patch_handler(
                        _path,
                        {"Oem": {self.rdmc.app.typepath.defs.oemhp: {"DHCPv4": {"DHCPEnabled": True}}}},
                        silent=True,
                    )
                    self.rdmc.ui.printer("DHCP Enabled.\n")
                    if "IPv4Addresses" in ethernet_data:
                        del ethernet_data["IPv4Addresses"]
                elif (
                    not oem_dhcpv4conf.get("Enabled")
                    and curr_sel.dict["Oem"][self.rdmc.app.typepath.defs.oemhp]["DHCPv4"]["Enabled"]
                ):
                    oem_dhcpv4conf["UseDNSServers"] = False
                    oem_dhcpv4conf["UseNTPServers"] = False
                    oem_dhcpv4conf["UseGateway"] = False
                    oem_dhcpv4conf["UseDomainName"] = False
                    self.rdmc.ui.printer("DHCP Disabled.\n")
            except (KeyError, NameError) as exp:
                errors.append("Failure in parsing or removing data in OEM DHCPv4: %s.\n" % exp)

        try:
            # if the ClientIDType is custom and we are missing the ClientID then this property can
            # not be set.
            if "ClientIdType" in list(dhcpv4conf.keys()):
                if dhcpv4conf["ClientIdType"] == "Custom" and "ClientID" not in list(dhcpv4conf.keys()):
                    del ethernet_data["DHCPv4"]["ClientIdType"]
            elif "ClientIdType" in list(oem_dhcpv4conf.keys()):
                if oem_dhcpv4conf["ClientIdType"] == "Custom" and "ClientID" not in list(oem_dhcpv4conf.keys()):
                    del ethernet_data["Oem"][self.rdmc.app.typepath.defs.oemhp]["DHCPv4"]["ClientIdType"]
        except (KeyError, NameError, TypeError, AttributeError):
            try:
                if "ClientIdType" in list(oem_dhcpv4conf.keys()):
                    if oem_dhcpv4conf["ClientIdType"] == "Custom" and "ClientID" not in list(oem_dhcpv4conf.keys()):
                        del ethernet_data["Oem"][self.rdmc.app.typepath.defs.oemhp]["DHCPv4"]["ClientIdType"]
            except (KeyError, NameError) as exp:
                errors.append("Unable to remove property %s.\n" % exp)

        # special considerations go here for things that need to stay despite diffdict
        # EX: IPv4 addresses (aka bug). Changing only one property within the
        # IPv4StaticAddresses or IPv4Addresses causes an issue during load. Must include IP,
        # subnet mask and gateway (they can not be patched individually).
        # spec_dict = {'Oem': {self.rdmc.app.typepath.defs.oemhp: {}}}
        spec_dict = dict()
        if "IPv4Addresses" in ethernet_data:
            spec_dict["IPv4Addresses"] = copy.deepcopy(ethernet_data["IPv4Addresses"])
        try:
            if "IPv4Addresses" in ethernet_data["Oem"][self.rdmc.app.typepath.defs.oemhp]:
                spec_dict["Oem"][self.rdmc.app.typepath.defs.oemhp]["IPv4Addresses"] = copy.deepcopy(
                    ethernet_data["Oem"][self.rdmc.app.typepath.defs.oemhp]["IPv4StaticAddresses"]
                )
        except (KeyError, NameError, TypeError, AttributeError):
            pass

        # diff and overwrite the original payload
        ethernet_data = diffdict(ethernet_data, curr_sel.dict)
        ethernet_data.update(spec_dict)

        # verify dependencies on those flags which are to be applied are eliminated
        try:
            # delete Domain name and FQDN if UseDomainName for DHCPv4 or DHCPv6
            # is present. can wait to apply at the end
            if dhcpv4conf.get("UseDomainName"):  # or dhcpv6conf['UseDomainName']:
                if "DomainName" in ethernet_data["Oem"][self.rdmc.app.typepath.defs.oemhp]:
                    del ethernet_data["Oem"][self.rdmc.app.typepath.defs.oemhp]["DomainName"]
                if "FQDN" in ethernet_data:
                    del ethernet_data["FQDN"]
        except (KeyError, NameError, TypeError, AttributeError):
            # try again with OEM
            try:
                if oem_dhcpv4conf.get("UseDomainName") or oem_dhcpv6conf.get("UseDomainName"):
                    if (
                        "Oem" in ethernet_data
                        and "DomainName" in ethernet_data["Oem"][self.rdmc.app.typepath.defs.oemhp]
                    ):
                        del ethernet_data["Oem"][self.rdmc.app.typepath.defs.oemhp]["DomainName"]
                    if "FQDN" in ethernet_data:
                        del ethernet_data["FQDN"]
            except (KeyError, NameError) as exp:
                errors.append("Unable to remove property %s.\n" % exp)

        try:
            # delete DHCP4 DNSServers from IPV4 dict if UseDNSServers Enabled
            # can wait to apply at the end
            if dhcpv4conf.get("UseDNSServers"):  # and ethernet_data.get('NameServers'):
                json_traversal_delete_empty(data=ethernet_data, remove_list=["NameServers"])
        except (KeyError, NameError, TypeError, AttributeError):
            pass
        finally:
            try:
                if oem_dhcpv4conf.get("UseDNSServers"):
                    # del_sections('DNSServers', ethernet_data)
                    json_traversal_delete_empty(data=ethernet_data, remove_list=["DNSServers"])
            except (KeyError, NameError) as exp:
                errors.append("Unable to remove property %s.\n" % exp)
        try:
            if dhcpv4conf.get("UseWINSServers"):
                json_traversal_delete_empty(data=ethernet_data, remove_list=["WINServers"])
        except (KeyError, NameError, TypeError, AttributeError):
            pass
        finally:
            try:
                if oem_dhcpv4conf.get("UseWINSServers"):
                    json_traversal_delete_empty(
                        data=ethernet_data,
                        remove_list=["WINServers", "WINSRegistration"],
                    )
            except (KeyError, NameError) as exp:
                errors.append("Unable to remove property %s.\n" % exp)

        try:
            if dhcpv4conf.get("UseStaticRoutes"):
                json_traversal_delete_empty(data=ethernet_data, remove_list=["StaticRoutes"])
        except (KeyError, NameError, TypeError, AttributeError):
            pass
        finally:
            try:
                if oem_dhcpv4conf.get("UseStaticRoutes"):
                    json_traversal_delete_empty(data=ethernet_data, remove_list=["StaticRoutes"])
            except (KeyError, NameError) as exp:
                errors.append("Unable to remove property %s.\n" % exp)

        try:
            # if using DHCPv4, remove static addresses
            if dhcpv4conf.get("DHCPEnabled"):
                json_traversal_delete_empty(
                    data=ethernet_data,
                    remove_list=["IPv4Addresses", "IPv4StaticAddresses"],
                )
        except (KeyError, NameError, TypeError, AttributeError):
            pass
        finally:
            try:
                if oem_dhcpv4conf.get("Enabled"):
                    json_traversal_delete_empty(
                        data=ethernet_data,
                        remove_list=["IPv4Addresses", "IPv4StaticAddresses"],
                    )
            except (KeyError, NameError) as exp:
                errors.append("Unable to remove property %s.\n" % exp)

        try:
            # if not using DHCPv6, remove static addresses from payload
            if dhcpv6conf.get("OperatingMode") == "Disabled":
                json_traversal_delete_empty(
                    data=ethernet_data,
                    remove_list=["IPv6Addresses", "IPv6StaticAddresses"],
                )
        except (KeyError, NameError, TypeError, AttributeError):
            pass
        finally:
            try:
                if not oem_dhcpv6conf.get("StatefulModeEnabled"):
                    json_traversal_delete_empty(
                        data=ethernet_data,
                        remove_list=["IPv6Addresses", "IPv6StaticAddresses"],
                    )
            except (KeyError, NameError) as exp:
                errors.append("Unable to remove property %s.\n" % exp)

        flags = ethernet_data
        if "StaticNameServers" in flags:
            if dhcpv4curr["UseDNSServers"]:
                flags["DHCPv4"] = {"UseDNSServers": False}

        # verify dependencies on those flags which are to be applied are eliminated
        if (
            "IPv4Addresses" in flags
            and "Address" in flags["IPv4Addresses"][0]
            and "Address" in curr_sel.dict["IPv4Addresses"][0]
            and flags["IPv4Addresses"][0]["Address"] == curr_sel.dict["IPv4Addresses"][0]["Address"]
            and "Gateway" in flags["IPv4Addresses"][0]
            and "Gateway" in curr_sel.dict["IPv4Addresses"][0]
            and flags["IPv4Addresses"][0]["Gateway"] == curr_sel.dict["IPv4Addresses"][0]["Gateway"]
            and "SubnetMask" in flags["IPv4Addresses"][0]
            and "SubnetMask" in curr_sel.dict["IPv4Addresses"][0]
            and flags["IPv4Addresses"][0]["SubnetMask"] == curr_sel.dict["IPv4Addresses"][0]["SubnetMask"]
        ):
            del flags["IPv4Addresses"]
        try:
            if not flags:
                self.rdmc.ui.warn("No change in configurations in " + _path)
            else:
                self.rdmc.app.patch_handler(_path, flags, silent=True)
        except IloResponseError as excp:
            errors.append("iLO Responded with the following errors setting DHCP: %s.\n" % excp)

        try:
            if "AutoNeg" not in list(ethernet_data.keys()):
                json_traversal_delete_empty(data=ethernet_data, remove_list=["FullDuplex", "SpeedMbps"])

            # if Full Duplex exists, check if FullDuplexing enabled. If so,
            # remove Speed setting.
            elif "FullDuplex" in list(ethernet_data.keys()):
                json_traversal_delete_empty(data=ethernet_data, remove_list=["FullDuplex", "SpeedMbps"])
        except (KeyError, NameError) as exp:
            errors.append("Unable to remove property %s.\n" % exp)

        try:
            if "FrameSize" in list(ethernet_data.keys()):
                json_traversal_delete_empty(data=ethernet_data, remove_list=["FrameSize"])
        except (KeyError, NameError) as exp:
            errors.append("Unable to remove property %s.\n" % exp)

        if ethernet_data:
            self.patch_eth(_path, ethernet_data, errors)

        if errors and "Virtual" not in ident_name:
            raise RdmcError(
                "Ethernet configuration errors were found collectively on adapter: "
                "'%s, %s'\ntype: %s\nerrors: %s" % (ident_name, ident_id, _type, errors)
            )

    def patch_eth(self, _path, eth_data, errors=[]):
        """helper function for patching ethernet properties. Retry functionality with the ability
            to remove the offending property.
        :param _path: URI path to be patched.
        :type _path: string
        :param eth_data: JSON containing the ethernet instance (and valid, associated
                         properties) to be patched.
        :type eth_data: JSON
        :param errors: list of errors catalogued between attempts
        :type errors: list

        """

        try:
            if eth_data:
                # eth_data = json.dumps(eth_data)
                # import ast
                # eth_data = ast.literal_eval(eth_data)
                tmp = self.rdmc.app.patch_handler(_path, eth_data, silent=False, service=False)
                if tmp.status == 400:
                    raise InvalidPropertyError(tmp.dict["error"][next(iter(tmp.dict["error"]))])
            else:
                raise NoDifferencesFoundError(
                    "No differences between existing iLO ethernet "
                    "configuration and new ethernet configuration.\nPath: %s\n" % _path
                )

        except InvalidPropertyError as excp:
            errors.append("iLO Responded with the following error: %s.\n" % excp)

            def drill_to_data(data, list_o_keys):
                if len(list_o_keys) > 1:
                    k = list_o_keys.pop(0)
                else:
                    del data[k]
                if isinstance(data, dict):
                    drill_to_data(data[k], list_o_keys)

            if hasattr(excp, "message"):
                for key in excp.message[0]["MessageArgs"]:
                    try:
                        eth_data.pop(key)
                    except (AttributeError, KeyError, StopIteration):
                        try:
                            drill_to_data(
                                eth_data,
                                list_o_keys=json_traversal(eth_data, key, ret_key_path=True),
                            )
                        except:
                            errors.append("Unable to find '%s'" % key)
                        return
                self.patch_eth(_path, eth_data)

        except NoDifferencesFoundError as excp:
            errors.append("%s" % excp)

    def ethernetvalidation(self, options):
        """ethernet validation function
        :param options: command line options
        :type options: list.
        """

        self.cmdbase.login_select_validation(self, options)

        if options.ethfilename:
            if len(options.ethfilename) < 2:
                self.eth_file = options.ethfilename[0]
            else:
                raise InvalidCommandLineError("Only a single ethernet file may be specified.")
        else:
            self.eth_file = __eth_file__

    @staticmethod
    def options_argument_group(parser):
        """Define option arguments group
        :param parser: The parser to add the login option group to
        :type parser: ArgumentParser/OptionParser
        """

        parser.add_argument(
            "--encryption",
            dest="encryption",
            help="Optionally include this flag to encrypt/decrypt a file" " using the key provided.",
            default=None,
        )
        parser.add_argument(
            "-f",
            "--ethfile",
            dest="ethfilename",
            help="""Optionally specify a JSON file to store or load ethernet configuration data.""",
            action="append",
            default=None,
        )

    def definearguments(self, customparser):
        """Wrapper function for certificates command main function
        :param customparser: command line input
        :type customparser: parser.
        """
        if not customparser:
            return

        self.cmdbase.add_login_arguments_group(customparser)
        self.options_argument_group(customparser)
        subcommand_parser = customparser.add_subparsers(dest="command")
        default_parser = subcommand_parser.add_parser(
            "default",
            help="Obtain iLO management networking interface details and configure basic "
            "properties such as enablement/disablement, domain name servers, ipv4 and ipv6 "
            "networking configuration.",
            formatter_class=RawDescriptionHelpFormatter,
        )
        default_parser.add_argument(
            "--enable_nic",
            dest="enable_nic",
            help="Enable network interfaces. List each interface to be enabled by ID: "
            "Ex: ethernet --enable_nic 1,2,3. **Note**: Non-existent interfaces will be omitted from "
            "configuration.",
            type=str,
            default=None,
        )
        default_parser.add_argument(
            "--disable_nic",
            dest="disable_nic",
            help="Disable network interfaces. List each interface to be disabled by ID: "
            "Ex: ethernet --disable_nic 1,2,3. **Note**: Non-existent interfaces will be omitted from "
            "configuration.",
            type=str,
            default=None,
        )
        default_parser.add_argument(
            "--enable_vnic",
            dest="enable_vnic",
            help="""Enable virtual network interfaces of management network.
                Ex: ethernet --enable_vnic""",
            action="store_true",
            default=False,
        )
        default_parser.add_argument(
            "--disable_vnic",
            dest="disable_vnic",
            help="""Disable virtual network interfaces of management network.
                Ex: ethernet --disable_vnic""",
            action="store_true",
            default=False,
        )
        default_parser.add_argument(
            "--disable_enhanced_downloads",
            dest="disable_enhanced_downloads",
            help="""Disable enhanced download for virtual media and firmware update.
                        Ex: ethernet --disable_enhanced_downloads""",
            action="store_true",
            default=False,
        )
        default_parser.add_argument(
            "--enable_enhanced_downloads",
            dest="enable_enhanced_downloads",
            help="""Enable enhanced download for virtual media and firmware update.
                                Ex: ethernet --enable_enhanced_downloads""",
            action="store_true",
            default=False,
        )
        default_parser.add_argument(
            "--nameservers",
            dest="nameservers",
            help="Configure physical and shared management network interface domain name "
            "servers (DNS) in a list as follows: <DNS1> <DNS2> <DNS3>"
            "Ex: ethernet --nameservers 8.8.8.8,1.1.1.1,2.2.2.2 ethernet --nameservers dns_resolver1.aws.com, "
            "dns_resolver2.aws.com",
            default=None,
        )
        default_parser.add_argument(
            "--proxy",
            dest="proxy",
            type=str,
            help="Configure or clear proxy server for the network "
            "Ex:\nTo set proxy\nethernet --proxy http://proxy.abc.net:8080 or \n"
            "To clear proxy settings\n"
            "ethernet --proxy None",
            default=None,
        )
        default_parser.add_argument(
            "--network_ipv4",
            dest="network_ipv4",
            help="Configure physical and shared management network interface static IPv4 "
            "settings. Settings provided in a list as follows: "
            "<ipv4 address>, <ipv4 gateway>, <ipv4 network mask>. Ex: ethernet --network_ipv4 "
            "192.168.1.10, 192.168.1.1, 255.255.0.0",
            default=None,
        )
        default_parser.add_argument(
            "--network_ipv6",
            dest="network_ipv6",
            help="Configure physical and shared management network interface static IPv6 "
            "settings. Settings provided in a list as follows: "
            "<ipv6 address>, <ipv6 gateway>, <ipv6 network mask>. Ex: ethernet --network_ipv6 "
            "0:0:0:0:ffff:c0a8:10e, 0:0:0:0:0:ffff:c0a8:101, 64. **Note**: IPv6 network mask"
            "is restricted to '64' bits.",
            default=None,
        )
        default_parser.add_argument(
            "-j",
            "--json",
            dest="json",
            action="store_true",
            help="Optionally include this flag if you wish to change the " "displayed output to JSON format.",
            default=False,
        )
        self.cmdbase.add_login_arguments_group(default_parser)
        save_help = "Save a Network Configuration."
        save_parser = subcommand_parser.add_parser(
            __subparsers__[0],
            help=save_help,
            description="{0}\n\texample: ethernet save\n\n\tSave iLO ethernet network management interface "
            "settings to a non-default file name.\n\tEx: ethernet save -f networking.json\n\n\tSave "
            "an encrypted iLO networking configuration file\n\texample: ethernet save --encryption "
            "<ENCRYPTION_KEY>".format(save_help),
            formatter_class=RawDescriptionHelpFormatter,
        )
        self.cmdbase.add_login_arguments_group(save_parser)
        self.options_argument_group(save_parser)
        load_help = "Load a Network Configuration."
        load_parser = subcommand_parser.add_parser(
            __subparsers__[1],
            help=load_help,
            description="{0}\n\texample: ethernet load\n\n\tLoad iLO ethernet networking management interface "
            "settings from a non-default file name.\n\tEx: ethernet load -f "
            "networking.json\n\n\tLoad an encrypted iLO networking configuration file\n\texample: "
            "ethernet load --encryption <ENCRYPTION KEY>".format(load_help),
            formatter_class=RawDescriptionHelpFormatter,
        )
        load_parser.add_argument(
            "--force_network_config",
            dest="force_network_config",
            help="Use this flag to force set network configuration."
            "Network settings will be skipped if the flag is not included.",
            action="store_true",
            default=None,
        )
        self.cmdbase.add_login_arguments_group(load_parser)
        self.options_argument_group(load_parser)
