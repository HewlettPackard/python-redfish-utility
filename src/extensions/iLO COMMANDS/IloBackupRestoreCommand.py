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
""" Factory Defaults Command for rdmc """
import os

try:
    from rdmc_helper import (
        ReturnCodes,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        NoContentsFoundForOperationError,
        InvalidFileInputError,
        Encryption,
        UploadError,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        ReturnCodes,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        NoContentsFoundForOperationError,
        InvalidFileInputError,
        Encryption,
        UploadError,
    )


class IloBackupRestoreCommand:
    """Backup and restore server using iLO's .bak file"""

    def __init__(self):
        self.ident = {
            "name": "backuprestore",
            "usage": None,
            "description": "Create a .bak file. \n\tExample: backuprestore backup\n\n\t"
            "Restore a server using a .bak file. \n\texample: backuprestore "
            "restore\n\n\tNOTE: This command is designed to only restore\n\tthe "
            "machine from which the backup file was created against.\n\tIf you would like to "
            "take one configuration and apply it\n\tto multiple systems see the "
            "serverclone command.\n\tThis command is only available in remote mode.",
            "summary": "Backup and restore iLO to a server using a .bak file.",
            "aliases": ["br"],
            "auxcommands": ["LogoutCommand"],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """Main factorydefaults function

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
            if not line or line[0] == "help":
                self.parser.print_help()
                return ReturnCodes.SUCCESS
        except (InvalidCommandLineErrorOPTS, SystemExit):
            if ("-h" in line) or ("--help" in line):
                return ReturnCodes.SUCCESS
            else:
                raise InvalidCommandLineErrorOPTS("")

        if not len(args) == 1:
            raise InvalidCommandLineError("backuprestore command takes one argument.")

        self.ilobackuprestorevalidation(options)

        if "blobstore" in self.rdmc.app.current_client.base_url:
            raise InvalidCommandLineError("This command is only available remotely.")

        sessionkey = self.rdmc.app.current_client.session_key
        # sessionkey = (sessionkey).encode('ascii', 'ignore')

        if args[0].lower() == "backup":
            self.backupserver(options, sessionkey)
        elif args[0].lower() == "restore":
            self.restoreserver(options, sessionkey)
        else:
            raise InvalidCommandLineError(
                "%s is not a valid option for this " "command." % str(args[0])
            )

        self.cmdbase.logout_routine(self, options)
        # Return code
        return ReturnCodes.SUCCESS

    def backupserver(self, options, skey):
        """Create .bak file for a server

        :param options: command options
        :type options: list.
        :param skey: sessionkey of the currently logged in server
        :type skey: str.
        """
        select = "HpeiLOBackupRestoreService."
        backupfile = None
        results = self.rdmc.app.select(selector=select)

        try:
            results = results[0]
        except:
            pass

        if results:
            service = results.resp.dict
        else:
            raise NoContentsFoundForOperationError(
                "%s not found.It may not " "be available on this system." % select
            )

        backuplocation = service["BackupFileLocation"]
        backupname = backuplocation.split("/")[-1]

        postdata = []
        postdata.append(("sessionKey", skey))

        if options.fpass:
            postdata.append(("password", options.fpass))
        self.rdmc.ui.printer("Downloading backup file %s..." % backupname)
        backupfile = self.rdmc.app.post_handler(
            backuplocation, postdata, service=True, silent=True
        )

        if backupfile:
            self.rdmc.ui.printer("Download complete.\n")
            outfile = open(backupname, "wb")
            outfile.write(backupfile.ori)
            outfile.close()
        else:
            raise NoContentsFoundForOperationError("Unable to download file.\n")

    def restoreserver(self, options, skey):
        """Use a .bak file to restore a server

        :param options: command options
        :type options: list.
        :param skey: sessionkey of the currently logged in server
        :type skey: str.
        """

        select = "HpeiLOBackupRestoreService."

        if options.filename:
            filename = options.filename[0]
        else:
            files = []
            files = [
                f for f in os.listdir(".") if os.path.isfile(f) and f.endswith(".bak")
            ]
            if files and len(files) > 1:
                raise InvalidFileInputError(
                    "More than one .bak file found in "
                    "the current directory. Please specify "
                    "a file using the -f option."
                )
            elif not files:
                raise InvalidFileInputError(
                    "No .bak file found in current "
                    "directory. Please specify a file using the -f option."
                )
            else:
                filename = files[0]

        results = self.rdmc.app.select(selector=select)

        try:
            results = results[0]
        except:
            pass

        if results:
            service = results.resp.dict
        else:
            raise NoContentsFoundForOperationError(
                "%s not found.It may not " "be available on this system." % select
            )
        restorelocation = service["HttpPushUri"]
        postdata = []

        with open(filename, "rb") as fle:
            bakfile = fle.read()
        postdata.append(("sessionKey", skey))
        if options.fpass:
            postdata.append(("password", options.fpass))
        postdata.append(("file", (filename, bakfile, "application/octet-stream")))
        if isinstance(skey, bytes):
            skey = skey.decode("utf-8")
        resp = self.rdmc.app.post_handler(
            restorelocation,
            postdata,
            service=False,
            silent=True,
            headers={"Cookie": "sessionKey=" + skey},
        )

        if not resp.status == 200:
            if resp.ori == "invalid_restore_password":
                raise UploadError(
                    "Invalid or no password supplied during restore. Please "
                    "supply the password used during creation of the backup file."
                )
            else:
                raise UploadError("Error while uploading the backup file.")
        else:
            self.rdmc.ui.printer(
                "Restore in progress. iLO while be unresponsive while the "
                "restore completes.\nYour session will be terminated.\n"
            )
            self.auxcommands["logout"].run("")

    def ilobackuprestorevalidation(self, options):
        """factory defaults validation function

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
            "-f",
            "--filename",
            dest="filename",
            help="Use this flag to specify which backup file to restore. By "
            "default the commmand will try to find a .bak file in the current "
            "working directory.",
            action="append",
            default=None,
        )
        customparser.add_argument(
            "--filepass",
            dest="fpass",
            help="Optionally use the provided password when creating the "
            "backup file. The same password must be used for restoring.",
            default=None,
        )
