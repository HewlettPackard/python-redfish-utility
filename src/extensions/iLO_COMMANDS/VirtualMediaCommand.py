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
""" Virtual Media Command for rdmc """

try:
    from rdmc_helper import (
        UI,
        IloLicenseError,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        ReturnCodes,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        ReturnCodes,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        UI,
        IloLicenseError,
    )

from redfish.ris import rmc_helper


class VirtualMediaCommand:
    """ Changes the iscsi configuration for the server that is currently """ """ logged in """

    def __init__(self):
        self.ident = {
            "name": "virtualmedia",
            "usage": None,
            "description": "Run without"
            " arguments to view the available virtual media sources."
            "\n\tExample: virtualmedia\n\n\tInsert virtual media and "
            "set to boot on next restart.\n\texample: virtualmedia 2 "
            "http://xx.xx.xx.xx/vm.iso --bootnextreset\n\n\tRemove "
            "current inserted media.\n\texample: virtualmedia 2 --remove",
            "summary": "Command for inserting and removing virtual media.",
            "aliases": [],
            "auxcommands": [
                "GetCommand",
                "SetCommand",
                "SelectCommand",
                "RebootCommand",
            ],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """Main iscsi configuration worker function

        :param line: string of arguments passed in
        :type line: str.
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

        if len(args) > 2:
            raise InvalidCommandLineError(
                "Invalid number of parameters. " "virtualmedia command takes a maximum of 2 parameters."
            )
        else:
            self.virtualmediavalidation(options)

        resp = self.rdmc.app.get_handler("/rest/v1/Managers/1/VirtualMedia/1", silent=True)

        if not resp.status == 200:
            raise IloLicenseError("")

        self.auxcommands["select"].run("VirtualMedia.")
        ilover = self.rdmc.app.getiloversion()

        if self.rdmc.app.monolith.is_redfish:
            isredfish = True
            paths = self.auxcommands["get"].getworkerfunction("@odata.id", options, results=True, uselist=False)
            ids = self.auxcommands["get"].getworkerfunction("Id", options, results=True, uselist=False)
            paths = {ind: path for ind, path in enumerate(paths)}
            ids = {ind: id for ind, id in enumerate(ids)}
            for path in paths:
                paths[path] = paths[path]["@odata.id"]
            # paths = self.uniquevalmaker(paths)
        else:
            isredfish = False
            paths = self.auxcommands["get"].getworkerfunction("links/self/href", options, results=True, uselist=False)
            ids = self.auxcommands["get"].getworkerfunction("Id", options, results=True, uselist=False)
            paths = {ind: path for ind, path in enumerate(paths)}
            ids = {ind: id for ind, id in enumerate(ids)}
            for path in paths:
                paths[path] = paths[path]["links"]["self"]["href"]
        # To keep indexes consistent between versions
        if not list(ids.keys())[0] == list(list(ids.values())[0].values())[0]:
            finalpaths = {}
            for path in paths:
                finalpaths.update({int(list(ids[path].values())[0]): paths[path]})
            paths = finalpaths
        if options.removevm:
            self.vmremovehelper(args, options, paths, isredfish, ilover)
        elif len(args) == 2:
            self.vminserthelper(args, options, paths, isredfish, ilover)
        elif options.bootnextreset:
            self.vmbootnextreset(args, paths)
        elif not args:
            self.vmdefaulthelper(options, paths)
        else:
            raise InvalidCommandLineError("Invalid parameter(s). Please run" " 'help virtualmedia' for parameters.")

        self.cmdbase.logout_routine(self, options)
        # Return code
        return ReturnCodes.SUCCESS

    def uniquevalmaker(self, paths):
        unique_values = set(paths.values())

        res = {}
        i = 0
        for val in unique_values:
            if val.endswith("/"):
                val = val[:-1]
                res[i] = val
                i = i + 1
            else:
                res[i] = val
                i = i + 1
        i = 0
        res1 = dict()
        for val in set(res.values()):
            res1[i] = val
            i = i + 1
        return res1

    def vmremovehelper(self, args, options, paths, isredfish, ilover):
        """Worker function to remove virtual media

        :param args: arguments passed from command line
        :type args: list
        :param paths: virtual media paths
        :type paths: list
        :param isredfish: redfish flag
        :type isredfish: bool
        :param ilover: iloversion
        :type ilover: int
        :param options: command line options
        :type options: list.
        """
        path = None

        if isredfish:
            path, body = self.vmredfishhelper("remove", args[0])
        else:
            if ilover <= 4.230:
                body = {"Image": None}
            else:
                body = {"Action": "EjectVirtualMedia", "Target": "/Oem/Hp"}

        try:
            path = paths[int(args[0])] if not path else path
        except:
            raise InvalidCommandLineError(
                "Invalid input value for virtual "
                "media please run the command with no "
                "arguments for possible values."
            )

        if ilover <= 4.230:
            self.rdmc.app.patch_handler(path, body)
        else:
            self.rdmc.app.post_handler(path, body)

        if options.reboot:
            self.auxcommands["reboot"].run(options.reboot)

    def vminserthelper(self, args, options, paths, isredfish, ilover):
        """Worker function to insert virtual media

        :param args: arguments passed from command line
        :type args: list
        :param paths: virtual media paths
        :type paths: list
        :param isredfish: redfish flag
        :type isredfish: bool
        :param ilover: iloversion
        :type ilover: int
        :param options: command line options
        :type options: list.
        """
        path = None
        if not args[1].startswith("http://") and not args[1].startswith("https://"):
            raise InvalidCommandLineError("Virtual media path must be a URL.")
        if args[0] in "1":
            if not args[1].endswith(".img"):
                raise InvalidCommandLineError("Only .img files are allowed")
        if args[0] in "2":
            if not args[1].endswith(".iso"):
                raise InvalidCommandLineError("Only .iso files are allowed")
        if isredfish:
            path, body = self.vmredfishhelper("insert", args[0], args[1])
        else:
            if ilover <= 4.230:
                body = {"Image": args[1]}
            else:
                body = {
                    "Action": "InsertVirtualMedia",
                    "Target": "/Oem/Hp",
                    "Image": args[1],
                }

        try:
            path = paths[int(args[0])] if not path else path
        except:
            raise InvalidCommandLineError(
                "Invalid input value for virtual "
                "media please run the command with "
                "no arguments for possible values."
            )

        if ilover <= 4.230:
            self.rdmc.app.patch_handler(path, body)
        else:
            try:
                results = self.rdmc.app.post_handler(path, body)
                if results.status == 200:
                    if options.bootnextreset:
                        self.vmbootnextreset(args, paths)
                    if options.reboot:
                        self.auxcommands["reboot"].run(options.reboot)
                    return ReturnCodes.SUCCESS
            except rmc_helper.IloLicenseError:
                raise IloLicenseError("Error:License Key Required\n")
            # except Exception:
            #     self.rdmc.ui.printer("Please unmount/Eject virtual media and try it again\n")

    def vmdefaulthelper(self, options, paths):
        """Worker function to reset virtual media config to default

        :param paths: virtual media paths
        :type paths: list
        :param options: command line options
        :type options: list.
        """
        images = {}
        count = 0
        mediatypes = self.auxcommands["get"].getworkerfunction("MediaTypes", options, results=True, uselist=False)
        ids = self.auxcommands["get"].getworkerfunction("Id", options, results=True, uselist=False)
        ids = {ind: id for ind, id in enumerate(ids)}
        mediatypes = {ind: med for ind, med in enumerate(mediatypes)}
        # To keep indexes consistent between versions
        if not list(ids.keys())[0] == list(list(ids.values())[0].values())[0]:
            finalmet = {}
            for mount in mediatypes:
                finalmet.update({int(list(ids[mount].values())[0]): mediatypes[mount]})
            mediatypes = finalmet

        for path in paths:
            count += 1
            image = self.rdmc.app.get_handler(paths[path], service=True, silent=True)
            image = image.dict["Image"]
            images.update({path: image})

        self.rdmc.ui.printer("Available Virtual Media Options:\n")
        if getattr(options, "json", False):
            json_str = dict()
            json_str["MediaTypes"] = dict()
        # else:
        #     self.rdmc.ui.printer("Available Virtual Media Options:\n")

        for image in images:
            media = ""

            if images[image]:
                imagestr = images[image]
            else:
                imagestr = "None"

            for medtypes in mediatypes[image]["MediaTypes"]:
                media += medtypes + " "

            if getattr(options, "json", False):
                json_str["MediaTypes"][str(media)] = imagestr
            else:
                self.rdmc.ui.printer(
                    "[%s] Media Types Available: %s Image Inserted:" " %s\n" % (str(image), str(media), imagestr)
                )
        if getattr(options, "json", False):
            UI().print_out_json(json_str)

    def vmbootnextreset(self, args, paths):
        """Worker function to boot virtual media on next serverreset

        :param args: arguments passed from command line
        :type args: list
        :param paths: all virtual media paths
        :type paths: list
        """
        try:
            path = paths[int(args[0])]
        except:
            raise InvalidCommandLineError(
                "Invalid input value for virtual media"
                " please run the command with no "
                "arguments for possible values."
            )

        self.rdmc.app.patch_handler(
            path,
            {"Oem": {self.rdmc.app.typepath.defs.oemhp: {"BootOnNextServerReset": True}}},
            service=True,
            silent=True,
        )

    def vmredfishhelper(self, action, number, image=None):
        """Redfish version of the worker function

        :param action: action item
        :type action: str
        :param number: virtual media ID
        :type number: int
        """

        results = self.rdmc.app.select(selector="VirtualMedia.")
        bodydict = None

        try:
            for result in results:
                if result.resp.dict["Id"] == number:
                    bodydict = result.resp.dict
                    break
        except:
            pass

        if not bodydict:
            raise InvalidCommandLineError(
                "Invalid input value for virtual media"
                " please run the command with no "
                "arguments for possible values."
            )
        if action == "remove" and not bodydict["Inserted"]:
            raise InvalidCommandLineError(
                "Invalid input value for virtual media."
                " No media present in this drive to unmount. Please recheck "
                "arguments for possible values."
            )

        if action == "insert" and image:
            for item in bodydict["Oem"][self.rdmc.app.typepath.defs.oemhp]["Actions"]:
                if "InsertVirtualMedia" in item:
                    if self.rdmc.app.typepath.defs.isgen10:
                        action = item.split("#")[-1]
                    else:
                        action = "InsertVirtualMedia"

                    path = bodydict["Oem"][self.rdmc.app.typepath.defs.oemhp]["Actions"][item]["target"]
                    body = {"Action": action, "Image": image}
                    break
        elif action == "remove":
            for item in bodydict["Oem"][self.rdmc.app.typepath.defs.oemhp]["Actions"]:
                if "EjectVirtualMedia" in item:
                    if self.rdmc.app.typepath.defs.isgen10:
                        action = item.split("#")[-1]
                    else:
                        action = "EjectVirtualMedia"

                    path = bodydict["Oem"][self.rdmc.app.typepath.defs.oemhp]["Actions"][item]["target"]
                    body = {"Action": action}
                    break
        else:
            return None, None

        return path, body

    def virtualmediavalidation(self, options):
        """sigrecomputevalidation method validation function

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
            "--reboot",
            dest="reboot",
            help="Use this flag to perform a reboot command function after"
            " completion of operations.  For help with parameters and"
            " descriptions regarding the reboot flag, run help reboot.",
            default=None,
        )
        customparser.add_argument(
            "--remove",
            dest="removevm",
            action="store_true",
            help="Use this flag to remove the media from the selection.",
            default=False,
        )
        customparser.add_argument(
            "--bootnextreset",
            dest="bootnextreset",
            action="store_true",
            help="Use this flag if you wish to boot from the image on "
            "next server reboot. NOTE: The image will be ejected "
            "automatically on the second server reboot so that the server "
            "does not boot to this image twice.",
            default=False,
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
