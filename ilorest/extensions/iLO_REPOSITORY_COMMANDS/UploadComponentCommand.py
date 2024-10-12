# ##
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
# ##

# -*- coding: utf-8 -*-
""" Upload Component Command for rdmc """

import os
import json
import sys
import time
import shutil
from random import choice
from string import ascii_lowercase
import ctypes
from six.moves import input
from ctypes import (
    c_char_p,
    c_void_p,
    byref,
    c_ubyte,
    c_int,
    c_uint32,
    POINTER,
    create_string_buffer,
)
from redfish.hpilo.rishpilo import (
    HpIloInitialError,
    HpIloChifAccessDeniedError,
    HpIloNoChifDriverError,
)
from redfish.hpilo.rishpilo import BlobReturnCodes
from redfish.hpilo.risblobstore2 import BlobStore2

try:
    from rdmc_helper import (
        LOGGER,
        ReturnCodes,
        InvalidCommandLineErrorOPTS,
        UploadError,
        IncompatibleiLOVersionError,
        TimeOutError,
        InvalidFileInputError,
        UploadPowerOffError,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        LOGGER,
        ReturnCodes,
        InvalidCommandLineErrorOPTS,
        UploadError,
        IncompatibleiLOVersionError,
        TimeOutError,
        InvalidFileInputError,
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


class UploadComponentCommand:
    """Constructor"""

    def __init__(self):
        self.ident = {
            "name": "uploadcomp",
            "usage": None,
            "description": "Run to upload the component on "
            "to iLO Repository\n\n\tUpload component to the iLO "
            "repository.\n\texample: uploadcomp --component <path> "
            "--compsig <path_to_signature>\n\n\tFlash the component "
            "instead of add to the iLO repository.\n\texample: "
            "uploadcomp --component <binary_path> --update_target "
            "--update_repository",
            "summary": "Upload components/binary to the iLO Repository.",
            "aliases": [],
            "auxcommands": ["FwpkgCommand"],
        }

        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """Wrapper function for upload command main function

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

        self.uploadcommandvalidation(options)
        fwpkg = False
        if (
            options.component.endswith(".fwpkg")
            or options.component.endswith(".fup")
            or options.component.endswith(".hpb")
            or options.component.endswith(".HPb")
            or options.component.endswith(".pup")
        ):
            fwpkg = True
            try:
                comp, loc, ctype, pldmfw = self.auxcommands["flashfwpkg"].preparefwpkg(self, options.component, options)
            except UploadPowerOffError:
                self.rdmc.ui.error(
                    "Server power is On,Kindly Power Off the server,to be able to flash the B- component \n"
                )
                return ReturnCodes.UPLOAD_POWEROFF_ERROR
            # if pldm firmware
            if pldmfw:
                path = self.rdmc.app.typepath.defs.systempath
                results = self.rdmc.app.get_handler(path, service=True, silent=True).dict
                device_discovery_status = results["Oem"]["Hpe"]["DeviceDiscoveryComplete"]["DeviceDiscovery"]
                LOGGER.info("Device Discovery Status is {}".format(device_discovery_status))
                # check for device discovery
                # if ("DeviceDiscoveryComplete" not in device_discovery_status):
                #    raise DeviceDiscoveryInProgress(
                #        "Device Discovery in progress...Please retry flashing firmware after 10 minutes"
                #    )
            if ctype in ["C", "BC"]:
                options.component = comp[0]
            # else:
            #    options.component = os.path.join(loc, comp[0])

        if self.rdmc.app.typepath.defs.isgen9:
            raise IncompatibleiLOVersionError("iLO Repository commands are only available on iLO 5.")

        filestoupload = self._check_and_split_files(options)
        validation = self.componentvalidation(options, filestoupload)
        if validation:
            start_time = time.time()
            ret = ReturnCodes.FAILED_TO_UPLOAD_COMPONENT

            # ret = self.uploadfunction(filestoupload, options)
            if "blobstore" in self.rdmc.app.current_client.base_url:
                ret = self.uploadlocally(filestoupload, options)
            else:
                ret = self.uploadfunction(filestoupload, options)

            if ret == ReturnCodes.SUCCESS and not options.update_target:
                self.rdmc.ui.printer("Uploading took %s\n" % human_readable_time(time.time() - start_time))

            if len(filestoupload) > 1:
                path, _ = os.path.split((filestoupload[0])[1])
                shutil.rmtree(path)
            elif fwpkg:
                if os.path.exists(loc):
                    shutil.rmtree(loc)
        elif not validation and options.forceupload:
            self.rdmc.ui.printer(
                "Component " + filestoupload[0][0] + " is already present in repository ,Hence skipping the re upload\n"
            )
            ret = ReturnCodes.SUCCESS
        else:
            ret = ReturnCodes.FAILED_TO_UPLOAD_COMPONENT
        self.cmdbase.logout_routine(self, options)
        # Return code
        return ret

    def componentvalidation(self, options, filelist):
        """Check for duplicate component in repository

        :param options: command line options
        :type options: list.
                :param filelist: list of files to be uploaded (multiple files will be
               generated for items over 32K in size)
        :type filelist: list of strings
        """
        validation = True
        prevfile = None

        path = "/redfish/v1/UpdateService/ComponentRepository/?$expand=."
        results = self.rdmc.app.get_handler(path, service=True, silent=True)

        results = results.dict

        if "Members" in results and results["Members"]:
            for comp in results["Members"]:
                for filehndl in filelist:
                    if (
                        comp["Filename"].upper() == str(filehndl[0]).upper()
                        and not options.forceupload
                        and prevfile != filehndl[0].upper()
                    ):
                        ans = input(
                            "A component with the same name (%s) has "
                            "been found. Would you like to upload and "
                            "overwrite this file? (y/n)" % comp["Filename"]
                        )

                        while ans.lower() != "n" and ans.lower() != "y":
                            ans = input("Please enter valid option (y/n)")

                        if ans.lower() == "n":
                            self.rdmc.ui.printer(
                                "Error: Upload stopped by user due to filename conflict."
                                " If you would like to bypass this check include the"
                                ' "--forceupload" flag.\n'
                            )
                            validation = False
                            break
                    elif (
                        comp["Filename"].upper() == str(filehndl[0]).upper()
                        and options.forceupload
                        and prevfile != filehndl[0].upper()
                    ):
                        if comp["Locked"]:
                            options.update_repository = False
                        else:
                            options.update_repository = True
                        if not options.update_target and comp["Locked"]:
                            validation = False
                            break
                    if options.update_repository:
                        if (
                            comp["Filename"].upper() == str(filehndl[0]).upper()
                            and prevfile != filehndl[0].upper()
                            and comp["Locked"]
                        ):
                            self.rdmc.ui.printer(
                                "Error: Component is currently locked by a taskqueue task or "
                                "installset. Remove any installsets or taskqueue tasks "
                                "containing the file and try again OR use taskqueue command "
                                "to put the component to installation queue\n"
                            )
                            validation = False
                            break
                        elif (
                            comp["Filename"].upper() == str(filehndl[0]).upper()
                            and prevfile != filehndl[0].upper()
                            and comp["Locked"]
                            and options.forceupload
                        ):
                            validation = False
                            break
                    prevfile = str(comp["Filename"].upper())
        return validation

    def _check_and_split_files(self, options):
        """Check and split the file to upload on to iLO Repository

        :param options: command line options
        :type options: list.
        """

        def check_file_rw(filename, rw):
            try:
                fd = open(filename, rw)
                fd.close()
            except IOError:
                raise InvalidFileInputError("The file '%s' could not be opened for upload" % filename)

        maxcompsize = 32 * 1024 * 1024
        filelist = []

        # Lets get the component filename
        _, filename = os.path.split(options.component)
        check_file_rw(os.path.normpath(options.component), "r")
        self.rdmc.ui.printer("Successfully checked '%s'.\n" % filename)
        size = os.path.getsize(options.component)

        # This is to upload the binary directly to flash scenario
        if not options.componentsig:
            if not self.findcompsig(filename):
                return [(filename, options.component, options.componentsig, 0)]

        if size > maxcompsize:
            self.rdmc.ui.printer("Component is more than 32MB in size.\n")
            self.rdmc.ui.printer("Component size = %s\n" % str(size))
            section = 1

            sigpath, _ = os.path.split(options.componentsig)
            check_file_rw(os.path.normpath(options.componentsig), "r")
            filebasename = filename[: filename.rfind(".")]
            tempfoldername = "bmn" + "".join(choice(ascii_lowercase) for i in range(12))

            if self.rdmc.app.cache:
                tempdir = os.path.join(self.rdmc.app.cachedir, tempfoldername)
            else:
                tempdir = os.path.join(sys.executable, tempfoldername)

            self.rdmc.ui.printer("Spliting component. Temporary " "cache directory at %s\n" % tempdir)

            if not os.path.exists(tempdir):
                os.makedirs(tempdir)

            with open(options.component, "rb") as component:
                while True:
                    data = component.read(maxcompsize)
                    if len(data) != 0:
                        sectionfilename = filebasename + "_part" + str(section)
                        sectionfilepath = os.path.join(tempdir, sectionfilename)

                        sectioncompsigpath = os.path.join(sigpath, sectionfilename + ".compsig")
                        sigfullpath = os.path.join(tempdir, sigpath)
                        if not os.path.exists(sigfullpath):
                            os.makedirs(sigfullpath)
                        writefile = open(sectionfilepath, "wb")
                        writefile.write(data)
                        writefile.close()

                        item = (
                            filename,
                            sectionfilepath,
                            sectioncompsigpath,
                            section - 1,
                        )

                        filelist.append(item)
                        section += 1

                    if len(data) != maxcompsize:
                        break

            return filelist
        else:
            return [(filename, options.component, options.componentsig, 0)]

    def uploadfunction(self, filelist, options=None):
        """Main upload command worker function

        :param filelist: List of files to upload.
        :type filelist: list.
        :param options: command line options
        :type options: list.
        """

        # returns a tuple with the state and the result dict
        state, result = self.get_update_service_state()

        if state != "COMPLETED" and state != "COMPLETE" and state != "ERROR" and state != "IDLE":
            self.rdmc.ui.error("iLO UpdateService is busy. Please try again.")

            return ReturnCodes.UPDATE_SERVICE_BUSY

        sessionkey = self.rdmc.app.current_client.session_key

        etag = ""
        hpe = result["Oem"]["Hpe"]
        urltosend = "/cgi-bin/uploadFile"

        if "PushUpdateUri" in hpe:
            urltosend = hpe["PushUpdateUri"]
        elif "HttpPushUri" in result:
            urltosend = result["HttpPushUri"]
        else:
            return ReturnCodes.FAILED_TO_UPLOAD_COMPONENT

        for item in filelist:
            ilo_upload_filename = item[0]

            ilo_upload_compsig_filename = ilo_upload_filename[: ilo_upload_filename.rfind(".")] + ".compsig"

            componentpath = item[1]
            compsigpath = item[2]

            _, filename = os.path.split(componentpath)

            if not etag:
                etag = "sum" + filename.replace(".", "")
                etag = etag.replace("-", "")
                etag = etag.replace("_", "")

            section_num = item[3]
            if isinstance(sessionkey, bytes):
                sessionkey = sessionkey.decode("utf-8")

            parameters = {
                "UpdateRepository": options.update_repository,
                "UpdateTarget": options.update_target,
                "ETag": etag,
                "Section": section_num,
                "UpdateRecoverySet": options.update_srs,
                "TPMOverride": options.tover,
            }

            data = [("sessionKey", sessionkey), ("parameters", json.dumps(parameters))]

            if not compsigpath:
                compsigpath = self.findcompsig(componentpath)
            if compsigpath:
                with open(compsigpath, "rb") as fle:
                    output = fle.read()
                data.append(
                    (
                        "compsig",
                        (
                            ilo_upload_compsig_filename,
                            output,
                            "application/octet-stream",
                        ),
                    )
                )
                output = None

            with open(componentpath, "rb") as fle:
                output = fle.read()
            data.append(("file", (ilo_upload_filename, output, "application/octet-stream")))

            if options.update_repository:
                self.rdmc.ui.printer("Uploading component " + filename + ".\n")
            if options.update_target:
                self.rdmc.ui.printer("Flashing component " + filename + ".\n")
            res = self.rdmc.app.post_handler(
                str(urltosend),
                data,
                headers={"Cookie": "sessionKey=" + sessionkey},
                silent=False,
                service=False,
            )

            if res.status == 400 and res.dict is None:
                self.rdmc.ui.error(
                    "Component " + filename + " was not uploaded , iLO returned 400 error code. "
                    "Check if the user has all privileges to perform the operation.\n"
                )
                return ReturnCodes.FAILED_TO_UPLOAD_COMPONENT

            if res.status != 200:
                return ReturnCodes.FAILED_TO_UPLOAD_COMPONENT
            else:
                if options.update_repository:
                    self.rdmc.ui.printer("Component " + filename + " uploading successfully.\n")
                if options.update_target:
                    self.rdmc.ui.printer("Component " + filename + " flashing successfully.\n")

            if not self.wait_for_state_change():
                # Failed to upload the component.
                raise UploadError("Error while processing the component.")

        return ReturnCodes.SUCCESS

    def wait_for_state_change(self, wait_time=4800):
        """Wait for the iLO UpdateService to a move to terminal state.
        :param options: command line options
        :type options: list.
        :param wait_time: time to wait on upload
        :type wait_time: int.
        """
        total_time = 0
        spinner = ["|", "/", "-", "\\"]
        state = ""
        self.rdmc.ui.printer("Waiting for iLO UpdateService to finish processing the component\n")

        while total_time < wait_time:
            state, _ = self.get_update_service_state()

            if state == "ERROR":
                return False
            elif state != "COMPLETED" and state != "IDLE" and state != "COMPLETE":
                # Lets try again after 8 seconds
                count = 0

                # fancy spinner
                while count <= 32:
                    self.rdmc.ui.printer("Updating: %s\r" % spinner[count % 4])
                    time.sleep(0.25)
                    count += 1

                total_time += 8
            else:
                break

        if total_time > wait_time:
            raise TimeOutError("UpdateService in " + state + " state for " + str(wait_time) + "s")

        return True

    def get_update_service_state(self):
        """Get the current UpdateService state

        :param options: command line options
        :type options: list.
        """
        path = "/redfish/v1/UpdateService"
        results = self.rdmc.app.get_handler(path, service=True, silent=True)

        if results and results.status == 200 and results.dict:
            output = results.dict

            if self.rdmc.opts.verbose:
                self.rdmc.ui.printer("UpdateService state = " + (output["Oem"]["Hpe"]["State"]).upper() + "\n")

            return (output["Oem"]["Hpe"]["State"]).upper(), results.dict
        else:
            return "UNKNOWN", {}

    def findcompsig(self, comppath):
        """Try to find compsig if not included
        :param comppath: Path of file to find compsig for.
        :type comppath: str.
        """
        compsig = ""

        cutpath = comppath.split(os.sep)
        _file = cutpath[-1]
        _file_rev = _file[::-1]
        filename = _file[: ((_file_rev.find(".")) * -1) - 1]

        try:
            location = os.sep.join(cutpath[:-1])
        except:
            location = os.curdir

        if not location:
            location = os.curdir

        files = [f for f in os.listdir(location) if os.path.isfile(os.path.join(location, f))]

        for filehndl in files:
            if filehndl.startswith(filename) and filehndl.endswith(".compsig"):
                self.rdmc.ui.printer("Compsig found for file.\n")

                if location != ".":
                    compsig = location + os.sep + filehndl
                else:
                    compsig = filehndl

                break

        return compsig

    def uploadlocally(self, filelist, options=None):
        """Upload component locally

        :param filelist: List of files to upload.
        :type filelist: list.
        :param options: command line options
        :type options: list.
        """
        new_chif_needed = False
        upload_failed = False
        if not options.update_target:
            options.upload_srs = False

        if options.update_srs:
            if options.user and options.password:
                new_chif_needed = True
            else:
                self.rdmc.ui.error(
                    "ERROR: --update_srs option needs to be passed with "
                    "--username and --password options, upload failed\n"
                )
                return ReturnCodes.FAILED_TO_UPLOAD_COMPONENT
        try:
            dll = self.rdmc.app.current_client.connection._conn.channel.dll
            multiupload = False

            if new_chif_needed:
                # Backup old chif channel
                dll_bk = dll
                dll = None
                user = options.user
                passwrd = options.password
                dll, fhandle = self.create_new_chif_for_upload(user, passwrd)
                self.rdmc.app.current_client.connection._conn.channel.dll = dll

            dll.uploadComponent.argtypes = [c_char_p, c_char_p, c_char_p, c_uint32]
            dll.uploadComponent.restype = c_int

            for item in filelist:
                ilo_upload_filename = item[0]
                componentpath = item[1]
                compsigpath = item[2]

                if not compsigpath:
                    compsigpath = self.findcompsig(componentpath)

                _, filename = os.path.split(componentpath)

                # 0x00000001  // FUM_WRITE_NAND
                # 0x00000002  // FUM_USE_NAND
                # 0x00000004  // FUM_NO_FLASH
                # 0x00000008  // FUM_FORCE
                # 0x00000010  // FUM_SIDECAR
                # 0x00000020  // FUM_APPEND
                # 0x40  // FUM_UPDATE_RECOVERY
                # 0x00000080   //FUM_RECOVERY
                # 0x00000100 // FUM_TASK
                # 0x00000200  //FUM_RECO_PRIV

                if not compsigpath and options.update_target:
                    if not options.update_repository:
                        # Just update the firmware
                        if options.update_srs:
                            dispatchflag = ctypes.c_uint32(0x00000000 | 0x40)
                        else:
                            dispatchflag = ctypes.c_uint32(0x00000000)
                    else:
                        # Update the firmware and Upload to Repository
                        if options.update_srs:
                            dispatchflag = ctypes.c_uint32(0x00000000 | 0x00000001 | 0x40)
                        else:
                            dispatchflag = ctypes.c_uint32(0x00000000 | 0x00000001)
                elif not compsigpath and not options.update_target and options.update_repository:
                    # uploading a secuare flash binary image onto the NAND
                    if options.update_srs:
                        dispatchflag = ctypes.c_uint32(0x00000001 | 0x00000004 | 0x40)
                    else:
                        dispatchflag = ctypes.c_uint32(0x00000001 | 0x00000004)
                else:
                    # Uploading a component with a side car file.
                    if options.update_srs:
                        dispatchflag = ctypes.c_uint32(0x00000001 | 0x00000004 | 0x00000010 | 0x40)
                    else:
                        dispatchflag = ctypes.c_uint32(0x00000001 | 0x00000004 | 0x00000010)

                if multiupload:
                    # For second upload to append if the component is > 32MB in size
                    if options.update_srs:
                        dispatchflag = ctypes.c_uint32(0x00000001 | 0x00000004 | 0x00000010 | 0x00000020 | 0x40)
                    else:
                        dispatchflag = ctypes.c_uint32(0x00000001 | 0x00000004 | 0x00000010 | 0x00000020)

                if options.update_repository:
                    self.rdmc.ui.printer("Uploading component " + filename + "\n")
                if options.update_target:
                    self.rdmc.ui.printer("Flashing component " + filename + "\n")

                ret = dll.uploadComponent(
                    ctypes.create_string_buffer(compsigpath.encode("utf-8")),
                    ctypes.create_string_buffer(componentpath.encode("utf-8")),
                    ctypes.create_string_buffer(ilo_upload_filename.encode("utf-8")),
                    dispatchflag,
                )

                upload_failed = False
                if ret != 0:
                    LOGGER.error("Component {} upload failed".format(filename))
                    self.rdmc.ui.error("Component " + filename + " upload failed.\n")
                    upload_failed = True
                else:
                    LOGGER.info("Component {} uploaded successfully".format(filename))
                    if options.update_repository:
                        self.rdmc.ui.printer("Component " + filename + " uploaded successfully.\n")
                    if options.update_target:
                        self.rdmc.ui.printer("Component " + filename + " flashed successfully.\n")
                    self.rdmc.ui.printer("[200] The operation completed successfully.\n")
                    if not options.update_target:
                        if not self.wait_for_state_change():
                            # Failed to upload the component.
                            raise UploadError("Error while processing the component.")

                multiupload = True

                if new_chif_needed:
                    dll.ChifTerminate()
                    dll.ChifClose(fhandle)
                    fhandle = None
                    BlobStore2.unloadchifhandle(dll)
                    # Restore old chif channel
                    dll = dll_bk
                    self.rdmc.app.current_client.connection._conn.channel.dll = dll_bk
                    LOGGER.info("Restored the old chif channel\n")

        except Exception as excep:
            LOGGER.error("Exception occured, {}".format(excep))
            raise excep

        if upload_failed:
            return ReturnCodes.FAILED_TO_UPLOAD_COMPONENT
        else:
            return ReturnCodes.SUCCESS

    def create_new_chif_for_upload(self, user, passwrd):
        dll = BlobStore2.gethprestchifhandle()
        dll.ChifInitialize(None)
        # Enable Security Flag in Chif
        dll.ChifEnableSecurity()
        fhandle = c_void_p()
        dll.ChifCreate.argtypes = [c_void_p]
        dll.ChifCreate.restype = c_uint32
        status = dll.ChifCreate(byref(fhandle))
        if status != BlobReturnCodes.SUCCESS:
            if status == BlobReturnCodes.CHIFERR_NoDriver:
                raise HpIloNoChifDriverError(
                    "Error %s - No Chif Driver occurred while trying to create a channel." % status
                )
            else:
                raise HpIloInitialError("Error %s occurred while trying to create a channel." % status)
        dll.initiate_credentials.argtypes = [c_char_p, c_char_p]
        dll.initiate_credentials.restype = POINTER(c_ubyte)
        usernew = create_string_buffer(user.encode("utf-8"))
        passnew = create_string_buffer(passwrd.encode("utf-8"))
        dll.initiate_credentials(usernew, passnew)
        status = dll.ChifPing(fhandle)
        if status != BlobReturnCodes.SUCCESS:
            raise HpIloInitialError("Error %s occurred while trying to create a channel." % status)
        dll.ChifSetRecvTimeout(fhandle, 60000)
        credreturn = dll.ChifVerifyCredentials()
        if not credreturn == BlobReturnCodes.SUCCESS:
            if credreturn == BlobReturnCodes.CHIFERR_AccessDenied:
                raise HpIloChifAccessDeniedError(
                    "Error %s - Chif Access Denied occurred while trying "
                    "to open a channel to iLO. Verify iLO Credetials passed." % credreturn
                )
            else:
                raise HpIloInitialError("Error %s occurred while trying " "to open a channel to iLO" % credreturn)
        return dll, fhandle

    def uploadcommandvalidation(self, options):
        """upload command method validation function

        :param options: command line options
        :type options: list.
        """
        self.rdmc.login_select_validation(self, options)

    def definearguments(self, customparser):
        """Define command line argument for the upload command

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
            "--component",
            dest="component",
            help="""Component or binary file path to upload to the update service.""",
            default="",
            required=True,
        )
        customparser.add_argument(
            "--compsig",
            dest="componentsig",
            help="Component signature file path needed by iLO to authenticate the "
            "component file. If not provided will try to find the "
            "signature file from component file path.",
            default="",
        )
        customparser.add_argument(
            "--forceupload",
            dest="forceupload",
            action="store_true",
            help="Add this flag to force upload components with the same name already on the repository.",
            default=False,
        )
        customparser.add_argument(
            "--update_repository",
            dest="update_repository",
            action="store_false",
            help="Add this flag to skip uploading component/binary to the iLO Repository. If this "
            "flag is included with --update_srs, it will be ignored. Adding component to the "
            "repository is required to update the system reovery set.",
            default=True,
        )
        customparser.add_argument(
            "--update_target",
            dest="update_target",
            action="store_true",
            help="Add this flag if you wish to flash the component/binary.",
            default=False,
        )
        customparser.add_argument(
            "--update_srs",
            dest="update_srs",
            action="store_true",
            help="Add this flag to update the System Recovery Set with the uploaded component. "
            "NOTE: This requires an account login with the system recovery set privilege.",
            default=False,
        )
        customparser.add_argument(
            "--tpmover",
            dest="tover",
            action="store_true",
            help="If set then the TPMOverrideFlag is passed in on the associated flash operations",
            default=False,
        )
