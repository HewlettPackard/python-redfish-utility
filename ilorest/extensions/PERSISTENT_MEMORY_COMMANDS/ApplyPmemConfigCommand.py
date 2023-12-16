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
"""Command to apply a pre-defined configuration to PMM"""
from __future__ import absolute_import

from copy import deepcopy

try:
    from rdmc_helper import (
        LOGGER,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        NoChangesFoundOrMadeError,
        NoContentsFoundForOperationError,
        ReturnCodes,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        ReturnCodes,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        LOGGER,
        NoChangesFoundOrMadeError,
        NoContentsFoundForOperationError,
    )

from .lib.DisplayHelpers import DisplayHelpers
from .lib.RestHelpers import RestHelpers


class ApplyPmemConfigCommand:
    """
    Command to apply a pre-defined configuration to PMM
    """

    # Available configIDs
    config_ids = [
        {
            "name": "MemoryMode",
            "description": "Configure all the PMMs to 100% Memory Mode.",
            "totalPmemPercentage": 0,
            "pmemIntereleaved": False,
        },
        {
            "name": "PmemInterleaved",
            "description": "Configure all PMMs to 100% Persistent. "
            "Interleave the Persistent memory regions within each processor.",
            "totalPmemPercentage": 100,
            "pmemIntereleaved": True,
        },
        {
            "name": "PmemNotInterleaved",
            "description": "Configure all PMMs to 100% Persistent. "
            "The Persistent memory regions are not interleaved.",
            "totalPmemPercentage": 100,
            "pmemIntereleaved": False,
        },
    ]

    def __init__(self):
        self.ident = {
            "name": "applypmmconfig",
            "usage": None,
            "description": "Applies a pre-defined configuration to PMM\n"
            "\texample: applypmmconfig --pmmconfig MemoryMode\n",
            "summary": "Applies a pre-defined configuration to PMM.",
            "aliases": [],
            "auxcommands": [
                "ShowPmemPendingConfigCommand",
                "ClearPendingConfigCommand",
            ],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

        self._display_helpers = DisplayHelpers()

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
            "-C",
            "--pmmconfig",
            action="store",
            type=str,
            dest="config",
            help="Specify one of the pre-defined configIDs to apply" " to all Persistent Memory Modules.",
            default=None,
        )

        customparser.add_argument(
            "-L",
            "--list",
            action="store_true",
            dest="list",
            help="Display a list of available pre-defined configIDs" " along with a brief description.",
            default=False,
        )

        customparser.add_argument(
            "-f",
            "--force",
            action="store_true",
            dest="force",
            help="Allow the user to force the configuration " "by automatically accepting any prompts.",
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
        LOGGER.info("PMM Apply Pre-Defined Configuration: %s", self.ident["name"])
        try:
            (options, args) = self.rdmc.rdmc_parse_arglist(self, line)
        except (InvalidCommandLineErrorOPTS, SystemExit):
            if ("-h" in line) or ("--help" in line):
                return ReturnCodes.SUCCESS
            else:
                raise InvalidCommandLineError("Failed to parse options")
        if args:
            self.validate_args(options)
        self.validate_options(options)
        self.apply_pmm_config(options)

        self.cmdbase.logout_routine(self, options)
        # Return code
        return ReturnCodes.SUCCESS

    @staticmethod
    def validate_args(options):
        """
        Produces relevant error messages when unwanted extra arguments are specified with flags.
        """
        if options.config:
            raise InvalidCommandLineError("'config | -C' expects a single argument")
        else:
            raise InvalidCommandLineError("Chosen flag doesn't expect additional arguments")

    def validate_options(self, options):
        """
        Validate whether options specified by user are valid.
        :param options: options specified by the user.
        :type options: instance of OptionParser class.
        """
        # Set of valid configIDs
        valid_config_ids = {config_id.get("name").lower() for config_id in self.config_ids}

        if not options.config and not options.list and not options.force:
            raise InvalidCommandLineError("No flag specified.\n\nUsage: " + self.ident["usage"])
        if not options.config and options.force:
            raise InvalidCommandLineError("'--force | -f' flag mandatorily requires the " "'--pmmconfig | -C' flag.")
        if options.config and options.list:
            raise InvalidCommandLineError("Only one of '--pmmconfig | -C' or '--list | -L' " "may be specified")
        # Check whether the user entered configID is valid
        if options.config and not options.config.lower() in valid_config_ids:
            raise InvalidCommandLineError(
                "Invalid configID.\nTo view a list of pre-defined " "configIDs, use 'applypmmconfig --list'"
            )

    def apply_pmm_config(self, options):
        """
        Calls relevant functions based on the flags specified by the user.
        :param options: options specified by the user.
        :type options: instance of OptionParser class.
        """
        if options.list:
            self.show_predefined_config_options()
        elif options.config:
            # Raise exception if server is in POST
            if RestHelpers(rdmcObject=self.rdmc).in_post():
                raise NoContentsFoundForOperationError(
                    "Unable to retrieve resources - " "server might be in POST or powered off"
                )
            self.apply_predefined_config(options)

    def show_predefined_config_options(self):
        """
        Display the available pre-defined configIDs that the user can choose from to
        apply to their Persistent memory Modules.
        """
        self.rdmc.ui.printer("\nAvailable Configurations:\n\n")
        for config_id in ApplyPmemConfigCommand.config_ids:
            self.rdmc.ui.printer(config_id.get("name") + "\n")
            self.rdmc.ui.printer("\t" + config_id.get("description") + "\n")
        self.rdmc.ui.printer("\n")

    def warn_existing_chunks_and_tasks(self, memory_chunk_tasks, memory_chunks):
        """
        Checks for existing Memory Chunks and Pending Configuration Task resources on
        a server where a user is trying to apply a pre-defined configuration
        :param memory_chunk_tasks: Pending Configuration Tasks
        :type memory_chunk_tasks: list
        :memory_chunks: Memory Chunks in the existing configuration
        :type memory_chunks: list
        :returns: None
        """
        # If Memory Chunks exist, display Existing configuration warning
        if memory_chunks:
            self.rdmc.ui.printer(
                "Warning: Existing configuration found. Proceeding with applying a new "
                "configuration will result in overwriting the current configuration and "
                "cause data loss.\n"
            )
        # If Pending Configuration Tasks exist, display warning
        if memory_chunk_tasks:
            self.rdmc.ui.printer(
                "Warning: Pending configuration tasks found. Proceeding with applying "
                "a new configuration will result in overwriting the pending "
                "configuration tasks.\n"
            )
        # Raise a NoChangesFoundOrMade exception when either of the above conditions exist
        if memory_chunks or memory_chunk_tasks:
            # Line feed for proper formatting
            raise NoChangesFoundOrMadeError(
                "\nFound one or more of Existing Configuration or "
                "Pending Configuration Tasks. Please use the "
                "'--force | -f' flag with the same command to "
                "approve these changes."
            )
        return None

    def delete_existing_chunks_and_tasks(self, memory_chunk_tasks, memory_chunks):
        """
        Delete existing Memory Chunks and Pending Configuration Tasks
        :param memory_chunk_tasks: Pending Configuration Tasks
        :type memory_chunk_tasks: list
        :memory_chunks: Memory Chunks in the existing configuration
        :type memory_chunks: list
        :returns: None
        """
        # Delete any pending configuration tasks
        if memory_chunk_tasks:
            self.auxcommands["clearpmmpendingconfig"].delete_tasks(memory_chunk_tasks)
        # Delete any existing configuration
        if memory_chunks:
            for chunk in memory_chunks:
                data_id = chunk.get("@odata.id")
                resp = RestHelpers(rdmcObject=self.rdmc).delete_resource(data_id)
                if not resp:
                    raise NoChangesFoundOrMadeError("Error occured while deleting " "existing configuration")
        return None

    @staticmethod
    def get_post_data(config_data, interleavable_memory_sets):
        """
        Create post body based on config data
        :param config_data: An entry of self.config_iD's list
        :type config_data: dict
        :param interleavable_memory_sets: List of interleavable sets
        :type interleavable_memory_sets: List
        :returns: Returns post data
        """

        body = {
            "AddressRangeType": "PMEM",
            "InterleaveSets": [],
            "Oem": {"Hpe": {"MemoryChunkSizePercentage": config_data["totalPmemPercentage"]}},
        }
        # Get the list of interleave sets based on the configuration
        if config_data["pmemIntereleaved"] or config_data["totalPmemPercentage"] == 0:
            # If pmem regions are interleaved or if it MemoryMode, choose the list with maximum entries.
            interleave_sets = [max(interleavable_memory_sets, key=lambda x: len(x["MemorySet"]))]
        else:
            # If pmem regions are NOT interleaved, choose all the lists with exactly one entry.
            interleave_sets = [il_set for il_set in interleavable_memory_sets if len(il_set["MemorySet"]) == 1]

        # Using in-place update to change the interleave sets format.
        # Replace 'MemorySet' with 'Memory' for each MemorySet in interleave_sets.
        # Get '@odata.id' for each memory region from original interleave_sets and add this to new structure.
        for index, interleavableset in enumerate(interleave_sets):
            interleave_sets[index] = [
                {"Memory": {"@odata.id": str(memory_region["@odata.id"])}}
                for memory_region in interleavableset["MemorySet"]
            ]

        # Create post body for each interleave sets from post body template.
        post_data = []
        for interleaveset in interleave_sets:
            current_body = deepcopy(body)
            current_body["InterleaveSets"] = interleaveset
            post_data.append(current_body)

        return post_data

    def apply_predefined_config(self, options):
        """
        Apply the selected pre-defined configuration to Persistent Memory Modules.
        :param options: option specified by the user.
        :returns: None
        """
        # Retrieve Memory Chunks and Task Resources from server
        (task_members, domain_members, memory_chunks) = RestHelpers(
            rdmcObject=self.rdmc
        ).retrieve_task_members_and_mem_domains()

        # Filter Task Resources to include only Pending Configuration Tasks
        memory_chunk_tasks = RestHelpers(rdmcObject=self.rdmc).filter_task_members(task_members)

        if options.force:
            self.delete_existing_chunks_and_tasks(memory_chunk_tasks, memory_chunks)
        else:
            self.warn_existing_chunks_and_tasks(memory_chunk_tasks, memory_chunks)

        if not domain_members:
            raise NoContentsFoundForOperationError("Failed to retrive Memory Domain Resources")

        # Get the user specified configID
        config_data = next(
            (config_id for config_id in self.config_ids if config_id.get("name").lower() == options.config.lower()),
            None,
        )

        for proc in domain_members:
            path = proc["MemoryChunks"].get("@odata.id")
            data = self.get_post_data(config_data, proc["InterleavableMemorySets"])
            for body in data:
                resp = RestHelpers(rdmcObject=self.rdmc).post_resource(path, body)
                if resp is None:
                    raise NoChangesFoundOrMadeError("Error occured while applying configuration")

        # display warning
        self.rdmc.ui.printer("Configuration changes require reboot to take effect.\n")

        # display pending configuration
        self.auxcommands["showpmmpendingconfig"].show_pending_config(type("MyOptions", (object,), dict(json=False)))
