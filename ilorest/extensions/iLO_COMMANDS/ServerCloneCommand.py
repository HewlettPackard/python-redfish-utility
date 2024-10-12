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
""" Server Clone Command for rdmc """

import getpass
import json
import os
import os.path
import re
import sys
import time
import traceback
from argparse import RawDescriptionHelpFormatter
from collections import OrderedDict

import jsonpath_rw
from six.moves import input

import redfish.ris
from redfish.ris.rmc_helper import IdTokenError, IloResponseError, InstanceNotFoundError
from redfish.ris.utils import iterateandclear, json_traversal_delete_empty
from redfish.ris import SessionExpired

try:
    from rdmc_helper import (
        LOGGER,
        Encryption,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        InvalidFileInputError,
        InvalidKeyError,
        NoChangesFoundOrMadeError,
        NoContentsFoundForOperationError,
        NoDifferencesFoundError,
        ResourceExists,
        ReturnCodes,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        LOGGER,
        Encryption,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        InvalidFileInputError,
        InvalidKeyError,
        NoChangesFoundOrMadeError,
        NoContentsFoundForOperationError,
        NoDifferencesFoundError,
        ResourceExists,
        ReturnCodes,
    )

# default file name
__DEFAULT__ = "<p/k>"
__MINENCRYPTIONLEN__ = 16
__clone_file__ = "ilorest_clone.json"
__tmp_clone_file__ = "_ilorest_clone_tmp"
__tmp_sel_file__ = "_ilorest_sel_tmp"
__error_log_file__ = "clone_error_logfile.log"
__changelog_file__ = "changelog.log"
__tempfoldername__ = "serverclone_data"


def log_decor(func):
    """
    Log Decorator function
    :param func: function to be decorated
    :type func: class method
    """

    def func_wrap(*args, **kwargs):
        """
        Log Decorator function wrapper
        :param args: function to be decorated
        :type args: *
        :param kwargs: keyword arguments
        :type kwargs: *
        """
        try:
            return func(*args, **kwargs)
        except IdTokenError as excp:
            sys.stderr.write(
                "You have logged into iLO with an account which has insufficient "
                " user access privileges to modify properties in this type:\n %s\n" % (excp)
            )
            if args[0].rdmc.opts.debug:
                logging(
                    func.func_name if hasattr(func, "func_name") else str(func),
                    traceback.format_exc(),
                    excp,
                    args,
                )
        except NoDifferencesFoundError as excp:
            sys.stderr.write("No differences identified from current configuration.\n")
            if args[0].rdmc.opts.debug:
                logging(
                    func.func_name if hasattr(func, "func_name") else str(func),
                    traceback.format_exc(),
                    excp,
                    args,
                )
        except ExitHandler:
            sys.stderr.write("Exiting Serverclone command...no further changes have been implemented.\n")
            raise NoChangesFoundOrMadeError("Exiting Serverclone command...no further changes have been implemented.\n")

        except Exception as excp:
            sys.stderr.write("Unhandled exception(s) occurred: %s\n" % str(excp))
            if not args[0].rdmc.opts.debug:
                args[0].rdmc.ui.error(
                    "Check the ServerClone Error logfile for further info: %s\n" % __error_log_file__,
                    excp,
                )
                logging(
                    func.func_name if hasattr(func, "func_name") else str(func),
                    traceback.format_exc(),
                    excp,
                    args,
                )

    return func_wrap


def logging(command, _trace, error, _args):
    """
    Handler for error logging
    :param command: command in error
    :type command: method identifier
    :param _trace: traceback data
    :type _trace: object
    :param error: error logged (simplified version)
    :type error: string
    :param _agrs: array of methods arguments
    :type _args: array
    """

    sys.stderr.write(
        "An error occurred: %s. Check the ServerClone Error logfile "
        "for further info: %s\n" % (error, __error_log_file__)
    )
    sys.stderr.write("Logging error to '%s'.\n" % __error_log_file__)
    with open(__error_log_file__, "a+") as efh:
        efh.write(command + ":\n")
        efh.write("Simplified Error: " + str(error) + "\n")
        efh.write("Traceback:\n")
        efh.write(str(_trace) + "\n")
        efh.write("Args State in: '%s'.\n" % command)
        i = 0
        for _arg in _args:
            efh.write("Arg %s: %s\n" % (str(i), _arg))
            i += 1
        efh.write("\n")


class ExitHandler(Exception):
    pass


