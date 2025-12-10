###
# Copyright 2021-2025 Hewlett Packard Enterprise, Inc. All rights reserved.
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
"""computeopsmanagement Command for rdmc"""


import json
import time
import os
from argparse import RawDescriptionHelpFormatter
from datetime import datetime
from ipaddress import ip_address
from typing import Dict, Any

import requests
import urllib3
from requests.exceptions import ConnectionError, Timeout, RequestException
from urllib3.util.retry import Retry


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
        LOGGER,
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
        LOGGER,
    )

from redfish.ris.ris import SessionExpired
from .data.InputTemplate import template

ErrorMapping = {
    "ProxySettingsInvalid_RDA": "Could not connect to HPE using the provided web proxy. "
    "Ensure that the proxy details are correct. Additionally,"
    " you can set proxy using the --proxy parameter in the computeopsmanagement command.\n",
    "ProxyOrFirewallError_RDA": "The proxy or firewall in not configured properly."
    " Please check the respective values. Additionally, "
    "you can set proxy using the --proxy parameter in the computeopsmanagement command.\n",
    "iLOTimeError_RDA": "Could not obtain an identity for this server "
    "to connect to Compute Ops Management due to a "
    "incorrect iLO system time. Please update time on RBSU.\n",
    "iLOTimeError_COM": "Could not verify the identity of Compute Ops Management. "
    "This could be due to an incorrect iLO system time. "
    "Contact HPE support if the problem persists.\n",
    "ProxyOrFirewallError_COM": "Could not connect to Compute Ops Management due to proxy issue.\n",
    "ProxySettingsInvalid_COM": "Could not connect to HPE using the "
    "provided web proxy. Ensure that the proxy details are correct.\n",
    "ActivationKeyRequired": "An activation key is required in order "
    "to connect to HPE Compute Ops Management. Please enter an activation key.\n",
    "InvalidActivationKey": "The activation key entered is invalid. "
    "Please check the value entered. If the problem persists, contact HPE Support.\n",
    "ExpiredActivationKey": "The activation key entered is expired. "
    "Please enter a valid activation key. "
    "If the problem persists, contact HPE Support.\n ",
    "WrongiLOVersion": (
        "Unsupported iLO version. Upgrade to the latest iLO version " "to use HPE Compute Ops Management.\n"
    ),
    "DeviceAssignFailed": "Device assignment has failed. Visit HPE GreenLake, select Device tab and ensure"
    " this device is not already added to another Compute Ops Management instance.\n",
    "DeviceClaimUnauthorized": "Device claim is unauthorized. Contact your HPE GreenLake administrator to "
    "verify that you have the right permissions to add "
    "a device to HPE GreenLake device inventory.\n",
    "DeviceNotFound": "Device not found. Contact HPE Support to resolve this issue.\n",
    "InternalError_RDA": "Unknown error. Reset iLO and re-try connecting."
    " Contact HPE support if the problem persists.\n",
    "InternalError_COM": "Unknown error. Reset iLO and re-try connecting. "
    "Contact HPE support if the problem persists.\n",
    "ExternalError_RDA": "External error. Retry after some time. Contact HPE support if the problem persists.\n",
    "ExternalError_COM": "External error. Retry after some time. Contact HPE support if the problem persists.\n",
    "DisabledByCOM": "Disabled by Compute Ops Management.\n",
}

Cloudconnectstatus = {
    # Network Status Config
    "Initializing": "Cloud connection setup is in progress. Please wait a moment.",
    "IPAddressNotConfigured": "iLO doesn't have an IP address configured. Please check network settings.",
    "DNSResolutionError": "Unable to resolve DNS. Please verify your DNS configuration.",
    "Configured": "Configured.",
    "NotTested": "Not tested yet.",
    "InternalError": "iLO ran into an internal issue while trying "
    "to connect to the cloud. Please try again or contact support.",
    # Web Connectivity
    "iLOTimeError": "The iLO time settings are incorrect. Please synchronize time to proceed.",
    "ProxyOrFirewallError": "iLO couldn't reach the endpoint. Check your proxy or firewall settings.",
    "Connected": "Connected.",
    "ProxySettingsInvalid": "Proxy settings appear to be invalid. Please review and update them.",
    "ExternalError": "There was an issue with the external cloud service. Please try again later.",
    # iLO Configuration for Cloud Connect
    "ActivationKeyRequired": "An activation key is needed to enable cloud connectivity. Please provide a valid key.",
    "WrongiLOVersion": "This iLO version doesn't support the requested operation. Please update iLO firmware.",
    "InvalidActivationKey": "The activation key provided is invalid. Please check and enter a valid one.",
    "DeviceAssignFailed": "iLO was unable to register the device with the cloud. Please try again later.",
    "DeviceClaimUnauthorized": "Device claim failed due to insufficient authorization. Please check credentials.",
    "DeviceNotFound": "The device couldn't be found in the cloud service. Ensure the activation key is correct.",
    "DisabledByCOM": "Cloud connectivity has been disabled by COM settings.",
}

DEFAULT_TEMPLATE_FILE_NAME = "multiconnect_input_template.json"
DNS_SERVER_EXCLUSION_LIST = ["0.0.0.0", "::"]


