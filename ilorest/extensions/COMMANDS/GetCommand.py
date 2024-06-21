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
""" Get Command for RDMC """
from collections import OrderedDict

import six

import redfish.ris
from redfish.ris.utils import iterateandclear

try:
    from rdmc_helper import (
        UI,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        NoContentsFoundForOperationError,
        ReturnCodes,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        UI,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        NoContentsFoundForOperationError,
        ReturnCodes,
    )
try:
    from rdmc_helper import HARDCODEDLIST
except:
    from ilorest.rdmc_helper import HARDCODEDLIST


class GetCommand:
    """Constructor"""

    def __init__(self):
        self.ident = {
            "name": "get",
            "usage": None,
            "description": "To retrieve all"
            " the properties run without arguments. \n\t*Note*: "
            "a type will need to be selected or this will return an "
            "error.\n\texample: get\n\n\tTo retrieve multiple "
            "properties use the following example\n\texample: "
            "get Temperatures/ReadingCelsius Fans/Name --selector=Thermal."
            "\n\n\tTo change output style format provide"
            " the json flag\n\texample: get --json",
            "summary": "Displays the current value(s) of a" " property(ies) within a selected type.",
            "aliases": [],
            "auxcommands": ["LogoutCommand"],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """Main get worker function

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

        if getattr(options, "json"):
            self.rdmc.json = True

        selector = options.selector.lower() if options.selector else self.rdmc.app.selector.lower()

        if "securityservice" in selector:
            self.cmdbase.login_validation(self, options)
        else:
            self.getvalidation(options)

        filtr = (None, None)
        if options.filter:
            try:
                if (str(options.filter)[0] == str(options.filter)[-1]) and str(options.filter).startswith(("'", '"')):
                    options.filter = options.filter[1:-1]

                (sel, val) = options.filter.split("=")
                filtr = (sel.strip(), val.strip())

            except:
                raise InvalidCommandLineError("Invalid filter" " parameter format [filter_attribute]=[filter_value]")

        self.getworkerfunction(
            args,
            options,
            results=None,
            uselist=True,
            filtervals=filtr,
            readonly=options.noreadonly,
        )

        self.cmdbase.logout_routine(self, options)
        # Return code
        return ReturnCodes.SUCCESS

    def getworkerfunction(
        self,
        args,
        options,
        readonly=False,
        filtervals=(None, None),
        results=None,
        uselist=False,
    ):
        """main get worker function

        :param args: command line arguments
        :type args: list.
        :param options: command line options
        :type options: list.
        :param line: command line input
        :type line: string.
        :param readonly: remove readonly properties
        :type readonly: bool
        :param filtervals: filter key value pair (Key,Val)
        :type filtervals: tuple
        :param results: current results collected
        :type results: string.
        :param uselist: use reserved properties list to filter results
        :type uselist: boolean.
        """
        nocontent = set()
        instances = None
        arg = None

        # For rest redfish compatibility of bios.
        if hasattr(options, "selector") and options.selector:
            self.rdmc.app.selector = options.selector
        args = [args] if args and isinstance(args, six.string_types) else args
        if self.rdmc.app.selector and "." not in self.rdmc.app.selector:
            self.rdmc.app.selector = self.rdmc.app.selector + "."
        args = (
            [
                (
                    "Attributes/" + arg
                    if self.rdmc.app.selector
                    and self.rdmc.app.selector.lower().startswith("bios.")
                    and "attributes" not in arg.lower()
                    else arg
                )
                for arg in args
            ]
            if args
            else args
        )
        if filtervals[0]:
            instances = self.rdmc.app.select(selector=self.rdmc.app.selector, fltrvals=filtervals)

        try:
            if "securityservice" in self.rdmc.app.selector.lower():
                url = "/redfish/v1/Managers/1/SecurityService/"
                contents = self.rdmc.app.get_handler(url, service=True, silent=True).dict
                security_contents = []
                if not args and not options.json:
                    UI().print_out_human_readable(contents)
                elif options and options.json and contents:
                    UI().print_out_json(contents)
                else:
                    attr = args[0]
                    contents_lower = {k.lower(): v for k, v in contents.items()}
                    security_contents.append({attr: contents_lower[attr.lower()]})
                if security_contents:
                    UI().print_out_human_readable(security_contents)
            else:
                if "selector" in options:
                    contents = self.rdmc.app.getprops(
                        props=args,
                        remread=readonly,
                        selector=options.selector,
                        nocontent=nocontent,
                        insts=instances,
                    )
                else:
                    contents = self.rdmc.app.getprops(
                        props=args, remread=readonly, nocontent=nocontent, insts=instances
                    )
            uselist = False if readonly else uselist
        except redfish.ris.rmc_helper.EmptyRaiseForEAFP:
            contents = self.rdmc.app.getprops(props=args, nocontent=nocontent)
        for ind, content in enumerate(contents):
            if "bios." in self.rdmc.app.selector.lower() and "Attributes" in list(content.keys()):
                content.update(content["Attributes"])
                del content["Attributes"]
            contents[ind] = OrderedDict(sorted(list(content.items()), key=lambda x: x[0]))
        if len(args) > 0 and "Members" in args[0]:
            uselist = False
        if uselist:
            for item in contents:
                self.removereserved(item)
        if results:
            return contents

        contents = contents[0] if len(contents) == 1 else contents

        if options and options.json and contents:
            UI().print_out_json(contents)
        elif contents:
            UI().print_out_human_readable(contents)
        else:
            try:
                if nocontent or not any(next(iter(contents))):
                    raise Exception()
            except Exception:
                strtoprint = ", ".join(str(val) for val in nocontent)
                if not strtoprint and arg:
                    strtoprint = arg
                    raise NoContentsFoundForOperationError("No get contents found for entry: %s" % strtoprint)
                else:
                    raise NoContentsFoundForOperationError("No get contents found for " "selected type.")
        if options.logout:
            self.auxcommands["logout"].run("")

    def removereserved(self, entry):
        """function to remove reserved properties
        :param entry: dictionary to remove reserved properties from
        :type entry: dict.
        """

        for key, val in list(entry.items()):
            if key.lower() in HARDCODEDLIST or "@odata" in key.lower():
                del entry[key]
            elif isinstance(val, list):
                for item in entry[key]:
                    if isinstance(item, dict) and item:
                        self.removereserved(item)
                        if all([True if not test else False for test in entry[key]]):
                            del entry[key]
            elif isinstance(val, dict):
                self.removereserved(val)
                if all([True if not test else False for test in entry[key]]):
                    del entry[key]

    def checktoprint(self, options, contents, nocontent, arg):
        """function to decide what/how to print
        :param options: list of options
        :type options: list.
        :param contents: dictionary value returned by getprops.
        :type contents: dict.
        :param nocontent: props not found are added to the list.
        :type nocontent: list.
        :param arg: string of args
        :type arg: string
        """
        if options and options.json and contents:
            self.rdmc.ui.print_out_json(contents)
        elif contents:
            self.rdmc.ui.print_out_human_readable(contents)
        else:
            try:
                if nocontent or not any(next(iter(contents))):
                    raise Exception()
            except:
                strtoprint = ", ".join(str(val) for val in nocontent)
                if not strtoprint and arg:
                    strtoprint = arg
                    raise NoContentsFoundForOperationError("No get contents " "found for entry: %s" % strtoprint)
                else:
                    raise NoContentsFoundForOperationError("No get contents " "found for selected type.")

    def collectandclear(self, contents, key, values):
        """function to find and remove unneeded values from contents dictionary
        :param contents: dictionary value returned by getprops
        :type contents: dict.
        :param key: string of keys
        :type key: string.
        :param values: list of values
        :type values: list.
        """
        clearcontent = contents[0][key]
        if isinstance(clearcontent, dict):
            keyslist = list(clearcontent.keys())
        else:
            keyslist = [clearcontent]
        clearedlist = keyslist
        for arg in values:
            for keys in keyslist:
                if str(keys).lower() == str(arg).lower():
                    clearedlist.remove(arg)
        contents = iterateandclear(contents, clearedlist)
        return contents

    def getvalidation(self, options):
        """get method validation function

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
            "--noreadonly",
            dest="noreadonly",
            action="store_true",
            help="Optionally include this flag if you wish to only show"
            " properties that are not read-only. This is useful to see what "
            "is configurable with the selected type(s).",
            default=False,
        )
        customparser.add_argument(
            "--refresh",
            dest="ref",
            action="store_true",
            help="Optionally reload the data of selected type and clear " "patches from current selection.",
            default=False,
        )
