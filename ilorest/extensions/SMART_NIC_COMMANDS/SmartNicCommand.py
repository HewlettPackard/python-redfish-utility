###
# Copyright 2016-2022 Hewlett Packard Enterprise, Inc. All rights reserved.
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
""" Smart Nic Command for rdmc """
import os
import time

try:
    from rdmc_helper import (
        UI,
        FirmwareUpdateError,
        IncompatibleiLOVersionError,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        ReturnCodes,
        UploadError,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        UI,
        FirmwareUpdateError,
        IncompatibleiLOVersionError,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        ReturnCodes,
        UploadError,
    )


class SmartNicCommand:
    """Smart nic command"""

    def __init__(self):
        self.ident = {
            "name": "smartnic",
            "usage": None,
            "description": "\tRun without arguments for the "
            "current list of smartnic including json format.\n\texample: "
            "smartnic/smartnic -j\n\n"
            "Show all available options\n\n\t"
            "example: smartnic --id <id> \n\t"
            "smartnic --id <id> -j\n\t"
            "smartnic --id <id> --logs\n\t"
            "smartnic --id <id> --bootprogress\n\t"
            "smartnic --id <id> --clearlog\n\t"
            "smartnic --id <id> --update_fw <fwpkg>\n\t"
            "smartnic --id <id> --reset < GracefulShutdown / ForceRestart / Nmi / GracefulRestart >\n",
            "summary": "Discovers all pensando nic installed in the " "server",
            "aliases": [],
            "auxcommands": ["SelectCommand"],
        }
        self.config_file = None
        self.fdata = None
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """Smartnic command"""

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
        if args:
            raise InvalidCommandLineError("servernic command takes no " "arguments.")

        ilo_ver = self.rdmc.app.getiloversion()
        if ilo_ver < 5.268:
            raise IncompatibleiLOVersionError(
                "Please upgrade to iLO 5 2.68 or " "greater to ensure correct flash of this firmware."
            )

        self.smartnicvalidation(options)

        path = self.rdmc.app.typepath.defs.systempath

        info = self.gatherinfo(path)

        if not info:
            raise InvalidCommandLineError("No SmartNic available.")

        fw_version = self.get_fw_version()
        options_system = True

        if options.json and options.id is not None:
            string_id = options.id
            to_list = list(string_id.split(","))
            for id in to_list:
                if options.bootprogress:
                    if id == info["Id"]:
                        json_content = self.print_get_bootprogress(info)
                        UI().print_out_json(json_content)
                    elif id != info["Id"]:
                        self.rdmc.ui.printer("No bootprogress present for given smartnic id %s \n" % id)

                elif options.logs:
                    if id == info["Id"]:
                        json_content = self.print_get_logs(info)
                        UI().print_out_json(json_content)
                    elif id != info["Id"]:
                        self.rdmc.ui.printer("No logs present for given smartnic id %s \n" % id)

                elif options_system:
                    if id == info["Id"] and info["SystemType"] == "DPU":
                        json_content = self.build_json_out(info, fw_version)
                        UI().print_out_json(json_content)
                    elif id != info["Id"] or info["SystemType"] != "DPU":
                        self.rdmc.ui.printer("System %s:\n" % id)
                        self.rdmc.ui.printer("\tNo SmartNic present in given id %s \n" % id)

        elif options.json and options.id is None and options_system and not options.logs and not options.bootprogress:
            if info["SystemType"] == "DPU":
                json_content = self.build_json_out(info, fw_version)
                UI().print_out_json(json_content)
            if info["SystemType"] != "DPU":
                self.rdmc.ui.printer("System %s:\n" % id)
                self.rdmc.ui.printer("\tNo SmartNic present in given id %s \n" % id)

        elif (options.json and options.logs and options.id is None) or (
            options.logs and not options.json and options.id is None
        ):
            raise InvalidCommandLineError(
                "No command --logs for smartnic\n"
                "usage: smartnic --id <id> --logs \n"
                "\t  smartnic --id <id> --logs -j"
            )

        elif (options.bootprogress and options.json and options.id is None) or (
            options.bootprogress and not options.json and options.id is None
        ):
            raise InvalidCommandLineError(
                "No command --bootprogress for smartnic\n"
                "usage: smartnic --id <id> --bootprogress\n"
                "\t smartnic --id <id> --bootprogress -j"
            )

        else:
            if options.id is not None:
                string_id = options.id
                str_lst = list(string_id.split(","))
                if options.update_fw is None and options.reset is None:
                    for id in str_lst:
                        if options.bootprogress:
                            if id == info["Id"]:
                                self.get_bootprogress(info)
                            elif id != info["Id"]:
                                self.rdmc.ui.printer("No bootprogress present for given smartnic id %s\n" % id)

                        elif options.logs:
                            if id == info["Id"]:
                                self.get_logs(info)
                            elif id != info["Id"]:
                                self.rdmc.ui.printer("No logs present for given smartnic id %s \n" % id)

                        elif options_system and not options.clearlog and not options.logs:
                            if id == info["Id"] and info["SystemType"] == "DPU":
                                self.prettyprintinfo(info, fw_version)
                            elif id != info["Id"] or info["SystemType"] != "DPU":
                                self.rdmc.ui.printer("System %s:\n" % id)
                                self.rdmc.ui.printer("\tNo SmartNic present in given id %s \n" % id)

                        elif options.clearlog and options_system:
                            try:
                                for id in str_lst:
                                    if id == info["Id"]:
                                        self.clearlog(options, info, id)
                                    elif id != info["Id"]:
                                        self.rdmc.ui.printer("Given smartnic id is not present to clear the logs.")
                            except Exception as excp:
                                raise excp

                elif options.update_fw is not None:
                    try:
                        self.upload_firmware(options, info)
                    except Exception as excp:
                        # if SessionExpired:
                        # time.sleep(320)  # wait till reboot the server
                        # self.smartnicvalidation(options)
                        # self.cmdbase.login_select_validation(self, options)
                        # else:
                        raise excp

                elif options.reset is not None:
                    try:
                        for id in str_lst:
                            if id == info["Id"]:
                                self.get_resettype(options, info, id)
                            elif id != info["Id"]:
                                self.rdmc.ui.printer("No reset type present for given smartnic id %s \n" % id)

                    except Exception as excp:
                        raise excp

            else:
                if options.clearlog and options_system:
                    raise InvalidCommandLineError(
                        "No command --clearlog for smartnic\n" "usage: smartnic --id <id> --clearlog"
                    )

                if options_system and not options.clearlog:
                    if info["SystemType"] == "DPU":
                        self.prettyprintinfo(info, fw_version)
                    elif info["SystemType"] != "DPU":
                        self.rdmc.ui.printer("No SmartNic available.")

        self.cmdbase.logout_routine(self, options)
        # Return code
        return ReturnCodes.SUCCESS

    def get_fw_version(self):
        # to get pensando firmware version
        name = []
        f_version = ""
        fw_path = "/redfish/v1/UpdateService/FirmwareInventory/?$expand=."
        fw_result = self.rdmc.app.get_handler(fw_path, service=True, silent=True)
        fw_result = fw_result.dict
        members = fw_result["Members"]
        for n in members:
            name_version = n["Name"], n["Version"]
            name.append(name_version)

        for fw_name in name:
            if "Pensando" in fw_name[0]:
                f_version += fw_name[1]
        return f_version

    def clearlog(self, options, info, id):
        try:
            log_service = info["LogServices"]
            for log_id in log_service.values():
                data = self.rdmc.app.get_handler(log_id, service=True, silent=True).dict
                members = data["Members"]
                for val in members:
                    for dpu in val.values():
                        dpu_data = self.rdmc.app.get_handler(dpu, service=True, silent=True).dict
                        path = dpu_data["Actions"]["#LogService.ClearLog"]["target"]
                        action = path.split("/")[-2]
                        action = {"Action": action}
                        self.rdmc.app.post_handler(path, action)

        except Exception as excp:
            raise excp

    def get_resettype(self, options, info, id):
        self.printreboothelp(options.reset)
        time.sleep(3)

        if id == info["Id"]:
            put_path = info["@odata.id"]

        for item in info["Actions"]:
            if "Reset" in item:
                if self.rdmc.app.typepath.defs.isgen10:
                    # action = item.split("#")[-1]
                    put_path = info["Actions"][item]["target"]
                    break

        if options.reset.lower() == "gracefulshutdown":
            body = {"ResetType": "GracefulShutdown"}
        elif options.reset.lower() == "forcerestart":
            body = {"ResetType": "ForceRestart"}
        elif options.reset.lower() == "nmi":
            body = {"ResetType": "Nmi"}
        elif options.reset.lower() == "gracefulrestart":
            body = {"ResetType": "GracefulRestart"}

        self.rdmc.app.post_handler(put_path, body)

        self.cmdbase.logout_routine(self, options)
        # Return code
        return ReturnCodes.SUCCESS

    def printreboothelp(self, flag):
        if flag.upper() == "FORCERESTART":
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

        elif flag.upper() == "GRACEFULSHUTDOWN":
            self.rdmc.ui.warn(
                "\nThe server will be graceful shutdown. Note, the current session will be "
                "terminated.\nPlease wait for the server to boot completely before logging in "
                "again.\nRebooting the server in 3 seconds...\n"
            )

        elif flag.upper() == "GRACEFULRESTART":
            self.rdmc.ui.warn(
                "\nGraceful server restart. Note, the current session will be "
                "terminated.\nPlease wait for the server to boot completely before logging in "
                "again.\nRebooting the server in 3 seconds...\n"
            )

    def upload_firmware(self, options, info):
        try:
            string_id = options.id
            to_list = list(string_id.split(","))
            for id in to_list:
                for info_id in info["Id"]:
                    if id == info_id:
                        target = info["@odata.id"]
                        fw_path = options.update_fw
                        results = self.rdmc.app.select(selector="UpdateService.", path_refresh=True)[0].dict
                        results = results["Actions"]["#UpdateService.SimpleUpdate"]["target"]
                        string_split = fw_path.split("/")
                        for tar in string_split:
                            if tar.endswith("tar"):
                                self.rdmc.ui.printer("Uploading firmware: %s\n" % os.path.basename(tar))

                        res = self.rdmc.app.post_handler(results, {"ImageURI": fw_path, "Targets": [target]})

                        # Taskmonitor to find the firmware status
                        task_id = res.dict["TaskMonitor"]

                        if res.status == 202:
                            status = self.wait_for_state_change(task_id, options)
                            if status:
                                self.rdmc.ui.printer(
                                    "Component " + tar + " uploaded successfully.\n"
                                    "A reboot may be required for firmware changes to take effect.\n"
                                )

                            if not status:
                                # Failed to upload the component.
                                raise UploadError("Error while processing the component.")

                        elif (res.status == 404) or (res.status == 402):
                            return ReturnCodes.FAILED_TO_UPLOAD_COMPONENT

        except (FirmwareUpdateError, UploadError) as excp:
            raise excp

    def wait_for_state_change(self, taskid, options, wait_time=4800):
        """Wait for the iLO UpdateService to a move to terminal state.
        :param options: command line options
        :type options: list.
        :param wait_time: time to wait on upload
        :type wait_time: int.
        """
        total_time = 0
        spinner = ["|", "/", "-", "\\"]
        state = ""
        self.rdmc.ui.printer("Waiting for iLO UpdateService to finish flashing the firmware \n")

        while total_time < wait_time:
            state, _ = self.get_update_service_state(taskid)
            if state == "ERROR":
                return False
            elif (
                (state == "Running")
                or (state == "New")
                or (state == "Starting")
                or (state == "Interrupted")
                or (state == "Suspended")
            ):
                # Lets try again after 8 seconds
                count = 0
                # fancy spinner
                while count <= 32:
                    self.rdmc.ui.printer("Updating: %s\r" % spinner[count % 4])
                    time.sleep(0.25)
                    count += 1
                total_time += 8
            elif state == "Completed":
                break

        if total_time >= wait_time:
            raise FirmwareUpdateError("UpdateService in " + state + " state for " + str(wait_time) + "s")

        return True

    def get_update_service_state(self, taskid):
        results = self.rdmc.app.get_handler(taskid, service=True, silent=True)
        if results.status == 202:
            return results.dict["TaskState"], results.dict

        if results and results.status == 200 and results.dict:
            output = results.dict
            err = output["error"]["@Message.ExtendedInfo"]
            for e in err:
                msgsrg = e["MessageArgs"]
            return msgsrg[0], results.dict
        else:
            return "UNKNOWN", {}

    def print_get_bootprogress(self, info):
        try:
            if info is not None:
                for id in info["Id"]:
                    content = {"Id": id}
                    content.update({"LastState": info["BootProgress"]["LastState"]})
                    content.update({"OemLastState": info["BootProgress"]["OemLastState"]})
                content_json = {"Boot Progress": content}
                return content_json
        except Exception as excp:
            raise excp

    def get_bootprogress(self, info):
        boot_output = ""
        boot_output = "------------------------------------------------\n"
        boot_output += "Boot Progress \n"
        boot_output += "------------------------------------------------\n"
        if info is not None:
            for id in info["Id"]:
                boot_output += "Id: %s\n" % id
                boot_output += "LastState: %s\n" % info["BootProgress"]["LastState"]
                boot_output += "OemLastState: %s\n" % info["BootProgress"]["OemLastState"]
            self.rdmc.ui.printer(boot_output, verbose_override=True)

    def print_get_logs(self, info):
        log_service = info["LogServices"]
        for log_id in log_service.values():
            data = self.rdmc.app.get_handler(log_id, service=True, silent=True).dict
            members = data["Members"]
            for val in members:
                for dpu in val.values():
                    dpu_data = self.rdmc.app.get_handler(dpu, service=True, silent=True).dict
                    entry = dpu_data["Entries"]
                    for dpu_entry in entry.values():
                        result = self.rdmc.app.get_handler(dpu_entry, service=True, silent=True).dict
                        result = result["Members"]
                        if not result:
                            content = {}
                        else:
                            for member in result:
                                get_res = member["@odata.id"]
                                get_result = self.rdmc.app.get_handler(get_res, service=True, silent=True).dict
                                content = {"Id": get_result["Id"]}
                                content.update({"Name": get_result["Name"]})
                                content.update({"Created": get_result["Created"]})
                                content.update({"EntryType": get_result["EntryType"]})
                                content.update({"Severity": get_result["Severity"]})
                                message = get_result["Message"]
                                message = message.split(":")
                                content.update({message[0]: message[1]})
        content_json = {"Logs View": content}
        return content_json

    def get_logs(self, info):
        log_output = ""
        log_service = info["LogServices"]
        for log_id in log_service.values():
            data = self.rdmc.app.get_handler(log_id, service=True, silent=True).dict
            members = data["Members"]
            log_output = "------------------------------------------------\n"
            log_output += "Logs View \n"
            log_output += "------------------------------------------------\n"
            for val in members:
                for dpu in val.values():
                    dpu_data = self.rdmc.app.get_handler(dpu, service=True, silent=True).dict
                    entry = dpu_data["Entries"]
                    for dpu_entry in entry.values():
                        result = self.rdmc.app.get_handler(dpu_entry, service=True, silent=True).dict
                        result = result["Members"]
                        for member in result:
                            get_res = member["@odata.id"]
                            get_result = self.rdmc.app.get_handler(get_res, service=True, silent=True).dict
                            log_output += "Id: %s\n" % get_result["Id"]
                            log_output += "Name: %s\n" % get_result["Name"]
                            log_output += "Created: %s\n" % get_result["Created"]
                            log_output += "EntryType: %s\n" % get_result["EntryType"]
                            log_output += "Severity: %s\n" % get_result["Severity"]
                            log_output += "%s\n" % get_result["Message"]
            self.rdmc.ui.printer(log_output, verbose_override=True)

    def prettyprintinfo(self, info, fw_version):
        output = ""
        output = "------------------------------------------------\n"
        output += "SmartNic Information\n"
        output += "------------------------------------------------\n"

        if info is not None:
            for id in info["Id"]:
                output += "System %s:\n" % id
                output += "\tModel: %s\n" % info["Model"]
                output += "\tManufacturer: %s\n" % info["Manufacturer"]
                output += "\tName: %s\n" % info["Name"]
                output += "\tFirmware Version: %s\n" % fw_version
                output += "\tPowerState: %s\n" % info["PowerState"]
                output += "\tSerialNumber: %s\n" % info["SerialNumber"]
                output += "\tSystemType: %s\n" % info["SystemType"]
                try:
                    output += "\tHealth: %s\n" % info["Status"]["Health"]
                except KeyError:
                    pass
                try:
                    output += "\tState: %s\n" % info["Status"]["State"]
                except KeyError:
                    pass
                try:
                    output += (
                        "\tOperating System: %s \n"
                        % info["Oem"][self.rdmc.app.typepath.defs.oemhp]["OperatingSystem"]["Kernel"]["Name"]
                    )
                except KeyError:
                    pass
                try:
                    output += (
                        "\tOS Version: %s \n"
                        % info["Oem"][self.rdmc.app.typepath.defs.oemhp]["OperatingSystem"]["Kernel"]["Version"]
                    )
                except KeyError:
                    pass
                try:
                    avail_sys = info["Oem"][self.rdmc.app.typepath.defs.oemhp]["AvailableSystemCapabilities"]
                    avail_sys = str(avail_sys).strip("[]''")
                    output += "\tAvailable SystemCapabilities: %s \n" % avail_sys
                except KeyError:
                    pass
                try:
                    enable_sys = info["Oem"][self.rdmc.app.typepath.defs.oemhp]["EnabledSystemCapabilities"]
                    enable_sys = str(enable_sys).strip("[]''")
                    output += "\tEnable SystemCapabilities: %s \n" % enable_sys
                except KeyError:
                    pass
                try:
                    integration_con = info["Oem"][self.rdmc.app.typepath.defs.oemhp]["IntegrationConfig"]
                    integration_con = str(integration_con).strip("'{} ")
                    integration_con = integration_con.replace("'", "")
                    output += "\tIntegration Config: %s \n" % integration_con
                except KeyError:
                    pass

                output += "\tUUID: %s\n" % info["UUID"]

        self.rdmc.ui.printer(output, verbose_override=True)

    def build_json_out(self, info, fw_version):
        if info is not None:
            for id in info["Id"]:
                content = {"model": info["Model"]}
                content.update({"Manufacturer": info["Manufacturer"]})
                content.update({"Name": info["Name"]})
                content.update({"Firmware Version": fw_version})
                content.update({"PowerState": info["PowerState"]})
                content.update({"SerialNumber": info["SerialNumber"]})
                content.update({"SystemType": info["SystemType"]})
                try:
                    content.update({"Health": info["Status"]["Health"]})
                except KeyError:
                    pass
                try:
                    content.update({"State": info["Status"]["State"]})
                except KeyError:
                    pass
                try:
                    content.update(
                        {
                            "Operating System": info["Oem"][self.rdmc.app.typepath.defs.oemhp]["OperatingSystem"][
                                "Kernel"
                            ]["Name"]
                        }
                    )
                except KeyError:
                    pass
                try:
                    content.update(
                        {
                            "OS Version": info["Oem"][self.rdmc.app.typepath.defs.oemhp]["OperatingSystem"]["Kernel"][
                                "Version"
                            ]
                        }
                    )
                except KeyError:
                    pass
                try:
                    content.update(
                        {
                            "Available SystemCapabilities": info["Oem"][self.rdmc.app.typepath.defs.oemhp][
                                "AvailableSystemCapabilities"
                            ]
                        }
                    )
                except KeyError:
                    pass
                try:
                    content.update(
                        {
                            "Enable SystemCapabilities": info["Oem"][self.rdmc.app.typepath.defs.oemhp][
                                "EnabledSystemCapabilities"
                            ]
                        }
                    )
                except KeyError:
                    pass
                try:
                    content.update(
                        {"Integration Config": info["Oem"][self.rdmc.app.typepath.defs.oemhp]["IntegrationConfig"]}
                    )
                except KeyError:
                    pass
                content.update({"UUID": info["UUID"]})
            system = {"System %s" % id: content}
        content_json = {"SmartNic Information": system}
        return content_json

    def gatherinfo(self, path):
        try:
            # info = {}
            results = ""
            csysresults = self.rdmc.app.select(selector="ComputerSystemCollection.")
            csysresults = csysresults[0].dict
            members = csysresults["Members"]
            for id in members:
                for mem_id in id.values():
                    if path != mem_id:
                        results = self.rdmc.app.get_handler(mem_id, service=True, silent=True).dict
            return results
        except:
            pass

    def smartnicvalidation(self, options):
        """smartnic validation function.

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
            "--id",
            dest="id",
            help="Optionally include this flag to retrive the selected smartnic .",
            default=None,
        )

        customparser.add_argument(
            "--logs",
            dest="logs",
            action="store_true",
            help="Optionally include this flag to list all the logs .",
            default=False,
        )

        customparser.add_argument(
            "--bootprogress",
            dest="bootprogress",
            action="store_true",
            help="Optionally include this flag to list the bootprogress information",
            default=False,
        )

        customparser.add_argument(
            "--update_fw",
            dest="update_fw",
            help="Include this flag to update firmware to pensando card",
            default=None,
        )
        # customparser.add_argument(
        #    "--update_os",
        #    dest="update_os",
        #    help="Include this flag to update OS to pensando card",
        #    default=None,
        # )

        customparser.add_argument(
            "--reset",
            dest="reset",
            help="Add this flag to reset the server",
            nargs="?",
            type=str,
            const="GracefulRestart",
        )

        customparser.add_argument(
            "--clearlog",
            dest="clearlog",
            action="store_true",
            help="Optionally include this flag to clear log",
            default=False,
        )