class ServerCloneCommand:
    """Constructor"""

    def __init__(self):
        self.ident = {
            "name": "serverclone",
            "usage": None,
            "description": "Clone from a server or restore to a server a JSON formatted file "
            "containing the configuration settings of a system's iLO and Bios configuration.\n"
            "SSA controller settings and logical configurations can be optionally be included for "
            "save.\nTo view help on specific sub-commands run: serverclone <sub-command> -h\n\n"
            "Example: serverclone <sub-command> <option>\n"
            "Example: serverclone save --auto --all\n"
            "Example: serverclone load --auto --all\n"
            "Example: serverclone save --all --auto -f clone.json -sf storage_clone.json \n"
            "Example: serverclone load --all --auto -f clone.json -sf storage_clone.json --noautorestart\n"
            "Example: serverclone save/load --ilossa \n"
            "Example: serverclone save/load --uniqueoverride \n\n"
            "NOTE 1: Use the '--auto' option to ignore "
            "all user input. Intended for scripting purposes.\n"
            "NOTE 2: During clone load, login using an ilo account with full privileges"
            " (such as the Administrator account) to ensure all items are cloned "
            "successfully.\n"
            "NOTE 3: It is suggested to only include types and properties targetted for "
            "modification when loading. If entire sections of properties (or all sub dictionaries)\n\t"
            "of a particular types) are to be removed; then the type, path and all associated "
            "properties within the section should be removed \n\tin a manner preserving the JSON "
            "formatting.Individual properties or entire sections may be removed.\n"
            "NOTE 4: Any iLO management account or iLO federation account not present in the "
            "serverclone file will be deleted if present on the server during load.",
            "summary": "Creates a JSON formatted clone file of a system's iLO, Bios, and SSA "
            "configuration which can be duplicated onto other systems. "
            "User editable JSON file can be manipulated to modify settings before being "
            "loaded onto another machine.",
            "aliases": [],
            "auxcommands": [
                "LoginCommand",
                "LogoutCommand",
                "LoadCommand",
                "EthernetCommand",
                "CreateVolumeCommand",
                "IloAccountsCommand",
                "IloFederationCommand",
                "IloLicenseCommand",
                "CertificateCommand",
                "SingleSignOnCommand",
                "IloResetCommand",
                "RebootCommand",
                "StorageControllerCommand",
                "SelectCommand",
                "FactoryResetControllerCommand",
            ],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()
        self.storage_file = None
        self.clone_file = None  # set in validation
        self._cache_dir = None  # set in validation
        self.tmp_clone_file = __tmp_clone_file__
        self.tmp_sel_file = __tmp_sel_file__
        self.change_log_file = __changelog_file__
        self.error_log_file = __error_log_file__
        self.https_cert_file = None
        self.sso_cert_file = None
        self.save = None
        self.load = None
        self._fdata = None
        self.curr_iloversion = None
        self.curr_ilorev = None

    def cleanup(self):
        self.save = None
        self.load = None
        self._fdata = None

    def run(self, line, help_disp=False):
        """Main Serverclone Command function
        :param line: string of arguments passed in
        :type line: str.
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

        if "save" in options.command.lower():
            self.save = True
            self.load = False
        elif "load" in options.command.lower():
            self.save = False
            self.load = True
        else:
            raise InvalidCommandLineError("Save or load was not selected.")

        self.serverclonevalidation(options)

        self.curr_iloversion, self.curr_ilorev = str(self.rdmc.app.getiloversion()).split(".")
        self.check_files(options)

        if self.save:
            self.gatherandsavefunction(self.getilotypes(options), options)
        elif self.load:
            self._fdata = self.file_handler(self.clone_file, operation="r+", options=options)
            data = self._fdata["#ManagerAccount.v1_3_0.ManagerAccount"]
            if "#HpeiLOFederationGroup.v2_0_0.HpeiLOFederationGroup" in self._fdata:
                fed_data = self._fdata["#HpeiLOFederationGroup.v2_0_0.HpeiLOFederationGroup"]
            else:
                fed_data = dict()
            user_counter = 0
            fed_counter = 0
            if options.all:
                for useracct in data.items():
                    user = useracct[1]
                    if not user["Password"] == "<p/k>":
                        user_counter = user_counter + 1
                    else:
                        self.c_log_write(
                            "Kindly modify the password from <p/k> to valid pass in the clone file for the user :"
                            + user["UserName"]
                            + "\n"
                        )
                if fed_data:
                    for fedkey in fed_data.items():
                        fedacct = fedkey[1]
                        if not fedacct["FederationKey"] == "<p/k>":
                            fed_counter = fed_counter + 1
                        else:
                            self.c_log_write(
                                "Kindly modify the password from <p/k> to valid pass in the clone file for the user :"
                                + fedacct["FederationName"]
                                + "\n"
                            )
                else:
                    self.rdmc.ui.printer("No federation accounts available\n")
                if user_counter == len(data.items()) or fed_counter == len(fed_data.items()):
                    self.loadfunction(options)
                    self.load_storageclone(options)
                else:
                    self.rdmc.ui.error(
                        "Please modify the default password <p/k> to a valid password "
                        "in the clone json file and rerun the load command"
                    )

            elif not options.iLOSSA:
                for useracct in data.items():
                    user = useracct[1]
                    if not user["Password"] == "<p/k>":
                        user_counter = user_counter + 1
                    else:
                        self.c_log_write(
                            "Kindly modify the password from <p/k> to valid pass in the clone file for the user :"
                            + user["UserName"]
                            + "\n"
                        )
                if fed_data:
                    for fedkey in fed_data.items():
                        fedacct = fedkey[1]
                        if not fedacct["FederationKey"] == "<p/k>":
                            fed_counter = fed_counter + 1
                        else:
                            self.c_log_write(
                                "Kindly modify the password from <p/k> to valid pass in the clone file for the user :"
                                + fedacct["FederationName"]
                                + "\n"
                            )
                else:
                    self.rdmc.ui.printer("No federation accounts available\n")
                if user_counter == len(data.items()) or fed_counter == len(fed_data.items()):
                    self.loadfunction(options)
                else:
                    self.rdmc.ui.error(
                        "Please modify the default password <p/k> to a valid password "
                        "in the clone json file and rerun the load command"
                    )
            else:
                self.load_storageclone(options)

        self.cleanup()
        # self.cmdbase.logout_routine(self, options)
        # Return code
        return ReturnCodes.SUCCESS

    @log_decor
    def file_handler(self, filename, operation, options, data=None, sk=None):
        """
        Wrapper function to read or write data to a respective file
        :param data: data to be written to output file
        :type data: container (list of dictionaries, dictionary, etc.)
        :param file: filename to be written
        :type file: string (generally this should be self.clone_file or tmp_clone_file
        :param operation: file operation to be performed
        :type operation: string ('w+', 'a+', 'r+')
        :param sk: sort keys flag
        :type sk: boolean
        :param options: command line options
        :type options: attribute
        :returns: json file data
        """
        writeable_ops = ["w", "w+", "a", "a+"]

        fdata = None

        try:
            if operation in writeable_ops:
                if options.encryption:
                    with open(filename, operation + "b") as outfile:
                        outfile.write(
                            Encryption().encrypt_file(
                                json.dumps(
                                    data,
                                    indent=2,
                                    cls=redfish.ris.JSONEncoder,
                                    sort_keys=sk,
                                ),
                                options.encryption,
                            )
                        )
                else:
                    with open(filename, operation) as outfile:
                        outfile.write(
                            json.dumps(
                                data,
                                indent=2,
                                cls=redfish.ris.JSONEncoder,
                                sort_keys=sk,
                            )
                        )
            else:
                if options.encryption:
                    with open(filename, operation + "b") as file_handle:
                        fdata = json.loads(Encryption().decrypt_file(file_handle.read(), options.encryption))
                else:
                    with open(filename, operation) as file_handle:
                        fdata = json.loads(file_handle.read())
        except Exception as excp:
            self.cleanup()
            raise InvalidFileInputError(
                "Unable to open file: %s.\nVerify the file location " "and the file has a valid JSON format.\n" % excp
            )
        else:
            return fdata

    @log_decor
    def controller_id(self, options):
        """
        Get iLO types from server and save storageclone URL get Controller
        :parm options: command line options
        :type options: attribute
        :returns: returns list
        """
        self.auxcommands["select"].selectfunction("StorageControllerCollection.")
        ctr_content = self.rdmc.app.getprops()
        ctrl_data = []
        all_ctrl = dict()

        for ct_controller in ctr_content:
            path = ct_controller["Members"]
            for i in path:
                res = i["@odata.id"]
                if self.rdmc.opts.verbose and not self.load:
                    sys.stdout.write("Saving properties of type %s \t\n" % res)
                ctrl_data.append(res)
                ctrl_id_url = res + "?$expand=."
                get_ctr = self.rdmc.app.get_handler(ctrl_id_url, silent=True, service=True).dict
                ctrl_id = get_ctr["@odata.id"].split("/")
                ctrl_id = ctrl_id[8]
                get_ctr = self.rdmc.app.removereadonlyprops(get_ctr, False, True)
                all_ctrl[get_ctr["Name"]] = get_ctr
        return all_ctrl

    @log_decor
    def get_volume(self, options):
        """
        Get iLO types from server and save storageclone URL get volumes
        :parm options: command line options
        :type options: attribute
        :returns: returns list
        """
        self.auxcommands["select"].selectfunction("VolumeCollection.")
        vol_content = self.rdmc.app.getprops()
        vol_data = []
        all_vol = dict()
        for st_volume in vol_content:
            path = st_volume["Members"]
            for i in path:
                res = i["@odata.id"]
                if self.rdmc.opts.verbose:
                    sys.stdout.write("Saving properties of type %s \t\n" % res)
                vol_data.append(res)
                vol_id_url = res + "?$expand=."
                get_vol = self.rdmc.app.get_handler(vol_id_url, silent=True, service=True).dict
                # print("Assigned drive", get_vol["Links"]["Drives"])
                get_vol = self.rdmc.app.removereadonlyprops(get_vol, False, True)
                all_vol[get_vol["Name"]] = get_vol
        return all_vol

    @log_decor
    def save_storageclone(self, options):
        """
        Get iLO types from server and save storageclone URL
        :parm options: command line options
        :type options: attribute
        :returns: returns dict and save json format
        """

        self.auxcommands["select"].selectfunction("StorageCollection.")
        st_content = self.rdmc.app.getprops()
        st_flag = False
        all_stgcntrl = {}
        de_url = []
        if options.storageclonefilename:
            outfilename = options.storageclonefilename[0]
        else:
            outfilename = "ilorest_storage_clone.json"
        out_file = open(outfilename, "w")
        self.rdmc.ui.printer("Saving of storage clone file to '%s'...... \n" % out_file.name)
        for st_controller in st_content:
            path = st_controller["Members"]
            for i in path:
                res = i["@odata.id"]
                if "DE" in res:
                    de_url.append(res)
                    if self.rdmc.opts.verbose:
                        sys.stdout.write("Saving properties of type %s \t\n" % res)
                    st_flag = True
                    storage_id_url = res + "?$expand=."
                    get_storage = self.rdmc.app.get_handler(storage_id_url, silent=True, service=True).dict
                    vol = self.get_volume(options)
                    ctr = self.controller_id(options)
                    get_storage = self.rdmc.app.removereadonlyprops(get_storage, False, True)
                    # print("controller id", ctr["SATA Storage Controller"]["Id"])
                    # Controller and volume update abve method called
                    get_storage["Controllers"]["Members"].append(ctr)
                    del get_storage["Controllers"]["Members"][0]
                    get_storage["Volumes"]["Members"].append(vol)
                    del get_storage["Volumes"]["Members"][0]
                    all_stgcntrl[get_storage["Id"]] = get_storage
                else:
                    continue
        if st_flag:
            json.dump(all_stgcntrl, out_file, indent=6)
            out_file.close()
            self.rdmc.ui.printer("Saving of storage clone file to '%s' is complete.\n" % out_file.name)
        else:
            sys.stdout.write("\nNo Storage controllers found which is redfish enabled \n")

    @log_decor
    def get_drives_capacityt(self, options):
        self.auxcommands["select"].selectfunction("Drive.")
        drive_content = self.rdmc.app.getprops()
        drive_list = []
        loc_list = []
        for st_drive in drive_content:
            drive_cap = st_drive["CapacityBytes"]
            drive_list.append(drive_cap)
            drive_loc = st_drive["PhysicalLocation"]["PartLocation"]["ServiceLabel"]
            loc = drive_loc.split(":")
            drv_loc = str(loc[1].split("=")[1] + ":" + loc[2].split("=")[1] + ":" + loc[3].split("=")[1])
            loc_list.append(drv_loc)
        return drive_list, loc_list

    @log_decor
    def controller_get_id(self, options):
        self.auxcommands["select"].selectfunction("StorageController.")
        ctr_content = self.rdmc.app.getprops()
        for ct_data in ctr_content:
            ct_id = ct_data["Id"]
        return ct_id

    @log_decor
    def get_storage_de_id(self, options):
        self.auxcommands["select"].selectfunction("StorageCollection.")
        st_content = self.rdmc.app.getprops()
        try:
            for st_controller in st_content:
                path = st_controller["Members"]
                for i in path:
                    res = i["@odata.id"].split("/")
                    res = res[6]
                    if "DE" in res:
                        res
                    return res
        except:
            self.rdmc.ui.printer("Storage id not available")

    @log_decor
    def load_storageclone(self, options):
        """
        Load iLO Server storage URL.
        :parm ilovoldata: iLO Server Volume(logical drive) payload to be loaded
        :type ilovoldata: dict of values
        """
        if options.storageclonefilename:
            filename = options.storageclonefilename[0]
        else:
            filename = "ilorest_storage_clone.json"
        while True:
            ans = input(
                "A configuration file %s containing configuration changes will be "
                "applied to this iLO server resulting in system setting changes for "
                "Storage urls like controllers, volume, deletion and "
                "rearrangement of logical disks...etc. Please confirm you acknowledge "
                "and would like to perform this operation now? (y/n)\n" % filename
            )
            if ans.lower() == "y":
                self.rdmc.ui.printer("Proceeding with Storage Clone Load Operation...\n")
                break
            elif ans.lower() == "n":
                self.rdmc.ui.warn("Aborting load operation. No changes made to the server.\n")
                return ReturnCodes.NO_CHANGES_MADE_OR_FOUND
            else:
                self.rdmc.ui.warn("Invalid input...\n")

        ctr_id = self.controller_get_id(options)
        print("Controller id", ctr_id)
        st_id_de = self.get_storage_de_id(options)
        print("Storage ID only DE", st_id_de)
        with open(filename, "r+b") as file_handle:
            if options.encryption:
                data = json.load(Encryption().decrypt_file(file_handle.read(), options.encryption))
            else:
                data = json.load(file_handle)
            for k, v in data.items():
                while True:
                    ans = input("Do you want to delete current %s controller? (y/n)\n" % k)
                    if ans.lower() == "y":
                        self.rdmc.ui.printer("Proceeding with Deletion DE storage...\n")
                        break
                    elif ans.lower() == "n":
                        self.rdmc.ui.warn("Aborting load operation. No changes made to the server.\n")
                        return ReturnCodes.NO_CHANGES_MADE_OR_FOUND
                    else:
                        self.rdmc.ui.warn("Invalid input...\n")
                self.auxcommands["factoryresetcontroller"].run("--reset_type resetall --storageid " + k)
                if self.rdmc.opts.verbose:
                    self.rdmc.ui.printer("Deleted Volume using factoryresetcontroller %s command.\n" % k)
                v_data = v["Volumes"]["Members"][0]
                for i, j in v_data.items():
                    # print("Key", i)
                    writecachepolicy = j["WriteCachePolicy"]
                    readcachepolicy = j["ReadCachePolicy"]
                    displayname = j["DisplayName"]
                    raidtype = j["RAIDType"]
                    capacitybytes = j["CapacityBytes"]
                    dr, loc = self.get_drives_capacityt(options)
                    # print("------", dr, loc)
                    i = 0
                    for d in dr:
                        print("drives list", d)
                        if int(d) > int(capacitybytes):
                            create_val = (
                                raidtype
                                + " "
                                + str(loc[i])
                                + " "
                                + "DisplayName "
                                + displayname
                                + " --iOPerfModeEnabled False"
                                + " --ReadCachePolicy "
                                + readcachepolicy
                                + " --WriteCachePolicy "
                                + writecachepolicy
                                + " --controller="
                                + ctr_id
                                + " --capacitybytes "
                                + str(capacitybytes)
                            )
                            print("createvolume properties", create_val)
                            self.auxcommands["createvolume"].run("volume " + create_val)
                            break
                        elif int(d) < int(capacitybytes):
                            print("Implementation logic", d)
                            break
                        else:
                            sys.stdout.write("Drive capacity is lesser than present drives")
                        i = i + 1

    @log_decor
    def getilotypes(self, options):
        """
        Get iLO types from server and return a list of types
        :parm options: command line options
        :type options: attribute
        :returns: returns list of types
        """
        supported_types_dict = {
            "ManagerAccount": ["4", "5", "6", "7"],
            "AccountService": ["4", "5", "6", "7"],
            "Bios": ["4", "5", "6", "7"],
            "Manager": ["4", "5", "6", "7"],
            "SNMP": ["4", "5", "6", "7"],
            "iLOLicense": ["4", "5", "6", "7"],
            "ManagerNetworkService": ["4", "5", "6", "7"],
            "EthernetNetworkInterface": ["4", "5", "6", "7"],
            "iLODateTime": ["4", "5", "6", "7"],
            "iLOFederationGroup": ["4", "5", "6", "7"],
            "iLOSSO": ["4", "5", "6", "7"],
            "ESKM": ["4", "5", "6", "7"],
            "ComputerSystem": ["4", "5", "6", "7"],
            # "EthernetInterface": ["4", "5", "6"],
            "ServerBootSettings": ["4", "5", "6", "7"],
            "SecureBoot": ["4", "5", "6", "7"],
            "SmartStorageConfig": ["5"],
            "HpSmartStorage": ["4"],
            "HpeSmartStorage": ["5"],
        }
        types_accepted = set()
        if self.save:
            if options.noBIOS:
                self.rdmc.ui.warn("Bios configuration will be excluded.\n")
                del supported_types_dict["Bios"]
            if options.all:
                self.rdmc.ui.printer("Note: Smart storage configuration and Storage included all.\n")
                self.save_storageclone(options)
            if not options.iLOSSA and not options.all:
                self.rdmc.ui.printer("Note: Smart storage configuration will not be included.\n")
                self.rdmc.ui.warn("Smart storage configuration will not be included.")
                del supported_types_dict["SmartStorageConfig"]
                del supported_types_dict["HpSmartStorage"]
                del supported_types_dict["HpeSmartStorage"]
        unsupported_types_list = [
            "Collection",
            "PowerMeter",
            "BiosMapping",
            "Controller",
        ]

        # supported types comparison
        # types_accepted = set()
        for _type in sorted(set(self.rdmc.app.types("--fulltypes"))):
            if _type[:1].split(".")[0] == "#":
                _type_mod = _type[1:].split(".")[0]
            else:
                _type_mod = _type.split(".")[0]
            for stype in supported_types_dict:
                if stype.lower() in _type_mod.lower():
                    found = False
                    for ustype in unsupported_types_list:
                        if ustype.lower() in _type_mod.lower():
                            found = True
                            break
                    if not found:
                        if self.curr_iloversion in supported_types_dict[stype]:
                            types_accepted.add(_type)

        return sorted(types_accepted)

    def loadfunction(self, options):
        """
        Main load function. Handles SSO and SSL/TLS Certificates, kickoff load
        helper, load of patch file, get server status and issues system reboot
        and iLO reset after completion of all post and patch commands.
        :param options: command line options
        :type options: attribute
        """

        reset_confirm = True

        if not options.autocopy:
            while True:
                ans = input(
                    "A configuration file '%s' containing configuration changes will be "
                    "applied to this iLO server resulting in system setting changes for "
                    "BIOS, ethernet controllers, disk controllers, deletion and "
                    "rearrangement of logical disks...etc. Please confirm you acknowledge "
                    "and would like to perform this operation now? (y/n)\n" % self.clone_file
                )
                if ans.lower() == "y":
                    self.rdmc.ui.printer("Proceeding with ServerClone Load Operation...\n")
                    break
                elif ans.lower() == "n":
                    self.rdmc.ui.warn("Aborting load operation. No changes made to the server.\n")
                    return ReturnCodes.NO_CHANGES_MADE_OR_FOUND
                else:
                    self.rdmc.ui.warn("Invalid input...\n")

        self._fdata = self.file_handler(self.clone_file, operation="r+", options=options)
        self.loadhelper(options)
        self.load_idleconnectiontime(options)
        data = self._fdata["#ManagerAccount.v1_3_0.ManagerAccount"]
        if "#HpeiLOFederationGroup.v2_0_0.HpeiLOFederationGroup" in self._fdata:
            fed_data = self._fdata["#HpeiLOFederationGroup.v2_0_0.HpeiLOFederationGroup"]
            for fedkey in fed_data.items():
                self.load_federation(
                    fedkey[1],
                    "#HpeiLOFederationGroup.v2_0_0.HpeiLOFederationGroup",
                    "/redfish/v1/Managers/1/FederationGroups",
                    options,
                )
        else:
            self.rdmc.ui.printer("No federation accounts to load\n")
            pass
        for useracct in data.items():
            self.load_accounts(
                useracct[1], "#ManagerAccount.v1_3_0.ManagerAccount", "/redfish/v1/AccountService/Accounts", options
            )

        self.loadpatch(options)
        self.getsystemstatus(options)

        if not options.autocopy:
            while True:
                ans = input("The system is ready to be reset. Perform a reset now? (y/n)\n")
                if ans.lower() == "n":
                    reset_confirm = False
                    self.rdmc.ui.printer("Aborting Server Reboot and iLO reset...\n")
                    break
                elif ans.lower() == "y":
                    break
                else:
                    self.rdmc.ui.warn("Invalid input...\n")
        else:
            if options.noautorestart:
                reset_confirm = False

        if reset_confirm:
            if self.rdmc.app.current_client.base_url:  # reset process in remote mode
                self.rdmc.ui.printer("Resetting the server...\n")
                sys_url = "/redfish/v1/Systems/1/"
                sysresults = self.rdmc.app.get_handler(sys_url, service=True, silent=True).dict
                power_state = sysresults["PowerState"]
                if power_state == "On":
                    self.auxcommands["reboot"].run("ColdBoot")  # force restart, cold boot
                elif power_state == "Off":
                    self.rdmc.ui.printer("System is on power off state, powering ON\n")
                    self.auxcommands["reboot"].run("On")
                self.rdmc.ui.printer("Waiting 3 minutes for reboot to complete...\n")
                time.sleep(180)
                self.rdmc.ui.printer("Resetting iLO...\n")
                self.auxcommands["iloreset"].run("")
                self.rdmc.ui.printer("You will need to re-login to access this system...\n")
            else:  # reset process in local mode
                self.rdmc.ui.printer("Resetting local iLO...\n")
                self.auxcommands["iloreset"].run("")
                self.rdmc.ui.printer("Your system may require a reboot...use at your discretion\n")

        else:
            self.rdmc.ui.printer("Your system may require a reboot...use at your discretion\n")

        self.rdmc.ui.printer(
            "Loading of clonefile '%s' to server is complete. Review the "
            "changelog file '%s'.\n" % (self.clone_file, self.change_log_file)
        )

    def loadhelper(self, options):
        """
        Helper function for loading which calls additional helper functions for
        Server BIOS and Firmware compatibility, type compatibility, patch or
        postability (special functions). Data deemed for exclusive patching
        (through load) is written into a temporary file, which is deleted unless
        archived for later use.
        :param options: command line options
        :type options: attribute
        """
        data = list()

        server_avail_types = self.getilotypes(options)
        if not server_avail_types:
            raise NoContentsFoundForOperationError("Unable to Obtain iLO Types from server.")

        if "Comments" in list(self._fdata.keys()):
            self.system_compatibility_check(self._fdata["Comments"], options)
            del self._fdata["Comments"]
        else:
            raise InvalidFileInputError("Clone File '%s' does not include a valid 'Comments' " "dictionary.")
        if options.ssocert:
            self.load_ssocertificate()  # check and load sso certificates
        if options.tlscert:
            self.load_tlscertificate()  # check and load tls certificates

        typelist = []
        for _x in self._fdata:
            for _y in server_avail_types:
                _x1 = re.split("#|.", _x)
                _y1 = re.split("#|.", _y)
                if _x1[0] == "":
                    _x1.pop(0)
                if _y1[0] == "":
                    _y1.pop(0)
                if _x1[0] == _y1[0]:
                    _comp_tuple = self.type_compare(_x, _y)
                    if _comp_tuple[0] and _comp_tuple[1]:
                        self.rdmc.ui.printer("Type '%s' is compatible with this system.\n" % _x)
                        typelist.append(_x)
                    else:
                        self.rdmc.ui.warn(
                            "The type: '%s' isn't compatible with the type: '%s'"
                            "found on this system. Associated properties can not "
                            "be applied...Skipping\n" % (_x, _y)
                        )

        for _type in typelist:
            # Skipping cloning of Datetime temporarily. This is an iLO issue.
            if _type == "#HpeiLODateTime.v2_0_0.HpeiLODateTime":
                continue
            singlet = True
            thispath = next(iter(self._fdata[_type].keys()))
            try:
                root_path_comps = self.get_rootpath(thispath)

                multi_sel = self.rdmc.app.select(
                    _type.split(".")[0] + ".",
                    (self.rdmc.app.typepath.defs.hrefstring, root_path_comps[0] + "*"),
                    path_refresh=True,
                )

                curr_sel = self.rdmc.app.select(
                    _type.split(".")[0] + ".",
                    (self.rdmc.app.typepath.defs.hrefstring, thispath),
                    path_refresh=True,
                )

            except InstanceNotFoundError:
                if "iLOFederationGroup" in _type:
                    pass
                else:
                    curr_sel = self.rdmc.app.select(_type.split(".")[0] + ".")

            except Exception as excp:
                self.rdmc.ui.error(
                    "Unable to find the correct path based on system " "type and clone file type: %s\n" % _type,
                    excp,
                )
                continue
            finally:
                try:
                    if "multi_sel" in locals() and "curr_sel" in locals():
                        if (
                            len(multi_sel) > 1
                            and len(curr_sel) == 1
                            and (
                                root_path_comps[1].isdigit()
                                or "iLOFederationGroup" in _type
                                or "ManagerAccount" in _type
                                or "Manager" in _type
                            )
                        ):
                            singlet = False
                            curr_sel = multi_sel
                except (ValueError, KeyError):
                    pass

            scanned_dict = dict()
            for thing in curr_sel:
                scanned_dict[thing.path] = {
                    "Origin": "Server",
                    "Scanned": False,
                    "Data": thing.dict,
                }
            for thing in self._fdata[_type]:
                # if we only have a single path, the base path is in the path and only a single
                # instance was retrieved from the server
                if "ManagerAccount" in _type or "iLOFederationGroup" in _type:
                    scanned_dict[thing] = {
                        "Origin": "File",
                        "Scanned": False,
                        "Data": self._fdata[_type][thing],
                    }
                elif singlet and root_path_comps[0] in thing and len(scanned_dict) == 1:
                    scanned_dict[next(iter(scanned_dict))] = {
                        "Origin": "File",
                        "Scanned": False,
                        "Data": self._fdata[_type][thing],
                    }
                else:
                    scanned_dict[thing] = {
                        "Origin": "File",
                        "Scanned": False,
                        "Data": self._fdata[_type][thing],
                    }
            for path in scanned_dict.keys():
                try:
                    if scanned_dict[path]["Origin"] == "Server":
                        raise KeyError(path)
                    else:
                        sys.stdout.write(
                            "---Check special loading for entry---\ntype: %s\npath: " "%s\n" % (_type, path)
                        )
                        tmp = self.subhelper(scanned_dict[path]["Data"], _type, path, options)
                        if tmp:
                            sys.stdout.write("Special entry not applicable...reserving for " "patch loading stage.\n")
                            data.append(tmp)
                        else:
                            sys.stdout.write("---Special loading complete for entry---.\n")
                except KeyError as excp:
                    if path in str(excp) and self._fdata.get(_type) and "iLOFederationGroup" not in _type:
                        if self.delete(
                            scanned_dict[path]["Data"],
                            _type,
                            path,
                            self._fdata[_type],
                            options,
                        ):
                            # ok so this thing does not have a valid path, is not considered a
                            # deletable item so....idk what to do with you. You go to load.
                            # Goodluck
                            tmp = self.altsubhelper(scanned_dict[path]["Data"], _type, path)
                            if tmp:
                                data.append(tmp)
                    else:
                        # if the instance item was not replaced with an entry in the clone file then
                        # it will be deleted
                        self.rdmc.ui.warn("Entry at '%s' removed from this server.\n" % path)

                except Exception as excp:
                    self.rdmc.ui.error("An error occurred: '%s'" % excp)
                    continue
                finally:
                    scanned_dict[path]["Scanned"] = True

        self.file_handler(self.tmp_clone_file, "w+", options, data, True)

    def subhelper(self, data, _type, path, options):
        """
        Reusable code section for load helper
        :param data: dict data (from file or server)
        :type: dictionary
        :param _type: cross compatible iLO type
        :type: string
        :param path: iLO schema path determined from system query
        :type: string
        :param prev
        :parm options: command line options
        :type options: attribute
        """

        # due to EthernetInterfaces OEM/HPE/DHCPv4 also having a key with 'Name'
        # this is required, removing readonly types after POST commands have
        # completed. Would be great if that was resolved...
        prop_list = [
            "Modified",
            "Type",
            "Description",
            "Status",
            "Name",
            "AttributeRegistry",
            "links",
            "SettingsResult",
            "@odata.context",
            "@odata.type",
            "@odata.id",
            "@odata.etag",
            "Links",
            "Actions",
            "AvailableActions",
            "MACAddress",
            "BiosVersion",
        ]

        tmp = dict()
        tmp[_type] = {path: data}
        tmp[_type][path] = self.rdmc.app.removereadonlyprops(tmp[_type][path], False, True, prop_list)
        val_emp = tmp["#Bios.v1_0_4.Bios"]["/redfish/v1/systems/1/bios/settings/"]["Attributes"]
        if val_emp["AdminName"] == "" and val_emp["AdminPhone"] == "" and val_emp["AdminEmail"] == "":
            pass
        else:
            json_traversal_delete_empty(tmp, None, None)
        # if not self.ilo_special_functions(tmp, _type, path, options):
        return tmp

    @log_decor
    def altsubhelper(self, file_data, _type, curr_path):
        """
        Just for manipulating the file_data in the clone file and handing it off to load.
        :param file_data: clone file data
        :type: dictionary
        :param _type: cross compatible iLO type
        :type: string
        :param curr_path: iLO schema path determined from system query
        :type: string
        :param file_path: iLO schema path as observed in the clone file
        :type: string
        :returns: a dictionary containing the data which will be passed off to load.
        """

        tmp = dict()
        try:
            tmp[_type] = {curr_path: file_data[_type][next(iter(file_data[_type]))]}
        except KeyError:
            tmp[_type] = {curr_path: file_data}
        json_traversal_delete_empty(tmp, None, None)
        return tmp

    def loadpatch(self, options):
        """
        Load temporary patch file to server
        :parm options: command line options
        :type options: attribute
        """
        self.rdmc.ui.printer("Patching remaining data.\n")
        fdata = self.file_handler(self.tmp_clone_file, operation="r+", options=options)
        for _sect in fdata:
            _tmp_sel = {}
            _key = next(iter(_sect))
            _tmp_sel[_key.split(".")[0] + "."] = _sect[_key]
            self.file_handler(self.tmp_sel_file, "w", options, [_tmp_sel], True)
            self.loadpatch_helper(_key, _sect, options)

    @log_decor
    def loadpatch_helper(self, type, dict, options):
        """
        Load temporary patch file to server
        :parm options: command line options
        :type options: attribute
        """
        options_str = ""
        if options.encryption:
            options_str += " --encryption " + options.encryption

        if options.uniqueoverride:
            options_str += " --uniqueoverride"

        self.rdmc.ui.printer("Patching '%s'.\n" % type)
        try:
            self.auxcommands["load"].run("-f " + self.tmp_sel_file + options_str)
        except:
            # placeholder for any exception
            pass

    def gatherandsavefunction(self, typelist, options):
        """
        Write parsed JSON save data to file
        :param typelist: list of available types on iLO
        :type typelist: list
        :param options: command line options
        :type options: attribute
        """
        if options.iLOSSA:
            self.save_storageclone(options)
        else:
            data = OrderedDict()
            data.update(self.rdmc.app.create_save_header())
            self.rdmc.ui.printer("Saving of clone file to '%s'.......\n" % self.clone_file)
            for _type in typelist:
                self.gatherandsavehelper(_type, data, options)
            self.file_handler(self.clone_file, "w+", options, data, False)
            self.rdmc.ui.printer("Saving of clone file to '%s' is complete.\n" % self.clone_file)

    def gatherandsavehelper(self, _type, data, options):
        """
        Collect data on types and parse properties (delete unnecessary/readonly/
        empty properties.
        :param type: type for subsequent select and save
        :type type: string
        :param data: JSON data (to be written to file)
        :type data: JSON
        :param options: command line options
        :type options: attribute
        """
        _typep = _type.split(".")[0]
        _spec_list = ["SmartStorageConfig", "iLOLicense", "Bios"]

        try:
            if "EthernetInterface" in _type:
                instances = self.rdmc.app.select(
                    _typep + ".",
                    (
                        self.rdmc.app.typepath.defs.hrefstring,
                        self.rdmc.app.typepath.defs.managerpath + "*",
                    ),
                    path_refresh=True,
                )
            elif "EthernetNetworkInterface" in _type:
                instances = self.rdmc.app.select(
                    _typep + ".",
                    (
                        "links/self/" + self.rdmc.app.typepath.defs.hrefstring,
                        self.rdmc.app.typepath.defs.managerpath + "*",
                    ),
                    path_refresh=True,
                )
            else:
                instances = self.rdmc.app.select(_typep + ".", path_refresh=True)

            for j, instance in enumerate(self.rdmc.app.getprops(insts=instances)):
                if "#" in _typep:
                    _typep = _typep.split("#")[1]
                if self.rdmc.app.typepath.defs.flagforrest:
                    try:
                        path = instance["links"]["self"][self.rdmc.app.typepath.defs.hrefstring]
                    except:
                        path = instance["links"][next(iter(instance["links"]))][self.rdmc.app.typepath.defs.hrefstring]
                else:
                    path = instance[self.rdmc.app.typepath.defs.hrefstring]

                instance = self.ilo_special_functions(instance, _type, path, options)

                _itc_pass = True
                for _itm in _spec_list:
                    if _itm.lower() in _type.lower():
                        templist = [
                            "Modified",
                            "Type",
                            "Description",
                            "Status",
                            "links",
                            "SettingsResult",
                            "@odata.context",
                            "@odata.type",
                            "@odata.id",
                            "@odata.etag",
                            "Links",
                            "Actions",
                            "AvailableActions",
                            "BiosVersion",
                        ]
                        instance = iterateandclear(instance, templist)
                        _itc_pass = False
                        break
                if _itc_pass:
                    instance = self.rdmc.app.removereadonlyprops(instance, False, True)

                if instance and not options.iLOSSA:
                    if _typep != "SmartStorageConfig":
                        if self.rdmc.opts.verbose:
                            self.rdmc.ui.printer("Saving properties of type: %s, path: %s\n" % (_typep, path))
                    elif _typep in options.iLOSSA:
                        sys.stdout.write("ILO SSA calling")
                    if _type not in data:
                        data[_type] = OrderedDict(sorted({path: instance}.items()))
                    else:
                        data[_type][path] = instance
                else:
                    self.rdmc.ui.warn(
                        "Type: %s, path: %s does not contain any modifiable "
                        "properties on this system." % (_typep, path)
                    )

        except Exception as excp:
            self.rdmc.ui.printer('An error occurred saving type: %s\nError: "%s"' % (_typep, excp))

    @log_decor
    def getsystemstatus(self, options):
        """
        Retrieve system status information and save to a changelog file. This
        file will be added to an archive if the archive selection is made.
        :parm options: command line options
        :type options: attribute
        """
        status_list = []

        for item in self.rdmc.app.status():
            status_list.append(item)

        if status_list:
            self.file_handler(self.change_log_file, "w", options, status_list, True)
            with open(self.change_log_file, "rb") as myfile:
                data = myfile.read()
                if options.encryption:
                    data = Encryption().decrypt_file(data, options.encryption)
            with open(self.change_log_file, "wb") as outfile:
                outfile.write(data)
        else:
            self.rdmc.ui.printer("No changes pending.\n")

    def ilo_special_functions(self, data, _type, path, options):
        """
        Function used by both load and save for Restful commands requing a
        POST or PUT.
        :param data: JSON payload for saved or loaded properties
        :type data: json
        :param _type: selected type
        :type _type: string
        :param path: path of the selected type
        :type path: string
        :parm options: command line options
        :type options: attribute
        :returns: returns boolean indicating if the type/path was found.
        """
        identified = False
        _typep = _type.split(".")[0]
        if "#" in _typep:
            _typep = _typep.split("#")[1]

        if "EthernetInterface" in _typep or "EthernetNetworkInterface" in _typep:
            identified = True
            # save function not needed
            if self.load:
                self.load_ethernet(data[_type][path], _type, path)

        elif "DateTime" in _typep:
            # do not use identified=True. Kind of a hack to have additional items patched.
            # save function not needed
            if self.load:
                self.load_datetime(data[_type][path], path)

        elif "LicenseService" in path and "License" in _typep:
            identified = True
            if self.save:
                data = self.save_license(data, _type, options)
            elif self.load:
                self.load_license(data[_type][path])

        elif "AccountService/Accounts" in path and "AccountService" not in _typep:
            identified = True
            if self.save:
                data = self.save_accounts(data, _type, options)
            elif self.load:
                self.load_accounts(data[_type][path], _type, path, options)

        elif "FederationGroup" in _typep:
            identified = True
            if self.save:
                data = self.save_federation(data, _type, options)
            elif self.load:
                self.load_federation(data[_type][path], _type, path, options)

        elif "StorageCollection" in _typep:
            identified = True
            # if self.save:
            # data = self.save_smartstorage(data, _type, options)
            # elif self.load:
            #    self.load_smartstorage(data[_type][path], _type, path)

        if self.save:
            return data

        return identified

    def c_log_write(self, c_str):
        with open(self.change_log_file, "a") as c_log:
            c_log.write(c_str + "\n")

    @log_decor
    def delete(self, data, _type, path, fdata, options):
        """
        Delete operations to remove things on server
        :param data: Data to be deleted from the server
        :type data: dictionary
        :parm _type: iLO type to be queried
        :type _type: string
        :param path: iLO schema path
        :type path: string
        :returns: boolean indicating if the delete option occurred.
        """
        user_confirm = False

        if not options.autocopy and not options.iLOSSA and not options.all:
            while True:
                ans = input(
                    "\n%s\nAre you sure you would like to delete the entry?:\n"
                    % json.dumps(data, indent=1, sort_keys=True)
                )
                if ans.lower() == "y":
                    self.rdmc.ui.printer("Proceeding with Deletion...\n")
                    user_confirm = True
                    break
                elif ans.lower() == "n":
                    self.rdmc.ui.warn("Aborting deletion. No changes have been made made to " "the server.\n")
                    return False
                else:
                    self.rdmc.ui.warn("Invalid input...\n")

        # if "StorageCollection" in _type "Storage" in _type or :
        #     sys.stdout.write("Storage related delete lun on particular controller")

        if "ManagerAccount" in _type:
            user_name = data["UserName"]

            # obtaining account information on the current server as a check to verify the user
            # provided a decent path to use. This can be re-factored.
            try:
                for curr_sel in self.rdmc.app.select(_type.split(".")[0] + "."):
                    try:
                        if "UserName" in list(curr_sel.dict.keys()):
                            _ = curr_sel.dict["UserName"]
                            # check file to make sure this is not to be added later?
                        for fpath in fdata:
                            try:
                                if fdata[fpath]["UserName"] == data["UserName"]:
                                    self.rdmc.ui.warn(
                                        "Account '%s' exists in '%s', not "
                                        "deleting.\n" % (data["UserName"], self.clone_file)
                                    )
                                    return False
                            except:
                                continue

                        if data["UserName"] != "Administrator":
                            self.rdmc.ui.warn(
                                "Manager Account, '%s' was not found in the "
                                "clone file. Deleting entry from server.\n" % data["UserName"]
                            )
                            if not options.autocopy and not options.iLOSSA and not options.all:
                                ans = user_confirm
                            else:
                                ans = True
                            if ans:
                                self.auxcommands["iloaccounts"].run("delete " + data["UserName"])
                                self.c_log_write("[CHANGE]: Deleting user " + data["UserName"])
                                time.sleep(2)
                            del fdata[fpath]
                            return False
                        else:
                            self.rdmc.ui.error(
                                "Deletion of the Default System Administrator " "account is not allowed.\n"
                            )
                    except (KeyError, NameError):
                        self.rdmc.ui.error(
                            "Unable to obtain the account information " "for: '%s''s' account.\n" % user_name
                        )
                        continue
            except InstanceNotFoundError:
                return True
            return False

        if "FederationGroup" in _type:
            fed_identifier = None
            if "FederationName" in data:
                fed_identifier = "FederationName"
            elif "Name" in data:
                fed_identifier = "Name"
            else:
                raise InvalidKeyError("An invalid key was provided for the Federation Group Name.")
            if data[fed_identifier] != "DEFAULT":
                self.rdmc.ui.warn(
                    "Federation Account, '%s' was not found in the clone file."
                    " Deleting entry from server.\n" % data[fed_identifier]
                )
                for fpath in fdata:
                    if fdata[next(iter(fdata))].get("FederationName") == data[fed_identifier]:
                        self.rdmc.ui.warn("Account '%s' exists in file, not deleting." "\n" % data[fed_identifier])
                        return False
                if not options.autocopy and not options.iLOSSA and not options.all:
                    ans = user_confirm
                else:
                    ans = True
                if ans:
                    self.auxcommands["ilofederation"].run("delete " + data[fed_identifier])
                    self.c_log_write("[CHANGE]: Deleting ilo federation user " + data[fed_identifier])
            else:
                self.rdmc.ui.warn("Deletion of the Default iLO Federation Group is not allowed.\n")
            return False
        return True

    @log_decor
    def load_ssocertificate(self):
        """
        Load the SSO Certificate specified in the user defined options.
        """
        self.rdmc.ui.printer("Uploading SSO Certificate...\n")
        self.auxcommands["singlesignon"].run("importcert " + self.sso_cert_file)

    @log_decor
    def load_tlscertificate(self):
        """
        Load the SSO Certificate specified in the user defined options.
        """
        self.rdmc.ui.printer("Uploading TLS Certificate...\n")
        self.auxcommands["certificate"].run("tls " + self.https_cert_file)

    @log_decor
    def load_ethernet(self, ethernet_data, _type, path):
        """
        Load iLO Ethernet Adapters settings Payload.
        :parm datetime_data: iLO Ethernet Adapters payload to be loaded
        :type datetime_data: dict
        :param _type: iLO schema type
        :type _type: string
        :param path: iLO schema path
        :type path: string
        """
        self.auxcommands["ethernet"].load_ethernet_aux(_type, path, ethernet_data)

    @log_decor
    def load_idleconnectiontime(self, options):
        """
        Load iLO IdleConnectionTimeoutMinutes.
        :parm iloidlecondata: IdleConnectionTimeoutMinutes payload to be loaded
        :type iloidlecondata: dict
        :param path: iLO schema path
        """
        filename = self.clone_file
        idle_val = []
        cli_val = []

        with open(filename, "r+b") as file_handle:
            if options.encryption:
                data = json.loads(Encryption().decrypt_file(file_handle.read(), options.encryption))
            else:
                data = json.load(file_handle)
            # data = json.load(file_handle, encoding='cp1252')
            idle_con = data["#Manager.v1_5_1.Manager"]["/redfish/v1/Managers/1/"]["Oem"]["Hpe"][
                "IdleConnectionTimeoutMinutes"
            ]
            serialclispeed = data["#Manager.v1_5_1.Manager"]["/redfish/v1/Managers/1/"]["Oem"]["Hpe"]["SerialCLISpeed"]
            idle_val.append(idle_con)
            cli_val.append(serialclispeed)
        for _t in self._fdata:
            try:
                if "Manager" in _t:
                    _t_path = next(iter(list(self._fdata.get(_t).keys())))
                    pass_dict = {"Oem": {self.rdmc.app.typepath.defs.oemhp: {"IdleConnectionTimeoutMinutes": idle_con}}}
                    cli_dict = {"Oem": {self.rdmc.app.typepath.defs.oemhp: {"SerialCLISpeed": serialclispeed}}}
                    sys.stdout.write("IdleConnectionTimeoutMinutes data %s\n" % pass_dict)
                    sys.stdout.write("SerialCLISpeed data %s\n" % cli_dict)
                    sys.stdout.write("Manager data %s\n" % _t_path)
                    self.rdmc.app.patch_handler(_t_path, pass_dict)
                    self.c_log_write("[CHANGE]: " + _t_path + ":" + str(pass_dict))
                    self.rdmc.app.patch_handler(_t_path, cli_dict)
                    self.c_log_write("[CHANGE]: " + _t_path + ":" + str(cli_dict))
                    break
            except KeyError:
                pass

    @log_decor
    def load_datetime(self, datetime_data, path):
        """
        Load iLO NTP Servers, DateTime Locale Payload.
        :parm datetime_data: iLO NTP Server and Datetime payload to be loaded
        :type datetime_data: dict
        :param path: iLO schema path
        :type path: string
        """
        errors = []

        if "StaticNTPServers" in datetime_data:
            self.rdmc.ui.printer(
                "Attempting to modify 'UseNTPServers' in each iLO Management "
                "Network Interface regarding the StaticNTPServers list in "
                "section 'iLODateTime (DateTime)'\n"
            )
            oem_str = self.rdmc.app.typepath.defs.oempath
            prop_str = (oem_str + "/DHCPv4/UseNTPServers")[1:]
            path_str = self.rdmc.app.typepath.defs.managerpath + "*"
            _instances = self.rdmc.app.select("EthernetInterface", (self.rdmc.app.typepath.defs.hrefstring, path_str))
            _content = self.rdmc.app.getprops("EthernetInterface", [prop_str], None, True, True, _instances)

            for item in _content:
                try:
                    if next(iter(jsonpath_rw.parse("$..UseNTPServers").find(item))).value:
                        self.rdmc.app.patch_handler(
                            path,
                            {oem_str: {"DHCPv4": {"UseNTPServers": True}}},
                        )
                        self.c_log_write(
                            "[CHANGE]: " + path + ":" + str({oem_str: {"DHCPv4": {"UseNTPServers": True}}})
                        )
                    else:
                        self.rdmc.app.patch_handler(
                            path,
                            {oem_str: {"DHCPv4": {"UseNTPServers": False}}},
                        )
                        self.c_log_write(
                            "[CHANGE]: " + path + ":" + str({oem_str: {"DHCPv4": {"UseNTPServers": False}}})
                        )
                except IloResponseError as excp:
                    errors.append("iLO Responded with the following error: %s.\n" % excp)

        if errors:
            self.rdmc.ui.error(
                "iLO responded with an error while attempting to set values "
                "for 'UseNTPServers'. An attempt to patch DateTime "
                "properties will be performed, but may be unsuccessful.\n"
            )
            raise IloResponseError("The following errors in, 'DateTime' were found " "collectively: %s" % errors)

    @log_decor
    def save_license(self, license_data, _type, options):
        """
        Save iLO Server License.
        :parm license_data: iLO Server License payload to be saved
        :type license_data: dict
        :param _type: iLO schema type
        :type _type: string
        :param options: command line options
        :type options: attribute
        """
        key_found = False
        valid_key = False
        license_keys = []
        try:
            if "LicenseKey" in list(license_data["ConfirmationRequest"]["EON"].keys()):
                license_keys.append(license_data["ConfirmationRequest"]["EON"]["LicenseKey"])
        except:
            pass
        finally:
            license_keys.append(license_data.get("LicenseKey"))
        for lic in reversed(license_keys):
            if lic != "" and lic is not None:
                license_key = lic
                key_found = True
                if self.rdmc.opts.verbose:
                    self.rdmc.ui.printer("License Key Found ending in: %s\n" % license_key.split("-")[-1])
                segpass = []
                for seg in lic.split("-"):
                    if "XXXXX" in seg.upper():
                        segpass.append(True)

                if True not in segpass:
                    valid_key = True
                    break

        if not key_found:
            self.rdmc.ui.printer("A License Key was not found on this system.\n")
            license_key = "XXXXX-XXXXX-XXXXX-XXXXX-XXXXX"

        if not options.autocopy and not valid_key and not options.iLOSSA and not options.all:
            while True:
                segpass = []
                license_key = input("Provide your license key: (press enter to skip)\n")

                if license_key.count("X") == 25 or license_key.count("-") == 0:
                    break

                for seg in license_key[0].split("-"):
                    if len(seg) == 5:
                        segpass.append(True)

                if len(segpass) == 5:
                    break
                else:
                    segpass = False
                    self.rdmc.ui.warn("An Invalid License Key was Provided: %s" % license_key)
        else:
            self.rdmc.ui.warn("Remember to verify your License Key...")

        # clear everything, we do not need and just keep license key
        license_data = {"LicenseKey": license_key.upper()}
        return license_data

    @log_decor
    def load_license(self, ilolicdata):
        """
        Load iLO Server License.
        :parm ilolicdata: iLO Server License payload to be loaded
        :type ilolicdata: dict
        """
        license_error_list = "InvalidLicenseKey"
        license_str = ""
        try:
            license_str = ilolicdata["LicenseKey"]
            segpass = []
            for seg in license_str.split("-"):
                if len(seg) == 5:
                    segpass.append(True)

            if len(segpass) == 5:
                self.rdmc.ui.printer("Attempting to load a license key to the server.")
                self.auxcommands["ilolicense"].run("" + license_str)
            else:
                raise ValueError
        except IloResponseError as excp:
            if str(excp) in license_error_list:
                self.rdmc.ui.error("iLO is not accepting your license key ending in '%s'." % license_str.split("-")[-1])
        except ValueError:
            self.rdmc.ui.error("An Invalid License Key ending in '%s' was provided." % license_str.split("-")[-1])

    @log_decor
    def save_accounts(self, accounts, _type, options):
        """
        Load iLO User Account Data.
        :parm accounts: iLO User Account payload to be saved
        :type accounts: dict
        :param _type: iLO schema type
        :type _type: string
        :param options: command line options
        :type options: attribute
        """
        try:
            account_type = next(iter(jsonpath_rw.parse("$..Name").find(accounts))).value
        except StopIteration:
            account_type = None

        try:
            account_un = next(iter(jsonpath_rw.parse("$..UserName").find(accounts))).value
        except StopIteration:
            account_un = None

        try:
            account_ln = next(iter(jsonpath_rw.parse("$..LoginName").find(accounts))).value
        except StopIteration:
            account_ln = None

        try:
            privileges = next(iter(jsonpath_rw.parse("$..Privileges").find(accounts))).value
        except StopIteration:
            privileges = None

        try:
            role_id = next(iter(jsonpath_rw.parse("$..RoleId").find(accounts))).value
        except StopIteration:
            role_id = None

        password = [__DEFAULT__, __DEFAULT__]
        if not options.autocopy and not options.iLOSSA and not options.all:
            while True:
                for i in range(2):
                    if i < 1:
                        self.rdmc.ui.printer("Please input the desired password for user: %s\n" % account_un)
                    else:
                        self.rdmc.ui.printer("Please re-enter the desired password for user: %s\n" % account_un)

                    password[i] = getpass.getpass()
                    try:
                        [password[i], _] = password[i].split("\r")
                    except ValueError:
                        pass

                if password[0] == password[1] and (password[0] is not None or password[0] != ""):
                    break
                else:
                    ans = input("You have entered two different passwords...Retry?(y/n)\n")
                    if ans.lower() != "y":
                        self.rdmc.ui.printer("Skipping Account Migration for: %s\n" % account_un)
                        return None
        else:
            if self.rdmc.opts.verbose:
                self.rdmc.ui.printer(
                    "Remember to edit password for user: '%s', login name: '%s'" "." % (account_un, account_ln)
                )

        if not password[0]:
            password[0] = __DEFAULT__
            self.rdmc.ui.printer("Using a placeholder password of '%s' in %s file.\n" % (password[0], self.clone_file))
        accounts = {
            "AccountType": account_type,
            "UserName": account_un,
            "LoginName": account_ln,
            "Password": password[0],
            "RoleId": role_id,
            "Privileges": privileges,
        }

        return accounts

    def getsesprivs(self, availableprivsopts=False):
        """Finds and returns the curent session's privileges

        :param availableprivsopts: return available privileges
        :type availableprivsopts: boolean.
        """
        if self.rdmc.app.current_client:
            sespath = self.rdmc.app.current_client.session_location
            sespath = (
                self.rdmc.app.current_client.default_prefix
                + sespath.split(self.rdmc.app.current_client.default_prefix)[-1]
            )

            ses = self.rdmc.app.get_handler(sespath, service=False, silent=True)

            if not ses:
                raise SessionExpired("Invalid session. Please logout and " "log back in or include credentials.")

            sesprivs = {
                "HostBIOSConfigPriv": True,
                "HostNICConfigPriv": True,
                "HostStorageConfigPriv": True,
                "LoginPriv": True,
                "RemoteConsolePriv": True,
                "SystemRecoveryConfigPriv": True,
                "UserConfigPriv": True,
                "VirtualMediaPriv": True,
                "VirtualPowerAndResetPriv": True,
                "iLOConfigPriv": True,
            }
            if "Oem" in ses.dict:
                sesoemhp = ses.dict["Oem"][self.rdmc.app.typepath.defs.oemhp]
                if "Privileges" in list(sesoemhp.keys()):
                    sesprivs = sesoemhp["Privileges"]
            availableprivs = list(sesprivs.keys())
            updated_privs = dict()
            for priv, val in sesprivs.items():
                if val:
                    updated_privs[priv] = sesprivs[priv]
            sesprivs = updated_privs
            del updated_privs
        else:
            sesprivs = None
        if availableprivsopts:
            return availableprivs
        else:
            return sesprivs

    @log_decor
    def load_accounts(self, user_accounts, _type, path, options):
        """
        Load iLO User Account Data.
        :parm user_accounts: iLO User Account payload to be loaded
        :type user_accounts: dict
        :param _type: iLO schema type
        :type _type: string
        :param path: iLO schema path
        :type path: string
        """
        found_user = False
        if "UserName" in user_accounts:
            user_name = user_accounts["UserName"]
        else:
            user_name = user_accounts["User_Name"]
        if "LoginName" in user_accounts:
            login_name = user_accounts["LoginName"]
        else:
            login_name = user_accounts["Login_Name"]

        # set minimum password length:
        for _t in self._fdata:
            try:
                if "AccountService" in _t:
                    _t_path = next(iter(list(self._fdata.get(_t).keys())))
                    pass_dict = {"Oem": {self.rdmc.app.typepath.defs.oemhp: {}}}
                    pass_dict["Oem"][self.rdmc.app.typepath.defs.oemhp]["MinPasswordLength"] = self._fdata[_t][_t_path][
                        "Oem"
                    ][self.rdmc.app.typepath.defs.oemhp]["MinPasswordLength"]
                    del self._fdata[_t][_t_path]["Oem"][self.rdmc.app.typepath.defs.oemhp]["MinPasswordLength"]
                    self.rdmc.app.patch_handler(_t_path, pass_dict)
                    self.c_log_write("[CHANGE]: " + _t_path + ":" + str(pass_dict))
                    break
            except KeyError:
                pass
            except Exception as excp:
                self.rdmc.ui.error(
                    "Unable to set minimum password length for manager accounts.\n",
                    excp,
                )

        # set the current privileges to those in the clone file
        curr_privs = user_accounts["Privileges"]

        # set the current role to that in the clone file
        curr_role_id = role_id = None
        role_id = user_accounts.get("RoleId")

        if self.rdmc.app.typepath.defs.flagforrest:
            _ = "links/self/" + self.rdmc.app.typepath.defs.hrefstring
        else:
            _ = self.rdmc.app.typepath.defs.hrefstring

        # obtaining account information on the current server as a check to verify the user
        # provided a decent path to use. This can be re-factored.
        try:
            for curr_sel in self.rdmc.app.select(_type.split(".")[0] + "."):
                try:
                    curr_privs = curr_sel.dict["Oem"][self.rdmc.app.typepath.defs.oemhp]["Privileges"]
                    curr_role_id = curr_sel.dict.get("RoleId")
                    if "UserName" in list(curr_sel.dict.keys()):
                        curr_un = curr_sel.dict["UserName"]
                    else:
                        curr_un = curr_sel.dict["Oem"][self.rdmc.app.typepath.defs.oemhp]["LoginName"]
                    if curr_un != user_name:
                        continue
                    else:
                        found_user = True
                        break
                except (KeyError, NameError):
                    self.rdmc.ui.error("Unable to obtain the account information for: '%s''s'" "account.\n" % user_name)
                    continue
        except InstanceNotFoundError:
            pass

        if not found_user:
            self.rdmc.ui.printer("Account '%s' was not found on this system.\n" % user_name)

        user_pass = user_accounts["Password"]

        (add_privs_str, remove_privs_str) = self.priv_helper(user_accounts, curr_privs)

        if curr_role_id == role_id:
            role_id = None

        # Don't think we need to rely on ResourceExists. Should be able to easily tell which
        # operation should be performed before this point.
        if user_pass:
            if user_pass == __DEFAULT__:
                self.rdmc.ui.warn("The default password will be attempted.")
            try:
                if found_user:
                    raise ResourceExists("")

                    # issue here then we just let it happen and perform a modify on the account.
                elif role_id:
                    self.auxcommands["iloaccounts"].run(
                        "add " + user_name + " " + login_name + " " + user_pass + " " + " --role " + role_id
                    )
                    self.c_log_write("[CHANGE]: Added " + user_name + " with role id " + role_id)
                    time.sleep(2)
                elif add_privs_str:
                    self.auxcommands["iloaccounts"].run(
                        "add " + user_name + " " + login_name + " " + user_pass + " " + " --addprivs " + add_privs_str
                    )
                    self.c_log_write("[CHANGE]: Added " + user_name + " with privs string " + str(add_privs_str))
                    time.sleep(2)
                else:
                    self.auxcommands["iloaccounts"].run("add " + user_name + " " + login_name + " " + user_pass)
                    self.c_log_write("[CHANGE]: Added " + user_name)
                    time.sleep(2)
            except ResourceExists:
                self.rdmc.ui.warn(
                    "The account name '%s' exists on this system. " "Checking for account modifications.\n" % user_name
                )
                self.rdmc.ui.printer("Changing account password for '%s'.\n" % user_name)
                self.auxcommands["iloaccounts"].run("changepass " + user_name + " " + user_pass)
                self.c_log_write("[CHANGE]: Changing password for " + user_name)
                time.sleep(2)
                # if the user includes both role_id and privileges then privileges are applied
                # first skipping role, if they exist. Extra steps, yes, in certain cases
                # but not necessarily.
                if role_id:
                    self.rdmc.ui.printer("Changing roles for user: '%s'.\n" % user_name)
                    self.auxcommands["iloaccounts"].run("modify " + user_name + " --role " + role_id)
                    self.c_log_write("[CHANGE]: Modify role for " + user_name)
                    time.sleep(2)
                else:
                    if "blobstore" in self.rdmc.app.current_client.base_url:
                        url = "/redfish/v1/Managers/1/SecurityService/"
                        get_security = self.rdmc.app.get_handler(url, silent=True, service=True).dict
                        security_mode = get_security["SecurityState"]

                        if (
                            "10" in add_privs_str
                            and "Production" in security_mode
                            and (options.user is None and options.password is None)
                        ):
                            self.c_log_write(
                                "Warning: For the users In local mode privileges might not get "
                                "updated in Production mode , Kindly rerun the serverclone load "
                                "with passing credentials which has recovery privilege"
                            )
                            self.rdmc.ui.error(
                                "Warning: For the users In local mode privileges might not get "
                                "updated in Production mode , Kindly rerun the serverclone load "
                                "with passing credentials which has recovery privilege"
                            )
                        elif not (options.user is None and options.password is None):
                            LOGGER.info("Logging out of the session without user and password")
                            self.rdmc.app.current_client.logout()
                            LOGGER.info("Logging in with user and password for deleting system recovery set")
                            self.rdmc.app.current_client._user_pass = (options.user, options.password)
                            self.rdmc.app.current_client.login(self.rdmc.app.current_client.auth_type)
                            if add_privs_str:
                                self.rdmc.ui.printer("Adding privileges for user: '%s'.\n" % user_name)
                                self.auxcommands["iloaccounts"].run(
                                    "modify " + user_name + " --addprivs " + add_privs_str
                                )
                                self.c_log_write("[CHANGE]: Adding privs for " + user_name)
                                time.sleep(2)
                            if remove_privs_str:
                                self.rdmc.ui.printer("Removing privileges for user: '%s'.\n" % user_name)
                                self.auxcommands["iloaccounts"].run(
                                    "modify " + user_name + " --removeprivs " + remove_privs_str
                                )
                                self.c_log_write("[CHANGE]: Removing privs for " + user_name)
                                time.sleep(2)
                            elif role_id:
                                self.auxcommands["iloaccounts"].run("modify " + user_name + " --role " + role_id)
                                self.c_log_write("[CHANGE]: Modify role id for " + user_name)
                                time.sleep(2)
                    else:
                        if add_privs_str:
                            self.rdmc.ui.printer("Adding privileges for user: '%s'.\n" % user_name)
                            self.auxcommands["iloaccounts"].run("modify " + user_name + " --addprivs " + add_privs_str)
                            self.c_log_write("[CHANGE]: Adding privs for " + user_name)
                            time.sleep(2)
                        if remove_privs_str:
                            self.rdmc.ui.printer("Removing privileges for user: '%s'.\n" % user_name)
                            self.auxcommands["iloaccounts"].run(
                                "modify " + user_name + " --removeprivs " + remove_privs_str
                            )
                            self.c_log_write("[CHANGE]: Removing privs for " + user_name)
                            time.sleep(2)
                        elif role_id:
                            self.auxcommands["iloaccounts"].run("modify " + user_name + " --role " + role_id)
                            self.c_log_write("[CHANGE]: Modify role id for " + user_name)
                            time.sleep(2)
        else:
            raise Exception(
                "A password was not provided for account: '%s', path: '%s'. "
                "iLO accounts will not be altered without a valid password.\n" % (user_name, path)
            )

    @log_decor
    def save_federation(self, fedaccts, _type, options):
        """
        Save of Federation Account Data.
        :parm fedaccts: Federation account payload to be saved
        :type fedaccts: dict
        :param _type: iLO schema type
        :type _type: string
        :param options: command line options
        :type options: attribute
        """

        try:
            fed_name = next(iter(jsonpath_rw.parse("$..Name").find(fedaccts))).value
        except StopIteration:
            privileges = None

        try:
            fed_id = next(iter(jsonpath_rw.parse("$..Id").find(fedaccts))).value
        except StopIteration:
            privileges = None

        try:
            privileges = next(iter(jsonpath_rw.parse("$..Privileges").find(fedaccts))).value
        except StopIteration:
            privileges = None

        fedkey = [__DEFAULT__, __DEFAULT__]
        # if options.iLOSSA:
        #     sys.stdout.write("Smart Storage Array functionality")

        if not options.autocopy and not options.iLOSSA and not options.all:
            while True:
                for i in range(2):
                    if i < 1:
                        self.rdmc.ui.printer("Please input the federation key for Federation " "user: %s\n" % fed_name)
                    else:
                        self.rdmc.ui.printer(
                            "Please re-enter the federation key for Federation " "user: %s\n" % fed_name
                        )

                    fedkey[i] = getpass.getpass()
                    try:
                        [fedkey[i], _] = fedkey[i].split("\r")
                    except ValueError:
                        pass

                if fedkey[0] == fedkey[1] and (fedkey[0] is not None or fedkey[0] != ""):
                    break
                else:
                    ans = input("You have entered two different federation keys...Retry?(y/n)\n")
                    if ans.lower() != "y":
                        self.rdmc.ui.printer("Skipping Federation Account Migration for: " "%s\n" % fed_name)
                        return None
        else:
            self.rdmc.ui.warn("Remember to edit the Federation key for acct: '%s'." % fed_name)

        if not fedkey[0]:
            fedkey[0] = __DEFAULT__
            self.rdmc.ui.warn("Using a placeholder federation key '%s' in %s file.\n" % (fedkey[0], self.clone_file))
        fedaccts = {
            "AccountID": fed_id,
            "FederationName": fed_name,
            "FederationKey": fedkey[0],
            "Privileges": privileges,
        }
        return fedaccts

    @log_decor
    def load_federation(self, fed_accounts, _type, path, options):
        """
        Load of Federation Account Data.
        :parm fed_accounts: Federation account payload to be loaded
        :type fed_accounts: dict
        """

        found_user = False
        fed_name = fed_accounts["FederationName"]
        fed_key = fed_accounts["FederationKey"]

        # set the current privileges to those in the clone file
        curr_privs = fed_accounts["Privileges"]

        # obtaining account information on the current server as a check to verify the user
        # provided a decent path to use. This can be re-factored.
        try:
            for curr_sel in self.rdmc.app.select(_type.split(".")[0] + "."):
                try:
                    curr_privs = curr_sel.dict.get("Privileges")
                    curr_fed = curr_sel.dict.get("Name")
                    if curr_fed != fed_name:
                        continue
                    else:
                        found_user = True
                        break
                except (KeyError, NameError):
                    self.rdmc.ui.error("Unable to obtain the account information for: '%s''s'" "account.\n" % fed_name)
                    continue
        except InstanceNotFoundError:
            pass

        if not found_user:
            self.rdmc.ui.warn("Fed Account '%s' was not found on this system.\n" % fed_name)

        if fed_key:
            if fed_key == __DEFAULT__:
                self.rdmc.ui.warn("The default federation key will be attempted.")
            (add_privs_str, remove_privs_str) = self.priv_helper(fed_accounts, curr_privs)
            try:
                if found_user:
                    raise ResourceExists("")
                else:
                    self.rdmc.ui.printer("Adding '%s' to iLO Federation.\n" % fed_name)
                    self.auxcommands["ilofederation"].run("add " + fed_name + " " + fed_key + " " + add_privs_str)
                    time.sleep(2)
            except ResourceExists:
                self.rdmc.ui.warn("This account already exists on this system: '%s'\n" % fed_name)
                self.rdmc.ui.printer("Changing Federation account: '%s's key\n" % fed_name)
                self.auxcommands["ilofederation"].run("changekey " + fed_name + " " + fed_key)
            except ValueError:
                self.rdmc.ui.error("Some other error occured while attempting to create this " "account: %s" % fed_name)
            finally:
                if "blobstore" in self.rdmc.app.current_client.base_url:
                    url = "/redfish/v1/Managers/1/SecurityService/"
                    get_security = self.rdmc.app.get_handler(url, silent=True, service=True).dict
                    security_mode = get_security["SecurityState"]

                    if (
                        "10" in add_privs_str
                        and (options.user is None and options.password is None)
                        and "Production" in security_mode
                    ):
                        self.c_log_write(
                            "Warning: For the users In local mode privileges might not get updated in "
                            "Production mode , Kindly rerun the serverclone load with "
                            "passing credentials which has recovery privilege"
                        )
                        self.rdmc.ui.error(
                            "Warning: For the users In local mode privileges might not get updated in "
                            "Production mode , Kindly rerun the serverclone load with "
                            "passing credentials which has recovery privilege"
                        )
                    elif not (options.user is None and options.password is None):
                        LOGGER.info("Logging out of the session without user and password")
                        self.rdmc.app.current_client.logout()
                        LOGGER.info("Logging in with user and password for deleting system recovery set")
                        self.rdmc.app.current_client._user_pass = (options.user, options.password)
                        self.rdmc.app.current_client.login(self.rdmc.app.current_client.auth_type)

                        if add_privs_str:
                            self.rdmc.ui.printer("Adding privs to Federation account: '%s'\n" % fed_name)
                            self.auxcommands["ilofederation"].run(
                                "modify "
                                + fed_name
                                + " "
                                + fed_key
                                + " --addprivs "
                                + add_privs_str
                                + " -u "
                                + options.user
                                + " -p "
                                + options.password
                            )
                            time.sleep(2)
                        if remove_privs_str:
                            self.rdmc.ui.printer("Removing privs from Federation account: '%s'\n" % fed_name)
                            self.auxcommands["ilofederation"].run(
                                "modify "
                                + fed_name
                                + " "
                                + fed_key
                                + " --removeprivs "
                                + remove_privs_str
                                + " -u "
                                + options.user
                                + " -p "
                                + options.password
                            )
                            time.sleep(2)

                else:
                    if add_privs_str:
                        self.rdmc.ui.printer("Adding privs to Federation account: '%s'\n" % fed_name)
                        self.auxcommands["ilofederation"].run(
                            "modify " + fed_name + " " + fed_key + " --addprivs " + add_privs_str
                        )
                        time.sleep(2)
                    if remove_privs_str:
                        self.rdmc.ui.printer("Removing privs from Federation account: '%s'\n" % fed_name)
                        self.auxcommands["ilofederation"].run(
                            "modify " + fed_name + " " + fed_key + " --removeprivs " + remove_privs_str
                        )
                        time.sleep(2)

        else:
            self.rdmc.ui.warn(
                "A valid Federation key was not provided...skipping account "
                "creation or modification for Fed. Acct '%s'" % fed_name
            )

    @log_decor
    def save_smartstorage(self, drive_data, _type):
        """
        Smart Storage Disk and Array Controller Configuration save.
        :parm drive_data: Smart Storage Configuration payload to be saved
        :type drive_data: dict
        :param _type: iLO schema type
        :type _type: string
        """

    @log_decor
    def load_smartstorage(self, controller_data, _type, path):
        """
        Smart Storage Disk and Array Controller Configuration load.
        :parm controller_data: Smart Storage Configuration payload to be loaded
        :type controller_data: dict
        :param _type: iLO schema type
        :type _type: string
        :param path: iLO schema path
        :type path: string
        """
        self.smartarrayobj.load(controller_data)

    # Helper Functions
    @log_decor
    def system_compatibility_check(self, sys_info, options):
        """
        Check if files needed for serverclone are available
        :param sys_info: dictionary of comments for iLO firmware and BIOS ROM
        versions
        :type sys_info: dict
        :param options: command line options
        :type options: attribute
        """

        checks = []
        try:
            curr_sys_info = self.rdmc.app.create_save_header()["Comments"]
            curr_ilorev = format(float(self.curr_ilorev[0] + "." + self.curr_ilorev[1:]), ".2f")
            _, file_iloversion, file_ilorev = sys_info["iLOVersion"].split(" ")
            file_ilorev = file_ilorev.split("v")[-1]
            self.rdmc.ui.printer("This system has iLO Version %s. \n" % curr_sys_info["iLOVersion"])
            self.rdmc.ui.printer("This system has BIOS Version %s.\n" % curr_sys_info["BIOSFamily"])
            if curr_sys_info["BIOSFamily"] == sys_info["BIOSFamily"]:
                self.rdmc.ui.printer("BIOS Versions are compatible.\n")
                checks.append(True)
            else:
                self.rdmc.ui.warn(
                    "BIOS Versions are different. Suggest to have"
                    " '%s' in place before upgrading.\n" % sys_info["BIOSFamily"]
                )
                checks.append(False)
            # Commenting out this line as same inforation is being printed twice.
            # self.rdmc.ui.printer(
            #     "This system has iLO %s with firmware revision %s.\n"
            #     % (self.curr_iloversion, curr_ilorev)
            # )
            if self.curr_iloversion == file_iloversion and curr_ilorev == file_ilorev:
                self.rdmc.ui.printer("iLO Versions are fully compatible.\n")
                checks.append(True)
            elif self.curr_iloversion == file_iloversion and curr_ilorev != file_ilorev:
                self.rdmc.ui.warn(
                    "The iLO Versions are compatible; however, the revisions "
                    "differ (system version: iLO %s %s, file version: iLO %s %s). Some "
                    "differences in properties, schemas and incompatible dependencies may "
                    "exist. Proceed with caution.\n" % (self.curr_iloversion, curr_ilorev, file_iloversion, file_ilorev)
                )
                checks.append(False)
            else:
                self.rdmc.ui.warn(
                    "The iLO Versions are different. Compatibility issues may exist "
                    "attempting to commit changes to this system.\n(System version: iLO %s %s, "
                    "file version: iLO %s %s)\n" % (self.curr_iloversion, curr_ilorev, file_iloversion, file_ilorev)
                )
                checks.append(False)
        except KeyError as exp:
            if "iLOVersion" in str(exp):
                self.rdmc.ui.warn("iLOVersion not found in clone file 'Comments' dictionary.\n")
            elif "BIOSFamily" in str(exp):
                self.rdmc.ui.warn("BIOS Family not found in clone file 'Comments' dictionary.\n")
            else:
                raise Exception("%s" % exp)

        if (len(checks) == 0 or False in checks) and not options.autocopy and not options.iLOSSA and not options.all:
            while True:
                ans = input(
                    "Would you like to continue with migration of iLO configuration from "
                    "'%s' to '%s'? (y/n)\n" % (sys_info["Model"], curr_sys_info["Model"])
                )
                if ans.lower() == "n":
                    raise ExitHandler("Aborting load operation. No changes made to the server.")
                elif ans.lower() == "y":
                    break
                else:
                    self.rdmc.ui.warn("Invalid input...\n")

        self.rdmc.ui.printer(
            "Attempting system clone from a '%s' to a '%s'.\n" % (sys_info["Model"], curr_sys_info["Model"])
        )

    def priv_helper(self, desired_priv, curr_privs):
        """
        Privilege helper. Assigns privileges to a string for addition or removal when loading
        iLO management account or iLO Federation data
        :param desired_priv: dictionary of desired privileges
        :type desired_priv: dict
        :param curr_priv: dictionary of current system privileges
        :type curr_priv: dict
        """

        add_privs_str = ""
        remove_privs_str = ""

        if desired_priv.get("Privileges").get("HostBIOSConfigPriv"):
            add_privs_str += "8,"
        else:
            remove_privs_str += "8,"

        if desired_priv.get("Privileges").get("HostNICConfigPriv"):
            add_privs_str += "7,"
        else:
            remove_privs_str += "7,"

        if desired_priv.get("Privileges").get("HostStorageConfigPriv"):
            add_privs_str += "9,"
        else:
            remove_privs_str += "9,"
        if desired_priv.get("Privileges").get("LoginPriv"):
            add_privs_str += "1,"
        else:
            remove_privs_str += "1,"

        if desired_priv.get("Privileges").get("RemoteConsolePriv"):
            add_privs_str += "2,"
        else:
            remove_privs_str += "2,"

        if desired_priv.get("Privileges").get("SystemRecoveryConfigPriv"):
            add_privs_str += "10,"
        else:
            remove_privs_str += "10,"

        if desired_priv.get("Privileges").get("UserConfigPriv"):
            add_privs_str += "3,"
        else:
            remove_privs_str += "3,"
        if desired_priv.get("Privileges").get("VirtualMediaPriv"):
            add_privs_str += "5,"
        else:
            remove_privs_str += "5,"

        if desired_priv.get("Privileges").get("VirtualPowerAndResetPriv"):
            add_privs_str += "6,"
        else:
            remove_privs_str += "6,"

        if desired_priv.get("Privileges").get("iLOConfigPriv"):
            add_privs_str += "4,"
        else:
            remove_privs_str += "4,"

        return (add_privs_str[:-1], remove_privs_str[:-1])

    def get_rootpath(self, path):
        """
        Obtain the root path of the current path (multiple instances within a path)
        :param path: current type path
        :returns: a tuple including either the root_path and the ending or the original path and
        ending
        """

        root_path = ""

        if path[-1] == "/":
            ending = path.split("/")[-2]
        else:
            ending = path.split("/")[-1]

        entries_list = [(pos.start(), pos.end()) for pos in list(re.finditer(ending, path))]
        root_path, ident_ending = (
            path[: entries_list[-1][0]],
            path[entries_list[-1][0] :],
        )

        # check to verify the root path + ending match the original path.
        _ = ""
        if len(root_path + ident_ending) == len(path):
            return (root_path, _.join(ident_ending.split("/")))
        return (path, ident_ending)

    def get_filenames(self):
        """
        Obtain a dictionary of filenames for clonefile, and cert files
        :returns: returns dictionary of filenames
        """
        return {
            "clone_file": self.clone_file,
            "https_cert_file": self.https_cert_file,
            "sso_cert_file": self.sso_cert_file,
        }

    def check_files(self, options):
        """
        Check if files needed for serverclone are available
        :param options: command line options
        :type options: attribute
        """
        if options.encryption:
            if self.save:
                self.rdmc.ui.printer("Serverclone JSON, '%s' will be encrypted.\n" % self.clone_file)
            if self.load:
                self.rdmc.ui.printer("Loading the encrypted JSON clone file: %s.\n" % self.clone_file)
                self.rdmc.ui.printer("Note: Make sure %s is encrypted.\n" % self.clone_file)

        # delete anything in the change log file
        with open(self.change_log_file, "w+") as clf:
            clf.write("")
        # delete anything in the error log file
        with open(self.error_log_file, "w+") as elf:
            elf.write("")

        # check the clone file exists (otherwise create)
        try:
            if options.encryption:
                file_handle = open(self.clone_file, "r+b")
            else:
                file_handle = open(self.clone_file, "r+")
            file_handle.close()
        except:
            if self.save:
                if options.encryption:
                    file_handle = open(self.clone_file, "w+b")
                else:
                    file_handle = open(self.clone_file, "w+")
                file_handle.close()
            else:
                self.rdmc.ui.error("The clone file '%s', selected for loading," " was not found.\n" % self.clone_file)
                raise IOError

    @log_decor
    def type_compare(self, type1, type2):
        """
        iLO schema type compatibility verification
        :param type1
        :type string
        :param type2
        :type string
        :returns: return tuple with booleans of comparison checks
        """
        _type1 = type1
        _type2 = type2
        checklist = ["Major"]  # , 'Minor'] #No minor checking for now

        found_type = False
        compatible = list()

        _type1 = self.type_break(_type1)
        _type2 = self.type_break(_type2)

        if _type1[type1]["Type"].lower() == _type2[type2]["Type"].lower():
            found_type = True

        for item in checklist:
            if _type1[type1]["Version"][item] == _type2[type2]["Version"][item]:
                compatible.append("True")
            else:
                compatible.append("False")

        if "False" in compatible:
            return (found_type, False)
        return (found_type, True)

    @log_decor
    def type_break(self, _type):
        """
        Breakdown of each iLO schema type for version comparison
        :param _type: iLO schema type
        :type _type: string
        """

        _type2 = dict()
        _type_breakdown = _type.split("#")[-1].split(".")
        _type2[_type] = dict([("Type", _type_breakdown[0]), ("Version", {})])
        versioning = list()
        if len(_type_breakdown) == 3 and "_" in _type_breakdown[1]:
            rev = _type_breakdown[1].split("_")
            _type2[_type]["Version"] = {
                "Major": int(rev[0][-1]),
                "Minor": int(rev[1]),
                "Errata": int(rev[2]),
            }
        elif len(_type_breakdown) > 3 and "_" not in _type:
            for value in _type_breakdown:
                if value.isdigit():
                    versioning.append(int(value))
            _type2[_type]["Version"] = {
                "Major": versioning[0],
                "Minor": versioning[1],
                "Errata": versioning[2],
            }

        return _type2

    def serverclonevalidation(self, options):
        """
        Serverclone validation function. Validates command line options and
        initiates a login to the iLO Server.
        :param options: command line options
        :type options: list.
        """

        self._cache_dir = os.path.join(self.rdmc.app.cachedir, __tempfoldername__)
        if not os.path.exists(self._cache_dir):
            os.makedirs(self._cache_dir)
        self.tmp_clone_file = os.path.join(self._cache_dir, __tmp_clone_file__)
        self.tmp_sel_file = os.path.join(self._cache_dir, __tmp_sel_file__)
        # self.change_log_file = os.path.join(self._cache_dir, __changelog_file__)
        # self.error_log_file = os.path.join(self._cache_dir, __error_log_file__)

        self.cmdbase.login_select_validation(self, options)

        if options.clonefilename:
            if len(options.clonefilename) < 2:
                self.clone_file = options.clonefilename[0]
            else:
                raise InvalidCommandLineError("Only a single clone file may be specified.")
        else:
            self.clone_file = __clone_file__

        if options.encryption:
            if len(options.encryption.encode("utf8")) not in [16, 24, 32]:
                raise InvalidKeyError(
                    "An invalid encryption key has been used with a length of: "
                    "%s chars....ensure the encryption key length is 16, 24 or "
                    "32 characters long." % len((options.encryption).encode("utf8"))
                )
        # filenames
        if self.load:
            if options.ssocert:
                if len(options.ssocert) < 2 and self.load:
                    self.sso_cert_file = options.ssocert[0]
                else:
                    raise InvalidCommandLineError("Ensure you are loading a single SSO certificate" ".\n")
            if options.tlscert:
                if len(options.tlscert) < 2 and self.load:
                    self.https_cert_file = options.tlscert[0]
                else:
                    raise InvalidCommandLineError("Ensure you are loading a single TLS certificate" ".\n")
        if self.rdmc.opts.debug:
            self.rdmc.ui.warn(
                "Debug selected...all exceptions will be handled in an external log "
                "file (check error log for automatic testing).\n"
            )
            with open(self.error_log_file, "w+") as efh:
                efh.write("")

    @staticmethod
    def options_argument_group(parser):
        """Define option arguments group
        :param parser: The parser to add the login option group to
        :type parser: ArgumentParser/OptionParser
        """

        parser.add_argument(
            "--encryption",
            dest="encryption",
            help="Optionally include this flag to encrypt/decrypt a file" " using the key provided.",
            default=None,
        )
        parser.add_argument(
            "-f",
            "--clonefile",
            dest="clonefilename",
            help="Optionally rename the default clone file 'ilorest_clone.json'",
            action="append",
            default=None,
        )
        parser.add_argument(
            "-sf",
            "--storageclonefile",
            dest="storageclonefilename",
            help="Optionally rename the default clone file 'ilorest_storage_clone.json'",
            action="append",
            default=None,
        )
        parser.add_argument(
            "--uniqueoverride",
            dest="uniqueoverride",
            action="store_true",
            help="Override the measures stopping the tool from writing." "over items that are system unique.",
            default=None,
        )
        parser.add_argument(
            "--auto",
            dest="autocopy",
            help="Optionally include this flag to ignore user prompts for save or load processes.",
            action="store_true",
            default=None,
        )

    def definearguments(self, customparser):
        """Wrapper function for new command main function
        :param customparser: command line input
        :type customparser: parser.
        """
        if not customparser:
            return

        self.cmdbase.add_login_arguments_group(customparser)
        # self.options_argument_group(customparser)
        subcommand_parser = customparser.add_subparsers(dest="command")
        subcommand_parser.required = True
        save_help = "Save an iLO, Bios and SSA config."
        # save sub-parser
        save_parser = subcommand_parser.add_parser(
            "save",
            help=save_help,
            description=save_help + "\n\texample: serverclone save"
            "\n\n\tSave iLO config omitting BIOS attributes to a non-default file name.\n\t"
            "example: serverclone save -f serv_clone.json --nobios"
            "\n\n\tSave an encrypted iLO configuration file (to the default file name)\n\t"
            "example: serverclone save --encryption <ENCRYPTION KEY>",
            formatter_class=RawDescriptionHelpFormatter,
        )
        save_parser.add_argument(
            "--ilossa",
            dest="iLOSSA",
            help="Optionally include this flag to include configuration of" " iLO Smart Array Devices during save.",
            action="store_true",
            default=None,
        )

        save_parser.add_argument(
            "--all",
            dest="all",
            help="Optionally include this flag to include all" " iLO Smart Array Devices and All during save.",
            action="store_true",
            default=None,
        )

        save_parser.add_argument(
            "--nobios",
            dest="noBIOS",
            help="Optionally include this flag to omit save of Bios configuration.",
            action="store_true",
            default=None,
        )
        self.cmdbase.add_login_arguments_group(save_parser)
        self.options_argument_group(save_parser)

        load_help = "Load an iLO, Bios and/or SSA config."
        # load sub-parser
        load_parser = subcommand_parser.add_parser(
            "load",
            help=load_help,
            description=load_help + "SSO and TLS certificates may be"
            "added on load.\n\n\tLoad a clone file from a non-default file name.\n\t"
            "example: serverclone load -f serv_clone.json"
            "\n\n\tLoad a clone file with SSO and TLS certificates.\n\t"
            "example: serverclone load -ssocert sso.txt --tlscert tls.txt"
            "\n\n\tLoad a clone file which has been encrypted.\n\t"
            "example: serverclone load --encryption abc12abc12abc123\n\n\t",
            formatter_class=RawDescriptionHelpFormatter,
        )
        load_parser.add_argument(
            "--ssocert",
            dest="ssocert",
            help="Use this flag during 'load' to include an SSO certificate."
            " This should be properly formatted in a simple text file.",
            action="append",
            default=None,
        )
        load_parser.add_argument(
            "--tlscert",
            dest="tlscert",
            help="Use this flag during 'load' to include a TLS certificate."
            " This should be properly formatted in a simple text file.",
            action="append",
            default=None,
        )
        load_parser.add_argument(
            "--all",
            dest="all",
            help="Optionally include this flag to include all" " iLO Smart Array Devices and All during save.",
            action="store_true",
            default=None,
        )
        load_parser.add_argument(
            "--ilossa",
            dest="iLOSSA",
            help="Optionally include this flag to include all" " iLO Smart Array Devices and All during loadn.",
            action="store_true",
            default=None,
        )
        load_parser.add_argument(
            "--noautorestart",
            dest="noautorestart",
            help="Optionally noautorestart after loading",
            action="store_true",
            default=False,
        )
        self.cmdbase.add_login_arguments_group(load_parser)
        self.options_argument_group(load_parser)
