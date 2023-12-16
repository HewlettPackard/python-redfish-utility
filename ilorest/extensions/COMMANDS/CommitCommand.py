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
""" Commit Command for RDMC """

from redfish.ris.rmc_helper import NothingSelectedError

try:
    from rdmc_helper import (
        FailureDuringCommitError,
        InvalidCommandLineErrorOPTS,
        NoChangesFoundOrMadeError,
        NoCurrentSessionEstablished,
        ReturnCodes,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        FailureDuringCommitError,
        InvalidCommandLineErrorOPTS,
        NoChangesFoundOrMadeError,
        NoCurrentSessionEstablished,
        ReturnCodes,
    )


class CommitCommand:
    """Constructor"""

    def __init__(self):
        self.ident = {
            "name": "commit",
            "usage": None,
            "description": "commit [OPTIONS]\n\n\tRun to apply all changes made during"
            " the current session\n\texample: commit",
            "summary": "Applies all the changes made during the current session.",
            "aliases": [],
            "auxcommands": ["LogoutCommand", "RebootCommand"],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def commitfunction(self, options=None):
        """Main commit worker function

        :param options: command line options
        :type options: list.
        """
        self.commitvalidation()

        self.rdmc.ui.printer("Committing changes...\n")

        if options:
            if options.biospassword:
                self.rdmc.app.current_client.bios_password = options.biospassword
        try:
            failure = False
            commit_opp = self.rdmc.app.commit()
            for path in commit_opp:
                if self.rdmc.opts.verbose:
                    self.rdmc.ui.printer("Changes are being made to path: %s\n" % path)
                if next(commit_opp):
                    failure = True
        except NothingSelectedError:
            raise NoChangesFoundOrMadeError("No changes found or made during commit operation.")
        else:
            if failure:
                raise FailureDuringCommitError(
                    "One or more types failed to commit. Run the "
                    "status command to see uncommitted data. "
                    "if you wish to discard failed changes refresh the "
                    "type using select with the --refresh flag."
                )

        if options.reboot:
            self.auxcommands["reboot"].run(options.reboot)
            self.auxcommands["logout"].run("")

    def run(self, line, help_disp=False):
        """Wrapper function for commit main function

        :param line: command line input
        :type line: string.
        """
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

        self.commitfunction(options)

        # Return code
        return ReturnCodes.SUCCESS

    def commitvalidation(self):
        """Commit method validation function"""

        try:
            _ = self.rdmc.app.current_client
        except:
            raise NoCurrentSessionEstablished("Please login and make setting" " changes before using commit command.")

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
