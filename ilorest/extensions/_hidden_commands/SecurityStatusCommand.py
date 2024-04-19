###
# Copyright 2016 Hewlett Packard Enterprise, Inc. All rights reserved.
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
""" Security Status Command for rdmc """

import struct
from argparse import SUPPRESS
from ctypes import POINTER, c_char_p, c_ubyte, create_string_buffer

try:
    from rdmc_base_classes import RdmcCommandBase
    from rdmc_helper import Encryption, InvalidCommandLineErrorOPTS, ReturnCodes
except ImportError:
    from ilorest.rdmc_base_classes import RdmcCommandBase
    from ilorest.rdmc_helper import Encryption, InvalidCommandLineErrorOPTS, ReturnCodes
from redfish.hpilo.risblobstore2 import BlobStore2
from redfish.hpilo.rishpilo import BlobReturnCodes, HpIloChifAccessDeniedError


class SecurityStatusCommand(RdmcCommandBase):
    """Security Status class command"""

    def __init__(self):
        self.ident = {
            "name": "securitystatus",
            "usage": None,
            "description": "Security status example:\n\tsecuritystatus",
            "summary": "command to retrieve the current system security status and validate " "credentials via chif.",
            "aliases": [],
            "auxcommands": [],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """Access blobstore directly and perform desired function

        :param line: string of arguments passed in
        :type line: str.
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

        if bool(options.user) ^ bool(options.password):
            self.rdmc.ui.error("Credentials: Missing\n")

        elif options.user and options.password:
            if options.encode:
                options.user = Encryption.decode_credentials(options.user)
                if isinstance(options.user, bytes):
                    options.user = options.user.decode("utf-8")
                options.password = Encryption.decode_credentials(options.password)
                if isinstance(options.password, bytes):
                    options.password = options.password.decode("utf-8")

            result = self.validate_creds(options.user, options.password)
            # self.rdmc.ui.printer("Validate Creds is {}...\n".format(result))
            if result:
                secstate = BlobStore2().get_security_state()
                if isinstance(secstate, bytes):
                    if secstate == b"\x00":
                        state = struct.unpack("B", secstate)
                        state = str(state).strip(",( )")
                        self.rdmc.ui.printer("Security State is {}\n".format(state))
                    else:
                        secstate = secstate.decode("utf-8")
                        self.rdmc.ui.printer("Security State is {}\n".format(secstate))
                else:
                    self.rdmc.ui.printer("Security State is {}\n".format(secstate))
                self.rdmc.ui.printer("Credentials: Valid\n")
            else:
                self.rdmc.ui.error("Credentials: Invalid\n")

        else:
            secstate = BlobStore2().get_security_state()
            if isinstance(secstate, bytes):
                if secstate == b"\x00":
                    state = struct.unpack("B", secstate)
                    state = str(state).strip(",( )")
                    self.rdmc.ui.printer("Security State is {}\n".format(state))
                else:
                    secstate = secstate.decode("utf-8")
                    self.rdmc.ui.printer("Security State is {}\n".format(secstate))
            else:
                self.rdmc.ui.printer("Security State is {}\n".format(secstate))

        return ReturnCodes.SUCCESS

    def validate_creds(self, user, passwrd):
        """Validates credentials via CHIF

        :param user: username to validate
        :type user: str.
        :param passwrd: password to validate
        :type passwrd: str.
        """

        valid = False
        dll = BlobStore2.gethprestchifhandle()
        dll.ChifInitialize(None)
        sec_support = dll.ChifGetSecuritySupport()
        if sec_support <= 1:
            dll.ChifEnableSecurity()
        dll.initiate_credentials.argtypes = [c_char_p, c_char_p]
        dll.initiate_credentials.restype = POINTER(c_ubyte)

        usernew = create_string_buffer(user.encode("utf-8"))
        passnew = create_string_buffer(passwrd.encode("utf-8"))

        dll.initiate_credentials(usernew, passnew)
        credreturn = dll.ChifVerifyCredentials()
        if credreturn == 0:
            valid = True
        else:
            valid = False
            if not credreturn == BlobReturnCodes.CHIFERR_AccessDenied:
                raise HpIloChifAccessDeniedError(
                    "Error %s - Chif Access Denied occurred while trying " "to open a channel to iLO." % credreturn
                )

        BlobStore2.unloadchifhandle(dll)
        return valid

    def definearguments(self, customparser):
        """Wrapper function for new command main function

        :param customparser: command line input
        :type customparser: parser.
        """
        if not customparser:
            return

        customparser.add_argument(
            "-u",
            "--user",
            dest="user",
            help="If you are not logged in yet, including this flag along"
            " with the password and URL flags can be used to login to a"
            " server in the same command."
            "",
            default=None,
        )
        customparser.add_argument(
            "-p",
            "--password",
            dest="password",
            help="""Use the provided iLO password to log in.""",
            default=None,
        )
        customparser.add_argument(
            "-e",
            "--enc",
            dest="encode",
            action="store_true",
            help=SUPPRESS,
            default=False,
        )
