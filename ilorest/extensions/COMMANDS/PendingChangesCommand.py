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
""" Results Command for rdmc """

import copy
import json
import sys

import jsondiff

try:
    from rdmc_helper import HARDCODEDLIST
except:
    from ilorest.rdmc_helper import HARDCODEDLIST
try:
    from rdmc_helper import (
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        ReturnCodes,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        ReturnCodes,
    )


class PendingChangesCommand:
    """PendingChanges class command"""

    def __init__(self):
        self.ident = {
            "name": "pending",
            "usage": None,
            "description": "Run to show pending committed changes "
            "that will be applied after a reboot.\n\texample: pending",
            "summary": "Show the pending changes that will be applied on reboot.",
            "aliases": [],
            "auxcommands": [],
        }

        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """Show pending changes of settings objects

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
            raise InvalidCommandLineError("Pending command does not take any arguments.")
        self.pendingvalidation(options)

        self.pendingfunction()
        sys.stdout.write("\n")
        self.cmdbase.logout_routine(self, options)
        return ReturnCodes.SUCCESS

    def pendingfunction(self):
        """Main pending command worker function"""
        settingsuri = []
        ignorekeys = ["@odata.id", "@odata.etag", "@redfish.settings", "oem"]
        ignoreuri = [str("hpsut*")]
        ignorekeys.extend(HARDCODEDLIST)

        resourcedir = self.rdmc.app.get_handler(self.rdmc.app.monolith._resourcedir, service=True, silent=True)

        for resource in resourcedir.dict["Instances"]:
            if (resource["@odata.id"].split("/").__len__() - 1) > 4:
                splitstr = resource["@odata.id"].split("/")[5]
            for element in ignoreuri:
                if "/settings" in resource["@odata.id"] and not self.wildcard_str_match(element, splitstr):
                    settingsuri.append(resource["@odata.id"])

        self.rdmc.ui.printer("Current Pending Changes:\n")

        for uri in settingsuri:
            diffprint = {}
            baseuri = uri.split("settings")[0]

            base = self.rdmc.app.get_handler(baseuri, service=True, silent=True)
            settings = self.rdmc.app.get_handler(uri, service=True, silent=True)

            typestring = self.rdmc.app.monolith.typepath.defs.typestring
            currenttype = ".".join(base.dict[typestring].split("#")[-1].split(".")[:-1])

            differences = json.loads(jsondiff.diff(base.dict, settings.dict, syntax="symmetric", dump=True))

            diffprint = self.recursdict(differences, ignorekeys)

            self.rdmc.ui.printer("\n%s:" % currenttype)
            if not diffprint:
                self.rdmc.ui.printer("\nNo pending changes found.\n")
            else:
                self.rdmc.ui.pretty_human_readable(diffprint)

    def wildcard_str_match(self, first, second):
        """
        Recursive function for determining match between two strings. Accounts
        for wildcard characters

        :param first: comparison string (may contain '*' or '?' for wildcards)
        :param type: str (unicode)
        :param second: string value to be compared (must not contain '*' or '?')
        :param type: str (unicode)
        """

        if not first and not second:
            return True
        if len(first) > 1 and first[0] == "*" and not second:
            return False
        if (len(first) > 1 and first[0] == "?") or (first and second and first[0] == second[0]):
            return self.wildcard_str_match(first[1:], second[1:])
        if first and first[0] == "*":
            return self.wildcard_str_match(first[1:], second) or self.wildcard_str_match(first, second[1:])

        return False

    def recursdict(self, diff, ignorekeys):
        """Recursively get dict ready for printing

        :param diff: diff dict
        :type options: dict.
        """
        diffprint = copy.deepcopy(diff)
        for item in diff:
            if item.lower() in ignorekeys:
                diffprint.pop(item)
            elif item == "$delete":
                for ditem in diff[item]:
                    if isinstance(diff[item], list):
                        continue
                    if isinstance(diff[item][ditem], dict):
                        diffprint[item].pop(ditem)
                        if ditem.lower() in ignorekeys or ditem.isdigit():
                            continue
                        else:
                            diffprint.update({"removed": ditem})
                diffprint.pop(item)
            elif item == "$insert":
                for ditem in diff[item]:
                    del diffprint[item][diffprint[item].index(ditem)]
                    diffprint.update({"changed index position": ditem[1]})
                diffprint.pop(item)
            elif isinstance(diff[item], dict):
                diffprint[item] = self.recursdict(diff[item], ignorekeys)

            elif isinstance(diff[item], list):
                diffprint.update({item: {"Current": diff[item][0], "Pending": diff[item][1]}})
            else:
                continue

        return diffprint

    def pendingvalidation(self, options):
        """Pending method validation function

        :param options: command line options
        :type options: list.
        """
        self.cmdbase.login_select_validation(self, options)

    def definearguments(self, customparser):
        """Wrapper function for new command main function

        :param customparser: command line input
        :type customparser: parser.
        """
        if not customparser:
            return

        self.cmdbase.add_login_arguments_group(customparser)
