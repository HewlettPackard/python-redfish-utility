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
""" Save Command for RDMC """

import json
from collections import OrderedDict

import redfish.ris

try:
    from rdmc_helper import (
        Encryption,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        InvalidFileFormattingError,
        ReturnCodes,
        iLORisCorruptionError,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        Encryption,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        InvalidFileFormattingError,
        ReturnCodes,
        iLORisCorruptionError,
    )

# default file name
__filename__ = "ilorest.json"


class SaveCommand:
    """Constructor"""

    def __init__(self):
        self.ident = {
            "name": "save",
            "usage": None,
            "description": "Run to save a selected type to a file"
            "\n\texample: save --selector HpBios.\n\n\tChange the default "
            "output filename\n\texample: save --selector HpBios. -f "
            "output.json\n\n\tTo save multiple types in one file\n\texample: "
            "save --multisave Bios.,ComputerSystem.",
            "summary": "Saves the selected type's settings to a file.",
            "aliases": [],
            "auxcommands": ["SelectCommand"],
        }
        self.filename = __filename__
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """Main save worker function

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

        if options.multisave:
            options.selector = ""
        if (
            hasattr(options, "selector")
            and "hpbaseconfigs" not in options.selector.lower()
            and "hpebaseconfigs" not in options.selector.lower()
            and "bios" not in options.selector.lower()
        ):
            self.savevalidation(options)
        else:
            # filename validations and checks
            self.cmdbase.login_validation(self, options)
            self.filename = None
            if options.filename and len(options.filename) > 1:
                raise InvalidCommandLineError("Save command doesn't support multiple filenames.")
            elif options.filename:
                self.filename = options.filename[0]
            elif self.rdmc.config:
                if self.rdmc.config.defaultsavefilename:
                    self.filename = self.rdmc.config.defaultsavefilename

            if not self.filename:
                self.filename = __filename__

        # if args:
        #  raise InvalidCommandLineError("Save command takes no arguments.")

        self.rdmc.ui.printer("Saving configuration...\n")
        if options.filter:
            try:
                if (str(options.filter)[0] == str(options.filter)[-1]) and str(options.filter).startswith(("'", '"')):
                    options.filter = options.filter[1:-1]

                (sel, val) = options.filter.split("=")
                sel = sel.strip()
                val = val.strip()
            except:
                raise InvalidCommandLineError("Invalid filter" " parameter format [filter_attribute]=[filter_value]")

            instances = self.rdmc.app.select(
                selector=self.rdmc.app.selector,
                fltrvals=(sel, val),
                path_refresh=True,
            )
            contents = self.saveworkerfunction(options, instances=instances)
        else:
            contents = self.saveworkerfunction(options)

        if options.multisave:
            for select in options.multisave:
                try:
                    self.auxcommands["select"].run(select)
                except:
                    pass
                contents += self.saveworkerfunction(options)

        if not contents:
            raise redfish.ris.NothingSelectedError
        else:
            # TODO: Maybe add this to the command. Not sure we use it elsewhere in the lib
            contents = self.add_save_file_header(contents)

        if options.encryption:
            with open(self.filename, "wb") as outfile:
                outfile.write(
                    Encryption().encrypt_file(
                        json.dumps(contents, indent=2, cls=redfish.ris.JSONEncoder),
                        options.encryption,
                    )
                )
        else:
            with open(self.filename, "w") as outfile:
                outfile.write(json.dumps(contents, indent=2, cls=redfish.ris.JSONEncoder, sort_keys=True))
        self.rdmc.ui.printer("Configuration saved to: %s\n" % self.filename)

        self.cmdbase.logout_routine(self, options)

        # Return code
        return ReturnCodes.SUCCESS

    def saveworkerfunction(self, options, instances=None):
        """Returns the currently selected type for saving

        :param instances: list of instances from select to save
        :type instances: list.
        """
        try:
            if (
                "bios" in options.selector.lower()
                or "hpbaseconfigs" in options.selector.lower()
                or "hpebaseconfigs" in options.selector.lower()
            ) and (options.multisave is None or options.multisave == ""):
                raise KeyError
            content = self.rdmc.app.getprops(insts=instances)
            try:
                contents = [{val[self.rdmc.app.typepath.defs.hrefstring]: val} for val in content]
            except KeyError:
                try:
                    contents = [{val["links"]["self"][self.rdmc.app.typepath.defs.hrefstring]: val} for val in content]
                except KeyError:
                    raise iLORisCorruptionError(
                        "iLO Database seems to be corrupted. Please check. Reboot the server to " "restore\n"
                    )
        except Exception:
            config_path = None
            contents = list()
            if options.selector.lower() == "bios." or "bios.v" in options.selector.lower():
                config_path = ["/redfish/v1/systems/1/bios/settings/"]
            elif options.selector.lower() == "bios":
                config_path = ["/redfish/v1/systems/1/bios/settings/", "/redfish/v1/systems/1/bios/mappings/"]
            elif "hpbaseconfigs" in options.selector.lower() or "hpebaseconfigs" in options.selector.lower():
                config_path = [
                    "/redfish/v1/systems/1/bios/oem/hpe/baseconfigs/",
                    "/redfish/v1/systems/1/bios/oem/hpe/nvmeof/baseconfigs/",
                    "/redfish/v1/systems/1/bios/oem/hpe/iscsi/baseconfigs/",
                    "/redfish/v1/systems/1/bios/oem/hpe/tlsconfig/baseconfigs/",
                    "/redfish/v1/systems/1/bios/oem/hpe/serverconfiglock/baseconfigs/",
                    "/redfish/v1/systems/1/bios/oem/hpe/kmsconfig/baseconfigs/",
                    "/redfish/v1/systems/1/bios/oem/hpe/boot/baseconfigs/",
                    "/redfish/v1/systems/1/bios/baseconfigs/",
                    "/redfish/v1/systems/1/bios/nvmeof/baseconfigs/",
                    "/redfish/v1/systems/1/bios/iscsi/baseconfigs/",
                    "/redfish/v1/systems/1/bios/tlsconfig/baseconfigs/",
                    "/redfish/v1/systems/1/bios/serverconfiglock/baseconfigs/",
                    "/redfish/v1/systems/1/bios/kmsconfig/baseconfigs/",
                    "/redfish/v1/systems/1/bios/boot/baseconfigs/",
                ]
            result = None
            for b in config_path:
                try:
                    result = self.rdmc.app.get_handler(b, silent=True, service=True)
                except:
                    pass
                if result is not None:
                    if result.status == 200:
                        d = {b: result.dict}
                        contents.append(d)

        type_string = self.rdmc.app.typepath.defs.typestring

        templist = list()
        srnum_list = list()

        for content in contents:
            typeselector = None
            pathselector = None

            for path, values in content.items():
                # if "Managers/1/EthernetInterfaces/1" not in path:
                for dictentry in list(values.keys()):
                    if dictentry == type_string:
                        typeselector = values[dictentry]
                        pathselector = path
                        del values[dictentry]
                    if dictentry in [
                        "IPv4Addresses",
                        "IPv6Addresses",
                        "IPv6AddressPolicyTable",
                        "MACAddress",
                        "StaticNameServers",
                        # "AutoNeg",
                        # "FullDuplex",
                        "SpeedMbps",
                    ]:
                        del values[dictentry]
                    if dictentry in [
                        "IPv6StaticAddresses",
                        "IPv6StaticDefaultGateways",
                        "IPv4StaticAddresses",
                    ]:
                        if values[dictentry]:
                            del values[dictentry]
                    if dictentry in ["IPv4", "IPv6", "DHCPv6", "DHCPv4"]:
                        if "DNSServers" in values[dictentry]:
                            del values[dictentry]["DNSServers"]
                            del values["Oem"]["Hpe"][dictentry]["DNSServers"]
                        if "UseDNSServers" in values[dictentry]:
                            del values[dictentry]["UseDNSServers"]
                            del values["Oem"]["Hpe"][dictentry]["UseDNSServers"]

                if values:
                    skip = False
                    if "SerialNumber" in values and values["SerialNumber"] is not None and values["SerialNumber"] != "":
                        if values["SerialNumber"] in srnum_list:
                            skip = True
                        else:
                            srnum_list.append(values["SerialNumber"])
                    tempcontents = dict()

                    if not skip:
                        if typeselector and pathselector:
                            tempcontents[typeselector] = {pathselector: values}
                        else:
                            raise InvalidFileFormattingError("Missing path or selector in input file.")

                templist.append(tempcontents)

        return templist

    def nested_sort(self, data):
        """Helper function to sort all dictionary key:value pairs

        :param data: dictionary to sort
        :type data: dict.
        """

        for key, value in data.items():
            if isinstance(value, dict):
                data[key] = self.nested_sort(value)

        data = OrderedDict(sorted(list(data.items()), key=lambda x: x[0]))

        return data

    def savevalidation(self, options):
        """Save method validation function

        :param options: command line options
        :type options: list.
        """

        if options.multisave:
            options.multisave = options.multisave.replace('"', "").replace("'", "")
            options.multisave = options.multisave.replace(" ", "").split(",")
            if not len(options.multisave) >= 1:
                raise InvalidCommandLineError("Invalid number of types in multisave option.")
            options.selector = options.multisave[0]
            options.multisave = options.multisave[1:]

        self.cmdbase.login_select_validation(self, options)

        # filename validations and checks
        self.filename = None

        if options.filename and len(options.filename) > 1:
            raise InvalidCommandLineError("Save command doesn't support multiple filenames.")
        elif options.filename:
            self.filename = options.filename[0]
        elif self.rdmc.config:
            if self.rdmc.config.defaultsavefilename:
                self.filename = self.rdmc.config.defaultsavefilename

        if not self.filename:
            self.filename = __filename__

    def add_save_file_header(self, contents):
        """Helper function to retrieve the comments for save file

        :param contents: current save contents
        :type contents: list.
        """
        templist = list()

        headers = self.rdmc.app.create_save_header()
        templist.append(headers)

        for content in contents:
            templist.append(content)

        return templist

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
            help="Use this flag if you wish to use a different filename than the default one. "
            "The default filename is %s." % __filename__,
            action="append",
            default=None,
        )

        customparser.add_argument(
            "--selector",
            dest="selector",
            help="Optionally include this flag to select a type to run the current command on. "
            "Use this flag when you wish to select a type without entering another command, "
            "or if you wish to work with a type that is different from the one currently "
            "selected.",
            default=None,
            # required=True,
        )
        customparser.add_argument(
            "--multisave",
            dest="multisave",
            help="Optionally include this flag to save multiple types to a single file. "
            "Overrides the currently selected type.\n\t Usage: --multisave type1.,type2.,type3.",
            default="",
        )
        customparser.add_argument(
            "--filter",
            dest="filter",
            help="Optionally set a filter value for a filter attribute. This uses the provided "
            "filter for the currently selected type. Note: Use this flag to narrow down your "
            "results. For example, selecting a common type might return multiple objects that "
            "are all of that type. If you want to modify the properties of only one of those "
            "objects, use the filter flag to narrow down results based on properties."
            "\n\t Usage: --filter [ATTRIBUTE]=[VALUE]",
            default=None,
        )
        customparser.add_argument(
            "-j",
            "--json",
            dest="json",
            action="store_true",
            help="Optionally include this flag if you wish to change the displayed output to "
            "JSON format. Preserving the JSON data structure makes the information easier to "
            "parse.",
            default=False,
        )
        customparser.add_argument(
            "--encryption",
            dest="encryption",
            help="Optionally include this flag to encrypt/decrypt a file using the key provided.",
            default=None,
        )
