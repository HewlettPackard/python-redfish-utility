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
""" BiosDefaultsCommand for rdmc """

from argparse import RawDescriptionHelpFormatter

try:
    from rdmc_helper import (
        LOGGER,
        IncompatibleiLOVersionError,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        InvalidPasswordLengthError,
        ReturnCodes,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        LOGGER,
        IncompatibleiLOVersionError,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        InvalidPasswordLengthError,
        ReturnCodes,
    )


class ServerConfigurationLockCommand:
    """Set BIOS settings back to default for the server that is currently
    logged in"""

    def __init__(self):
        self.ident = {
            "name": "serverconfiglock",
            "usage": None,
            "description": "To to perform validation checks on raw JSON data "
            "server.\n\texample: serverconfiglock\n\t"
            "example: serverconfiglock enable --serverconfiglockpassword=AWS@123456789 "
            "--serverconfiglockexcludefwrevs=True\t serverconfiglockexcludefwrevs set True or False\n\t"
            "example: serverconfiglock disable --serverconfiglockpassword=AWS@1234 "
            "--serverconfiglockdisable=True\t serverconfiglockdisable set True or False\n\t"
            "example: serverconfiglock display",
            "summary": "The BIOS feature “Server Configuration Lock” supports certain parameters,"
            "including a password. This password has a 16 to 31 character limit. "
            "“Server Configuration Lock” is not one of the special commands in iLO REST.",
            "aliases": [],
            "auxcommands": [],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """Main BIOS defaults worker function"""
        if help_disp:
            self.parser.print_help()
            return ReturnCodes.SUCCESS
        try:
            (options, _) = self.rdmc.rdmc_parse_arglist(self, line)
        except (InvalidCommandLineErrorOPTS, SystemExit):
            if ("-h" in line) or ("--help" in line):
                return ReturnCodes.SUCCESS
            else:
                raise InvalidCommandLineErrorOPTS("")
        bios_path = self.rdmc.app.typepath.defs.biospath
        resp = self.rdmc.app.get_handler(bios_path, silent=True, service=True).dict
        match_url = resp["Oem"]["Hpe"]["Links"]["ServerConfigLock"]["@odata.id"]
        if "oem" in match_url:
            scs_path = bios_path + "oem/hpe/serverconfiglock/settings/"
        else:
            scs_path = bios_path + "serverconfiglock/settings/"
        self.serverconfiglockvalidation(options)
        if options.command:
            if options.command.lower() == "enable":
                self.enable_scs(options, scs_path)
            elif options.command.lower() == "disable":
                self.disable_scs(options, scs_path)
            elif options.command == "display":
                self.display_scs(scs_path)
            else:
                raise InvalidCommandLineError("%s is not a valid option for this " "command." % str(options.command))
        else:
            raise InvalidCommandLineError(
                "Please provide either enable, disable and display subcommand. "
                "For help or usage related information, use -h or --help"
            )
        self.cmdbase.logout_routine(self, options)
        # Return code
        return ReturnCodes.SUCCESS

    def enable_scs(self, options, scs_path):
        """
        Enable/Disable the SCL config function
        """
        if options.serverconfiglockpassword:
            ser_cf_password = options.serverconfiglockpassword
        self.serverconfiglockpassword_validation(options)
        if options.serverconfiglockexcludefwrevs.lower() == "true":
            serverconfrevs = "True"
        elif options.serverconfiglockexcludefwrevs.lower() == "false":
            serverconfrevs = "False"
        else:
            raise InvalidCommandLineError("ServerConfigLockExcludeFwRevs value invalid set only true or false")
        body = {"ServerConfigLockPassword": ser_cf_password, "ServerConfigLockExcludeFwRevs": serverconfrevs}
        try:
            self.rdmc.ui.printer("payload: %s \n" % body)
            LOGGER.info("payload", body)
            resp = self.rdmc.app.patch_handler(scs_path, body)
            if resp.status == 200:
                self.rdmc.ui.printer("SCS enabled successfully\n")
                LOGGER.info("SCS enabled successfully")
                self.rdmc.ui.printer("Help: System Reboot is required after changing the serverconfiglock settings \n")
                return ReturnCodes.SUCCESS
        except IncompatibleiLOVersionError:
            self.rdmc.ui.error("iLO FW version on this server doesnt support SCS")
            LOGGER.error("iLO FW version on this server doesnt support SCS")
            return ReturnCodes.INCOMPATIBLE_ILO_VERSION_ERROR

    def disable_scs(self, options, scs_path):
        """
        Disable the SCL config function
        """
        if options.serverconfiglockpassword:
            ser_cf_password = options.serverconfiglockpassword
        self.serverconfiglockpassword_validation(options)
        if options.serverconfiglockdisable.lower() == "true":
            sclockdisable = "True"
        elif options.serverconfiglockdisable.lower() == "false":
            sclockdisable = "False"
        else:
            raise InvalidCommandLineError("ServerConfigLockDisable value invalid set only true or false")
        body = {"ServerConfigLockPassword": ser_cf_password, "ServerConfigLockDisable": sclockdisable}
        try:
            self.rdmc.ui.printer("payload: %s \n" % body)
            LOGGER.info("payload", body)
            resp = self.rdmc.app.patch_handler(scs_path, body)
            if resp.status == 200:
                self.rdmc.ui.printer("SCS Disabled successfully\n")
                LOGGER.info("SCS Disabled successfully")
                self.rdmc.ui.printer("Help: System Reboot is required after changing the serverconfiglock settings \n")
                return ReturnCodes.SUCCESS
        except IncompatibleiLOVersionError:
            self.rdmc.ui.error("iLO FW version on this server doesnt support SCS")
            LOGGER.error("iLO FW version on this server doesnt support SCS")
            return ReturnCodes.INCOMPATIBLE_ILO_VERSION_ERROR

    def display_scs(self, scs_path):
        """
        Display SCS details
        """
        ilo_ver = self.rdmc.app.getiloversion()
        if ilo_ver >= 5.290 or ilo_ver < 6.000:
            results = self.rdmc.app.get_handler(scs_path, silent=True)
            if results.status == 200:
                self.rdmc.ui.printer("Server Configuration Lock setting details ...\n")
                LOGGER.info("Server Configuration Lock setting details ...")
                results = results.dict
                self.print_scs_info(results)
        else:
            self.rdmc.ui.printer("For iLO6, this command is not yet supported.\n")
            LOGGER.error("For iLO6, this command is not yet supported.")

    def print_scs_info(self, results):
        """
        Prints the SCL: info
        """
        for key, value in results.items():
            if "@odata" not in key:
                if type(value) is dict:
                    self.print_cert_info(value)
                else:
                    self.rdmc.ui.printer(key + ":" + str(value) + "\n")

    def serverconfiglockpassword_validation(self, options):
        """
        Password validation for ServerConfigLockPassword method
        """
        import re

        if options.serverconfiglockpassword:
            password = options.serverconfiglockpassword
        if len(password) < 16 or len(password) > 31:
            LOGGER.info("Length of password requires min of 16 and max of 31 character " "excluding '/' character.\n")
            raise InvalidPasswordLengthError(
                "Length of password requires min of 16 and max of 31 character " "excluding '/' character.\n"
            )
        elif re.search("[0-9]", password) is None:
            print("Make sure your password has a number in it\n")
        elif re.search("[A-Z]", password) is None:
            print("Make sure your password has a capital letter in it\n")

    def serverconfiglockvalidation(self, options):
        """new command method validation function"""
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
        enable_help = "To enable ServerConfigurationLock \n"

        enable_parser = subcommand_parser.add_parser(
            "enable",
            help=enable_help,
            description=enable_help + "\n\tExample:\n\tserverconfiglock enable ",
            formatter_class=RawDescriptionHelpFormatter,
        )
        enable_parser.add_argument(
            "--serverconfiglockpassword",
            dest="serverconfiglockpassword",
            help="Set a serverconfiglockpassword",
            required=True,
            type=str,
            default=None,
        )
        enable_parser.add_argument(
            "--serverconfiglockexcludefwrevs",
            dest="serverconfiglockexcludefwrevs",
            help="to set/enable serverconfiglockexcludefwrevs",
            default=False,
            required=True,
        )
        self.cmdbase.add_login_arguments_group(enable_parser)

        status_help = "To check the ServerConfigurationLock display\n"
        status_parser = subcommand_parser.add_parser(
            "display",
            help=status_help,
            description=status_help + "\n\tExample:\n\tserverconfiglock display or " "\n\tserverconfiglock status -j",
            formatter_class=RawDescriptionHelpFormatter,
        )

        self.cmdbase.add_login_arguments_group(status_parser)

        disable_help = "To disable the ServerConfigurationLock\n"
        disable_parser = subcommand_parser.add_parser(
            "disable",
            help=disable_help,
            description=disable_help + "\n\tExample:\n\tserverconfiglock disable",
            formatter_class=RawDescriptionHelpFormatter,
        )
        disable_parser.add_argument(
            "--serverconfiglockpassword",
            dest="serverconfiglockpassword",
            help="Server Configuration Lock password and to digitally fingerprint the system to enable Server "
            "Configuration Lock.",
            required=True,
            type=str,
            default=None,
        )
        disable_parser.add_argument(
            "--serverconfiglockdisable",
            dest="serverconfiglockdisable",
            help="Select this option to disable Server Configuration Lock.",
            required=True,
            default=False,
        )
        self.cmdbase.add_login_arguments_group(disable_parser)
