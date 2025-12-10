###
# Copyright 2016-2024 Hewlett Packard Enterprise, Inc. All rights reserved.
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
"""DetectiLO Command for RDMC"""
from redfish.hpilo.vnichpilo import AppAccount
from redfish.rest.connections import ChifDriverMissingOrNotFound, VnicNotEnabledError
import requests

try:
    from rdmc_helper import (
        UI,
        InvalidCommandLineErrorOPTS,
        ReturnCodes,
        GenBeforeLoginError,
        VnicExistsError,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        UI,
        InvalidCommandLineErrorOPTS,
        ReturnCodes,
        GenBeforeLoginError,
        VnicExistsError,
    )


class DetectiLOCommand:
    """Constructor"""

    def __init__(self):
        self.ident = {
            "name": "detectilo",
            "usage": None,
            "description": "Provides the iLO generation of the currently logged-in server.\n\n"
            "If --ignore_session is specified, it retrieves the iLO generation of the IP mentioned in --url\n"
            "or attempts to determine the iLO generation of the current server.",
            "summary": "Retrieves the iLO generation of the server.",
            "aliases": [],
            "auxcommands": [],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """Main get worker function

        :param line: command line input
        :type line: string.
        """
        if help_disp:
            line.append("-h")
            try:
                (_, _) = self.rdmc.rdmc_parse_arglist(self, line)
            except:
                return ReturnCodes.SUCCESS
            return ReturnCodes.SUCCESS
        try:
            (options, _) = self.rdmc.rdmc_parse_arglist(self, line)
        except (InvalidCommandLineErrorOPTS, SystemExit):
            if ("-h" in line) or ("--help" in line):
                return ReturnCodes.SUCCESS
            else:
                raise InvalidCommandLineErrorOPTS("")

        if not options.ignore_session and not options.url:
            client = self.detectilovalidation(options)
            if client:
                if not options.json:
                    self.rdmc.ui.printer("Using the current logged in session information.\n")
                if not any(substring in client.base_url for substring in ("blobstore", "16.1.15.1")):
                    options.url = client.base_url.split("/")[-1]

        if options.url:
            if not options.json:
                self.rdmc.ui.printer("Detecting iLO for remote device %s\n" % options.url)
            retcode = self.detect_remote_ilotype(options)
        else:
            if not options.json:
                self.rdmc.ui.printer("Detecting iLO for this server.\n")
            retcode = self.detect_local_ilotype(options)
        return retcode

    def detectilovalidation(self, options):
        """detectilo validation function

        :param options: command line options
        :type options: list.
        """
        return self.rdmc.login_select_validation(self, options)

    def detect_remote_ilotype(self, options):
        try:
            path = "https://" + options.url + "/redfish/v1"
            data = requests.get(path, verify=False)
            json_data = data.json()
            Oem_Hpe = json_data["Oem"]["Hpe"]
            if "ManagerType" in Oem_Hpe["Manager"][0]:
                ilo_ver = int(Oem_Hpe["Manager"][0]["ManagerType"].split(" ")[1])
            else:
                manager_data = Oem_Hpe["Moniker"]
                ilo_ver = int(manager_data["PRODGEN"].split(" ")[1])
        except Exception as excp:
            raise GenBeforeLoginError(
                "An error occurred while retrieving the iLO generation. "
                "Please ensure that the virtual NIC is enabled for iLO7 based "
                "servers, or that the CHIF driver is installed for iLO5 "
                "and iLO6 based servers.\n"
            )

        if options.json:
            content = {"iLOType": ilo_ver}
            UI().print_out_json(content)
        else:
            self.rdmc.ui.printer("iLO Type: %s\n" % ilo_ver)

        return ReturnCodes.SUCCESS

    def detect_local_ilotype(self, options):
        app_obj = AppAccount(log_dir=self.rdmc.log_dir)
        security_state_dict = {
            0: "Error occurred while fetching the security state",
            1: "Factory",
            2: "Wipe",
            3: "Production",
            4: "HighSecurity",
            5: "FIPS",
            6: "SuiteB",
        }
        try:
            ilo_ver, sec_state = self.rdmc.app.getilover_beforelogin(app_obj)
            if options.json:
                contents = {"iLOType": str(ilo_ver)}
                if ilo_ver < 7:
                    contents["SecurityState"] = security_state_dict[sec_state]
                UI().print_out_json(contents)
            else:
                self.rdmc.ui.printer("iLO Type: %s\n" % ilo_ver)
                if ilo_ver < 7:
                    self.rdmc.ui.printer("Security State: %s\n" % security_state_dict[sec_state])
            return ReturnCodes.SUCCESS
        except ChifDriverMissingOrNotFound:
            if options.json:
                contents = {"iLOType": "5_6"}
                UI().print_out_json(contents)
            else:
                self.rdmc.ui.printer("iLO Type: Unable to find iLO generation\n")
            raise
        except VnicNotEnabledError:
            ilo_ver = 7
            if options.json:
                contents = {"iLOType": str(ilo_ver)}
                UI().print_out_json(contents)
            else:
                self.rdmc.ui.printer("iLO Type: %s\n" % ilo_ver)
            raise VnicExistsError(
                "Unable to access iLO using virtual NIC. "
                "Please ensure virtual NIC is enabled in iLO. "
                "Ensure that virtual NIC in the host OS is "
                "configured properly. Refer to documentation for more information.\n"
            )
        except Exception:
            raise GenBeforeLoginError(
                "An error occurred while retrieving the iLO generation. "
                "Please ensure that the virtual NIC is enabled for iLO7 based "
                "servers, or that the CHIF driver is installed for iLO5 and iLO6 "
                "based servers.\n"
            )

    def definearguments(self, customparser):
        """Wrapper function for new command main function
        :param customparser: command line input
        :type customparser: parser.
        """
        if not customparser:
            return

        self.cmdbase.add_login_arguments_group(customparser)

        customparser.add_argument(
            "-j",
            "--json",
            dest="json",
            action="store_true",
            help="Optionally include this flag if you wish to change the"
            " displayed output to JSON format. Preserving the JSON data"
            " structure makes the information easier to parse.",
            default=False,
        )

        customparser.add_argument(
            "--ignore_session",
            dest="ignore_session",
            action="store_true",
            help="Optionally include this flag if you wish to ignore any"
            " session that has been logged in, in order to perform detectilo",
            default=False,
        )
