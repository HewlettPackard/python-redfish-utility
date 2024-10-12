###
# Copyright 2021-2022 Hewlett Packard Enterprise, Inc. All rights reserved.
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
""" computeopsmanagement Command for rdmc """

import time
from argparse import RawDescriptionHelpFormatter

try:
    from rdmc_helper import (
        CloudConnectFailedError,
        CloudConnectTimeoutError,
        IncompatibleiLOVersionError,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        NoCurrentSessionEstablished,
        ProxyConfigFailedError,
        ReturnCodes,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        CloudConnectFailedError,
        CloudConnectTimeoutError,
        IncompatibleiLOVersionError,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        NoCurrentSessionEstablished,
        ProxyConfigFailedError,
        ReturnCodes,
    )

from redfish.ris.ris import SessionExpired


class ComputeOpsManagementCommand:
    """Main new command template class"""

    def __init__(self):
        self.ident = {
            "name": "computeopsmanagement",
            "usage": "computeopsmanagement\n\n",
            "description": "Run to enable your servers to be discovered, "
            "monitored and managed through ComputeOpsManagement\n\t"
            "Example:\n\tcomputeopsmanagement connect or \n\t"
            "computeopsmanagement connect --activationkey <ACTIVATION KEY> or \n\t"
            "computeopsmanagement connect --activationkey <ACTIVATION KEY> --proxy http://proxy.abc.com:8080 or \n\t"
            "computeopsmanagement disconnect or \n\t"
            "computeopsmanagement status or \n\t"
            "computeopsmanagement status -j\n",
            "summary": "Enables the server to be discovered, monitored and managed through ComputeOpsManagement",
            "aliases": [],
            "auxcommands": [],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def proxy_config(self, proxy_server):
        """Main cloudconnect worker function

        :param proxy_server: proxy
        :type proxy_server: str.
        """
        if proxy_server != "None":
            try:
                body = dict()
                body["Oem"] = {}
                body["Oem"]["Hpe"] = {}
                body["Oem"]["Hpe"]["WebProxyConfiguration"] = {}
                proxy_body = body["Oem"]["Hpe"]["WebProxyConfiguration"]
                proxy_body["ProxyServer"] = None
                proxy_body["ProxyUserName"] = None
                proxy_body["ProxyPassword"] = None
                if "https" in proxy_server:
                    proxy_body["ProxyPort"] = 443
                else:
                    proxy_body["ProxyPort"] = 80
                if "@" in proxy_server:
                    proxy = proxy_server.split("@")
                    proxy_usr_pass = proxy[0]
                    proxy_srv_port = proxy[1]
                    if "//" in proxy_usr_pass:
                        proxy_usr_pass = proxy_usr_pass.split("//")[1]
                    if ":" in proxy_srv_port:
                        proxy = proxy_srv_port.split(":")
                        proxy_body["ProxyServer"] = proxy[0]
                        proxy_body["ProxyPort"] = int(proxy[1])
                    else:
                        proxy_body["ProxyServer"] = proxy_srv_port
                    if ":" in proxy_usr_pass:
                        proxy = proxy_usr_pass.split(":")
                        proxy_body["ProxyPassword"] = proxy[1]
                        proxy_body["ProxyUserName"] = proxy[0]
                    else:
                        proxy_body["ProxyUserName"] = proxy_usr_pass
                else:
                    proxy_srv_port = proxy_server
                    if "//" in proxy_srv_port:
                        proxy_srv_port = proxy_srv_port.split("//")[1]
                    if ":" in proxy_srv_port:
                        proxy = proxy_srv_port.split(":")
                        proxy_body["ProxyServer"] = proxy[0]
                        proxy_body["ProxyPort"] = int(proxy[1])
                    else:
                        proxy_body["ProxyServer"] = proxy_srv_port

                path = self.rdmc.app.getidbytype("NetworkProtocol.")

                if path and body:
                    self.rdmc.ui.printer("Setting Proxy configuration...\n", verbose_override=True)
                    self.rdmc.app.patch_handler(path[0], body, service=False, silent=True)
            except:
                raise ProxyConfigFailedError("Setting Proxy Server Configuration Failed.\n")
        else:
            try:
                body = dict()
                body["Oem"] = {}
                body["Oem"]["Hpe"] = {}
                body["Oem"]["Hpe"]["WebProxyConfiguration"] = {}
                proxy_body = body["Oem"]["Hpe"]["WebProxyConfiguration"]
                proxy_body["ProxyServer"] = ""
                proxy_body["ProxyPort"] = None
                proxy_body["ProxyUserName"] = ""
                proxy_body["ProxyPassword"] = None
                path = self.rdmc.app.getidbytype("NetworkProtocol.")

                if path and body:
                    self.rdmc.ui.printer("Clearing Proxy configuration...\n", verbose_override=True)
                    self.rdmc.app.patch_handler(path[0], body, service=False, silent=True)
            except:
                raise ProxyConfigFailedError("Clearing Proxy Server Configuration Failed.\n")

    def get_cloud_status(self):
        path = self.rdmc.app.typepath.defs.managerpath
        resp = self.rdmc.app.get_handler(path, service=False, silent=True)
        if resp.status != 200:
            raise SessionExpired("Invalid session. Please logout and log back in or include credentials.")
        status = resp.dict["Oem"]["Hpe"]["CloudConnect"]["CloudConnectStatus"]
        return status

    def connect_cloud(self, activationkey=None):
        """cloud connect function

        :param activationkey: activation key
        :type activationkey: str.
        """
        status = self.get_cloud_status()
        if status == "Connected":
            self.rdmc.ui.printer("Warning: ComputeOpsManagement is already connected.\n")
            return ReturnCodes.SUCCESS
        body = dict()
        # Temporary
        # body['CloudActivateURL'] = "https://qa-devices.rugby.hpeserver.management/inventory/compute-provision"
        if activationkey:
            body["ActivationKey"] = activationkey
        else:
            body = {}
        path = self.rdmc.app.typepath.defs.managerpath + "Actions" + self.rdmc.app.typepath.defs.oempath
        path = path + "/HpeiLO.EnableCloudConnect"
        try:
            if path:
                self.rdmc.ui.printer("Connecting to ComputeOpsManagement...", verbose_override=True)
                self.rdmc.app.post_handler(path, body, service=False, silent=True)
        except:
            raise CloudConnectFailedError("ComputeOpsManagement connection Failed.\n")
        start_time = time.time()
        allowed_seconds = 120
        time_increment = 5
        i = 1
        while True:
            # time.sleep(time_increment * i)
            time.sleep(time_increment)
            current_time = time.time()
            elapsed_time = current_time - start_time
            if elapsed_time > allowed_seconds:
                self.rdmc.ui.printer("\n")
                raise CloudConnectTimeoutError(
                    "ComputeOpsManagement connection timed out, Please check the "
                    "activation key and network or proxy settings and try again.\n"
                )
            else:
                status = self.get_cloud_status()
                # self.rdmc.ui.printer("ComputeOpsManagement connection status is %s.\n" % status)
                if status == "Connected":
                    # Check again after 10 seconds before breaking the loop
                    time.sleep(10)
                    status = self.get_cloud_status()
                    if status == "Connected":
                        self.rdmc.ui.printer("\n")
                        self.rdmc.ui.printer("ComputeOpsManagement connection is successful.\n")
                        break
                # If connection has failed while checking waiting for success message
                if status == "ConnectionFailed":
                    self.rdmc.ui.printer("\n")
                    raise CloudConnectFailedError(
                        "ComputeOpsManagement connection Failed. Please check the "
                        "activation key and network or proxy settings and try again.\n"
                    )
                else:
                    self.rdmc.ui.printer("..")
                    i = i + 1

    def disconnect_cloud(self):
        """cloud disconnect function"""
        cloud_status = self.get_cloud_status()
        if cloud_status == "Connected" or cloud_status == "ConnectionFailed":
            path = self.rdmc.app.typepath.defs.managerpath + "Actions" + self.rdmc.app.typepath.defs.oempath
            path = path + "/HpeiLO.DisableCloudConnect"
            body = dict()
            try:
                if path:
                    self.rdmc.ui.printer("Disconnecting ComputeOpsManagement...\n", verbose_override=True)
                    self.rdmc.app.post_handler(path, body)
                    time.sleep(10)
                    cloud_status = self.get_cloud_status()
                    if cloud_status == "NotEnabled":
                        self.rdmc.ui.printer("The operation completed successfully.\n")
            except:
                raise CloudConnectFailedError("ComputeOpsManagement is not disconnected.\n")
        else:
            self.rdmc.ui.printer(
                "Warning: ComputeOpsManagement is not at all connected.\n",
                verbose_override=True,
            )

    def cloud_status(self, json=False):
        """cloud connect function

        :param json: json
        :type json: bool
        """
        path = self.rdmc.app.typepath.defs.managerpath
        resp = self.rdmc.app.get_handler(path, service=False, silent=True)
        if resp.status != 200:
            raise SessionExpired("Invalid session. Please logout and log back in or include credentials.")
        cloud_info = resp.dict["Oem"]["Hpe"]["CloudConnect"]
        output = "------------------------------------------------\n"
        output += "ComputeOpsManagement connection status\n"
        output += "------------------------------------------------\n"
        output += "ComputeOpsManagement Status : %s\n" % (cloud_info["CloudConnectStatus"])
        if cloud_info["CloudConnectStatus"] != "NotEnabled":
            if "CloudActivateURL" in cloud_info:
                output += "CloudActivateURL : %s\n" % (cloud_info["CloudActivateURL"])
            if "ActivationKey" in cloud_info:
                output += "ActivationKey : %s\n" % (cloud_info["ActivationKey"])
        if not json:
            self.rdmc.ui.printer(output, verbose_override=True)
        else:
            self.rdmc.ui.print_out_json(cloud_info)

    def run(self, line, help_disp=False):
        """Wrapper function for cloudconnect main function

        :param line: command line input
        :type line: string.
        :param help_disp: display help flag
        :type line: bool.
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

        self.cmdbase.login_select_validation(self, options)
        if not self.rdmc.app.redfishinst:
            raise NoCurrentSessionEstablished("Please login to iLO and retry the command")

        ilo_ver = self.rdmc.app.getiloversion()
        if ilo_ver < 5.247:
            raise IncompatibleiLOVersionError(
                "ComputeOpsManagement Feature is only available with iLO 5 version 2.47 or higher.\n"
            )

        # validation checks
        self.cloudconnectvalidation(options)
        if options.command:
            if options.command.lower() == "connect":
                if options.proxy:
                    self.proxy_config(options.proxy)
                if options.activationkey:
                    self.connect_cloud(activationkey=options.activationkey)
                elif not options.activationkey:
                    self.connect_cloud()
                else:
                    raise InvalidCommandLineError(
                        "Activation Key %s is not alphanumeric or not of length 32." % str(options.activationkey)
                    )
            elif options.command.lower() == "disconnect":
                self.disconnect_cloud()
            elif options.command.lower() == "status":
                if options.json:
                    self.cloud_status(json=True)
                else:
                    self.cloud_status()
            else:
                raise InvalidCommandLineError("%s is not a valid option for this " "command." % str(options.command))
        else:
            raise InvalidCommandLineError(
                "Please provide either connect, disconnect or status as additional subcommand."
                " For help or usage related information, use -h or --help"
            )
        # logout routine
        self.cmdbase.logout_routine(self, options)
        # Return code
        return ReturnCodes.SUCCESS

    def cloudconnectvalidation(self, options):
        """new command method validation function"""
        # Check if Cloud Connect feature is enabled in iLO.
        path = self.rdmc.app.typepath.defs.managerpath
        resp = self.rdmc.app.get_handler(path, service=True, silent=True)
        if resp.status == 200:
            oem_actions = resp.dict["Oem"]["Hpe"]["Actions"]
            # print(oem_actions)
            if "#HpeiLO.EnableCloudConnect" not in oem_actions or "#HpeiLO.DisableCloudConnect" not in oem_actions:
                raise CloudConnectFailedError("ComputeOpsManagement is disabled in this iLO.\n")

    def definearguments(self, customparser):
        """Wrapper function for new command main function

        :param customparser: command line input
        :type customparser: parser.
        """
        if not customparser:
            return

        self.cmdbase.add_login_arguments_group(customparser)
        subcommand_parser = customparser.add_subparsers(dest="command")
        connect_help = "To connect to ComputeOpsManagement\n"
        # connect sub-parser
        connect_parser = subcommand_parser.add_parser(
            "connect",
            help=connect_help,
            description=connect_help + "\n\tExample:\n\tcomputeopsmanagement connect or"
            "\n\tcomputeopsmanagement connect --proxy http://proxy.abc.com:8080 or "
            "\n\tcomputeopsmanagement connect --proxy None or "
            "\n\tcomputeopsmanagement connect --activationkey 123456789EFGA or "
            "\n\tcomputeopsmanagement connect --activationkey 123456789EFGA --proxy http://proxy.abc.com:8080 or "
            "\n\tcomputeopsmanagement connect --activationkey 123456789EFGA --proxy None",
            formatter_class=RawDescriptionHelpFormatter,
        )
        connect_parser.add_argument(
            "--activationkey",
            dest="activationkey",
            help="activation key is optional for connecting",
            required=False,
            type=str,
            default=None,
        )
        connect_parser.add_argument(
            "--proxy",
            dest="proxy",
            help="to set or clear proxy while connecting",
            type=str,
            default=None,
        )
        self.cmdbase.add_login_arguments_group(connect_parser)
        status_help = "To check the ComputeOpsManagement connection status\n"
        status_parser = subcommand_parser.add_parser(
            "status",
            help=status_help,
            description=status_help + "\n\tExample:\n\tcomputeopsmanagement status or "
            "\n\tcomputeopsmanagement status -j",
            formatter_class=RawDescriptionHelpFormatter,
        )
        status_parser.add_argument(
            "-j",
            "--json",
            dest="json",
            help="to print in json format",
            action="store_true",
            default=False,
        )
        self.cmdbase.add_login_arguments_group(status_parser)
        disconnect_help = "To disconnect from ComputeOpsManagement\n"
        disconnect_parser = subcommand_parser.add_parser(
            "disconnect",
            help=disconnect_help,
            description=disconnect_help + "\n\tExample:\n\tcomputeopsmanagement disconnect",
            formatter_class=RawDescriptionHelpFormatter,
        )
        self.cmdbase.add_login_arguments_group(disconnect_parser)
