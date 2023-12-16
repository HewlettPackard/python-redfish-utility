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
""" Automatic Testing for rdmc """

import datetime
import json
import os
import platform
import random
import re
import string
import sys
import time
import traceback
from logging import FileHandler
from zipfile import ZipFile

from six.moves.urllib.request import urlopen, urlretrieve

try:
    from rdmc_helper import (
        HARDCODEDLIST,
        CommandNotEnabledError,
        Encryption,
        IncompatibleiLOVersionError,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        InvalidOrNothingChangedSettingsError,
        NoChangesFoundOrMadeError,
        NoContentsFoundForOperationError,
        PathUnavailableError,
        ReturnCodes,
    )
except:
    from ilorest.rdmc_helper import (
        HARDCODEDLIST,
        CommandNotEnabledError,
        Encryption,
        IncompatibleiLOVersionError,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        InvalidOrNothingChangedSettingsError,
        NoChangesFoundOrMadeError,
        NoContentsFoundForOperationError,
        PathUnavailableError,
        ReturnCodes,
    )

from redfish.ris.rmc_helper import IloResponseError

__error_logfile__ = "automatictesting_error_logfile.log"
__pass_fail__ = "passfail"
__last_line__ = "lastline"


def log_decor(func):
    """decorator to gather and log traceback while continuing testing"""

    def func_wrap(*args, **kwargs):
        """decorator wrapper function"""
        try:
            func(*args, **kwargs)
        except Exception as exp:
            if isinstance(exp, dict) or isinstance(exp, list):
                # DOES NOT WORK YET. For errors which are captured and gathered before a raise, there
                # is no point in showing the DEBUG log.
                logging(command=func.__name__, error=exp, logfile_ignore=True)
            elif args:
                logging(command=func.__name__, error=exp, args=args[0])
            else:
                logging(command=func.__name__, error=exp)
        else:
            logging(command=func.__name__, args=args[0])

    return func_wrap


def logging(command, error=None, args=None, logfile_ignore=False):
    """
    handler for logging errors as well as the pass/fail log.

    :param command: string representing the command/function which was tested
    :param error: error string (if provided in the event of an exception)
    :param args: arguments provided to the command/function which was tested. May need this
    for various purposes (file handles, references to objects, references to object attributes)

    """
    debug_ret_err = False
    debug_log_errs = []
    data2 = []
    data_passed_failed = {}
    lockout = False
    pass_flag = True

    error_strs = ["Code:400", "Code:401", "Exception", "EXCEPTION", "Warning", "WARNING"]
    if not error:
        try:
            if args:
                if args.rdmc.opts.debug:
                    for handle in args.rdmc.app.logger.parent.handlers:
                        if isinstance(handle, FileHandler):
                            # obtain last 25 lines of the debug log (if '-d' is used)
                            with open(handle.baseFilename, "rb") as dlfh:
                                debug_log_errs = tail_debug_log(dlfh, 25)
            for line in debug_log_errs:
                for err in error_strs:
                    if err in line:
                        with open(__last_line__, "r") as ll_file:
                            tmp_err = ll_file.readline()
                        if err not in tmp_err:
                            with open(__last_line__, "w+") as ll_file:
                                ll_file.write(line)
                                error = line
                                pass_flag = False
                                break
                if error:
                    break
        except:
            debug_ret_err = True

    error_strs = ["Code:400", "Code:401", "Exception", "EXCEPTION", "Warning", "WARNING"]
    if not error:
        try:
            if args:
                if args.rdmc.opts.debug:
                    for handle in args.rdmc.app.logger.parent.handlers:
                        if isinstance(handle, FileHandler):
                            # obtain last 25 lines of the debug log (if '-d' is used)
                            with open(handle.baseFilename, "rb") as dlfh:
                                debug_log_errs = tail_debug_log(dlfh, 25)
            for line in debug_log_errs:
                for err in error_strs:
                    if err in line:
                        with open(__last_line__, "r") as ll_file:
                            tmp_err = ll_file.readline()
                        if err not in tmp_err:
                            with open(__last_line__, "w+") as ll_file:
                                ll_file.write(line)
                                error = line
                                pass_flag = False
                                break
                if error:
                    break
        except:
            debug_ret_err = True

    try:
        fhandle = open(__pass_fail__, "r")
        data = fhandle.readlines()
        fhandle.close()
        for itr in data:
            if "Total: " in itr:
                data2.append("Total: " + str(int(itr.split(":")[-1].split("\n")[0]) + 1))
                continue
            elif "Fail:" in itr and error:
                data2.append("Fail: " + str(int(itr.split(":")[-1].split("\n")[0]) + 1))
                data_passed_failed[command] = "'{}' Command - Failed".format(command)
            elif "Pass:" in itr and pass_flag:
                data2.append("Pass: " + str(int(itr.split(":")[-1].split("\n")[0]) + 1))
                if command not in data_passed_failed:
                    data_passed_failed[command] = "'{}' Command - Passed".format(command)
            elif "Command - " in itr:
                resultdata = itr.split("'")
                data_passed_failed[(resultdata[1])] = itr
            elif not lockout:
                lockout = True
                data2.append(itr.split("\n")[0])
    except Exception:
        sys.stderr.write("An error occurred with Pass/Fail log counter.\n")
        data2 = None
        pass
    finally:
        fhandle = open(__pass_fail__, "w+")
        for element in data2:
            fhandle.writelines(element + "\n")
        fhandle.writelines("\n")
        for k, v in list(data_passed_failed.items()):
            if "\n" in v:
                fhandle.writelines(v)
            else:
                fhandle.writelines(v + "\n")
        fhandle.close()

    if error:
        sys.stderr.write("An error occurred in: %s - %s\n" % (command, error))
        with open(__error_logfile__, "a+") as fhandle:
            fhandle.write("\n" + command + " - Test#: ")
            if data[0]:
                fhandle.write(str(int(data[0].split(":")[-1].split("\n")[0]) + 1))
            else:
                fhandle.write(" 1")

            fhandle.write("\nSimplified Error: " + str(error) + "\n")
            # if args:
            fhandle.write("\nTraceback:\n------------------------\n")
            fhandle.write(str(traceback.format_exc()) + "\n")
            if not debug_ret_err and not logfile_ignore:
                fhandle.write("\nTail of Debug Logfile:")
                fhandle.write("\n------------------------\n")
                for item in debug_log_errs:
                    fhandle.write(item)
                fhandle.write("\n------END OF DEBUG------\n")


def tail_debug_log(f, lines=1, _buffer=4098):
    """Returns last n lines from the filename.

    :param f: filename for 'tail' retrieval
    :type f: file handle
    :param lines: number of lines to retrieve
    :type lines: int
    :param _buffer: buffer space for blocks
    :type _buffer: bytes
    """
    # place holder for the lines found
    lines_found = []

    # block counter will be multiplied by buffer
    # to get the block size from the end
    block_counter = -1

    # loop until we find X lines
    while len(lines_found) < lines:
        try:
            f.seek(block_counter * _buffer, os.SEEK_END)
        except IOError:  # either file is too small, or too many lines requested
            f.seek(0)
            lines_found = f.readlines()
            break

        lines_found = f.readlines()
        block_counter -= 1

    return lines_found[-lines:]


