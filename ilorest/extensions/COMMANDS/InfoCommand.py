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
""" Info Command for RDMC """

try:
    from rdmc_helper import (
        InfoMissingEntriesError,
        InvalidCommandLineErrorOPTS,
        ReturnCodes,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        InfoMissingEntriesError,
        InvalidCommandLineErrorOPTS,
        ReturnCodes,
    )

try:
    from rdmc_helper import HARDCODEDLIST
except:
    from ilorest.rdmc_helper import HARDCODEDLIST


class InfoCommand:
    """Constructor"""

    def __init__(self):
        self.ident = {
            "name": "info",
            "usage": None,
            "description": "Displays detailed "
            "information about a property within a selected type"
            "\n\texample: info property\n\n\tDisplays detailed "
            "information for several properties\n\twithin a selected "
            "type\n\texample: info property property/sub-property property\n\n\t"
            "Run without arguments to display properties \n\tthat "
            "are available for info command\n\texample: info",
            "summary": "Displays detailed information about a property within a selected type.",
            "aliases": [],
            "auxcommands": [],
        }

        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, autotest=False, help_disp=False):
        """Main info worker function

        :param line: command line input
        :type line: string.
        :param autotest: flag to determine if running automatictesting
        :type autotest: bool.
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

        self.infovalidation(options)

        if args:
            for item in args:
                if self.rdmc.app.selector.lower().startswith("bios.") and "attributes" not in item.lower():
                    if not (item.lower() in HARDCODEDLIST or "@odata" in item.lower()):
                        item = "Attributes/" + item

                outdata = self.rdmc.app.info(props=item, dumpjson=options.json, latestschema=options.latestschema)

                if autotest:
                    return outdata
                if outdata and options.json:
                    self.rdmc.ui.print_out_json(outdata)
                elif outdata:
                    self.rdmc.ui.printer(outdata)

                if not outdata:
                    raise InfoMissingEntriesError("There are no valid " "entries for info in the current instance.")
                else:
                    if len(args) > 1 and not item == args[-1]:
                        self.rdmc.ui.printer("\n************************************" "**************\n")
        else:
            results = set()
            instances = self.rdmc.app.select()
            for instance in instances:
                currdict = instance.resp.dict
                currdict = (
                    currdict["Attributes"]
                    if instance.maj_type.startswith(self.rdmc.app.typepath.defs.biostype)
                    and currdict.get("Attributes", None)
                    else currdict
                )
                results.update([key for key in currdict if key not in HARDCODEDLIST and "@odata" not in key.lower()])

            if results and autotest:
                return results
            elif results:
                self.rdmc.ui.printer("Info options:\n")
                for item in results:
                    self.rdmc.ui.printer("%s\n" % item)
            else:
                raise InfoMissingEntriesError(
                    "No info items available for this selected type." " Try running with the --latestschema flag."
                )

        self.cmdbase.logout_routine(self, options)
        # Return code
        return ReturnCodes.SUCCESS

    def infovalidation(self, options):
        """Info method validation function

        :param options: command line options
        :type options: list.
        """

        if self.rdmc.opts.latestschema:
            options.latestschema = True

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
            "--selector",
            dest="selector",
            help="Optionally include this flag to select a type to run"
            " the current command on. Use this flag when you wish to"
            " select a type without entering another command, or if you"
            " wish to work with a type that is different from the one"
            " you currently have selected.",
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
        customparser.add_argument(
            "--latestschema",
            dest="latestschema",
            action="store_true",
            help="Optionally use the latest schema instead of the one "
            "requested by the file. Note: May cause errors in some data "
            "retrieval due to difference in schema versions.",
            default=None,
        )
