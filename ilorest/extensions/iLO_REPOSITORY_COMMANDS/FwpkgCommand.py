# ##
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
# ##

# -*- coding: utf-8 -*-
""" Fwpkg Command for rdmc """

import os
import json
import sys
from random import randint
import shutil
import zipfile
import tempfile
from io import open

import ctypes
from ctypes import c_char_p, c_int, c_bool

from redfish.hpilo.risblobstore2 import BlobStore2

try:
    from rdmc_helper import (
        LOGGER,
        IncompatibleiLOVersionError,
        ReturnCodes,
        InvalidCommandLineErrorOPTS,
        InvalidFileInputError,
        UploadError,
        TaskQueueError,
        FirmwareUpdateError,
        UploadPowerOffError,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        LOGGER,
        IncompatibleiLOVersionError,
        ReturnCodes,
        InvalidCommandLineErrorOPTS,
        InvalidFileInputError,
        UploadError,
        TaskQueueError,
        FirmwareUpdateError,
    )


class FwpkgCommand:
    """Fwpkg command class"""

    def __init__(self):
        self.ident = {
            "name": "flashfwpkg",
            "usage": None,
            "description": "Run to upload and flash "
            "components from fwpkg files.\n\n\tUpload component and flashes it or sets a task"
            "queue to flash.\n\texample: flashfwpkg component.fwpkg.\n\n\t"
            "Skip extra checks before adding taskqueue. (Useful when adding "
            "many flashfwpkg taskqueue items in sequence.)\n\texample: flashfwpkg "
            "component.fwpkg --ignorechecks"
            "\n\n\t Uploading component "
            "flashfwpkg create taskqueue using target and flashes.\n\texample: flashfwpkg "
            "component.fwpkg --targets <id>",
            "summary": "Flashes fwpkg components using the iLO repository.",
            "aliases": ["fwpkg"],
            "auxcommands": [
                "UploadComponentCommand",
                "UpdateTaskQueueCommand",
                "FirmwareUpdateCommand",
                "FwpkgCommand",
            ],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """Main fwpkg worker function

        :param line: string of arguments passed in
        :type line: str.
        :param help_disp: display help flag
        :type line: bool.
        """
        if help_disp:
            self.parser.print_help()
            return ReturnCodes.SUCCESS
        try:
            if "-" in line[0] and "thirdparty" in line[0]:
                line.insert(0, "dummy_arg")
            (options, _) = self.rdmc.rdmc_parse_arglist(self, line)
        except (InvalidCommandLineErrorOPTS, SystemExit):
            if ("-h" in line) or ("--help" in line):
                return ReturnCodes.SUCCESS
            else:
                raise InvalidCommandLineErrorOPTS("")

        self.fwpkgvalidation(options)

        if self.rdmc.app.typepath.defs.isgen9:
            LOGGER.error("iLO Repository commands are only available on iLO 5.")
            raise IncompatibleiLOVersionError("iLO Repository commands are only available on iLO 5.")

        if self.rdmc.app.getiloversion() <= 5.120 and options.fwpkg.lower().startswith("iegen10"):
            raise IncompatibleiLOVersionError(
                "Please upgrade to iLO 5 1.20 or greater to ensure correct flash of this firmware."
            )

        updateservice_url = "/redfish/v1/UpdateService/"
        # Get handler to check Accept3rdPartyFirmware enabled or disabled
        get_content = self.rdmc.app.get_handler(updateservice_url, silent=True, service=True).dict
        accept3rdpartyfw = get_content["Oem"]["Hpe"]["Accept3rdPartyFirmware"]
        line_l = line[0].lower()
        if (
            line
            and ".fwpkg" not in line_l
            and (".pup" in line_l or ".hpb" in line_l or ".fup" in line_l or ".bin" in line_l)
        ):
            if not accept3rdpartyfw and not options.enable_thirdparty_fw:
                raise InvalidCommandLineErrorOPTS(
                    "Please use the option --enable_thirdparty_fw to flash Third Party Firmware Update Packages\n"
                )

        if options.enable_thirdparty_fw:
            self.rdmc.ui.printer("Enabling Third party Firmware flashing.\n")
            self.rdmc.app.patch_handler(
                updateservice_url,
                {"Oem": {"Hpe": {"Accept3rdPartyFirmware": True}}},
                silent=True,
                service=True,
            )
            if "dummy" in line[0]:
                return ReturnCodes.SUCCESS
        elif options.disable_thirdparty_fw:
            self.rdmc.ui.printer("Disabling Third party Firmware flashing.\n")
            self.rdmc.app.patch_handler(
                updateservice_url,
                {"Oem": {"Hpe": {"Accept3rdPartyFirmware": False}}},
                silent=True,
                service=True,
            )
            if "dummy" in line[0]:
                return ReturnCodes.SUCCESS

        tempdir = ""
        fwpkg_l = options.fwpkg.lower()
        if (
            not fwpkg_l.endswith(".fwpkg")
            and not fwpkg_l.endswith(".fup")
            and not fwpkg_l.endswith(".hpb")
            and not fwpkg_l.endswith(".bin")
            and not fwpkg_l.endswith(".pup")
        ):
            LOGGER.error("Invalid file type. Please make sure the file provided is a valid .fwpkg file type.")
            raise InvalidFileInputError(
                "Invalid file type. Please make sure the file provided is a valid .fwpkg file type."
            )

        try:
            components, tempdir, comptype, _ = self.preparefwpkg(self, options.fwpkg, options)
            if comptype == "D":
                LOGGER.error("Component Type D, Unable to flash this fwpkg file.")
                raise InvalidFileInputError("Unable to flash this fwpkg file.")

            elif options.targets:
                for component in components:
                    component_l = component.lower()
                    if (
                        component_l.endswith(".fwpkg")
                        or component_l.endswith(".hpb")
                        or component_l.endswith(".HPb")
                        or component_l.endswith(".bin")
                        or component_l.endswith(".fup")
                        or component_l.endswith(".pup")
                        or component_l.endswith(".zip")
                    ):
                        uploadcommand = "--component %s" % component
                    else:
                        uploadcommand = "--component %s" % os.path.join(tempdir, component)
                    if options.forceupload:
                        uploadcommand += " --forceupload"
                    self.rdmc.ui.printer("Uploading firmware: %s\n" % os.path.basename(component))
                    self.auxcommands["uploadcomp"].run(uploadcommand)
                    targets = []
                    target_list = options.targets.split(",")
                    for target in target_list:
                        target_url = "/redfish/v1/UpdateService/FirmwareInventory/" + str(target) + "/"
                        targets.append(target_url)
                    verified = self.verify_targets(options.targets)
                    if not verified:
                        self.rdmc.ui.error("Provided target was not available, Please provide valid target id\n")
                        return ReturnCodes.INVALID_TARGET_ERROR
                    path = "/redfish/v1/UpdateService/UpdateTaskQueue/"
                    try:
                        self.taskqueuecheck()
                    except TaskQueueError as excp:
                        if options.ignore:
                            self.rdmc.ui.warn(str(excp) + "\n")
                        else:
                            raise excp

                    comp = "%s" % os.path.basename(component)
                    try:
                        newtask = {
                            "Name": "Update-%s" % (str(randint(0, 1000000)),),
                            "Command": "ApplyUpdate",
                            "Filename": os.path.basename(comp),
                            "UpdatableBy": ["Bmc"],
                            "TPMOverride": options.tover,
                            "Targets": targets,
                        }
                        self.rdmc.ui.printer('payload: "%s"\n' % newtask)
                    except ValueError:
                        pass
                    self.rdmc.ui.printer('Creating task: "%s"\n' % newtask["Name"])
                    self.rdmc.app.post_handler(path, newtask)
                    self.cmdbase.logout_routine(self, options)
                    # Return code
                    return ReturnCodes.SUCCESS

            elif comptype in ["C", "BC"]:
                try:
                    self.taskqueuecheck()
                except TaskQueueError as excp:
                    if options.ignore:
                        self.rdmc.ui.warn(str(excp) + "\n")
                    else:
                        raise excp
            self.applyfwpkg(options, tempdir, components, comptype)

            if comptype == "A":
                message = "Firmware has successfully been flashed.\n"
                if "ilo" in options.fwpkg.lower():
                    message += "iLO will reboot to complete flashing. Session will be" " terminated.\n"
            elif comptype in ["B", "BC"]:
                message = (
                    "Firmware has successfully been flashed and a reboot is required for "
                    "this firmware to take effect.\n"
                )
            elif comptype in ["C", "BC"]:
                message = "This firmware is set to flash on reboot.\n"
            if ".bin" not in components[0]:
                if "blobstore" not in self.rdmc.app.redfishinst.base_url:
                    if not self.auxcommands["uploadcomp"].wait_for_state_change():
                        # Failed to upload the component.
                        raise FirmwareUpdateError("Error while processing the component.")

            self.rdmc.ui.printer(message)

        except (FirmwareUpdateError, UploadError) as excp:
            raise excp
        except UploadPowerOffError:
            self.rdmc.ui.error("Server power is On,Kindly Power Off the server,to be able to flash the B- component \n")
            return ReturnCodes.UPLOAD_POWEROFF_ERROR

        finally:
            if tempdir:
                shutil.rmtree(tempdir)

        self.cmdbase.logout_routine(self, options)
        # Return code
        return ReturnCodes.SUCCESS

    def taskqueuecheck(self):
        """Check taskqueue for potential issues before starting"""

        select = "ComputerSystem."
        results = self.rdmc.app.select(selector=select, path_refresh=True)

        try:
            results = results[0]
        except:
            pass

        powerstate = results.resp.dict["PowerState"]
        tasks = self.rdmc.app.getcollectionmembers("/redfish/v1/UpdateService/UpdateTaskQueue/")

        for task in tasks:
            if task["State"] == "Exception":
                raise TaskQueueError(
                    "Exception found in taskqueue which will "
                    "prevent firmware from flashing. Please run "
                    "iLOrest command: taskqueue --cleanqueue to clear"
                    " any errors before continuing."
                )
            if task["UpdatableBy"] == "Uefi" and not powerstate == "Off" or task["Command"] == "Wait":
                raise TaskQueueError(
                    "Taskqueue item found that will "
                    "prevent firmware from flashing immediately. Please "
                    "run iLOrest command: taskqueue --resetqueue to "
                    "reset the queue if you wish to flash immediately "
                    "or include --ignorechecks to add this firmware "
                    "into the task queue anyway."
                )
        if tasks:
            self.rdmc.ui.warn(
                "Items are in the taskqueue that may delay the flash until they "
                "are finished processing. Use the taskqueue command to monitor updates.\n"
            )

    def is_ripcord(self):
        chassis_path = "/redfish/v1/Chassis/1/"
        chassis_info = self.rdmc.app.get_handler(chassis_path, silent=True)
        if (
            chassis_info.obj["SKU"] == "RIPCORD"
            or "Gen12" in chassis_info.obj["Model"]
            or "DL340" in chassis_info.obj["Model"]
            or "DL320" in chassis_info.obj["Model"]
        ):
            return True
        else:
            return False

    def get_comp_type(self, payload, cmdname, targetupdate):
        """Get's the component type and returns it

        :param payload: json payload of .fwpkg file
        :type payload: dict.
        :returns: returns the type of component. Either A,B,C, or D.
        :rtype: string
        """
        ctype = ""
        if "Uefi" in payload["UpdatableBy"] and "RuntimeAgent" in payload["UpdatableBy"]:
            ctype = "D"
        elif "Uefi" in payload["UpdatableBy"] and "Bmc" in payload["UpdatableBy"]:
            fw_url = "/redfish/v1/UpdateService/FirmwareInventory/" + "?$expand=."
            data = self.rdmc.app.get_handler(fw_url, silent=True).dict["Members"]
            da_flag = False
            cc_flag = False
            if data is not None:
                type_set = None
                for fw in data:
                    for device in payload["Devices"]["Device"]:
                        if fw["Oem"]["Hpe"].get("Targets") is not None:
                            if device["Target"] in fw["Oem"]["Hpe"]["Targets"]:
                                # print devicecontext in debugger
                                LOGGER.info("DeviceContext", fw["Oem"]["Hpe"]["DeviceContext"])
                                if (
                                    "Slot=" in fw["Oem"]["Hpe"]["DeviceContext"]
                                    and ":" in fw["Oem"]["Hpe"]["DeviceContext"]
                                ):
                                    cc_flag = True
                                else:
                                    da_flag = True
                if cc_flag and da_flag:
                    ctype = "BC"
                    type_set = True
                elif cc_flag and not da_flag:
                    ctype = "B"
                    type_set = True
                elif not cc_flag and da_flag:
                    ctype = "C"
                    type_set = True
                if type_set is None:
                    LOGGER.error("Component type is not identified, Please check if the particular H/W is present")
                    ilo_ver_int = self.rdmc.app.getiloversion()
                    ilo_ver = str(ilo_ver_int)
                    error_msg = (
                        "Cannot flash the component on this server, check whether the component is fwpkg-v2 "
                        "or check whether the server is iLO"
                    )
                    if ilo_ver_int >= 6:
                        error_msg = (
                            error_msg + ilo_ver[0] + ", FW is above 1.50 or the particular drive HW is present\n"
                        )
                    else:
                        error_msg = (
                            error_msg + ilo_ver[0] + ", FW is above 2.30 or the particular drive HW is present\n"
                        )
                    raise IncompatibleiLOVersionError(error_msg)
        else:
            b_minus_flag = False
            for device in payload["Devices"]["Device"]:
                for image in device["FirmwareImages"]:
                    if "DirectFlashOk" not in list(image.keys()):
                        raise InvalidFileInputError("Cannot flash this firmware.")
                    if "ServerPowerOff" in image and image["ServerPowerOff"]:
                        b_minus_flag = True
                    if not b_minus_flag:
                        if image["DirectFlashOk"]:
                            ctype = "A"
                            if image["ResetRequired"]:
                                ctype = "B"
                                break
                        elif image["UefiFlashable"]:
                            ctype = "C"
                            break
                        else:
                            ctype = "D"
                    elif b_minus_flag and cmdname == "uploadcomp" and not targetupdate:
                        if image["DirectFlashOk"]:
                            ctype = "A"
                            if image["ResetRequired"]:
                                ctype = "B"
                                break
                        elif image["UefiFlashable"]:
                            ctype = "C"
                            break
                        else:
                            ctype = "D"

                    else:
                        systems_path = "/redfish/v1/Systems/1/"
                        systems_info = self.rdmc.app.get_handler(systems_path, silent=True)
                        if systems_info.obj["PowerState"] == "On" and not (
                            self.is_ripcord() and "U69" in image["FileName"]
                        ):
                            raise UploadPowerOffError(
                                "Server power is On, Kindly power off the server to be able to be flash the B- component on the server \n"
                            )

                        else:
                            if self.is_ripcord() and "U69" in image["FileName"]:
                                LOGGER.info(
                                    "Flashing the B- Bios component , Please perform cold reboot of the server for iLO to complete the flashing ."
                                )
                            ctype = "B"
                    b_minus_flag = False
        LOGGER.info("Component Type identified is {}".format(ctype))
        return ctype

    @staticmethod
    def preparefwpkg(self, pkgfile, options):
        """Prepare fwpkg file for flashing

        :param pkgfile: Location of the .fwpkg file
        :type pkgfile: string.
        :returns: returns the files needed to flash, directory they are located
                                                            in, and type of file.
        :rtype: string, string, string
        """
        files = []
        imagefiles = []
        payloaddata = None
        tempdir = tempfile.mkdtemp()
        pldmflag = False
        pkgfile_l = pkgfile.lower()
        target = False
        if "update_target" in options:
            if options.update_target:
                target = True
            else:
                target = False

        if (
            not pkgfile_l.endswith(".fup")
            and not pkgfile_l.endswith(".hpb")
            and not pkgfile_l.endswith(".bin")
            and not pkgfile_l.endswith(".pup")
        ):
            try:
                zfile = zipfile.ZipFile(pkgfile)
                zfile.extractall(tempdir)
                zfile.close()
            except Exception as excp:
                raise InvalidFileInputError("Unable to unpack file. " + str(excp))

            files = os.listdir(tempdir)

            if "payload.json" in files:
                with open(os.path.join(tempdir, "payload.json"), encoding="utf-8") as pfile:
                    data = pfile.read()
                payloaddata = json.loads(data)
            else:
                raise InvalidFileInputError("Unable to find payload.json in fwpkg file.")

        if (
            not pkgfile_l.endswith(".fup")
            and not pkgfile_l.endswith(".hpb")
            and not pkgfile_l.endswith(".bin")
            and not pkgfile_l.endswith(".pup")
        ):
            comptype = self.auxcommands["flashfwpkg"].get_comp_type(payloaddata, self.cmdbase.name, target)
        else:
            comptype = "A"

        results = self.rdmc.app.getprops(selector="UpdateService.", props=["Oem/Hpe/Capabilities"])
        if comptype in ["C", "BC"]:
            imagefiles = [self.auxcommands["flashfwpkg"].type_c_change(tempdir, pkgfile)]
        else:
            if (
                not pkgfile_l.endswith("fup")
                and not pkgfile_l.endswith(".hpb")
                and not pkgfile_l.endswith(".bin")
                and not pkgfile_l.endswith(".pup")
            ):
                for device in payloaddata["Devices"]["Device"]:
                    for firmwareimage in device["FirmwareImages"]:
                        if "PLDMImage" in firmwareimage and firmwareimage["PLDMImage"]:
                            pldmflag = True
                        if firmwareimage["FileName"] not in imagefiles:
                            imagefiles.append(firmwareimage["FileName"])

        if (
            "blobstore" in self.rdmc.app.redfishinst.base_url
            and comptype in ["A", "B", "BC"]
            and results
            and "UpdateFWPKG" in results[0]["Oem"]["Hpe"]["Capabilities"]
        ):
            dll = BlobStore2.gethprestchifhandle()
            dll.isFwpkg20.argtypes = [c_char_p, c_int]
            dll.isFwpkg20.restype = c_bool

            with open(pkgfile, "rb") as fwpkgfile:
                fwpkgdata = fwpkgfile.read()

            fwpkg_buffer = ctypes.create_string_buffer(fwpkgdata)
            if dll.isFwpkg20(fwpkg_buffer, 2048):
                imagefiles = [pkgfile]
                tempdir = ""
        if (
            pkgfile_l.endswith(".hpb")
            or pkgfile_l.endswith(".fup")
            or pkgfile_l.endswith(".pup")
            or pkgfile_l.endswith(".bin")
        ):
            imagefiles = [pkgfile]

        elif self.rdmc.app.getiloversion() > 5.230 and payloaddata.get("PackageFormat") == "FWPKG-v2":
            imagefiles = [pkgfile]
        return imagefiles, tempdir, comptype, pldmflag

    def type_c_change(self, tdir, pkgloc):
        """Special changes for type C

        :param tempdir: path to temp directory
        :type tempdir: string.
        :param components: components to upload
        :type components: list.

        :returns: The location of the type C file to upload
        :rtype: string.
        """

        shutil.copy(pkgloc, tdir)

        fwpkgfile = os.path.split(pkgloc)[1]
        zfile = fwpkgfile[:-6] + ".zip"
        zipfileloc = os.path.join(tdir, zfile)

        os.rename(os.path.join(tdir, fwpkgfile), zipfileloc)

        return zipfileloc

    def applyfwpkg(self, options, tempdir, components, comptype):
        """Apply the component to iLO

        :param options: command line options
        :type options: list.
        :param tempdir: path to temp directory
        :type tempdir: string.
        :param components: components to upload
        :type components: list.
        :param comptype: type of component. Either A,B,C, or D.
        :type comptype: str.
        """

        for component in components:
            component_l = component.lower()
            if (
                component_l.endswith(".fwpkg")
                or component_l.endswith(".hpb")
                or component_l.endswith(".bin")
                or component_l.endswith(".fup")
                or component_l.endswith(".pup")
                or component_l.endswith(".zip")
            ):
                uploadcommand = "--component %s" % component
            else:
                uploadcommand = "--component %s" % os.path.join(tempdir, component)

            if options.forceupload:
                uploadcommand += " --forceupload"
            if comptype in ["A", "B"]:
                LOGGER.info("Setting --update_target --update_repository options as it is A or B")
                uploadcommand += " --update_target --update_repository"
            elif comptype in ["BC"]:
                LOGGER.info("Setting --update_target --update_repository options and " "calling uploadcomp once.")
                uploadcommand1 = uploadcommand + " --update_repository --update_target"
                if options.tover:
                    LOGGER.info("Setting --tpmover if tpm enabled.")
                    uploadcommand1 += " --tpmover"
                ret = self.auxcommands["uploadcomp"].run(uploadcommand1)
                if ret != ReturnCodes.SUCCESS:
                    raise UploadError("Error uploading component.")
                LOGGER.info(
                    "Continuing the flow with --component such that uploadcomp"
                    " is called again to upload component to the repository."
                )
            if options.update_srs:
                LOGGER.info("Setting --update_srs to store as recovery set.")
                uploadcommand += " --update_srs"
            if options.tover:
                LOGGER.info("Setting --tpmover if tpm enabled.")
                uploadcommand += " --tpmover"
            if "update_repository" not in uploadcommand:
                self.rdmc.ui.printer("Uploading firmware: %s\n" % os.path.basename(component))
            if "update_target" in uploadcommand:
                self.rdmc.ui.printer("Flashing firmware: %s\n" % os.path.basename(component))
            try:
                ret = self.auxcommands["uploadcomp"].run(uploadcommand)
                if ret != ReturnCodes.SUCCESS:
                    raise UploadError
            except UploadError:
                if comptype in ["A", "B", "BC"]:
                    select = self.rdmc.app.typepath.defs.hpilofirmwareupdatetype
                    results = self.rdmc.app.select(selector=select)

                    try:
                        results = results[0]
                    except:
                        pass

                    if results:
                        update_path = results.resp.request.path
                        error = self.rdmc.app.get_handler(update_path, silent=True)
                        self.auxcommands["firmwareupdate"].printerrmsg(error)
                    else:
                        raise FirmwareUpdateError("Error occurred while updating the firmware.")
                else:
                    raise UploadError("Error uploading component.")

            if comptype in ["C", "BC"]:
                self.rdmc.ui.warn("Setting a taskqueue item to flash UEFI flashable firmware.\n")
                path = "/redfish/v1/updateservice/updatetaskqueue"
                newtask = {
                    "Name": "Update-%s" % (str(randint(0, 1000000)),),
                    "Command": "ApplyUpdate",
                    "Filename": os.path.basename(component),
                    "UpdatableBy": ["Uefi"],
                    "TPMOverride": options.tover,
                }
                res = self.rdmc.app.post_handler(path, newtask)

                if res.status != 201:
                    raise TaskQueueError("Not able create UEFI task.\n")
                else:
                    self.rdmc.ui.printer(
                        "Created UEFI Task for Component " + os.path.basename(component) + " successfully.\n"
                    )

    def verify_targets(self, target):
        target_list = target.split(",")
        for target in target_list:
            try:
                target_url = "/redfish/v1/UpdateService/FirmwareInventory/" + target
                dd = self.rdmc.app.get_handler(target_url, service=True, silent=True)
                if dd.status == 404:
                    return False
            except:
                return False
        return True

    def fwpkgvalidation(self, options):
        """fwpkg validation function

        :param options: command line options
        :type options: list.
        """
        self.rdmc.login_select_validation(self, options)

    def definearguments(self, customparser):
        """Wrapper function for new command main function

        :param customparser: command line input
        :type customparser: parser.
        """
        if not customparser:
            return

        self.cmdbase.add_login_arguments_group(customparser)

        customparser.add_argument("fwpkg", help="""fwpkg file path""", metavar="[FWPKG]", default=None)
        customparser.add_argument(
            "--forceupload",
            dest="forceupload",
            action="store_true",
            help="Add this flag to force upload firmware with the same name already on the repository.",
            default=False,
        )
        customparser.add_argument(
            "--ignorechecks",
            dest="ignore",
            action="store_true",
            help="Add this flag to ignore all checks to the taskqueue before attempting to process the .fwpkg file.",
            default=False,
        )
        customparser.add_argument(
            "--enable_thirdparty_fw",
            dest="enable_thirdparty_fw",
            action="store_true",
            help="Add this flag to enable flashing third party firmware to server.",
            default=False,
        )
        customparser.add_argument(
            "--disable_thirdparty_fw",
            dest="disable_thirdparty_fw",
            action="store_true",
            help="Add this flag to disable flashing third party firmware to server.",
            default=False,
        )
        customparser.add_argument(
            "--tpmover",
            dest="tover",
            action="store_true",
            help="If set then the TPMOverrideFlag is passed in on the associated flash operations",
            default=False,
        )
        customparser.add_argument(
            "--update_srs",
            dest="update_srs",
            action="store_true",
            help="Add this flag to update the System Recovery Set with the uploaded firmware. "
            "NOTE: This requires an account login with the system recovery set privilege.",
            default=False,
        )
        customparser.add_argument(
            "--targets",
            help="If targets value specify a comma separated\t" "firmwareinventory id only",
            metavar="targets_indices",
        )
