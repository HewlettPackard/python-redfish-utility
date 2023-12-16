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
""" Delete Component Command for rdmc """

try:
    from rdmc_helper import (
        IncompatibleiLOVersionError,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        ReturnCodes,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        IncompatibleiLOVersionError,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        ReturnCodes,
    )


class DeleteComponentCommand:
    """Main download command class"""

    def __init__(self):
        self.ident = {
            "name": "deletecomp",
            "usage": None,
            "description": "Run to delete component(s) of the currently logged in system.\n\n\t"
            "Delete a single component by name.\n\texample: deletecomp "
            "CP327.zip\n\n\tDelete multiple components by "
            "id.\n\tExample: deletecomp 377fg6c4 327cf4c7\n\n\tDelete "
            "multiple components by filename.\n\texample: deletecomp "
            "CP327.exe CP99.exe",
            "summary": "Deletes components/binaries from the iLO Repository.",
            "aliases": [],
            "auxcommands": [],
        }

        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """Main deletecomp worker function

        :param line: string of arguments passed in
        :type line: str.
        :param help_disp: display help flag
        :type line: bool.
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

        self.deletecomponentvalidation(options)

        if self.rdmc.app.typepath.defs.isgen9:
            raise IncompatibleiLOVersionError("iLO Repository commands are " "only available on iLO 5.")

        comps = self.rdmc.app.getcollectionmembers("/redfish/v1/UpdateService/ComponentRepository/")

        if not comps:
            self.rdmc.ui.printer("No components found to delete\n")

        elif options.deleteall:
            delopts = []

            for comp in comps:
                try:
                    if comp["Locked"]:
                        self.rdmc.ui.warn(
                            "Unable to delete %s. It is in use by "
                            "an install set or update task.\n" % comp["Filename"]
                        )
                        continue
                except KeyError:
                    pass
                delopts.append(comp["@odata.id"])

            self.deletecomponents(comps, delopts)
        elif args:
            self.deletecomponents(comps, args)
        else:
            InvalidCommandLineError("Please include the component(s) you wish to delete")

        self.cmdbase.logout_routine(self, options)
        # Return code
        return ReturnCodes.SUCCESS

    def deletecomponents(self, comps, delopts):
        """component validation function

        :param comps: component list
        :type comps: list.
        :param delopts: delete items list
        :type delopts: list.
        """
        if "," in delopts:
            delopts = delopts.split(",")
        elif not isinstance(delopts, list):
            delopts = [delopts]

        for opt in delopts:
            deleted = False

            if "/" in opt:
                self.rdmc.app.delete_handler(opt)
                deleted = True
            else:
                for comp in comps:
                    if opt == comp["Id"] or opt == comp["Filename"]:
                        try:
                            if comp["Locked"]:
                                self.rdmc.ui.error(
                                    "Unable to delete %s. It is in use by "
                                    "an install set or update task.\n" % comp["Filename"]
                                )
                                continue
                        except KeyError:
                            pass

                        self.rdmc.app.delete_handler(comp["@odata.id"])
                        deleted = True

                if deleted:
                    self.rdmc.ui.printer("Deleted %s\n" % opt)
                    self.rdmc.ui.printer("Component " + opt + " deleted successfully.\n")
                    # self.rdmc.ui.printer("[200] The operation completed successfully.\n")
                else:
                    raise InvalidCommandLineError("Cannot find or unable to delete component %s" % opt)

    def deletecomponentvalidation(self, options):
        """component validation function

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
            "-a",
            "--all",
            dest="deleteall",
            action="store_true",
            help="""Delete all components.""",
            default=False,
        )
