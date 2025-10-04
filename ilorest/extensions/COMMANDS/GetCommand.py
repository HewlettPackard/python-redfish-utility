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
"""Get Command for RDMC"""
from collections import OrderedDict

import six
import logging

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
except ImportError:
    from ilorest.rdmc_helper import HARDCODEDLIST

LOGGER = logging.getLogger(__name__)


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
            "summary": "Displays the current value(s) of a " "property(ies) within a selected type.",
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

            except (InvalidCommandLineError, SystemExit):
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
                    and not (
                        arg.lower() in ["id", "name", "attributeregistry", "attributes"] or "@odata" in arg.lower()
                    )
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
                LOGGER.info("Fetching SecurityService data from: %s", url)
                contents = self.rdmc.app.get_handler(url, service=True, silent=True).dict
                security_contents = []
                if not args and not options.json:
                    LOGGER.debug("Printing human-readable security service data.")
                    UI().print_out_human_readable(contents)
                elif options and options.json and contents:
                    LOGGER.debug("Printing JSON security service data.")
                    UI().print_out_json(contents)
                else:
                    attr = args[0]
                    contents_lower = {k.lower(): v for k, v in contents.items()}
                    security_contents.append({attr: contents_lower[attr.lower()]})
                if security_contents:
                    UI().print_out_human_readable(security_contents)
            elif (
                "componentintegrity"
                in self.rdmc.app.selector.lower()
                # or "bios." in self.rdmc.app.selector.lower()
            ):
                url = ""
                if "componentintegrity" in self.rdmc.app.selector.lower():
                    url = "/redfish/v1/ComponentIntegrity/?$expand=."
                # elif "bios." in self.rdmc.app.selector.lower():
                #     url = "/redfish/v1/systems/1/bios/?$expand=."

                LOGGER.info("Fetching %s data from: %s", self.rdmc.app.selector, url)
                contents = self.get_content(url, args, uselist, options)
            else:
                LOGGER.debug("Handling general selector case.")
                skipnonsettingflag = True
                if "networkadapter" in self.rdmc.app.selector.lower():
                    skipnonsettingflag = False

                if "selector" in options:
                    LOGGER.info("Fetching properties with selector: %s", options.selector)
                    contents = self.rdmc.app.getprops(
                        props=args,
                        remread=readonly,
                        selector=options.selector,
                        nocontent=nocontent,
                        insts=instances,
                        skipnonsetting=skipnonsettingflag,
                    )

                    if "networkadapter" in self.rdmc.app.selector.lower():
                        unique_adapters = {}
                        for entry in contents:
                            # Remove keys @odata.id & Id if it contains "settings"
                            adapter_id = entry.get("Id", "")
                            odata_id = entry.get("@odata.id", "")
                            if "settings" in odata_id.lower() or "settings" in adapter_id.lower():
                                continue
                            # Preventing deduplicates by Id
                            if adapter_id:
                                unique_adapters[adapter_id] = entry

                        if unique_adapters:
                            contents = list(unique_adapters.values())

                    if (
                        contents
                        and "logentrycollection" in self.rdmc.app.selector.lower()
                        and "@odata.id" in args
                        and not uselist
                    ):
                        # as per documentation
                        # collection of LogEntry resource instances
                        log_contents = self.rdmc.app.getprops(
                            props=["entries/@odata.id"],
                            remread=readonly,
                            selector="logservice",
                            nocontent=nocontent,
                            insts=instances,
                            skipnonsetting=skipnonsettingflag,
                        )
                        if log_contents:
                            log_contents = [
                                val["Entries"]
                                for val in log_contents
                                if "Entries" in val and "@odata.id" in val["Entries"]
                            ]

                            if log_contents:
                                contents.extend(log_contents)
                            # Removing duplicates
                            contents = list({val["@odata.id"]: val for val in contents}.values())

                else:
                    LOGGER.info("Fetching properties without selector.")
                    contents = self.rdmc.app.getprops(
                        props=args, remread=readonly, nocontent=nocontent, insts=instances
                    )
            uselist = False if readonly else uselist
        except redfish.ris.rmc_helper.EmptyRaiseForEAFP:
            LOGGER.error("EmptyRaiseForEAFP exception encountered, retrying getprops without remread.")
            contents = self.rdmc.app.getprops(props=args, nocontent=nocontent)
        for ind, content in enumerate(contents):
            if "bios." in self.rdmc.app.selector.lower() and "Attributes" in list(content.keys()):
                content.update(content["Attributes"])
                del content["Attributes"]
                LOGGER.debug("Flattened BIOS attributes in response.")
            contents[ind] = OrderedDict(sorted(list(content.items()), key=lambda x: x[0]))
        if len(args) > 0 and "Members" in args[0]:
            uselist = False
        if uselist:
            for item in contents:
                self.removereserved(item)
        if results:
            LOGGER.info("Returning retrieved contents.")
            return contents

        contents = contents[0] if len(contents) == 1 else contents

        if options and options.json and contents:
            LOGGER.debug("Printing output in JSON format.")
            UI().print_out_json(contents)
        elif contents:
            LOGGER.debug("Printing output in human-readable format.")
            UI().print_out_human_readable(contents)
        else:
            try:
                if nocontent or not any(next(iter(contents))):
                    raise Exception()
            except Exception:
                strtoprint = ", ".join(str(val) for val in nocontent)
                if not strtoprint and arg:
                    strtoprint = arg
                    LOGGER.error("No contents found for entry: %s", strtoprint)
                    raise NoContentsFoundForOperationError("No get contents found for entry: %s" % strtoprint)
                else:
                    LOGGER.error("No contents found for selected type.")
                    raise NoContentsFoundForOperationError("No get contents found for " "selected type.")
        if options.logout:
            LOGGER.info("Logging out.")
            self.auxcommands["logout"].run("")

    def get_content(self, url, args, uselist, options):
        """Get data from url"""
        contents = self.rdmc.app.get_handler(url, service=True, silent=True).dict
        if uselist:
            # for get command removing @odata.* properties
            args = [arg.lower() for arg in args if "@odata." not in arg.lower()]
        else:
            args = [arg.lower() for arg in args]

        if contents and not args:
            contents = [contents]
        elif contents and args:
            collect_data = []
            for key, value in contents.items():
                # Collect top-level keys based on args
                if any(key.lower() == arg for arg in args):
                    collect_data.append({key: value})

                if "attributes" == key.lower() and isinstance(value, dict) and "attributes" not in args:
                    attr_vals = {k.lower(): v for k, v in value.items()}
                    val_dict = {arg: attr_vals[arg.lower()] for arg in args if arg.lower() in attr_vals}
                    if val_dict:
                        collect_data.append(val_dict)

                if key == "Members" and isinstance(value, list):
                    for member in value:
                        # Loop through each dict of Members
                        m_dict = {k.lower(): v for k, v in member.items()}
                        val_dict = {arg: m_dict[arg.lower()] for arg in args if arg.lower() in m_dict}
                        if val_dict:
                            collect_data.append(val_dict)

            # collect_data = [dict(t) for t in {tuple(d.items()) for d in collect_data}]
            contents = collect_data
        else:
            contents = []

        return contents

    def find_key_recursive(self, data, target_key):
        """Recursively searches for a key in a nested dictionary (case-insensitive) and returns its value(s)."""
        target_key_lower = target_key.lower()  # Convert target_key to lowercase for case-insensitive matching

        if isinstance(data, dict):
            for key, value in data.items():
                if key.lower() == target_key_lower:  # Convert dictionary key to lowercase before comparison
                    yield value  # Use yield to return multiple matches
                elif isinstance(value, (dict, list)):
                    yield from self.find_key_recursive(value, target_key)

        elif isinstance(data, list):
            for item in data:
                yield from self.find_key_recursive(item, target_key)

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
            except Exception:
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
