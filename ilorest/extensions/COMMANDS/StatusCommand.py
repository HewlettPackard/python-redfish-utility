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
""" Status Command for RDMC """

from functools import reduce

from redfish.ris.utils import merge_dict

try:
    from rdmc_helper import InvalidCommandLineErrorOPTS, ReturnCodes
except ImportError:
    from ilorest.rdmc_helper import InvalidCommandLineErrorOPTS, ReturnCodes


class StatusCommand:
    """Constructor"""

    def __init__(self):
        self.ident = {
            "name": "status",
            "usage": None,
            "description": "Run to display all pending changes within"
            " the currently\n\tselected type that need to be"
            " committed\n\texample: status",
            "summary": "Displays all pending changes within a selected type" " that need to be committed.",
            "aliases": [],
            "auxcommands": ["SelectCommand"],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """Main status worker function

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

        self.statusvalidation(options)
        contents = self.rdmc.app.status()
        selector = self.rdmc.app.selector

        if contents and options.json:
            self.jsonout(contents)
        elif contents:
            self.outputpatches(contents, selector)
        else:
            self.rdmc.ui.printer("No changes found\n")

        # Return code
        return ReturnCodes.SUCCESS

    def jsonout(self, contents):
        """Helper function to print json output of patches

        :param contents: contents for the selection
        :type contents: string.
        """
        self.rdmc.ui.printer("Current changes found:\n")
        createdict = lambda y, x: {x: y}
        totdict = {}
        for item in contents:
            for keypath, value in item.items():
                path = keypath.split("(")[1].strip("()")
                cont = {}
                totdict[path] = cont
                for content in value:
                    val = (
                        ["List Manipulation"]
                        if content["op"] == "move"
                        else [content["value"].strip("\"'")] if len(content["value"]) else [""]
                    )
                    cont = reduce(
                        createdict,
                        reversed([path] + content["path"].strip("/").split("/") + val),
                    )
                    merge_dict(totdict, cont)
        self.rdmc.ui.print_out_json(totdict)

    def outputpatches(self, contents, selector):
        """Helper function for status for use in patches

        :param contents: contents for the selection
        :type contents: string.
        :param selector: type selected
        :type selector: string.
        """
        self.rdmc.ui.printer("Current changes found:\n")
        for item in contents:
            moveoperation = ""
            for key, value in item.items():
                if selector and key.lower().startswith(selector.lower()):
                    self.rdmc.ui.printer("%s (Currently selected)\n" % key)
                else:
                    self.rdmc.ui.printer("%s\n" % key)

                for content in value:
                    try:
                        if content["op"] == "move":
                            moveoperation = "/".join(content["path"].split("/")[1:-1])
                            continue
                    except:
                        if content[0]["op"] == "move":
                            moveoperation = "/".join(content[0]["path"].split("/")[1:-1])
                            continue
                    try:
                        if isinstance(content[0]["value"], int):
                            self.rdmc.ui.printer("\t%s=%s" % (content[0]["path"][1:], content[0]["value"]))
                        elif not isinstance(content[0]["value"], bool) and not len(content[0]["value"]) == 0:
                            if content[0]["value"][0] == '"' and content[0]["value"][-1] == '"':
                                self.rdmc.ui.printer(
                                    "\t%s=%s"
                                    % (
                                        content[0]["path"][1:],
                                        content[0]["value"][1:-1],
                                    )
                                )
                            else:
                                self.rdmc.ui.printer("\t%s=%s" % (content[0]["path"][1:], content[0]["value"]))
                        else:
                            output = content[0]["value"]

                            if not isinstance(output, bool):
                                if len(output) == 0:
                                    output = '""'

                            self.rdmc.ui.printer("\t%s=%s" % (content[0]["path"][1:], output))
                    except:
                        if isinstance(content["value"], int):
                            self.rdmc.ui.printer("\t%s=%s" % (content["path"][1:], content["value"]))
                        elif (
                            content["value"]
                            and not isinstance(content["value"], bool)
                            and not len(content["value"]) == 0
                        ):
                            if content["value"][0] == '"' and content["value"][-1] == '"':
                                self.rdmc.ui.printer("\t%s=%s" % (content["path"][1:], content["value"]))
                            else:
                                self.rdmc.ui.printer("\t%s=%s" % (content["path"][1:], content["value"]))
                        else:
                            output = content["value"]

                            if output and not isinstance(output, bool):
                                if len(output) == 0:
                                    output = '""'

                            self.rdmc.ui.printer("\t%s=%s" % (content["path"][1:], output))
                    self.rdmc.ui.printer("\n")
            if moveoperation:
                self.rdmc.ui.printer("\t%s=List Manipulation\n" % moveoperation)

    def statusvalidation(self, options):
        """Status method validation function"""

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
