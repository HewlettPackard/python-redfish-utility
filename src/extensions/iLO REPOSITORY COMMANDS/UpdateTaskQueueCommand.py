# ##
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
# ##

# -*- coding: utf-8 -*-
""" Update Task Queue Command for rdmc """

from random import randint
from argparse import RawDescriptionHelpFormatter

from redfish.ris.rmc_helper import IdTokenError

try:
    from rdmc_helper import (
        IncompatibleiLOVersionError,
        ReturnCodes,
        NoContentsFoundForOperationError,
        InvalidCommandLineErrorOPTS,
        InvalidCommandLineError,
        Encryption,
        TaskQueueError,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        IncompatibleiLOVersionError,
        ReturnCodes,
        NoContentsFoundForOperationError,
        InvalidCommandLineErrorOPTS,
        InvalidCommandLineError,
        Encryption,
        TaskQueueError,
    )

__subparsers__ = ["create"]


class UpdateTaskQueueCommand:
    """Main download command class"""

    def __init__(self):
        self.ident = {
            "name": "taskqueue",
            "usage": None,
            "description": "Run to add or remove tasks from the task queue. Added tasks are "
            "appended to the end of the queue. Note: iLO 5 required.\n"
            "Example:\n\ttaskqueue create 30\n\t"
            "taskqueue create <COMP_NAME>\n\t"
            "taskqueue\n",
            "summary": "Manages the update task queue for iLO.",
            "aliases": [],
            "auxcommands": [],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """Main update task queue worker function

        :param line: string of arguments passed in
        :type line: str.
        :param help_disp: display help flag
        :type line: bool.
        """
        if help_disp:
            line.append("-h")
            try:
                (_, _) = self.rdmc.rdmc_parse_arglist(self, line)
            except:
                return ReturnCodes.SUCCESS
            return ReturnCodes.SUCCESS
        try:
            ident_subparser = False
            for cmnd in __subparsers__:
                if cmnd in line:
                    (options, args) = self.rdmc.rdmc_parse_arglist(self, line)
                    ident_subparser = True
                    break
            if not ident_subparser:
                (options, args) = self.rdmc.rdmc_parse_arglist(self, line, default=True)
                # if not line or line[0] == "help":
                #    self.parser.print_help()
                #    return ReturnCodes.SUCCESS
        except (InvalidCommandLineErrorOPTS, SystemExit):
            if ("-h" in line) or ("--help" in line):
                return ReturnCodes.SUCCESS
            else:
                raise InvalidCommandLineErrorOPTS("")

        self.updatetaskqueuevalidation(options)

        if self.rdmc.app.typepath.defs.isgen9:
            raise IncompatibleiLOVersionError(
                "iLO Repository commands are only available on iLO 5."
            )

        if options.command.lower() == "create":
            self.createtask(options.keywords, options)
        else:
            if options.resetqueue:
                self.resetqueue()
            elif options.cleanqueue:
                self.cleanqueue()
            self.printqueue(options)

        self.cmdbase.logout_routine(self, options)
        # Return code
        return ReturnCodes.SUCCESS

    def resetqueue(self):
        """Deletes everything in the update task queue"""
        tasks = self.rdmc.app.getcollectionmembers(
            "/redfish/v1/UpdateService/UpdateTaskQueue/"
        )
        if not tasks:
            self.rdmc.ui.printer("No tasks found.\n")

        self.rdmc.ui.printer("Deleting all update tasks...\n")

        for task in tasks:
            self.rdmc.ui.printer("Deleting: %s\n" % task["Name"])
            self.rdmc.app.delete_handler(task["@odata.id"])

    def cleanqueue(self):
        """Deletes all finished or errored tasks in the update task queue"""
        tasks = self.rdmc.app.getcollectionmembers(
            "/redfish/v1/UpdateService/UpdateTaskQueue/"
        )
        if not tasks:
            self.rdmc.ui.printer("No tasks found.\n")

        self.rdmc.ui.printer("Cleaning update task queue...\n")

        for task in tasks:
            if task["State"] == "Complete" or task["State"] == "Exception":
                self.rdmc.ui.printer("Deleting %s...\n" % task["Name"])
                self.rdmc.app.delete_handler(task["@odata.id"])

    def createtask(self, tasks, options):
        """Creates a task in the update task queue

        :param tasks: arguments for creating tasks
        :type tasks: list.
        :param options: command line options
        :type options: list.
        """

        tpmflag = None

        path = "/redfish/v1/UpdateService/UpdateTaskQueue/"
        comps = self.rdmc.app.getcollectionmembers(
            "/redfish/v1/UpdateService/" "ComponentRepository/"
        )
        curr_tasks = self.rdmc.app.getcollectionmembers(
            "/redfish/v1/UpdateService/UpdateTaskQueue/"
        )
        for task in tasks:
            usedcomp = None
            newtask = None

            try:
                usedcomp = int(task)
                newtask = {
                    "Name": "Wait-%s %s seconds"
                    % (str(randint(0, 1000000)), str(usedcomp)),
                    "Command": "Wait",
                    "WaitTimeSeconds": usedcomp,
                    "UpdatableBy": ["Bmc"],
                }
            except ValueError:
                pass

            if task.lower() == "reboot":
                newtask = {
                    "Name": "Reboot-%s" % str(randint(0, 1000000)),
                    "Command": "ResetServer",
                    "UpdatableBy": ["RuntimeAgent"],
                }
            elif not newtask:
                if tpmflag is None:
                    if options.tover:
                        tpmflag = True
                    else:
                        tpmflag = False
                    # TODO: Update to monolith check
                    results = self.rdmc.app.get_handler(
                        self.rdmc.app.typepath.defs.biospath, silent=True
                    )
                    if results.status == 200:
                        contents = (
                            results.dict
                            if self.rdmc.app.typepath.defs.isgen9
                            else results.dict["Attributes"]
                        )
                        tpmstate = contents["TpmState"]
                        if "Enabled" in tpmstate and not tpmflag:
                            raise IdTokenError("")

                for curr_task in curr_tasks:
                    if (
                        "Filename" in curr_task
                        and curr_task["Filename"] == task
                        and curr_task["State"].lower() != "exception"
                    ):
                        raise TaskQueueError(
                            "This file already has a task queue for flashing "
                            "associated with it. Reset the taskqueue and "
                            "retry if you need to add this task again."
                        )
                for comp in comps:
                    if comp["Filename"] == task:
                        usedcomp = comp
                        break

                if not usedcomp:
                    raise NoContentsFoundForOperationError(
                        "Component " "referenced is not present on iLO Drive: %s" % task
                    )

                newtask = {
                    "Name": "Update-%s %s"
                    % (
                        str(randint(0, 1000000)),
                        usedcomp["Name"].encode("ascii", "ignore"),
                    ),
                    "Command": "ApplyUpdate",
                    "Filename": usedcomp["Filename"],
                    "UpdatableBy": usedcomp["UpdatableBy"],
                    "TPMOverride": tpmflag,
                }

            self.rdmc.ui.printer('Creating task: "%s"\n' % newtask["Name"])

            self.rdmc.app.post_handler(path, newtask)

    def printqueue(self, options):
        """Prints the update task queue

        :param options: command line options
        :type options: list.
        """
        tasks = self.rdmc.app.getcollectionmembers(
            "/redfish/v1/UpdateService/UpdateTaskQueue/"
        )
        if not tasks:
            self.rdmc.ui.printer("No tasks found.\n")
            return

        if not options.json:
            self.rdmc.ui.printer("\nCurrent Update Task Queue:\n\n")

        if not options.json:
            for task in tasks:
                self.rdmc.ui.printer("Task %s:\n" % task["Name"])
                if "Filename" in list(task.keys()):
                    self.rdmc.ui.printer(
                        "\tCommand: %s\n\tFilename: %s\n\t"
                        "State:%s\n" % (task["Command"], task["Filename"], task["State"])
                    )
                elif "WaitTimeSeconds" in list(task.keys()):
                    self.rdmc.ui.printer(
                        "\tCommand: %s %s seconds\n\tState:%s\n"
                        % (task["Command"], str(task["WaitTimeSeconds"]), task["State"])
                    )
                else:
                    self.rdmc.ui.printer(
                        "\tCommand:%s\n\tState: %s\n" % (task["Command"], task["State"])
                    )
        elif options.json:
            outjson = dict()
            for task in tasks:
                outjson[task["Name"]] = dict()
                outjson[task["Name"]]["Command"] = task["Command"]
                if "Filename" in task:
                    outjson[task["Name"]]["Filename"] = task["Filename"]
                if "WaitTimeSeconds" in task:
                    outjson[task["Name"]]["WaitTimeSeconds"] = task["WaitTimeSeconds"]
                outjson[task["Name"]]["State"] = task["State"]
            self.rdmc.ui.print_out_json(outjson)

    def updatetaskqueuevalidation(self, options):
        """taskqueue validation function

        :param options: command line options
        :type options: list.
        """
        self.cmdbase.login_select_validation(self, options)

    @staticmethod
    def options_argument_group(parser):
        """Define optional arguments group

        :param parser: The parser to add the --addprivs option group to
        :type parser: ArgumentParser/OptionParser
        """
        group = parser.add_argument_group(
            "GLOBAL OPTIONS",
            "Options are available for all "
            "arguments within the scope of this command.",
        )

        group.add_argument(
            "--tpmover",
            dest="tover",
            action="store_true",
            help="If set then the TPMOverrideFlag is passed in on the "
            "associated flash operations",
            default=False,
        )

    def definearguments(self, customparser):
        """Wrapper function for new command main function

        :param customparser: command line input
        :type customparser: parser.
        """
        if not customparser:
            return

        self.cmdbase.add_login_arguments_group(customparser)

        subcommand_parser = customparser.add_subparsers(dest="command")

        default_parser = subcommand_parser.add_parser(
            "default",
            help="Running without any sub-command will return the current task \n"
            "queue information on the currently logged in server.",
        )
        default_parser.add_argument(
            "-r",
            "--resetqueue",
            action="store_true",
            dest="resetqueue",
            help="Remove all update tasks in the queue.\n\texample: taskqueue --resetqueue or taskqueue -r",
            default=False,
        )
        default_parser.add_argument(
            "-c",
            "--cleanqueue",
            action="store_true",
            dest="cleanqueue",
            help="Clean up all finished or errored tasks left pending.\n\texample: taskqueue "
            "--cleanqueue or taskqueue -c",
            default=False,
        )
        default_parser.add_argument(
            "-j",
            "--json",
            dest="json",
            action="store_true",
            help="Optionally include this flag if you wish to change the"
            " displayed output to JSON format. Preserving the JSON data"
            " structure makes the information easier to parse.",
            default=False,
        )
        self.cmdbase.add_login_arguments_group(default_parser)
        self.options_argument_group(default_parser)

        # create
        create_help = "Create a new task queue task."
        create_parser = subcommand_parser.add_parser(
            "create",
            help=create_help,
            description=create_help
            + "\n\n\tCreate a new task for 30 secs:\n\t\ttaskqueue "
            "create 30\n\n\tCreate a new reboot task.\n\t\ttaskqueue create reboot"
            "\n\n\tCreate a new component task.\n\t\ttaskqueue create compname.exe"
            "\n\n\tCreate multiple tasks at once.\n\t\ttaskqueue create 30 "
            '"compname.exe compname2.exe reboot"',
            formatter_class=RawDescriptionHelpFormatter,
        )
        create_parser.add_argument(
            "keywords",
            help="Keyword for a task queue item. *Note*: Multiple tasks can be created by "
            "using quotations wrapping all tasks, delimited by whitespace.",
            metavar="KEYWORD",
            type=str,
            nargs="+",
            default="",
        )
        self.cmdbase.add_login_arguments_group(create_parser)
        self.options_argument_group(create_parser)
