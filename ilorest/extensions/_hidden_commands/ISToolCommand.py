###
# Copyright 2016 Hewlett Packard Enterprise, Inc. All rights reserved.
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
""" ISTool Command for rmdc """

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


class ISToolCommand:
    """ISTool class command"""

    def __init__(self):
        self.ident = {
            "name": "istool",
            "usage": None,
            "description": "Displays ilo data useful in debugging",
            "summary": "displays ilo data useful in debugging",
            "aliases": [],
            "auxcommands": [],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """Debug helper for iLO

        :param line: string of arguments passed in
        :type line: str.
        """
        if help_disp:
            self.parser.print_help()
            return ReturnCodes.SUCCESS
        ilodata = ""
        reglist = []
        foundreg = False

        try:
            (options, args) = self.rdmc.rdmc_parse_arglist(self, line)
        except (InvalidCommandLineErrorOPTS, SystemExit):
            if ("-h" in line) or ("--help" in line):
                return ReturnCodes.SUCCESS
            else:
                raise InvalidCommandLineErrorOPTS("")

        if args:
            raise InvalidCommandLineError("Istool command does not take any arguments.")

        self.istoolvalidation(options)

        if self.rdmc.app.monolith.is_redfish:
            regstr = "/redfish/v1/Registries/"
            ilostr = "/redfish/v1/Managers/1/"
        else:
            regstr = "/rest/v1/Registries"
            ilostr = "/rest/v1/Managers/1"

        try:
            biosresults = self.rdmc.app.get_handler(self.rdmc.app.typepath.defs.biospath, service=True, silent=True)
            regresults = self.rdmc.app.get_handler(regstr, service=True, silent=True)
            romresults = self.rdmc.app.get_handler(self.rdmc.app.typepath.defs.systempath, service=True, silent=True)
            iloresults = self.rdmc.app.get_handler(ilostr, silent=True, service=True)
        except:
            raise

        if biosresults.dict:
            try:
                biosreg = biosresults.dict["AttributeRegistry"]
                self.rdmc.ui.printer("System has attribute registry: %s\n" % biosreg)
            except Exception as excp:
                biosreg = None
                self.rdmc.ui.error("Attribute registry not found in BIOS.\n", excp)

        if regresults.dict:
            items = regresults.dict[self.rdmc.app.typepath.defs.collectionstring]

            for item in items:
                try:
                    schema = item["Schema"]
                except:
                    item = self.rdmc.app.get_handler(
                        item[self.rdmc.app.typepath.defs.hrefstring],
                        service=True,
                        silent=True,
                    )

                    item = item.dict
                    if "Schema" in item:
                        schema = item["Schema"]
                    else:
                        schema = item["Registry"]

                if schema:
                    available = True

                    locationdict = (
                        self.rdmc.app.validationmanager.geturidict(item["Location"][0])
                        if self.rdmc.app.validationmanager
                        else None
                    )
                    extref = (
                        self.rdmc.app.get_handler(locationdict, service=True, silent=True) if locationdict else None
                    )

                    if not extref:
                        available = False

                    if available:
                        val = schema + " : Available"
                        reglist.append(val)
                    else:
                        val = schema + " : Not Available"
                        reglist.append(val)

                    if schema == biosreg:
                        foundreg = True

            self.rdmc.ui.printer(
                "The following attribute registries are in the registry \
                                                                                repository:\n"
            )
            for item in reglist:
                self.rdmc.ui.printer("%s\n" % item)

        if foundreg:
            self.rdmc.ui.printer("The system attribute registry was found in the " "registry repository.\n")
        else:
            self.rdmc.ui.error("The system attribute registry was not found in " "the registry repository.\n")

        if iloresults.dict:
            try:
                ilodata = iloresults.dict["FirmwareVersion"]
                self.rdmc.ui.printer("iLO Version: %s\n" % ilodata)
            except Exception as excp:
                self.rdmc.ui.error("Unable to find iLO firmware data.\n", excp)

        if romresults.dict:
            try:
                biosversion = romresults.dict["BiosVersion"]
                self.rdmc.ui.printer("BIOS Version: %s\n" % biosversion)
            except Exception as excp:
                self.rdmc.ui.error("Unable to find ROM data.\n", excp)

        self.cmdbase.logout_routine(self, options)
        # Return code
        return ReturnCodes.SUCCESS

    def istoolvalidation(self, options):
        """ISTool validation function"""
        self.cmdbase.login_select_validation(self, options)

    def definearguments(self, customparser):
        """Wrapper function for new command main function

        :param customparser: command line input
        :type customparser: parser.
        """
        if not customparser:
            return

        self.cmdbase.add_login_arguments_group(customparser)
