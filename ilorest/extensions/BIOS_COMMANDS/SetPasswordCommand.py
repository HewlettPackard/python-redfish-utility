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
""" SetPassword Command for rdmc """

try:
    from rdmc_helper import (
        Encryption,
        InvalidCommandLineErrorOPTS,
        ReturnCodes,
        UnableToDecodeError,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        Encryption,
        InvalidCommandLineErrorOPTS,
        ReturnCodes,
        UnableToDecodeError,
    )


class SetPasswordCommand:
    """Set password class command"""

    def __init__(self):
        self.ident = {
            "name": "setpassword",
            "usage": None,
            "description": "Sets the admin password and power-on password\n"
            "setpassword --newpassword <NEW_PASSWORD> --currentpassword <OLD_PASSWORD> [OPTIONS]\n\n\t"
            "Setting the admin password with no previous password set."
            "\n\texample: setpassword --newpassword testnew --currentpassword None\n\n\tSetting the admin "
            "password back to nothing.\n\texample: setpassword --newpassword None --currentpassword testnew "
            "\n\n\tSetting the power on password.\n\texample: setpassword"
            " --newpassword testnew --currentpassword None --poweron\n\tNote: "
            "if it is empty password, send None as above.",
            "summary": "Sets the admin password and power-on password",
            "aliases": [],
            "auxcommands": [
                "LoginCommand",
                "SetCommand",
                "SelectCommand",
                "CommitCommand",
                "RebootCommand",
                "LogoutCommand",
            ],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """Main set password worker function

        :param line: string of arguments passed in
        :type line: str.
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

        self.setpasswordvalidation(options)

        # if not args:
        #    self.rdmc.ui.printer('Please input the current password.\n')
        #    tempoldpass = getpass.getpass()

        #   if tempoldpass and tempoldpass != '\r':
        #        tempoldpass = tempoldpass
        #    else:
        #        tempoldpass = '""'

        #    self.rdmc.ui.printer('Please input the new password.\n')
        #    tempnewpass = getpass.getpass()

        #    if tempnewpass and tempnewpass != '\r':
        #        tempnewpass = tempnewpass
        #    else:
        #        tempnewpass = '""'
        #    args.extend([tempnewpass, tempoldpass])

        # if len(args) < 2:
        #    raise InvalidCommandLineError("Please pass both new password and old password.")

        args = list()
        args.append(options.newpassword)
        args.append(options.currentpassword)
        count = 0
        for arg in args:
            if arg:
                if arg.lower() == "none" or arg.lower() == "null" or arg is None:
                    args[count] = ""
                elif len(arg) > 2:
                    if ('"' in arg[0] and '"' in arg[-1]) or ("'" in arg[0] and "'" in arg[-1]):
                        args[count] = arg[1:-1]
                elif len(arg) == 2:
                    if (arg[0] == '"' and arg[1] == '"') or (arg[0] == "'" and arg[1] == "'"):
                        args[count] = ""
            count += 1

        if options.encode:
            _args = []
            for arg in args:
                try:
                    arg = Encryption.decode_credentials(arg)
                    if isinstance(arg, bytes):
                        arg = arg.decode("utf-8")
                    _args.append(arg)
                except UnableToDecodeError:
                    _args.append(arg)
            args = _args
        if self.rdmc.app.typepath.defs.isgen10:
            bodydict = self.rdmc.app.get_handler(self.rdmc.app.typepath.defs.biospath, service=True, silent=True).dict

            for item in bodydict["Actions"]:
                if "ChangePassword" in item:
                    path = bodydict["Actions"][item]["target"]
                    break

            if options.poweron:
                body = {
                    "PasswordName": "User",
                    "OldPassword": args[1],
                    "NewPassword": args[0],
                }
            else:
                body = {
                    "PasswordName": "Administrator",
                    "OldPassword": args[1],
                    "NewPassword": args[0],
                }

            self.rdmc.app.post_handler(path, body)
        else:
            if options.poweron:
                self.auxcommands["select"].run("HpBios.")
                self.auxcommands["set"].run("PowerOnPassword=%s OldPowerOnPassword=%s" % (args[0], args[1]))
                self.auxcommands["commit"].run("")
            else:
                self.auxcommands["select"].run("HpBios.")
                self.auxcommands["set"].run("AdminPassword=%s OldAdminPassword=%s" % (args[0], args[1]))
                self.auxcommands["commit"].run("")
                self.rdmc.ui.printer(
                    "\nThe session will now be terminated.\n"
                    " login again with updated credentials in order to continue.\n"
                )
                self.auxcommands["logout"].run("")

        if options:
            if options.reboot:
                self.auxcommands["reboot"].run(options.reboot)

        self.cmdbase.logout_routine(self, options)
        return ReturnCodes.SUCCESS

    def setpasswordvalidation(self, options):
        """Results method validation function

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
            "--currentpassword",
            dest="currentpassword",
            help="Use this flag to provide current password.",
            required=True,
        )

        customparser.add_argument(
            "--newpassword",
            dest="newpassword",
            help="Use this flag to provide new password.",
            required=True,
        )

        customparser.add_argument(
            "--reboot",
            dest="reboot",
            help="Use this flag to perform a reboot command function after "
            "completion of operations. 'REBOOT' is a replaceable parameter "
            "that can have multiple values. For help with parameters and "
            "descriptions regarding the reboot flag, run help reboot.",
            default=None,
        )
        customparser.add_argument(
            "--poweron",
            dest="poweron",
            action="store_true",
            help="""Use this flag to set power on password instead""",
            default=None,
        )
