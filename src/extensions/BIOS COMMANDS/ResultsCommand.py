###
# Copyright 2020 Hewlett Packard Enterprise, Inc. All rights reserved.
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
""" Results Command for rdmc """

import sys

from argparse import ArgumentParser

from redfish.ris.resp_handler import ResponseHandler

from redfish.ris.rmc_helper import EmptyRaiseForEAFP

from rdmc_base_classes import RdmcCommandBase, add_login_arguments_group, login_select_validation, \
                                logout_routine
from rdmc_helper import ReturnCodes, InvalidCommandLineError, InvalidCommandLineErrorOPTS, \
                        Encryption

class ResultsCommand(RdmcCommandBase):
    """ Monolith class command """
    def __init__(self, rdmcObj):
        RdmcCommandBase.__init__(self,\
            name='results',\
            usage='results [OPTIONS]\n\n\tRun to show the results of the last' \
                    ' changes after a server reboot.\n\texample: results',\
            summary='Show the results of changes which require a server reboot.',\
            aliases=['results'],\
            argparser=ArgumentParser())
        self.definearguments(self.parser)
        self._rdmc = rdmcObj
        self.typepath = rdmcObj.app.typepath
        self.lobobj = rdmcObj.commands_dict["LoginCommand"](rdmcObj)
        self.selobj = rdmcObj.commands_dict["SelectCommand"](rdmcObj)

    def run(self, line):
        """ Gather results of latest BIOS change

        :param line: string of arguments passed in
        :type line: str.
        """
        try:
            (options, args) = self._parse_arglist(line)
        except (InvalidCommandLineErrorOPTS, SystemExit):
            if ("-h" in line) or ("--help" in line):
                return ReturnCodes.SUCCESS
            else:
                raise InvalidCommandLineErrorOPTS("")

        if args:
            raise InvalidCommandLineError("Results command does not take any arguments.")
        self.resultsvalidation(options)
        results = {}
        if self.typepath.defs.biospath[-1] == '/':
            iscsipath = self.typepath.defs.biospath + 'iScsi/'
            bootpath = self.typepath.defs.biospath + 'Boot/'
        else:
            iscsipath = self.typepath.defs.biospath + '/iScsi'
            bootpath = self.typepath.defs.biospath + '/Boot'

        try:
            self.selobj.selectfunction("SmartStorageConfig")
            smartarray = self._rdmc.app.getprops()
            sapaths = [path['@odata.id'].split('settings')[0] for path in smartarray]
        except:
            sapaths = None

        biosresults = self._rdmc.app.get_handler(self.typepath.defs.biospath, \
                    service=True, silent=True)
        iscsiresults = self._rdmc.app.get_handler(iscsipath, \
                    service=True, silent=True)
        bootsresults = self._rdmc.app.get_handler(bootpath, \
                    service=True, silent=True)
        if sapaths:
            saresults = [self._rdmc.app.get_handler(path, service=True, \
                            silent=True) for path in sapaths]
        try:
            results.update({'Bios:': biosresults.dict[self.typepath.defs.\
                                            biossettingsstring]['Messages']})
        except Exception as exp:
            results.update({'Bios:': None})

        try:
            results.update({'Iscsi:': iscsiresults.dict[self.typepath.defs.\
                                           biossettingsstring]['Messages']})
        except:
            results.update({'Iscsi:': None})

        try:
            results.update({'Boot:': bootsresults.dict[self.typepath.defs.\
                                             biossettingsstring]['Messages']})
        except:
            results.update({'Boot:': None})
        try:
            for result in saresults:
                loc = 'SmartArray'
                if saresults.index(result) > 0:
                    loc += ' %d:' % saresults.index(result)
                else:
                    loc += ':'
                results.update({loc: result.dict[self.typepath.defs.\
                                             biossettingsstring]['Messages']})
        except:
            results.update({'SmartArray:': None})

        messagelist = list()

        sys.stdout.write("Results of the previous reboot changes:\n\n")

        for result in results:
            sys.stdout.write("%s\n" % result)
            try:
                for msg in results[result]:
                    ResponseHandler(self._rdmc.app.validationmanager,
                        self.typepath.defs.messageregistrytype).\
                        message_handler(response_data=msg, response_status="", message_text="", \
                        response_error_str="", dl_reg=False, verbosity=self._rdmc.app.verbose)
            except EmptyRaiseForEAFP as exp:
                raise EmptyRaiseForEAFP(exp)
            except Exception:
                sys.stderr.write("No messages found for %s.\n" % result[:-1])

        logout_routine(self, options)
        return ReturnCodes.SUCCESS

    def resultsvalidation(self, options):
        """ Results method validation function

        :param options: command line options
        :type options: list.
        """
        login_select_validation(self, options)

    def definearguments(self, customparser):
        """ Wrapper function for new command main function

        :param customparser: command line input
        :type customparser: parser.
        """
        if not customparser:
            return

        add_login_arguments_group(customparser)
