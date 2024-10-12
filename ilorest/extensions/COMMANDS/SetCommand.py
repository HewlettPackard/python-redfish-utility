###
# Copyright 2016-2023 Hewlett Packard Enterprise, Inc. All rights reserved.
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
""" Set Command for RDMC """
import json
import os
import sys

import redfish.ris

try:
    from rdmc_helper import (
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        InvalidOrNothingChangedSettingsError,
        ReturnCodes,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        ReturnCodes,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        InvalidOrNothingChangedSettingsError,
    )

from redfish.ris.rmc_helper import NothingSelectedError


class SetCommand:
    """Constructor"""

    def __init__(self):
        self.ident = {
            "name": "set",
            "usage": None,
            "description": "Setting a "
            "single level property example:\n\tset property=value\n\n\t"
            "Setting multiple single level properties example:\n\tset "
            "property=value property=value property=value\n\n\t"
            "Setting a multi level property example:\n\tset property/"
            "subproperty=value",
            "summary": "Changes the value of a property within the" " currently selected type.",
            "aliases": [],
            "auxcommands": [
                "CommitCommand",
                "RebootCommand",
                "RawPatchCommand",
                "SelectCommand",
                "LogoutCommand",
            ],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def setfunction(self, line, skipprint=False):
        """Main set worker function

        :param line: command line input
        :type line: string.
        :param skipprint: boolean to determine output
        :type skipprint: boolean.
        """

        try:
            (options, args) = self.rdmc.rdmc_parse_arglist(self, line)
        except (InvalidCommandLineErrorOPTS, SystemExit):
            if ("-h" in line) or ("--help" in line):
                return ReturnCodes.SUCCESS
            else:
                raise InvalidCommandLineErrorOPTS("")

        if not self.rdmc.interactive and not self.rdmc.app.cache:
            raise InvalidCommandLineError("The 'set' command is not useful in " "non-interactive and non-cache modes.")

        self.setvalidation(options)
        _ = args[0].find("HighSecurity")

        fsel = None
        fval = None
        if args:
            if "ethernetinterface" in self.rdmc.app.selector.lower() and "ipv4addresses" in args[0].lower():
                raise InvalidCommandLineError(
                    "For security reasons this request is discarded. "
                    "Use `rawpatch` or the `load --force_network_config` command "
                    "to modify the IP configuration of the ilO.\n"
                )
            if options.filter:
                try:
                    (fsel, fval) = str(options.filter).strip("'\" ").split("=")
                    (fsel, fval) = (fsel.strip(), fval.strip())
                except:
                    raise InvalidCommandLineError(
                        "Invalid filter" " parameter format [filter_attribute]=[filter_value]"
                    )

            if any([s.lower().startswith("adminpassword=") for s in args]) and not any(
                [s.lower().startswith("oldadminpassword=") for s in args]
            ):
                raise InvalidCommandLineError(
                    "'OldAdminPassword' must also "
                    "be set with the current password \nwhen "
                    "changing 'AdminPassword' for security reasons."
                )
            count = 0
            for arg in args:
                if arg:
                    if len(arg) > 2:
                        if ('"' in arg[0] and '"' in arg[-1]) or ("'" in arg[0] and "'" in arg[-1]):
                            args[count] = arg[1:-1]
                    elif len(arg) == 2:
                        if (arg[0] == '"' and arg[1] == '"') or (arg[0] == "'" and arg[1] == "'"):
                            args[count] = None
                count += 1
                if not self.rdmc.app.selector:
                    raise NothingSelectedError
                if "." not in self.rdmc.app.selector:
                    self.rdmc.app.selector = self.rdmc.app.selector + "."
                if self.rdmc.app.selector:
                    if self.rdmc.app.selector.lower().startswith("bios."):
                        if "attributes" not in arg.lower():
                            arg = "Attributes/" + arg

                try:
                    (sel, val) = arg.split("=")
                    sel = sel.strip().lower()
                    val = val.strip("\"'")

                    if val.lower() == "true" or val.lower() == "false":
                        val = val.lower() in ("yes", "true", "t", "1")
                except:
                    raise InvalidCommandLineError("Invalid set parameter format. [Key]=[Value]")

                newargs = list()

                if "/" in sel and "/" not in str(val):
                    newargs = sel.split("/")
                elif "/" in sel:
                    items = arg.split("=", 1)
                    newargs = items[0].split("/")
                if not isinstance(val, bool):
                    if val:
                        if val[0] == "[" and val[-1] == "]":
                            val = val[1:-1].split(",")
                payload = {newargs[-1]: val} if newargs else {sel: val}
                if newargs:
                    for key in newargs[:-1][::-1]:
                        payload = {key: payload}
                try:
                    contents = self.rdmc.app.loadset(
                        seldict=payload,
                        latestschema=options.latestschema,
                        fltrvals=(fsel, fval),
                        uniqueoverride=options.uniqueoverride,
                    )
                    if not contents:
                        if not sel.lower() == "oldadminpassword":
                            raise InvalidOrNothingChangedSettingsError(
                                "Nothing changed "
                                "for attribute '%s'.\nPlease check if the attribute is Oem/Hpe Attribute or Read-only "
                                "or System Unique property or the value trying to set is same or invalid" % sel
                            )
                    elif contents == "No entries found":
                        raise InvalidOrNothingChangedSettingsError(
                            "No " "entries found in the current " "selection for the setting '%s'." % sel
                        )
                    elif contents == "reverting":
                        self.rdmc.ui.error("Removing previous patch and returning to the " "original value.\n")
                    else:
                        for content in contents:
                            self.rdmc.ui.printer("Added the following patch:\n")
                            self.rdmc.ui.print_out_json(content)

                except redfish.ris.ValidationError as excp:
                    errs = excp.get_errors()

                    for err in errs:
                        if err.sel and err.sel.lower() == "adminpassword":
                            types = self.rdmc.app.monolith.types

                            for item in types:
                                for instance in types[item]["Instances"]:
                                    if "hpbios." in instance.maj_type.lower():
                                        _ = [
                                            instance.patches.remove(patch)
                                            for patch in instance.patches
                                            if patch.patch[0]["path"] == "/OldAdminPassword"
                                        ]

                        if isinstance(err, redfish.ris.RegistryValidationError):
                            self.rdmc.ui.printer(err.message)

                    raise redfish.ris.ValidationError(excp)

            if options.commit:
                self.auxcommands["commit"].commitfunction(options)

            if options.reboot and not options.commit:
                self.auxcommands["reboot"].run(options.reboot)

            if options.logout:
                self.auxcommands["logout"].run("")

        else:
            raise InvalidCommandLineError("Missing parameters for 'set' command.\n")

    def patchfunction(self, line):
        """Main set worker function
        :param line: command line input
        :type line: string.
        :param skipprint: boolean to determine output
        :type skipprint: boolean.
        """
        try:
            (options, args) = self.rdmc.rdmc_parse_arglist(self, line)
        except (InvalidCommandLineErrorOPTS, SystemExit):
            if ("-h" in line) or ("--help" in line):
                return ReturnCodes.SUCCESS
            else:
                raise InvalidCommandLineErrorOPTS("")

        if not self.rdmc.interactive and not self.rdmc.app.cache:
            raise InvalidCommandLineError("The 'set' command is not useful in " "non-interactive and non-cache modes.")

        _ = self.rdmc.app.selector
        self.setvalidation(options)
        if args:
            count = 0
            for arg in args:
                if arg:
                    if len(arg) > 2:
                        if ('"' in arg[0] and '"' in arg[-1]) or ("'" in arg[0] and "'" in arg[-1]):
                            args[count] = arg[1:-1]
                    elif len(arg) == 2:
                        if (arg[0] == '"' and arg[1] == '"') or (arg[0] == "'" and arg[1] == "'"):
                            args[count] = None
                count += 1
                if not self.rdmc.app.selector:
                    raise NothingSelectedError
                if "." not in self.rdmc.app.selector:
                    self.rdmc.app.selector = self.rdmc.app.selector + "."
                if self.rdmc.app.selector:
                    if self.rdmc.app.selector.lower().startswith("bios."):
                        if "attributes" not in arg.lower():
                            arg = "Attributes/" + arg

                try:
                    (sel, val) = arg.split("=")
                    sel = sel.strip()
                    val = val.strip("\"'")

                    if val.lower() == "true" or val.lower() == "false":
                        val = val.lower() in ("yes", "true", "t", "1")
                except:
                    raise InvalidCommandLineError("Invalid set parameter format. [Key]=[Value]")

                newargs = list()

                if "/" in sel and "/" not in str(val):
                    newargs = sel.split("/")
                elif "/" in sel:
                    items = arg.split("=", 1)
                    newargs = items[0].split("/")

                if not isinstance(val, bool):
                    if val:
                        if val[0] == "[" and val[-1] == "]":
                            val = val[1:-1].split(",")
                    if val.isdigit():
                        val = int(val)
                patch_data = dict()
                payload = {newargs[-1]: val} if newargs else {sel: val}
                if newargs:
                    for key in newargs[:-1][::-1]:
                        if key == "PowerControl":
                            payload = {key: [payload]}
                        else:
                            payload = {key: payload}
                        patch_data.update(payload)
                        if "Oem" in key:
                            if (
                                "managernetworkprotocol." in self.rdmc.app.selector
                                or "thermal." in self.rdmc.app.selector
                            ):
                                import platform
                                import tempfile

                                tempdir = "/tmp" if platform.system() == "Darwin" else tempfile.gettempdir()
                                temp_file = os.path.join(tempdir, "temp_patch.json")
                                out_file = open(temp_file, "w")
                                if "managernetworkprotocol." in self.rdmc.app.selector:
                                    patchpath = self.rdmc.app.typepath.defs.managerpath + "NetworkProtocol/"
                                elif "thermal." in self.rdmc.app.selector:
                                    patchpath = "/redfish/v1/Chassis/1/Thermal/"
                                patch_payload = {patchpath: payload}
                                json.dump(patch_payload, out_file, indent=6)
                                out_file.close()
                                sys.stdout.write("payload %s \n" % patch_payload)
                                self.auxcommands["rawpatch"].run(temp_file + " --service")
                                self.auxcommands["select"].run(self.rdmc.app.selector + " --refresh")
                                os.remove(temp_file)
                    if "PowerControl" in payload.keys():
                        import platform
                        import tempfile

                        tempdir = "/tmp" if platform.system() == "Darwin" else tempfile.gettempdir()
                        temp_file = os.path.join(tempdir, "temp_patch.json")
                        out_file = open(temp_file, "w")
                        patch_path = "/redfish/v1/Chassis/1/Power"
                        patch_payload = {patch_path: payload}
                        json.dump(patch_payload, out_file, indent=6)
                        out_file.close()
                        self.auxcommands["rawpatch"].run(temp_file + " --service")
                        os.remove(temp_file)

    def run(self, line, skipprint=False, help_disp=False):
        """Main set function

        :param line: command line input
        :type line: string.
        :param skipprint: boolean to determine output
        :type skipprint: boolean.
        """
        if help_disp:
            self.parser.print_help()
            return ReturnCodes.SUCCESS
        if (
            ("Oem/Hpe/EnhancedDownloadPerformanceEnabled" in line[0])
            or ("Oem/Hpe/ThermalConfiguration" in line[0])
            or ("Oem/Hpe/FanPercentMinimum" in line[0])
            or ("PowerControl" in line[0])
            or ("drive" in self.rdmc.app.selector.lower())
        ):
            self.patchfunction(line)
        else:
            self.setfunction(line, skipprint=skipprint)
        # Return code
        return ReturnCodes.SUCCESS

    def setvalidation(self, options):
        """Set data validation function"""

        if self.rdmc.opts.latestschema:
            options.latestschema = True
        if self.rdmc.config.commit.lower() == "true":
            options.commit = True
        try:
            self.cmdbase.login_select_validation(self, options)
        except redfish.ris.NothingSelectedError:
            raise redfish.ris.NothingSelectedSetError("")

    def definearguments(self, customparser):
        """Wrapper function for new command main function

        :param customparser: command line input
        :type customparser: parser.
        """
        if not customparser:
            return

        self.cmdbase.add_login_arguments_group(customparser)

        customparser.add_argument(
            "--selector",
            dest="selector",
            help="Optionally include this flag to select a type to run"
            " the current command on. Use this flag when you wish to"
            " select a type without entering another command, or if you"
            " wish to work with a type that is different from the one"
            " you currently have selected.",
            default=None,
        )

        customparser.add_argument(
            "--filter",
            dest="filter",
            help="Optionally set a filter value for a filter attribute."
            " This uses the provided filter for the currently selected"
            " type. Note: Use this flag to narrow down your results. For"
            " example, selecting a common type might return multiple"
            " objects that are all of that type. If you want to modify"
            " the properties of only one of those objects, use the filter"
            " flag to narrow down results based on properties."
            "\t\t\t\t\t Usage: --filter [ATTRIBUTE]=[VALUE]",
            default=None,
        )
        customparser.add_argument(
            "--commit",
            dest="commit",
            action="store_true",
            help="Use this flag when you are ready to commit all pending"
            " changes. Note that some changes made in this way will be updated"
            " instantly, while others will be reflected the next time the"
            " server is started.",
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
        customparser.add_argument(
            "--latestschema",
            dest="latestschema",
            action="store_true",
            help="Optionally use the latest schema instead of the one "
            "requested by the file. Note: May cause errors in some data "
            "retrieval due to difference in schema versions.",
            default=None,
        )
        customparser.add_argument(
            "--uniqueoverride",
            dest="uniqueoverride",
            action="store_true",
            help="Override the measures stopping the tool from writing " "over items that are system unique.",
            default=None,
        )
