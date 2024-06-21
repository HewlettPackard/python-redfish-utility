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
# BMN
# ##

# -*- coding: utf-8 -*-
""" Get Inventory Command for rdmc """


try:
    from rdmc_helper import (
        IncompatibleiLOVersionError,
        InvalidCommandLineErrorOPTS,
        ReturnCodes,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        IncompatibleiLOVersionError,
        InvalidCommandLineErrorOPTS,
        ReturnCodes,
    )

from redfish.ris.resp_handler import ResponseHandler


class GetInventoryCommand:
    """GetInventory command class"""

    def __init__(self):
        self.ident = {
            "name": "getinventory",
            "usage": None,
            "description": "Get complete inventory"
            "data from the iLO, including iLO Repo and install set."
            "\n\texample: getinventory all",
            "summary": "Get complete inventory data from the iLO.",
            "aliases": [],
            "auxcommands": [],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()
        self.response_handler = None

    def run(self, line, help_disp=False):
        """Main GetInventory worker function
        :param line: string of arguments passed in
        :type line: str.
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

        self.getinventoryvalidation(options)
        self.response_handler = ResponseHandler(
            self.rdmc.app.validationmanager,
            self.rdmc.app.typepath.defs.messageregistrytype,
        )
        if self.rdmc.app.typepath.defs.isgen9:
            raise IncompatibleiLOVersionError("GetInventory command is " "available only on iLO 5 node.")

        alldata = {}
        results = {}

        # If both are not set, then we will get both inventory and repo data
        if not options.inventory and not options.repo_data and not options.sut:
            options.inventory = True
            options.repo_data = True
            options.sut = True

        if options.inventory:
            try:
                collectiondata = self.rdmc.app.get_handler(
                    "/redfish/v1/updateservice/firmwareinventory", service=False, silent=True
                ).dict
                members = self.rdmc.app.getcollectionmembers(collectiondata.get("@odata.id"))
                collectiondata.update({"Members": members})
                alldata.update({"firmwareInventory": collectiondata})
            except:
                alldata.update({"firmwareInventory": {}})
            try:
                collectiondata = self.rdmc.app.get_handler(
                    "/redfish/v1/updateservice/softwareinventory", service=False, silent=True
                ).dict
                members = self.rdmc.app.getcollectionmembers(collectiondata.get("@odata.id"))
                collectiondata.update({"Members": members})
                alldata.update({"softwareInventory": collectiondata})
            except:
                alldata.update({"softwareInventory": {}})

            try:
                members = self.rdmc.app.get_handler("/redfish/v1/systems/", service=False, silent=True).dict["Members"]
                systemdata = {}
                rootsystem = {}
                for id in members:
                    for mem_id in id.values():
                        results = self.rdmc.app.get_handler(mem_id, service=True, silent=True).dict
                        id = results["Id"]
                        if id != "1":
                            rootsystem.update({"systems%s" % id: results})
                            systemdata.update({"systems": rootsystem})
                            alldata.update(systemdata)
                        if id == "1":
                            alldata.update({"systems1": results})
            except:
                alldata.update({"systems": {}})

            try:
                sutlocation = alldata.get("systems1").get("Oem").get("Hpe").get("Links")
            except:
                if results:
                    sutlocation = next(iter(results)).dict.get("Links")
            for key, value in list(sutlocation.items()):
                if key == "SUT":
                    result2 = self.rdmc.app.get_handler(value.get("@odata.id"), service=False, silent=True)

                    if result2.status == 200:
                        alldata["SUT"] = result2.dict
                    else:
                        return self.printlastfailedresult(result2)
                    break
            try:
                collectiondata = self.rdmc.app.get_handler(
                    "/redfish/v1/Managers/1/EthernetInterfaces/", service=False, silent=True
                ).dict
                members = self.rdmc.app.getcollectionmembers(collectiondata.get("@odata.id"))
                collectiondata.update({"Members": members})
                alldata.update({"EthernetInterfaces": collectiondata})
            except:
                alldata.update({"EthernetInterfaces": {}})

            try:
                results = self.rdmc.app.select(selector="HpeiLODateTime.", path_refresh=True)
                alldata["DateTime"] = next(iter(results)).resp.dict
            except:
                alldata.update({"DateTime": {}})

            try:
                collectiondata = self.rdmc.app.get_handler(
                    "/redfish/v1/UpdateService/", service=False, silent=True
                ).dict
                alldata.update({"DowngradePolicy": collectiondata})
            except:
                alldata.update({"DowngradePolicy": {}})

        if options.sut:
            if "system1" not in alldata:
                try:
                    results = self.rdmc.app.get_handler("/redfish/v1/systems/", service=False, silent=True).dict
                    members = results["Members"]
                    for id in members:
                        for mem_id in id.values():
                            results = self.rdmc.app.get_handler(mem_id, service=True, silent=True).dict
                            id = results["Id"]
                            if id == "1":
                                alldata.update({"systems1": results})
                except:
                    alldata.update({"systems1": {}})
            else:
                _ = alldata["systems1"]

            if alldata.get("systems1"):
                try:
                    sutlocation = alldata.get("systems1").get("Oem").get("Hpe").get("Links")
                except:
                    if results:
                        sutlocation = next(iter(results)).dict.get("Links")
                for key, value in list(sutlocation.items()):
                    if key == "SUT":
                        result2 = self.rdmc.app.get_handler(value.get("@odata.id"), service=False, silent=True)

                        if result2.status == 200:
                            alldata["SUT"] = result2.dict
                        else:
                            return self.printlastfailedresult(result2)
                        break

        if options.repo_data:
            try:
                collectiondata = self.rdmc.app.get_handler(
                    "/redfish/v1/UpdateService/installsets", service=False, silent=True
                ).dict
                members = self.rdmc.app.getcollectionmembers(collectiondata.get("@odata.id"))
                if len(members) == 0:
                    members = []
                collectiondata.update({"Members": members})
                alldata.update({"installsets": collectiondata})
            except:
                alldata.update({"installsets": []})

            try:
                collectiondata = self.rdmc.app.get_handler(
                    "/redfish/v1/UpdateService/updatetaskqueue", service=False, silent=True
                ).dict
                members = self.rdmc.app.getcollectionmembers(collectiondata.get("@odata.id"))
                if len(members) == 0:
                    members = []
                collectiondata.update({"Members": members})
                alldata.update({"updatetaskqueue": collectiondata})
            except:
                alldata.update({"updatetaskqueue": []})

            if self.rdmc.app.getiloversion(skipschemas=True) >= 5.130:
                try:
                    collectiondata = self.rdmc.app.get_handler(
                        "/redfish/v1/UpdateService/maintenancewindows", service=False, silent=True
                    ).dict
                    members = self.rdmc.app.getcollectionmembers(collectiondata.get("@odata.id"))
                    if len(members) == 0:
                        members = []
                    collectiondata.update({"Members": members})
                    alldata.update({"maintenancewindows": collectiondata})
                except:
                    alldata.update({"maintenancewindows": []})

            comp_repo_url = "/redfish/v1/UpdateService/ComponentRepository/" + "?$expand=."
            try:
                members = self.rdmc.app.get_handler(comp_repo_url, silent=True, service=True).dict
                alldata.update({"ComponentRepository": members})
            except:
                alldata.update({"ComponentRepository": {}})

        self.rdmc.ui.print_out_json(alldata)

        self.cmdbase.logout_routine(self, options)
        # Return code
        return ReturnCodes.SUCCESS

    def combineinstances(self, data, alldata, name, coll=None):
        """combine the data into one json dictionary"""
        if coll:
            coll = coll.resp.dict
            finaldata = []
            if "Members" in coll:
                for member in data:
                    finaldata.append(member.resp.dict)
                coll["Members"] = finaldata
            alldata[name] = coll
        elif len(data) > 1:
            alldata.update({name: {"Members": []}})
            for item in data:
                alldata[name]["Members"].append(item.resp.dict)
        else:
            alldata.update({name: {"Members": next(iter(data)).resp.dict}})

    def printlastfailedresult(self, results):
        """print last failed result function"""
        self.response_handler.output_resp(results)

        return ReturnCodes.NO_CONTENTS_FOUND_FOR_OPERATION

    def getinventoryvalidation(self, options):
        """get inventory validation function
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
            "-i",
            "--inventory",
            dest="inventory",
            action="store_true",
            help="""Use this option to get only the inventory data.""",
            default=False,
        )
        customparser.add_argument(
            "-s",
            "--sut",
            dest="sut",
            action="store_true",
            help="""Use this option to get only SUT data from iLO.""",
            default=False,
        )
        customparser.add_argument(
            "-r",
            "--repo_data",
            dest="repo_data",
            action="store_true",
            help="""Use this option to get only iLO repository, install set """ """and Task queue details.""",
            default=False,
        )
