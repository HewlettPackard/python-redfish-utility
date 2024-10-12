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
""" Select Command for RDMC """

from redfish.ris import NothingSelectedError

try:
    from rdmc_helper import LOGGER, InvalidCommandLineErrorOPTS, ReturnCodes
except ImportError:
    from ilorest.rdmc_helper import LOGGER, InvalidCommandLineErrorOPTS, ReturnCodes


class SelectCommand:
    """Constructor"""

    def __init__(self):
        self.ident = {
            "name": "select",
            "usage": None,
            "description": "Selects the Redfish/HpRest type to be used.\nIn order to "
            "remove the need of including the version while selecting you"
            " can simply enter the type name until the first period\n\t"
            "example: select HpBios.\n"
            "Run without an argument to "
            "display the currently selected type\n\texample: select",
            "summary": "Selects the object type to be used.",
            "aliases": ["sel"],
            "auxcommands": ["LoginCommand"],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def selectfunction(self, line):
        """Main select worker function

        :param line: command line input
        :type line: string.
        """

        try:
            (options, args) = self.rdmc.rdmc_parse_arglist(self, line)
        except (InvalidCommandLineErrorOPTS, SystemExit):
            if ("-h" in line) or ("--help" in line):
                return ReturnCodes.SUCCESS
            else:
                raise InvalidCommandLineErrorOPTS("")

        self.selectvalidation(options)

        if args:
            if options.ref:
                LOGGER.warning("Patches from current selection will be cleared.")
            selector = args[0]
            selections = self.rdmc.app.select(selector=selector, path_refresh=options.ref)

            if "storage" in selector.lower():
                storage_url = "/redfish/v1/Systems/1/Storage/"
                list_storageid = self.rdmc.app.get_handler(storage_url, silent=True, service=True).dict["Members"]
                for val in list_storageid:
                    storageid_fromurl = val["@odata.id"]
                    ctr = self.rdmc.app.get_handler(storageid_fromurl, silent=True, service=True).dict
                    if "Controllers" in ctr:
                        ctr_url = ctr["Controllers"]["@odata.id"]
                        self.rdmc.app.get_handler(ctr_url, silent=True, service=True).dict
            if self.rdmc.opts.verbose and selections:
                templist = list()
                self.rdmc.ui.printer("Selected option(s): ")

                for item in selections:
                    if item.type not in templist:
                        templist.append(item.type)

                self.rdmc.ui.printer("%s\n" % ", ".join(map(str, templist)))

        else:
            selector = self.rdmc.app.selector

            if selector:
                sellist = [sel for sel in self.rdmc.app.monolith.typesadded if selector.lower() in sel.lower()]
                self.rdmc.ui.printer("Current selection: ")
                self.rdmc.ui.printer("%s\n" % ", ".join(map(str, sellist)))
            else:
                raise NothingSelectedError

        self.cmdbase.logout_routine(self, options)

    def selectvalidation(self, options):
        """Select data validation function

        :param options: command line options
        :type options: list.
        """

        self.cmdbase.login_select_validation(self, options)

    def run(self, line, help_disp=False):
        """Wrapper function for main select function

        :param line: entered command line
        :type line: list.
        """
        if help_disp:
            self.parser.print_help()
            return ReturnCodes.SUCCESS
        self.selectfunction(line)

        # Return code
        return ReturnCodes.SUCCESS

    def definearguments(self, customparser):
        """Wrapper function for new command main function

        :param customparser: command line input
        :type customparser: parser.
        """
        if not customparser:
            return

        self.cmdbase.add_login_arguments_group(customparser)

        customparser.add_argument(
            "--refresh",
            dest="ref",
            action="store_true",
            help="Optionally reload the data of selected type and clear " "patches from current selection.",
            default=False,
        )
