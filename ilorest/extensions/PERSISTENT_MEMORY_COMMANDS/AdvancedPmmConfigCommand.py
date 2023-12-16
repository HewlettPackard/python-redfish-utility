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
"""Command to apply specified configuration to PMM"""
from __future__ import absolute_import  # verify if python3 libs can handle

from argparse import Action
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

from .lib.RestHelpers import RestHelpers


class _ParseOptionsList(Action):
    def __init__(self, option_strings, dest, nargs, **kwargs):
        super(_ParseOptionsList, self).__init__(option_strings, dest, nargs, **kwargs)

    def __call__(self, parser, namespace, values, option_strings):
        """
        Callback to parse a comma-separated list into an array.
        Then store the array in the option's destination
        """
        try:
            setattr(namespace, self.dest, next(iter(values)).split(","))
        except:
            raise InvalidCommandLineError("Values in a list must be separated by a comma.")


class AdvancedPmmConfigCommand:
    """
    Command to apply specified configuration to PMM
    """

    def __init__(self):
        self.ident = {
            "name": "provisionpmm",
            "usage": None,
            "description": "Applies specified configuration to PMM.\n" "\texample: provisionpmm -m 50 -i On -pid 1,2",
            "summary": "Applies specified configuration to PMM.",
            "aliases": ["provisionpmm"],
            "auxcommands": [
                "ShowPmemPendingConfigCommand",
                "ClearPendingConfigCommand",
            ],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()
        self._rest_helpers = RestHelpers(rdmcObject=self.rdmc)

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

        if args:
            self.validate_args(args, options)
        self.validate_options(options)
        # Raise exception if server is in POST
        if self._rest_helpers.in_post():
            raise NoContentsFoundForOperationError(
                "Unable to retrieve resources - " "server might be in POST or powered off"
            )
        self.configure_pmm(options)

        return ReturnCodes.SUCCESS

    @staticmethod
    def validate_args(args, options):
        """
        Produces relevant error messages when unwanted
        extra arguments are specified with flags.
        """
        error_message = (
            "Chosen flag is invalid. Use the '-m | --memory-mode'" " flag to specify the size in percentage."
        )
        some_flag = options.memorymode or options.interleave or options.proc or options.force

        case_a = options.force and not options.memorymode and not options.interleave and not options.proc
        case_b = options.interleave and not options.memorymode and not options.force and not options.proc
        case_c = options.proc and not options.memorymode and not options.force and not options.interleave
        case_d = options.memorymode and not options.proc and not options.interleave and not options.force

        if case_a or case_b or case_c:
            raise InvalidCommandLineError(error_message)
        if case_d or (some_flag not in args):
            raise InvalidCommandLineError("Chosen flag is Invalid")

    def validate_options(self, options):
        """
        Validate whether options specified by user are valid or not
        :param options: options specified by the user with the 'provisionpmm' command
        :type options: instance of OptionParser class
        """
        some_flag = options.memorymode or options.interleave or options.proc or options.force
        if not some_flag:
            raise InvalidCommandLineError("No flag specified.\n\nUsage: " + self.ident["usage"])

        # If the memory mode option value is not valid.
        resp = self._rest_helpers.retrieve_model(self.rdmc)
        model = resp["Model"]

        if "Gen10 Plus" in model:
            if not (options.memorymode == 0 or options.memorymode == 100):
                raise InvalidCommandLineError("Specify the correct value (0 or 100)" " to configure PMM")
        else:
            if options.memorymode < 0 or options.memorymode > 100:
                raise InvalidCommandLineError("Specify the correct value (1-100)" " to configure PMM")
        if options.interleave:
            if options.interleave.lower() not in ["on", "off"]:
                raise InvalidCommandLineError(
                    "Specify the correct value to set interleave"
                    " state of persistent memory regions\n\n" + self.ident["usage"]
                )
            options.interleave = options.interleave.lower()

        if options.proc and not options.memorymode and not options.interleave:
            raise InvalidCommandLineError(
                "Use '-m|--memory-mode' flag to specify the size in percentage"
                " or '-i|--pmem-interleave' flag to set interleave"
                " state of persistent memory regions"
            )

        # If not 100% memorymode, -i flag is mandatory to interleave memroy regions.
        if 0 <= options.memorymode < 100 and not options.interleave:
            raise InvalidCommandLineError(
                "Use '-i | --pmem-interleave' flag to" " specify the interleave state of persistent" " memory regions"
            )
        if options.proc:
            for proc_id in options.proc:
                if not proc_id.isdigit():
                    raise InvalidCommandLineError("Specify the correct processor id")

    def definearguments(self, customparser):
        """
        Wrapper function for new command main function
        :param customparser: command line input
        :type customparser: parser
        """
        if not customparser:
            return

        self.cmdbase.add_login_arguments_group(customparser)

        customparser.add_argument(
            "-m",
            "--memory-mode",
            dest="memorymode",
            type=int,
            help="Percentage of the total capacity to configure all PMMs to MemoryMode."
            " This flag is optional. If not specified,"
            " by default configuration will be applied with 0%% Volatile."
            " To interleave persistent memory regions, use this flag in conjunction with"
            " the --pmem-interleave flag. To configure all the PMMs on specific processor,"
            " use this flag in conjunction with the --proc flag.",
            default=0,
        )

        customparser.add_argument(
            "-i",
            "--pmem-interleave",
            dest="interleave",
            help="Indicates whether the persistent memory regions should be interleaved or not.",
            default=None,
        )

        customparser.add_argument(
            "-pid",
            "--proc",
            nargs=1,
            action=_ParseOptionsList,
            dest="proc",
            help="To apply selected configuration on specific processors, "
            "supply a comma-separated list of Processor IDs (without spaces) where "
            "p=processor id. This flag is optional. If not specified, "
            "by default configuration will be applied to all the Processors.",
        )

        customparser.add_argument(
            "-f",
            "--force",
            action="store_true",
            dest="force",
            help="Allow the user to force the configuration " "by automatically accepting any prompts.",
            default=False,
        )

    @staticmethod
    def warn_existing_chunks_and_tasks(self, memory_chunk_tasks, memory_chunks):
        """
        Checks for existing Memory Chunks and Pending Configuration Task resources on
        a server where a user is trying to selected configuration
        :param memory_chunk_tasks: Pending Configuration Tasks
        :type memory_chunk_tasks: list
        :memory_chunks: Memory Chunks in the existing configuration
        :type memory_chunks: list
        :returns: None
        """
        # If Memory Chunks exist, display Existing configuration warning
        if memory_chunks:
            self.rdmc.ui.warn(
                "Existing configuration found. Proceeding with applying a new "
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
                resp = self._rest_helpers.delete_resource(data_id)
                if not resp:
                    raise NoChangesFoundOrMadeError("Error occurred while deleting " "existing configuration")
        return None

    @staticmethod
    def get_valid_processor_list(input_proc_list, domain_members):
        """
        Function to check processors specified by user are valid or not
        :param domain_members: Memory Resources
        :type input_proc_list: List
        :type domain_members: Dict
        :returns: List of valid processors in string format (ex: [PROC1MemoryDomain])
        """
        proc_list = []
        index = 0
        invalid_proc_list = []
        # Create list with valid processors based on 'Id' attribute.
        for member in domain_members:
            proc_list.append(member["Id"])

        for index, proc_id in enumerate(input_proc_list):
            temp_proc_id = "PROC" + str(proc_id) + "MemoryDomain"
            if temp_proc_id not in proc_list:
                invalid_proc_list.append(proc_id)
            else:
                input_proc_list[index] = temp_proc_id

        # Raise execption if given proc id is not exist.
        if invalid_proc_list:
            if len(invalid_proc_list) == 1:
                raise NoChangesFoundOrMadeError(
                    "Specified processor number {proc_list} is invalid".format(proc_list=invalid_proc_list[0])
                )
            else:
                raise NoChangesFoundOrMadeError(
                    "Specified processor numbers {proc_list} are invalid".format(proc_list=",".join(invalid_proc_list))
                )

        return input_proc_list

    @staticmethod
    def filter_memory_chunks(memory_chunks, domain_members, proc_list):
        """
        Filter memory chunks based on specified processor list
        :param memory_chunks: list of all memory chunks
        :param domain_members: dict of memory resources
        :param proc list: List of specified processors
        :Retrun: List of memory chunks corresponding to specified processors
        """
        all_chunks = list()
        for member in domain_members:
            proc_id = member["Id"]
            if not proc_list or (proc_id in proc_list):
                data_id = member.get("MemoryChunks").get("@odata.id")
                all_chunks += [chunk for chunk in memory_chunks if data_id in chunk.get("@odata.id")]

        return all_chunks

    @staticmethod
    def get_post_data(config_data, interleavable_memory_sets):
        """
        Create post body based on config data
        :param config_data: dict with user input
        :type config_data: dict
        :param interleavable_memory_sets: List of interleavable sets
        :type interleavable_memory_sets: List
        :returns: Returns post data
        """

        body = {
            "AddressRangeType": "PMEM",
            "InterleaveSets": [],
            "Oem": {"Hpe": {"MemoryChunkSizePercentage": 100 - config_data["size"]}},
        }
        # Get the list of interleave sets based on the configuration
        if config_data["pmeminterleave"] == "on" or config_data["size"] == 100:
            # If persistent memory regions are interleaved or if it's 100% MemoryMode,
            # choose the list with maximum entries.
            interleave_sets = [max(interleavable_memory_sets, key=lambda x: len(x["MemorySet"]))]
        else:
            # If persistent memory regions are not interleaved,
            # choose all the lists with exactly one entry.
            interleave_sets = [il_set for il_set in interleavable_memory_sets if len(il_set["MemorySet"]) == 1]

        # Using in-place update to change the interleave sets format.
        # Replace 'MemorySet' with 'Memory' for each MemorySet in interleave_sets.
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

    def configure_pmm(self, options):
        """
        Applies selected configuration to the PMMs
        :param options: options specified by user
        :returns: None
        """
        # Retrieve Memory Chunks and Task Resources from server.
        (
            task_members,
            domain_members,
            memory_chunks,
        ) = self._rest_helpers.retrieve_task_members_and_mem_domains()

        # Filter Task Resources to include only Pending Configuration Tasks.
        memory_chunk_tasks = self._rest_helpers.filter_task_members(task_members)

        if not domain_members:
            raise NoContentsFoundForOperationError(
                "Failed to retrieve Memory Domain Resources, please check if persistent memory is present/configured"
            )

        # Dict with input config data
        config_data = {
            "size": options.memorymode,
            "pmeminterleave": options.interleave,
            "proc": options.proc,
        }
        # Check for given processor id list is valid or not.
        if options.proc:
            config_data["proc"] = self.get_valid_processor_list(config_data["proc"], domain_members)
            memory_chunks = self.filter_memory_chunks(memory_chunks, domain_members, config_data["proc"])

        # In case of 100% Volatile, Interleaving memory regions is not applicable.
        if (
            config_data["size"] == 100
            and config_data["pmeminterleave"]
            and config_data["pmeminterleave"].lower() == "on"
        ):
            raise InvalidCommandLineError(
                "Selected configuration is invalid. " "Interleaving not supported in 100% volatile."
            )

        if options.force:
            self.delete_existing_chunks_and_tasks(memory_chunk_tasks, memory_chunks)
        else:
            self.warn_existing_chunks_and_tasks(self, memory_chunk_tasks, memory_chunks)

        for member in domain_members:
            proc_id = member["Id"]
            # If given proc list is not empty, applies configuration to selected processors
            if not config_data["proc"] or (proc_id in config_data["proc"]):
                path = member["MemoryChunks"].get("@odata.id")
                data = self.get_post_data(config_data, member["InterleavableMemorySets"])
                for body in data:
                    resp = self._rest_helpers.post_resource(path, body)
                if resp is None:
                    raise NoChangesFoundOrMadeError("Error occurred while applying configuration")

        # Display warning
        self.rdmc.ui.printer("\nConfiguration changes require reboot to take effect.\n")

        # Display pending configuration
        self.auxcommands["showpmmpendingconfig"].show_pending_config(type("MyOptions", (object,), dict(json=False)))
        return None
