# ##
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
# ##

# -*- coding: utf-8 -*-
""" Update Task Queue Command for rdmc """

from argparse import RawDescriptionHelpFormatter
from random import randint

from redfish.ris.rmc_helper import IdTokenError

try:
    from rdmc_helper import (
        IncompatibleiLOVersionError,
        InvalidCommandLineErrorOPTS,
        NoContentsFoundForOperationError,
        ReturnCodes,
        TaskQueueError,
        LOGGER,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        IncompatibleiLOVersionError,
        InvalidCommandLineErrorOPTS,
        NoContentsFoundForOperationError,
        ReturnCodes,
        TaskQueueError,
        LOGGER,
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
            "taskqueue --cleanqueue\n\t"
            "taskqueue --resetqueue\n\t"
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
        except (InvalidCommandLineErrorOPTS, SystemExit):
            if ("-h" in line) or ("--help" in line):
                return ReturnCodes.SUCCESS
            else:
                raise InvalidCommandLineErrorOPTS("")

        self.updatetaskqueuevalidation(options)

        if self.rdmc.app.typepath.defs.isgen9:
            raise IncompatibleiLOVersionError("iLO Repository commands are only available on iLO 5.")

        if options.command.lower() == "create":
            self.createtask(options.keywords, options)
        else:
            if options.resetqueue:
                self.resetqueue(options)
            elif options.cleanqueue:
                self.cleanqueue()
            self.printqueue(options)

        self.cmdbase.logout_routine(self, options)
        # Return code
        return ReturnCodes.SUCCESS

    def resetqueue(self, options):
        """Deletes everything in the update task queue"""
        tasks = self.rdmc.app.getcollectionmembers("/redfish/v1/UpdateService/UpdateTaskQueue/")
        if not tasks:
            self.rdmc.ui.printer("No tasks found.\n")

        self.rdmc.ui.printer("Deleting all update tasks...\n")

        for task in tasks:
            self.rdmc.ui.printer("Deleting: %s\n" % task["Name"])
            if "RecoveryPrivilege" in task and task["RecoveryPrivilege"]:
                self.rdmc.ui.printer("This task is associated with updating recovery set\n")
                if not (options.user and options.password):
                    raise TaskQueueError("Deleting this task needs " "--user and --password options, delete failed\n")
                if "blobstore" in self.rdmc.app.current_client.base_url:
                    LOGGER.info("Logging out of the session without user and password")
                    self.rdmc.app.current_client.logout()
                    LOGGER.info("Logging in with user and password for deleting system recovery set")
                    self.rdmc.app.current_client._user_pass = (options.user, options.password)
                    self.rdmc.app.current_client.login(self.rdmc.app.current_client.auth_type)
                    self.rdmc.app.delete_handler(task["@odata.id"])
                else:
                    self.rdmc.app.delete_handler(task["@odata.id"])
            else:
                self.rdmc.app.delete_handler(task["@odata.id"])

    def cleanqueue(self):
        """Deletes all finished or errored tasks in the update task queue"""
        tasks = self.rdmc.app.getcollectionmembers("/redfish/v1/UpdateService/UpdateTaskQueue/")
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
        comps = self.rdmc.app.getcollectionmembers("/redfish/v1/UpdateService/" "ComponentRepository/")
        curr_tasks = self.rdmc.app.getcollectionmembers("/redfish/v1/UpdateService/UpdateTaskQueue/")
        for task in tasks:
            usedcomp = None
            newtask = None
            if options.targets:
                targets = []
                target_list = options.targets.split(",")
                for target in target_list:
                    target_url = "/redfish/v1/UpdateService/FirmwareInventory/" + str(target) + "/"
                    targets.append(target_url)
                verified = self.verify_targets(options.targets)
                if not verified:
                    self.rdmc.ui.error("Provided target was not available, Please provide valid target id\n")
                    return ReturnCodes.INVALID_TARGET_ERROR
            try:
                usedcomp = int(task)
                newtask = {
                    "Name": "Wait-%s %s seconds" % (str(randint(0, 1000000)), str(usedcomp)),
                    "Command": "Wait",
                    "WaitTimeSeconds": usedcomp,
                    "UpdatableBy": ["Bmc"],
                }
                if options.targets:
                    newtask["Targets"] = targets
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
                    results = self.rdmc.app.get_handler(self.rdmc.app.typepath.defs.biospath, silent=True)
                    if results.status == 200:
                        contents = results.dict if self.rdmc.app.typepath.defs.isgen9 else results.dict["Attributes"]
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
                if options.targets:
                    newtask["Targets"] = targets

            self.rdmc.ui.printer('Creating task: "%s"\n' % newtask["Name"])
            self.rdmc.ui.printer('payload: "%s"\n' % newtask)
            self.rdmc.app.post_handler(path, newtask)

    def verify_targets(self, target):
        target_list = target.split(",")
        for target in target_list:
            try:
                target_url = "/redfish/v1/UpdateService/FirmwareInventory/" + target
                dd = self.rdmc.app.get_handler(target_url, service=True, silent=True)
                if dd.status == 404:
                    return False
            except:
                return False
        return True

    def printqueue(self, options):
        """Prints the update task queue

        :param options: command line options
        :type options: list.
        """
        tasks = self.rdmc.app.getcollectionmembers("/redfish/v1/UpdateService/UpdateTaskQueue/")
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
                    self.rdmc.ui.printer("\tCommand:%s\n\tState: %s\n" % (task["Command"], task["State"]))
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
            "Options are available for all " "arguments within the scope of this command.",
        )

        group.add_argument(
            "--tpmover",
            dest="tover",
            action="store_true",
            help="If set then the TPMOverrideFlag is passed in on the " "associated flash operations",
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
            description=create_help + "\n\n\tCreate a new task for 30 secs:\n\t\ttaskqueue "
            "create 30\n\n\tCreate a new reboot task.\n\t\ttaskqueue create reboot"
            "\n\n\tCreate a new component task.\n\t\ttaskqueue create compname"
            "\n\n\tCreate multiple tasks at once.\n\t\ttaskqueue create 30 "
            '"compname compname2 reboot"'
            "\n\n\tCreate a new task using targets: \n\t\t taskqueue create compname --targets <id>\n\n\t",
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
        create_parser.add_argument(
            "--targets",
            help="If targets value specify a comma separated\t" "firmwareinventory id only",
            metavar="targets_indices",
        )

        self.cmdbase.add_login_arguments_group(create_parser)
        self.options_argument_group(create_parser)
