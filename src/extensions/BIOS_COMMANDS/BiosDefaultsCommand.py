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

try:
    from rdmc_helper import Encryption, InvalidCommandLineErrorOPTS, ReturnCodes
except ImportError:
    from ilorest.rdmc_helper import Encryption, InvalidCommandLineErrorOPTS, ReturnCodes


class BiosDefaultsCommand:
    """Set BIOS settings back to default for the server that is currently
    logged in"""

    def __init__(self):
        self.ident = {
            "name": "biosdefaults",
            "usage": None,
            "description": "Run to set the currently"
            " logged in server's Bios. type settings to defaults\n\texample: "
            "biosdefaults\n\n\tRun to set the currently logged in server's "
            "Bios. type settings to user defaults\n\texample: biosdefaults "
            "--userdefaults\n\n\tRun to set the currently logged in server "
            "to manufacturing defaults, including boot order and secure boot."
            "\n\texample: biosdefaults --manufacturingdefaults",
            "summary": "Set the currently logged in server to default BIOS settings.",
            "aliases": [],
            "auxcommands": ["SetCommand", "RebootCommand"],
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

        self.defaultsvalidation(options)

        if options.manufdefaults:
            self.rdmc.ui.printer("Resetting BIOS attributes and settings to manufacturing defaults.\n")
        elif options.userdefaults:
            self.rdmc.ui.printer("Resetting BIOS attributes and settings to user defaults.\n")

        put_path = self.rdmc.app.typepath.defs.biospath
        body = None

        if self.rdmc.app.typepath.defs.isgen10 and not options.manufdefaults:
            bodydict = self.rdmc.app.get_handler(self.rdmc.app.typepath.defs.biospath, service=True, silent=True).dict

            for item in bodydict["Actions"]:
                if "ResetBios" in item:
                    action = item.split("#")[-1]
                    path = bodydict["Actions"][item]["target"]
                    break

            body = {"Action": action}

            if options.userdefaults:
                body["ResetType"] = "default.user"
            else:
                body["ResetType"] = "default"

            self.rdmc.app.post_handler(path, body)
        else:
            if options.userdefaults:
                body = {"BaseConfig": "default.user"}
            elif not options.manufdefaults:
                body = {"BaseConfig": "default"}
            if body:
                self.rdmc.app.put_handler(
                    put_path + "/settings",
                    body=body,
                    optionalpassword=options.biospassword,
                )

        if not body and options.manufdefaults:
            setstring = "RestoreManufacturingDefaults=Yes --selector=HpBios. --commit"
            if options.reboot:
                setstring += " --reboot=%s" % options.reboot

            self.auxcommands["set"].run(setstring)

        elif options.reboot:
            self.auxcommands["reboot"].run(options.reboot)

        self.cmdbase.logout_routine(self, options)
        # Return code
        return ReturnCodes.SUCCESS

    def defaultsvalidation(self, options):
        """BIOS defaults method validation function"""
        self.cmdbase.login_select_validation(self, options)

        if options.encode:
            options.biospassword = Encryption.decode_credentials(options.biospassword)
            if isinstance(options.biospassword, bytes):
                options.biospassword = options.biospassword.decode("utf-8")

    def definearguments(self, customparser):
        """Wrapper function for new command main function

        :param customparser: command line input
        :type customparser: parser.
        """
        if not customparser:
            return

        self.cmdbase.add_login_arguments_group(customparser)

        customparser.add_argument(
            "--reboot",
            dest="reboot",
            help="Use this flag to perform a reboot command function after"
            " completion of operations.  For help with parameters and"
            " descriptions regarding the reboot flag, run help reboot.",
            default=None,
        )
        customparser.add_argument(
            "--userdefaults",
            dest="userdefaults",
            action="store_true",
            help="Sets bios to user defaults instead of manufacturing defaults.",
            default=False,
        )
        customparser.add_argument(
            "--manufacturingdefaults",
            dest="manufdefaults",
            action="store_true",
            help="Reset all configuration settings to manufacturing defaults, " "including boot order and secure boot.",
            default=False,
        )
