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
""" SigRecompute Command for rdmc """

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


class SigRecomputeCommand:
    """Recalculate the signature of the servers configuration"""

    def __init__(self):
        self.ident = {
            "name": "sigrecompute",
            "usage": None,
            "description": "Recalculate the signature on "
            "the computers configuration.\n\texample: sigrecompute\n\n"
            "\tNote: sigrecompute command is not available on Redfish systems.",
            "summary": "Command to recalculate the signature of the computer's " "configuration.",
            "aliases": [],
            "auxcommands": [],
        }

        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """Main sigrecompute function

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

        if args:
            raise InvalidCommandLineError("Sigrecompute command takes no arguments.\n")

        self.sigrecomputevalidation(options)
        path = self.rdmc.app.typepath.defs.systempath

        if self.rdmc.app.typepath.defs.flagforrest:
            body = {"Action": "ServerSigRecompute", "Target": "/Oem/Hp"}
            self.rdmc.app.post_handler(path, body)
        else:
            raise IncompatibleiLOVersionError("Sigrecompute action not available on redfish.\n")

        self.cmdbase.logout_routine(self, options)
        # Return code
        return ReturnCodes.SUCCESS

    def sigrecomputevalidation(self, options):
        """sigrecomputevalidation method validation function

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
