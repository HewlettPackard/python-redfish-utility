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
""" BootOrder Command for rdmc """

import ast
import copy
import fnmatch
from functools import reduce

import six

try:
    from rdmc_helper import (
        UI,
        BootOrderMissingEntriesError,
        Encryption,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        InvalidOrNothingChangedSettingsError,
        ReturnCodes,
    )
except:
    from ilorest.rdmc_helper import (
        UI,
        BootOrderMissingEntriesError,
        Encryption,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        InvalidOrNothingChangedSettingsError,
        ReturnCodes,
    )


class BootOrderCommand:
    """Changes the boot order for the server that is currently logged in"""

    def __init__(self):
        self.ident = {
            "name": "bootorder",
            "usage": None,
            "description": "Run without arguments for current boot order and one time boot options."
            "\n\texample: bootorder\n\n\tTo set the persistent boot order pick items "
            'from\n\tthe "Current Persistent Boot Order" section.\n\t'
            "example: bootorder [5,4,3,2,1] --commit\n\n\tSetting partial"
            " boot order is also supported.\n\tMissing entries are "
            "concatenated at the end.\n\texample: bootorder [5] --commit\n\n\t"
            "You can also set the boot order using partial string matching.\n\t"
            "example: bootorder NIC.*v4 HD* Generic.USB.1.1 --commit\n\n\tThis will set "
            "All v4 NICs first, followed by all hard drives,\n\tfollowed by Generic.USB.1.1. "
            "Everything not listed will be\n\tadded to the end of the boot order."
            '\n\n\tTo set one time boot entry pick items from the\n\t"'
            'Continuous and one time boot uefi options" section.\n\t'
            "example: bootorder --onetimeboot=Hdd\n\n\tTo set continuous"
            ' boot entry pick items from the\n\t"Continuous and one time '
            'boot uefi options" section.\n\texample: bootorder --'
            "continuousboot=Utilities --commit\n\n\tDisable either "
            "continuous or one time boot options.\n\texample: bootorder "
            "--disablebootflag --commit\n\n\t"
            "Changing Secure Boot Keys:\n\tTo manage secure boot keys use"
            " the --securebootkeys flag.\n\tTo delete all keys.\n\n\texample:"
            " bootorder --securebootkeys=deletepk\n\tFor all possibilities"
            " see the --securebootkeys flag \n\tin the options list.\n\n\t"
            "NOTE: pick ONETIMEBOOT and "
            'CONTINUOUS items from "Continuous\n\tand one time boot '
            'options" section. Items in this list represent\n\ta '
            '"clustered" view of the "Continuous and one time boot uefi'
            '\n\toptions" section. Example: choosing Pxe will try to Pxe'
            ' boot\n\tcapable devices in the order found in the "'
            'Continuous and one\n\ttime boot options".\n\n\t',
            "summary": "Displays and sets the current boot order.",
            "aliases": [],
            "auxcommands": [
                "GetCommand",
                "SelectCommand",
                "SetCommand",
                "RebootCommand",
            ],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """Main boot order worker function"""
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

        self.bootordervalidation(options)

        if options.secureboot:
            self.secureboothelper(options.secureboot)

            if options.reboot:
                self.auxcommands["reboot"].run(options.reboot)

            return ReturnCodes.SUCCESS

        self.rdmc.app.select(selector="HpeServerBootSettings.", path_refresh=True)

        props = self.rdmc.app.getprops(skipnonsetting=False)

        for prop in props:
            bootname = prop.get("Name")

            self.rdmc.ui.printer("bootname is : {0}\n\n".format(bootname))

            if self.rdmc.app.typepath.defs.isgen10:
                if "current" in bootname.lower() or "pending" in bootname.lower():
                    try:
                        bootpath = prop.get("@odata.id")
                    except:
                        bootpath = prop.get("links")
            else:
                bootpath = "/rest/v1/systems/1/bios/boot"

        self.rdmc.ui.printer("bootpath is : {0}\n\n".format(bootpath))

        bootsources = self.rdmc.app.get_handler(bootpath, service=True, silent=True).dict["BootSources"]

        bootoverride = None
        self.auxcommands["select"].selectfunction("HpeBios.")
        try:
            bootmode = self.auxcommands["get"].getworkerfunction("BootMode", options, results=True, uselist=True)
        except:
            bootmode = dict()
            bootmode["BootMode"] = "Uefi"

        self.auxcommands["select"].selectfunction("ComputerSystem.")
        onetimebootsettings = self.auxcommands["get"].getworkerfunction(
            ["Boot/" + self.rdmc.app.typepath.defs.bootoverridetargettype],
            options,
            results=True,
            uselist=True,
        )

        bootstatus = self.auxcommands["get"].getworkerfunction(
            ["Boot/BootSourceOverrideEnabled"],
            options,
            results=True,
            uselist=True,
        )

        targetstatus = self.auxcommands["get"].getworkerfunction(
            ["Boot/BootSourceOverrideTarget"],
            options,
            results=True,
            uselist=True,
        )

        uefitargetstatus = self.auxcommands["get"].getworkerfunction(
            ["Boot/UefiTargetBootSourceOverride"],
            options,
            results=True,
            uselist=True,
        )

        currentsettings = self.rdmc.app.get_handler(self.rdmc.app.typepath.defs.systempath, service=True, silent=True)

        if bootmode and bootmode[0].get("BootMode", None) == "Uefi":
            if self.rdmc.app.typepath.defs.isgen9:
                uefionetimebootsettings = self.auxcommands["get"].getworkerfunction(
                    ["Boot/UefiTargetBootSourceOverrideSupported"],
                    options,
                    results=True,
                    uselist=True,
                )

            else:
                # Gen 10
                bootsettings = self.auxcommands["get"].getworkerfunction(
                    ["Boot"],
                    options,
                    results=True,
                    uselist=True,
                )[0]["Boot"]
                finaluefi = []
                if "UefiTargetBootSourceOverride@Redfish.AllowableValues" in bootsettings:
                    uefionetimebootsettings = bootsettings["UefiTargetBootSourceOverride@Redfish.AllowableValues"]

                    for setting in uefionetimebootsettings:
                        for source in bootsources:
                            if "UEFIDevicePath" in source and source["UEFIDevicePath"].endswith(setting):
                                finaluefi.append(source["StructuredBootString"])
                                continue

                uefionetimebootsettings = {"Boot": {"UefiTargetBootSourceOverrideSupported": finaluefi}}
        else:
            uefionetimebootsettings = None

        if options.onetimeboot is None and options.continuousboot is None and not options.disablebootflag:
            self.auxcommands["select"].selectfunction("HpeServerBootSettings.")
            bootsettings = self.auxcommands["get"].getworkerfunction(
                "PersistentBootConfigOrder", options, results=True, uselist=True
            )

            if not args:
                if not options.json:
                    self.print_out_boot_order(
                        bootsettings,
                        onetimebootsettings,
                        uefionetimebootsettings,
                        bootmode,
                        bootsources,
                        bootstatus,
                        targetstatus,
                    )
                elif options.json:
                    UI().print_out_json(bootsettings)
            elif len(args) == 1 and args[0][0] == "[":
                bootlist = args[0][1:-1].split(",")
                currentlist = bootsettings[0]["PersistentBootConfigOrder"]

                if not isinstance(currentlist, list):
                    templist = ast.literal_eval(currentlist[1:-1])
                    currentlist = [n.strip() for n in templist]

                removallist = copy.deepcopy(currentlist)

                if len(bootlist) > len(currentlist):
                    raise InvalidCommandLineError("Number of entries is greater than the current boot order length.")
                else:
                    newlist = "["

                    for value, _ in enumerate(bootlist):
                        try:
                            newlist += currentlist[int(bootlist[value]) - 1]
                        except:
                            raise InvalidCommandLineError(
                                "Invalid entry "
                                "number passed to bootorder. Please \n"
                                "       run bootorder without arguments"
                                " for possible boot \n       order numbers. "
                            )

                        removallist.remove(currentlist[int(bootlist[value]) - 1])

                        if removallist:
                            newlist += ","

                    if not removallist:
                        newlist += "]"
                    else:
                        for value, _ in enumerate(removallist):
                            newlist += removallist[value]

                            if not value == len(removallist) - 1:
                                newlist += ","

                        newlist += "]"

                    if options.biospassword:
                        newlist += " --biospassword " + options.biospassword

                    if options.reboot:
                        newlist += " --commit --reboot " + options.reboot
                    elif options.commit:
                        newlist += " --commit"

                    self.auxcommands["set"].run("PersistentBootConfigOrder=" + newlist)
            else:
                currlist = bootsettings[0]["PersistentBootConfigOrder"]
                if not isinstance(currlist, list):
                    templist = ast.literal_eval(currlist[1:-1])
                    currlist = [n.strip() for n in templist]
                remlist = copy.deepcopy(currlist)
                if len(args) > len(currlist):
                    raise InvalidCommandLineError("Number of entries is " "greater than the current boot order length.")
                newlist = []
                for arg in args:
                    argmatch = [val for val in remlist if fnmatch.fnmatch(val.lower(), arg.lower())]
                    if not argmatch and not options.ime:
                        raise InvalidCommandLineError(
                            "Invalid entry passed: "
                            "{0}. Please run bootorder to check for possible "
                            "values and reevaluate.\n".format(arg)
                        )
                    if argmatch:
                        newlist.extend(argmatch)
                        _ = [remlist.remove(val) for val in newlist if val in remlist]
                newlist.extend(remlist)
                strlist = "["
                concatlist = reduce((lambda x, y: x + "," + y), newlist)
                strlist = strlist + concatlist + "]"

                if options.biospassword:
                    strlist += " --biospassword " + options.biospassword
                if options.reboot:
                    strlist += " --commit --reboot " + options.reboot
                elif options.commit:
                    strlist += " --commit"
                self.auxcommands["set"].run("PersistentBootConfigOrder=" + strlist)
        else:
            if options.onetimeboot is not None:
                entry = options.onetimeboot

                if not bootstatus[0]["Boot"]["BootSourceOverrideEnabled"] == "Once":
                    bootoverride = " Boot/BootSourceOverrideEnabled=Once"
            elif options.continuousboot is not None:
                entry = options.continuousboot

                if not bootstatus[0]["Boot"]["BootSourceOverrideEnabled"] == "Continuous":
                    bootoverride = " Boot/BootSourceOverrideEnabled=Continuous"
            else:
                entry = "JacksBootOption"
                if not bootstatus[0]["Boot"]["BootSourceOverrideEnabled"] == "Disabled":
                    if currentsettings.dict["Boot"]["BootSourceOverrideEnabled"] == "Disabled":
                        bootoverride = "Boot/BootSourceOverrideTarget=None" " Boot/BootSourceOverrideEnabled=Disabled"
                    else:
                        bootoverride = "Boot/BootSourceOverrideTarget=None"

            newlist = ""

            if entry.lower() in (
                item.lower() for item in onetimebootsettings[0]["Boot"][self.rdmc.app.typepath.defs.bootoverridetargettype]
            ):
                if entry and isinstance(entry, six.string_types):
                    entry = entry.upper()

                entry = self.searchcasestring(
                    entry,
                    onetimebootsettings[0]["Boot"][self.rdmc.app.typepath.defs.bootoverridetargettype],
                )

                if not entry == targetstatus[0]["Boot"]["BootSourceOverrideTarget"]:
                    newlist += " Boot/BootSourceOverrideTarget=" + entry

                if bootoverride:
                    newlist += bootoverride

                if options.biospassword and newlist:
                    newlist += " --biospassword " + options.biospassword

                if options.reboot and newlist:
                    newlist += " --commit --reboot " + options.reboot
                elif options.commit and newlist:
                    newlist += " --commit"

                if newlist:
                    self.auxcommands["set"].run(newlist)
                else:
                    raise InvalidOrNothingChangedSettingsError("Entry is the current boot setting.")
            elif (
                uefionetimebootsettings
                and uefionetimebootsettings["Boot"]["UefiTargetBootSourceOverrideSupported"]
                and entry in (item for item in uefionetimebootsettings["Boot"]["UefiTargetBootSourceOverrideSupported"])
            ):
                if entry and isinstance(entry, six.string_types):
                    entry = entry.upper()

                entry = self.searchcasestring(
                    entry,
                    uefionetimebootsettings["Boot"]["UefiTargetBootSourceOverrideSupported"],
                )
                try:
                    # gen10
                    allowable_vals = next(
                        iter(
                            self.auxcommands["get"].getworkerfunction(
                                ["Boot/UefiTargetBootSourceOverride@Redfish.AllowableValues"],
                                options,
                                results=True,
                                uselist=True,
                            )
                        ),
                        {},
                    )["Boot"]["UefiTargetBootSourceOverride@Redfish.AllowableValues"]
                    for source in bootsources:
                        if source["StructuredBootString"].upper() == entry.upper():
                            for val in allowable_vals:
                                if "UEFIDevicePath" in source and source["UEFIDevicePath"].endswith(val):
                                    entry = val
                                    break
                except KeyError:
                    pass

                if not entry == uefitargetstatus["Boot"]["UefiTargetBootSourceOverride"]:
                    newlist += " Boot/UefiTargetBootSourceOverride=" + entry
                elif not targetstatus["Boot"]["BootSourceOverrideTarget"] == "UefiTarget":
                    newlist += " Boot/BootSourceOverrideTarget=UefiTarget"

                if bootoverride:
                    if self.rdmc.app.typepath.defs.isgen9 and newlist:
                        if not bootoverride.split("=")[-1] == bootstatus["Boot"]["BootSourceOverrideEnabled"]:
                            # Preemptively set UefiTargetBootSourceOverride so iLO 4 doesn't complain
                            self.rdmc.app.patch_handler(
                                self.rdmc.app.typepath.defs.systempath,
                                {"Boot": {"UefiTargetBootSourceOverride": entry}},
                                silent=True,
                                service=True,
                            )
                            self.rdmc.app.select(selector=self.rdmc.app.selector, path_refresh=True)
                            newlist = ""
                            newlist += bootoverride
                    else:
                        newlist += bootoverride

                if options.reboot and newlist:
                    newlist += " --commit --reboot " + options.reboot
                elif options.commit and newlist:
                    newlist += " --commit"

                if newlist:
                    try:
                        self.auxcommands["set"].run(newlist)
                    except InvalidOrNothingChangedSettingsError:
                        if self.rdmc.app.typepath.defs.isgen9:
                            pass
                        else:
                            raise
                else:
                    raise InvalidOrNothingChangedSettingsError("Entry is the " "current boot setting.\n")
            elif options.disablebootflag:
                if bootoverride:
                    newlist += bootoverride

                if options.reboot:
                    newlist += " --commit --reboot " + options.reboot
                elif options.commit and newlist:
                    newlist += " --commit"

                if newlist:
                    self.auxcommands["set"].run(newlist)
                else:
                    raise InvalidOrNothingChangedSettingsError("Entry is the " "current boot setting.\n")
            else:
                raise InvalidCommandLineError(
                    "Invalid entry passed for one"
                    " time boot. Please run boot \n       order without"
                    " arguments to view available options.\n"
                )

        self.cmdbase.logout_routine(self, options)

        # Return code
        return ReturnCodes.SUCCESS

    def searchcasestring(self, entry, content):
        """Helper function for retrieving correct case for value

        :param entry: entry to correlate case
        :type entry: string.
        :param content: list of items
        :type content: list.
        """
        for item in content:
            if entry.upper() == item.upper():
                return item

    def secureboothelper(self, securebootoption):
        """Helper function for secure boot function

        :param securebootoption: option passed in for secure boot
        :type securebootoption: string.
        """
        actionlist = ["defaultkeys", "deletekeys", "deletepk"]

        if not securebootoption.lower() in actionlist:
            raise InvalidCommandLineError("%s is not a valid option for " "the securebootkeys flag." % securebootoption)

        if securebootoption == actionlist[0]:
            action = "ResetAllKeysToDefault"
        elif securebootoption == actionlist[1]:
            action = "DeleteAllKeys"
        elif securebootoption == actionlist[2]:
            action = "DeletePK"

        results = self.rdmc.app.select(selector=self.rdmc.app.typepath.defs.hpsecureboot)

        try:
            results = results[0]
        except:
            pass

        if results:
            path = results.resp.request.path
            results = results.resp.dict

        try:
            for item in results["Actions"]:
                if "ResetKeys" in item:
                    path = results["Actions"][item]["target"]
                    break

            body = {"ResetKeysType": action}
            self.rdmc.app.post_handler(path, body)
        except:
            if securebootoption == actionlist[0]:
                self.auxcommands["select"].selectfunction(self.rdmc.app.typepath.defs.hpsecureboot)
                self.auxcommands["set"].run("ResetToDefaultKeys=True --commit")
            elif securebootoption == actionlist[1]:
                self.auxcommands["select"].selectfunction(self.rdmc.app.typepath.defs.hpsecureboot)
                self.auxcommands["set"].run("ResetAllKeys=True --commit")
            else:
                self.rdmc.ui.warn("DeletePK option is not available on Gen9.\n")

    def print_out_boot_order(
        self,
        content,
        onetimecontent,
        uefionetimecontent,
        bootmode,
        bootsources,
        bootstatus,
        targetstatus,
    ):
        """Convert content to human readable and print out to std.out

        :param content: current content
        :type content: string.
        :param onetimecontent: list of one time boot entries
        :type onetimecontent: list.
        :param uefionetimecontent: list of uefi one time boot entries
        :type uefionetimecontent: list.
        :param bootmode: current system boot mode
        :type bootmode: string.
        :param bootsources: current systems boot sources
        :type bootsources: list.
        """
        if content is None:
            raise BootOrderMissingEntriesError("No entries found in " "current boot order.\n\n")
        else:
            self.print_boot_helper(content[0], "\nCurrent Persistent Boot " "Order:", bootsources=bootsources)

        bootstatusval = bootstatus[0]["Boot"]["BootSourceOverrideEnabled"]
        boottoval = targetstatus[0]["Boot"]["BootSourceOverrideTarget"]
        if bootstatusval == "Continuous":
            self.rdmc.ui.printer("Current continuous boot: {0}\n\n".format(boottoval))
        elif bootstatusval == "Once":
            self.rdmc.ui.printer("Current one time boot: {0}\n\n".format(boottoval))

        if onetimecontent is None:
            raise BootOrderMissingEntriesError("No entries found for one time boot options.\n\n")
        else:
            self.print_boot_helper(onetimecontent[0]["Boot"], "Continuous and one time boot options:")

        if bootmode and any([bootmode[0].get(boot, None) == "Uefi" for boot in bootmode[0]]):
            if uefionetimecontent is None:
                self.rdmc.ui.printer("Continuous and one time boot uefi options:\n")
                self.rdmc.ui.printer(
                    "No entries found for one-time UEFI options or boot source mode " "is not set to UEFI."
                )
            else:
                if isinstance(uefionetimecontent, dict):
                    self.print_boot_helper(
                        uefionetimecontent["Boot"],
                        "Continuous and one time boot uefi options:",
                        bootsources=bootsources,
                    )
                else:
                    self.print_boot_helper(
                        uefionetimecontent[0]["Boot"],
                        "Continuous and one time boot uefi options:",
                        bootsources=bootsources,
                    )

    def print_boot_helper(self, content, outstring, indent=0, bootsources=None):
        """Print boot helper

        :param content: current content
        :type content: string.
        :param outstring: output string
        :type outstring: string.
        :param indent: indent format
        :type indent: string.
        :param bootsources: current systems boot sources
        :type bootsources: list.
        """
        for _, value in list(content.items()):
            self.rdmc.ui.printer("\t" * indent + outstring)

            if isinstance(value, list):
                count = 1

                for item in value:
                    self.rdmc.ui.printer("\n")

                    if not item:
                        item = str("null")

                    # if isinstance(item, six.string_types):
                    bootstring = False
                    try:
                        for source in bootsources:
                            if item == source["StructuredBootString"]:
                                self.rdmc.ui.printer(
                                    "\t" * indent
                                    + str(count)
                                    + ". "
                                    + str(item)
                                    + " ("
                                    + str(source["BootString"])
                                    + ")"
                                )
                                bootstring = True
                                break

                        if not bootstring:
                            self.rdmc.ui.printer("\t" * indent + str(count) + ". " + str(item))
                    except:
                        self.rdmc.ui.printer("\t" * indent + str(count) + ". " + str(item))

                    count += 1
                    # else:
                    #    self.print_boot_helper(item, indent+1)

        self.rdmc.ui.printer("\n\n")

    def bootordervalidation(self, options):
        """Boot order method validation function

        :param options: command line options
        :type options: list.
        """
        inputline = list()

        if self.rdmc.config.commit.lower() == "true":
            options.commit = True

        self.cmdbase.login_select_validation(self, options)

        if inputline:
            self.lobobj.loginfunction(inputline)

        if options.encode:
            options.biospassword = Encryption.decode_credentials(options.biospassword)
            if isinstance(options.biospassword, bytes):
                options.biospassword = options.biospassword.decode("utf-8")

    @staticmethod
    def options_argument_group(parser):
        """Additional argument

        :param parser: The parser to add the removeprivs option group to
        :type parser: ArgumentParser/OptionParser
        """

        parser.add_argument_group(
            "GLOBAL OPTION:",
            "Option(s) are available " "for all arguments within the scope of this command.",
        )

        parser.add_argument(
            "-j",
            "--json",
            dest="json",
            action="store_true",
            help="Optionally include this flag if you wish to change the"
            " displayed output to JSON format. Preserving the JSON data"
            " structure makes the information easier to parse.",
            default=False,
        )

    def definearguments(self, customparser):
        """Wrapper function for new command main function

        :param customparser: command line input
        :type customparser: parser.
        """
        if not customparser:
            return

        self.cmdbase.add_login_arguments_group(customparser)
        self.options_argument_group(customparser)

        customparser.add_argument(
            "--onetimeboot",
            dest="onetimeboot",
            help="Use this flag to configure a one-time boot option."
            " Using this flag will prioritize the provided boot source"
            " only on the very next time the server is booted.",
            default=None,
        )
        customparser.add_argument(
            "--continuousboot",
            dest="continuousboot",
            help="Use this flag to enable a continuous boot option. Using"
            " this flag will cause the system to boot to the selected"
            " device every time the system boots.",
            default=None,
        )
        customparser.add_argument(
            "--disablebootflag",
            dest="disablebootflag",
            action="store_true",
            help="Use this to disable either continuous or one-time boot modes.",
            default=None,
        )
        customparser.add_argument(
            "--securebootkeys",
            dest="secureboot",
            help="Use this flag to perform actions on secure boot keys."
            "Possible values include defaultkeys: resets all keys to default,"
            "deletekeys: deletes all keys, deletepk: deletes all product keys.",
            default=False,
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
            "--ignorematcherror",
            dest="ime",
            action="store_true",
            help="Use this flag when you want to run multiple matches and "
            "not throw an error in case there are no matches found for given "
            "expression.",
            default=None,
        )
