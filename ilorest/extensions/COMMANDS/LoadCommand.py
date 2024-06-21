###
# Copyright 2016-2023 Hewlett Packard Enterprise, Inc. All rights reserved.
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
""" Load Command for RDMC """

import json
import os
import shlex
import subprocess
import sys
from datetime import datetime

from six.moves import queue

import redfish.ris
from redfish.ris.rmc_helper import LoadSkipSettingError

try:
    from rdmc_helper import (
        Encryption,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        InvalidFileFormattingError,
        InvalidFileInputError,
        InvalidMSCfileInputError,
        MultipleServerConfigError,
        NoChangesFoundOrMadeError,
        ReturnCodes,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        Encryption,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        InvalidFileFormattingError,
        InvalidFileInputError,
        InvalidMSCfileInputError,
        MultipleServerConfigError,
        NoChangesFoundOrMadeError,
        ReturnCodes,
    )

try:
    from rdmc_helper import HARDCODEDLIST
except:
    from ilorest.rdmc_helper import HARDCODEDLIST

# default file name
__filename__ = "ilorest.json"


class LoadCommand:
    """Constructor"""

    def __init__(self):
        self.ident = {
            "name": "load",
            "usage": None,
            "description": "Run to load the default configuration"
            " file\n\texample: load\n\n\tLoad configuration file from a "
            "different file\n\tif any property values have changed, the "
            "changes are committed and the user is logged out of the server"
            "\n\n\texample: load -f output.json\n\n\tLoad configurations to "
            "multiple servers\n\texample: load -m mpfilename.txt -f output."
            "json\n\n\tNote: multiple server file format (1 server per new "
            "line)\n\t--url <iLO url/hostname> -u admin -p password\n\t--url"
            " <iLO url/hostname> -u admin -p password\n\t--url <iLO url/"
            "hostname> -u admin -p password",
            "summary": "Loads the server configuration settings from a file.",
            "aliases": [],
            "auxcommands": ["CommitCommand", "SelectCommand", "RawPatchCommand"],
        }
        self.filenames = None
        self.mpfilename = None
        self.queue = queue.Queue()
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def securebootremovereadonly(self, tmp):
        templist = [
            "SecureBootCurrentBoot",
            "@odata.etag",
            "Id",
            "AutoNeg",
            "FQDN",
            "FullDuplex",
            "HostName",
            "IPv6Addresses",
            "IPv6DefaultGateway",
            "LinkStatus",
            "MaxIPv6StaticAddresses",
            "Name",
            "NameServers",
            "PermanentMACAddress",
            "ConfigurationSettings",
            "InterfaceType",
            "NICSupportsIPv6",
            "DomainName",
            "IPV6",
            "DNSServers",
            "MACAddress",
            "VLAN",
            "SpeedMbps",
            "DateTime",
        ]
        remove_data = self.rdmc.app.removereadonlyprops(tmp, False, True, templist)
        return remove_data

    def run(self, line, help_disp=False):
        """Main load worker function

        :param line: command line input
        :type line: string.
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

        self.loadvalidation(options)
        returnvalue = False

        if options.mpfilename:
            self.rdmc.ui.printer("Loading configuration for multiple servers...\n")
        else:
            self.rdmc.ui.printer("Loading configuration...\n")

        for files in self.filenames:
            if not os.path.isfile(files):
                raise InvalidFileInputError(
                    "File '%s' doesn't exist. Please create file by running save command." % files
                )
            if options.encryption:
                with open(files, "rb") as myfile:
                    data = myfile.read()
                    data = Encryption().decrypt_file(data, options.encryption)
                    loadcontents = json.loads(data)
            else:
                try:
                    with open(files, "r") as myfile:
                        loadcontents = json.load(myfile)
                except:
                    raise InvalidFileFormattingError("Invalid file formatting found in file %s" % files)

            if options.mpfilename:
                mfile = options.mpfilename
                outputdir = None

                if options.outdirectory:
                    outputdir = options.outdirectory

                if self.runmpfunc(mpfile=mfile, lfile=files, outputdir=outputdir):
                    return ReturnCodes.SUCCESS
                else:
                    raise MultipleServerConfigError("One or more servers failed to load given configuration.")

            results = False
            eth_conf = False
            validation_errs = []

            for loadcontent in loadcontents:
                for content, loaddict in loadcontent.items():
                    inputlist = list()

                    if content == "Comments":
                        continue

                    if "EthernetInterface" in content:
                        if options.force_network_config:
                            import platform
                            import tempfile

                            patchpath = "/redfish/v1/Managers/1/EthernetInterfaces/1/"

                            try:
                                payload = loadcontent[content][patchpath]
                            except KeyError:
                                continue

                            payload = loadcontent[content][patchpath]
                            remove_odata = self.securebootremovereadonly(payload)
                            payload.update(remove_odata)
                            if "StaticNameServers" in payload:
                                payload["StaticNameServers"] = [
                                    item for item in payload["StaticNameServers"] if item != "::"
                                ]
                            tempdir = "/tmp" if platform.system() == "Darwin" else tempfile.gettempdir()
                            temp_file = os.path.join(tempdir, "temp_patch.json")
                            out_file = open(temp_file, "w")
                            patch_payload = {patchpath: payload}
                            json.dump(patch_payload, out_file, indent=6)
                            out_file.close()
                            self.auxcommands["rawpatch"].run(temp_file + " --service")
                            os.remove(temp_file)
                            eth_conf = True
                            continue
                        else:
                            self.rdmc.ui.printer(
                                "Skipping network configurations as" " --force_network_config is not included.\n"
                            )
                            continue

                    inputlist.append(content)
                    if options.biospassword:
                        inputlist.extend(["--biospassword", options.biospassword])

                    self.auxcommands["select"].selectfunction(inputlist)
                    if self.rdmc.app.selector.lower() not in content.lower():
                        raise InvalidCommandLineError("Selector not found.\n")

                    try:
                        for _, items in loaddict.items():
                            remove_odata = self.securebootremovereadonly(items)
                            items.update(remove_odata)
                            try:
                                if self.rdmc.app.loadset(
                                    seldict=items,
                                    latestschema=options.latestschema,
                                    uniqueoverride=options.uniqueoverride,
                                ):
                                    results = True
                            except LoadSkipSettingError:
                                returnvalue = True
                                results = True
                            except:
                                raise
                    except redfish.ris.ValidationError as excp:
                        errs = excp.get_errors()
                        validation_errs.append({self.rdmc.app.selector: errs})
                    except:
                        raise

            try:
                if results:
                    self.auxcommands["commit"].commitfunction(options=options)
                    reboot_needed = False
                    for n in inputlist:
                        n = n.lower()
                        if "bios" in n or "boot" in n or "iscsi" in n:
                            reboot_needed = True
                    if reboot_needed:
                        self.rdmc.ui.printer("Reboot is required for settings to take effect.\n")
            except NoChangesFoundOrMadeError as excp:
                if returnvalue:
                    pass
                else:
                    raise excp

            if validation_errs:
                for validation_err in validation_errs:
                    for err_type in validation_err:
                        self.rdmc.ui.error("Validation error(s) in type %s:\n" % err_type)
                        for err in validation_err[err_type]:
                            if isinstance(err, redfish.ris.RegistryValidationError):
                                self.rdmc.ui.error(err.message)
                                try:
                                    if err.reg:
                                        self.rdmc.ui.error(str(err.sel))
                                except:
                                    pass
                raise redfish.ris.ValidationError()

            if not results:
                if eth_conf:
                    continue
                else:
                    self.rdmc.ui.printer("No differences found from current configuration.\n")

        # Return code
        if returnvalue:
            return ReturnCodes.LOAD_SKIP_SETTING_ERROR

        return ReturnCodes.SUCCESS

    def loadvalidation(self, options):
        """Load method validation function

        :param options: command line options
        :type options: list.
        """

        if self.rdmc.opts.latestschema:
            options.latestschema = True

        try:
            self.cmdbase.login_validation(self, options)
        except Exception:
            if options.mpfilename:
                pass
            else:
                raise

        # filename validations and checks
        if options.filename:
            self.filenames = options.filename
        elif self.rdmc.config:
            if self.rdmc.config.defaultloadfilename:
                self.filenames = [self.rdmc.config.defaultloadfilename]

        if not self.filenames:
            self.filenames = [__filename__]

    def verify_file(self, filedata, inputfile):
        """Function used to handle oddly named files and convert to JSON

        :param filedata: input file data
        :type filedata: string.
        :param inputfile: current input file
        :type inputfile: string.
        """
        try:
            tempholder = json.loads(filedata)
            return tempholder
        except:
            raise InvalidFileFormattingError("Invalid file formatting found in file %s" % inputfile)

    def get_current_selector(self, path=None):
        """Returns current selected content minus hard coded list

        :param path: current path
        :type path: string.
        """
        contents = self.rdmc.app.monolith.path[path]

        if not contents:
            contents = list()

        for content in contents:
            for k in list(content.keys()):
                if k.lower() in HARDCODEDLIST or "@odata" in k.lower():
                    del content[k]

        return contents

    def runmpfunc(self, mpfile=None, lfile=None, outputdir=None):
        """Main worker function for multi file command

        :param mpfile: configuration file
        :type mpfile: string.
        :param lfile: custom file name
        :type lfile: string.
        :param outputdir: custom output directory
        :type outputdir: string.
        """
        # self.logoutobj.run("")
        data = self.validatempfile(mpfile=mpfile, lfile=lfile)

        if not data:
            return False

        processes = []
        finalreturncode = True
        outputform = "%Y-%m-%d-%H-%M-%S"

        if outputdir:
            if outputdir.endswith(('"', "'")) and outputdir.startswith(('"', "'")):
                outputdir = outputdir[1:-1]

            if not os.path.isdir(outputdir):
                self.rdmc.ui.error("The give output folder path does not exist.\n")
                raise InvalidCommandLineErrorOPTS("")

            dirpath = outputdir
        else:
            dirpath = os.getcwd()

        dirname = "%s_%s" % (datetime.now().strftime(outputform), "MSClogs")
        createdir = os.path.join(dirpath, dirname)
        os.mkdir(createdir)

        oofile = open(os.path.join(createdir, "CompleteOutputfile.txt"), "w+")
        self.rdmc.ui.printer("Create multiple processes to load configuration " "concurrently to all servers...\n")

        while True:
            if not self.queue.empty():
                line = self.queue.get()
            else:
                break

            finput = "\n" + "Output for " + line[line.index("--url") + 1] + ": \n\n"
            urlvar = line[line.index("--url") + 1]

            if "python" in os.path.basename(sys.executable.lower()):
                # If we are running from source we have to add the python file to the command
                listargforsubprocess = [sys.executable, sys.argv[0]] + line
            else:
                listargforsubprocess = [sys.executable] + line

            if os.name != "nt":
                listargforsubprocess = " ".join(listargforsubprocess)

            urlfilename = urlvar.split("//")[-1]
            logfile = open(os.path.join(createdir, urlfilename + ".txt"), "w+")
            pinput = subprocess.Popen(listargforsubprocess, shell=True, stdout=logfile, stderr=logfile)

            processes.append((pinput, finput, urlfilename, logfile))

        for pinput, finput, urlfilename, logfile in processes:
            pinput.wait()
            returncode = pinput.returncode
            finalreturncode = finalreturncode and not returncode

            logfile.close()
            logfile = open(os.path.join(createdir, urlfilename + ".txt"), "r+")
            oofile.write(finput + str(logfile.read()))
            oofile.write("-x+x-" * 16)
            logfile.close()

            if returncode == 0:
                self.rdmc.ui.printer("Loading Configuration for {} : SUCCESS\n".format(urlfilename))
            else:
                self.rdmc.ui.error("Loading Configuration for {} : FAILED\n".format(urlfilename))
                self.rdmc.ui.error(
                    "ILOREST return code : {}.\nFor more details please check "
                    "{}.txt under {} directory.\n".format(returncode, urlfilename, createdir)
                )

        oofile.close()

        if finalreturncode:
            self.rdmc.ui.printer("All servers have been successfully configured.\n")

        return finalreturncode

    def validatempfile(self, mpfile=None, lfile=None):
        """Validate temporary file

        :param mpfile: configuration file
        :type mpfile: string.
        :param lfile: custom file name
        :type lfile: string.
        """
        self.rdmc.ui.printer("Checking given server information...\n")

        if not mpfile:
            return False

        if not os.path.isfile(mpfile):
            raise InvalidFileInputError(
                "File '%s' doesn't exist, please " "create file by running save command." % mpfile
            )

        try:
            with open(mpfile, "r") as myfile:
                data = list()
                cmdtorun = ["load"]
                cmdargs = ["-f", str(lfile)]
                globalargs = ["-v", "--nocache"]

                while True:
                    line = myfile.readline()

                    if not line:
                        break

                    if line.endswith(os.linesep):
                        line.rstrip(os.linesep)

                    args = shlex.split(line, posix=False)

                    if len(args) < 5:
                        self.rdmc.ui.error("Incomplete data in input file: {}\n".format(line))
                        raise InvalidMSCfileInputError("Please verify the " "contents of the %s file" % mpfile)
                    else:
                        linelist = globalargs + cmdtorun + args + cmdargs
                        line = str(line).replace("\n", "")
                        self.queue.put(linelist)
                        data.append(linelist)
        except Exception as excp:
            raise excp

        if data:
            return data

        return False

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
            help="Use this flag if you wish to use a different"
            " filename than the default one. The default filename is"
            " %s." % __filename__,
            action="append",
            default=None,
        )
        customparser.add_argument(
            "-m",
            "--multiprocessing",
            dest="mpfilename",
            help="""use the provided filename to obtain data""",
            default=None,
        )
        customparser.add_argument(
            "--outputdirectory",
            dest="outdirectory",
            help="""use the provided directory to output data for multiple server configuration""",
            default=None,
        )
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
            "--uniqueoverride",
            dest="uniqueoverride",
            action="store_true",
            help="Override the measures stopping the tool from writing " "over items that are system unique.",
            default=False,
        )
        customparser.add_argument(
            "--encryption",
            dest="encryption",
            help="Optionally include this flag to encrypt/decrypt a file " "using the key provided.",
            default=None,
        )
        customparser.add_argument(
            "--reboot",
            dest="reboot",
            help="Use this flag to perform a reboot command function after"
            " completion of operations.  For help with parameters and"
            " descriptions regarding the reboot flag, run help reboot.",
            default=None,
        )
        customparser.add_argument(
            "--force_network_config",
            dest="force_network_config",
            help="Use this flag to force set network configuration."
            "Network settings will be skipped if the flag is not included.",
            action="store_true",
            default=None,
        )
