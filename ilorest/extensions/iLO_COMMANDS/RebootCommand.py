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
""" Reboot Command for rdmc """

import time

from six.moves import input

try:
    from rdmc_helper import (
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        NoContentsFoundForOperationError,
        ReturnCodes,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        NoContentsFoundForOperationError,
        ReturnCodes,
    )


class RebootCommand:
    """Reboot server that is currently logged in"""

    def __init__(self):
        self.ident = {
            "name": "reboot",
            "usage": None,
            "description": "Remotely control system power state commands such as, "
            "\n\t1. Turning the system on.\n\t2. Turning the system off.\n\t3. Power "
            "cycling/rebooting.\n\t4. Issuing a Non-Maskable Interrupt (NMI).\n\t5. Any "
            "number of pre-defined operations through virtual power-button presses."
            "\n\n\tNote: By default a force "
            "restart will occur, if the system is in an applicable power state.\n\texample: "
            "reboot On\n\n\tOPTIONAL PARAMETERS AND DESCRIPTIONS:"
            "\n\tOn \t\t(Turns the system on.)\n\tForceOff  "
            "\t(Performs an immediate non-graceful shutdown.)"
            "\n\tForceRestart \t(DEFAULT) (Performs"
            " an immediate non-graceful shutdown,\n\t\t\t"
            " followed by a restart of the system.)\n\tNmi  "
            "\t\t(Generates a Non-Maskable Interrupt to cause"
            " an\n\t\t\t immediate system halt.)\n\tPushPowerButton "
            "(Simulates the pressing of the physical power "
            "button\n\t\t\t on this system.)\n\n\tOEM PARAMETERS AND"
            " DESCRIPTIONS:\n\tPress\t\t(Simulates the pressing of the"
            " physical power button\n\t\t\t on this system.)\n\t"
            "PressAndHold\t(Simulates pressing and holding of the power"
            " button\n\t\t\t on this systems.)\n\tColdBoot\t(Immidiately"
            " Removes power from the server,\n\t\t\tfollowed by a restart"
            " of the system)",
            "summary": "Reboot operations for the current logged in server.",
            "aliases": [],
            "auxcommands": [],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """Main reboot worker function

        :param line: string of arguments passed in
        :type line: str.
        :param help_disp: display help flag
        :type line: bool.
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

        if len(args) < 2:
            self.rebootvalidation(options)
        else:
            raise InvalidCommandLineError("Invalid number of parameters." " Reboot takes a maximum of 1 parameter.")

        if not args:
            self.rdmc.ui.warn(
                "\nAfter the server is rebooted the session will be terminated."
                "\nPlease wait for the server to boot completely before logging in "
                "again.\nRebooting server in 3 seconds...\n"
            )
            time.sleep(3)
        else:
            self.printreboothelp(args[0])
            time.sleep(3)

        select = "ComputerSystem."
        results = self.rdmc.app.select(selector=select)
        oemlist = ["press", "pressandhold", "coldboot"]

        try:
            results = results[0]
        except:
            pass

        if results:
            put_path = results.resp.request.path
        else:
            raise NoContentsFoundForOperationError("Unable to find %s" % select)

        if args and args[0].lower() in oemlist:
            bodydict = results.resp.dict["Oem"][self.rdmc.app.typepath.defs.oemhp]

            if args[0].lower() == "coldboot":
                resettype = "SystemReset"
            else:
                resettype = "PowerButton"
        else:
            bodydict = results.resp.dict
            resettype = "Reset"

        try:
            for item in bodydict["Actions"]:
                if resettype in item:
                    if self.rdmc.app.typepath.defs.isgen10:
                        action = item.split("#")[-1]
                    else:
                        action = resettype

                    put_path = bodydict["Actions"][item]["target"]
                    break
        except:
            action = resettype

        if args and not args[0].lower() == "forcerestart":
            if args[0].lower() == "on":
                body = {"Action": action, "ResetType": "On"}
            elif args[0].lower() == "forceoff":
                body = {"Action": action, "ResetType": "ForceOff"}
            elif args[0].lower() == "nmi":
                body = {"Action": action, "ResetType": "Nmi"}
            elif args[0].lower() == "pushpowerbutton":
                body = {"Action": action, "ResetType": "PushPowerButton"}
            elif args[0].lower() == "press":
                body = {"Action": action, "PushType": "Press"}
            elif args[0].lower() == "pressandhold":
                body = {"Action": action, "PushType": "PressAndHold"}
            elif args[0].lower() == "coldboot":
                body = {"Action": action, "ResetType": "ColdBoot"}
        else:
            body = {"Action": action, "ResetType": "ForceRestart"}

        if options.confirm is True:
            count = 0
            while True:
                count = count + 1
                confirmation = input("Rebooting system, type yes to confirm or no to abort:")
                if confirmation.lower() in ("no", "n") or count > 3:
                    self.rdmc.ui.printer("Aborting reboot.\n")
                    return ReturnCodes.SUCCESS
                elif confirmation.lower() in ("yes", "y"):
                    break

        self.rdmc.app.post_handler(put_path, body)

        if not options.nologout:
            self.cmdbase.logout_routine(self, options)
        # Return code
        return ReturnCodes.SUCCESS

    def printreboothelp(self, flag):
        """helper print function for reboot function

        :param flag: command line option
        :type flag: str
        """
        if flag.upper() == "ON":
            self.rdmc.ui.warn(
                "\nThe server is powering on. Note, the current session will be "
                "terminated.\nPlease wait for the server to boot completely before logging in "
                "again.\nTurning on the server in 3 seconds...\n"
            )
        elif flag.upper() == "FORCEOFF":
            self.rdmc.ui.warn(
                "\nThe server is powering off. Note, the current session will be "
                "terminated.\nPlease wait for the server to power off completely before logging "
                "in again.\nPowering off the server in 3 seconds...\n"
            )
        elif flag.upper() == "FORCERESTART":
            self.rdmc.ui.warn(
                "\nForcing a server restart. Note, the current session will be "
                "terminated.\nPlease wait for the server to boot completely before logging in "
                "again.\nRebooting the server in 3 seconds...\n"
            )
        elif flag.upper() == "NMI":
            self.rdmc.ui.warn(
                "\nA non-maskable interrupt will be issued to this server. Note, the "
                "current session will be terminated.\nIssuing interrupt in 3 seconds...\n"
            )
        elif flag.upper() == "PUSHPOWERBUTTON" or flag.upper() == "PRESS":
            self.rdmc.ui.warn(
                "\nThe server power button will be virtually pushed; the reaction "
                "will be dependent on the current system power and boot state. Note the current "
                "session will be terminated.\nVirtual push in 3 seconds...\n"
            )
        elif flag.upper() == "COLDBOOT":
            self.rdmc.ui.warn(
                "\nThe server will be cold boot, power cycled. Note, the current "
                "session will be terminated.\nPlease wait for the server to boot completely "
                "before logging in again.\nCold Booting server in 3 seconds...\n"
            )
        elif flag.upper() == "PRESSANDHOLD":
            self.rdmc.ui.warn(
                "\nThe server will be forcefully powered off. Note, the current "
                "session will be terminated.\nPlease wait for the server to power off "
                "completely before logging in again.\nPressing and holding the power button in "
                "3 seconds...\n"
            )
        else:
            raise InvalidCommandLineError("Invalid parameter: '%s'. Please run" " 'help reboot' for parameters." % flag)

    def rebootvalidation(self, options):
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

        customparser.add_argument(
            "--confirm",
            dest="confirm",
            action="store_true",
            help="Optionally include to request user confirmation for reboot.",
            default=False,
        )
        customparser.add_argument(
            "--nologout",
            dest="nologout",
            action="store_true",
            help="Optionally include to not to logout of iLO connection.",
            default=False,
        )
