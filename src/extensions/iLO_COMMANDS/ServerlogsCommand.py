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
""" Log Operations Command for rdmc """

import ctypes
import datetime
import itertools
import json
import os
import platform
import shlex
import string
import subprocess
import sys
import tempfile
import time

from six.moves import queue

import redfish.hpilo.risblobstore2 as risblobstore2
from redfish.rest.connections import SecurityStateError
from redfish.ris.utils import filter_output

try:
    from rdmc_helper import (
        LOGGER,
        UI,
        IncompatibleiLOVersionError,
        InvalidCListFileError,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        InvalidFileInputError,
        InvalidKeyError,
        InvalidMSCfileInputError,
        MultipleServerConfigError,
        NoContentsFoundForOperationError,
        PartitionMoutingError,
        ReturnCodes,
        UnabletoFindDriveError,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        LOGGER,
        UI,
        IncompatibleiLOVersionError,
        InvalidCListFileError,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        InvalidFileInputError,
        InvalidKeyError,
        InvalidMSCfileInputError,
        MultipleServerConfigError,
        NoContentsFoundForOperationError,
        PartitionMoutingError,
        ReturnCodes,
        UnabletoFindDriveError,
    )

if os.name == "nt":
    import win32api
elif sys.platform != "darwin" and "VMkernel" not in platform.uname():
    import pyudev


