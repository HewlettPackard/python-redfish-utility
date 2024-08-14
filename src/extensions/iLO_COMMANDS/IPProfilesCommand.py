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
""" RawGet Command for rdmc """

import base64
import gzip
import json
import os
import re
import time
from ctypes import create_string_buffer
from datetime import datetime
import six
from six import BytesIO

if six.PY3:
    from datetime import timezone


import redfish
from redfish.hpilo.risblobstore2 import BlobStore2

try:
    from rdmc_helper import (
        InvalidCommandLineErrorOPTS,
        InvalidFileFormattingError,
        InvalidFileInputError,
        NoContentsFoundForOperationError,
        PathUnavailableError,
        ReturnCodes,
        UnableToDecodeError,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        InvalidCommandLineErrorOPTS,
        InvalidFileFormattingError,
        InvalidFileInputError,
        NoContentsFoundForOperationError,
        PathUnavailableError,
        ReturnCodes,
        UnableToDecodeError,
    )


class IPProfilesCommand:
    """Raw form of the get command"""

    def __init__(self):
        self.ident = {
            "name": "ipprofiles",
            "usage": None,
            "description": "Decodes and lists "
            "ipprofiles. This is default option. No argument required"
            "\n\tExample: ipprofiles"
            "\n\n\tAdds a new ipprofile from the provided json file."
            "\n\tNOTE: Path can be absolute or from the "
            "same path you launch iLOrest."
            "\n\tipprofiles <file path>"
            "\n\n\tDelete an ipprofile or list of profiles.\n\t"
            "Provide the unique key that corresponds to the ipprofile"
            " data you want to delete.\n\tSeveral IDs can be comma-separated"
            " with no space in between to delete more than one profile. "
            "\n\tipprofiles --delete ID1,ID2,ID3..."
            "\n\n\tCopies ip profile with the specified ID into the ip job queue."
            "and starts it.\n\texample: ipprofiles --start=<profile ID>",
            "summary": "This is used to manage hpeipprofile data store.",
            "aliases": [],
            "auxcommands": ["BootOrderCommand", "RebootCommand"],
        }
        self.path = ""
        self.ipjobs = ""
        self.running_jobs = ""
        self.hvt_output = ""
        self.ipjobtype = ["langsel", "hvt", "ssa", "install", "rbsu"]
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """Main raw get worker function

        :param line: command line input
        :type line: string.
        :param help_disp: display help flag
        :type line: bool.

        """
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

        self.getpaths()

        self.validation(options)

        self.ipprofileworkerfunction(options, args)

        self.cmdbase.logout_routine(self, options)
        # Return code
        return ReturnCodes.SUCCESS

    def ipprofileworkerfunction(self, options, args):
        """
        Ipprofile manager worker function. It calls appropriate function.
        :param options: command line options
        :type options: list.
        :param args: command line args
        :type args: string.
        """

        if options.running_jobs:
            self.get_running_job()
            return ReturnCodes.SUCCESS
        if options.get_hvt:
            if options.filename:
                self.rdmc.ui.warn("iprprofiles -D option does not support -f, please remove -f and rerun\n")
                return ReturnCodes.SUCCESS
            self.get_hvt_output()
            return ReturnCodes.SUCCESS
        if options.del_key:
            self.deletekeyfromipprofiledata(options)
            return ReturnCodes.SUCCESS

        if options.start_ip:
            self.addprofileandstartjob(options)
            return ReturnCodes.SUCCESS

        if len(args) == 1:
            self.encodeandpatchipprofiledata(args)
            return ReturnCodes.SUCCESS

        self.getipprofiledataanddecode(options)

    def getipprofiledataanddecode(self, options):
        """
        Retrieves and decodes, if encoded, data from hpeprofile data store
        :param options: command line options
        :type options: list.
        :return returncode: int
        """

        results = self.rdmc.app.get_handler(self.path, silent=True)
        if results.status == 404:
            raise PathUnavailableError(
                "The Intelligent Provisioning resource "
                "is not available on this system. You may need"
                " to run IP at least once to add the resource."
            )

        if results and results.status == 200:
            j2python = json.loads(results.read)
            for _, val in enumerate(j2python.keys()):
                if isinstance(val, six.string_types):
                    result = self.decode_base64_string(str(j2python[val]))
                    if result is not None:
                        j2python[val] = result

            results.read = json.dumps(j2python, ensure_ascii=False, sort_keys=True)
            if results.dict:
                if options.filename:
                    output = json.dumps(
                        results.dict,
                        indent=2,
                        cls=redfish.ris.JSONEncoder,
                        sort_keys=True,
                    )

                    filehndl = open(options.filename[0], "w")
                    filehndl.write(output)
                    filehndl.close()

                    self.rdmc.ui.printer("Results written out to '%s'.\n" % options.filename[0])
                else:
                    self.rdmc.ui.print_out_json(results.dict)
        else:
            self.rdmc.ui.warn("No IP profiles found\n")

    def get_running_job(self):
        """
        Retrieves and decodes, running job
        :return returncode: int
        """

        results = self.rdmc.app.get_handler(self.running_jobs, silent=True)
        if results.status == 404:
            raise PathUnavailableError(
                "The Intelligent Provisioning resource "
                "is not available on this system. You may need"
                " to run IP at least once to add the resource."
            )

        if results and results.status == 200:
            j2python = json.loads(results.read)
            for _, val in enumerate(list(j2python.keys())):
                if isinstance(val, six.string_types):
                    result = self.decode_base64_string(str(j2python[val]))
                    if result is not None:
                        j2python[val] = result

            results.read = json.dumps(j2python, ensure_ascii=False)
            if results.dict:
                self.rdmc.ui.print_out_json(results.dict)
        else:
            self.rdmc.ui.warn("No IP profiles found\n")

    def get_hvt_output(self):
        """
        Retrieves and decodes, running job
        :return returncode: int
        """
        return_value = {}
        results = self.rdmc.app.get_handler(self.hvt_output, silent=True)
        if results.status == 404:
            raise PathUnavailableError(
                "The Intelligent Provisioning resource "
                "is not available on this system. You may need"
                " to run IP at least once to add the resource."
            )

        if results and results.status == 200:
            j2python = json.loads(results.read)
            for _, val in enumerate(list(j2python.keys())):
                if isinstance(val, six.string_types) and "@" not in val:
                    return_value = json.loads(self.decode_base64_string(str(j2python[val])))
            self.rdmc.ui.print_out_json(return_value)
        else:
            self.rdmc.ui.error("No IP profiles found\n")

    def encodeandpatchipprofiledata(self, args):
        """
        Reads file in the given path, encode it,
        and apply it on iLO hpeipprofiles data store.
        :param args: command line args
        :type args: string.
        :retirn returncode: int
        """

        contentsholder = self.encode_base64_string(args)

        if "path" in contentsholder and "body" in contentsholder:
            self.rdmc.app.patch_handler(contentsholder["path"], contentsholder["body"])

        return ReturnCodes.SUCCESS

    def deletekeyfromipprofiledata(self, options):
        """
        Provide a string which represents a valid key in
        hpeipprofiles data store.
        :param options: command line options
        :type options: list.
        :return returncode: int
        """

        get_results = self.rdmc.app.get_handler(self.path, silent=True)

        j2python = json.loads(get_results.read)
        all_keys = options.del_key[0].split(",")
        for key in all_keys:
            if isinstance(key, six.string_types) and j2python.get(key.strip(), False):
                del j2python[key.strip()]
            else:
                raise InvalidFileFormattingError("%s was not found .\n" % key)

        payload = {"path": self.path, "body": j2python}

        self.rdmc.app.put_handler(payload["path"], payload["body"])

        return ReturnCodes.SUCCESS

    def addprofileandstartjob(self, options):
        """
        Adds ip profile into the job queue and start it.
        :return returncode: int
        """

        ipprovider = self.hasipprovider()
        if ipprovider is None:
            raise PathUnavailableError("System does not support this feature of IP.\n")

        ipjob = self.hasipjobs()
        if not ipjob:
            raise InvalidFileFormattingError("System does not have any IP" " profile to copy to the job queue.\n")

        current_state = self.inipstate(ipprovider)
        if current_state is None:
            raise PathUnavailableError("System does not support this feature of IP.\n")

        later_state = False
        ipstate = current_state["InIP"]
        if isinstance(ipstate, bool) and ipstate:
            # make sure we are in IP state.  Reset and monitor
            self.resetinipstate(ipprovider, current_state)
            # if we are in ip, monitor should be fast, use 15 seconds
            later_status = self.monitorinipstate(ipprovider, 3)
            if later_status:
                self.rdmc.ui.printer("Server is in IP state. Powering on...\n")
                self.copyjobtoipqueue(ipjob, options.start_ip)
                self.rdmc.ui.printer("Copy operation was successful...\n")
                return ReturnCodes.SUCCESS

        if not isinstance(ipstate, bool):
            #       inip is in an unknown state, so ...
            # patch to false, reboot, then monitor...if it turns true later...
            # then we are in IP state otherwise, manually check system...
            self.resetinipstate(ipprovider, current_state)
            later_status = self.monitorinipstate(ipprovider, 3)
            if later_status:
                self.copyjobtoipqueue(ipjob, options.start_ip)
                self.rdmc.ui.printer("Copy operation was successful...\n")
                return ReturnCodes.SUCCESS

        # Check if the server is On or Off, If it is Off, make it on
        path = self.rdmc.app.typepath.defs.systempath
        get_results = self.rdmc.app.get_handler(path, silent=True)
        result = json.loads(get_results.read)
        if result and result.get("PowerState") == "Off":
            self.rdmc.ui.printer("Server is in OFF state. Powering on...\n")
            self.auxcommands["bootorder"].run("--onetimeboot=Utilities " "--reboot=On --commit")
        elif result and result.get("Oem").get("Hpe").get("PostState") != "FinishedPost":
            self.rdmc.ui.printer("Server is in POST state. Restarting...\n")
            # Forcefully switch off as it is stuck in POST
            self.auxcommands["reboot"].run("ForceOff")
            time.sleep(5)
            # Switch on with bootorder set
            self.auxcommands["bootorder"].run("--onetimeboot=Utilities " "--reboot=On --commit")
            # Check to find out if server in POST
            # count = 0
            # in_post = True
            # path = self.rdmc.app.typepath.defs.systempath
            # while (count < 5):
            #    count = count + 1
            #    get_results = self.rdmc.app.get_handler(path, silent=True)
            #    result = json.loads(get_results.read)
            #    if result and result.get("Oem").get("Hpe").get("PostState") == "FinishedPost":
            #        in_post = False
            #        break
            #    else:
            #        # Sleep for 1 minutes for 5 times.
            #        self.rdmc.ui.printer("System in POST...waiting for 1 min...\n")
            #        time.sleep(60)

            # if in_post:
            #    raise NoContentsFoundForOperationError(
            #        "Server still in POST even after 5 minutes - Please check"
            #    )
        else:
            self.rdmc.ui.printer("Server is in OS state. ColdBooting...\n")
            try:
                self.auxcommands["bootorder"].run("--onetimeboot=Utilities " "--reboot=ColdBoot --commit")
            except:
                raise InvalidFileFormattingError("System failed to reboot")

        # After reboot, login again
        time.sleep(options.sleep_time)  # Sleep until reboot
        self.validation(options)

        later_state = self.monitorinipstate(ipprovider)
        if later_state:
            self.copyjobtoipqueue(ipjob, options.start_ip)
            self.rdmc.ui.printer("Copy operation was successful...\n")
        else:
            raise InvalidFileFormattingError(
                "\nSystem reboot took longer than 4 minutes."
                "something is wrong. You need to physically check this system.\n"
            )

        return ReturnCodes.SUCCESS

    def resetinipstate(self, ipprovider, current_state):
        """
        Regardless of previous value, sets InIP value to False
        :param ipprovider: url path of heip.
        :type ipprovider: string.
        :param current_state: the value of InIP.
        :type current_state: dict
        """

        current_state["InIP"] = False

        payload = {"path": ipprovider, "body": current_state}

        self.rdmc.app.put_handler(payload["path"], payload["body"], silent=True)

    def monitorinipstate(self, ipprovider, timer=48):
        """
        Monitor InIP value every 5 seconds until it turns true or time expires.
        :param ipprovider: url path of heip.
        :type ipprovider: string.
        :param timer: time it takes iLO to boot into F10 assuming we are in boot state.
        :type timer: int
        :return ipstate: boolean
        """

        retry = timer  # 48 * 5 = 4 minutes
        ipstate = False
        progress = self.progressbar()
        self.rdmc.ui.printer("\n")
        while retry > 0:
            time.sleep(5)
            next(progress)
            status = self.inipstate(ipprovider)
            if isinstance(status["InIP"], bool) and status["InIP"]:
                ipstate = True
                break
            retry = retry - 1
        self.rdmc.ui.printer("\n")

        return ipstate

    def progressbar(self):
        """
        An on demand function use to output the progress while iLO is booting into F10.
        """
        while True:
            yield self.rdmc.ui.printer(">>>")

    def copyjobtoipqueue(self, ipjobs, jobkey):
        """
        Copies HpeIpJob to Job queue. Function assumes there is a job to copy.
        A check was already done to make sure we have a job to copy in hasipjobs()
        :param ipjobs: url path of heip.
        :type ipjobs: list of dictionary.
        :param jobkey: key of job to copy.
        :type jokbey: str.
        """

        get_results = self.rdmc.app.get_handler(self.path, silent=True)

        j2python = json.loads(get_results.read)
        copy_job = {}
        for ipj in j2python:
            if jobkey == ipj:
                _decode = self.decode_base64_string(j2python[ipj])
                if _decode is not None:
                    _critical_props = {
                        "log": '[{"msg": "WAITINGTOBEPROCESSED", "percent": 0}]',
                        "status": "waiting",
                    }
                    copy_job.update(
                        {
                            k: v.update(_critical_props) or v
                            for k, v in json.loads(_decode).items()
                            if k in self.ipjobtype
                        }
                    )
                else:
                    raise NoContentsFoundForOperationError("Not supported profile content")
                break
        if not copy_job:
            raise NoContentsFoundForOperationError("The ID %s does not match any ipprofile" % jobkey)
        payload = {"path": self.ipjobs, "body": copy_job}

        self.rdmc.app.put_handler(payload["path"], payload["body"])

    def inipstate(self, ipprovider):
        """
        A check is done to determine if this version of iLO has InIP profile.
        :param ipprovider: url path of heip.
        :type ipprovider: string.
        :return is_inip: None or dict
        """

        if ipprovider.startswith("/redfish/"):
            get_results = self.rdmc.app.get_handler(ipprovider, silent=True)
            result = json.loads(get_results.read)

            is_inip = None
            try:
                if "InIP" in list(result.keys()):
                    is_inip = result
            except KeyError:
                pass

        return is_inip

    def hasipjobs(self):
        """
        A check is done to determine if there is a job in HpeIpJobs we can
        copy to IP job queue
        :param options: command line options
        :type options: list.
        :return list_dict: list of dicts
        """

        results = self.rdmc.app.get_handler(self.path, silent=True)

        j2python = json.loads(results.read)
        for _, val in enumerate(j2python.keys()):
            if isinstance(val, six.string_types):
                result = self.decode_base64_string(str(j2python[val]))
                if result is not None:
                    j2python[val] = result

        list_dict = []

        for key, value in j2python.items():
            if not re.match("@odata", key):
                if len(key) >= 13 and key.isdigit():
                    list_dict.append({key: value})  # list of dict with valid key/value

        return list_dict

    def hasipprovider(self):
        """
        A check is done here to determine if this version of iLO has IP provider
        profile path using the  "Oem.Hpe.Links.HpeIpProvider"

        :return is_provider: None or string.
        """
        path = self.rdmc.app.typepath.defs.systempath
        get_results = self.rdmc.app.get_handler(path, silent=True)

        result = json.loads(get_results.read)

        is_ipprovider = None
        try:
            is_ipprovider = list(result["Oem"]["Hpe"]["Links"]["HpeIpProvider"].values())[0]
        except KeyError:
            pass

        return is_ipprovider

    def validation(self, options):
        """IPProfiles validation function

        :param options: command line options
        :type options: list.
        """
        self.cmdbase.login_select_validation(self, options)

    def decode_base64_string(self, str_b64):
        """
        Decodes a given string that was encoded with base64 and gzipped.
        :param str_b64: a string that was base64 encoded and the  gzipped
        :type str_b64: string.
        """

        read_data = None
        if isinstance(str_b64, six.string_types) and str_b64:
            try:
                decoded_str = base64.decodebytes(str_b64.encode("utf-8"))
                inbuffer = BytesIO(decoded_str)
                gzffile = gzip.GzipFile(mode="rb", fileobj=inbuffer)
                read_data = ""
                for line in gzffile.readlines():
                    read_data = read_data + line.decode("utf-8")
            except:
                pass

            return read_data

    def encode_base64_string(self, args):
        """
        Encode a given string  with base64 and gzip it.
        :param args: command line args
        :type args: string.
        """

        payload = {}
        filename = args[0]
        if filename:
            if not os.path.isfile(filename):
                raise InvalidFileInputError(
                    "File '%s' doesn't exist. " "Please create file by running 'save' command." % filename
                )

            try:
                with open(filename, "r") as fh:
                    contentsholder = json.loads(fh.read())
            except:
                raise InvalidFileFormattingError("Input file '%s' was not " "format properly." % filename)

            try:
                text = json.dumps(contentsholder).encode("utf-8")
                buf = BytesIO()
                gzfile = gzip.GzipFile(mode="wb", fileobj=buf)
                gzfile.write(text)
                gzfile.close()

                en_text = base64.encodebytes(buf.getvalue()).decode("utf-8")

                if six.PY3:
                    epoch = datetime.fromtimestamp(0, tz=timezone.utc)
                    now = datetime.now(tz=timezone.utc)
                elif six.PY2:
                    epoch = datetime.utcfromtimestamp(0)
                    now = datetime.utcnow()
                delta = now - epoch
                time_stamp = delta.total_seconds() * 1000
                time_stamp = repr(time_stamp).split(".")[0]

                body_text = {time_stamp: en_text.strip()}

                payload["body"] = body_text
                if isinstance(self.path, bytes):
                    self.path = self.path.decode("utf-8")
                payload["path"] = self.path
            except Exception as excp:
                raise UnableToDecodeError("Error while encoding string %s." % excp)

        return payload

    def getpaths(self):
        """Get paths for ipprofiles command"""
        if not all(iter([self.path, self.ipjobs, self.running_jobs, self.hvt_output])):
            dll = BlobStore2.gethprestchifhandle()

            profiles_path = create_string_buffer(50)
            jobs_path = create_string_buffer(50)
            running_jobs_path = create_string_buffer(50)
            hvt_output_path = create_string_buffer(50)

            dll.get_ip_profiles(profiles_path)
            dll.get_ip_jobs(jobs_path)
            dll.get_running_jobs(running_jobs_path)
            dll.get_hvt_output(hvt_output_path)

            self.path = profiles_path.value
            self.ipjobs = jobs_path.value
            self.running_jobs = running_jobs_path.value
            self.hvt_output = hvt_output_path.value

    def definearguments(self, customparser):
        """Wrapper function for new command main function

        :param customparser: command line input
        :type customparser: parser.
        """
        if not customparser:
            return

        self.cmdbase.add_login_arguments_group(customparser)

        customparser.add_argument(
            "-r",
            "--running",
            dest="running_jobs",
            default=False,
            action="store_true",
            help="""Show status of the currently running or last job executed""",
        )
        customparser.add_argument(
            "-D",
            "--diags",
            help="""Get result of last HVT (diagnostics) run as part of an ipprofile job""",
            default=False,
            action="store_true",
            dest="get_hvt",
        )
        customparser.add_argument(
            "-f",
            "--filename",
            dest="filename",
            help="""Write results to the specified file.""",
            action="append",
            default=None,
        )
        customparser.add_argument(
            "--delete",
            dest="del_key",
            action="append",
            help="Look for the key or keys in the ipprofile manager and delete",
            default=None,
        )
        customparser.add_argument(
            "-s",
            "--start",
            dest="start_ip",
            help="Copies the specified ip profile into the job queue and starts it",
            default=None,
        )
        customparser.add_argument(
            "-t",
            "--sleeptime",
            dest="sleep_time",
            type=int,
            help="Sleep time in seconds when server in OS mode and rebooted",
            default=320,
        )
