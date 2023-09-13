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
"""Command to show recommended configurations"""
from __future__ import absolute_import, division

from collections import OrderedDict

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


class ShowRecommendedConfigCommand:
    """Show recommended configurations"""

    def __init__(self):
        self.ident = {
            "name": "showrecommendedpmmconfig",
            "usage": None,
            "description": "Show recommended configurations\n" "\texample: showrecommendedpmmconfig",
            "summary": "Show Recommended Configuration",
            "aliases": [],
            "auxcommands": [],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()
        self._display_helpers = DisplayHelpers()
        self._mapper = Mapper()
        self._pmem_helpers = PmemHelpers()

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
        LOGGER.info("Show Recommended Configuration: %s", self.ident["name"])
        try:
            (_, args) = self.rdmc.rdmc_parse_arglist(self, line)
        except (InvalidCommandLineErrorOPTS, SystemExit):
            if ("-h" in line) or ("--help" in line):
                return ReturnCodes.SUCCESS
            else:
                raise InvalidCommandLineError("Failed to parse options")
        if args:
            raise InvalidCommandLineError("Chosen command doesn't expect additional arguments")
        # Raise exception if server is in POST
        if RestHelpers(rdmcObject=self.rdmc).in_post():
            raise NoContentsFoundForOperationError(
                "Unable to retrieve resources - " "server might be in POST or powered off"
            )
        self.show_recommended_config()

        return ReturnCodes.SUCCESS

    def show_recommended_config(self):
        """
        Show recommended pmm configuration
        """
        members = RestHelpers(rdmcObject=self.rdmc).retrieve_memory_resources().get("Members")

        if not members:
            raise NoContentsFoundForOperationError("Failed to retrieve memory resources")

        # Retreving dimms
        pmem_members = self._pmem_helpers.get_pmem_members(members)[0]

        if not pmem_members:
            raise NoContentsFoundForOperationError("No Persistent Memory Modules found")

        # Retreving dram dimms
        dram_members = self._pmem_helpers.get_non_aep_members(members)[0]

        if not dram_members:
            raise NoContentsFoundForOperationError("No DRAM DIMMs found")

        # retrieving Total Capacity of PMEM dimms
        attr = self._mapper.get_single_attribute(pmem_members, "TotalCapacity", MappingTable.summary.value, True)
        pmem_size = attr.get("TotalCapacity", {}).get("Value", 0)

        # retrieving Total Capacity of DRAM dimms
        dram_size = self._mapper.get_single_attribute(dram_members, "TotalCapacity", MappingTable.summary.value, True)
        dram_size = dram_size.get("TotalCapacity", {}).get("Value", 0)

        display_output = list()
        recommended_config = list()

        # Add AppDirect Mode
        temp_dict = OrderedDict()
        temp_dict["MemoryModeTotalSize"] = 0
        temp_dict["PmemTotalSize"] = pmem_size
        temp_dict["CacheRatio"] = None
        recommended_config.append(temp_dict)

        # Add Memory Mode
        temp_dict = OrderedDict()
        temp_dict["MemoryModeTotalSize"] = pmem_size
        temp_dict["PmemTotalSize"] = 0
        temp_dict["CacheRatio"] = pmem_size / dram_size
        recommended_config.append(temp_dict)

        # Add Mixed Mode (BPS doesn't support it)
        if "Gen10 Plus" not in RestHelpers(rdmcObject=self.rdmc).retrieve_model(self.rdmc)["Model"]:
            stepsize = 32
            appdirect_size = 0
            step = 1
            while appdirect_size < pmem_size:
                appdirect_size = step * stepsize * len(pmem_members)
                memorymode_size = pmem_size - appdirect_size
                cache_ratio = memorymode_size / dram_size
                if 2 <= cache_ratio <= 16:
                    temp_dict = OrderedDict()
                    temp_dict["MemoryModeTotalSize"] = memorymode_size
                    temp_dict["PmemTotalSize"] = appdirect_size
                    temp_dict["CacheRatio"] = cache_ratio
                    recommended_config.append(temp_dict)
                step += 1

        # Sorting based on MemoryModeTotalSize
        recommended_config = sorted(recommended_config, key=lambda x: x["MemoryModeTotalSize"])

        # Adding units and formating cache ratio
        for output in recommended_config:
            output["MemoryModeTotalSize"] = "%d GB" % output["MemoryModeTotalSize"]
            output["PmemTotalSize"] = "%d GB" % output["PmemTotalSize"]
            if output["CacheRatio"] is None:
                output["CacheRatio"] = "N/A"
            else:
                output["CacheRatio"] = "1:%.1f" % output["CacheRatio"]
            display_output.append(self._pmem_helpers.json_to_text(output)[0])

        # Display output in table format
        self._display_helpers.display_data(display_output, OutputFormats.table)
