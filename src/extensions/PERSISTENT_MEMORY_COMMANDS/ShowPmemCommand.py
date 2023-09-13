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
"""Command to display information about Persistent Memory modules"""
from __future__ import absolute_import, division

import re
from argparse import Action
from enum import Enum

try:
    from rdmc_helper import (
        LOGGER,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        NoContentsFoundForOperationError,
        ReturnCodes,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        ReturnCodes,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        NoContentsFoundForOperationError,
        LOGGER,
    )

from .lib.DisplayHelpers import DisplayHelpers, OutputFormats
from .lib.Mapper import Mapper
from .lib.MapperRenderers import MappingTable
from .lib.PmemHelpers import PmemHelpers
from .lib.RestHelpers import RestHelpers


class _Parse_Options_List(Action):
    def __init__(self, option_strings, dest, nargs, **kwargs):
        super(_Parse_Options_List, self).__init__(option_strings, dest, nargs, **kwargs)

    def __call__(self, parser, namespace, values, option_strings):
        """
        Callback to parse a comma-separated list into an array.
        Then store the array in the option's destination
        """
        try:
            setattr(namespace, self.dest, next(iter(values)).split(","))
        except:
            raise InvalidCommandLineError("Values in a list must be separated by a comma.")


class DefaultAttributes(Enum):
    """
    Enum class containing default display attributes for various flags
    """

    device = ["Location", "Capacity", "Status", "DIMMStatus", "Life", "FWVersion"]
    config = ["Location", "VolatileSize", "PmemSize", "PmemInterleaved"]
    summary = ["TotalCapacity", "TotalVolatileSize", "TotalPmemSize"]
    logical = ["PmemSize", "DimmIds"]


def get_default_attributes(flag):
    """
    This method returns default attributes to be displayed
    :param flag: name of flag
    :type flag: string
    :return: list of default attributes for the passed flag
    """
    if flag == "device":
        return list(DefaultAttributes.device.value)
    if flag == "config":
        return list(DefaultAttributes.config.value)
    if flag == "logical":
        return list(DefaultAttributes.logical.value)
    if flag == "summary":
        return list(DefaultAttributes.summary.value)
    return []


