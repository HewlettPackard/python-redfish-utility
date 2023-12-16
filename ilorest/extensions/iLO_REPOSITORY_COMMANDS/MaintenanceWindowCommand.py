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

import re
from argparse import RawDescriptionHelpFormatter
from random import randint

from redfish.ris.rmc_helper import ValidationError

try:
    from rdmc_helper import (
        IncompatibleiLOVersionError,
        InvalidCommandLineErrorOPTS,
        NoContentsFoundForOperationError,
        ReturnCodes,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        IncompatibleiLOVersionError,
        InvalidCommandLineErrorOPTS,
        NoContentsFoundForOperationError,
        ReturnCodes,
    )

__subparsers__ = ["add", "delete"]


class MaintenanceWindowCommand:
    """Main maintenancewindow command class"""

    def __init__(self):
        self.ident = {
            "name": "maintenancewindow",
            "usage": None,
            "description": "Add or delete maintenance windows from the iLO repository.\nTo "
            " view help on specific sub-commands run: maintenancewindow <sub-command> -h\n\n"
            "NOTE: iLO 5 required.",
            "summary": "Manages the maintenance windows for iLO.",
            "aliases": [],
            "auxcommands": [],
        }

    def run(self, line, help_disp=False):
        """Main update maintenance window worker function

        :param line: string of arguments passed in
        :type line: str.
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

        self.maintenancewindowvalidation(options)

        if self.rdmc.app.typepath.defs.isgen9:
            raise IncompatibleiLOVersionError("iLO Repository commands are only available on iLO 5.")

        windows = self.rdmc.app.getcollectionmembers("/redfish/v1/UpdateService/MaintenanceWindows/")

        if options.command.lower() == "add":
            self.addmaintenancewindow(options, windows, options.time_window)
        elif options.command.lower() == "delete":
            self.deletemaintenancewindow(windows, options.identifier)
        else:
            self.listmainenancewindows(options, windows)

        self.cmdbase.logout_routine(self, options)
        # Return code
        return ReturnCodes.SUCCESS

    def addmaintenancewindow(self, options, windows, startafter):
        """Add a maintenance window

        :param options: command line options
        :type options: list.
        :param windows: list of maintenance windows on the system
        :type windows: list.
        :param startafter: redfish date-time string to start the maintenance window
        :type startafter: str.
        """
        adddata = {"StartAfter": startafter}

        if options.name:
            adddata["Name"] = options.name
        else:
            adddata["Name"] = "MW-%s" % str(randint(0, 1000000))

        if options.description:
            if options.description.startswith('"') and options.description.endswith('"'):
                options.description = options.description[1:-1]
            adddata["Description"] = options.description

        if options.expire:
            adddata["Expire"] = options.expire

        errors = self.validatewindow(adddata, windows)

        if not errors:
            path = "/redfish/v1/UpdateService/MaintenanceWindows/"
            self.rdmc.app.post_handler(path, adddata)
        else:
            self.rdmc.ui.error("Invalid Maintenance Window:\n")
            for error in errors:
                self.rdmc.ui.error("\t" + error + "\n")
            raise ValidationError("")

    def deletemaintenancewindow(self, windows, nameid):
        """Delete a maintenance window by Id or Name

        :param windows: list of maintenance windows on the system
        :type windows: list.
        :param nameid: id or name string to remove
        :type nameid: str.
        """

        deleted = False
        for window in windows:
            if window["Name"] == nameid or window["Id"] == nameid:
                path = window["@odata.id"]
                self.rdmc.ui.printer("Deleting %s\n" % nameid)
                self.rdmc.app.delete_handler(path)
                deleted = True
                break

        if not deleted:
            raise NoContentsFoundForOperationError("No maintenance window found with that Name/Id.")

    def listmainenancewindows(self, options, windows):
        """Lists the maintenance windows

        :param options: command line options
        :type options: list.
        :param windows: list of maintenance windows on the system
        :type windows: list.
        """

        outstring = ""
        jsonwindows = []

        if windows:
            for window in windows:
                if options.json:
                    jsonwindows.append(dict((key, val) for key, val in window.items() if "@odata." not in key))
                else:
                    outstring += "%s:" % window["Name"]
                    outstring += "%s:" % window["Id"]
                    if "Description" in list(window.keys()) and window["Description"]:
                        outstring += "\n\tDescription: %s" % window["Description"]
                    else:
                        outstring += "\n\tDescription: %s" % "No description."
                    outstring += "\n\tStart After: %s" % window["StartAfter"]
                    if "Expire" in list(window.keys()):
                        outstring += "\n\tExpires at: %s" % window["Expire"]
                    else:
                        outstring += "\n\tExpires at: %s" % "No expire time set."
                    outstring += "\n"
            if jsonwindows:
                self.rdmc.ui.print_out_json(jsonwindows)
            else:
                self.rdmc.ui.printer(outstring)
        else:
            self.rdmc.ui.warn("No maintenance windows found on system.\n")

    def validatewindow(self, cmw, windows):
        """Validate the maintenance window before adding

        :param cmw: a maintenance window candidate
        :type cmw: dict.
        :param windows: list of maintenance windows on the system
        :type windows: list.
        :returns: returns a list of errors or a empty list if no errors
        """
        errorlist = []
        rfdtregex = "\\d\\d\\d\\d-\\d\\d-\\d\\dT\\d\\d:\\d\\d:\\d\\dZ?"

        for window in windows:
            if cmw["Name"] == window["Name"]:
                errorlist.append("Maintenance window with Name: %s already exists." % cmw["Name"])

        if "Name" in list(cmw.keys()):
            if len(cmw["Name"]) > 64:
                errorlist.append("Name must be 64 characters or less.")
        if "Description" in list(cmw.keys()):
            if len(cmw["Description"]) > 64:
                errorlist.append("Description must be 64 characters or less.")
        if "Expire" in list(cmw.keys()):
            if not re.match(rfdtregex, cmw["Expire"]):
                errorlist.append(
                    "Invalid redfish date-time format in Expire. "
                    "Accepted formats: YYYY-MM-DDThh:mm:ss, YYYY-MM-DDThh:mm:ssZ"
                )
        if not re.match(rfdtregex, cmw["StartAfter"]):
            errorlist.append(
                "Invalid redfish date-time format in StartAfter. "
                "Accepted formats YYYY-MM-DDThh:mm:ss, YYYY-MM-DDThh:mm:ssZ"
            )

        return errorlist

    def maintenancewindowvalidation(self, options):
        """maintenencewindow validation function

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
        subcommand_parser = customparser.add_subparsers(dest="command")

        # default sub-parser
        default_parser = subcommand_parser.add_parser(
            "default",
            help="Running without any sub-command will return all maintenace windows on the "
            "currently logged in server.",
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

        # add sub-parser
        add_help = "Adds a maintenance window to iLO"
        add_parser = subcommand_parser.add_parser(
            "add",
            help=add_help,
            description=add_help + "\nexample: maintenancewindow add 1998-11-21T00:00:00 "
            "--expire=1998-11-22T00:00:00 --name=MyMaintenanceWindow --description "
            '"My maintenance window description.,"',
            formatter_class=RawDescriptionHelpFormatter,
        )
        add_parser.add_argument(
            "time_window",
            help="Specify the time window start period in DateTime format.\ni.e. YEAR-MONTH-DAY"
            "THOUR:MINUTE:SECOND.\nexample: 1998-11-21T10:59:58",
            metavar="TIMEWINDOW",
        )
        add_parser.add_argument(
            "--description",
            dest="description",
            help="Optionally include this flag if you would like to add a "
            "description to the maintenance window you create",
            default=None,
        )
        add_parser.add_argument(
            "--name",
            dest="name",
            help="Optionally include this flag if you would like to add a "
            "name to the maintenance window you create. If you do not specify one"
            " a unique name will be added.",
            default=None,
        )
        add_parser.add_argument(
            "--expire",
            dest="expire",
            help="Optionally include this flag if you would like to add a " "time the maintenance window expires.",
            default=None,
        )
        self.cmdbase.add_login_arguments_group(add_parser)

        # delete sub-parser
        delete_help = "Deletes the specified maintenance window on the currently logged in server."
        delete_parser = subcommand_parser.add_parser(
            "delete",
            help=delete_help,
            description=delete_help + "\nexample: maintenancewindow delete mymaintenancewindowname\n"
            "Note: The maintenance window identifier can be referenced by Name or ID#."
            "maintenancewindow delete name",
            formatter_class=RawDescriptionHelpFormatter,
        )
        delete_parser.add_argument(
            "identifier",
            help="The unique identifier provided by iLO or the identifier provided by '--name' "
            "when the maintenance window was created.",
        )
        self.cmdbase.add_login_arguments_group(delete_parser)
