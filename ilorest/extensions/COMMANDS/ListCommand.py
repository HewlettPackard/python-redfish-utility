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
""" List Command for RDMC """

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


class ListCommand:
    """Constructor"""

    def __init__(self):
        self.ident = {
            "name": "list",
            "usage": None,
            "description": "Displays the current values of the "
            "properties within\n\ta selected type including"
            " reserved properties\n\texample: list\n\n\tNOTE: If "
            "you wish to not list all the reserved properties\n\t     "
            " run the get command instead",
            "summary": "Displays the current value(s) of a"
            " property(ies) within a selected type including"
            " reserved properties.",
            "aliases": ["ls"],
            "auxcommands": ["GetCommand"],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """Wrapper function for main list function

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

        selector = options.selector.lower() if options.selector else self.rdmc.app.selector.lower()

        if "securityservice" in selector:
            self.cmdbase.login_validation(self, options)
        else:
            self.listvalidation(options)

        fvals = (None, None)

        if options.filter:
            try:
                if (str(options.filter)[0] == str(options.filter)[-1]) and str(options.filter).startswith(("'", '"')):
                    options.filter = options.filter[1:-1]

                (sel, val) = options.filter.split("=")
                fvals = (sel.strip(), val.strip())
            except:
                raise InvalidCommandLineError("Invalid filter" " parameter format [filter_attribute]=[filter_value]")
        if "StorageController." in options.selector.lower():
            options.selector = "storagecontrollercollection"
        if options.selector:
            self.rdmc.app.selector = options.selector
        elif self.rdmc.app.selector:
            options.selector = self.rdmc.app.selector
        if "securityservice" in options.selector.lower():
            url = "/redfish/v1/Managers/1/SecurityService/"
            contents = self.rdmc.app.get_handler(url, service=True, silent=True).dict
            security_contents = []

            if options and options.json and contents:
                UI().print_out_json(contents)
            elif not args:
                UI().print_out_human_readable(contents)
            else:
                attr = args[0]
                contents_lower = {k.lower(): v for k, v in contents.items()}
                security_contents.append({attr: contents_lower[attr.lower()]})
            if security_contents:
                UI().print_out_human_readable(security_contents)
        else:
            self.auxcommands["get"].getworkerfunction(args, options, filtervals=fvals, uselist=False)

        self.cmdbase.logout_routine(self, options)
        # Return code
        return ReturnCodes.SUCCESS

    def listvalidation(self, options):
        """List data validation function

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
            "-j",
            "--json",
            dest="json",
            action="store_true",
            help="Optionally include this flag if you wish to change the"
            " displayed output to JSON format. Preserving the JSON data"
            " structure makes the information easier to parse.",
            default=False,
        )
        customparser.add_argument(
            "--refresh",
            dest="ref",
            action="store_true",
            help="Optionally reload the data of selected type and clear " "patches from current selection.",
            default=False,
        )
