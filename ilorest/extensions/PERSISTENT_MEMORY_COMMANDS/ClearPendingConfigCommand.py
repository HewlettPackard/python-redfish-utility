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
"""Command to clear pending tasks"""
from __future__ import absolute_import

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
        NoContentsFoundForOperationError,
        NoChangesFoundOrMadeError,
        LOGGER,
    )

from .lib.RestHelpers import RestHelpers


class ClearPendingConfigCommand:
    """Command to clear pending config tasks"""

    def __init__(self):
        self.ident = {
            "name": "clearpmmpendingconfig",
            "usage": None,
            "description": "Clear pmm pending config tasks\n" "\texample: clearpmmpendingconfig",
            "summary": "Clear pending config tasks",
            "aliases": [],
            "auxcommands": [],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def get_memory_chunk_tasks(self):
        """
        Function to retrieve Memory Chunk Tasks
        :returns: Retrieved Memory Chunk Tasks
        """
        # Retrieving tasks members
        tasks = RestHelpers(rdmcObject=self.rdmc).retrieve_task_members()
        if tasks:
            # Filtering out Memory Chunk Tasks
            memory_chunk_tasks = RestHelpers(rdmcObject=self.rdmc).filter_task_members(tasks)
            if memory_chunk_tasks:
                return memory_chunk_tasks
        self.rdmc.ui.printer("No pending configuration tasks found.\n\n")
        return []

    def delete_tasks(self, memory_chunk_tasks, verbose=False):
        """
        Function to delete pending configuration tasks
        :param memory_chunk_tasks: Pending confguration tasks.
        :type memory_chunk_tasks: list
        :param verbose: Toggles verbose mode, which print task IDs as
                        individual tasks are deleted.
        :type verbose: Boolean
        :returns: None
        """
        for task in memory_chunk_tasks:
            data_id = task.get("@odata.id")
            task_id = task.get("Id")
            resp = RestHelpers(rdmcObject=self.rdmc).delete_resource(data_id)
            if resp:
                if verbose:
                    self.rdmc.ui.printer("Deleted Task #{}".format(task_id) + "\n")
            else:
                raise NoChangesFoundOrMadeError("Error occured while deleting " "task #{}".format(task_id))
        return None

    def run(self, line, help_disp=False):
        """
        Wrapper function for new command main function
        :param line: command line input
        :type line: string.
        """
        if help_disp:
            self.parser.print_help()
            return ReturnCodes.SUCCESS
        LOGGER.info("Clear Pending Configuration: %s", self.ident["name"])
        # pylint: disable=unused-variable
        try:
            (options, args) = self.rdmc.rdmc_parse_arglist(self, line)
        except (InvalidCommandLineErrorOPTS, SystemExit):
            if ("-h" in line) or ("--help" in line):
                return ReturnCodes.SUCCESS
            else:
                raise InvalidCommandLineError("Failed to parse options")
        if args:
            raise InvalidCommandLineError("Chosen flag doesn't expect additional arguments")
        # Raise exception if server is in POST
        if RestHelpers(rdmcObject=self.rdmc).in_post():
            raise NoContentsFoundForOperationError(
                "Unable to retrieve resources - " "server might be in POST or powered off"
            )
        memory_chunk_tasks = self.get_memory_chunk_tasks()
        self.delete_tasks(memory_chunk_tasks, verbose=True)

        return ReturnCodes.SUCCESS

    def definearguments(self, customparser):
        """
        Wrapper function for new command main function
        :param customparser: command line input
        :type customparser: parser.
        """
        if not customparser:
            return

        self.cmdbase.add_login_arguments_group(customparser)