class AutomaticTestingCommand:
    """Automatic testing class command"""

    def __init__(self):
        self.ident = {
            "name": "automatictesting",
            "usage": None,
            "description": "Automatic testing command, not customer facing.",
            "summary": "Automatic testing command, not customer facing.",
            "aliases": [],
            "auxcommands": [
                "LoginCommand",
                "LogoutCommand",
                "TypesCommand",
                "SelectCommand",
                "GetCommand",
                "ListCommand",
                "InfoCommand",
                "SetCommand",
                "StatusCommand",
                "CommitCommand",
                "SaveCommand",
                "LoadCommand",
                "RawDeleteCommand",
                "RawHeadCommand",
                "RawGetCommand",
                "RawPatchCommand",
                "RawPutCommand",
                "RawPostCommand",
                "IscsiConfigCommand",
                "FirmwareUpdateCommand",
                "IloResetCommand",
                "ISToolCommand",
                "ResultsCommand",
                "BootOrderCommand",
                "ServerStateCommand",
                "VirtualMediaCommand",
                "IloAccountsCommand",
                "IloFederationCommand",
                "ClearRestApiStateCommand",
                "CertificateCommand",
                "SigRecomputeCommand",
                "ESKMCommand",
                "SendTestCommand",
                "SingleSignOnCommand",
                "ServerlogsCommand",
                "AHSdiagCommand",
                "SMBiosCommand",
                "IloLicenseCommand",
                "DeleteComponentCommand",
                "DownloadComponentCommand",
                "InstallSetCommand",
                "ListComponentCommand",
                "UpdateTaskQueueCommand",
                "UploadComponentCommand",
                "HpGooeyCommand",
                "PendingChangesCommand",
                "ServerInfoCommand",
                "MaintenanceWindowCommand",
                "FwpkgCommand",
                "RebootCommand",
                "IPProfilesCommand",
                "FirmwareIntegrityCheckCommand",
                "SetPasswordCommand",
                "BiosDefaultsCommand",
                "FwpkgCommand",
                "ServerCloneCommand",
                "FactoryDefaultsCommand",
                "DirectoryCommand",
                "SmartArrayCommand",
            ],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()
        self.ret_code = ReturnCodes.SUCCESS

    def run(self, line, help_disp=False):
        """Main automatic testing worker function

        :param line: string of arguments passed in
        :type line: str.
        """
        if help_disp:
            self.parser.print_help()
            return ReturnCodes.SUCCESS
        try:
            if sys.platform == "darwin":
                raise CommandNotEnabledError("'%s' command is not supported on MacOS" % str(self.name))
            elif "VMkernel" in platform.uname():
                raise CommandNotEnabledError("'%s' command is not supported on VMWare" % str(self.name))
            (options, _) = self.rdmc.rdmc_parse_arglist(self, line)
        except (InvalidCommandLineErrorOPTS, SystemExit):
            if ("-h" in line) or ("--help" in line):
                return ReturnCodes.SUCCESS
            else:
                raise InvalidCommandLineErrorOPTS("")

        self.getautomatictestingvalidation(options)
        with open(__last_line__, "w+") as ll_file:
            ll_file.write("")
        with open(__pass_fail__, "w+") as pf_file:
            pf_file.write("Total: 0\nPass: 0\nFail: 0\n")
        with open(__error_logfile__, "w+") as log_file:
            log_file.write("")

        self.rdmc.ui.printer("***************************************************" "******************************\n")
        self.rdmc.ui.printer("****************************AUTOMATIC TESTING " "STARTING***************************\n")
        self.rdmc.ui.printer("***************************************************" "******************************\n\n")

        self.options = options
        if options.sumtest:
            self.testsumcode()
            return ReturnCodes.SUCCESS
        if options.ahsdiagtest:
            self.ahsdiagtesting(options.local)

        # erase iLORest Debug Log (if debugging enabled)
        if self.rdmc.opts.debug:
            for handle in self.rdmc.app.logger.parent.handlers:
                if isinstance(handle, FileHandler):
                    with open(handle.baseFilename, "w+") as dlfh:
                        dlfh.write("")
        if self.rdmc.config:
            if self.rdmc.config._ac__savefile:
                self.logfile = self.rdmc.config._ac__savefile

        self.helpmenusautomatictesting()
        self.loginautomatictesting()
        self.typesandselectautomatictesting(options.local, options.latestschema)
        self.getandsetautomatictesting(options.latestschema)
        self.saveandloadautomatictesting(options.local, options.latestschema)
        self.iscsiautomatictesting()
        self.istoolautomatictesting()
        self.resultsautomatictesting()
        self.bootorderautomatictesting()
        self.serverstateautomatictesting()
        self.virtualmediaautomatictesting()
        self.accountautomatictesting()
        self.federationautomatictesting()
        self.certificateautomatictesting()
        self.eskmautomatictesting()
        self.sendtestautomatictesting()
        self.ssoautomatictesting()
        self.sigrecomputeautomatictesting()
        self.serverlogstesting()
        self.ilolicensetesting()
        self.setbiospasswordautomatictesting(options.local)
        self.smbiostesting()
        self.cloningautomatictesting()
        self.pendingautomatictesting()
        self.serverinfoautomatictesting()
        self.directoryautomatictesting()
        if options.complete:
            self.serverclonecommandautomatictesting(options.local)
        self.fwpkgcommandautomatictesting()
        self.ipprofilesautomatictesting()
        self.fwintegritycheckautomatictesting()
        self.uploadcomptesting()
        self.listcomptesting()
        self.updatetaskqueuetesting()
        self.installsettesting()
        self.maintenancewindowautomatictesting()
        self.listanddownloadcomptesting()
        self.deletecomptesting()
        if options.complete:
            self.setbiosdefaultsautomatictesting()  # Sets bios default
        self.rawautomatictesting(options.local)
        if options.complete:
            self.smartarrayautomatictesting()
            self.firmwareautomatictesting()

        self.rdmc.ui.printer("***************************************************" "******************************\n")
        self.rdmc.ui.printer("******************************AUTOMATIC TESTING " "DONE*****************************\n")
        self.rdmc.ui.printer("***************************************************" "******************************\n\n")

        # Show PASS/FAIL
        with open(__pass_fail__, "r") as fhandle:
            data = fhandle.readlines()
            self.rdmc.ui.printer("Results are:\n")
            for item in data:
                if item == "\n":
                    break
                else:
                    self.rdmc.ui.printer(item)

        self.rdmc.ui.printer("Review logfiles: '%s', '%s',\n" % (__pass_fail__, __error_logfile__))

        if options.archive:
            self.archive_handler(options.archive[0])

        self.cmdbase.logout_routine(self, options)
        # Return code
        self.rdmc.ui.printer("\n")
        return self.ret_code

    def getautomatictestingvalidation(self, options):
        """get inventory validation function
        :param options: command line options
        :type options: list.
        """
        self.cmdbase.login_select_validation(self, options)

    @log_decor
    def helpmenusautomatictesting(self):
        """handler for help menu auto test"""
        self.rdmc.ui.printer("\n*************************************************" "********************************\n")
        self.rdmc.ui.printer("**********************STARTING HELP MENU AUTOMATIC " "TESTING***********************\n")
        self.rdmc.ui.printer("***************************************************" "******************************\n\n")

        # Argparse will attempt a force exit when using '-h'? Maybe we need to re-add the help
        # command again...
        # try:
        #    self.rdmc.run(['--h'])
        # except Exception as exp:
        #    pass

        for command in self.auxcommands:
            self.auxcommands[command].run("-h")
            self.rdmc.ui.printer(
                "\n*********************************************" "************************************\n"
            )
            self.rdmc.ui.printer(
                "***********************************************" "**********************************\n"
            )
            self.rdmc.ui.printer(
                "***********************************************" "**********************************\n\n"
            )

    @log_decor
    def loginautomatictesting(self):
        """handler for login auto test"""
        self.rdmc.ui.printer("\n*************************************************" "********************************\n")
        self.rdmc.ui.printer("************************STARTING LOGIN AUTOMATIC " "TESTING*************************\n")
        self.rdmc.ui.printer("***************************************************" "******************************\n\n")

        loopcount = 10

        for xint in range(loopcount):
            self.rdmc.ui.printer("Login operation counter: %d\n" % xint)
            self.auxcommands["login"].loginfunction("")

            self.auxcommands["logout"].logoutfunction("")
            self.rdmc.ui.printer("\n")

        self.rdmc.ui.printer("\n*************************************************" "********************************\n")
        self.rdmc.ui.printer("***************************************************" "******************************\n")
        self.rdmc.ui.printer("***************************************************" "******************************\n\n")

    @log_decor
    def typesandselectautomatictesting(self, local, latestschema):
        """handler for types and select auto test

        :param local: flag to enable local login
        :type local: boolean.
        :param latestschema: flag to determine if we should use smart schema.
        :type latestschema: boolean.
        """
        self.rdmc.ui.printer("\n*************************************************" "********************************\n")
        self.rdmc.ui.printer("*******************STARTING TYPES AND SELECT " "AUTOMATIC TESTING*******************\n")
        self.rdmc.ui.printer("***************************************************" "******************************\n\n")

        if local:
            self.auxcommands["login"].loginfunction("")

        typeslist = self.auxcommands["types"].typesfunction("", returntypes=True)

        for item in typeslist:
            if item and not item.startswith("Session."):
                self.rdmc.ui.printer("Selected option:   '%s'\n" % item)
                self.auxcommands["select"].selectfunction(item)
                self.auxcommands["select"].selectfunction("")

                self.getandinfoautomatictesting(latestschema=latestschema)

                self.rdmc.ui.printer(
                    "\n*****************************************" "***************************************\n"
                )
                self.rdmc.ui.printer(
                    "*******************************************" "*************************************\n"
                )
                self.rdmc.ui.printer(
                    "*******************************************" "*************************************\n\n"
                )

        self.auxcommands["logout"].logoutfunction("")

    @log_decor
    def getandsetautomatictesting(self, latestschema):
        """handler for get and set auto test

        :param latestschema: flag to determine if we should use smart schema.
        :type latestschema: boolean.
        """
        self.rdmc.ui.printer("\n*************************************************" "********************************\n")
        self.rdmc.ui.printer("*********************STARTING GET AND SET AUTOMATIC" " TESTING**********************\n")
        self.rdmc.ui.printer("***************************************************" "******************************\n\n")

        self.auxcommands["login"].loginfunction("")
        self.rdmc.ui.printer("\n")

        if self.rdmc.app.typepath.flagiften:
            biosinputlist = [
                "Attributes/BootMode",
                "Attributes/MissingItem",
                "Attributes/AdminName",
                "Attributes/AdminEmail",
                "Attributes/AdminPhone",
                "Attributes/CustomPostMessage",
                "Attributes/ServerAssetTag",
                "Attributes/ServerName",
                "Attributes/ServerOtherInfo",
                "Attributes/ServerPrimaryOs",
                "Attributes/ServiceEmail",
                "Attributes/ServiceName",
                "Attributes/ServiceOtherInfo",
                "Attributes/ServicePhone",
            ]
        else:
            biosinputlist = [
                "BootMode",
                "MissingItem",
                "AdminName",
                "AdminEmail",
                "AdminPhone",
                "CustomPostMessage",
                "ServerAssetTag",
                "ServerName",
                "ServerOtherInfo",
                "ServerPrimaryOs",
                "ServiceEmail",
                "ServiceName",
                "ServiceOtherInfo",
                "ServicePhone",
            ]

        self.setautomatichelper(biosinputlist, "HpBios.", latestschema)

        self.rdmc.ui.printer("\n*************************************************" "*******************************\n")
        self.rdmc.ui.printer("***************************************************" "*****************************\n")
        self.rdmc.ui.printer("***************************************************" "*****************************\n\n")

        biosinputlist = ["Boot/BootSourceOverrideTarget", "AssetTag"]
        self.setautomatichelper(biosinputlist, "ComputerSystem.", latestschema)

        self.rdmc.ui.printer("\n*************************************************" "*******************************\n")
        self.rdmc.ui.printer("***************************************************" "*****************************\n")
        self.rdmc.ui.printer("***************************************************" "*****************************\n\n")
        self.auxcommands["status"].run("")

        self.rdmc.ui.printer("\n*************************************************" "*******************************\n")
        self.rdmc.ui.printer("***************************************************" "*****************************\n")
        self.rdmc.ui.printer("***************************************************" "*****************************\n\n")
        self.auxcommands["commit"].run("")

    @log_decor
    def setautomatichelper(self, inputlist, selector, latestschema):
        """handler for set auto test

        :param inputlist: list of items to be set.
        :type inputlist: list.
        :param selector: type to be select for items that will be set.
        :type selector: str.
        :param latestschema: flag to determine if we should use smart schema.
        :type latestschema: boolean.
        """
        self.rdmc.ui.printer("STARTING TEST FOR SETTINGS ON '%s'.\n" % selector)
        self.auxcommands["select"].selectfunction([selector])

        for item in inputlist:
            listresults = self.auxcommands["get"].getworkerfunction(item, self.options, results=True)
            for getresults in listresults:
                if getresults and isinstance(getresults[next(iter(getresults))], dict):
                    for key in getresults:
                        getresults = getresults[key]

                    for key, value in list(getresults.items()):
                        if key == "BootSourceOverrideTarget":
                            if value == "None":
                                randstring = "Cd"
                            else:
                                randstring = "None"
                        else:
                            randstring = "".join(
                                random.SystemRandom().choice(string.ascii_letters + string.digits) for _ in range(10)
                            )

                        if value == randstring:
                            value = value[::-1]

                        self.rdmc.ui.printer("Setting: '%s'\t\tBefore:'%s'\tAfter:'%s" "'\n" % (key, value, randstring))

                        inputline = item + "=" + randstring

                        if latestschema:
                            inputline += " --latestschema"

                        try:
                            self.auxcommands["set"].run(inputline, skipprint=True)
                        except:
                            pass
                elif getresults:
                    for key, value in list(getresults.items()):
                        randstring = "".join(
                            random.SystemRandom().choice(string.ascii_letters + string.digits) for _ in range(10)
                        )

                        if value == randstring:
                            value = value[::-1]

                        self.rdmc.ui.printer("Setting: '%s'\t\tBefore:'%s'\tAfter:'%s" "'\n" % (key, value, randstring))

                        inputline = key + "=" + randstring

                        if latestschema:
                            inputline += " --latestschema"

                        try:
                            self.auxcommands["set"].run(inputline, skipprint=True)
                        except:
                            pass
                else:
                    InvalidCommandLineError("Variable '%s' was not found in the " "current selection.\n" % item)

    @log_decor
    def getandinfoautomatictesting(self, item="", latestschema=False, getval=None, already_checked=[]):
        """handler for get and info auto test

        :param item: list of items to be set.
        :type item: list.
        :param latestschema: flag to determine if we should use smart schema.
        :type latestschema: boolean.
        :param selectitems: list of selected items.
        :type selectitems: list.
        :param origin: location for current item.
        :type origin: str.
        :param already_checked: List of keys already checked.
        :type already_checked: list.
        """
        listdata = self.auxcommands["get"].getworkerfunction(item, self.options, results=True)
        if not listdata:
            self.rdmc.ui.warn("(GET) No list contents found for section: '%s'\n" % item)

        getdata = self.auxcommands["get"].getworkerfunction(item, self.options, uselist=True, results=True)
        if getdata and item and self.rdmc.opts.verbose:
            self.rdmc.ui.printer("Contents found for section: '%s'\n" % item)
        elif not getdata:
            self.rdmc.ui.warn("(LIST) No contents found for section: '%s'\n" % item)

        cline = item + " --latestschema" if latestschema else item
        try:
            if not self.auxcommands["info"].run(cline, autotest=True):
                logging("info", cline, add_traceback=False)
                raise KeyError
        except:
            self.rdmc.ui.warn("(LIST) No info contents found for section: '%s'\n" % cline)

        if not getdata:
            return

        getdata = getval if getval is not None or item else getdata
        if isinstance(getdata, dict):
            for key, val in list(getdata.items()):
                if key.lower() in HARDCODEDLIST or key.lower() in already_checked:
                    continue
                key = (item + "/" + key) if item else key
                already_checked.append(key)
                self.getandinfoautomatictesting(
                    item=key,
                    latestschema=latestschema,
                    getval=val,
                    already_checked=already_checked,
                )
        elif isinstance(getdata, (list, tuple)):
            for kii in getdata:
                if not isinstance(kii, dict):
                    continue
                for key, val in list(kii.items()):
                    if key.lower() in HARDCODEDLIST:
                        continue
                    key = (item + "/" + key) if item else key
                    if key in already_checked:
                        continue
                    else:
                        already_checked.append(key)
                    self.getandinfoautomatictesting(
                        item=key,
                        latestschema=latestschema,
                        getval=val,
                        already_checked=already_checked,
                    )

    @log_decor
    def saveandloadautomatictesting(self, local, latestschema):
        """handler for save and load auto test

        :param local: flag to enable local login
        :type local: boolean.
        :param latestschema: flag to determine if we should use smart schema.
        :type latestschema: boolean.
        """
        self.rdmc.ui.printer("\n*************************************************" "********************************\n")
        self.rdmc.ui.printer("********************STARTING SAVE AND LOAD " "AUTOMATIC TESTING*********************\n")
        self.rdmc.ui.printer("***************************************************" "******************************\n\n")

        biosinputlist = [
            "AdminName",
            "AdminEmail",
            "AdminPhone",
            "CustomPostMessage",
            "ServerAssetTag",
            "ServerName",
            "ServerOtherInfo",
            "ServerPrimaryOs",
            "ServiceEmail",
            "ServiceName",
            "ServiceOtherInfo",
            "ServicePhone",
        ]
        # TODO: Verify the data in file matches server after load
        # TODO: Add multi select save/load checking
        if local:
            self.auxcommands["login"].loginfunction("")

        self.auxcommands["save"].run("--selector=HpBios. -f ilorest.json")

        fileh = open("ilorest.json", "r")
        tempholder = fileh.read()

        for item in biosinputlist:
            restring = '"' + item + '": ".*?"'
            randstring = "".join(random.SystemRandom().choice(string.ascii_letters + string.digits) for _ in range(10))

            replacestring = '"' + item + '": "' + randstring + '"'
            tempholder = re.sub(restring, replacestring, tempholder, flags=re.DOTALL)

        outfile = open("ilorest.json", "w")
        outfile.write(tempholder)
        outfile.close()

        self.rdmc.ui.printer("\n")

        if latestschema:
            self.auxcommands["load"].run("--latestschema")
        else:
            self.auxcommands["load"].run("-f ilorest.json")

        self.rdmc.ui.printer("\n")
        self.auxcommands["logout"].run("")

    @log_decor
    def iscsiautomatictesting(self):
        """iscsi automatic testing"""
        self.rdmc.ui.printer("***************************************************" "******************************\n")
        self.rdmc.ui.printer("*****************STARTING ISCSI CONFIGURATION " "AUTOMATIC TESTING******************\n")
        self.rdmc.ui.printer("***************************************************" "******************************\n\n")

        found = 0
        testfile = None
        self.auxcommands["iscsiconfig"].run("")

        try:
            self.auxcommands["iscsiconfig"].run("--delete 1")
        except:
            pass

        self.auxcommands["iscsiconfig"].run("--add [1]")
        self.auxcommands["iscsiconfig"].run("--list")
        self.auxcommands["iscsiconfig"].run("--list -f TESTFILE")

        try:
            testfile = open("TESTFILE")
            for line in testfile:
                if '"Attempt 1"' in line:
                    found = 1
                    self.rdmc.ui.printer("Output Validated.\n")
                    break

            if found == 0:
                raise NoContentsFoundForOperationError("Change not found.")
        except Exception as excp:
            raise excp

        try:
            testfile.seek(0)
            found = 1
            self.auxcommands["iscsiconfig"].run("--delete 1")
            self.auxcommands["iscsiconfig"].run("--list -f TESTFILE")

            for line in testfile:
                if '"Attempt 1"' in line:
                    raise NoChangesFoundOrMadeError("Not deleted")

            if found == 0:
                self.rdmc.ui.printer("Attempt successfully deleted.\n")
        except Exception as excp:
            raise excp

        self.auxcommands["logout"].run("")

    @log_decor
    def rawautomatictesting(self, local):
        """raw commands automatic testing

        :param local: flag to enable local login
        :type local: boolean.
        """
        if local:
            self.auxcommands["login"].loginfunction("")

        self.rdmc.ui.printer("\n*************************************************" "********************************\n")
        self.rdmc.ui.printer("*********************STARTING RAW_COMMANDS " "AUTOMATIC TESTING*********************\n")
        self.rdmc.ui.printer("***************************************************" "******************************\n\n")

        self.auxcommands["rawhead"].run('"/rest/v1/systems/1" -f TESTFILE')

        try:
            testfile = open("TESTFILE")
            json.loads(testfile.read())
        except Exception as excp:
            raise excp
        finally:
            testfile.close()

        self.rdmc.ui.printer("json return validated.\n")
        self.auxcommands["rawget"].run('"/rest/v1/systems/1/bios/Settings" -f TESTFILE')

        try:
            testfile = open("TESTFILE")
            json.loads(testfile.read())
        except Exception as excp:
            raise excp
        finally:
            testfile.close()

        self.rdmc.ui.printer("json return validated.\n")

        try:
            writefile = open("WRITEFILE", "w")
            writefile.write(
                '{\n\t"path": "/rest/v1/systems/1/bios/Settings",' '\n\t"body": {\n\t\t"AdminName": "RexySmith"\n\t}\n}'
            )
            writefile.close()

            self.auxcommands["rawpatch"].run("WRITEFILE")
            self.auxcommands["rawget"].run('"/rest/v1/systems/1/bios/Settings" -f TESTFILE')
            testfile = open("TESTFILE")
            found = 0

            for line in testfile:
                if '"AdminName"' in line:
                    if '"RexySmith"' in line:
                        found = 1
                        self.rdmc.ui.printer("json return validated.\n")
                        break

            if found == 0:
                raise NoContentsFoundForOperationError("Change not found.")

        except Exception as excp:
            raise excp

        finally:
            testfile.close()

        # ******************RAW PUT*************************
        try:
            writefile = open("WRITEFILE", "w")
            if self.rdmc.app.typepath.flagiften:
                writefile.write(
                    '{\n\t"path":"/rest/v1/systems/1/bios/Settings",\n'
                    '\t"body":{\n\t\t"Attributes":{\n\t\t\t"BaseConfig":'
                    ' "default"\n\t\t}\n\t}\n}'
                )
            else:
                writefile.write(
                    '{\n\t"path": "/rest/v1/systems/1/bios/Settings",\n'
                    '\t"body":{\n\t\t"BaseConfig": "default"'
                    "\n\t}\n}"
                )
            writefile.close()

            self.auxcommands["rawput"].run("WRITEFILE")
            self.auxcommands["rawget"].run('"/rest/v1/systems/1/bios/Settings" -f TESTFILE')
            testfile = open("TESTFILE")
            found = 0

            for line in testfile:
                if '"BaseConfig"' in line:
                    if '"default"' in line:
                        found = 1
                        self.rdmc.ui.printer("json return validated\n")
                        break

            if found == 0:
                raise NoContentsFoundForOperationError("Change not found.")
        except Exception as excp:
            raise excp
        finally:
            testfile.close()

        # ******************RAW POST************************
        if not local:
            try:
                writefile = open("WRITEFILE", "w")

                if self.rdmc.app.typepath.flagiften:
                    writefile.write(
                        '{\n\t"path": "/redfish/v1/Systems/1/'
                        'Actions/ComputerSystem.Reset/",\n\t"body": '
                        '{\n\t\t"ResetType": "ForceRestart"\n\t}\n}'
                    )
                else:
                    writefile.write(
                        '{\n\t"path": "/rest/v1/Systems/1",\n'
                        '\t"body": {\n\t\t"Action": "Reset",'
                        '\n\t\t"ResetType": "ForceRestart"\n\t}\n}'
                    )

                writefile.close()

                self.auxcommands["rawpost"].run("WRITEFILE")
                self.rdmc.ui.printer("Waiting for BIOS to reset. See you in 7 mins.\n")
                time.sleep(60)
                self.rdmc.ui.printer("6 minutes remaining...\n")
                time.sleep(60)
                self.rdmc.ui.printer("5 minutes remaining...\n")
                time.sleep(60)
                self.rdmc.ui.printer("4 minutes remaining...\n")
                time.sleep(60)
                self.rdmc.ui.printer("3 minutes remaining...\n")
                time.sleep(60)
                self.rdmc.ui.printer("2 minutes remaining...\n")
                time.sleep(60)
                self.rdmc.ui.printer("1 minute remaining...\n")
                time.sleep(60)

                self.auxcommands["rawget"].run('"/rest/v1/systems/1/bios/Settings" -f TESTFILE')
                testfile = open("TESTFILE")
                found = 0

                # may error if bios don't update upon restart
                for line in testfile:
                    if '"AdminEmail"' in line:
                        if '""' in line:
                            found = 1
                            self.rdmc.ui.printer("reset validated\n")
                            break

                if found == 0:
                    raise NoContentsFoundForOperationError("Change not found.")
            except Exception as excp:
                raise excp
            finally:
                testfile.close()

        # ******************RAW DELETE**********************
        self.auxcommands["rawget"].run('"/rest/v1/Sessions" -f TESTFILE')

        try:
            testfile = open("TESTFILE")
            next_item = False

            for line in testfile:
                if next_item:
                    session = line
                    break

                if '"MySession":' in line and '"MySession": false' not in line and '"MySession": true' not in line:
                    next_item = True

            session = session.split('"')

            for item in session:
                if "/Sessions/" in item:
                    session = '"%s"' % item
                    break
        except Exception as excp:
            raise excp
        finally:
            testfile.close()

        try:
            self.auxcommands["rawdelete"].run(session)
            self.rdmc.ui.printer("Session Deleted\n")
        except Exception as excp:
            raise excp

    ''' Rework to configure firmware update test.
    @log_decor
    def firmwareautomatictesting(self):
        """ firmware update automatic testing """

        self.rdmc.ui.printer("\n*************************************************" \
                                        "********************************\n")
        self.rdmc.ui.printer("*********************SKIPING FIRMWARE " \
                            "AUTOMATIC TESTING***************************\n")
        self.rdmc.ui.printer("***************************************************" \
                                        "******************************\n\n")

        fw_url = "http://infinitymaster.us.rdlabs.hpecorp.net:1051/automatic_testing/components"\
                                                                                "/FIRMWARE/blah"
        tmp = urlopen(fw_url)
        rom_url = fw_url + "/ROM/"
        ilo_url = fw_url + "/iLO/"

#         rom_fw_dict = []
#         ilo_fw_dict = []

        rom_fw_arr = self.automatictesting_helper_fb(rom_url)
#         ilo_fw_arr = self.automatictesting_helper_fb(ilo_url)

        try:
            for i in rom_fw_arr:
                #tmparr = path.split('/')
                #urlretrieve(fw_url + path, tmparr[-1])
                (fmw, _) = urlretrieve(rom_url + i, i)
                self.auxcommands['flashfwpkg'].run(fmw + ' --forceupload --ignorechecks')

        except Exception as excp:
            self.rdmc.ui.printer("A General Error Occured: %s" %excp)
            block = True

        #self.auxcommands['login'].run("")

#        if local:
#            return

#        self.auxcommands['login'].run("")
#        tests = {'rom': [], 'firmware': firmware}
#        (romfamily, _) = self.rdmc.app.getbiosfamilyandversion()

#        for version in rom:
#            if romfamily.lower() in version.lower():
#                tests['rom'].append(version)

#        for test in tests:
#            for link in tests[test]:
#                counter = 0
#                keep_going = True

#                self.auxcommands['logout'].run("")
#                self.auxcommands['login'].run("")
#                self.auxcommands['firmwareupdate'].run(link)

#                if test == 'rom':
#                    self.auxcommands['login'].run("")
#                    self.auxcommands['iloreset'].run("")

#                self.rdmc.ui.printer("Waiting for iLO...\n")
#                time.sleep(60)
#                self.rdmc.ui.printer("1 minute remaining...\n")
#                time.sleep(60)

#                while keep_going:
#                    try:
#                        if counter > 50:
#                            raise

#                        counter += 1
#                        keep_going = False
#                        self.auxcommands['login'].run("")
#                    except Exception as excp:
#                        if counter > 50:
#                            raise excp
#                        else:
#                            keep_going = True

    '''

    @log_decor
    def istoolautomatictesting(self):
        """istool automatic testing"""
        self.rdmc.ui.printer("\n*************************************************" "********************************\n")
        self.rdmc.ui.printer("*********************STARTING ISTOOL " "AUTOMATIC TESTING***************************\n")
        self.rdmc.ui.printer("***************************************************" "******************************\n\n")

        self.auxcommands["login"].run("")
        self.auxcommands["istool"].run("")
        self.auxcommands["logout"].run("")

    @log_decor
    def resultsautomatictesting(self):
        """results automatic testing"""
        self.rdmc.ui.printer("\n*************************************************" "********************************\n")
        self.rdmc.ui.printer("*********************STARTING RESULTS " "AUTOMATIC TESTING**************************\n")
        self.rdmc.ui.printer("***************************************************" "******************************\n\n")

        self.auxcommands["login"].run("")
        self.auxcommands["results"].run("")
        self.auxcommands["logout"].run("")

    @log_decor
    def bootorderautomatictesting(self):
        """boot order automatic testing"""
        self.rdmc.ui.printer("\n*************************************************" "********************************\n")
        self.rdmc.ui.printer("*********************STARTING BOOT ORDER " "AUTOMATIC TESTING***********************\n")
        self.rdmc.ui.printer("***************************************************" "******************************\n\n")

        try:
            self.auxcommands["bootorder"].run("--disablebootflag --commit")
        except:
            pass

        self.auxcommands["bootorder"].run("[5,4,3,2,1]")
        self.auxcommands["logout"].run("")

        self.auxcommands["bootorder"].run("--onetimeboot=Cd")
        self.auxcommands["commit"].run("")
        btype, target = self.bootorderhelper()

        if not btype == "Once" or not target == "Cd":
            raise InvalidOrNothingChangedSettingsError

        self.auxcommands["bootorder"].run("--onetimeboot=Hdd")
        self.auxcommands["bootorder"].run("--continuousboot=Hdd --commit")
        btype, target = self.bootorderhelper()

        if not btype == "Continuous" or not target == "Hdd":
            raise InvalidOrNothingChangedSettingsError

        #         self.auxcommands['bootorder'].run("--onetimeboot=Cd")
        #         self.auxcommands['bootorder'].run("--continuousboot=Hdd")
        #         self.auxcommands['bootorder'].run("--disablebootflag --commit")
        #         btype, target = self.bootorderhelper()
        #
        #         if not btype == 'Disabled' or not target == 'None':
        #             raise InvalidOrNothingChangedSettingsError

        self.auxcommands["bootorder"].run("--disablebootflag")
        #         try:
        #             self.auxcommands['bootorder'].run("--disablebootflag")
        #         except:
        #             self.rdmc.ui.printer("Entry is the current boot setting.\n")

        self.auxcommands["logout"].run("")

        self.auxcommands["login"].run("")
        self.auxcommands["bootorder"].run("--securebootkeys=deletepk")
        self.auxcommands["logout"].run("")

        self.auxcommands["login"].run("")
        self.auxcommands["bootorder"].run("--securebootkeys=defaultkeys")
        self.auxcommands["logout"].run("")

        self.auxcommands["login"].run("")
        self.auxcommands["bootorder"].run("--securebootkeys=deletekeys")
        self.auxcommands["logout"].run("")

    @log_decor
    def bootorderhelper(self):
        """boot order helper for automatic testing"""
        self.auxcommands["login"].run("")
        results = self.rdmc.app.get_handler(self.rdmc.app.typepath.defs.systempath, service=True, silent=True)

        btype = results.dict["Boot"]["BootSourceOverrideEnabled"]
        target = results.dict["Boot"]["BootSourceOverrideTarget"]

        return btype, target

    @log_decor
    def serverstateautomatictesting(self):
        """server state automatic testing"""
        self.rdmc.ui.printer("\n*************************************************" "********************************\n")
        self.rdmc.ui.printer("*********************SERVER STATE " "AUTOMATIC TESTING******************************\n")
        self.rdmc.ui.printer("***************************************************" "******************************\n\n")

        self.auxcommands["login"].run("")
        self.auxcommands["serverstate"].run("")
        self.auxcommands["logout"].run("")

    @log_decor
    def virtualmediaautomatictesting(self):
        """virtual media automatic testing"""
        self.rdmc.ui.printer("\n*************************************************" "********************************\n")
        self.rdmc.ui.printer("*********************VIRTUAL MEDIA " "AUTOMATIC TESTING*****************************\n")
        self.rdmc.ui.printer("***************************************************" "******************************\n\n")
        return

        self.auxcommands["login"].run("")
        self.auxcommands["virtualmedia"].run("")

        try:
            self.auxcommands["virtualmedia"].run("2 --remove")
        except:
            pass

        # Needs to be updated
        self.auxcommands["virtualmedia"].run("2 http://10.0.0.1/vm.iso --bootnextreset")
        results = self.rdmc.app.get_handler("/rest/v1/Managers/1/VirtualMedia/2", service=True, silent=True).dict

        if not results["Inserted"] or not results["Oem"][self.rdmc.app.typepath.defs.oemhp]["BootOnNextServerReset"]:
            raise InvalidOrNothingChangedSettingsError("VM not found.")

        self.auxcommands["virtualmedia"].run("2 --remove")

        results = self.rdmc.app.get_handler("/rest/v1/Managers/1/VirtualMedia/2", service=True, silent=True).dict

        if results["Inserted"] or results["Oem"][self.rdmc.app.typepath.defs.oemhp]["BootOnNextServerReset"]:
            raise InvalidOrNothingChangedSettingsError("VM not removed.")

        self.auxcommands["logout"].run("")

    @log_decor
    def accountautomatictesting(self):
        """iLO manager account automatic testing"""
        """ - add, modify privs, changepass, delete"""
        self.rdmc.ui.printer("\n*************************************************" "********************************\n")
        self.rdmc.ui.printer("**************************ACCOUNT " "AUTOMATIC TESTING******************************\n")
        self.rdmc.ui.printer("***************************************************" "******************************\n\n")

        self.auxcommands["login"].run("")
        self.auxcommands["iloaccounts"].run("")
        errors = []
        priv_dict = {
            "LoginPriv": 1,
            "RemoteConsolePriv": 2,
            "UserConfigPriv": 3,
            "iLOConfigPriv": 4,
            "VirtualMediaPriv": 4,
            "VirtualPowerAndResetPriv": 5,
            "HostNICConfigPriv": 6,
            "HostBIOSConfigPriv": 7,
            "HostStorageConfigPriv": 9,
            "SystemRecoveryConfigPriv": 7,
        }
        for i in range(5):
            randname = "".join(random.SystemRandom().choice(string.ascii_letters + string.digits) for _ in range(6))
            accid = None
            rand_privs = random.sample(priv_dict, 3)
            rand_priv_str = "--addprivs "
            for rp in enumerate(rand_privs):
                if rp[1] == "SystemRecoveryConfigPriv":
                    continue
                elif rp[0] == (len(rand_privs) - 1):
                    rand_priv_str += str(priv_dict[rp[1]])
                else:
                    rand_priv_str += str(priv_dict[rp[1]]) + ","
            acct_str = "add " + randname + " " + randname + " testpassword " + rand_priv_str
            try:
                self.auxcommands["iloaccounts"].run(acct_str)
            except Exception as excp:
                if "rand_priv" in locals():
                    errors.append("Unable to create account '{}',  " "'{}': {}".format(randname, acct_str, str(excp)))

            results = self.rdmc.app.get_handler(
                self.rdmc.app.typepath.defs.accountspath, service=True, silent=True
            ).dict[self.rdmc.app.typepath.defs.collectionstring]

            if "Id" not in list(results[0].keys()):
                newresults = []

                for acct in results:
                    acct = self.rdmc.app.get_handler(
                        acct[self.rdmc.app.typepath.defs.hrefstring],
                        service=True,
                        silent=True,
                    ).dict
                    newresults.append(acct)

                results = newresults

            for acct in results:
                if acct["Oem"][self.rdmc.app.typepath.defs.oemhp]["LoginName"] != randname:
                    continue
                else:
                    self.rdmc.ui.printer("Created account found.\n")
                    accid = acct["Id"]
                    privs = acct["Oem"][self.rdmc.app.typepath.defs.oemhp]["Privileges"]
                    try:
                        rand_priv = next(iter(random.sample(privs, 1)))
                        privstr = ""
                        if privs[rand_priv]:
                            privstr = "--removeprivs=" + str(priv_dict[rand_priv])
                        else:
                            privstr = "--addprivs=" + str(priv_dict[rand_priv])
                        self.auxcommands["iloaccounts"].run("modify " + randname + " " + privstr)
                    except Exception as excp:
                        if "rand_priv" in locals():
                            errors.append(
                                "Unable to modify privilege '{}' for account "
                                "'{}': {}".format(rand_priv, randname, str(excp))
                            )
                        else:
                            errors.append(
                                "Unable to retrieve privileges for account '{}' " ": {}".format(randname, excp)
                            )
                    break
            self.auxcommands["iloaccounts"].run("changepass " + randname + " newpassword")
            self.auxcommands["iloaccounts"].run("delete " + accid)

            if not accid:
                raise NoChangesFoundOrMadeError("Created account not found.")

        self.auxcommands["logout"].run("")
        if errors:
            raise Exception("The following errors occurred while testing accounts: %s" % errors)

    @log_decor
    def federationautomatictesting(self):
        """federation automatic testing"""
        self.rdmc.ui.printer("\n*************************************************" "********************************\n")
        self.rdmc.ui.printer("*********************ADDFEDERATION " "AUTOMATIC TESTING*****************************\n")
        self.rdmc.ui.printer("***************************************************" "******************************\n\n")

        self.auxcommands["login"].run("")
        self.auxcommands["ilofederation"].run("")

        redfish = self.rdmc.app.monolith.is_redfish
        randname = "".join(random.SystemRandom().choice(string.ascii_letters + string.digits) for _ in range(6))
        foundfed = False

        self.auxcommands["ilofederation"].run("add " + randname + " password")
        self.auxcommands["ilofederation"].run("")

        path = self.rdmc.app.typepath.defs.federationpath
        results = self.rdmc.app.get_handler(path, service=True, silent=True).dict

        if redfish:
            results = results["Members"]
        else:
            results = results["links"]["Member"]

        newresults = []
        for fed in results:
            fed = self.rdmc.app.get_handler(fed[self.rdmc.app.typepath.defs.hrefstring], service=True, silent=True).dict

            newresults.append(fed)
            results = newresults

        for fed in results:
            if fed["Id"] == randname:
                self.rdmc.ui.printer("Created federation found.\n")
                foundfed = True
                break

        if not foundfed:
            raise NoChangesFoundOrMadeError("Created federation not found.")

        self.auxcommands["ilofederation"].run("changekey " + randname + " newpassword")
        self.auxcommands["ilofederation"].run("delete " + randname)
        self.auxcommands["logout"].run("")

    @log_decor
    def serverlogstesting(self):
        """server logs automatic testing"""
        self.rdmc.ui.printer("\n*************************************************" "********************************\n")
        self.rdmc.ui.printer("*********************STARTING SERVERLOGS " "AUTOMATIC TESTING***********************\n")
        self.rdmc.ui.printer("***************************************************" "******************************\n\n")

        self.auxcommands["login"].loginfunction("")
        self.auxcommands["serverlogs"].run("--selectlog=IEL -f IELlog.txt")
        self.auxcommands["serverlogs"].run("--selectlog=IML -f IMLlog.txt")
        self.auxcommands["serverlogs"].run("--selectlog=AHS --downloadallahs")
        self.auxcommands["serverlogs"].run("--selectlog=AHS --clearlog")
        self.auxcommands["serverlogs"].run("--selectlog=IEL --clearlog")
        self.auxcommands["serverlogs"].run("--selectlog=IML --clearlog")

        self.auxcommands["logout"].run("")

    @log_decor
    def ahsdiagtesting(self, local):
        """ahs diags automatic testing"""
        if local and os.name != "nt":
            self.rdmc.ui.printer(
                "\n*********************************************" "************************************\n"
            )
            self.rdmc.ui.printer(
                "*********************STARTING AHSDIAG " "AUTOMATIC TESTING**************************\n"
            )
            self.rdmc.ui.printer(
                "***********************************************" "**********************************\n\n"
            )
            pass

            self.auxcommands["login"].loginfunction("")
            self.auxcommands["ahsdiag"].run("--WriteSignPost")
            self.auxcommands["ahsdiag"].run(
                "--WriteMarkerPost --instance 1 --markervalue" ' 3 --markertext "Automatictesting"'
            )

        self.auxcommands["logout"].run("")

    @log_decor
    def crapistesting(self):
        """clear rest api automatic testing"""
        self.rdmc.ui.printer("\n*************************************************" "********************************\n")
        self.rdmc.ui.printer("*********************CLEARRESTAPI " "AUTOMATIC TESTING******************************\n")
        self.rdmc.ui.printer("***************************************************" "******************************\n\n")

        self.auxcommands["clearrestapistate"].run("")

        if self.rdmc.app.monolith.is_redfish:
            path = "/redfish/v1/registries/"
        else:
            path = "/rest/v1/registries"

        results = self.rdmc.app.get_handler(path, service=True, silent=True).dict

        for item in results[self.rdmc.app.typepath.dict.collectionstring]:
            if "attributereg" in item[self.rdmc.app.typepath.defs.hrefstring]:
                raise NoChangesFoundOrMadeError("No changes found.")

        self.auxcommands["logout"].run("")

    @log_decor
    def certificateautomatictesting(self):
        """generate csr automatic testing"""
        self.rdmc.ui.printer("\n*************************************************" "********************************\n")
        self.rdmc.ui.printer("*******************SSO AND TLS CERTIFICATE " "AUTOMATIC TESTING*********************\n")
        self.rdmc.ui.printer("***************************************************" "******************************\n\n")

        error_dict = dict()
        delete_items = list()

        url_path = "http://infinitymaster.us.rdlabs.hpecorp.net:1051/automatic_testing/x509_certs/"

        orgname = " HPE"
        orgunit = " _iLOrest_Team"
        commonname = " JustSomeGuys"
        country = " USA"
        state = " Tejas"
        city = " Houston"

        self.auxcommands["login"].run("")
        self.auxcommands["certificate"].run("csr" + orgname + orgunit + commonname + country + state + city)

        for item in self.automatictesting_helper_fb(url_path):
            fld = urlopen(url_path + item)
            data = fld.read()
            with open(item, "w+b") as certfile:
                certfile.write(data)
                delete_items.append(item)
            try:
                self.auxcommands["certificate"].run("tls " + item)
            except Exception:
                error_dict[file] = "tls " + item
                self.rdmc.ui.printer(
                    "iLO flagged an error while uploading the" " TLS certificate file to iLO: %s\n" % item
                )

            try:
                self.auxcommands["singlesignon"].run("importcert " + item)
            except Exception:
                error_dict[file] = "tls " + item
                self.rdmc.ui.printer(
                    "iLO flagged an error while uploading the" " SSO certificate file to iLO: %s\n" % item
                )

        self.automatictesting_helper_fd(delete_items)
        self.auxcommands["logout"].run("")

        if error_dict:
            try:
                raise ValueError
            except ValueError as err:
                if not err.args:
                    err.args = ("iLO flagged an error with components: ",)
                for item in error_dict:
                    err.args = err.args + ("Component: %s, Full String: %s" % (item, error_dict[item]),)
                raise

    @log_decor
    def eskmautomatictesting(self):
        """eskm automatic testing"""
        self.rdmc.ui.printer("\n*************************************************" "********************************\n")
        self.rdmc.ui.printer("*************************ESKM " "AUTOMATIC TESTING**********************************\n")
        self.rdmc.ui.printer("***************************************************" "******************************\n\n")
        pass

        self.auxcommands["login"].run("")
        self.auxcommands["eskm"].run("testconnections")
        self.auxcommands["eskm"].run("clearlog")
        self.auxcommands["logout"].run("")

    @log_decor
    def sigrecomputeautomatictesting(self):
        """sigrecompute automatic testing"""
        self.rdmc.ui.printer("\n*************************************************" "********************************\n")
        self.rdmc.ui.printer("*********************SIGRECOMPUTE " "AUTOMATIC TESTING******************************\n")
        self.rdmc.ui.printer("***************************************************" "******************************\n\n")

        self.auxcommands["login"].run("")

        try:
            self.auxcommands["sigrecompute"].run("")
        except IncompatibleiLOVersionError:
            self.rdmc.ui.printer("Server is redfish. Skipping sigrecompute.\n")

        self.auxcommands["logout"].run("")

    @log_decor
    def sendtestautomatictesting(self):
        """results automatic testing"""
        self.rdmc.ui.printer("\n*************************************************" "********************************\n")
        self.rdmc.ui.printer("*************************SENDTEST " "AUTOMATIC TESTING******************************\n")
        self.rdmc.ui.printer("***************************************************" "******************************\n\n")
        self.auxcommands["login"].run("")
        try:
            self.auxcommands["select"].run(self.rdmc.app.typepath.defs.snmpservice)
            self.auxcommands["select"].run(self.rdmc.app.typepath.defs.managernetworkservicetype)
        except:
            self.rdmc.ui.printer("Skipping sendtest testing, resource not available.\n")
            self.auxcommands["logout"].run("")
            return

        try:
            # setup for snmpalert
            # set SNMPAlertProtocol=SNMPv1Trap
            self.auxcommands["select"].run(self.rdmc.app.typepath.defs.snmpservice)
            self.auxcommands["set"].run("AlertsEnabled=true")
            self.auxcommands["set"].run("AlertDestinations=[testdns.newdnststr] --commit")
        except:
            pass

        try:
            # setup for alertmail
            # {"Oem": { "Hpe":{"AlertMailEnabled": true, "AlertMailEmail": "bob@bob.bob",
            # "AlertMailSenderDomain": "domain", "AlertMailSMTPServer": "1.35.35.35"}}}
            self.auxcommands["select"].run(self.rdmc.app.typepath.defs.managernetworkservicetype)

            if self.rdmc.app.typepath.flagiften:
                oem = "Oem/Hpe"
            else:
                oem = "Oem/Hp"

            self.auxcommands["set"].run(
                oem
                + "/AlertMailEmail=test@test.test "
                + oem
                + "/AlertMailEnabled=True "
                + oem
                + "/AlertMailSMTPServer=testserver.test.test "
                + oem
                + "/AlertMailSenderDomain=testdomain.test.test --commit"
            )
        except:
            pass

        try:
            # setup for syslog
            self.auxcommands["select"].run(self.rdmc.app.typepath.defs.managernetworkservicetype)
            self.auxcommands["set"].run(
                oem + "/RemoteSyslogServer=testserver.test.svrtest " + oem + "/RemoteSyslogEnabled=True --commit"
            )
        except:
            pass

        self.auxcommands["login"].run("")

        self.auxcommands["sendtest"].run("syslog")
        self.auxcommands["sendtest"].run("alertmail")
        self.auxcommands["sendtest"].run("snmpalert")

        self.auxcommands["logout"].run("")

    @log_decor
    def ssoautomatictesting(self):
        """sso automatic testing"""
        self.rdmc.ui.printer("\n*************************************************" "********************************\n")
        self.rdmc.ui.printer("*********************SINGLESIGNON " "AUTOMATIC TESTING******************************\n")
        self.rdmc.ui.printer("***************************************************" "******************************\n\n")

        self.auxcommands["login"].run("")
        self.auxcommands["singlesignon"].run("importdns newdnsname.dnstest")
        self.auxcommands["singlesignon"].run("deleterecord 1")
        self.auxcommands["singlesignon"].run("importdns newdnsname.dnstest")
        self.auxcommands["singlesignon"].run("deleterecord all")

        self.auxcommands["logout"].run("")

    @log_decor
    def ilolicensetesting(self):
        """iLO license automatic testing"""
        self.rdmc.ui.printer("\n*************************************************" "********************************\n")
        self.rdmc.ui.printer("***********************ILOLICENSE " "AUTOMATIC TESTING******************************\n")
        self.rdmc.ui.printer("***************************************************" "******************************\n\n")

        self.auxcommands["login"].run("")

        try:
            self.auxcommands["ilolicense"].run("xx-xx-xx-xx")
        except IloResponseError:
            pass

        self.auxcommands["logout"].run("")

    @log_decor
    def smbiostesting(self):
        """smbios automatic testing"""
        self.rdmc.ui.printer("\n*************************************************" "********************************\n")
        self.rdmc.ui.printer("***************************SMBIOS " "AUTOMATIC TESTING******************************\n")
        self.rdmc.ui.printer("***************************************************" "******************************\n\n")

        if self.rdmc.app.typepath.flagiften:
            self.auxcommands["login"].run("")
            self.auxcommands["smbios"].run("smbios")
            self.auxcommands["logout"].run("")
        else:
            self.rdmc.ui.printer("Skipping smbios testing, server not gen10.\n")

    @log_decor
    def directoryautomatictesting(self):
        """Directory command automatic testing"""
        self.rdmc.ui.printer("\n*************************************************" "********************************\n")
        self.rdmc.ui.printer("*************************DIRECTORY " "AUTOMATIC TESTING*****************************\n")
        self.rdmc.ui.printer("***************************************************" "******************************\n\n")

        self.rdmc.ui.printer("Testing settings output.\n")
        self.auxcommands["directory"].run("kerberos")
        self.auxcommands["directory"].run("ldap")
        self.auxcommands["directory"].run("kerberos -j")
        self.auxcommands["directory"].run("ldap -j")

        self.rdmc.ui.printer("Testing setting properties.\n")
        self.auxcommands["directory"].run("kerberos --serviceaddress test.account --port 1337 --realm " "testrealm")
        self.auxcommands["directory"].run("ldap testusername testpassword --enable")
        self.auxcommands["directory"].run(
            "ldap --serviceaddress test2.account --addsearch autotestsearch," "autotestsearch2"
        )

        self.rdmc.ui.printer("Testing adding roles.\n")
        self.auxcommands["directory"].run(
            'kerberos --addrole "Administrator:a test,' 'ReadOnly:another test" --disable'
        )

        self.rdmc.ui.printer("Validating changes...\n")

        results = self.rdmc.app.select(selector="AccountService.", path_refresh=True)[0].dict

        if results["LDAP"]["Authentication"]["Username"] == "testusername":
            self.rdmc.ui.printer("Validated Username.\n")
        else:
            sys.stderr.write("Username not changed.\n")
        if (
            results["ActiveDirectory"]["ServiceAddresses"][0] == "test.account:1337"
            and results["LDAP"]["ServiceAddresses"][0] == "test2.account"
        ):
            self.rdmc.ui.printer("Validated Service addresses.\n")
        else:
            sys.stderr.write("Service addresses not changed.\n")
            raise IloResponseError("")
        if (
            results["Oem"]["Hpe"]["DirectorySettings"]["LdapServerPort"] == 55
            and results["Oem"]["Hpe"]["KerberosSettings"]["KDCServerPort"] == 1337
        ):
            self.rdmc.ui.printer("Validated Ports.\n")
        else:
            sys.stderr.write("Ports not changed.\n")
            raise IloResponseError("")
        if results["Oem"]["Hpe"]["KerberosSettings"]["KerberosRealm"] == "testrealm":
            self.rdmc.ui.printer("Validated Realm.\n")
        else:
            sys.stderr.write("Realm not changed.\n")
            raise IloResponseError("")
        if (
            "autotestsearch" in results["LDAP"]["LDAPService"]["SearchSettings"]["BaseDistinguishedNames"]
            and "autotestsearch2" in results["LDAP"]["LDAPService"]["SearchSettings"]["BaseDistinguishedNames"]
        ):
            self.rdmc.ui.printer("Validated SearchSettings.\n")
        else:
            sys.stderr.write("SearchSettings not changed.\n")
        if results["LDAP"]["ServiceEnabled"] and not results["ActiveDirectory"]["ServiceEnabled"]:
            self.rdmc.ui.printer("Validated ServiceEnabled.\n")
        else:
            sys.stderr.write("Service not enabled/disabled.\n")
            raise IloResponseError("")
        rolecount = 0
        for role in results["LDAP"]["RemoteRoleMapping"]:
            if role["RemoteGroup"] == "a test" or role["RemoteGroup"] == "another test":
                rolecount += 1
        if rolecount == 2:
            self.rdmc.ui.printer("Validated Role mappings.\n")
        else:
            sys.stderr.write("Remote roles not changed.\n")
            raise IloResponseError("")

        self.rdmc.ui.printer("Removing changes...\n")
        self.auxcommands["directory"].run('kerberos --serviceaddress "" --realm ""')
        self.auxcommands["directory"].run(
            'ldap --serviceaddress "" --disable --removesearch ' "autotestsearch,autotestsearch2"
        )
        self.auxcommands["directory"].run('ldap --removerole "dirgroupa test,dirgroupanother test"')

        self.rdmc.ui.printer("Validating removal.\n")

        results = self.rdmc.app.select(selector="AccountService.", path_refresh=True)[0].dict

        if not results["LDAP"]["ServiceEnabled"]:
            self.rdmc.ui.printer("Validated Service disabled.\n")
        else:
            sys.stderr.write("Service not disabled.\n")
            raise IloResponseError("")
        if not results["ActiveDirectory"]["ServiceAddresses"][0] and not results["LDAP"]["ServiceAddresses"][0]:
            self.rdmc.ui.printer("Validated Service addresses.\n")
        else:
            sys.stderr.write("Service addresses not removed.\n")
            raise IloResponseError("")
        if not results["Oem"]["Hpe"]["KerberosSettings"]["KerberosRealm"]:
            self.rdmc.ui.printer("Validated Realm.\n")
        else:
            sys.stderr.write("Realm not removed.\n")
            raise IloResponseError("")
        if (
            not "autotestsearch" in results["LDAP"]["LDAPService"]["SearchSettings"]["BaseDistinguishedNames"]
            and not "autotestsearch2" in results["LDAP"]["LDAPService"]["SearchSettings"]["BaseDistinguishedNames"]
        ):
            self.rdmc.ui.printer("Validated SearchSettings.\n")
        else:
            sys.stderr.write("SearchSettings not removed.\n")
            raise IloResponseError("")
        rolecount = 0
        for role in results["LDAP"]["RemoteRoleMapping"]:
            if role["RemoteGroup"] == "a test" or role["RemoteGroup"] == "another test":
                rolecount += 1
        if rolecount == 0:
            self.rdmc.ui.printer("Validated Role mappings.\n")
        else:
            sys.stderr.write("Remote roles not removed.\n")
            raise IloResponseError("")

    @log_decor
    def serverclonecommandautomatictesting(self, local):
        """copy command automatic testing"""

        self.rdmc.ui.printer("\n*************************************************" "********************************\n")
        self.rdmc.ui.printer("**************************SERVER CLONE " "AUTOMATIC TESTING*************************\n")
        self.rdmc.ui.printer("***************************************************" "******************************\n\n")

        ue_clone_file_name = "ilorest_clone_ue.json"
        enc_clone_file_name = "ilorest_clone_enc.json"
        delete_list = [ue_clone_file_name, enc_clone_file_name]
        error = {}

        self.auxcommands["login"].loginfunction("")
        try:
            self.rdmc.ui.printer("Testing 'save' operation (unencrypted)...\n")
            line_str = "save --nobios --silent -f " + ue_clone_file_name
            self.auxcommands["serverclone"].run(line_str)

            self.rdmc.ui.printer("Testing 'load' operation (unencrypted)...\n")
            line_str = "load --silent -f "
            tmp_file = self.serverclone_helper(ue_clone_file_name, line_str)
            delete_list.append(tmp_file)
            self.auxcommands["serverclone"].run(line_str + tmp_file)
            self.rdmc.ui.printer("Unencrypted Clone Test Complete\n")

        except Exception as excp:
            self.rdmc.ui.printer("Unencrypted Clone Test Failed\n")
            with open("clone_error_logfile.log", "r") as err_logfile:
                error_log = err_logfile.read()
            with open("changelog.log", "r") as chng_logfile:
                try:
                    chng_log = json.loads(chng_logfile.read())
                except ValueError:
                    chng_log = chng_logfile.read()
            error["unencrypted_clone"] = {
                "base_error": "An error occurred working with serverclone unencrypted save/load: {}".format(excp),
                "command": line_str + tmp_file,
                "traceback": traceback.format_exc(),
                "clone_error_logfile": error_log,
                "change_log": chng_log,
            }

        try:
            self.rdmc.ui.printer("Testing 'save' operation (encrypted)...\n")
            line_str = "save --encryption HPESecretAESKey1 --silent --nobios -f " + enc_clone_file_name
            self.auxcommands["serverclone"].run(line_str)

            self.rdmc.ui.printer("Testing 'load' operation (encrypted)...\n")
            line_str = "load --silent --encryption HPESecretAESKey1 -f "
            tmp_file = self.serverclone_helper(enc_clone_file_name, line_str)
            delete_list.append(tmp_file)
            self.auxcommands["serverclone"].run(line_str)
            self.rdmc.ui.printer("Encrypted Clone Test Complete\n")

        except Exception as excp:
            self.rdmc.ui.printer("Encrypted Clone Test Failed\n")
            with open("clone_error_logfile.log", "r") as err_logfile:
                error_log = err_logfile.read()
            with open("changelog.log", "r") as chng_logfile:
                try:
                    chng_log = json.loads(chng_logfile.read())
                except ValueError:
                    chng_log = chng_logfile.read()
            error["encrypted_clone"] = {
                "base_error": "An error occurred working with serverclone unencrypted save/load: {}".format(excp),
                "command": line_str + tmp_file,
                "traceback": traceback.format_exc(),
                "clone_error_logfile": error_log,
                "change_log": chng_log,
            }

        """ #DO NOT OPEN UNTIL CHRISTMAS (Ok maybe earlier)
        self.rdmc.ui.printer("Attempting load of clone files from NFS server...\n")
        for item in self.automatictesting_helper_fb(url_path):
            f_name = ""
            clone_file = urlopen(url_path + item)
            data = clone_file.read()
            with open(item, 'w+b') as target:
                target.write(data)
            if isinstance(item, six.string_types):
                f_name += item
            delete_list.append(f_name)
            self.auxcommands['serverclone'].run("load --silent -f " + f_name)

        self.rdmc.ui.printer("Test Complete...cleaning up.\n")
        """

        try:
            err_list, err_str = self.automatictesting_helper_fd(delete_list)
            if err_list:
                raise Exception(err_str)
        except Exception as excp:
            error["delete_cfs"] = "An error occurred deleting clone files: '%s'" % str(excp)

        if error:
            raise Exception("The following exceptions occured in ServerClone:\n {}".format(error))

    @log_decor
    def cloningautomatictesting(self):
        """cloning automatic testing"""
        self.rdmc.ui.printer("\n*************************************************" "********************************\n")
        self.rdmc.ui.printer("**************************CLONING " "AUTOMATIC TESTING******************************\n")
        self.rdmc.ui.printer("***************************************************" "******************************\n\n")

        if not self.rdmc.app.typepath.flagiften:
            self.rdmc.ui.printer("Skipping iloclone command, server is not gen10.\n")
            return ReturnCodes.SUCCESS

        self.auxcommands["login"].run("")
        self.cloneobj.run("save -f CLONETEST.json", testing=True)
        self.auxcommands["logout"].run("")
        self.auxcommands["login"].run("")
        self.cloneobj.run("load -f CLONETEST.json", testing=True)
        self.auxcommands["logout"].run("")

    @log_decor
    def pendingautomatictesting(self):
        """pending automatic testing"""
        self.rdmc.ui.printer("\n*************************************************" "********************************\n")
        self.rdmc.ui.printer("**************************PENDING " "AUTOMATIC TESTING******************************\n")
        self.rdmc.ui.printer("***************************************************" "******************************\n\n")

        self.auxcommands["login"].run("")
        self.auxcommands["pending"].run("")
        self.auxcommands["logout"].run("")

    @log_decor
    def deletecomtesting(self):
        """Delete component command testing"""
        self.rdmc.ui.printer("\n*************************************************" "********************************\n")
        self.rdmc.ui.printer("*************************DELETE " "COMPONENT TESTING******************************\n")
        self.rdmc.ui.printer(
            "***************************************************" "********************************\n\n"
        )

        self.auxcommands["login"].run("")

        if not self.rdmc.app.typepath.flagiften:
            self.rdmc.ui.printer("Skipping delete component command, server is not gen10.\n")
            return ReturnCodes.SUCCESS

        self.auxcommands["deletecomp"].run("-a")
        self.auxcommands["logout"].run("")

    @log_decor
    def uploadcomptesting(self):
        """Upload component command testing"""
        self.rdmc.ui.printer("\n*************************************************" "********************************\n")
        self.rdmc.ui.printer("***************************UPLOAD " "COMPONENT TESTING******************************\n")
        self.rdmc.ui.printer("*************************************************" "********************************\n\n")

        error_dict = dict()
        self.auxcommands["login"].run("")
        url_path = "http://infinitymaster.us.rdlabs.hpecorp.net:1051/automatic_testing/components" "/COMPONENTS/"

        if not self.rdmc.app.typepath.flagiften:
            self.rdmc.ui.printer("Skipping upload component command, server is not gen10.\n")
            return ReturnCodes.SUCCESS

        # skip = False
        # compname = "cp029917.exe"
        # compsigname_1 = "cp029917_part1.compsig"
        # compsigname_2 = "cp029917_part2.compsig"
        # compnamepath = os.path.join(os.getcwd(), compname)
        # compsigname_1path = os.path.join(os.getcwd(), compsigname_1)
        # compsigname_2path = os.path.join(os.getcwd(), compsigname_2)

        components_dict = self.automatictesting_helper_fb(url_path, True)
        delete_list = []
        for _, val in list(components_dict.items()):
            compy = None
            try:
                uploadstr = ""
                for file in val:
                    if len(file.split(".")) <= 2:
                        tmparr = file.split(".")
                        fld = urlopen(url_path + file)
                        data = fld.read()
                        with open(file, "w+b") as target:
                            target.write(data)
                        delete_list.append(file)
                        if "compsig" in tmparr[-1]:
                            uploadstr += " --compsig="
                        else:
                            uploadstr += " --component="
                            compy = file
                        uploadstr += file

                self.auxcommands["uploadcomp"].run(uploadstr + " --forceupload")

            except Exception:
                error_dict[compy] = uploadstr
                self.rdmc.ui.printer("iLO flagged an error while uploading the" " previous files: %s\n" % uploadstr)
                self.rdmc.ui.printer("Check for correct file type and compsig.\n")
                continue

        # cleanup routine
        self.automatictesting_helper_fd(delete_list)

        if error_dict:
            try:
                raise ValueError
            except ValueError as err:
                if not err.args:
                    err.args = ("iLO flagged an error with components: ",)
                for item in error_dict:
                    err.args = err.args + ("Component: %s, Full String: %s" % (item, error_dict[item]),)
                raise

    #         try:
    #             if not os.path.isfile(compnamepath):
    #                 (compname, _) = urlretrieve("http://infinitymaster:81"\
    #                     "/automatic_testing/" \
    #                                                         + compname, compname)
    #
    #             if not os.path.isfile(compsigname_1path):
    #                 (compsigname_1, _) = urlretrieve(\
    #                     "http://16.83.62.70/jack/" + compsigname_1, compsigname_1)
    #
    #             if not os.path.isfile(compsigname_2path):
    #                 (compsigname_2, _) = urlretrieve(\
    #                     "http://16.83.62.70/jack/" + compsigname_2, compsigname_2)
    #         except:
    #             skip = True
    #
    #         if not skip:
    #             self.auxcommands['uploadcomp'].run("--component={0} --compsig={1} " \
    #                                "--forceupload".format(compname, compsigname_1))
    #             #self.auxcommands['uploadcomp'].run("--component=firmware-nic-qlogic-nx2-2." \
    #             #                       "19.6-1.1.x86_64.rpm --compsig=firmware-" \
    #             #                       "nic-qlogic-nx2-2.19.6-1.1.x86_64.compsig")
    #
    #             self.auxcommands['logout'].run("")
    #         else:
    #             self.rdmc.ui.printer("Could not complete test due to missing test " \
    #                                                                     "files.\n")

    @log_decor
    def listanddownloadcomptesting(self):
        """List and Download component command testing"""
        self.rdmc.ui.printer("\n*************************************************" "********************************\n")
        self.rdmc.ui.printer("*************************DOWNLOAD " "COMPONENT TESTING******************************\n")
        self.rdmc.ui.printer("***************************************************" "******************************\n\n")

        delete_list = list()
        if not self.rdmc.app.typepath.flagiften:
            self.rdmc.ui.printer("Skipping download component command, server is not gen10.\n")
            return ReturnCodes.SUCCESS

        self.auxcommands["login"].run("")

        self.rdmc.ui.printer("Components found in iLO Repository:\n\n")
        self.auxcommands["listcompt"].run("")
        comps = self.rdmc.app.getcollectionmembers("/redfish/v1/UpdateService/ComponentRepository/")

        for item in comps:
            uri_str = ""
            uri_str += "/fwrepo/" + item["Filename"]
            self.rdmc.ui.printer("Downloading component: '%s'.\n" % item["Filename"])
            self.auxcommands["downloadcomp"].run(uri_str)
            self.rdmc.ui.printer("Successfully downloaded '%s' from iLO " "Repository.\n" % item["Filename"])
            delete_list.append(item["Filename"])

        self.rdmc.ui.printer("Test Complete...cleaning up.\n")
        self.automatictesting_helper_fd(delete_list)
        self.auxcommands["logout"].run("")
        return ReturnCodes.SUCCESS

    @log_decor
    def deletecomptesting(self):
        """Delete from component repository testing"""
        self.rdmc.ui.printer("\n*************************************************" "********************************\n")
        self.rdmc.ui.printer("***************************DELETE " "COMPONENT TESTING******************************\n")
        self.rdmc.ui.printer("***************************************************" "******************************\n\n")
        return

        if not self.rdmc.app.typepath.flagiften:
            self.rdmc.ui.printer("Skipping download component command, server is not gen10.\n")
            return ReturnCodes.SUCCESS

        self.auxcommands["login"].run("")
        self.rdmc.ui.printer("Components found in iLO Repository:\n\n")
        self.auxcommands["listcompt"].run("")

        comps = self.rdmc.app.getcollectionmembers("/redfish/v1/UpdateService/ComponentRepository/")

        for item in comps:
            # str = ""
            # str += "/fwrepo/" + item['Filename']
            self.rdmc.ui.printer("Deleting component: '%s'.\n" % item["Filename"])
            self.auxcommands["deletecomp"].run(item["Filename"])
            self.rdmc.ui.printer("Successfully downloaded '%s' from iLO " "Repository.\n" % item["Filename"])

        self.rdmc.ui.printer("Test Complete...\n")
        self.auxcommands["logout"].run("")
        return ReturnCodes.SUCCESS

    @log_decor
    def installsettesting(self):
        """Install set command testing"""
        self.rdmc.ui.printer("\n*************************************************" "********************************\n")
        self.rdmc.ui.printer("*************************INSTALL " "SET COMMAND TESTING*****************************\n")
        self.rdmc.ui.printer("**************************************************" "*******************************\n\n")

        self.auxcommands["login"].run("")

        if not self.rdmc.app.typepath.flagiften:
            self.rdmc.ui.printer("Skipping install set command, server is not gen10.\n")
            return ReturnCodes.SUCCESS

        installsetlist = []
        url = "http://infinitymaster.us.rdlabs.hpecorp.net:1051/automatic_testing/install_sets/"

        # skip MakeInstallSet
        installsetlist = self.automatictesting_helper_fb(url)
        i = 0

        self.auxcommands["login"].loginfunction("")

        for installset in installsetlist:
            try:
                (installsetfile, _) = urlretrieve(url + installset, installset)
                i = i + 1
                self.rdmc.ui.printer("Uploading Installset: %s\n" % installsetfile)
                self.auxcommands["installset"].run("add " + installset)
                self.rdmc.ui.printer("Invoking Installset: %s\n" % installsetfile)
                self.auxcommands["installset"].run("invoke --name=TestSet" + str(i) + " --cleartaskqueue")
                self.rdmc.ui.printer("Removing Installset: %s\n" % installsetfile)
                self.auxcommands["installset"].run("delete --name=TestSet" + str(i))

            except Exception as excp:
                self.rdmc.ui.printer(
                    "A general error occured while attempting to "
                    "use the file: %s. The following error was "
                    "logged: %s\n" % (installsetfile, excp)
                )
                self.rdmc.ui.printer("Check for missing test files\n")
                continue

        self.rdmc.ui.printer("Removing any remaining installsets\n")
        self.auxcommands["installset"].run("--removeall")
        self.auxcommands["logout"].logoutfunction("")

        for installset in installsetlist:
            try:
                if os.path.exists(installsetfile):
                    self.rdmc.ui.printer("Removing local file: %s\n" % installsetfile)
                    os.remove(installsetfile)
            except Exception as excp:
                self.rdmc.ui.printer(
                    "An error occured attempting to remove the " "file: %s, logged: %s\n" % (installsetfile, excp)
                )
                continue

        return ReturnCodes.SUCCESS

    @log_decor
    def updatetaskqueuetesting(self):
        """Update task queue command testing"""
        self.rdmc.ui.printer("\n*************************************************" "********************************\n")
        self.rdmc.ui.printer("**************************UPDATE " "TASK QUEUE TESTING******************************\n")
        self.rdmc.ui.printer("***************************************************" "******************************\n\n")

        self.auxcommands["login"].run("")

        if not self.rdmc.app.typepath.flagiften:
            self.rdmc.ui.printer("Skipping taskqueue command, server is not gen10.\n")
            return ReturnCodes.SUCCESS

        self.auxcommands["taskqueue"].run("")
        self.auxcommands["taskqueue"].run("create 30")
        self.auxcommands["taskqueue"].run("")

        self.auxcommands["taskqueue"].run("create reboot")
        self.auxcommands["taskqueue"].run("")
        self.auxcommands["taskqueue"].run("-r")
        self.auxcommands["taskqueue"].run("")

        self.auxcommands["logout"].run("")

    @log_decor
    def listcomptesting(self):
        """List component command testing"""
        self.rdmc.ui.printer("\n*************************************************" "********************************\n")
        self.rdmc.ui.printer("*****************************LIST " "COMPONENT TESTING******************************\n")
        self.rdmc.ui.printer("***************************************************" "******************************\n\n")

        self.auxcommands["login"].run("")

        if not self.rdmc.app.typepath.flagiften:
            self.rdmc.ui.printer("Skipping list component command, server is not gen10.\n")
            return ReturnCodes.SUCCESS

        self.auxcommands["listcompt"].run("")
        self.auxcommands["logout"].run("")

    @log_decor
    def testsumcode(self):
        """SUM commands batch testing"""
        self.rdmc.ui.printer("\n*************************************************" "********************************\n")
        self.rdmc.ui.printer("*************************SUM " "COMMANDS TESTING******************************\n")
        self.rdmc.ui.printer(
            "***************************************************" "********************************\n\n"
        )

        self.auxcommands["login"].run("")

        if not self.rdmc.app.typepath.flagiften:
            self.rdmc.ui.printer("Skipping list component command, server is not gen10.")
            return ReturnCodes.SUCCESS

        # TODO:verification of cache to be done manually for now
        if not self.rdmc.app.typepath.flagiften:
            self.auxcommands["rawget"].run("/rest/v1/Chassis/1/Power")
            self.auxcommands["rawget"].run("/redfish/v1/Chassis/1/Power/")
            self.auxcommands["rawget"].run("/rest/v1/Systems/1")
            self.auxcommands["rawget"].run("/redfish/v1/Systems/1/")

            self.auxcommands["hpgooey"].run(" --list --namespace perm")
            #             self.auxcommands['hpgooey'].run(" --read --key ipmanager --namespace perm -f " \
            #                                                                     "c:\ipman.json")
            self.auxcommands["logout"].run("")
            self.auxcommands["login"].run("")

            # Update the password in session_payload.json file.
            #             self.auxcommands['rawpost'].run("session_payload.json --getheaders --service")

            session_key = ""
            for client in self.rdmc.app._rmc_clients:
                session_key = client.get_authorization_key()
                session_key = " --sessionid={0}".format(session_key)
                break
            self.auxcommands["rawpost"].run(
                "sut_provider_registration_payload.json "
                "--getheaders --response --service --providerid"
                "=SUT-PROVIDER" + session_key
            )
            self.auxcommands["rawput"].run(
                "sut_registry_payload.json --getheaders --response" " --service --providerid=SUT-PROVIDER" + session_key
            )
            self.auxcommands["rawput"].run(
                "sut_schema.json --getheaders --response --service " "--providerid=SUT-PROVIDER" + session_key
            )
            self.auxcommands["rawput"].run(
                "sut_settings_schema.json --getheaders --response " "--service --providerid=SUT-PROVIDER" + session_key
            )
            self.auxcommands["rawput"].run(
                "sut_tasksettings_schema.json --getheaders "
                "--response --service --providerid=SUT-PROVIDER " + session_key
            )
            self.auxcommands["rawput"].run(
                "sut_systeminventory_schema.json --getheaders "
                "--response --service --providerid=SUT-PROVIDER " + session_key
            )
            self.auxcommands["rawput"].run("HPSUT_rest.json --providerid=HPSUT-PROVIDER")
            self.auxcommands["rawput"].run("HPSUTSettings_rest.json --providerid=HPSUT-PROVIDER")
            self.auxcommands["rawpatch"].run("HPSUTSettings_rest.json --providerid=HPSUT-PROVIDER")
            self.auxcommands["logout"].run("")

        if self.rdmc.app.typepath.flagiften:
            self.auxcommands["rawget"].run("/redfish/v1/Managers/1/")
            self.auxcommands["rawget"].run("/redfish/v1/Chassis/1/Power/")
            self.auxcommands["rawget"].run("/redfish/v1/Systems/1/")
            self.auxcommands["rawget"].run("/redfish/v1/Managers/1/UpdateService")
            self.auxcommands["rawget"].run("/redfish/v1/Chassis/")

            self.auxcommands["hpgooey"].run(" --list --namespace perm")
            #             self.auxcommands['hpgooey'].run(" --read --key ipmanager --namespace perm -f " \
            #                                                                     "c:\ipman.json")

            self.auxcommands["rawget"].run("/redfish/v1/Managers/1/SecurityService/")
            self.auxcommands["rawget"].run("/redfish/v1/UpdateService/FirmwareInventory/ --expand")
            self.auxcommands["rawget"].run("/redfish/v1/UpdateService/SoftwareInventory/ --expand")
            self.auxcommands["rawget"].run("/redfish/v1/updateService/installsets/ --expand")

            # Check if the uploadcomp commands are necessary for the continuation of the code
            #             compname = "xxx"
            #             compsigname = "yyy"
            compname = "cp029917.exe"
            compsigname_1 = "cp029917_part1.compsig"
            self.auxcommands["uploadcomp"].run(
                "--component={0} --compsig={1} " "--forceupload".format(compname, compsigname_1)
            )

            self.auxcommands["rawget"].run("/redfish/v1/updateService/ComponentRepository/ --expand")
            self.auxcommands["rawget"].run("/redfish/v1/Managers/1/EthernetInterfaces/ --expand")
            self.auxcommands["logout"].run("")

            self.auxcommands["login"].run("")
            # TODO:update the password in session_payload_gen10.json file.
            self.auxcommands["rawpost"].run("session_payload_gen10.json --getheaders --service")
            session_key = ""
            for client in self.rdmc.app._rmc_clients:
                session_key = client.get_authorization_key()
                session_key = " --sessionid={0}".format(session_key)
                break
            self.auxcommands["rawdelete"].run(
                "<session URL returned by previous rawpost> "
                "--getheaders --response --service --providerid="
                "SUT-PROVIDER" + session_key
            )
            self.auxcommands["rawpost"].run(
                "sut_provider_registration_payload_gen10.json "
                "--getheaders --response --service --providerid="
                "SUT-PROVIDER" + session_key
            )
            self.auxcommands["rawput"].run(
                "sut_registry_payload_gen10.json --getheaders "
                "--response --service --providerid=SUT-PROVIDER " + session_key
            )
            self.auxcommands["rawput"].run(
                "sut_schema_gen10.json --getheaders --response " "--service --providerid=SUT-PROVIDER" + session_key
            )
            self.auxcommands["rawput"].run(
                "sut_settings_schema_gen10.json --getheaders "
                "--response --service --providerid=SUT-PROVIDER " + session_key
            )
            self.auxcommands["rawput"].run(
                "sut_tasksettings_schema_gen10.json --getheaders "
                "--response --service --providerid=SUT-PROVIDER " + session_key
            )
            self.auxcommands["rawput"].run(
                "sut_systeminventory_schema_gen10.json --getheaders "
                "--response --service --providerid=SUT-PROVIDER " + session_key
            )

            self.auxcommands["rawput"].run("HPSUT_redfish.json --providerid=HPSUT-PROVIDER")
            self.auxcommands["rawput"].run("HPSUTSettings_redfish.json --providerid=HPSUT-PROVIDER")
            self.auxcommands["rawpatch"].run("HPSUTSettings_redfish.json --providerid=HPSUT-PROVIDER")
            self.auxcommands["logout"].run("")

        self.auxcommands["login"].run("")
        self.auxcommands["rawget"].run("/redfish/v1/Chassis/1/Power/")
        self.auxcommands["rawget"].run("/redfish/v1/Systems/1/")
        self.auxcommands["rawget"].run("/redfish/v1/updateService/installsets/")
        self.auxcommands["rawget"].run("/redfish/v1/updateService/updatetaskqueue/")
        self.auxcommands["rawget"].run("/redfish/v1/UpdateService/FirmwareInventory/")
        self.auxcommands["rawget"].run("/redfish/v1/UpdateService/SoftwareInventory/")
        self.auxcommands["rawget"].run("/redfish/v1/Managers/1/SecurityService/CertificateAuthentication/")
        self.auxcommands["rawget"].run("/redfish/v1/Managers/1/DateTime/")
        self.auxcommands["rawget"].run("/redfish/v1/UpdateService/ComponentRepository/")
        self.auxcommands["rawget"].run("/redfish/v1/UpdateService/FirmwareInventory/")
        self.auxcommands["rawget"].run("/redfish/v1/UpdateService/UpdateTaskQueue/ --expand")

        #         compname = "xxx"
        #         compsigname = "yyy"
        compname = "cp029917.exe"
        compsigname_1 = "cp029917_part1.compsig"
        self.auxcommands["uploadcomp"].run(
            "--component={0} --compsig={1} " "--forceupload".format(compname, compsigname_1)
        )
        self.auxcommands["rawget"].run("/redfish/v1/updateService/ComponentRepository/")
        # Component uri returned by the rawget above
        #         self.auxcommands['downloadcomp'].run("Component uri returned by the rawget above")
        self.auxcommands["logout"].run("")

    @log_decor
    def maintenancewindowautomatictesting(self):
        """Maintenance window command automatic testing"""
        self.rdmc.ui.printer("\n*************************************************" "********************************\n")
        self.rdmc.ui.printer("******************MAINTENANCE WINDOW " "AUTOMATIC TESTING***************************\n")
        self.rdmc.ui.printer("***********************************************" "**********************************\n\n")

        if not self.rdmc.app.typepath.flagiften:
            self.rdmc.ui.printer("Skipping... Not available on Gen 9.")
            return
        self.auxcommands["login"].loginfunction("")

        for entry_ in range(0, 10):
            startoffset = random.randint(1, 10)
            endoffset = random.randint(1, 10) + startoffset

            startdatetime = datetime.datetime.now() + datetime.timedelta(days=startoffset)
            enddatetime = datetime.datetime.now() + datetime.timedelta(days=endoffset)

            maintenancewindow_start_time = startdatetime.strftime("%Y-%m-%dT%H:%M:%S")
            maintenancewindow_descr = '"This is a test for planned maintenance"'
            maintenancewindow_end_time = enddatetime.strftime("%Y-%m-%dT%H:%M:%S")
            maintenancewindow_str = (
                "add "
                + maintenancewindow_start_time
                + " --expire="
                + maintenancewindow_end_time
                + " --name=TestMaintenanceEntry"
                + str(entry_)
                + " --description "
                + maintenancewindow_descr
            )

            self.rdmc.ui.printer("Adding Maintenance Window: " + maintenancewindow_str + "\n")
            self.auxcommands["maintenancewindow"].run(maintenancewindow_str)

            self.auxcommands["maintenancewindow"].run("")

            maintenancewindow_str = "delete TestMaintenanceEntry" + str(entry_)

            self.rdmc.ui.printer("Removing Maintenance Window: " + maintenancewindow_str + "\n")
            self.auxcommands["maintenancewindow"].run(maintenancewindow_str)

        self.auxcommands["logout"].logoutfunction("")

    @log_decor
    def serverinfoautomatictesting(self):
        """Serverinfo command automatic testing"""
        info_list = {
            "--fans",
            "--processor",
            "--memory",
            "--thermals",
            "--power",
            "--system",
        }
        info_string = "--fans --processor --memory --thermals --power --system --showabsent"
        self.rdmc.ui.printer("\n*************************************************" "********************************\n")
        self.rdmc.ui.printer("*************************SERVER INFO AUTOMATIC " "TESTING***************************\n")
        self.rdmc.ui.printer("***********************************************" "**********************************\n\n")

        self.auxcommands["login"].loginfunction("")

        for item in info_list:
            self.auxcommands["serverinfo"].run(item)

        self.auxcommands["serverinfo"].run(info_string)

        self.auxcommands["logout"].logoutfunction("")

    @log_decor
    def fwpkgcommandautomatictesting(self):
        """Fwpkg command automatic testing"""
        self.rdmc.ui.printer("\n*************************************************" "********************************\n")
        self.rdmc.ui.printer("************************FIRMWARE PACKAGE AUTOMATIC " "TESTING***********************\n")
        self.rdmc.ui.printer("*************************************************" "********************************\n\n")

        self.rdmc.ui.printer("Skipping FW Package testing\n")
        # self.fwpackage.run("")

    @log_decor
    def ipprofilesautomatictesting(self):
        """ipprofiles command automatic testing"""
        self.rdmc.ui.printer("\n*************************************************" "********************************\n")
        self.rdmc.ui.printer("*****************************IP PROFILES AUTOMATIC " "TESTING***********************\n")
        self.rdmc.ui.printer("*************************************************" "********************************\n\n")

        self.auxcommands["login"].loginfunction("")
        try:
            self.auxcommands["ipprofiles"].run("")  # expect a non-empty string or buffer
            # self.rdmc.ui.printer("Update with JSON:\n")
            # self.rdmc.ui.printer(repr(self.auxcommands['ipprofiles']obj.run("ipprofiles" + \
            #                                                                ipprofile.json)))
            # self.rdmc.ui.printer(repr(self.auxcommands['ipprofiles']obj.run("ipprofiles")))
        except PathUnavailableError:
            self.rdmc.ui.printer("Skipping IP Profiles test, IP provider is unavailable.\n")

        self.auxcommands["logout"].logoutfunction("")

    @log_decor
    def fwintegritycheckautomatictesting(self):
        """fwintegrity command automatic testing"""
        self.rdmc.ui.printer("\n*************************************************" "********************************\n")
        self.rdmc.ui.printer("******************FIRMWARE INTEGRITY CHECK AUTOMATIC " "TESTING*********************\n")
        self.rdmc.ui.printer("*************************************************" "********************************\n\n")

        if not self.rdmc.app.typepath.flagiften:
            self.rdmc.ui.printer("Skipping firmware integrity check, only available on Gen 10.")
        else:
            self.auxcommands["login"].loginfunction("")
            self.auxcommands["fwintegritycheck"].run("--results")
            self.auxcommands["fwintegritycheck"].run("")
            self.auxcommands["logout"].logoutfunction("")

    @log_decor
    def setbiospasswordautomatictesting(self, local):
        """biospassword command automatic testing"""
        self.rdmc.ui.printer("\n*************************************************" "********************************\n")
        self.rdmc.ui.printer("**********************SET BIOS PASSWORD AUTOMATIC " "TESTING************************\n")
        self.rdmc.ui.printer("***********************************************" "**********************************\n\n")

        if not local:
            self.auxcommands["login"].loginfunction("")
            self.auxcommands["set"].run("testpassword " + '""')
            self.auxcommands["set"].run('""' + " testpassword")
            self.auxcommands["logout"].logoutfunction("")
        else:
            self.rdmc.ui.printer("Skipping setting bios password testing in local.\n")

    @log_decor
    def setbiosdefaultsautomatictesting(self):
        """biosdefault command automatictesting"""
        self.rdmc.ui.printer("\n*************************************************" "********************************\n")
        self.rdmc.ui.printer("************************SET BIOS DEFAULTS AUTOMATIC " "TESTING**********************\n")
        self.rdmc.ui.printer("***********************************************" "**********************************\n\n")

        self.auxcommands["login"].loginfunction("")
        try:
            self.rdmc.ui.printer("Setting BIOS Defaults:\n")
            self.rdmc.ui.printer(repr(self.auxcommands["biosdefaults"].run("--manufacturingdefaults")))
        except:
            self.rdmc.ui.printer("Unable to set BIOS Defaults\n")
        self.auxcommands["logout"].logoutfunction("")

    @log_decor
    def smartarrayautomatictesting(self):
        """smart array command automatictesting"""
        self.rdmc.ui.printer("\n*************************************************" "********************************\n")
        self.rdmc.ui.printer("************************SMART ARRAY AUTOMATIC " "TESTING*******************\n")
        self.rdmc.ui.printer("***********************************************" "********************************\n\n")

        self.auxcommands["select"].selectfunction("SmartStorageConfig.")
        content = self.rdmc.app.getprops()

        if content:
            self.auxcommands["smartarray"].selection_output(dict(controller=None), content)
        else:
            raise Exception("This system does not have a valid Smart Storage Controller")

    # helper functions
    def automatictesting_helper_fd(self, data):
        """
        Helper function to delete files pulled from remote to local machine.

        :param data: dictionary or list of files to be removed
        :type data: dictonary or list
        """
        errors = []

        if isinstance(data, dict):
            for _, d_file in list(data.items()):
                try:
                    if os.path.exists(d_file):
                        os.remove(d_file)
                except Exception as excp:
                    errors.append(
                        "An error occured attempting to remove the file: %s, logged: %s\n"
                        % (filename.split(".")[0], excp)
                    )

        elif isinstance(data, list):
            for d_file in data:
                try:
                    if os.path.exists(d_file):
                        os.remove(d_file)
                except Exception as excp:
                    errors.append(
                        "An error occured attempting to remove the file: %s, logged: %s\n"
                        % (filename.split(".")[0], excp)
                    )

        err_str = "Errors occurred deleting: "
        for blah in errors:
            err_str += "{},".format(blah)
        return errors

    def serverclone_helper(self, filename=None, line=None):
        """
        Helper function to modify and remove properties from a serverclone file

        :param filename: filename of the clone file
        :type filename: str
        """
        errors = []
        delete_dict = []
        data = {}
        try:
            with open(filename, "r") as cf:
                if "--encryption" in line:
                    entries_list = [(pos.start(), pos.end()) for pos in list(re.finditer(ending, path))]
                    encryption_key = None
                    data = json.loads(Encryption().decrypt_file(cf.read(), encryption_key))
                else:
                    data = json.loads(cf.read())
        except Exception as excp:
            errors.append("An error occurred opening the clone file '%s': %s" % (filename, excp))

        try:
            for type in data:
                if "AccountService" in type:
                    for path in list(data[type].keys()):
                        if "MinPasswordLength" in data[type][path]:
                            data[type][path]["MinPasswordLength"] = random.randint(8, 16)
                        if "AuthFailureDelayTimeSeconds" in data[type][path]:
                            data[type][path]["AuthFailureDelayTimeSeconds"] = random.randint(12, 40)
                if "ComputerSystem." in type:
                    for path in list(data[type].keys()):
                        if "IndicatorLED" in data[type][path]:
                            data[type][path]["IndicatorLED"] = "Blinking"
                        if "AssetTag" in data[type][path]:
                            data[type][path]["AssetTag"] = "AutomaticTestAsset".join(
                                random.SystemRandom().choice(string.ascii_letters + string.digits) for _ in range(6)
                            )
                if "EthernetInterface." in type:
                    for path in list(data[type].keys()):
                        if "SpeedMbps" in data[type][path]:
                            if data[type][path]["FullDuplex"]:
                                data[type][path]["FullDuplex"] = False
                            else:
                                data[type][path]["FullDuplex"] = True
                        if "AutoNeg" in data[type][path]:
                            if data[type][path]["AutoNeg"]:
                                data[type][path]["AutoNeg"] = False
                            else:
                                data[type][path]["AutoNeg"] = True
                        if "SpeedMbps" in data[type][path]:
                            if data[type][path]["SpeedMbps"] == 1000:
                                data[type][path]["SpeedMbps"] = 100
                            else:
                                data[type][path]["SpeedMbps"] = 1000
                if "ManagerAccount." in type:
                    for path in list(data[type].keys()):
                        if "Password" in data[type][path]:
                            data[type][path]["Password"] = "password"
                if "iLOLicense" in type:
                    delete_dict.append(type)
                if "SecureBoot" in type:
                    for path in list(data[type].keys()):
                        if "SecureBootEnable" in data[type][path]:
                            data[type][path]["SecureBootEnable"] = False
        except (KeyError, ValueError):
            pass

        for item in delete_dict:
            try:
                del data[item]
            except KeyError:
                pass

        try:
            filename2 = filename.split(".")[0] + "_edited" + ".json"
            with open(filename2, "wb") as cf:
                if "--encryption" in line:
                    [(pos.start(), pos.end()) for pos in list(re.finditer(ending, path))]
                    encryption_key = None
                    cf.write(Encryption().decrypt_file(json.dumps(data, indent=2), encryption_key))
                else:
                    cf.write(json.dumps(data, indent=2))
        except Exception as excp:
            errors.append("An error occurred writing the clone file '%s': %s" % (filename2, excp))

        if errors:
            raise
        else:
            return filename2

    def automatictesting_helper_fb(self, url, components=False):
        """
        Helper function for browsing and creating file dictionary from a
        file server index. Designed around the output display of Node.js
        v10.10.0 which places files into an html table.

        :param url: path to the file server.
        :type url: string
        :param components: flag if file components will be needed
        (multiple associated files)
        :type components: boolean
        """

        # list of ignored files and paths
        ignore_list = ["..", ".", "README"]

        table_row_list = []
        prev_tr = 7
        block = False
        try:
            source_url = urlopen(url)
            read_url = source_url.read()
            read_url = read_url[read_url.find("<table>") : read_url.find("<table>") + read_url.find("</table>")]
            while read_url.find("<tr>") > 0:
                current_str = read_url[prev_tr : prev_tr + read_url.find("</tr>")]
                current_str = current_str[
                    current_str.find("<a href") : current_str.find("<a href") + current_str.find("</a>")
                ]
                current_str = current_str[
                    current_str.find('="') + 2 : current_str.find('="') + 2 + current_str.find('">')
                ]
                current_str = current_str[: current_str.find(">") - 1]
                if current_str.split("/")[-1] in ignore_list or current_str.split("/")[-2] in ignore_list:
                    self.rdmc.ui.printer("Ignoring url: %s\n" % current_str)
                else:
                    # data[current_str.split('/')[-1]] = [table_row_list.append(current_str)
                    table_row_list.append(current_str.split("/")[-1])

                read_url = read_url[read_url.find("</tr>") + 1 :]
                prev_tr = 0

            source_url.close()

            if components:
                components_dict = {}

                while len(table_row_list) > 0:
                    for url in table_row_list:
                        split_url = re.split("/", url)
                        last_element = split_url[-1]
                        if last_element.count(".") > 2:
                            sys.stderr.write("Invalid Filetype...skipping\n")
                            table_row_list.remove(url)
                            break
                        else:
                            (compname, ext) = last_element.split(".")
                            if "compsig" in last_element:
                                if components_dict.get(compname) is not None and compname in last_element:
                                    components_dict[compname].append(url)
                                    table_row_list.remove(url)
                                    continue
                            if "part" in last_element and "_" in last_element:
                                (split_compname, _) = compname.split("_")
                                if split_compname in components_dict and url not in components_dict[split_compname]:
                                    components_dict[split_compname].append(url)
                                    table_row_list.remove(url)
                                else:
                                    components_dict.setdefault(compname.split("_")[0], [])
                                continue
                            else:
                                components_dict.setdefault(compname, []).append(url)
                                table_row_list.remove(url)

                return components_dict

            else:
                return table_row_list

        except ValueError or TypeError:
            self.rdmc.ui.printer("The web server may not be available")
            block = True
        except Exception as excp:
            self.rdmc.ui.printer("A General Error Occured: %s" % excp)
            block = True

    def archive_handler(self, archive_file):
        """
        Handles archiving of data for bug tracking and reporting
        """

        packlist = [__error_logfile__, __pass_fail__]

        if self.rdmc.opts.debug:
            for handle in self.rdmc.app.logger.parent.handlers:
                if isinstance(handle, FileHandler):
                    ilorestlog = handle.baseFilename

        if ilorestlog:
            packlist.append(ilorestlog)

        with ZipFile(archive_file, "w") as zip_arch:
            for _file in packlist:
                try:
                    zip_arch.write(_file)
                    os.remove(_file)
                except:
                    pass

        self.rdmc.ui.printer("Logifles archived in '%s'.\n" % archive_file)
        zip_arch.printdir()

    def definearguments(self, customparser):
        """Wrapper function for new command main function

        :param customparser: command line input
        :type customparser: parser.
        """
        if not customparser:
            return

        self.cmdbase.add_login_arguments_group(customparser)

        customparser.add_argument(
            "--latestschema",
            dest="latestschema",
            action="store_true",
            help="Optionally use the latest schema instead of the one "
            "requested by the file. Note: May cause errors in some data "
            "retrieval due to difference in schema versions.",
            default=None,
        )
        customparser.add_argument(
            "--complete",
            dest="complete",
            action="store_true",
            help="Run all available tests.",
            default=False,
        )
        customparser.add_argument(
            "--sumtest",
            dest="sumtest",
            action="store_true",
            help="Optionally use run only the sum command tests.",
            default=False,
        )
        customparser.add_argument(
            "--local",
            dest="local",
            action="store_true",
            help="""Use to perform a local login for every operation.""",
            default=None,
        )
        customparser.add_argument(
            "--ahsdiagtest",
            dest="ahsdiagtest",
            action="store_true",
            help="Optionally use run only the sum command tests.",
            default=False,
        )
        customparser.add_argument(
            "--archive",
            dest="archive",
            help="Optionally archive the logfiles",
            action="append",
            default=None,
        )
