# ##
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
# ##

# -*- coding: utf-8 -*-
""" Install Set Command for rdmc """

import json
import os

from six.moves import input

try:
    from rdmc_helper import (
        IncompatibleiLOVersionError,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        ReturnCodes,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        IncompatibleiLOVersionError,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        ReturnCodes,
    )


class MakeInstallSetCommand:
    """Command class to create installset payload"""

    def __init__(self):
        self.ident = {
            "name": "makeinstallset",
            "usage": None,
            "description": "Run to enter a guided shell for making "
            "install sets. If not currently\n\tlogged into a server will perform "
            "basic guidance on making an installset,\n\tif logged into a server "
            "will provide guidance based on the current\n\tcomponents on the system. "
            "If you wish to use this command on a logged in\n\tserver upload the "
            "components before running for best results.",
            "summary": "Creates install sets for iLO.",
            "aliases": ["minstallset"],
            "auxcommands": [],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()
        self.defaultprops = {
            "UpdatableBy": ["Bmc"],
            "Command": "ApplyUpdate",
            "WaitTimeSeconds": 0,
            "Filename": "",
        }
        self.helptext = {
            "Command": "Possible Commands: ApplyUpdate, ResetServer, " "ResetBmc, Wait",
            "UpdatableBy": "Possible Update parameter(s)"
            ":\nBmc: Updatable by iLO\nUefi: Updatable by Uefi\n"
            "RuntimeAgent: Updatable by runtime agent such as SUM/SUT",
            "WaitTimeSeconds": "Number of seconds to pause in Wait " "command.",
            "Filename": "Unique filename of component on " "iLO repository",
        }
        self.loggedin = None
        self.comps = None

    def run(self, line, help_disp=False):
        """Main installset worker function

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

        self.loggedin = None
        self.comps = None
        self.loggedin = self.minstallsetvalidation()

        if self.loggedin and self.rdmc.app.typepath.defs.isgen9:
            raise IncompatibleiLOVersionError("iLO Repository commands are " "only available on iLO 5.")

        self.rdmc.ui.warn("This command will run in interactive mode.\n")
        if args:
            raise InvalidCommandLineError("makeinstallset command takes no arguments.")

        self.minstallsetworker(options)

        self.cmdbase.logout_routine(self, options)
        # Return code
        return ReturnCodes.SUCCESS

    def minstallsetworker(self, options):
        """Main installset creation worker

        :param options: command line options
        :type options: list.
        """
        comps = {}
        totcomps = []
        count = -1
        totcount = 0
        self.rdmc.ui.warn("Entering new shell, type quit to leave!\n")
        if self.loggedin:
            self.rdmc.ui.printer("Running in logged in mode.")
            self.comps = self.rdmc.app.getcollectionmembers("/redfish/v1/UpdateService/ComponentRepository/")
        else:
            self.rdmc.ui.printer("Running in basic guidance mode.")
        while True:
            comps = {}
            count = -1
            reqdprops = ["Command"]
            while True:
                if len(reqdprops) <= count:
                    break
                if count == -1:
                    line = input("\nEnter a name for this command: ")
                else:
                    self.rdmc.ui.printer("\n" + self.helptext[reqdprops[count]] + "\n")
                    if self.loggedin and reqdprops[count].lower() == "filename":
                        filenm, updateby, target = self.checkfiles(options)
                        comps["Filename"] = filenm
                        comps["UpdatableBy"] = updateby
                        if options.targets:
                            comps["Targets"] = target
                        break
                    else:
                        line = input("Enter " + reqdprops[count] + " for " + comps["Name"] + ": ")
                if line.endswith(os.linesep):
                    line.rstrip(os.linesep)
                if line == "quit":
                    break
                elif line == "" and not count == -1:
                    line = self.defaultprops[reqdprops[count]]
                if count == -1:
                    comps["Name"] = line
                else:
                    while True:
                        validated = self.validatepropvalue(reqdprops[count], line, reqdprops)
                        if not validated:
                            if line == "quit":
                                break
                            line = input(
                                "Input %s is not a valid property " "for %s. Try again: " % (line, reqdprops[count])
                            )
                        else:
                            comps[reqdprops[count]] = validated
                            break
                count = count + 1
            if line == "quit":
                break
            else:
                totcomps.append(comps)
                totcount = totcount + 1

        if not totcount:
            self.rdmc.ui.warn("No sequences created. Exiting without creating an installset.\n")
        else:
            while True:
                isrecovery = input("Is this a recovery installset? ")
                isrecovery = True if str(isrecovery).lower() in ["true", "t", "yes", "y"] else isrecovery
                isrecovery = False if str(isrecovery).lower() in ["false", "f", "no", "n"] else isrecovery
                if not isinstance(isrecovery, bool):
                    self.rdmc.ui.warn("'Isrecovery' should be either true or false.\n")
                    continue
                else:
                    break

            if isrecovery:
                installsetname = "System Recovery Set"
            else:
                while True:
                    installsetname = input("Enter installset name: ")
                    if not installsetname:
                        self.rdmc.ui.warn("Install set must have a name.\n")
                    else:
                        break

            description = input("Enter description for the installset: ")

            body = {
                "Name": installsetname,
                "Description": description,
                "IsRecovery": isrecovery,
                "Sequence": totcomps,
            }

            self.rdmc.ui.print_out_json(body)
            with open(options.filename, "w") as outfile:
                json.dump(body, outfile, indent=2, sort_keys=True)

            self.rdmc.ui.printer("installset saved to %s\n" % options.filename)

    def validatepropvalue(self, propvalue, givenvalue, reqdprops):
        """Validates a string returning the correct type

        :param propvalue: property to validate
        :type propvalue: string.
        :param givenvalue: value to validate
        :type givenvalue: string.
        :param reqdprops: the required property list
        :type reqdprops: list.
        """
        validated_property = None
        if propvalue == "WaitTimeSeconds":
            validated_property = int(givenvalue)
        elif propvalue == "UpdatableBy":
            if isinstance(givenvalue, list):
                validated_property = givenvalue
            value = [x.strip() for x in givenvalue.split(",")]
            for ind, item in enumerate(value):
                if item.lower() == "runtimeagent":
                    value[ind] = "RuntimeAgent"
                elif item.lower() == "uefi":
                    value[ind] = "Uefi"
                elif item.lower() == "bmc":
                    value[ind] = "Bmc"
            validated_property = value
        elif propvalue == "Command":
            if givenvalue.lower() == "applyupdate":
                if self.loggedin and not self.comps:
                    self.rdmc.ui.printer("All components on the system are already " "added to the installset.\n")
                else:
                    reqdprops.append("Filename")
                    reqdprops.append("UpdatableBy")
                    validated_property = "ApplyUpdate"
            elif givenvalue.lower() == "resetserver":
                validated_property = "ResetServer"
            elif givenvalue.lower() == "resetbmc":
                validated_property = "ResetBmc"
            elif givenvalue.lower() == "wait":
                reqdprops.append("WaitTimeSeconds")
                validated_property = "Wait"
        elif propvalue == "Filename":
            if givenvalue:
                validated_property = givenvalue

        return validated_property

    def get_target(self, target):
        target_list = target.split(",")
        for target in target_list:
            try:
                target_url = "/redfish/v1/UpdateService/FirmwareInventory/" + target
                dd = self.rdmc.app.get_handler(target_url, service=True, silent=True)
                if dd.status == 404:
                    return False
            except:
                return False
        return True

    def checkfiles(self, options):
        count = 0
        self.rdmc.ui.printer("Components currently in the repository that have not " "been added to the installset:\n")
        for comp in self.comps:
            count += 1
            self.rdmc.ui.printer("[%d] %s %s\n" % (count, comp["Name"], comp["Version"]))
        while True:
            userinput = input("Select the number of the component you want to add to " "the install set: ")
            try:
                userinput = int(userinput)
                if userinput > count or userinput == 0:
                    raise
                break
            except:
                self.rdmc.ui.warn("Input is not a valid number.\n")
        filename = self.comps[userinput - 1]["Filename"]
        updatableby = self.comps[userinput - 1]["UpdatableBy"]
        if options.targets:
            targets = []
            target_list = options.targets.split(",")
            for target in target_list:
                target_url = "/redfish/v1/UpdateService/FirmwareInventory/" + str(target) + "/"
                targets.append(target_url)
            verified = self.get_target(options.targets)
            if not verified:
                self.rdmc.ui.error("Provided target was not available, Please provide valid target id\n")
                return ReturnCodes.INVALID_TARGET_ERROR
            target = targets
            return filename, updatableby, target
        else:
            target = None
            del self.comps[userinput - 1]
            return filename, updatableby, target

    def minstallsetvalidation(self):
        """makeinstallset validation function"""

        try:
            _ = self.rdmc.app.current_client
            loggedin = True
        except:
            loggedin = False

        return loggedin

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
            " myinstallset.json",
            default="myinstallset.json",
        )
        customparser.add_argument(
            "--targets",
            help="If targets value specify a comma separated" "firmwareinventory id only",
            metavar="targets_indices",
        )
