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
"""iLO CHIF Reset Command for rdmc"""
import sys
from argparse import RawDescriptionHelpFormatter

try:
    from rdmc_helper import (
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        ReturnCodes,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        ReturnCodes,
    )


class ChannelInterfaceCommand:
    """Reset iLO on the server that is currently logged in"""

    def __init__(self):
        self.ident = {
            "name": "channelinterface",
            "usage": None,
            "description": "Reset CHIF on the current logged in" " server.\n\tExample: channelinterface reset",
            "summary": "Reset CHIF on the current logged in server.",
            "aliases": [],
            "auxcommands": [],
        }

        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """Main iLO reset worker function

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

        self.iloresetvalidation(options)
        if "blobstore" not in self.rdmc.app.current_client.base_url:
            raise InvalidCommandLineError("CHIF reset is not supported in remote mode.\n")

        if line[0].lower() == "reset":

            ret = self.chif_reset()
            if ret:
                sys.stdout.write("Successfully reset the CHIF interface.\n")
                return ReturnCodes.SUCCESS
            else:
                sys.stdout.write("Failed to reset the CHIF interface.\n")
                return ReturnCodes.RIS_ILO_CHIF_PACKET_EXCHANGE_ERROR
        else:
            raise InvalidCommandLineError("Invalid parameter, please provide channelinterface reset command.\n")

    def chif_reset(self):
        """Function for handling chif packet exchange

        :param data: data to be sent for packet exchange
        :type data: str

        """
        try:
            libhandle = self.rdmc.app.current_client.connection._conn.channel.dll
            libhandle.ChifTerminate()
            libhandle.ChifInitialize(None)
            return True
        except:
            return False

    def iloresetvalidation(self, options):
        """reboot method validation function

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

        reset_help = "To disconnect from ComputeOpsManagement\n"
        reset_parser = subcommand_parser.add_parser(
            "reset",
            help=reset_help,
            description=reset_help + "\n\tExample:\n\tchannelinterface reset",
            formatter_class=RawDescriptionHelpFormatter,
        )
        self.cmdbase.add_login_arguments_group(reset_parser)
