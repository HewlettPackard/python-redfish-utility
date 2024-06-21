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
""" New Command for RDMC """

import json
import struct

import redfish.ris

try:
    from rdmc_helper import (
        IncompatibleiLOVersionError,
        InvalidCommandLineErrorOPTS,
        NoContentsFoundForOperationError,
        ReturnCodes,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        IncompatibleiLOVersionError,
        InvalidCommandLineErrorOPTS,
        NoContentsFoundForOperationError,
        ReturnCodes,
    )

__filename__ = "smbios.json"


class SMBiosCommand:
    """Main smbios command class"""

    def __init__(self):
        self.ident = {
            "name": "smbios",
            "usage": None,
            "description": "Run to get the smbios for the system." "\n\texample write smbios data to file: smbios",
            "summary": "Gets the smbios for the currently logged in server and "
            "write results to a file in json format.",
            "aliases": [],
            "auxcommands": [],
        }
        self.rdmc = None
        self.filename = None

    def smbiosfunction(self, options):
        """Main smbios command worker function

        :param options: command options
        :type options: options.
        """

        sysresp = self.rdmc.app.get_handler(self.rdmc.app.typepath.defs.systempath, silent=True, service=True)

        try:
            path = sysresp.dict["Oem"][self.rdmc.app.typepath.defs.oemhp]["SMBIOS"]["extref"]
        except:
            raise NoContentsFoundForOperationError("Unable to find ComputerSystems")

        resp = self.rdmc.app.get_handler(path, silent=True, service=True)

        if resp and resp.status == 200:
            data = self.unpackdata(resp.ori)
            data = {"smbios data": data}

            outfile = open(self.filename, "w")
            outfile.write(json.dumps(data, indent=2, cls=redfish.ris.JSONEncoder, sort_keys=True))
            outfile.close()

            self.rdmc.ui.printer("Smbios saved to: %s\n" % self.filename)
        else:
            raise NoContentsFoundForOperationError("Unable to find smbios.")

        self.cmdbase.logout_routine(self, options)
        # Return code
        return ReturnCodes.SUCCESS

    def unpackdata(self, data):
        """Unpacks and returns json formatted data

        :param data: data to unpack
        :type data: string.
        """

        dataptr = 0
        fulldata = []
        if not isinstance(data, (bytes, bytearray)):
            data = data.encode()

        try:
            while True:
                record_header = struct.unpack_from("BBH", data[dataptr : dataptr + 4])

                record_type = record_header[0]
                record_length = record_header[1]
                record_handle = record_header[2]

                # skip to the strings
                dataptr += record_length

                # read strings from end of record
                record_strings = []

                while True:
                    tempstr = ""

                    while data[dataptr] != 0:
                        tempstr += chr(data[dataptr])
                        dataptr += 1

                    dataptr += 1

                    if len(tempstr) == 0:
                        break

                    record_strings.append(str(tempstr))

                while data[dataptr] == 0:
                    dataptr += 1

                fulldata.append(
                    {
                        "Type": str(record_type),
                        "Length": str(record_length),
                        "Handle": str(record_handle),
                    }
                )

                if len(record_strings):
                    fulldata[-1]["Strings"] = str(record_strings)
        except IndexError:
            pass
        return fulldata

    def run(self, line, help_disp=False):
        """Wrapper function for smbios command main function

        :param line: command line input
        :type line: string.
        :param help_disp: display help flag
        :type line: bool.
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

        if self.rdmc.app.typepath.url:
            if "http" not in self.rdmc.app.typepath.url:
                options.logout = True
                self.cmdbase.logout_routine(self, options)
        else:
            options.logout = True
            self.cmdbase.logout_routine(self, options)
        self.smbiosvalidation(options)

        if not self.rdmc.app.typepath.flagiften:
            raise IncompatibleiLOVersionError("smbios command is RedFish only.")

        self.smbiosfunction(options)
        # Return code
        return ReturnCodes.SUCCESS

    def smbiosvalidation(self, options):
        """smbios command method validation function

        :param options: command options
        :type options: options.
        """
        self.cmdbase.login_select_validation(self, options)

        # filename validations and checks
        self.filename = None

        if options.filename:
            self.filename = options.filename[0]

        if not self.filename:
            self.filename = __filename__

    def definearguments(self, customparser):
        """Wrapper function for smbios command main function

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
            help="Use this flag if you wish to use a different"
            " filename than the default one. The default filename is"
            " %s." % __filename__,
            action="append",
            default=None,
        )
