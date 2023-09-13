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
# ##

# -*- coding: utf-8 -*-
""" Download Component Command for rdmc """

import ctypes
import os
import time
from ctypes import c_char_p, c_int

try:
    from rdmc_helper import (
        DownloadError,
        IncompatibleiLOVersionError,
        InvalidCommandLineErrorOPTS,
        InvalidFileInputError,
        ReturnCodes,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        DownloadError,
        IncompatibleiLOVersionError,
        InvalidCommandLineErrorOPTS,
        InvalidFileInputError,
        ReturnCodes,
    )


def human_readable_time(seconds):
    """Returns human readable time

    :param seconds: Amount of seconds to parse.
    :type seconds: string.
    """
    seconds = int(seconds)
    hours = seconds / 3600
    seconds = seconds % 3600
    minutes = seconds / 60
    seconds = seconds % 60

    return "{:02.0f} hour(s) {:02.0f} minute(s) {:02.0f} second(s) ".format(hours, minutes, seconds)


class DownloadComponentCommand:
    """Main download component command class"""

    def __init__(self):
        self.ident = {
            "name": "downloadcomp",
            "usage": None,
            "description": "Run to "
            "download the file from path\n\texample: downloadcomp "
            "/fwrepo/filename.exe --outdir <output location>"
            "download the file by name\n\texample: downloadcomp "
            "filename.exe --outdir <output location>",
            "summary": "Downloads components/binaries from the iLO Repository.",
            "aliases": [],
            "auxcommands": [],
        }

    def run(self, line, help_disp=False):
        """Wrapper function for download command main function

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

        self.downloadcomponentvalidation(options)

        if self.rdmc.app.typepath.defs.isgen9:
            raise IncompatibleiLOVersionError("iLO Repository commands are " "only available on iLO 5.")

        start_time = time.time()
        ret = ReturnCodes.FAILED_TO_DOWNLOAD_COMPONENT

        self.rdmc.ui.printer("Downloading component, this may take a while...\n")

        if "blobstore" in self.rdmc.app.current_client.base_url:
            ret = self.downloadlocally(options)
        else:
            ret = self.downloadfunction(options)

        self.rdmc.ui.printer("%s\n" % human_readable_time(time.time() - start_time))

        self.cmdbase.logout_routine(self, options)
        # Return code
        return ret

    def downloadfunction(self, options):
        """Main download command worker function

        :param options: command options (argparse)
        :type options: options.
        """
        filename = options.component.rsplit("/", 1)[-1]

        if not options.outdir:
            destination = os.path.join(os.getcwd(), filename)
        else:
            destination = os.path.join(options.outdir, filename)

        if not os.path.exists(os.path.join(os.path.split(destination)[0])):
            raise InvalidFileInputError("Invalid output file location.")
        if not os.access(os.path.join(os.path.split(destination)[0]), os.W_OK):
            raise InvalidFileInputError("File location is not writable.")
        if os.access(destination, os.F_OK) and not os.access(destination, os.W_OK):
            raise InvalidFileInputError("Existing File cannot be overwritten.")

        if options.component[0] != "/":
            options.component = "/" + options.component

        if "fwrepo" not in options.component:
            options.component = "/fwrepo/" + options.component

        results = self.rdmc.app.get_handler(options.component, uncache=True)

        if results.status == 404:
            raise DownloadError(
                "Downloading of component %s failed, please check the component name and check if the "
                "component exists in the repository\n" % options.component
            )

        with open(destination, "wb") as local_file:
            local_file.write(results.ori)

        self.rdmc.ui.printer("Download complete\n")

        return ReturnCodes.SUCCESS

    def downloadlocally(self, options=None):
        """Used to download a component from the iLO Repo locally

        :param options: command options (argparse)
        :type options: options.
        """
        try:
            dll = self.rdmc.app.current_client.connection._conn.channel.dll
            dll.downloadComponent.argtypes = [c_char_p, c_char_p]
            dll.downloadComponent.restype = c_int

            filename = options.component.rsplit("/", 1)[-1]
            if not options.outdir:
                destination = os.path.join(os.getcwd(), filename)
            else:
                destination = os.path.join(options.outdir, filename)

            if not os.path.exists(os.path.join(os.path.split(destination)[0])):
                raise InvalidFileInputError("Invalid output file location.")
            if not os.access(os.path.join(os.path.split(destination)[0]), os.W_OK):
                raise InvalidFileInputError("File location is not writable.")
            if os.access(destination, os.F_OK) and not os.access(destination, os.W_OK):
                raise InvalidFileInputError("Existing File cannot be overwritten.")

            ret = dll.downloadComponent(
                ctypes.create_string_buffer(filename.encode("utf-8")),
                ctypes.create_string_buffer(destination.encode("utf-8")),
            )

            if ret != 0:
                self.rdmc.ui.error(
                    "Component " + filename + " download failed, please check the "
                    "component name and check if the component exists in the respository.\n"
                )
                return ReturnCodes.FAILED_TO_DOWNLOAD_COMPONENT
            else:
                self.rdmc.ui.printer("Component " + filename + " downloaded successfully.\n")
                self.rdmc.ui.printer("[200] The operation completed successfully.\n")

        except Exception as excep:
            raise DownloadError(str(excep))

        return ReturnCodes.SUCCESS

    def downloadcomponentvalidation(self, options):
        """Download command method validation function

        :param options: command options
        :type options: options.
        """
        self.rdmc.login_select_validation(self, options)

    def definearguments(self, customparser):
        """Wrapper function for download command main function

        :param customparser: command line input
        :type customparser: parser.
        """
        if not customparser:
            return

        self.cmdbase.add_login_arguments_group(customparser)

        customparser.add_argument(
            "component",
            help="""Component name (starting with path '/fwrepo/<comp name>') of the target""" """ component.""",
            metavar="[COMPONENT URI]",
        )
        customparser.add_argument(
            "--outdir",
            dest="outdir",
            help="""Output directory for saving the file.""",
            default="",
        )