class ServerlogsCommand:
    """Download logs from the server that is currently logged in"""

    def __init__(self):
        self.ident = {
            "name": "serverlogs",
            "usage": None,
            "description": "Download the AHS"
            " logs from the logged in server.\n\texample: serverlogs "
            "--selectlog=AHS \n\n\tClear the AHS logs "
            "from the logged in server.\n\texample: serverlogs "
            "--selectlog=AHS --clearlog\n\n\tDownload the IEL"
            " logs from the logged in server.\n\texample: serverlogs "
            "--selectlog=IEL -f IELlog.txt\n\n\tClear the IEL logs "
            "from the logged in server.\n\texample: serverlogs "
            "--selectlog=IEL --clearlog\n\n\tDownload the IML"
            " logs from the logged in server.\n\texample: serverlogs "
            "--selectlog=IML -f IMLlog.txt\n\n\tClear the IML logs "
            "from the logged in server.\n\texample: serverlogs "
            "--selectlog=IML --clearlog\n\n\t(IML LOGS ONLY FEATURE)"
            "\n\tInsert entry in the IML logs from the logged in "
            'server.\n\texample: serverlogs --selectlog=IML -m "Text'
            ' message for maintenance"\n\n\tDownload the iLO Security'
            " logs from the logged in server.\n\texample: serverlogs "
            "--selectlog=SL -f SLlog.txt\n\n\tClear the iLO Security logs "
            "from the logged in server.\n\texample: serverlogs "
            "--selectlog=SL --clearlog\n\n\tDownload logs from multiple servers"
            "\n\texample: serverlogs --mpfile mpfilename.txt -o output"
            "directorypath --mplog=IEL,IML\n\n\tNote: multiple server file "
            "format (1 server per new line)\n\t--url <iLO url/hostname> "
            "-u admin -p password\n\t--url <iLO url/hostname> -u admin -"
            "p password\n\t--url <iLO url/hostname> -u admin -p password"
            "\n\n\tInsert customised string "
            "if required for AHS\n\texample: serverlogs --selectlog="
            'AHS --customiseAHS "from=2014-03-01&&to=2014'
            '-03-30"\n\n\t(AHS LOGS ONLY FEATURE)\n\tInsert the location/'
            "path of directory where AHS log needs to be saved."
            " \n\texample: serverlogs --selectlog=AHS "
            "--directorypath=C:\\Python38\\DataFiles\n\n\tRepair IML log."
            "\n\texample: serverlogs --selectlog=IML --repair IMLlogID",
            "summary": "Download and perform log operations.",
            "aliases": ["logservices"],
            "auxcommands": [],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()
        self.dontunmount = None
        self.queue = queue.Queue()
        self.abspath = None
        self.lib = None

    def run(self, line, help_disp=False):
        """Main serverlogs function

        :param line: string of arguments passed in
        :type line: str.
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

        if not getattr(options, "sessionid", False):
            self.serverlogsvalidation(options)

        if options.mpfilename:
            self.rdmc.ui.printer("Downloading logs for multiple servers...\n")
            return self.gotompfunc(options)

        self.serverlogsworkerfunction(options)

        self.cmdbase.logout_routine(self, options)
        # Return code
        return ReturnCodes.SUCCESS

    def serverlogsworkerfunction(self, options):
        """ "Main worker function outlining the process

        :param options: command line options
        :type options: list.
        """
        if not options.service:
            raise InvalidCommandLineError("Please select a log type using the --selectlog option.")

        if options.service.lower() == "iml":
            path = self.returnimlpath(options=options)
        elif options.service.lower() == "iel":
            path = self.returnielpath(options=options)
        elif options.service.lower() == "sl":
            path = self.returnslpath(options=options)
        elif options.service.lower() == "ahs" and options.filter:
            raise InvalidCommandLineError("Cannot filter AHS logs.")
        elif (
            options.service.lower() == "ahs"
            and (not self.rdmc.app.typepath.url or self.rdmc.app.typepath.url.startswith("blobstore"))
            and not options.clearlog
        ):
            if options.customiseAHS is not None:
                current_date = str(datetime.datetime.now()).split()[0]
                date_check = options.customiseAHS
                from_date = date_check.split("&")[0].split("=")[1]
                to_date = date_check.split("to")[-1].split("=")[-1]
                if to_date < from_date or from_date > current_date:
                    raise InvalidCommandLineError("Please provide valid date to customiseAHS")
            self.downloadahslocally(options=options)
            return
        elif options.service.lower() == "ahs":
            path = self.returnahspath(options)
        else:
            raise InvalidCommandLineError("Log opted does not exist!")

        data = None

        if options.clearlog:
            self.clearlog(path)
        elif options.mainmes:
            self.addmaintenancelogentry(options, path=path)
        elif options.repiml:
            self.repairlogentry(options, path=path)
        else:
            data = self.downloaddata(path=path, options=options)

        self.savedata(options=options, data=data)

    def gotompfunc(self, options):
        """ "Function to download logs from multiple servers concurrently

        :param options: command line options
        :type options: list.
        """
        if options.mpfilename:
            mfile = options.mpfilename
            outputdir = None

            if options.outdirectory:
                outputdir = options.outdirectory

            if self.runmpfunc(mpfile=mfile, outputdir=outputdir, options=options):
                return ReturnCodes.SUCCESS
            else:
                raise MultipleServerConfigError("One or more servers failed to download logs.")

    def runmpfunc(self, mpfile=None, outputdir=None, options=None):
        """Main worker function for multi file command

        :param mpfile: configuration file
        :type mpfile: string.
        :param outputdir: custom output directory
        :type outputdir: string.
        """
        self.logoutobj.run("")
        LOGGER.info("Validating input server collection file.")
        data = self.validatempfile(mpfile=mpfile, options=options)

        if not data:
            return False

        processes = []
        finalreturncode = True
        outputform = "%Y-%m-%d-%H-%M-%S"

        if outputdir:
            if outputdir.endswith(('"', "'")) and outputdir.startswith(('"', "'")):
                outputdir = outputdir[1:-1]

            if not os.path.isdir(outputdir):
                raise InvalidCommandLineError("The given output folder path does not exist.")

            dirpath = outputdir
        else:
            dirpath = os.getcwd()

        dirname = "%s_%s" % (datetime.datetime.now().strftime(outputform), "MSClogs")
        createdir = os.path.join(dirpath, dirname)
        os.mkdir(createdir)

        oofile = open(os.path.join(createdir, "CompleteOutputfile.txt"), "w+")
        self.rdmc.ui.printer("Creating multiple processes to load configuration " "concurrently to all servers...\n")

        while True:
            if not self.queue.empty():
                line = self.queue.get()
            else:
                break

            finput = "\n" + "Output for " + line[line.index("--url") + 1] + ": \n\n"
            urlvar = line[line.index("--url") + 1]
            urlfilename = urlvar.split("//")[-1]
            line[line.index("-f") + 1] = str(line[line.index("-f") + 1]) + urlfilename

            if "python" in os.path.basename(sys.executable.lower()):
                # If we are running from source we have to add the python file to the command
                listargforsubprocess = [sys.executable, sys.argv[0]] + line
            else:
                listargforsubprocess = [sys.executable] + line

            if os.name != "nt":
                listargforsubprocess = " ".join(listargforsubprocess)

            logfile = open(os.path.join(createdir, urlfilename + ".txt"), "w+")
            pinput = subprocess.Popen(listargforsubprocess, shell=True, stdout=logfile, stderr=logfile)

            processes.append((pinput, finput, urlvar, logfile))

        for pinput, finput, urlvar, logfile in processes:
            pinput.wait()
            returncode = pinput.returncode
            finalreturncode = finalreturncode and not returncode

            logfile.close()
            logfile = open(os.path.join(createdir, urlvar + ".txt"), "r+")
            oofile.write(finput + str(logfile.read()))
            oofile.write("-x+x-" * 16)
            logfile.close()

            if returncode == 0:
                self.rdmc.ui.printer("Loading Configuration for {} : SUCCESS\n".format(urlvar))
            else:
                self.rdmc.ui.error("Loading Configuration for {} : FAILED\n".format(urlvar))
                self.rdmc.ui.error(
                    "ILOREST return code : {}.\nFor more details please check {}"
                    ".txt under {} directory.\n".format(returncode, urlvar, createdir)
                )

        oofile.close()

        if finalreturncode:
            self.rdmc.ui.printer("All servers have been successfully configured.\n")

        return finalreturncode

    def validatempfile(self, mpfile=None, options=None):
        """Validate temporary file

        :param mpfile: configuration file
        :type mpfile: string.
        :param lfile: custom file name
        :type lfile: string.
        """
        self.rdmc.ui.printer("Checking given server information...\n")

        if not mpfile:
            return False
        elif mpfile.startswith(('"', "'")) and mpfile[0] == mpfile[-1]:
            mpfile = mpfile[1:-1]

        if not os.path.isfile(mpfile) or not options.mplog:
            raise InvalidFileInputError(
                "File '%s' doesn't exist, please " "create file by running save command." % mpfile
            )

        logs = self.checkmplog(options)

        try:
            with open(mpfile, "r") as myfile:
                data = list()
                cmdtorun = ["serverlogs"]
                globalargs = ["-v", "--nocache"]

                while True:
                    line = myfile.readline()
                    if not line:
                        break

                    for logval in logs:
                        cmdargs = ["--selectlog=" + str(logval), "-f", str(logval)]
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
            LOGGER.info("%s", str(excp))
            raise excp

        if data:
            return data

        return False

    def checkmplog(self, options):
        """Function to validate mplogs options

        :param options: command line options
        :type options: list.
        """
        if options.mplog:
            logs = str(options.mplog)
            if "," in logs:
                logs = logs.split(",")
                return logs
            if logs in ("all", "IEL", "IML", "AHS"):
                if logs == "all":
                    logs = ["IEL", "IML", "AHS"]
                else:
                    logs = [logs]
                return logs
        raise InvalidCommandLineError("Error in mplogs options")

    def addmaintenancelogentry(self, options, path=None):
        """Worker function to add maintenance log

        :param options: command line options
        :type options: list.
        :param path: path to post maintenance log
        :type path: str
        """
        LOGGER.info("Adding maintenance logs")
        if options.mainmes is None:
            raise InvalidCommandLineError("")

        if options.service != "IML":
            raise InvalidCommandLineError("Log opted cannot make maintenance entries!")

        message = options.mainmes

        if message.endswith(('"', "'")) and message.startswith(('"', "'")):
            message = message[1:-1]

        if path:
            bodydict = dict()
            bodydict["path"] = path
            bodydict["body"] = {"EntryCode": "Maintenance", "Message": message}

            LOGGER.info(
                "Writing maintenance post to %s with %s",
                str(path),
                str(bodydict["body"]),
            )

            self.rdmc.app.post_handler(path, bodydict["body"])

    def repairlogentry(self, options, path=None):
        """Worker function to repair maintenance log

        :param options: command line options
        :type options: list.
        :param path: path of IML log Entries
        :type path: str
        """
        if options.repiml is None or (options.clearlog and options.repiml):
            raise InvalidCommandLineError("")

        if options.service != "IML":
            raise InvalidCommandLineError("Log opted cannot repair maintenance entries.")

        imlid = options.repiml

        if imlid.endswith(('"', "'")) and imlid.startswith(('"', "'")):
            imlid = imlid[1:-1]

        if path:
            imlidpath = [path if path[-1] == "/" else path + "/"][0] + str(imlid) + "/"
            bodydict = dict()
            bodydict["path"] = imlidpath
            if self.rdmc.app.typepath.defs.isgen9:
                bodydict["body"] = {"Oem": {"Hp": {"Repaired": True}}}
            else:
                bodydict["body"] = {"Oem": {"Hpe": {"Repaired": True}}}
            LOGGER.info(
                "Repairing maintenance log at %s with %s",
                str(imlidpath),
                str(bodydict["body"]),
            )

            self.rdmc.app.patch_handler(imlidpath, bodydict["body"])

    def clearlog(self, path):
        """Worker function to clear logs.

        :param path: path to post clear log action
        :type path: str
        """
        LOGGER.info("Clearing logs.")
        if path and self.rdmc.app.typepath.defs.isgen9:
            if path.endswith("/Entries"):
                path = path[: -len("/Entries")]
            elif path.endswith("Entries/"):
                path = path[: -len("Entries/")]

            bodydict = dict()
            bodydict["path"] = path
            bodydict["body"] = {"Action": "ClearLog"}
            self.rdmc.app.post_handler(path, bodydict["body"])
        elif path:
            action = path.split("/")[-2]
            bodydict = dict()
            bodydict["path"] = path
            bodydict["body"] = {"Action": action}
            self.rdmc.app.post_handler(path, bodydict["body"])

    def downloaddata(self, path=None, options=None):
        """Worker function to download the log files

        :param options: command line options
        :type options: list.
        :param path: path to download logs
        :type path: str
        """
        if path:
            LOGGER.info("Getting data from %s", str(path))
            if options.service == "AHS":
                data = self.rdmc.app.get_handler(path, silent=True, uncache=True)
                if data:
                    return data.ori
                else:
                    raise NoContentsFoundForOperationError("Unable to retrieve AHS logs.")
            else:
                data = self.rdmc.app.get_handler(path, silent=True)

            datadict = data.dict

            try:
                completedatadictlist = datadict["Items"] if "Items" in datadict else datadict["Members"]
            except:
                self.rdmc.ui.error("No data available within log.\n")
                raise NoContentsFoundForOperationError("Unable to retrieve logs.")

            if self.rdmc.app.typepath.defs.flagforrest:
                morepages = True

                while morepages:
                    if "links" in datadict and "NextPage" in datadict["links"]:
                        next_link_uri = path + "?page=" + str(datadict["links"]["NextPage"]["page"])

                        href = "%s" % next_link_uri
                        data = self.rdmc.app.get_handler(href, silent=True)
                        datadict = data.dict

                        try:
                            completedatadictlist = completedatadictlist + datadict["Items"]
                        except:
                            self.rdmc.ui.error("No data available within log.\n")
                            raise NoContentsFoundForOperationError("Unable to retrieve logs.")
                    else:
                        morepages = False
            else:
                datadict = list()

                for members in completedatadictlist:
                    if len(list(members.keys())) == 1:
                        memberpath = members[self.rdmc.app.typepath.defs.hrefstring]
                        data = self.rdmc.app.get_handler(memberpath, silent=True)
                        datadict = datadict + [data.dict]
                    else:
                        datadict = datadict + [members]
                completedatadictlist = datadict

            if completedatadictlist:
                try:
                    return completedatadictlist
                except Exception:
                    self.rdmc.ui.error("Could not get the data from server.\n")
                    raise NoContentsFoundForOperationError("Unable to retrieve logs.")
            else:
                self.rdmc.ui.error("No log data present.\n")
                raise NoContentsFoundForOperationError("Unable to retrieve logs.")
        else:
            self.rdmc.ui.error("Path not found for input log.\n")
            raise NoContentsFoundForOperationError("Unable to retrieve logs.")

    def returnimlpath(self, options=None):
        """Return the requested path of the IML logs

        :param options: command line options
        :type options: list.
        """
        LOGGER.info("Obtaining IML path for download.")
        path = ""
        val = "/redfish/v1/Systems/1/LogServices/IML/"
        filtereddatainstance = self.rdmc.app.get_handler(val, silent=True).dict

        try:
            filtereddictslists = filtereddatainstance
            if not filtereddictslists:
                raise NoContentsFoundForOperationError("Unable to retrieve instance.")
            # for filtereddict in filtereddictslists:
            if filtereddictslists["Name"] == "Integrated Management Log":
                if options.clearlog:
                    if self.rdmc.app.typepath.defs.flagforrest:
                        linkpath = filtereddictslists["links"]
                        selfpath = linkpath["self"]
                        path = selfpath["href"]
                    elif self.rdmc.app.typepath.defs.isgen9:
                        path = filtereddictslists[self.rdmc.app.typepath.defs.hrefstring]
                    else:
                        actiondict = filtereddictslists["Actions"]
                        clearkey = [x for x in actiondict if x.endswith("ClearLog")]
                        path = actiondict[clearkey[0]]["target"]
                else:
                    linkpath = filtereddictslists["links"] if "links" in filtereddictslists else filtereddictslists
                    dictpath = linkpath["Entries"]
                    dictpath = dictpath[0] if isinstance(dictpath, list) else dictpath
                    path = dictpath[self.rdmc.app.typepath.defs.hrefstring]
            if not path:
                raise NoContentsFoundForOperationError("Unable to retrieve logs.")
        except NoContentsFoundForOperationError as excp:
            raise excp
        except Exception:
            self.rdmc.ui.error("No path found for the entry.\n")
            raise NoContentsFoundForOperationError("Unable to retrieve logs.")

        if self.rdmc.opts.verbose:
            self.rdmc.ui.printer(str(path) + "\n")

        return path

    def returnielpath(self, options=None):
        """Return the requested path of the IEL logs

        :param options: command line options
        :type options: list.
        """
        LOGGER.info("Obtaining IEL path for download.")
        path = ""
        val = "/redfish/v1/Managers/1/LogServices/IEL/"
        filtereddatainstance = self.rdmc.app.get_handler(val, silent=True).dict

        try:
            filtereddictslists = filtereddatainstance
            if not filtereddictslists:
                raise NoContentsFoundForOperationError("Unable to retrieve instance.")
            # for filtereddict in filtereddictslists:
            if filtereddictslists["Name"] == "iLO Event Log":
                if options.clearlog:
                    if self.rdmc.app.typepath.defs.flagforrest:
                        linkpath = filtereddictslists["links"]
                        selfpath = linkpath["self"]
                        path = selfpath["href"]
                    elif self.rdmc.app.typepath.defs.isgen9:
                        path = filtereddictslists[self.rdmc.app.typepath.defs.hrefstring]
                    else:
                        actiondict = filtereddictslists["Actions"]
                        clearkey = [x for x in actiondict if x.endswith("ClearLog")]
                        path = actiondict[clearkey[0]]["target"]
                else:
                    linkpath = filtereddictslists["links"] if "links" in filtereddictslists else filtereddictslists
                    dictpath = linkpath["Entries"]
                    dictpath = dictpath[0] if isinstance(dictpath, list) else dictpath
                    path = dictpath[self.rdmc.app.typepath.defs.hrefstring]

            if not path:
                raise NoContentsFoundForOperationError("Unable to retrieve logs.")
        except NoContentsFoundForOperationError as excp:
            raise excp
        except Exception:
            self.rdmc.ui.error("No path found for the entry.\n")
            raise NoContentsFoundForOperationError("Unable to retrieve logs.")

        if self.rdmc.opts.verbose:
            self.rdmc.ui.printer(str(path) + "\n")

        return path

    def returnslpath(self, options=None):
        """Return the requested path of the SL logs

        :param options: command line options
        :type options: list.
        """

        if not self.rdmc.app.typepath.defs.isgen10 or not self.rdmc.app.getiloversion() >= 5.210:
            raise IncompatibleiLOVersionError("Security logs are only available on iLO 5 2.10 or" " greater.")
        LOGGER.info("Obtaining SL path for download.")
        path = ""
        val = "/redfish/v1/Systems/1/LogServices/SL/"
        filtereddatainstance = self.rdmc.app.get_handler(val, silent=True).dict

        try:
            filtereddictslists = filtereddatainstance
            if not filtereddictslists:
                raise NoContentsFoundForOperationError("Unable to retrieve instance.")
            # for filtereddict in filtereddictslists:
            if filtereddictslists["Id"] == "SL":
                if options.clearlog:
                    actiondict = filtereddictslists["Actions"]
                    clearkey = [x for x in actiondict if x.endswith("ClearLog")]
                    path = actiondict[clearkey[0]]["target"]
                else:
                    dictpath = filtereddictslists["Entries"]
                    dictpath = dictpath[0] if isinstance(dictpath, list) else dictpath
                    path = dictpath[self.rdmc.app.typepath.defs.hrefstring]

            if not path:
                raise NoContentsFoundForOperationError("Unable to retrieve logs.")
        except NoContentsFoundForOperationError as excp:
            raise excp
        except Exception:
            self.rdmc.ui.error("No path found for the entry.\n")
            raise NoContentsFoundForOperationError("Unable to retrieve logs.")

        if self.rdmc.opts.verbose:
            self.rdmc.ui.printer(str(path) + "\n")

        return path

    def returnahspath(self, options):
        """Return the requested path of the AHS logs

        :param options: command line options
        :type options: list.
        """
        LOGGER.info("Obtaining AHS path for download.")
        path = ""

        if options.filename:
            raise InvalidCommandLineError(
                "AHS logs must be downloaded with " "default name. Please re-run command without filename option."
            )

        val = "/redfish/v1/Managers/1/ActiveHealthSystem/"
        filtereddatainstance = self.rdmc.app.get_handler(val, silent=True).dict

        try:
            filtereddictslists = filtereddatainstance

            if not filtereddictslists:
                raise NoContentsFoundForOperationError("Unable to retrieve log instance.")

            # for filtereddict in filtereddictslists:
            if options.clearlog:
                if self.rdmc.app.typepath.defs.flagforrest:
                    linkpath = filtereddictslists["links"]
                    selfpath = linkpath["self"]
                    path = selfpath["href"]
                elif self.rdmc.app.typepath.defs.isgen9:
                    path = filtereddictslists[self.rdmc.app.typepath.defs.hrefstring]
                else:
                    actiondict = filtereddictslists["Actions"]
                    clearkey = [x for x in actiondict if x.endswith("ClearLog")]
                    path = actiondict[clearkey[0]]["target"]
            else:
                linkpath = filtereddictslists["links"] if "links" in filtereddictslists else filtereddictslists["Links"]

                ahslocpath = linkpath["AHSLocation"]
                path = ahslocpath["extref"]
                weekpath = None

                if options.downloadallahs:
                    path = path
                elif options.customiseAHS:
                    custr = options.customiseAHS
                    if custr.startswith(("'", '"')) and custr.endswith(("'", '"')):
                        custr = custr[1:-1]

                    if custr.startswith("from="):
                        path = path.split("downloadAll=1")[0]

                    path = path + custr
                else:
                    if "RecentWeek" in list(linkpath.keys()):
                        weekpath = linkpath["RecentWeek"]["extref"]
                    elif "AHSFileStart" in list(filtereddictslists.keys()):
                        enddate = filtereddictslists["AHSFileEnd"].split("T")[0]
                        startdate = filtereddictslists["AHSFileStart"].split("T")[0]

                        enddat = list(map(int, enddate.split("-")))
                        startdat = list(map(int, startdate.split("-")))

                        weekago = datetime.datetime.now() - datetime.timedelta(days=6)
                        weekagostr = list(map(int, (str(weekago).split()[0]).split("-")))

                        strdate = min(
                            max(
                                datetime.date(weekagostr[0], weekagostr[1], weekagostr[2]),
                                datetime.date(startdat[0], startdat[1], startdat[2]),
                            ),
                            datetime.date(enddat[0], enddat[1], enddat[2]),
                        )

                        aweekstr = "from=" + str(strdate) + "&&to=" + enddate
                    else:
                        week_ago = datetime.datetime.now() - datetime.timedelta(days=6)
                        aweekstr = (
                            "from=" + str(week_ago).split()[0] + "&&to=" + str(datetime.datetime.now()).split()[0]
                        )

                    path = path.split("downloadAll=1")[0]
                    path = weekpath if weekpath else path + aweekstr

            if not path:
                raise NoContentsFoundForOperationError("Unable to retrieve logs.")
        except NoContentsFoundForOperationError as excp:
            raise excp
        except Exception:
            self.rdmc.ui.error("No path found for the entry.\n")
            raise NoContentsFoundForOperationError("Unable to retrieve logs.")

        if self.rdmc.opts.verbose:
            self.rdmc.ui.printer(str(path) + "\n")

        return path

    def savedata(self, options=None, data=None):
        """Save logs into the specified filename

        :param options: command line options
        :type options: list.
        :param data: log data
        :type data: dict
        """
        LOGGER.info("Saving/Writing data...")
        if data:
            data = self.filterdata(data=data, tofilter=options.filter)
            if options.service == "AHS":
                filename = self.getahsfilename(options)

                with open(filename, "wb") as foutput:
                    foutput.write(data)
            elif options.filename:
                with open(options.filename[0], "w") as foutput:
                    if options.json:
                        foutput.write(str(json.dumps(data, indent=2, sort_keys=True)))
                    else:
                        foutput.write(str(json.dumps(data)))
            else:
                if options.json:
                    UI().print_out_json(data)
                else:
                    UI().print_out_human_readable(data)

    def downloadahslocally(self, options=None):
        """Download AHS logs locally

        :param options: command line options
        :type options: list.
        """
        try:
            self.downloadahslocalworker(options)
        except:
            self.unmountbb()
            raise
        return

    def downloadahslocalworker(self, options):
        """Worker function to download AHS logs locally

        :param options: command line options
        :type options: list.
        """
        LOGGER.info("Entering AHS local download functions...")
        self.dontunmount = True

        if self.rdmc.app.typepath.ilogen and self.rdmc.app.typepath.ilogen < 4:
            raise IncompatibleiLOVersionError("Need at least iLO 4 for this program to run!\n")

        if sys.platform == "darwin":
            raise InvalidCommandLineError("AHS loacal download is not supported on MacOS")
        elif "VMkernel" in platform.uname():
            raise InvalidCommandLineError("AHS loacal download is not supported on VMWare")

        if options.filename:
            raise InvalidCommandLineError(
                "AHS logs must be downloaded with default name! Re-run command without filename!"
            )

        secstate = risblobstore2.BlobStore2().get_security_state()
        # self.rdmc.ui.printer('Security State is {}...\n'.format(secstate))

        if isinstance(secstate, bytes):
            secstate = secstate.decode("utf-8")
        if isinstance(secstate, str):
            secstate = secstate.replace("\x00", "").strip()
        if secstate == "":
            secstate = 0
        self.rdmc.ui.printer("Security State is {}...\n".format(secstate))
        if int(secstate) > 3:
            raise SecurityStateError("AHS logs cannot be downloaded locally in high security state.\n")

        self.lib = risblobstore2.BlobStore2.gethprestchifhandle()

        self.rdmc.ui.printer("Mounting AHS partition...\n")

        try:
            (manual_ovr, abspath) = self.getbbabspath()
        except (PartitionMoutingError, IOError):
            self.mountbb()
            (manual_ovr, abspath) = self.getbbabspath()
            self.dontunmount = False

        LOGGER.info("Blackbox folder path:%s", ",".join(next(os.walk(abspath))[2]))
        if "data" not in abspath:
            self.abspath = os.path.join(abspath, "data")
        LOGGER.info("Blackbox data files path:%s", self.abspath)

        if self.rdmc.app.typepath.ilogen:
            self.updateiloversion()
        try:
            cfilelist = self.getclistfilelisting()
            allfiles = self.getfilenames(options=options, cfilelist=cfilelist)
            self.getdatfilelisting(cfilelist=cfilelist, allfile=allfiles)
            self.createahsfile(ahsfile=self.getahsfilename(options))
        except Exception as excp:
            raise PartitionMoutingError(
                "An exception occurred obtaining Blackbox data files. The directory may be empty: %s.\n" % excp
            )

        if not manual_ovr:
            self.unmountbb()
        else:
            self.unmountbb()
            self.manualunmountbb(abspath)

    def updateiloversion(self):
        """Update iloversion to create appropriate headers."""
        LOGGER.info("Updating iloversion to format data appropriately")
        self.lib.updateiloversion.argtypes = [ctypes.c_float]
        self.lib.updateiloversion(float("2." + str(self.rdmc.app.typepath.ilogen)))

    def createahsfile(self, ahsfile=None):
        """Create the AHS file

        :param ahsfile: ahsfilename
        :type ahsfile: str
        """
        LOGGER.info("Creating AHS file from the formatted data.")
        self.clearahsfile(ahsfile=ahsfile)
        self.lib.setAHSFilepath.argtypes = [ctypes.c_char_p]
        self.lib.setAHSFilepath(os.path.abspath(ahsfile).encode("utf-8", "ignore"))
        self.lib.setBBdatapath.argtypes = [ctypes.c_char_p]
        self.lib.setBBdatapath(self.abspath.encode("utf-8", "ignore"))
        self.lib.createAHSLogFile_G9()

    def clearahsfile(self, ahsfile=None):
        """Clear the ahslog file if already present in filesystem

        :param ahsfile: ahsfilename
        :type ahsfile: str
        """
        LOGGER.info("Clear redundant AHS file in current folder.")
        try:
            os.remove(ahsfile)
        except:
            pass

    def getdatfilelisting(self, cfilelist=None, allfile=None):
        """Create headers based on the AHS log files within blackbox

        :param cfilelist: configuration files in blackbox
        :type cfilelist: list of strings
        :param allfile: all files within blackbox
        :type allfile: list
        """
        LOGGER.info("Reading Blackbox to determine data files.")
        allfile = list(set(allfile) | set(cfilelist))
        LOGGER.info("Final filelist %s", str(allfile))
        for files in allfile:
            if files.startswith((".", "..")):
                continue

            bisrequiredfile = False

            if files.split(".")[0] in [x.split(".")[0] for x in cfilelist]:
                if files.endswith("bb"):
                    bisrequiredfile = True
                    self.lib.updatenfileoptions()

            self.lib.gendatlisting.argtypes = [
                ctypes.c_char_p,
                ctypes.c_bool,
                ctypes.c_uint,
            ]

            filesize = os.stat(os.path.join(self.abspath, files)).st_size
            self.lib.gendatlisting(files.encode("ascii", "ignore"), bisrequiredfile, filesize)

    def getfilenames(self, options=None, cfilelist=None):
        """Get all file names from the blackbox directory."""
        LOGGER.info("Obtaining all relevant file names from Blackbox.")
        datelist = list()
        allfiles = list()

        filenames = next(os.walk(self.abspath))[2]
        timenow = (str(datetime.datetime.now()).split()[0]).split("-")
        strdate = enddate = datetime.date(int(timenow[0]), int(timenow[1]), int(timenow[2]))

        if not options.downloadallahs and not options.customiseAHS:
            weekago = datetime.datetime.now() - datetime.timedelta(days=6)
            weekagostr = (str(weekago).split()[0]).split("-")
            strdate = datetime.date(int(weekagostr[0]), int(weekagostr[1]), int(weekagostr[2]))

        if options.customiseAHS:
            instring = options.customiseAHS
            if instring.startswith(("'", '"')) and instring.endswith(("'", '"')):
                instring = instring[1:-1]
            try:
                (strdatestr, enddatestr) = [e.split("-") for e in instring.split("from=")[-1].split("&&to=")]
                strdate = datetime.date(int(strdatestr[0]), int(strdatestr[1]), int(strdatestr[2]))
                enddate = datetime.date(int(enddatestr[0]), int(enddatestr[1]), int(enddatestr[2]))
            except Exception as excp:
                LOGGER.warning(excp)
                raise InvalidCommandLineError("Cannot parse customised AHSinput.")

        atleastonefile = False
        for files in list(filenames):
            if not files.endswith("bb"):
                # Check the logic for the non bb files
                allfiles.append(files)
                continue

            if options.downloadallahs:
                atleastonefile = True
            if files in ("ilo_boot_support.zbb", "sys_boot_support.zbb"):
                allfiles.append(files)
                filenames.append(files)
                LOGGER.info("%s, number of files%s", files, len(filenames))
                continue
            filenoext = files.rsplit(".", 1)[0]
            filesplit = filenoext.split("-")

            try:
                newdate = datetime.date(int(filesplit[1]), int(filesplit[2]), int(filesplit[3]))
                datelist.append(newdate)

                if (strdate <= newdate) and (newdate <= enddate) and not options.downloadallahs:
                    allfiles.append(files)
                    atleastonefile = True
            except:
                pass

        _ = [cfilelist.remove(fil) for fil in list(cfilelist) if fil not in filenames]

        if options.customiseAHS:
            for files in reversed(cfilelist):
                try:
                    filenoext = files.rsplit(".", 1)[0]
                    filesplit = filenoext.split("-")
                    newdate = datetime.date(int(filesplit[1]), int(filesplit[2]), int(filesplit[3]))
                    if not ((strdate <= newdate) and (newdate <= enddate)):
                        cfilelist.remove(files)
                except:
                    pass

        if options.downloadallahs:
            strdate = min(datelist) if datelist else strdate
            enddate = max(datelist) if datelist else enddate
        else:
            strdate = max(min(datelist), strdate) if datelist else strdate
            enddate = min(max(datelist), enddate) if datelist else enddate

        LOGGER.info("All filenames: %s; Download files: %s", str(filenames), str(allfiles))

        if atleastonefile:
            self.updateminmaxdate(strdate=strdate, enddate=enddate)
            return filenames if options.downloadallahs else allfiles
        else:
            raise NoContentsFoundForOperationError("No AHS log files found.")

    def updateminmaxdate(self, strdate=None, enddate=None):
        """Get the minimum and maximum date of files into header

        :param strdate: starting date of ahs logs
        :type strdate: dateime obj
        :param enddate: ending date of ahs logs
        :type enddate: datetime obj
        """
        LOGGER.info("Updating min and max dates for download.")
        self.lib.updateMinDate.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
        self.lib.updateMinDate(strdate.year, strdate.month, strdate.day)
        self.lib.updateMaxDate.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
        self.lib.updateMaxDate(enddate.year, enddate.month, enddate.day)

    def getclistfilelisting(self):
        """Get files present within clist.pkg ."""
        LOGGER.info("Getting all config files that are required.")
        sclistpath = os.path.join(self.abspath, "clist.pkg")
        cfilelist = []
        if os.path.isfile(sclistpath):
            cfile = open(sclistpath, "rb")
            data = cfile.read()

            if data == "":
                raise InvalidCListFileError("Could not read Cfile\n")

            sizeofcfile = len(str(data))
            sizeofrecord = self.lib.sizeofchifbbfilecfgrecord()
            count = sizeofcfile / sizeofrecord
            revcount = 0

            while count >= 1:
                dat = data[revcount * sizeofrecord : (revcount + 1) * sizeofrecord]
                dat = ctypes.create_string_buffer(dat)
                self.lib.getbbfilecfgrecordname.argtypes = [ctypes.c_char_p]
                self.lib.getbbfilecfgrecordname.restype = ctypes.c_char_p
                ptrname = self.lib.getbbfilecfgrecordname(dat)
                name = str(bytearray(ptrname[:32][:]))

                if name not in cfilelist:
                    cfilelist.append(name)

                count = count - 1
                revcount = revcount + 1
        else:
            cfilelist = [f for f in os.listdir(self.abspath) if f.endswith(".zbb")]

        LOGGER.info("CLIST files %s", str(cfilelist))
        return cfilelist

    def getbbabspath(self):
        """Get blackbox folder path."""
        LOGGER.info("Obtaining the absolute path of blackbox.")
        count = 0

        while count < 20:
            if os.name == "nt":
                drives = self.get_available_drives()

                for i in drives:
                    try:
                        label = win32api.GetVolumeInformation(i + ":")[0]

                        if label == "BLACKBOX":
                            abspathbb = i + ":\\data\\"
                            self.abspath = abspathbb
                            cfilelist = self.getclistfilelisting()
                            if not cfilelist:
                                self.unmountbb()
                                self.manualmountbb()
                            else:
                                return False, abspathbb
                    except:
                        pass
            else:
                with open("/proc/mounts", "r") as fmount:
                    while True:
                        lin = fmount.readline()

                        if len(lin.strip()) == 0:
                            break

                        if r"/BLACKBOX" in lin:
                            abspathbb = lin.split()[1]
                            self.abspath = abspathbb
                            cfilelist = self.getclistfilelisting()
                            if not cfilelist:
                                self.unmountbb()
                                self.manualmountbb()
                            else:
                                return False, abspathbb

                if count > 5:
                    found, path = self.manualmountbb()
                    if found:
                        return True, path

            count = count + 1
            time.sleep(5)

        raise PartitionMoutingError("iLO not responding to request " "for mounting AHS partition")

    def manualmountbb(self):
        """Manually mount blackbox when after fixed time."""
        LOGGER.info("Manually mounting the blackbox.")

        try:
            context = pyudev.Context()
            for device in context.list_devices(subsystem="block"):
                if device.get("ID_FS_LABEL") == "BLACKBOX":
                    dirpath = os.path.join(tempfile.gettempdir(), "BLACKBOX")

                    if not os.path.exists(dirpath):
                        try:
                            os.makedirs(dirpath)
                        except Exception as excp:
                            raise excp

                    pmount = subprocess.Popen(
                        ["mount", device.device_node, dirpath],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    )
                    _, _ = pmount.communicate()

                    return True, dirpath
        except UnicodeDecodeError as excp:
            self.unmountbb()
            raise UnabletoFindDriveError(excp)

        return False, None

    def manualunmountbb(self, dirpath):
        """Manually unmount blackbox when after fixed time

        :param dirpath: mounted directory path
        :type dirpath: str
        """
        LOGGER.info("Manually unmounting the blackbox.")
        pmount = subprocess.Popen(["umount", dirpath], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        _, _ = pmount.communicate()

    def mountbb(self):
        """Mount blackbox."""
        LOGGER.info("Mounting blackbox...")
        bs2 = risblobstore2.BlobStore2()
        bs2.mount_blackbox()
        bs2.channel.close()

    def unmountbb(self):
        """Unmount blacbox."""
        if not self.dontunmount:
            bs2 = risblobstore2.BlobStore2()
            bs2.bb_media_unmount()
            bs2.channel.close()

    def get_available_drives(self):
        """Obtain all drives"""
        LOGGER.info("Unmounting blackbox...")
        if "Windows" not in platform.system():
            return []

        drive_bitmask = ctypes.cdll.kernel32.GetLogicalDrives()

        return list(
            itertools.compress(
                string.ascii_uppercase,
                [ord(drive) - ord("0") for drive in bin(drive_bitmask)[:1:-1]],
            )
        )

    def filterdata(self, data=None, tofilter=None):
        """Filter the logs

        :param data: log data
        :type data: dict
        :param tofilter: command line filter option
        :type tofilter: str
        """
        LOGGER.info("Filtering logs based on requsted options.")
        if tofilter and data:
            try:
                if (str(tofilter)[0] == str(tofilter)[-1]) and str(tofilter).startswith(("'", '"')):
                    tofilter = tofilter[1:-1]

                (sel, val) = tofilter.split("=")
                sel = sel.strip()
                val = val.strip()

                if val.lower() == "true" or val.lower() == "false":
                    val = val.lower() in ("yes", "true", "t", "1")
            except:
                raise InvalidCommandLineError("Invalid filter" " parameter format [filter_attribute]=[filter_value]")

            # Severity inside Oem/Hpe should be filtered
            if sel == "Severity":
                if not self.rdmc.app.typepath.defs.isgen9:
                    sel = "Oem/Hpe/" + sel
                else:
                    sel = "/" + sel
            data = filter_output(data, sel, val)
            if not data:
                raise NoContentsFoundForOperationError("Filter returned no matches.")

        return data

    def getahsfilename(self, options):
        """Create a default name if no ahsfilename is passed

        :param options: command line options
        :type options: list.
        """
        LOGGER.info("Obtaining Serialnumber from iLO for AHS filename.")

        if not options.sessionid:
            val = "ComputerSystem."
            filtereddatainstance = self.rdmc.app.select(selector=val)
            snum = None

            try:
                filtereddictslists = [x.resp.dict for x in filtereddatainstance]

                if not filtereddictslists:
                    raise NoContentsFoundForOperationError("")
            except Exception:
                try:
                    resp = self.rdmc.app.get_handler(
                        self.rdmc.app.typepath.defs.systempath,
                        silent=True,
                        service=True,
                        uncache=True,
                    )
                    snum = resp.dict["SerialNumber"] if resp else snum
                except KeyError:
                    raise InvalidKeyError(
                        "Unable to find key SerialNumber, please check path %s" % self.rdmc.app.typepath.defs.systempath
                    )
                except:
                    raise NoContentsFoundForOperationError("Unable to retrieve log instance.")

            snum = filtereddictslists[0]["SerialNumber"] if not snum else snum
        else:
            resp = self.rdmc.app.get_handler(
                "/redfish/v1/systems/1",
                sessionid=options.sessionid,
                silent=True,
                service=True,
                uncache=True,
            )
            if "SerialNumber" in resp.dict:
                snum = resp.dict["SerialNumber"] if resp else snum
        snum = "UNKNOWN" if snum.isspace() else snum
        timenow = (str(datetime.datetime.now()).split()[0]).split("-")
        todaysdate = "".join(timenow)

        resp = self.rdmc.app.get_handler(
            "/redfish/v1",
            sessionid=options.sessionid,
            silent=True,
            service=True,
            uncache=True,
        )
        ahsdefaultfilename = "HPE_" + snum + "_" + todaysdate + ".ahs"
        if "Vendor" in resp.dict:
            ahsdefaultfilename = ahsdefaultfilename.replace("HPE", resp.dict["Vendor"])

        if options.directorypath:
            dir_name = options.directorypath
            dir_name = dir_name.encode("utf-8").decode("utf-8")
            if not os.path.exists(dir_name):
                os.makedirs(dir_name)
            ahsdefaultfilename = os.path.join(dir_name, ahsdefaultfilename)

        return ahsdefaultfilename

    def serverlogsvalidation(self, options):
        """Serverlogs method validation function

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
            "-f",
            "--filename",
            dest="filename",
            help="Use this flag if you wish to use a different"
            " filename than the default one. The default filename is"
            " ilorest.json.",
            action="append",
            default=None,
        )
        customparser.add_argument(
            "--filter",
            dest="filter",
            help="Optionally set a filter value for a filter attribute."
            " This uses the provided filter for the currently selected"
            " type. Note: Use this flag to narrow down your results. For"
            " example, selecting a common type might return multiple"
            " objects that are all of that type. If you want to modify"
            " the properties of only one of those objects, use the filter"
            " flag to narrow down results based on properties."
            "\t\t\t\t\t Usage: --filter [ATTRIBUTE]=[VALUE]",
            default=None,
        )
        customparser.add_argument(
            "--selectlog",
            dest="service",
            help="""Read log from the given log service. Options: IML, """ """IEL or AHS.""",
            default=None,
        )
        customparser.add_argument(
            "--clearlog",
            "-c",
            dest="clearlog",
            action="store_true",
            help="""Clears the logs for a the selected option.""",
            default=None,
        )
        customparser.add_argument(
            "--maintenancemessage",
            "-m",
            dest="mainmes",
            help="""Maintenance message to be inserted into the log. """ """(IML LOGS ONLY FEATURE)""",
            default=None,
        )
        customparser.add_argument(
            "--customiseAHS",
            dest="customiseAHS",
            help="""Allows customised AHS log data to be downloaded.""",
            default=None,
        )
        customparser.add_argument(
            "--downloadallahs",
            dest="downloadallahs",
            action="store_true",
            help="""Allows complete AHS log data to be downloaded.""",
            default=None,
        )
        customparser.add_argument(
            "--directorypath",
            dest="directorypath",
            help="""Directory path for the ahs file.""",
            default=None,
        )
        customparser.add_argument(
            "--mpfile",
            dest="mpfilename",
            help="""use the provided filename to obtain server information.""",
            default=None,
        )
        customparser.add_argument(
            "--outputdirectory",
            dest="outdirectory",
            help="""use the provided directory to output data for multiple server downloads.""",
            default=None,
        )
        customparser.add_argument(
            "--mplog",
            dest="mplog",
            help="""used to indicate the logs to be downloaded on multiple servers. """
            """Allowable values: IEL, IML, AHS, all or combination of any two.""",
            default=None,
        )
        customparser.add_argument(
            "--repair",
            "-r",
            dest="repiml",
            help="""Repair the IML logs with the given ID.""",
            default=None,
        )
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