class ComputeOpsManagementCommand:
    """Main new command template class"""

    def __init__(self):
        self.ident = {
            "name": "computeopsmanagement",
            "usage": "computeopsmanagement\n\n",
            "description": (
                "Run to enable your servers to be discovered, monitored and managed through ComputeOpsManagement\n\t"
                "Example:\n\t"
                "computeopsmanagement connect\n\t"
                "computeopsmanagement connect --activationkey <ACTIVATION KEY>\n\t"
                "computeopsmanagement connect --activationkey <ACTIVATION KEY> --proxy http://proxy.abc.com:8080\n\t"
                "computeopsmanagement disconnect\n\t"
                "computeopsmanagement multiconnect --input_file_json_template\n\t"
                "computeopsmanagement multiconnect --input_file servers.json\n\t"
                "computeopsmanagement multiconnect --input_file servers.json --allow_ilo_reset\n\t"
                "computeopsmanagement multiconnect --input_file servers.json --output report.json\n\t"
                "computeopsmanagement multiconnect --input_file servers.json --output report.json --allow_ilo_reset\n\t"
                "computeopsmanagement status\n\t"
                "computeopsmanagement status -j\n\n"
            ),
            "summary": (
                "Enables the server to be discovered, monitored and managed "
                "through ComputeOpsManagement, Also gives bulk onboarding of iLOs to COM."
            ),
            "aliases": [],
            "auxcommands": ["EthernetCommand"],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def resolve_ilo_config(self, config_json_path: str) -> Dict[str, Dict[str, Any]]:
        """Load config from a JSON file and resolve iLO configuration as a dict keyed by IP."""
        with open(config_json_path, "r") as f:
            config_json = json.load(f)

        common = config_json.get("commonSettings", {})
        common_dns = common.get("network", {}).get("dns", [])
        common_ntp = common.get("network", {}).get("ntp", [])
        common_proxy = common.get("proxy", {})
        common_auth = {
            "username": common.get("iloAuthentication", {}).get("iloUser"),
            "password": common.get("iloAuthentication", {}).get("iloPassword"),
        }

        resolved = {}

        def build_config(
            ip_str: str,
            entry: Dict[str, Any],
            default_dns,
            default_ntp,
            skip_dns=False,
            skip_ntp=False,
            skip_proxy=False,
        ):
            network = entry.get("network", {})
            dns = [] if skip_dns else network.get("dns", default_dns)
            ntp = [] if skip_ntp else network.get("ntp", default_ntp)
            return {
                "ip": ip_str,
                "dns": dns,
                "ntp": ntp,
                "skipDns": skip_dns,
                "skipNtp": skip_ntp,
                "skipProxy": skip_proxy,  # Consistent naming without underscore
                "proxy": common_proxy,
                "auth": common_auth,
            }

        individual_entries = config_json.get("targets", {}).get("ilos", {}).get("individual", [])
        for entry in individual_entries:
            ip = entry["ip"]
            skip_dns = entry.get("skipDns", False)
            skip_ntp = entry.get("skipNtp", False)
            skip_proxy = entry.get("skipProxy", False)  # Read from input as "skipProxy" (user-facing)
            config = build_config(ip, entry, common_dns, common_ntp, skip_dns, skip_ntp, skip_proxy)
            resolved[ip] = config

        range_entries = config_json.get("targets", {}).get("ilos", {}).get("ranges", [])
        for range_entry in range_entries:
            start_ip = ip_address(range_entry["start"])
            end_ip = ip_address(range_entry["end"])
            skip_dns = range_entry.get("skipDns", False)
            skip_ntp = range_entry.get("skipNtp", False)
            skip_proxy = range_entry.get("skipProxy", False)  # Read from input as "skipProxy" (user-facing)
            network = range_entry.get("network", {})
            range_dns = [] if skip_dns else network.get("dns", common_dns)
            range_ntp = [] if skip_ntp else network.get("ntp", common_ntp)

            # Optimize: Convert to int once, iterate directly, convert back to string once per IP
            start_int = int(start_ip)
            end_int = int(end_ip)
            for ip_int in range(start_int, end_int + 1):
                ip_str = str(ip_address(ip_int))
                config = build_config(ip_str, {}, range_dns, range_ntp, skip_dns, skip_ntp, skip_proxy)
                resolved[ip_str] = config

        return resolved

    def _get_progress_bar_implementation(self):
        """Get tqdm progress bar implementation or fallback to simple progress bar

        :returns: tqdm function or SimplePbar fallback
        :rtype: function
        """
        # Try to import tqdm, fall back to simple progress if not available
        try:
            from tqdm import tqdm
            return tqdm
        except ImportError:
            # Create a simple progress bar fallback that displays to stdout
            class SimplePbar:
                def __init__(self, total, desc="", unit=""):
                    self.total = total
                    self.desc = desc
                    self.unit = unit
                    self.current = 0
                    # Display initial progress bar to stdout
                    initial_bar = self._get_progress_bar()
                    print(f"{desc}: 0/{total} {initial_bar}", end="", flush=True)

                def _get_progress_bar(self, width=40):
                    """Generate visual progress bar with # symbols"""
                    progress_pct = (self.current / self.total * 100) if self.total > 0 else 0
                    filled_length = int(width * self.current // self.total) if self.total > 0 else 0
                    bar = "#" * filled_length + "-" * (width - filled_length)
                    return f"[{bar}] {progress_pct:.1f}%"

                def set_description(self, desc):
                    self.desc = desc

                def set_postfix(self, **kwargs):
                    postfix_str = ", ".join([f"{k}={v}" for k, v in kwargs.items()])
                    # Update stdout display with visual progress bar
                    progress_bar = self._get_progress_bar()
                    status_info = f" [{postfix_str}]" if postfix_str else ""
                    print(
                        f"\r{self.desc}: {self.current}/{self.total} " f"{progress_bar}{status_info}",
                        end="",
                        flush=True,
                    )

                def update(self, n):
                    self.current += n
                    # Display visual progress bar
                    progress_bar = self._get_progress_bar()
                    print(f"\r{self.desc}: {self.current}/{self.total} {progress_bar}", end="", flush=True)

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    print()  # New line after progress bar completion

            def tqdm(total, desc="", unit="", file=None):
                return SimplePbar(total, desc, unit)

            return tqdm

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
            except Exception as e:
                raise ProxyConfigFailedError(f"Setting Proxy Server Configuration Failed: {str(e)}\n")
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
            except Exception as e:
                raise ProxyConfigFailedError(f"Clearing Proxy Server Configuration Failed: {str(e)}\n")

    def get_cloud_status(self, need_reason=None):
        path = self.rdmc.app.typepath.defs.managerpath
        resp = self.rdmc.app.get_handler(path, service=False, silent=True)
        if resp.status != 200:
            raise SessionExpired("Invalid session. Please logout and log back in or include credentials.")
        status = resp.dict["Oem"]["Hpe"]["CloudConnect"]["CloudConnectStatus"]
        if need_reason:
            reason = resp.dict["Oem"]["Hpe"]["CloudConnect"].get("FailReason", "")
            return status, reason
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
        except Exception as e:
            raise CloudConnectFailedError(f"ComputeOpsManagement connection Failed: {str(e)}\n")
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
                status, reason = self.get_cloud_status(need_reason=True)
                if status == "NotEnabled":
                    raise CloudConnectFailedError(ErrorMapping[reason])
                raise CloudConnectTimeoutError(
                    "ComputeOpsManagement connection timed out, Please check the "
                    "activation key and network or proxy settings and try again.\n"
                )
            else:
                status, reason = self.get_cloud_status(need_reason=True)
                # self.rdmc.ui.printer("ComputeOpsManagement connection status is %s.\n" % status)
                if status == "Connected":
                    # Check again after 10 seconds before breaking the loop
                    time.sleep(10)
                    status, reason = self.get_cloud_status(need_reason=True)
                    if status == "Connected":
                        self.rdmc.ui.printer("\n")
                        self.rdmc.ui.printer("ComputeOpsManagement connection is successful.\n")
                        break
                # If connection has failed while checking waiting for success message
                if status == "ConnectionFailed" or status == "NotConnected":
                    self.rdmc.ui.printer("\n")
                    if reason:
                        raise CloudConnectFailedError(ErrorMapping[reason])
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
            except Exception as e:
                raise CloudConnectFailedError(f"ComputeOpsManagement is not disconnected: {str(e)}\n")
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
            if "ExtendedStatusInfo" in cloud_info:
                output += "\n"
                output += "Extended Cloud connect status is as follows:\n\n"
                output += "Network Configuration : %s\n" % (
                    Cloudconnectstatus[cloud_info["ExtendedStatusInfo"]["NetworkConfig"]]
                )
                output += "Web Connectivity : %s\n" % (
                    Cloudconnectstatus[cloud_info["ExtendedStatusInfo"]["WebConnectivity"]]
                )
                output += "iLO Configuration for Cloud Connect : %s\n" % (
                    Cloudconnectstatus[cloud_info["ExtendedStatusInfo"]["iLOConfigForCloudConnect"]]
                )
        if not json:
            self.rdmc.ui.printer(output, verbose_override=True)
        else:
            self.rdmc.ui.print_out_json(cloud_info)

    def generate_template_file(self, template_input_file=DEFAULT_TEMPLATE_FILE_NAME):
        """Generate template JSON input file for multiconnect"""

        template_str = json.dumps(template, indent=4)

        try:
            with open(template_input_file, "w") as outfile:
                outfile.write(template_str)
                self.rdmc.ui.printer(f"Template written to: {template_input_file}\n", verbose_override=True)
        except Exception as e:
            LOGGER.error(f"Exception writing template file: {e}")
            raise InvalidCommandLineError(f"Failed to write template JSON file: {e}\n")

    def bulk_connect_precheck(self, config_file, output_file=None):
        """Perform precheck validation for bulk connect operations

        :param config_file: path to JSON configuration file
        :type config_file: str
        :param output_file: optional output file for report
        :type output_file: str or None
        :param allow_ilo_reset: allow iLO reset during operations
        :type allow_ilo_reset: bool
        """
        # Suppress urllib3 warnings (connection retry warnings, InsecureRequestWarning, etc.)
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        urllib3.disable_warnings(urllib3.exceptions.ConnectionError)
        urllib3.disable_warnings()

        current_time = datetime.now()
        LOGGER.info(f"Starting bulk_connect precheck: config={config_file}, output={output_file}")

        # Load and validate configuration (do once, not in loop)
        try:
            config = self._validate_input_file(config_file)
        except (Exception) as e:
            raise e

        # Generate default output filename if not provided
        if not output_file:
            output_file = f"onboard_precheck_{current_time.strftime('%m%d%Y_%H%M%S')}.json"

        LOGGER.info(f"Report will be saved to: {output_file}")

        # Initialize report with new format
        report = {
            "iloPrecheck": [],
            "resultCount": {"ilos": "0", "preCheckPassed": "0", "preCheckFailed": "0"}
        }

        # Counters for result tracking
        counters = {"total": 0, "preCheckPassed": 0, "preCheckFailed": 0}

        # Progressive update for pbar implementation
        # This gets updated in every iteration of the for loop below
        pbar_postfix = {}

        # Extract common settings
        common_settings = config.get("commonSettings", {})
        ilo_auth = (
            common_settings.get("iloAuthentication", {})
            if isinstance(common_settings.get("iloAuthentication"), dict)
            else {}
        )
        com_settings = (
            common_settings.get("computeOpsManagement", {})
            if isinstance(common_settings.get("computeOpsManagement"), dict)
            else {}
        )
        network_settings = (
            common_settings.get("network", {}) if isinstance(common_settings.get("network"), dict) else {}
        )
        proxy_settings = common_settings.get("proxy", {}) if isinstance(common_settings.get("proxy"), dict) else {}

        # Get target IPs
        try:
            target_ips = self._get_all_target_ips(config.get("targets", {}))
            counters["total_targets"] = len(target_ips)
            LOGGER.info(f"Precheck for {len(target_ips)} target iLO(s)")
        except Exception as e:
            error_msg = f"Error processing target IPs: {str(e)}"
            LOGGER.error(error_msg)
            raise InvalidCommandLineError(error_msg)

        # Get progress bar implementation
        tqdm = self._get_progress_bar_implementation()

        # Process each target IP with progress bar for precheck validation
        with tqdm(total=len(target_ips), desc="Validating iLOs", unit="iLO") as pbar:
            for ip_info in target_ips:
                ip = ip_info["ip"]
                individual_settings = ip_info.get("settings", {}) if isinstance(ip_info.get("settings"), dict) else {}

                pbar.set_description(f"Validating {ip}")
                LOGGER.info(f"Starting precheck validation for iLO: {ip}")

                # Initialize precheck result
                precheck_result = {
                    "ip": ip,
                    "managementProcessorModel": "",
                    "iloVersion": "",
                    "preCheckResult": "FAILED",
                    "details": "",
                    "recommendation": "",
                }

                # Initialize status tracking variables
                postfix_type = "FAILED"

                # Validate single iLO
                validation_result = self._validate_single_ilo_for_precheck(
                    ip, ilo_auth, com_settings, network_settings, individual_settings
                )

                status = validation_result["status"]
                error = validation_result["error"]
                recommendation = validation_result["recommendation"]
                precheck_result["managementProcessorModel"] = validation_result["managementProcessorModel"]
                precheck_result["iloVersion"] = validation_result["iloVersion"]

                # Set postfix type for progress bar
                if error == "Authentication or connectivity failed with iLO":
                    postfix_type = "ERROR"

                # Update precheck result with final values
                precheck_result["preCheckResult"] = status
                precheck_result["details"] = error
                precheck_result["recommendation"] = recommendation

                # Update counters and progress bar
                if status == "PASSED":
                    counters["preCheckPassed"] += 1
                    pbar_postfix["status"] = "PASSED"
                    pbar_postfix["preCheckPassed"] = counters["preCheckPassed"]
                    pbar.set_postfix(**pbar_postfix)
                else:
                    counters["preCheckFailed"] += 1
                    pbar_postfix["status"] = postfix_type
                    pbar_postfix["preCheckFailed"] = counters["preCheckFailed"]
                    pbar.set_postfix(**pbar_postfix)

                # Add to report
                report["iloPrecheck"].append(precheck_result)
                counters["total"] += 1
                pbar.update(1)

        # Finalize report
        report["resultCount"] = {
            "ilos": str(counters["total"]),
            "preCheckPassed": str(counters["preCheckPassed"]),
            "preCheckFailed": str(counters["preCheckFailed"]),
        }

        # Write report to JSON file
        try:
            self._save_json_report(report, output_file)
            LOGGER.info(f"Precheck report saved to: {output_file}")
            self.rdmc.ui.printer(f"Precheck completed. Report saved to: {output_file}\n", verbose_override=True)
            self.rdmc.ui.printer(f"Precheck passed for {counters['preCheckPassed']} iLO(s).\n", verbose_override=True)
            self.rdmc.ui.printer(f"Precheck failed for {counters['preCheckFailed']} iLO(s).\n", verbose_override=True)
        except Exception as e:
            LOGGER.error(f"Failed to save precheck report: {str(e)}")
            raise InvalidCommandLineError(f"Failed to save precheck report: {str(e)}")

        return ReturnCodes.SUCCESS

    def _get_ilo_credentials(self, ilo_auth, individual_settings):
        """Extract iLO credentials, prioritizing individual settings over common settings

        :param ilo_auth: Common iLO authentication settings
        :type ilo_auth: dict
        :param individual_settings: Individual iLO settings that may contain authentication
        :type individual_settings: dict
        :returns: tuple of (username, password)
        :rtype: tuple
        """
        # Check if individual settings contain iLO authentication
        individual_auth = individual_settings.get("iloAuthentication", {})
        if isinstance(individual_auth, dict) and individual_auth.get("iloUser") and individual_auth.get("iloPassword"):
            username = individual_auth.get("iloUser")
            password = individual_auth.get("iloPassword")
            return username, password

        # Fall back to common authentication settings
        username = ilo_auth.get("iloUser", "administrator")
        password = ilo_auth.get("iloPassword", "")
        return username, password

    def _validate_single_ilo_for_precheck(self, ip, ilo_auth, com_settings, network_settings, individual_settings):
        """Validate a single iLO for precheck operations

        :param ip: iLO IP address
        :type ip: str
        :param ilo_auth: iLO authentication settings
        :type ilo_auth: dict
        :param com_settings: COM settings
        :type com_settings: dict
        :param network_settings: network settings
        :type network_settings: dict
        :param proxy_settings: proxy settings
        :type proxy_settings: dict
        :param individual_settings: individual iLO settings
        :type individual_settings: dict
        :returns: dict with validation results
        :rtype: dict
        """
        # Initialize results
        validation_data = {
            "status": "FAILED",
            "error": "",
            "recommendation": "",
            "managementProcessorModel": "",
            "iloVersion": "",
        }

        try:
            # Perform basic connectivity and version checks
            base_url = f"https://{ip}"
            username, password = self._get_ilo_credentials(ilo_auth, individual_settings)

            if not password:
                validation_data["error"] = "No password provided"
                validation_data["recommendation"] = "Provide valid iLO credentials"
                return validation_data
            # Basic connectivity test
            from requests.auth import HTTPBasicAuth

            response = requests.get(
                f"{base_url}/redfish/v1/",
                auth=HTTPBasicAuth(username, password),
                verify=False,
                timeout=30
            )

            if response.status_code == 200:
                # Get iLO version information
                model, ilo_version = self._get_ilo_version_from_response(response.json(), base_url, username, password)

                # Set model and version info
                validation_data["managementProcessorModel"] = f"iLO{model}" if model else ""
                validation_data["iloVersion"] = str(ilo_version) if ilo_version else ""

                # Check version compatibility
                is_compatible, err_msg, rec_msg = self._check_ilo_version_compatibility(model, ilo_version, ip)
                if is_compatible:
                    # Check if iLO is already connected to COM
                    # Create HTTP session
                    session = requests.Session()
                    session.auth = HTTPBasicAuth(username, password)
                    session.verify = False

                    is_connected = self._check_com_connection_status(session, base_url)
                    # if iLO is connected, set validation_data results as PASSED
                    if is_connected:
                        validation_data["status"] = "PASSED"
                    else:
                        # Check activationKey/workspace_id based on iLO version capabilities
                        is_pin_supported = self._is_pin_onboarding_supported(ilo_version, model)

                        if not is_pin_supported:
                            workspace_id = com_settings.get("workspace_id", "")
                            if not workspace_id:
                                validation_data["error"] = "The version of iLO requires a valid workspace_id"
                                validation_data["recommendation"] = (
                                    "Provide a valid workspace_id in the configuration for onboarding"
                                )
                                return validation_data
                        else:
                            activation_key = com_settings.get("activationKey", "")
                            if not activation_key:
                                validation_data["error"] = "The version of iLO requires a valid activation Key"
                                validation_data["recommendation"] = (
                                    "Provide a valid activation Key in the configuration for onboarding"
                                )
                                return validation_data

                        merged_network = network_settings.copy() if isinstance(network_settings, dict) else {}
                        individual_network = individual_settings.get("network", {})
                        if individual_network and isinstance(individual_network, dict):
                            merged_network.update(individual_network)

                        session = self._create_session_with_retries(username, password)

                        dns_precheck_result, validation_data = self._precheck_validate_dns_settings(
                            session,
                            base_url,
                            merged_network,
                            individual_settings,
                            validation_data,
                        )
                        if not dns_precheck_result:
                            return validation_data

                        ntp_precheck_result, validation_data = self._precheck_validate_ntp_settings(
                            session,
                            base_url,
                            merged_network,
                            individual_settings,
                            validation_data,
                        )
                        if not ntp_precheck_result:
                            return validation_data

                        # All checks have passed, mark as ready for onboarding
                        validation_data["status"] = "PASSED"
                else:
                    validation_data["error"] = err_msg
                    validation_data["recommendation"] = rec_msg
            else:
                validation_data["error"] = f"HTTP {response.status_code} - Authentication or connectivity failed"
                validation_data["recommendation"] = "Verify iLO credentials and network connectivity"

        except Exception as e:
            validation_data["error"] = "Authentication or connectivity failed with iLO"
            validation_data["recommendation"] = "Review the input file for credentials and re-run the command"

        return validation_data

    def _precheck_validate_dns_settings(self, session, base_url, merged_network, individual_settings, validation_data):
        """Validate a DNS setting in iLO for precheck

        :param session: session object to iLO
        :type session: object
        :param base_url: base URL for iLO REST API
        :type base_url: str
        :param merged_network: merged network settings
        :type merged_network: dict
        :param individual_settings: individual settings
        :type individual_settings: dict
        :param validation_data: validation data dictionary
        :type validation_data: dict
        :returns: tuple of (DNS precheck status, updated validation data)
        :rtype: tuple
        """
        dns_precheck_status = False
        current_dns_servers, dhcp_dns_enabled, dhcp_check_attempted = self._get_current_dns_servers(session, base_url)
        if not dhcp_check_attempted:
            LOGGER.error("Unable to retrieve DNS settings from iLO during precheck")
            validation_data["error"] = "Unable to retrieve DNS settings from iLO"
            validation_data["recommendation"] = "Check iLO connectivity and retry the operation"
            return dns_precheck_status, validation_data

        if individual_settings.get("skipDns", False):
            if not current_dns_servers and not dhcp_dns_enabled:
                if merged_network.get("dns", []):
                    LOGGER.info("skipDNS flag is set, no DNS configured in iLO")
                    validation_data["recommendation"] = (
                        "Remove skipDns or Configure DNS in iLO before attempting"
                        " to Onboard to HPE Compute Ops Management"
                    )
                else:
                    LOGGER.info("skipDNS flag is set, no DNS settings in input. Also no DNS configured in iLO")
                    validation_data["recommendation"] = (
                        "Configure DNS in iLO before attempting to Onboard to HPE Compute Ops Management"
                    )
                validation_data["error"] = "No DNS configuration found in iLO"
                return dns_precheck_status, validation_data
        elif not merged_network.get("dns", []):
            if not current_dns_servers and not dhcp_dns_enabled:
                LOGGER.info("No DNS settings in input and no DNS configured in iLO")
                validation_data["error"] = "No DNS configuration found in iLO"
                validation_data["recommendation"] = (
                    "Configure DNS in iLO before attempting to Onboard to HPE Compute Ops Management"
                )
                return dns_precheck_status, validation_data

        dns_precheck_status = True
        LOGGER.info("DNS precheck passed")
        return dns_precheck_status, validation_data

    def _precheck_validate_ntp_settings(self, session, base_url, merged_network, individual_settings, validation_data):
        """Validate NTP settings in iLO for precheck

        :param session: session object to iLO
        :type session: object
        :param base_url: base URL for iLO REST API
        :type base_url: str
        :param merged_network: merged network settings
        :type merged_network: dict
        :param individual_settings: individual settings
        :type individual_settings: dict
        :param validation_data: validation data dictionary
        :type validation_data: dict
        :returns: tuple of (NTP precheck status, updated validation data)
        :rtype: tuple
        """
        ntp_precheck_status = True
        eth_interfaces_url = f"{base_url}/redfish/v1/Managers/1/EthernetInterfaces"
        dhcp_ntp_is_enabled, _, dhcp_check_attempted = self._check_dhcp_ntp_config_on_interfaces(
            session,
            base_url,
            eth_interfaces_url,
        )
        ntp_servers = self._get_current_ntp_servers(session, base_url)
        if not dhcp_check_attempted or ntp_servers is None:
            LOGGER.error("Unable to retrieve NTP settings from iLO during precheck")
            ntp_precheck_status = False
            validation_data["error"] = "Unable to retrieve NTP settings from iLO"
            validation_data["recommendation"] = "Check iLO connectivity and retry the operation"
            return ntp_precheck_status, validation_data

        if individual_settings.get("skipNtp", False):
            if not dhcp_ntp_is_enabled and not ntp_servers:
                if merged_network.get("ntp", []):
                    LOGGER.info("skipNTP flag is set and no NTP configured in iLO")
                    validation_data["recommendation"] = (
                        "Remove skipNtp or Configure NTP in iLO before attempting"
                        " to Onboard to HPE Compute Ops Management"
                    )
                else:
                    LOGGER.info("skipNTP flag is set, no NTP settings in input. Also no NTP configured in iLO")
                    validation_data["recommendation"] = (
                        "Configure NTP in iLO before attempting to Onboard to HPE Compute Ops Management"
                    )
                validation_data["error"] = "No NTP configuration found in iLO"
                return ntp_precheck_status, validation_data
        elif not merged_network.get("ntp", []):
            if not dhcp_ntp_is_enabled and not ntp_servers:
                LOGGER.info("No NTP settings in input and no NTP configured in iLO")
                validation_data["error"] = "No NTP configuration found in iLO"
                validation_data["recommendation"] = (
                    "Configure NTP in iLO before attempting to Onboard to HPE Compute Ops Management"
                )
                return ntp_precheck_status, validation_data

        LOGGER.info("NTP precheck passed")
        return ntp_precheck_status, validation_data

    def _validate_bulk_connect_input(self, config):
        """
        Validate the input JSON from file for below:
        - key named "commonSettings" must be present
        - commonSettings must have computeOpsManagement key with atleast either of activationKey or workspace_id
        - commonSettings must have iloAuthentication key that contains iloUser and iloPassword attributes.
        - key named "targets" must be present
        - key named "ilos" must be present
        - atleast one iLO ip should be present either in individual or ranges section.
        """
        if not isinstance(config, dict):
            raise InvalidCommandLineError("Invalid configuration format: expected a JSON object at the top level")

        if "commonSettings" not in config:
            raise InvalidCommandLineError("Missing 'commonSettings' section in configuration")

        common_settings = config["commonSettings"]
        if not isinstance(common_settings, dict):
            raise InvalidCommandLineError("'commonSettings' must be a JSON object")

        com_settings = common_settings.get("computeOpsManagement", {})
        if not isinstance(com_settings, dict):
            raise InvalidCommandLineError("'computeOpsManagement' in 'commonSettings' must be a JSON object")

        activation_key = com_settings.get("activationKey")
        workspace_id = com_settings.get("workspace_id")
        if not activation_key and not workspace_id:
            raise InvalidCommandLineError(
                "In 'commonSettings.computeOpsManagement', either 'activationKey' or 'workspace_id' must be provided"
            )

        if "targets" not in config:
            raise InvalidCommandLineError("Missing 'targets' section in configuration")

        targets = config["targets"]
        if not isinstance(targets, dict):
            raise InvalidCommandLineError("'targets' must be a JSON object")

        if "ilos" not in targets:
            raise InvalidCommandLineError("Missing 'ilos' section in 'targets'")

        ilos = targets["ilos"]
        if not isinstance(ilos, dict):
            raise InvalidCommandLineError("'ilos' in 'targets' must be a JSON object")

        individual_ilos = ilos.get("individual", [])
        ranges = ilos.get("ranges", [])

        if not isinstance(individual_ilos, list):
            raise InvalidCommandLineError("'individual' in 'ilos' must be an array")

        # Check if common iLO authentication is provided
        common_auth_provided = False
        if "iloAuthentication" in common_settings:
            ilo_auth = common_settings["iloAuthentication"]
            if isinstance(ilo_auth, dict) and ilo_auth.get("iloUser") and ilo_auth.get("iloPassword"):
                common_auth_provided = True

        # If common authentication is not provided, verify all targets have individual authentication
        if not common_auth_provided:
            # Check that all individual iLOs have authentication
            for ilo in individual_ilos:
                individual_auth = ilo.get("iloAuthentication", {})
                if not (isinstance(individual_auth, dict) and
                       individual_auth.get("iloUser") and 
                       individual_auth.get("iloPassword")):
                    raise InvalidCommandLineError(
                        "The operation failed as iLO credential is not provided in the input json"
                    )

            # Check that all ranges have authentication
            for range_config in ranges:
                range_auth = range_config.get("iloAuthentication", {})
                if not (isinstance(range_auth, dict) and
                       range_auth.get("iloUser") and
                       range_auth.get("iloPassword")):
                    raise InvalidCommandLineError(
                        "The operation failed as iLO credential is not provided in the input json"
                    )
        else:
            # Common authentication is provided, ensure it's properly formatted
            ilo_auth = common_settings["iloAuthentication"]
            if not isinstance(ilo_auth, dict):
                raise InvalidCommandLineError("'iloAuthentication' in 'commonSettings' must be a JSON object")

            if "iloUser" not in ilo_auth or "iloPassword" not in ilo_auth:
                raise InvalidCommandLineError("Missing 'iloUser' or 'iloPassword' in 'iloAuthentication'")

        if not isinstance(ranges, list):
            raise InvalidCommandLineError("'ranges' in 'ilos' must be an array")

        total_individual_ilos = len(individual_ilos)
        total_range_objects = len(ranges)
        for ilo in individual_ilos:
            if not isinstance(ilo, dict) or "ip" not in ilo:
                raise InvalidCommandLineError("Each entry in 'individual' must be an object with an 'ip' field")

        for range_config in ranges:
            if not isinstance(range_config, dict) or "start" not in range_config or "end" not in range_config:
                raise InvalidCommandLineError("Each entry in 'ranges' must be an object with 'start' and 'end' fields")

        if total_individual_ilos == 0 and total_range_objects == 0:
            raise InvalidCommandLineError("At least one iLO IP must be specified in 'individual' or 'ranges'")

    def _validate_input_file(self, config_file) -> Dict[str, Any]:
        # Load and validate configuration (do once, not in loop)
        try:
            if not os.path.exists(config_file):
                error_msg = f"Configuration file not found: {config_file}"
                LOGGER.error(error_msg)
                raise InvalidCommandLineError(error_msg)

            with open(config_file, "r") as f:
                config = json.load(f)
            LOGGER.info(f"Loaded configuration from: {config_file}")

            # Validate configuration
            self._validate_bulk_connect_input(config)
            LOGGER.info("Configuration validation passed")
            return config
        except (json.JSONDecodeError, InvalidCommandLineError) as e:
            error_msg = f"Error in configuration file '{config_file}': {str(e)}"
            LOGGER.error(error_msg)
            raise InvalidCommandLineError(error_msg)

    def bulk_connect(self, config_file, output_file=None, allow_ilo_reset=False):
        """Perform bulk connect operations for multiple iLOs

        :param config_file: path to JSON configuration file
        :type config_file: str
        :param output_file: optional output file for report
        :type output_file: str or None
        :param allow_ilo_reset: allow iLO reset during operations
        :type allow_ilo_reset: bool
        """

        # Suppress urllib3 warnings (connection retry warnings, InsecureRequestWarning, etc.)
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        urllib3.disable_warnings(urllib3.exceptions.ConnectionError)
        urllib3.disable_warnings()

        # Get progress bar implementation
        tqdm = self._get_progress_bar_implementation()

        # Setup logging
        current_time = datetime.now()
        LOGGER.info(f"Starting bulk_connect: config={config_file}, output={output_file}, allow_reset={allow_ilo_reset}")

        # Load and validate configuration (do once, not in loop)
        try:
            config = self._validate_input_file(config_file)
        except (Exception) as e:
            raise e

        # Generate default output filename if not provided
        if not output_file:
            output_file = f"onboard_{current_time.strftime('%m%d%Y_%H%M%S')}.json"

        LOGGER.info(f"Report will be saved to: {output_file}")

        # Initialize report with new format
        report = {
            "iloOnboard": [],
            "resultCount": {"ilos": "0", "connected": "0", "failed": "0", "notAttempted": "0", "pendingiloReset": "0"},
        }

        # Counters for result tracking
        counters = {"total": 0, "connected": 0, "failed": 0, "notAttempted": 0, "pendingiloReset": 0}

        # Progressive update for pbar implementation
        # This gets updated in every iteration of the for loop below
        pbar_postfix = {}

        # Extract common settings once (not per iLO)
        common_settings = config.get("commonSettings", {})
        ilo_auth = (
            common_settings.get("iloAuthentication", {})
            if isinstance(common_settings.get("iloAuthentication"), dict)
            else {}
        )
        com_settings = (
            common_settings.get("computeOpsManagement", {})
            if isinstance(common_settings.get("computeOpsManagement"), dict)
            else {}
        )
        network_settings = (
            common_settings.get("network", {}) if isinstance(common_settings.get("network"), dict) else {}
        )
        proxy_settings = common_settings.get("proxy", {}) if isinstance(common_settings.get("proxy"), dict) else {}

        # Get target IPs
        try:
            target_ips = self._get_all_target_ips(config.get("targets", {}))
            counters["total_targets"] = len(target_ips)
            LOGGER.info(f"Processing {len(target_ips)} target iLO(s)")
        except Exception as e:
            error_msg = f"Error processing target IPs: {str(e)}"
            LOGGER.error(error_msg)
            raise InvalidCommandLineError(error_msg)

        # Process each target IP sequentially with progress bar
        with tqdm(total=len(target_ips), desc="Connecting iLOs", unit="iLO") as pbar:
            for ip_info in target_ips:
                ip = ip_info["ip"]
                individual_settings = ip_info.get("settings", {}) if isinstance(ip_info.get("settings"), dict) else {}

                pbar.set_description(f"Processing {ip}")
                LOGGER.info(f"Starting connection for iLO: {ip}")

                result = {
                    "ip": ip,
                    "status": "pending",
                    "message": "",
                    "timestamp": datetime.now().isoformat(),
                    "details": {},
                }

                # add precheck validation here
                validation_result = self._validate_single_ilo_for_precheck(
                    ip, ilo_auth, com_settings, network_settings, individual_settings
                )

                if validation_result["status"] == "PASSED":
                    try:
                        # Connect to individual iLO and perform COM connection
                        success, ilo_was_reset, needs_manual_reset, ilo_result = self._connect_single_ilo_to_com(
                            ip=ip,
                            ilo_auth=ilo_auth,
                            com_settings=com_settings,
                            network_settings=network_settings,
                            proxy_settings=proxy_settings,
                            individual_settings=individual_settings,
                            allow_ilo_reset=allow_ilo_reset,
                            validation_result=validation_result,
                        )
                    except Exception as e:
                        # Handle unexpected exceptions
                        report["iloOnboard"].append(
                            {
                                "ip": ip,
                                "managementProcessorModel": "",
                                "iloVersion": "",
                                "onboardStatus": "not attempted",
                                "onboardError": f"{str(e)}",
                                "recommendation": "Review error details and verify iLO configuration",
                            }
                        )
                        counters["total"] += 1
                        counters["failed"] += 1
                        LOGGER.error(f"ERROR {ip}: Error - {str(e)}")
                        pbar_postfix["status"] = "ERROR"
                        pbar_postfix["failed"] = counters["failed"]
                        pbar.set_postfix(**pbar_postfix)
                    else:
                        # Add to report
                        report["iloOnboard"].append(
                            {
                                "ip": ilo_result["ip"],
                                "managementProcessorModel": ilo_result["managementProcessorModel"],
                                "iloVersion": ilo_result["iloVersion"],
                                "onboardStatus": ilo_result["onboardStatus"],
                                "onboardError": ilo_result["onboardError"],
                                "recommendation": ilo_result["recommendation"],
                                "preCheckResult": validation_result["status"],
                                "preCheckError": validation_result["error"],
                            }
                        )

                        # Update counters
                        counters["total"] += 1
                        if ilo_result["onboardStatus"] == "connected":
                            counters["connected"] += 1

                        if success:
                            result["status"] = "success"
                            result["message"] = "Successfully connected to COM"
                            result["details"] = {
                                "authentication": "successful",
                                "com_connection": "established",
                                "activation_method": "pin" if com_settings.get("activationKey") else "workspace_id",
                                "ilo_was_reset": ilo_was_reset,
                            }
                            LOGGER.info(f"SUCCESS {ip}: Connected successfully")
                            pbar_postfix["status"] = "SUCCESS"
                            pbar_postfix["connected"] = counters["connected"]
                            pbar.set_postfix(**pbar_postfix)
                        elif ilo_result["onboardStatus"] == "not attempted":
                            counters["notAttempted"] += 1
                            LOGGER.warning(f"NOT ATTEMPTED {ip}: {ilo_result['onboardError']}")
                            pbar_postfix["status"] = "NOT ATTEMPTED"
                            pbar_postfix["notAttempted"] = counters["notAttempted"]
                            pbar.set_postfix(**pbar_postfix)
                        elif (
                            "reset" in ilo_result.get("onboardError", "").lower()
                            or "waiting" in ilo_result.get("onboardError", "").lower()
                        ):
                            counters["pendingiloReset"] += 1
                            LOGGER.warning(f"PENDING RESET {ip}")
                            pbar_postfix["status"] = "PENDING RESET"
                            pbar_postfix["pendingiloReset"] = counters["pendingiloReset"]
                            pbar.set_postfix(**pbar_postfix)
                        else:
                            counters["failed"] += 1
                            LOGGER.warning(f"FAILED {ip}: {ilo_result['onboardError']}")
                            pbar_postfix["status"] = "FAILED"
                            pbar_postfix["failed"] = counters["failed"]
                            pbar.set_postfix(**pbar_postfix)
                            result["status"] = "failed"
                            if needs_manual_reset:
                                result["message"] = "NTP configured but requires manual iLO reset"
                                result["details"] = {
                                    "error": "NTP configured but manual reset required",
                                    "ilo_was_reset": ilo_was_reset,
                                    "needs_manual_reset": True,
                                }
                            else:
                                result["message"] = "Failed to connect to COM"
                                result["details"] = {
                                    "error": "Connection failed during COM setup",
                                    "ilo_was_reset": ilo_was_reset,
                                }
                else:
                    # Precheck failed, do not attempt connection
                    report["iloOnboard"].append(
                        {
                            "ip": ip,
                            "managementProcessorModel": validation_result["managementProcessorModel"],
                            "iloVersion": validation_result["iloVersion"],
                            "onboardStatus": "not attempted",
                            "onboardError": "",
                            "recommendation": validation_result["recommendation"],
                            "preCheckResult": validation_result["status"],
                            "preCheckError": validation_result["error"],
                        }
                    )
                    counters["total"] += 1
                    counters["notAttempted"] += 1
                    LOGGER.warning(f"NOT ATTEMPTED {ip}: Precheck failed - {validation_result['error']}")
                    pbar_postfix["status"] = "NOT ATTEMPTED"
                    pbar_postfix["notAttempted"] = counters["notAttempted"]
                    pbar.set_postfix(**pbar_postfix)
                pbar.update(1)

        # Finalize report
        report["resultCount"] = {
            "ilos": str(counters["total"]),
            "connected": str(counters["connected"]),
            "failed": str(counters["failed"]),
            "notAttempted": str(counters["notAttempted"]),
            "pendingiloReset": str(counters["pendingiloReset"]),
        }

        end_time = datetime.now()
        duration_seconds = (end_time - current_time).total_seconds()
        LOGGER.info(
            f"Bulk connect completed in {duration_seconds:.2f}s: "
            f"{counters['connected']} connected, {counters['failed']} failed, "
            f"{counters['notAttempted']} not attempted, {counters['pendingiloReset']} pending reset"
        )

        # Write report to JSON file
        try:
            self._save_json_report(report, output_file)
        except Exception as e:
            LOGGER.error(f"Failed to save report: {str(e)}")
            print(f"ERROR: Could not save report to {output_file}: {str(e)}")

        # Display summary both to stdout and log file
        print(f"ComputeOpsManagement connection successful for {counters['connected']} server(s).")
        print(f"ComputeOpsManagement connection failed for {counters['failed']} server(s).")
        print(f"The operation completed. Details available in the output {output_file} file")

        LOGGER.info(f"Report saved to: {output_file}")
        return ReturnCodes.SUCCESS

    def _get_all_target_ips(self, targets):
        """Extract all target IPs from the configuration

        :param targets: targets section from config
        :type targets: dict
        :returns: list of IP information dictionaries
        :rtype: list
        """
        import ipaddress

        target_ips = []
        ilos = targets.get("ilos", {})

        # Process individual IPs
        individual_ilos = ilos.get("individual", [])
        for ilo in individual_ilos:
            ip_info = {"ip": ilo["ip"], "settings": ilo}
            target_ips.append(ip_info)

        # Process IP ranges
        ranges = ilos.get("ranges", [])
        for range_config in ranges:
            start_ip = ipaddress.IPv4Address(range_config["start"])
            end_ip = ipaddress.IPv4Address(range_config["end"])

            # Validate range size to prevent memory issues
            range_size = int(end_ip) - int(start_ip) + 1
            if range_size > 1000:
                raise InvalidCommandLineError(
                    f"IP range {range_config['start']} to {range_config['end']} contains {range_size} IPs. "
                    f"Maximum allowed range size is 1000 IPs to prevent memory issues."
                )

            current_ip = start_ip
            while current_ip <= end_ip:
                ip_info = {"ip": str(current_ip), "settings": range_config}
                target_ips.append(ip_info)
                current_ip += 1

        return target_ips

    def _get_all_target_ips_optimized(self, targets):
        """Optimized generator to extract all target IPs from the configuration

        :param targets: targets section from config
        :type targets: dict
        :yields: IP information dictionaries
        :rtype: iterator
        """
        import ipaddress

        ilos = targets.get("ilos", {})

        # Process individual IPs
        individual_ilos = ilos.get("individual", [])
        for ilo in individual_ilos:
            yield {"ip": ilo["ip"], "settings": ilo}

        # Process IP ranges
        ranges = ilos.get("ranges", [])
        for range_config in ranges:
            start_ip = ipaddress.IPv4Address(range_config["start"])
            end_ip = ipaddress.IPv4Address(range_config["end"])

            # Validate range size to prevent memory issues
            range_size = int(end_ip) - int(start_ip) + 1
            if range_size > 1000:
                raise InvalidCommandLineError(
                    f"IP range {range_config['start']} to {range_config['end']} contains {range_size} IPs. "
                    f"Maximum allowed range size is 1000 IPs to prevent memory issues."
                )

            current_ip = start_ip
            while current_ip <= end_ip:
                yield {"ip": str(current_ip), "settings": range_config}
                current_ip += 1

    def _connect_single_ilo_to_com(
        self,
        ip,
        ilo_auth,
        com_settings,
        network_settings,
        proxy_settings,
        individual_settings,
        allow_ilo_reset=False,
        validation_result=None,
    ):
        """Connect a single iLO to COM using HTTP-only connection

        :returns: tuple (success, ilo_was_reset, needs_manual_reset, result_dict)
        :rtype: tuple
        """
        import requests
        from requests.auth import HTTPBasicAuth

        # Initialize return structure
        result = {
            "ip": ip,
            "managementProcessorModel": "",
            "iloVersion": "",
            "onboardStatus": "not attempted",
            "onboardError": "",
            "recommendation": "",
        }

        ilo_was_reset = False

        try:
            # Create base URL and validate credentials
            base_url = f"https://{ip}"
            username, password = self._get_ilo_credentials(ilo_auth, individual_settings)

            if not password:
                result["onboardError"] = "No password provided"
                result["recommendation"] = "Provide valid iLO credentials"
                LOGGER.warning(f"{ip}: No password provided")
                return False, ilo_was_reset, False, result

            # Test connection with simple HTTP GET using requests
            response = requests.get(
                f"{base_url}/redfish/v1/", auth=HTTPBasicAuth(username, password), verify=False, timeout=30
            )

            if response.status_code != 200:
                result["onboardError"] = f"HTTP {response.status_code} - Authentication failed"
                result["recommendation"] = "Verify iLO credentials and network connectivity"
                LOGGER.error(f"{ip}: Authentication failed - HTTP {response.status_code}")
                return False, ilo_was_reset, False, result

            LOGGER.info(f"{ip}: Authenticated successfully")

            # Get iLO version information
            model = ""
            model_version = ""
            ilo_version = ""
            if validation_result:
                model = validation_result.get("managementProcessorModel", "iLO0")
                model_version = int((model.strip()).split("iLO")[-1])
                ilo_version = float(validation_result.get("iloVersion", "0.0"))
            else:
                model_version, ilo_version = self._get_ilo_version_from_response(
                    response.json(),
                    base_url,
                    username,
                    password
                )
                model = f"iLO{str(model_version)}" if model_version else ""

            result["managementProcessorModel"] = model
            result["iloVersion"] = ilo_version

            session = self._create_session_with_retries(username, password)

            # Configure proxy if needed - stop and move to next iLO on failure
            try:
                self._configure_proxy_for_ilo_requests(session, base_url, proxy_settings, individual_settings)
            except Exception as proxy_err:
                result["onboardStatus"] = "not attempted"
                result["onboardError"] = f"Proxy configuration failed: {str(proxy_err)}"
                result["recommendation"] = "Verify proxy settings and network connectivity, then retry"
                LOGGER.error(f"{ip}: Proxy configuration failed - {str(proxy_err)}")
                return False, ilo_was_reset, False, result

            # Configure network settings if needed and capture reset status - stop and move to next iLO on failure
            try:
                ilo_was_reset, ntp_configured_needs_reset = self._configure_network_settings_requests(
                    session, base_url, network_settings, individual_settings, allow_ilo_reset
                )
            except Exception as network_err:
                result["onboardStatus"] = "not attempted"
                result["onboardError"] = f"Network configuration failed: {str(network_err)}"
                result["recommendation"] = "Verify DNS/NTP settings and network connectivity, then retry"
                LOGGER.error(f"{ip}: Network configuration failed - {str(network_err)}")
                return False, ilo_was_reset, False, result

            # If NTP was configured but reset is not allowed, stop onboarding
            if ntp_configured_needs_reset:
                result["onboardStatus"] = "pending reset"
                result["onboardError"] = "NTP configuration requires manual iLO reset"
                result["recommendation"] = (
                    "Manually reset the iLO for NTP settings to take effect, "
                    "then re-run the onboarding command. "
                    "Alternatively, use --allow_ilo_reset flag to automatically reset iLO."
                )
                LOGGER.warning(f"{ip}: NTP configured but requires manual iLO reset")
                return False, ilo_was_reset, True, result

            # If iLO was reset and reset is allowed, wait for it to come back online
            if ilo_was_reset and allow_ilo_reset:
                LOGGER.info(f"{ip}: iLO was reset, waiting for it to come back online...")
                if self._wait_for_ilo_after_reset(ip, username, password):
                    LOGGER.info(f"{ip}: iLO is back online")
                    # Create new session after reset
                    session = requests.Session()
                    session.auth = HTTPBasicAuth(username, password)
                    session.verify = False
                else:
                    LOGGER.error(f"{ip}: iLO did not come back online within timeout")
                    return False, ilo_was_reset, False, result
            elif ilo_was_reset and not allow_ilo_reset:
                LOGGER.warning(f"{ip}: iLO was reset but --allow_ilo_reset not specified")
                return False, ilo_was_reset, True, result

            # Determine if PIN-based onboarding is supported
            workspace_id = com_settings.get("workspace_id")
            activation_key = com_settings.get("activationKey")
            pin_supported = self._is_pin_onboarding_supported(ilo_version, model_version)

            credential = activation_key if pin_supported and activation_key else workspace_id
            if credential:
                success, fail_reason = self._enable_com_connection_requests(session, base_url, credential)
                if success:
                    result["onboardStatus"] = "connected"
                    LOGGER.info(f"{ip}: Successfully connected to COM")
                    if not ilo_was_reset and "Configure NTP in iLO" in validation_result["recommendation"]:
                        result["recommendation"] = (
                            "Though iLO is onboarded to HPE Compute Ops Management, "
                            "it is recommended to configure NTP in iLO"
                        )
                    return True, ilo_was_reset, False, result
                else:
                    result["onboardStatus"] = "not connected"
                    if fail_reason == "InvalidActivationKey":
                        result["onboardError"] = "The activation key entered is invalid"
                        result["recommendation"] = (
                            "Please check the activation key value. " "If the problem persists, contact HPE Support"
                        )
                    elif fail_reason == "ExpiredActivationKey":
                        result["onboardError"] = "The activation key entered is expired"
                        result["recommendation"] = (
                            "Please enter a valid activation key. " "If the problem persists, contact HPE Support"
                        )
                    elif fail_reason == "ActivationKeyRequired":
                        result["onboardError"] = "An activation key is required"
                        result["recommendation"] = "Please provide a valid activation key"
                    else:
                        result["onboardError"] = (
                            f"Failed to enable COM connection: {fail_reason}"
                            if fail_reason
                            else "Failed to enable COM connection"
                        )
                        result["recommendation"] = "Verify activation key/workspace_id and network settings, then retry"
                    LOGGER.warning(f"{ip}: Failed to enable COM - {result['onboardError']}")
                    return False, ilo_was_reset, False, result

        except requests.exceptions.ConnectionError:
            result["onboardError"] = "iLO is not reachable"
            result["recommendation"] = "Verify network connectivity to iLO"
            LOGGER.error(f"{ip}: Connection error - iLO not reachable")
            return False, ilo_was_reset, False, result
        except requests.exceptions.Timeout:
            result["onboardError"] = "Connection timeout"
            result["recommendation"] = "Verify network connectivity and iLO responsiveness"
            LOGGER.error(f"{ip}: Connection timeout")
            return False, ilo_was_reset, False, result
        except Exception as e:
            result["onboardError"] = str(e)
            result["recommendation"] = "Review error details and verify iLO configuration"
            LOGGER.error(f"{ip}: Unexpected error - {str(e)}")
            return False, ilo_was_reset, False, result

    def _create_session_with_retries(self, username, password):
        """Create a requests session with retry strategy

        :param username: iLO username
        :type username: str
        :param password: iLO password
        :type password: str
        :returns: configured requests session
        :rtype: requests.Session
        """
        from requests.auth import HTTPBasicAuth
        from requests.adapters import HTTPAdapter

        # Create a session object with proper connection settings
        session = requests.Session()
        session.auth = HTTPBasicAuth(username, password)
        session.verify = False

        # Define retry strategy for connection errors
        retry_strategy = Retry(
            total=3,  # Total number of retries
            backoff_factor=1,  # Wait 1, 2, 4 seconds between retries
            status_forcelist=[500, 502, 503, 504],  # Retry on these HTTP status codes
            allowed_methods=["GET", "POST", "PATCH"],  # Retry these methods
            raise_on_status=False,  # Don't raise exceptions on retry exhaustion
        )

        # Create adapter with retry strategy
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=1,  # Single connection pool
            pool_maxsize=1,  # Single connection in pool to avoid conflicts
        )

        # Mount adapter for both http and https
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        return session

    def _wait_for_ilo_after_reset(self, ip, username, password, timeout_minutes=3):
        """Wait for iLO to come back online after reset

        :param ip: iLO IP address
        :type ip: str
        :param username: iLO username
        :type username: str
        :param password: iLO password
        :type password: str
        :param timeout_minutes: timeout in minutes to wait for iLO
        :type timeout_minutes: int
        :returns: True if iLO is back online, False if timeout
        :rtype: bool
        """
        import requests
        from requests.auth import HTTPBasicAuth
        import time

        base_url = f"https://{ip}"
        timeout_seconds = timeout_minutes * 60
        check_interval = 10  # Check every 10 seconds as requested
        max_attempts = int(timeout_seconds / check_interval)
        start_time = time.time()

        LOGGER.info("Continuing to wait ...")

        for attempt in range(max_attempts):
            try:
                response = requests.get(
                    f"{base_url}/redfish/v1/", auth=HTTPBasicAuth(username, password), verify=False, timeout=30
                )

                if response.status_code == 200:
                    elapsed_time = time.time() - start_time
                    LOGGER.info(f"{ip}: iLO back online after {elapsed_time:.1f}s")
                    return True

            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
                # Expected during reset - iLO is still rebooting
                pass
            except Exception as e:
                LOGGER.warning(f"{ip}: Unexpected error while waiting - {str(e)}")

            # Wait before next check (skip on last attempt)
            if attempt < max_attempts - 1:
                time.sleep(check_interval)

        elapsed_time = time.time() - start_time
        LOGGER.error(f"{ip}: Timeout - iLO did not come back online within {timeout_minutes}m ({elapsed_time:.1f}s)")
        return False

    def _get_ilo_version_from_response(self, redfish_data, base_url=None, username=None, password=None):
        """Get iLO version from Redfish response data."""
        model_version, ilo_version = 0, 0.0

        try:
            if all([redfish_data.get("Managers"), base_url, username, password]):
                model, firmware_version = self._get_ilo_model_and_version(base_url, username, password)

                if model and "iLO" in model:
                    model_version = int(model.replace("iLO", ""))

                if firmware_version:
                    parts = firmware_version.split()
                    if len(parts) >= 3:
                        # Handle old format: "iLO 6 v1.66" -> parts[2] = "v1.66"
                        if parts[0].lower() == "ilo" and parts[2].startswith('v'):
                            version_str = parts[2].lstrip('v')  # Remove 'v' prefix from old format
                        # Handle new format: "iLO 7 1.19.00 Nov 24 2025" -> parts[2] = "1.19.00"
                        elif parts[0].lower() == "ilo" and not parts[2].startswith('v'):
                            version_str = parts[2]  # Use version number as-is from new format
                        # Handle direct version format: "1.19.00 Nov 24 2025" -> parts[0] = "1.19.00"
                        else:
                            version_str = parts[0]  # Use first part for direct version format

                        version_parts = version_str.split(".")
                        ilo_version = float(".".join(version_parts[:2])) if len(version_parts) >= 2 else 0.0
            else:
                LOGGER.warning("Managers section not found in Redfish response or invalid credentials")
        except Exception as e:
            LOGGER.warning(f"Could not determine iLO version from response: {str(e)}")
            raise e

        return model_version, ilo_version

    def _is_pin_onboarding_supported(self, ilo_version, major_version):
        """Determine if PIN-based onboarding is supported

        :param ilo_version: iLO firmware version
        :type ilo_version: float
        :param major_version: iLO major version
        :type major_version: int
        :returns: True if PIN onboarding is supported
        :rtype: bool
        """
        # PIN-based onboarding support:
        # - iLO 6: available from version 1.64 onwards
        # - iLO 5: available from version 3.09 onwards
        # - iLO 7: available from version 1.12 onwards
        if major_version == 6 and ilo_version >= 1.64:
            return True
        elif major_version == 5 and ilo_version >= 3.09:
            return True
        elif major_version == 7 and ilo_version >= 1.12:
            return True
        return False

    def _check_ilo_version_compatibility(self, model, ilo_version, ip):
        """Check if iLO version is compatible with COM requirements

        :param model: iLO major version number
        :type model: int
        :param ilo_version: iLO firmware version
        :type ilo_version: float
        :param ip: iLO IP address for logging
        :type ip: str
        :returns: tuple of (is_compatible, error_message, recommendation)
        :rtype: tuple
        """
        # Define minimum supported versions
        ILO5_MIN_SUPPORTED = 2.47
        ILO6_MIN_SUPPORTED = 1.64
        ILO7_MIN_SUPPORTED = 1.12

        if model == 5 and ilo_version < ILO5_MIN_SUPPORTED:
            error_msg = f"iLO version should be greater than {ILO5_MIN_SUPPORTED}"
            recommendation = "Upgrade to the latest iLO version to use HPE Compute Ops Management"
            LOGGER.warning(f"{ip}: iLO version {ilo_version} incompatible - requires 2.47 or higher")
            return False, error_msg, recommendation
        elif model == 6 and ilo_version < ILO6_MIN_SUPPORTED:
            error_msg = f"iLO version should be greater than {ILO6_MIN_SUPPORTED}"
            recommendation = "Upgrade to the latest iLO version to use HPE Compute Ops Management"
            LOGGER.warning(f"{ip}: iLO version {ilo_version} incompatible - requires 1.64 or higher")
            return False, error_msg, recommendation
        elif model == 7 and ilo_version < ILO7_MIN_SUPPORTED:
            error_msg = f"iLO version should be greater than {ILO7_MIN_SUPPORTED}"
            recommendation = "Upgrade to the latest iLO version to use HPE Compute Ops Management"
            LOGGER.warning(f"{ip}: iLO version {ilo_version} incompatible - requires 1.12 or higher")
            return False, error_msg, recommendation

        # Compatible version
        return True, "", ""

    def _get_ilo_info(self, base_url, username, password):
        """Get iLO model and version information"""
        import requests
        from requests.auth import HTTPBasicAuth

        try:
            response = requests.get(
                f"{base_url}/redfish/v1/Managers/1/", auth=HTTPBasicAuth(username, password), verify=False, timeout=30
            )

            if response.status_code == 200:
                data = response.json()
                model = data.get("Model", "iLO5")
                firmware_version = data.get("FirmwareVersion", "3.09")

                try:
                    version_parts = firmware_version.split(".")
                    major_version = int(model.replace("iLO", "")) if "iLO" in model else 5

                    if len(version_parts) >= 2:
                        version_float = float(f"{version_parts[0]}.{version_parts[1]}")
                    else:
                        version_float = float(version_parts[0])
                except:
                    version_float = 3.09
                    major_version = 5

                return model, firmware_version, version_float, major_version
        except Exception as e:
            LOGGER.warning(f"Failed to get iLO info: {str(e)}")

        return "iLO5", "3.09", 3.09, 5

    def _get_ilo_model_and_version(self, base_url, username, password):
        """Get iLO model and version information from the Redfish API

        :param base_url: base URL for iLO
        :type base_url: str
        :param username: iLO username
        :type username: str
        :param password: iLO password
        :type password: str
        :returns: tuple of (model, firmware_version)
        :rtype: tuple
        """
        from requests.auth import HTTPBasicAuth

        try:
            mgr_response = requests.get(
                f"{base_url}/redfish/v1/Managers/1/",
                auth=HTTPBasicAuth(username, password),
                verify=False,
                timeout=30,
            )
            if mgr_response.status_code == 200:
                mgr_data = mgr_response.json()
                model = mgr_data.get("Model", "")
                firmware_version = mgr_data.get("FirmwareVersion", "")
                return model, firmware_version
            elif mgr_response.status_code == 401:
                LOGGER.warning("Authentication failed while retrieving iLO model and version")
                raise Exception("Authentication failed")
            else:
                return "", ""
        except Exception as e:
            LOGGER.warning(f"Failed to get iLO model and version: {str(e)}")
            raise e

    def _check_dns_configuration(self, session, base_url, network_settings, individual_settings):
        """Check if DNS is configured in iLO"""
        try:
            if individual_settings.get("skipDns", False):
                return True

            response = session.get(f"{base_url}/redfish/v1/Managers/1/EthernetInterfaces/1", timeout=30)
            if response.status_code == 200:
                data = response.json()
                oem_hpe = data.get("Oem", {}).get("Hpe", {})

                ipv4_dns = oem_hpe.get("IPv4", {}).get("DNSServers", [])
                ipv6_dns = oem_hpe.get("IPv6", {}).get("DNSServers", [])

                dns_servers = [dns for dns in (ipv4_dns + ipv6_dns) if dns and dns.strip() and dns != "0.0.0.0"]

                return len(dns_servers) > 0
        except Exception as e:
            LOGGER.warning(f"Failed to check DNS configuration: {str(e)}")

        return False

    def _check_ntp_configuration(self, session, base_url, network_settings, individual_settings):
        """Check if NTP is configured in iLO"""
        try:
            if individual_settings.get("skipNtp", False):
                return True

            response = session.get(f"{base_url}/redfish/v1/Managers/1/DateTime/", timeout=30)
            if response.status_code == 200:
                data = response.json()
                ntp_servers = data.get("NTPServers", [])
                static_ntp = data.get("StaticNTPServers", [])

                all_ntp = [ntp for ntp in (ntp_servers + static_ntp) if ntp and ntp.strip()]

                return len(all_ntp) > 0
        except Exception as e:
            LOGGER.warning(f"Failed to check NTP configuration: {str(e)}")

        return False

    def _check_com_connection_status(self, session, base_url):
        """Check if COM is already connected

        :param session: requests Session object
        :type session: requests.Session
        :param base_url: base URL for iLO
        :type base_url: str
        :returns: True if COM is connected or connection is unstable, False if not connected,
                  None if status check failed for other reasons
        :rtype: bool or None
        """
        try:
            response = session.get(f"{base_url}/redfish/v1/Managers/1/", timeout=30)
            if response.status_code != 200:
                LOGGER.warning(f"Failed to get manager resource, status: {response.status_code}")
                return False

            manager_data = response.json()
            cloud_connect = manager_data.get("Oem", {}).get("Hpe", {}).get("CloudConnect", {})
            current_status = cloud_connect.get("CloudConnectStatus", "")

            if current_status == "Connected":
                LOGGER.info(f"COM is already connected for {base_url.split('//')[1]}")
                return True
            return False
        except (ConnectionError, Timeout, RequestException) as e:
            # Connection errors indicate unstable connection - treat as "already connected" to be safe
            LOGGER.warning(f"Connection error while checking COM status: {str(e)}")
            LOGGER.info(
                "Treating as COM connected due to connection instability. Skipping configuration to avoid disruption."
            )
            return True  # Assume connected to avoid disruption during unstable connection
        except Exception as e:
            LOGGER.warning(f"Error checking COM connection status: {str(e)}")
            return None  # Cannot determine status

    def _configure_network_settings_requests(
        self, session, base_url, network_settings, individual_settings, allow_ilo_reset
    ):
        """Configure network settings using requests session

        :param session: requests Session object
        :type session: requests.Session
        :param base_url: base URL for iLO
        :type base_url: str
        :param network_settings: common network settings
        :type network_settings: dict
        :param individual_settings: individual iLO settings
        :type individual_settings: dict
        :param allow_ilo_reset: allow iLO reset if needed
        :type allow_ilo_reset: bool
        :returns: tuple of (ilo_was_reset flag, ntp_configured_needs_reset flag)
        :rtype: tuple(bool, bool)
        """
        ilo_was_reset = False
        ntp_configured_needs_reset = False
        all_configs_successful = True  # Track if all configurations succeed

        try:
            # Skip if both DNS and NTP are explicitly skipped
            if individual_settings.get("skipDns", False) and individual_settings.get("skipNtp", False):
                return ilo_was_reset, ntp_configured_needs_reset

            # Check COM connection status before doing any patch operation
            if self._check_com_connection_status(session, base_url):
                LOGGER.info("COM is already connected. Skipping network configuration to avoid disruption.")
                return ilo_was_reset, ntp_configured_needs_reset

            # Merge network settings (individual overrides common)
            merged_network = network_settings.copy() if isinstance(network_settings, dict) else {}
            individual_network = individual_settings.get("network", {})
            if individual_network and isinstance(individual_network, dict):
                merged_network.update(individual_network)

            # Configure DNS - if this fails, mark configs as unsuccessful
            if not individual_settings.get("skipDns", False) and merged_network.get("dns"):
                dns_servers = merged_network["dns"]
                try:
                    self._configure_dns(session, base_url, dns_servers)
                except Exception as dns_err:
                    all_configs_successful = False
                    LOGGER.error(f"DNS configuration failed, will not reset iLO: {str(dns_err)}")
                    raise  # Re-raise to stop processing

            # Configure NTP and capture if iLO was reset
            # Only allow iLO reset if all previous configurations succeeded
            if not individual_settings.get("skipNtp", False) and merged_network.get("ntp"):
                ntp_servers = merged_network["ntp"]
                # Pass allow_ilo_reset only if all configs successful so far
                effective_allow_reset = allow_ilo_reset and all_configs_successful
                if not effective_allow_reset and allow_ilo_reset:
                    LOGGER.warning("iLO reset disabled due to configuration errors, even though allow_ilo_reset=True")

                try:
                    ilo_was_reset, is_ntp_config_matching = self._configure_ntp(
                        session, base_url, ntp_servers, effective_allow_reset
                    )
                except Exception as ntp_err:
                    all_configs_successful = False
                    LOGGER.error(f"NTP configuration failed, will not reset iLO: {str(ntp_err)}")
                    raise  # Re-raise to stop processing

                LOGGER.info(f"is_ntp_config_matching {is_ntp_config_matching}")
                if is_ntp_config_matching:
                    return ilo_was_reset, ntp_configured_needs_reset

                # If allow_ilo_reset is False and NTP was configured, user must manually reset iLO
                if not allow_ilo_reset and not ilo_was_reset:
                    ntp_configured_needs_reset = True
                    LOGGER.warning("=" * 80)
                    LOGGER.warning("NTP CONFIGURATION REQUIRES MANUAL iLO RESET")
                    LOGGER.warning("=" * 80)
                    LOGGER.warning("NTP configuration has been applied, but --allow_ilo_reset was not specified.")
                    LOGGER.warning("Please manually reset the iLO for NTP changes to take effect,")
                    LOGGER.warning("then retry the onboarding command.")
                    LOGGER.warning("=" * 80)

        except Exception as e:
            error_msg = f"Failed to configure network settings: {str(e)}"
            LOGGER.error(error_msg)
            raise

        return ilo_was_reset, ntp_configured_needs_reset

    def _configure_dns(self, session, base_url, dns_servers):
        """Configure DNS settings for the iLO with IPv4 and IPv6 support.

        :param session: requests Session object
        :type session: requests.Session
        :param base_url: base URL for iLO
        :type base_url: str
        :param dns_servers: list of DNS servers (IPv4 and/or IPv6)
        :type dns_servers: list
        """
        try:
            # First, check if DNS servers are already configured as desired
            current_dns_servers, _, _ = self._get_current_dns_servers(session, base_url)

            if current_dns_servers is not None:
                # Normalize both lists for comparison (remove empty strings, sort)
                desired_dns = sorted([srv.strip() for srv in dns_servers if srv and srv.strip()])
                current_dns = sorted([srv.strip() for srv in current_dns_servers if srv and srv.strip()])

                if desired_dns == current_dns:
                    LOGGER.info(f"DNS already configured: {desired_dns}")
                    return
                else:
                    LOGGER.info(f"Updating DNS from {current_dns} to {desired_dns}")
            else:
                LOGGER.info("Unable to retrieve current DNS configuration. Proceeding with DNS configuration.")

            # Separate IPv4 and IPv6 DNS servers
            ipv4_dns_servers = []
            ipv6_dns_servers = []

            # Optimize: Strip once and reuse the cleaned value
            for dns_server in dns_servers:
                if dns_server:
                    dns_clean = dns_server.strip()
                    if dns_clean:
                        if self._is_ipv6_address(dns_clean):
                            ipv6_dns_servers.append(dns_clean)
                        else:
                            ipv4_dns_servers.append(dns_clean)

            # Use EthernetInterfaces endpoint to configure DNS properly
            dns_config_url = f"{base_url}/redfish/v1/Managers/1/EthernetInterfaces/1"

            # Build payload to disable DHCP for DNS servers and set static DNS for both IPv4 and IPv6
            payload = {
                "DHCPv4": {"UseDNSServers": False},
                "DHCPv6": {"UseDNSServers": False},
                "Oem": {"Hpe": {"DHCPv4": {"UseDNSServers": False}, "DHCPv6": {"UseDNSServers": False}}},
            }

            # Add IPv4 DNS servers if present
            if ipv4_dns_servers:
                payload["Oem"]["Hpe"]["IPv4"] = {"DNSServers": ipv4_dns_servers}

            # Add IPv6 DNS servers if present
            if ipv6_dns_servers:
                payload["Oem"]["Hpe"]["IPv6"] = {"DNSServers": ipv6_dns_servers}

            # Create fresh session for DNS configuration to avoid connection reuse issues
            dns_session = requests.Session()
            dns_session.auth = session.auth
            dns_session.verify = False

            LOGGER.info(f"Configuring DNS - IPv4: {ipv4_dns_servers}, IPv6: {ipv6_dns_servers}")

            response = dns_session.patch(dns_config_url, json=payload, timeout=30)

            if response.status_code not in [200, 204]:
                raise Exception(f"Failed to configure DNS. HTTP {response.status_code}: {response.text}")

            LOGGER.info("DNS configuration successful")
        except (ConnectionError, Timeout, RequestException) as e:
            error_msg = f"Connection error while configuring DNS: {str(e)}"
            LOGGER.error(error_msg)
            raise Exception(error_msg)
        except Exception as e:
            error_msg = f"Error configuring DNS: {str(e)}"
            LOGGER.error(error_msg)
            raise

    def _is_ipv6_address(self, address):
        """Check if the given address is an IPv6 address.

        :param address: IP address string
        :type address: str
        :returns: True if IPv6, False otherwise
        :rtype: bool
        """
        try:
            from ipaddress import IPv6Address

            IPv6Address(address)
            return True
        except (ValueError, Exception):
            return False

    def _get_current_dns_servers(self, session, base_url):
        """Get current DNS server configuration from iLO (both IPv4 and IPv6).

        :param session: requests Session object
        :type session: requests.Session
        :param base_url: base URL for iLO
        :type base_url: str
        :returns: list of currently configured DNS servers (IPv4 and IPv6), or None if unable to retrieve
        :rtype: list or None
        """
        dhcp_dns_enabled = False
        dhcp_check_attempted = False
        try:
            dns_config_url = f"{base_url}/redfish/v1/Managers/1/EthernetInterfaces/1"

            # Reuse existing session instead of creating a new one
            response = session.get(dns_config_url, timeout=30)
            if response.status_code == 200:
                data = response.json()

                dhcp_check_attempted = True
                dhcpv4_dns_enabled = data.get("DHCPv4", {}).get("UseDNSServers", False)
                dhcpv6_dns_enabled = data.get("DHCPv6", {}).get("UseDNSServers", False)

                oem_hpe = data.get("Oem", {}).get("Hpe", {})

                oem_dhcpv4_dns_enabled = oem_hpe.get("DHCPv4", {}).get("UseDNSServers", False)
                oem_dhcpv6_dns_enabled = oem_hpe.get("DHCPv6", {}).get("UseDNSServers", False)
                if any([dhcpv4_dns_enabled, dhcpv6_dns_enabled, oem_dhcpv4_dns_enabled, oem_dhcpv6_dns_enabled]):
                    LOGGER.info("DHCP DNS is enabled; static DNS servers may not be in use.")
                    dhcp_dns_enabled = True

                # Get both IPv4 and IPv6 DNS servers
                ipv4_dns_servers = oem_hpe.get("IPv4", {}).get("DNSServers", [])
                ipv6_dns_servers = oem_hpe.get("IPv6", {}).get("DNSServers", [])

                # Combine and filter using list comprehension (more efficient)
                current_dns_servers = [srv for srv in ipv4_dns_servers + ipv6_dns_servers if srv]

                formatted_dns_servers = [
                    srv.strip() for srv in current_dns_servers if srv and srv.strip() not in DNS_SERVER_EXCLUSION_LIST
                ]

                return formatted_dns_servers, dhcp_dns_enabled, dhcp_check_attempted
            else:
                LOGGER.warning(f"Failed to get current DNS configuration. HTTP {response.status_code}")
                return None, dhcp_dns_enabled, dhcp_check_attempted
        except (ConnectionError, Timeout, RequestException) as e:
            LOGGER.warning(f"Connection error while reading DNS configuration: {str(e)}")
            return None, dhcp_dns_enabled, dhcp_check_attempted
        except Exception as e:
            LOGGER.warning(f"Error reading DNS configuration: {str(e)}")
            return None, dhcp_dns_enabled, dhcp_check_attempted

    def _configure_ntp(self, session, base_url, ntp_servers, allow_ilo_reset):
        """Configure NTP settings for the iLO.

        :param session: requests Session object
        :type session: requests.Session
        :param base_url: base URL for iLO
        :type base_url: str
        :param ntp_servers: list of NTP servers
        :type ntp_servers: list
        :param allow_ilo_reset: allow iLO reset if needed
        :type allow_ilo_reset: bool
        :returns: tuple of (ilo_was_reset flag, is_config_matching flag)
        :rtype: tuple(bool, bool)
        """
        ilo_was_reset = False
        is_ntp_config_matching = False
        dhcp_disabled_successfully = False

        LOGGER.info(f"Starting NTP configuration for {base_url.split('//')[1]}")

        try:
            # First, check if DHCP NTP is enabled - if it is, static NTP list is irrelevant
            dhcp_ntp_is_enabled = False
            dhcp_check_attempted = False

            eth_interfaces_url = f"{base_url}/redfish/v1/Managers/1/EthernetInterfaces"

            dhcp_ntp_is_enabled, dhcp_disabled_successfully, dhcp_check_attempted = self._check_dhcp_ntp_config_on_interfaces(
                session,
                base_url,
                eth_interfaces_url,
            )

            if dhcp_check_attempted and not dhcp_ntp_is_enabled:
                LOGGER.info("DHCP NTP is already disabled on all ethernet interfaces")
                current_ntp_servers = self._get_current_ntp_servers(session, base_url)
                ntp_ips = [ntp_ip.strip() for ntp_ip in ntp_servers if ntp_ip and ntp_ip.strip()]
                if sorted(current_ntp_servers) == sorted(ntp_ips):
                    LOGGER.info("NTP servers are already configured as desired")
                    is_ntp_config_matching = True
                    return ilo_was_reset, is_ntp_config_matching

            # If we couldn't check any interface due to errors
            if not dhcp_check_attempted:
                LOGGER.warning("Could not check DHCP NTP status - will attempt to disable")

            # Always apply NTP configuration regardless of current state
            is_ntp_config_matching = False

            # Disable DHCP NTP if it's enabled
            if dhcp_ntp_is_enabled:
                LOGGER.info("Disabling DHCP NTP on ethernet interfaces")

                # Try to disable DHCP on ethernet interfaces
                try:
                    eth_response = session.get(eth_interfaces_url, timeout=30)
                    if eth_response.status_code == 200:
                        eth_data = eth_response.json()
                        members = eth_data.get("Members", [])

                        for member in members:
                            interface_url = base_url + member.get("@odata.id", "")
                            try:
                                interface_response = session.get(interface_url, timeout=30)
                                if interface_response.status_code == 200:
                                    interface_data = interface_response.json()
                                    if interface_data.get("Status", {}).get("State") == "Enabled":
                                        dhcp_ntp_payload = {
                                            "DHCPv4": {"UseNTPServers": False},
                                            "DHCPv6": {"UseNTPServers": False},
                                            "Oem": {
                                                "Hpe": {
                                                    "DHCPv4": {"UseNTPServers": False},
                                                    "DHCPv6": {"UseNTPServers": False},
                                                }
                                            },
                                        }

                                        dhcp_response = session.patch(interface_url, json=dhcp_ntp_payload, timeout=30)
                                        if dhcp_response.status_code in [200, 204]:
                                            LOGGER.info("Successfully disabled DHCP NTP")
                                            dhcp_disabled_successfully = True
                                            time.sleep(3)
                                            break
                            except Exception:
                                continue

                        if not dhcp_disabled_successfully:
                            LOGGER.warning("Could not disable DHCP NTP via ethernet interfaces")
                except Exception:
                    pass
            else:
                dhcp_disabled_successfully = True

            # Configure static NTP servers
            if not is_ntp_config_matching:
                # If DHCP wasn't disabled via ethernet interfaces, try NetworkProtocol
                if not dhcp_disabled_successfully:
                    try:
                        network_protocol_url = f"{base_url}/redfish/v1/Managers/1/NetworkProtocol"
                        network_payload = {
                            "NTP": {"ProtocolEnabled": True},
                            "Oem": {"Hpe": {"ConfigurationSettings": "Current"}},
                        }

                        network_response = session.patch(network_protocol_url, json=network_payload, timeout=30)

                        if network_response.status_code in [200, 204]:
                            LOGGER.info("Successfully configured NetworkProtocol for static NTP")
                            dhcp_disabled_successfully = True
                            time.sleep(3)
                    except Exception:
                        pass

                # If still not successful after all attempts, raise error and stop
                if not dhcp_disabled_successfully:
                    error_msg = (
                        "Failed to disable DHCP NTP. Cannot apply static NTP configuration while DHCP NTP is enabled."
                    )
                    LOGGER.error(error_msg)
                    raise Exception(error_msg)

                # Apply static NTP servers
                ntp_datetime_url = f"{base_url}/redfish/v1/Managers/1/DateTime"
                ntp_server_list = list(ntp_servers)

                if len(ntp_server_list) == 1:
                    ntp_server_list.append("")

                payload = {"StaticNTPServers": ntp_server_list}
                LOGGER.info(f"Configuring static NTP servers: {ntp_servers}")

                try:
                    response = session.patch(ntp_datetime_url, json=payload, timeout=30)

                    if response.status_code not in [200, 204]:
                        error_msg = f"Failed to configure NTP. HTTP {response.status_code}: {response.text}"
                        LOGGER.error(error_msg)
                        raise Exception(error_msg)
                except (ConnectionError, Timeout, RequestException) as conn_err:
                    LOGGER.warning(f"Connection error during NTP configuration: {str(conn_err)}")
                    LOGGER.info("NTP configuration may have been applied despite connection error")
                    is_ntp_config_matching = False

            # NTP configuration may require iLO reset to take effect
            # Only reset if allow_ilo_reset is True
            if allow_ilo_reset:
                LOGGER.info("Initiating iLO reset for NTP configuration")
                reset_url = f"{base_url}/redfish/v1/Managers/1/Actions/Manager.Reset"
                reset_payload = {"ResetType": "GracefulRestart"}

                try:
                    reset_response = session.post(reset_url, json=reset_payload, timeout=30)

                    if reset_response.status_code in [200, 202, 204]:
                        LOGGER.info("iLO reset initiated successfully")
                        ilo_was_reset = True
                        time.sleep(30)
                    else:
                        LOGGER.warning(f"Failed to reset iLO - HTTP {reset_response.status_code}")
                except (ConnectionError, Timeout, RequestException):
                    LOGGER.info("iLO appears to be resetting (connection closed)")
                    ilo_was_reset = True
                    time.sleep(30)
            else:
                LOGGER.info("NTP configured but iLO reset not allowed - manual reset may be required")

        except (ConnectionError, Timeout, RequestException) as e:
            LOGGER.error(f"Connection error during NTP configuration: {str(e)}")
        except Exception as e:
            LOGGER.error(f"Error configuring NTP: {str(e)}")

        LOGGER.info(f"NTP configuration completed - reset={ilo_was_reset}, matching={is_ntp_config_matching}")
        return ilo_was_reset, is_ntp_config_matching

    def _check_dhcp_ntp_config_on_interfaces(self, session, base_url, eth_interfaces_url):
        """Check NTP configuration status on ethernet interfaces.

        :param session: requests Session object
        :type session: requests.Session
        :param base_url: base URL for iLO
        :type base_url: str
        :param members: list of ethernet interface members
        :type members: list
        :returns: tuple of (dhcp_ntp_is_enabled, dhcp_disabled_successfully, dhcp_check_attempted)
        :rtype: tuple(bool, bool, bool)
        """
        dhcp_ntp_is_enabled = False
        dhcp_disabled_successfully = False
        dhcp_check_attempted = False

        members = []
        try:
            eth_response = session.get(eth_interfaces_url, timeout=30)

            if eth_response.status_code == 200:
                eth_data = eth_response.json()
                members = eth_data.get("Members", [])
        except (ConnectionError, Timeout, RequestException) as eth_err:
            LOGGER.warning(f"Error accessing ethernet interfaces: {str(eth_err)}")
            return dhcp_ntp_is_enabled, dhcp_disabled_successfully, dhcp_check_attempted

        # Find the first enabled interface to check/disable DHCP NTP
        for idx, member in enumerate(members):
            interface_url = base_url + member.get("@odata.id", "")

            try:
                interface_response = session.get(interface_url, timeout=30)

                if interface_response.status_code == 200:
                    interface_data = interface_response.json()
                    interface_state = interface_data.get("Status", {}).get("State")

                    if interface_state == "Enabled":
                        dhcp_check_attempted = True

                        dhcpv4_ntp_enabled = interface_data.get("DHCPv4", {}).get("UseNTPServers", False)
                        dhcpv6_ntp_enabled = interface_data.get("DHCPv6", {}).get("UseNTPServers", False)
                        oem_dhcpv4_ntp = (
                            interface_data.get("Oem", {})
                            .get("Hpe", {})
                            .get("DHCPv4", {})
                            .get("UseNTPServers", False)
                        )
                        oem_dhcpv6_ntp = (
                            interface_data.get("Oem", {})
                            .get("Hpe", {})
                            .get("DHCPv6", {})
                            .get("UseNTPServers", False)
                        )

                        if any([dhcpv4_ntp_enabled, dhcpv6_ntp_enabled, oem_dhcpv4_ntp, oem_dhcpv6_ntp]):
                            # DHCP NTP is enabled
                            dhcp_ntp_is_enabled = True
                            LOGGER.info("DHCP NTP is enabled, will disable and configure static NTP")
                        else:
                            LOGGER.info("DHCP NTP already disabled")
                            dhcp_disabled_successfully = True
                        break
            except (ConnectionError, Timeout, RequestException) as iface_err:
                # Connection errors during interface access - implement retry with new session
                LOGGER.warning(f"Connection error accessing interface: {type(iface_err).__name__}")

                # For RemoteDisconnected errors, retry once with a fresh session
                if "RemoteDisconnected" in str(type(iface_err)) or "Connection aborted" in str(iface_err):
                    retry_session = None
                    try:
                        time.sleep(2)
                        retry_session = requests.Session()
                        retry_session.auth = session.auth
                        retry_session.verify = False
                        retry_response = retry_session.get(interface_url, timeout=30)
                        if retry_response.status_code == 200:
                            interface_data = retry_response.json()
                            interface_state = interface_data.get("Status", {}).get("State")

                            if interface_state == "Enabled":
                                dhcp_check_attempted = True
                                dhcpv4_ntp_enabled = interface_data.get("DHCPv4", {}).get(
                                    "UseNTPServers", False
                                )
                                dhcpv6_ntp_enabled = interface_data.get("DHCPv6", {}).get(
                                    "UseNTPServers", False
                                )
                                oem_dhcpv4_ntp = (
                                    interface_data.get("Oem", {})
                                    .get("Hpe", {})
                                    .get("DHCPv4", {})
                                    .get("UseNTPServers", False)
                                )
                                oem_dhcpv6_ntp = (
                                    interface_data.get("Oem", {})
                                    .get("Hpe", {})
                                    .get("DHCPv6", {})
                                    .get("UseNTPServers", False)
                                )

                                if any(
                                    [dhcpv4_ntp_enabled, dhcpv6_ntp_enabled, oem_dhcpv4_ntp, oem_dhcpv6_ntp]
                                ):
                                    dhcp_ntp_is_enabled = True
                                    LOGGER.info("DHCP NTP enabled (retry check)")
                                else:
                                    dhcp_disabled_successfully = True
                                break
                    except Exception:
                        pass
                    finally:
                        if retry_session:
                            retry_session.close()
                continue

        return dhcp_ntp_is_enabled, dhcp_disabled_successfully, dhcp_check_attempted

    def _get_current_ntp_servers(self, session, base_url):
        """Get current NTP server configuration from iLO.

        :param session: requests Session object
        :type session: requests.Session
        :param base_url: base URL for iLO
        :type base_url: str
        :returns: list of currently configured NTP servers, or None if unable to retrieve
        :rtype: list or None
        """
        try:
            ntp_datetime_url = f"{base_url}/redfish/v1/Managers/1/DateTime"
            response = session.get(ntp_datetime_url, timeout=30)

            if response.status_code == 200:
                data = response.json()
                current_ntp_servers = data.get("StaticNTPServers", [])
                # Filter out empty strings and None values using list comprehension
                current_ntp_servers = [srv for srv in current_ntp_servers if srv]
                return current_ntp_servers
            else:
                LOGGER.warning(f"Failed to get NTP configuration - HTTP {response.status_code}")
                return None
        except (ConnectionError, Timeout, RequestException) as e:
            LOGGER.warning(f"Connection error reading NTP configuration: {str(e)}")
            return None
        except Exception as e:
            LOGGER.warning(f"Error reading NTP configuration: {str(e)}")
            return None

    def _get_current_proxy_settings(self, session, base_url):
        """Get current proxy configuration from iLO.

        :param session: requests Session object
        :type session: requests.Session
        :param base_url: base URL for iLO
        :type base_url: str
        :returns: dict with current proxy settings, or None if unable to retrieve
        :rtype: dict or None
        """
        try:
            proxy_config_url = f"{base_url}/redfish/v1/Managers/1/NetworkProtocol/"

            # Reuse existing session instead of creating a new one
            response = session.get(proxy_config_url, timeout=30)
            if response.status_code == 200:
                data = response.json()
                web_proxy = data.get("Oem", {}).get("Hpe", {}).get("WebProxyConfiguration", {})

                # Get raw values
                raw_server = web_proxy.get("ProxyServer", "")
                raw_port = web_proxy.get("ProxyPort")
                raw_username = web_proxy.get("ProxyUserName", "")

                # Normalize all values: treat empty strings and None as "no proxy"
                # Use 'is not None' check for port to correctly handle port 0
                current_proxy = {
                    "server": raw_server.strip() if raw_server else "",
                    "port": raw_port if raw_port is not None else None,
                    "username": raw_username.strip() if raw_username else "",
                }

                return current_proxy
            else:
                LOGGER.warning(f"Failed to get current proxy configuration. HTTP {response.status_code}")
                return None
        except (ConnectionError, Timeout, RequestException) as e:
            LOGGER.warning(f"Connection error while reading proxy configuration: {str(e)}")
            return None
        except Exception as e:
            LOGGER.warning(f"Error reading proxy configuration: {str(e)}")
            return None

    def _configure_proxy_for_ilo_requests(self, session, base_url, proxy_settings, individual_settings=None):
        """Configure proxy settings using requests session

        :param session: requests Session object
        :type session: requests.Session
        :param base_url: base URL for iLO
        :type base_url: str
        :param proxy_settings: proxy settings
        :type proxy_settings: dict
        :param individual_settings: individual iLO settings
        :type individual_settings: dict or None
        """
        try:
            # Check if proxy configuration should be skipped
            if individual_settings and individual_settings.get("skipProxy", False):
                LOGGER.info("Proxy configuration skipped per individual settings.")
                return

            # Check COM connection status before doing any patch operation
            if self._check_com_connection_status(session, base_url):
                LOGGER.info("COM is already connected. Skipping proxy configuration to avoid disruption.")
                return

            individual_proxy = individual_settings.get("proxy", {})
            # Only configure if proxy_settings exists and has meaningful content
            # Check if there's actually a proxy server to configure
            if not proxy_settings and not individual_proxy:
                LOGGER.info("No proxy settings provided. Skipping proxy configuration.")
                return

            # Apply proxy from individual or range in if present over common
            # Else proxy from common settings
            proxy_to_configure = individual_proxy if individual_proxy else proxy_settings

            # Check if server is provided and not empty
            proxy_server = proxy_to_configure.get("server", "").strip() if proxy_to_configure.get("server") else ""
            if not proxy_server:
                LOGGER.info("No proxy server specified. Skipping proxy configuration.")
                return

            # At this point, we have valid proxy settings to configure
            self._configure_proxy(session, base_url, proxy_to_configure)
            # Give iLO time to process proxy changes
            time.sleep(2)
        except Exception as e:
            error_msg = f"Failed to configure proxy settings: {str(e)}"
            LOGGER.error(error_msg)
            raise

    def _configure_proxy(self, session, base_url, proxy_settings):
        """Configure proxy settings for the iLO.

        :param session: requests Session object
        :type session: requests.Session
        :param base_url: base URL for iLO
        :type base_url: str
        :param proxy_settings: proxy settings
        :type proxy_settings: dict
        """
        try:
            # First, check if proxy settings are already configured as desired
            current_proxy = self._get_current_proxy_settings(session, base_url)

            if current_proxy is not None:
                # Normalize desired proxy settings for comparison
                # Treat empty strings and None as "no proxy configured"
                desired_server = proxy_settings.get("server", "").strip() if proxy_settings.get("server") else ""
                desired_port = proxy_settings.get("port") if proxy_settings.get("port") else None
                desired_credentials = proxy_settings.get("credentials", {})
                # Normalize port to int for comparison if not None
                if desired_port is not None:
                    try:
                        desired_port = int(desired_port)
                    except (ValueError, TypeError):
                        desired_port = None
                desired_username = desired_credentials.get("username", "").strip() if desired_credentials else ""

                # Normalize current proxy settings (already normalized in _get_current_proxy_settings)
                current_server = current_proxy.get("server", "")
                current_port = current_proxy.get("port")
                # Ensure current port is also int or None for consistent comparison
                if current_port is not None:
                    try:
                        current_port = int(current_port)
                    except (ValueError, TypeError):
                        current_port = None
                current_username = current_proxy.get("username", "")

                # Detect "no proxy" scenarios:
                # iLO has no proxy if: server is empty string AND port is None
                current_has_no_proxy = not current_server and current_port is None
                desired_has_no_proxy = not desired_server and desired_port is None

                if current_has_no_proxy and desired_has_no_proxy:
                    LOGGER.info("Proxy not configured - skipping")
                    return
                elif (
                    desired_server == current_server
                    and desired_port == current_port
                    and desired_username == current_username
                ):
                    LOGGER.info(f"Proxy already configured: {desired_server}:{desired_port}")
                    return
                else:
                    LOGGER.info(f"Updating proxy configuration to {desired_server}:{desired_port}")
            else:
                LOGGER.info("Unable to retrieve current proxy configuration. Proceeding with proxy configuration.")

            proxy_config_url = f"{base_url}/redfish/v1/Managers/1/NetworkProtocol/"

            # Build proxy configuration payload
            web_proxy_config = {
                "ProxyServer": proxy_settings.get("server", ""),
                "ProxyPort": proxy_settings.get("port"),
                "ProxyUserName": "",
                "ProxyPassword": "",
            }

            # Only add username and password if they are provided (not None and not empty)
            username = desired_credentials.get("username", "").strip() if desired_credentials else ""
            password = desired_credentials.get("password", "").strip() if desired_credentials else ""

            if username:
                web_proxy_config["ProxyUserName"] = username
            if password:
                web_proxy_config["ProxyPassword"] = password

            payload = {"Oem": {"Hpe": {"WebProxyConfiguration": web_proxy_config}}}

            response = session.patch(proxy_config_url, json=payload, timeout=30)

            if response.status_code not in [200, 204]:
                raise Exception(f"Failed to configure proxy. HTTP {response.status_code}: {response.text}")

            LOGGER.info("Proxy configured successfully")
        except Exception as e:
            error_msg = f"Error configuring proxy: {str(e)}"
            LOGGER.error(error_msg)
            raise

    def _enable_com_connection_requests(self, session, base_url, activation_key):
        """Enable COM connection using requests session

        :param session: requests Session object
        :type session: requests.Session
        :param base_url: base URL for iLO
        :type base_url: str
        :param activation_key: COM activation key or PIN
        :type activation_key: str
        :returns: tuple of (success, fail_reason) where success is True/False and fail_reason is string or None
        :rtype: tuple
        """

        try:
            # Get manager resource to check COM capabilities with timeout
            response = session.get(f"{base_url}/redfish/v1/Managers/1/", timeout=30)
            if response.status_code != 200:
                LOGGER.warning(f"Failed to get manager resource - HTTP {response.status_code}")
                return False, f"Failed to get manager resource: HTTP {response.status_code}"

            manager_data = response.json()

            # Check if COM is already connected
            cloud_connect = manager_data.get("Oem", {}).get("Hpe", {}).get("CloudConnect", {})
            current_status = cloud_connect.get("CloudConnectStatus", "")

            if current_status == "Connected":
                LOGGER.info("iLO is already connected")
                return True, None

            # Check if COM connect actions are available
            oem_actions = manager_data.get("Oem", {}).get("Hpe", {}).get("Actions", {})
            if "#HpeiLO.EnableCloudConnect" not in oem_actions:
                LOGGER.warning("COM feature not available on this iLO")
                return False, "COM feature not available"

            # Enable cloud connect with proper error handling and retry logic
            action_uri = f"{base_url}/redfish/v1/Managers/1/Actions/Oem/Hpe/HpeiLO.EnableCloudConnect/"
            body = {"ActivationKey": activation_key} if activation_key else {}

            LOGGER.info("Enabling COM connection")

            # Create a new session for the POST request to avoid connection reuse issues
            post_session = requests.Session()
            post_session.auth = session.auth
            post_session.verify = False

            success = False
            retry_count = 0
            max_retries = 3

            while retry_count <= max_retries and not success:
                try:
                    timeout_value = 90 + (retry_count * 30)  # Increase timeout with retries
                    response = post_session.post(action_uri, json=body, timeout=timeout_value)

                    if response.status_code in [200, 202]:
                        success = True
                        LOGGER.info("COM enable request successful")
                    else:
                        LOGGER.warning(f"COM enable failed - HTTP {response.status_code}")
                        if retry_count < max_retries:
                            retry_count += 1
                            time.sleep(5)
                        else:
                            return False, "COM enable request failed"

                except (ConnectionError, Timeout, RequestException) as conn_err:
                    LOGGER.warning(f"Connection issue during COM enable: {str(conn_err)}")

                    # Give iLO time to process the request
                    time.sleep(10)

                    # Try to check if the request was actually accepted by querying status
                    try:
                        status_response = session.get(f"{base_url}/redfish/v1/Managers/1/", timeout=30)
                        if status_response.status_code == 200:
                            mgr_data = status_response.json()
                            cc_status = (
                                mgr_data.get("Oem", {})
                                .get("Hpe", {})
                                .get("CloudConnect", {})
                                .get("CloudConnectStatus", "")
                            )
                            if cc_status in ["Initializing", "ConnectionInProgress", "Connected"]:
                                LOGGER.info(f"COM enable appears successful (status: {cc_status})")
                                success = True
                                break
                    except Exception:
                        pass

                    if retry_count < max_retries:
                        retry_count += 1
                        time.sleep(15)
                    else:
                        LOGGER.warning("Connection errors occurred, will check status to confirm")
                        success = True  # Proceed to status checking
                        break

            if not success:
                return False, "COM enable request failed"

            # Wait for connection to complete with improved status checking
            max_wait = 480  # Increased from 180s (3 min) to 480s (8 min)
            wait_interval = 12
            waited = 0

            while waited < max_wait:
                time.sleep(wait_interval)
                waited += wait_interval

                try:
                    status_response = session.get(f"{base_url}/redfish/v1/Managers/1/", timeout=30)
                    if status_response.status_code == 200:
                        manager_data = status_response.json()
                        cloud_connect = manager_data.get("Oem", {}).get("Hpe", {}).get("CloudConnect", {})
                        current_status = cloud_connect.get("CloudConnectStatus", "")

                        if current_status == "Connected":
                            LOGGER.info("COM connection successful")
                            return True, None
                        elif current_status == "Initializing":
                            LOGGER.info("COM connection is initializing, waiting...")
                            continue  # Keep waiting
                        elif current_status == "ConnectionFailed":
                            LOGGER.warning(f"COM connect terminal Status: {current_status}")
                            break
                        elif current_status in ["NotConnected", "NotEnabled"]:
                            fail_reason = cloud_connect.get("FailReason", "Unknown error")

                            LOGGER.warning(f"COM Current Status: {current_status}")
                            LOGGER.warning("Continuing to wait ...")
                            continue  # Keep waiting
                        # Add other terminal states if needed
                    else:
                        LOGGER.warning(
                            f"Failed to get manager resource during status check - HTTP {status_response.status_code}"
                        )
                except (ConnectionError, Timeout, RequestException):
                    LOGGER.warning("Connection error during COM status polling, will retry...")
                    continue
                except Exception as check_err:
                    LOGGER.warning(f"Error during COM status polling: {str(check_err)}")
                    continue

            status_response = session.get(f"{base_url}/redfish/v1/Managers/1/", timeout=30)
            if status_response.status_code == 200:
                manager_data = status_response.json()
                cloud_connect = manager_data.get("Oem", {}).get("Hpe", {}).get("CloudConnect", {})
                current_status = cloud_connect.get("CloudConnectStatus", "")
                if current_status == "Connected":
                    LOGGER.info("COM connection successful")
                    return True, None
                else:
                    fail_reason = cloud_connect.get("FailReason", "Unknown error")
                    LOGGER.warning(f"COM connection failed - final status: {current_status}")
                    return False, f"COM connection failed: {fail_reason}"

        except (ConnectionError, Timeout, RequestException) as e:
            LOGGER.warning(f"Connection error during COM enable: {str(e)}")
            # Try to verify if the connection actually succeeded
            try:
                verify_session = requests.Session()
                verify_session.auth = session.auth
                verify_session.verify = False
                time.sleep(5)

                response = verify_session.get(f"{base_url}/redfish/v1/Managers/1/", timeout=30)
                if response.status_code == 200:
                    mgr_data = response.json()
                    cc_status = (
                        mgr_data.get("Oem", {}).get("Hpe", {}).get("CloudConnect", {}).get("CloudConnectStatus", "")
                    )
                    if cc_status in ["Initializing", "ConnectionInProgress", "Connected"]:
                        LOGGER.info(f"COM enable appears successful despite connection error (status: {cc_status})")
                        success = True
                    else:
                        return False, "Connection error"
                else:
                    return False, "Connection error"
            except Exception:
                return False, "Connection error"

            if not success:
                return False, "Connection error"

        except Exception as e:
            LOGGER.error(f"Unexpected error enabling COM: {str(e)}")
            return False, str(e)

    def _save_json_report(self, report, output_file):
        """Save report to JSON file with proper formatting

        :param report: report data to save
        :type report: dict
        :param output_file: output filename
        :type output_file: str
        :returns: True if successful, False otherwise
        :rtype: bool
        """
        try:
            with open(output_file, "w") as f:
                json.dump(report, f, indent=2, sort_keys=True)

            LOGGER.info(f"Report successfully saved to {output_file}")

        except Exception as e:
            error_msg = f"Failed to save report to {output_file}: {str(e)}"
            LOGGER.error(error_msg)
            raise Exception(error_msg)

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
            except Exception:
                return ReturnCodes.SUCCESS
            return ReturnCodes.SUCCESS
        try:
            (options, _) = self.rdmc.rdmc_parse_arglist(self, line)
        except (InvalidCommandLineErrorOPTS, SystemExit):
            if ("-h" in line) or ("--help" in line):
                return ReturnCodes.SUCCESS
            else:
                raise InvalidCommandLineErrorOPTS("")

        # Skip validations for multiconnect as it handles multiple connections differently
        if not (options.command and options.command.lower() == "multiconnect"):
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
            elif options.command.lower() == "multiconnect":
                # Handle template generation
                if options.template_input_file is not None:
                    self.generate_template_file(options.template_input_file)
                # Handle bulk operations
                elif options.file:
                    if getattr(options, "precheck", False):
                        result = self.bulk_connect_precheck(options.file, options.output_file)
                        if result != ReturnCodes.SUCCESS:
                            return result
                    else:
                        result = self.bulk_connect(options.file, options.output_file, options.allow_ilo_reset)
                        if result != ReturnCodes.SUCCESS:
                            return result
                else:
                    raise InvalidCommandLineError(
                        "For multiconnect command, either --input_file_json_template"
                        " or --input_file must be specified. "
                        "Use -h for help."
                    )
            else:
                raise InvalidCommandLineError("%s is not a valid option for this command." % str(options.command))
        else:
            raise InvalidCommandLineError(
                "Please provide either connect, disconnect, status, or multiconnect as additional subcommand."
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
        )
        self.cmdbase.add_login_arguments_group(disconnect_parser)

        # Multiconnect subcommand
        multiconnect_help = "Bulk connect multiple iLOs using JSON configuration"
        multiconnect_parser = subcommand_parser.add_parser(
            "multiconnect",
            help=multiconnect_help,
            description=multiconnect_help
            + """
                EXAMPLES:
                    # Generate template JSON file
                    computeopsmanagement multiconnect --input_file_json_template
                    # Generate precheck report without making applying changes
                    computeopsmanagement multiconnect --input_file servers.json --precheck
                    computeopsmanagement multiconnect --input_file servers.json --precheck --output report.json
                    # Onboard multiple servers from JSON file to COM
                    computeopsmanagement multiconnect --input_file servers.json
                    computeopsmanagement multiconnect --input_file servers.json --allow_ilo_reset
                    computeopsmanagement multiconnect --input_file servers.json --allow_ilo_reset --output report.json
                """,
            formatter_class=RawDescriptionHelpFormatter,
        )

        multiconnect_parser.add_argument(
            "--input_file",
            "-i",
            dest="file",
            help="Path to JSON file containing bulk server configuration",
            required=False,
            type=str,
            default=None,
        )

        multiconnect_parser.add_argument(
            "--input_file_json_template",
            "-t",
            dest="template_input_file",
            help=f"Generate template JSON input file (writes {DEFAULT_TEMPLATE_FILE_NAME})",
            action="store_const",
            const=DEFAULT_TEMPLATE_FILE_NAME,
            default=None,
        )

        # Create mutually exclusive group for precheck and allow_ilo_reset
        exclusive_group = multiconnect_parser.add_mutually_exclusive_group()

        exclusive_group.add_argument(
            "--allow_ilo_reset",
            "-r",
            dest="allow_ilo_reset",
            help="If needed, allow iLO reset during bulk operations",
            required=False,
            action="store_true",
            default=False,
        )

        multiconnect_parser.add_argument(
            "--output",
            "-of",
            dest="output_file",
            help="Output file for reports",
            required=False,
            type=str,
            default=None,
        )

        exclusive_group.add_argument(
           "--precheck",
           "-c",
           dest="precheck",
           help="Perform precheck validation only (no onboarding or configuration)",
           required=False,
           action="store_true",
           default=False,
        )