class ShowPmemCommand:
    """Command to display information about Persistent Memory modules"""

    def __init__(self):
        self.ident = {
            "name": "showpmm",
            "usage": None,
            "description": "Display information about " "Persistent Memory modules \n\texample: showpmm --device",
            "summary": "Display information about Persistent Memory modules.",
            "aliases": [],
            "auxcommands": [],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()
        self._display_helpers = DisplayHelpers()
        self._mapper = Mapper()
        self._pmem_helpers = PmemHelpers()

    def show_pmem_modules(self, options):
        """
        Command to display information about Persistent Memory modules
        :param options: command options
        :type options: options.
        """
        # Retrieving memory collection resources
        if options.logical or options.config:
            memory, domain_members, all_chunks = RestHelpers(rdmcObject=self.rdmc).retrieve_mem_and_mem_domains()
            if not domain_members:
                raise NoContentsFoundForOperationError("Failed to retrieve Memory " "Domain resources")
        else:
            memory = RestHelpers(rdmcObject=self.rdmc).retrieve_memory_resources()

        if memory:
            memory_members = memory.get("Members")
        else:
            raise NoContentsFoundForOperationError("Failed to retrieve Memory Resources")

        # Get dimm ids of all memory objects
        member_dimm_ids = set()
        for member in memory_members:
            member_dimm_ids.add(member.get("DeviceLocator"))

        # Filtering Persistent Memory members
        pmem_members, pmem_dimm_ids = self._pmem_helpers.get_pmem_members(memory_members)
        if not pmem_members:
            raise NoContentsFoundForOperationError("No Persistent Memory Modules found")

        parsed_dimm_ids = list()
        if options.dimm:
            parsed_dimm_ids = self._pmem_helpers.parse_dimm_id(options.dimm)

        for dimm_id in parsed_dimm_ids:
            if dimm_id not in member_dimm_ids:
                raise InvalidCommandLineError("One or more of the specified " "DIMM ID(s) are invalid")
            elif dimm_id not in pmem_dimm_ids:
                raise InvalidCommandLineError(
                    "One or more of the specified DIMM ID(s) " "are not Persistent Memory Modules"
                )

        # Creating a list of persistent memory members according to specified DIMM Ids
        selected_pmem_members = list()
        if parsed_dimm_ids:
            for pmem_member in pmem_members:
                if pmem_member.get("DeviceLocator") in parsed_dimm_ids:
                    selected_pmem_members.append(pmem_member)
        else:
            selected_pmem_members = pmem_members

        # Call 'show_pmem_module_device()' when either the user specifies '--device' flag
        # or specifies no flag at all
        if (
            not options.device and not options.config and not options.logical and not options.summary
        ) or options.device:
            self.show_pmem_module_device(selected_pmem_members, options)

        elif options.config:
            self.show_pmem_module_configuration(selected_pmem_members, all_chunks, options)

        elif options.summary:
            self.show_pmem_module_summary(selected_pmem_members, options)

        elif options.logical:
            if not all_chunks:
                self.rdmc.ui.printer("No Persistent Memory regions found\n\n")
                return
            self.show_persistent_interleave_sets(selected_pmem_members, all_chunks, options)

    def generate_display_output(self, members, options, flag, mapping_table, **resources):
        """
        :param members: list of members returned as a result of GET request
        :type members: list of dictionaries
        :param options: command options
        :type options: options
        :param mapping_table: Mapping table to be used to extract attributes
        :param flag: name of flag
        :type flag: string
        :return: filtered list of dictionaries to be sent to Display Helpers for output
        """
        display_output_list = list()
        # use default attributes for now
        display_attributes = get_default_attributes(flag)

        for member in members:
            temp_dict = self._mapper.get_multiple_attributes(
                member, display_attributes, mapping_table, output_as_json=options.json, **resources
            )
            display_output_list.append(temp_dict)
        return display_output_list

    def show_pmem_module_device(self, selected_pmem_members, options):
        """
        Command to display information about DIMMs when the
        '--device' | '-D' flag is specified
        :param selected_pmem_members: pmem members to be displayed
        :type selected_pmem_members: list
        :param options: command options
        :type options: options
        """
        # generating the data to be printed
        display_output = self.generate_display_output(
            selected_pmem_members, options, "device", MappingTable.device.value
        )
        # Displaying output based on --json flag
        if options.json:
            self._display_helpers.display_data(display_output, OutputFormats.json)
        else:
            self._display_helpers.display_data(display_output, OutputFormats.table)

    def show_pmem_module_configuration(self, selected_pmem_members, all_chunks, options=None):
        """
        Command to display information about DIMMs when the
        '--pmmconfig' | '-C' flag is specified
        :param selected_pmem_members: pmem members to be displayed
        :type selected_pmem_members: list
        :param all_chunks: list of memory chunks
        :type all_chunks: list
        :param options: command options
        :type options: options
        """
        # generating the data to be printed
        display_output = self.generate_display_output(
            selected_pmem_members,
            options,
            "config",
            MappingTable.config.value,
            chunks=all_chunks,
        )
        # Displaying output based on --json flag
        if options.json:
            self._display_helpers.display_data(display_output, OutputFormats.json)
        else:
            self._display_helpers.display_data(display_output, OutputFormats.table)

    def show_persistent_interleave_sets(self, selected_pmem_members, all_chunks, options=None):
        """
        Command to display information about the Persistent interleave
        regions among the Persistent Memory Modules when the '--logical' | '-L' flag is
        specified
        :param selected_pmem_members: list of memory members retrieved via GET request
        :type selected_pmem_members: list
        :param all_chunks: list of memory chunks
        :type all_chunks: list
        :param options: command options
        :type options: options
        """
        # generating the data to be printed
        display_output = self.generate_display_output(
            all_chunks,
            options,
            "logical",
            MappingTable.logical.value,
            memory=selected_pmem_members,
        )
        # Displaying output based on --json flag
        if options.json:
            self._display_helpers.display_data(display_output, OutputFormats.json)
        else:
            self.rdmc.ui.printer("\nInterleave Persistent Memory regions\n")
            self._display_helpers.display_data(display_output, OutputFormats.table)

    def show_pmem_module_summary(self, selected_pmem_members, options=None):
        """
        Command to display a summary of the current Persistent Memory
        configuration when the '--summary' | '-M' flag is specified
        :param selected_pmem_members: list of memory members retrieved via GET request
        :type selected_pmem_members: list
        :param options: command options
        :type options: options
        """
        # getting default attributes for --summary flag
        attribute_list = get_default_attributes("summary")
        # generating the data to be printed
        display_output = self._mapper.get_multiple_attributes(
            selected_pmem_members,
            attribute_list,
            MappingTable.summary.value,
            options.json,
        )
        # Displaying output based on --json flag
        if options.json:
            self._display_helpers.display_data(display_output, OutputFormats.json)
        else:
            self._display_helpers.print_properties([display_output])

    def run(self, line, help_disp=False):
        """
        Wrapper function for new command main function
        :param line: command line input
        :type line: string.
        :param help_disp: display help flag
        :type line: bool.
        """
        if help_disp:
            self.parser.print_help()
            return ReturnCodes.SUCCESS
        LOGGER.info("PMM: %s", self.ident["name"])
        try:
            (options, args) = self.rdmc.rdmc_parse_arglist(self, line)
        except (InvalidCommandLineErrorOPTS, SystemExit):
            if ("-h" in line) or ("--help" in line):
                return ReturnCodes.SUCCESS
            else:
                raise InvalidCommandLineError("Failed to parse options")

        self.rdmc.login_select_validation(self, options)

        if args:
            self.validate_args(options)
        self.validate_show_pmem_options(options)
        # Raise exception if server is in POST
        if RestHelpers(rdmcObject=self.rdmc).in_post():
            raise NoContentsFoundForOperationError(
                "Unable to retrieve resources - " "server might be in POST or powered off"
            )
        self.show_pmem_modules(options)

        return ReturnCodes.SUCCESS

    @staticmethod
    def validate_args(options):
        """
        Produces relevant error messages when unwanted extra arguments are specified with flags
        """
        some_flag = options.device or options.config or options.logical or options.summary
        if options.logical or options.summary:
            raise InvalidCommandLineError("Chosen flag doesn't expect additional arguments")
        elif (options.device or options.config or not some_flag) and not options.dimm:
            raise InvalidCommandLineError("Use the '--dimm | -I' flag to filter by DIMM IDs")
        elif (options.device or options.config or not some_flag) and options.dimm:
            raise InvalidCommandLineError("Values in a list must be comma-separated " "(no spaces)")

    @staticmethod
    def validate_show_pmem_options(options):
        """
        Validate whether options specified by user are valid
        :param options: options specified by the user with the 'showpmm' command
        :type options: instance of OptionParser class
        """
        # Usage/Error strings
        usage_multiple_flags = (
            "Only one of '--device | -D', '--pmmconfig | -C', " "'--logical | -L' or '--summary | -M' may be specified"
        )
        # usage_all_display = "Only one of '--all | -a' or '--display | -d' may be specified\n"
        usage_dimm_flag = (
            "'--dimm | -I' can only be specified  with either the "
            "'--device | -D' or '--pmmconfig | -C' flag\n"
            " or without any flag"
        )
        error_dimm_format = "DIMM IDs should be of the form 'ProcessorNumber@SlotNumber'"
        error_dimm_range = "One or more of the specified DIMM ID(s) are invalid"

        views = [options.device, options.config, options.logical, options.summary]

        if (options.logical or options.summary) and options.dimm:
            raise InvalidCommandLineError(usage_dimm_flag)

        if views.count(False) < 3:
            raise InvalidCommandLineError(usage_multiple_flags)

        if options.dimm:
            for dimm_id in options.dimm:
                # Regex match test for expressions of type 'num1@num2'
                if not re.match(r"^\d+\@\d+$", dimm_id):
                    raise InvalidCommandLineError(error_dimm_format)
                # Accepts expressions from '1@1' to '9@19'
                if not re.match(r"^[1-9]\@([1-9]|[1]\d)$", dimm_id):
                    raise InvalidCommandLineError(error_dimm_range)

    def definearguments(self, customparser):
        """
        Wrapper function for new command main function
        :param customparser: command line input
        :type customparser: parser.
        """
        if not customparser:
            return

        self.cmdbase.add_login_arguments_group(customparser)

        customparser.add_argument(
            "-j",
            "--json",
            action="store_true",
            dest="json",
            help="Optionally include this flag to change the output to JSON format.",
            default=False,
        )

        customparser.add_argument(
            "-D",
            "--device",
            action="store_true",
            default=False,
            dest="device",
            help="Show information about the physical persistent memory modules."
            " Default view shows information about all PMMs."
            " To filter DIMMs, use this flag in conjunction with"
            " the --dimm flag.",
        )

        customparser.add_argument(
            "-C",
            "--pmmconfig",
            action="store_true",
            default=False,
            dest="config",
            help="Show the current configuration of the persistent memory modules."
            " Default view shows information about all PMMs."
            " To filter DIMMs, use this flag in conjunction with"
            " the --dimm flag.",
        )

        customparser.add_argument(
            "-L",
            "--logical",
            action="store_true",
            default=False,
            dest="logical",
            help="Show the Persistent Memory Regions.",
        )

        customparser.add_argument(
            "-M",
            "--summary",
            action="store_true",
            default=False,
            dest="summary",
            help="Show the summary of the persistent memory resources.",
        )

        customparser.add_argument(
            "-I",
            "--dimm",
            type=str,
            action=_Parse_Options_List,
            metavar="IDLIST",
            nargs=1,
            dest="dimm",
            help=" To view specific devices, supply a comma-separated list"
            " of DIMM IDs in the format P@S (without spaces),"
            " where P=processor and S=slot. Example: '1@1,1@12'",
        )
