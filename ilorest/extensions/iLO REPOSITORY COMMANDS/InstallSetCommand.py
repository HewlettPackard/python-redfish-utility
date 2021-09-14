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
""" Install Set Command for rdmc """

import re
import json
from datetime import datetime

from argparse import RawDescriptionHelpFormatter

from ilorest.rdmc_helper import IncompatibleiLOVersionError, ReturnCodes, Encryption,\
                        InvalidCommandLineErrorOPTS, InvalidCommandLineError,\
                        NoContentsFoundForOperationError, InvalidFileInputError

class InstallSetCommand():
    """ Main download command class """
    def __init__(self):
        self.ident = {
            'name':'installset',
            'usage': None,
            'description':'Run to perform operations on install sets.\nTo view help on specific '
                          'sub-commands run: installset <sub-command> -h\n\n\tExample: installset '
                          'add -h\nNote: iLO 5 required.',
            'summary':'Manages install sets for iLO.',
            'aliases': [],
            'auxcommands': []
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """ Main listcomp worker function

        :param line: string of arguments passed in
        :type line: str.
        """
        if help_disp:
            self.parser.print_help()
            return ReturnCodes.SUCCESS
        try:
            _subcommands = ['add', 'delete', 'invoke']
            found = False
            for i, arg in enumerate(line):
                if arg in _subcommands:
                    found = True
                    try:
                        if line[i+1] not in list(self.parser._option_string_actions.keys()):
                            (options, args) = self.rdmc.rdmc_parse_arglist(self, line)
                        else:
                            raise IndexError
                    except (KeyError, IndexError):
                        (options, args) = self.rdmc.rdmc_parse_arglist(self, line, default=True)
                    else:
                        continue
            if not found:
                (options, args) = self.rdmc.rdmc_parse_arglist(self, line, default=True)
        except (InvalidCommandLineErrorOPTS, SystemExit):
            if ("-h" in line) or ("--help" in line):
                # self.rdmc.ui.printer(self.ident['usage'])
                return ReturnCodes.SUCCESS
            else:
                raise InvalidCommandLineErrorOPTS("")

        self.installsetvalidation(options)

        if self.rdmc.app.typepath.defs.isgen9:
            raise IncompatibleiLOVersionError('iLO Repository commands are '
                                              'only available on iLO 5.')

        if hasattr(options, 'name'):
            if options.name:
                if options.name.startswith('"') and options.name.endswith('"'):
                    options.name = options.name[1:-1]
        if hasattr(options, 'removeall'):
            if options.removeall:
                self.removeinstallsets()
        if options.command.lower() == 'add':
            if not options.json:
                raise InvalidCommandLineError('add command requires an install set file.')
            else:
                self.addinstallset(options.json, options.name)
        elif options.command.lower() == 'delete':
            self.deleteinstallset(options.name)
        elif options.command.lower() == 'invoke':
            self.invokeinstallset(options)
        else:
            self.printinstallsets(options)

        self.cmdbase.logout_routine(self, options)
        #Return code
        return ReturnCodes.SUCCESS

    def addinstallset(self, setfile, name):
        """Adds an install set
        :param setfile: filename of install set
        :type setfile: str.
        :param name: string of the install set name to add
        :type name: str.
        """
        path = '/redfish/v1/UpdateService/InstallSets/'
        comps = self.rdmc.app.getcollectionmembers(
            '/redfish/v1/UpdateService/ComponentRepository/')

        sets = self.rdmc.app.getcollectionmembers(path)

        if not name:
            name = str(datetime.now())
            name = name.replace(':', '')
            name = name.replace(' ', 'T')
        try:
            inputfile = open(setfile, 'r')
            sequences = json.loads(inputfile.read())
        except Exception as excp:
            raise InvalidFileInputError("%s" % excp)

        listtype = self.validatefile(sequences)

        if listtype:
            body = {"Name": name, "Sequence": sequences}
        else:
            body = sequences
            if "Sequence" in body:
                sequences = body['Sequence']
            else:
                raise InvalidFileInputError("Invalid install set file.")
            sequences = body["Sequence"]

        filenamelist = [x['Filename'] for x in comps]

        for sequence in sequences:
            if sequence['Command'] == 'ApplyUpdate':
                if 'Filename' in list(sequence.keys()):
                    if not sequence['Filename'] in filenamelist:
                        raise NoContentsFoundForOperationError('Component' \
                            ' referenced in install set is not present on' \
                            ' iLO Drive: %s' % sequence['Filename'])
            elif sequence['Command'] == 'WaitTimeSeconds':
                sequence['WaitTimeSeconds'] = int(sequence['WaitTimeSeconds'])
        for setvar in sets:
            if setvar['Name'] == body['Name']:
                raise InvalidCommandLineError('Install set name is already in use.')

        self.rdmc.app.post_handler(path, body)

    def invokeinstallset(self, options):
        """Deletes the named set
        :param name: string of the install set name to delete
        :type name: str.
        """
        path = None
        name = options.name
        sets = self.rdmc.app.getcollectionmembers(
            '/redfish/v1/UpdateService/InstallSets/')

        for setvar in sets:
            if setvar['Name'] == name:
                path = setvar['Actions']['#HpeComponentInstallSet.Invoke']['target']

        if not path:
            raise NoContentsFoundForOperationError('No install set with the'
                                                   ' provided name could be found.')

        self.rdmc.ui.printer('Invoking install set:%s\n' % name)

        payload = self.checkpayloadoptions(options)
        self.rdmc.app.post_handler(path, payload)

    def deleteinstallset(self, name):
        """Deletes the named set

        :param name: string of the install set name to delete
        :type name: str.
        """
        path = None
        sets = self.rdmc.app.getcollectionmembers('/redfish/v1/UpdateService/InstallSets/')

        for setvar in sets:
            if setvar['Name'] == name:
                path = setvar['@odata.id']

        if path:
            self.rdmc.ui.printer('Deleting install set: %s...\n'% name)
            self.rdmc.app.delete_handler(path)
        else:
            raise NoContentsFoundForOperationError('Unable to find the specified install set.')

    def removeinstallsets(self):
        """Removes all install sets """
        sets = self.rdmc.app.getcollectionmembers('/redfish/v1/UpdateService/InstallSets/')

        if not sets:
            self.rdmc.ui.printer('No install sets found.\n')

        self.rdmc.ui.printer('Deleting all install sets...\n')

        for setvar in sets:
            if setvar['IsRecovery']:
                self.rdmc.ui.warn('Skipping delete of recovery set: %s\n' %setvar['Name'])
            else:
                self.rdmc.ui.printer('Deleting install set: %s\n' % setvar['Name'])
                self.rdmc.app.delete_handler(setvar['@odata.id'])

    def printinstallsets(self, options):
        """Prints install sets """
        sets = self.rdmc.app.getcollectionmembers('/redfish/v1/UpdateService/InstallSets/')
        if not options.json:
            self.rdmc.ui.printer('Install Sets:\n')

        if not sets:
            self.rdmc.ui.printer('No install sets found.\n')
        elif not options.json:
            for setvar in sets:
                if setvar['IsRecovery']:
                    recovery = "[Recovery Set]"
                else:
                    recovery = ""
                self.rdmc.ui.printer('\n%s: %s\n' % (setvar['Name'], recovery))

                if 'Sequence' not in list(setvar.keys()):
                    self.rdmc.ui.warn('\tNo Sequences in set.\n')
                    continue

                for item in setvar['Sequence']:
                    if 'Filename' in list(item.keys()):
                        self.rdmc.ui.printer('\t%s: %s %s\n' % (item['Name'],
                                                                item['Command'], item['Filename']))
                    elif 'WaitTimeSeconds' in list(item.keys()):
                        self.rdmc.ui.printer('\t%s: %s %s seconds\n' % (item['Name'],
                                                                        item['Command'], str(item['WaitTimeSeconds'])))
                    else:
                        self.rdmc.ui.printer('\t%s: %s\n' % (item['Name'], item['Command']))
        elif options.json:
            outjson = dict()
            for setvar in sets:
                outjson[setvar['Name']] = setvar
            self.rdmc.ui.print_out_json(outjson)

    def validatefile(self, installsetfile):
        """ validates json file

        :param file: json file to validate
        :type file: string.
        """
        listtype = True
        keylist = ['Name', 'UpdatableBy', 'Command', 'WaitTimeSeconds', 'Filename']

        if isinstance(installsetfile, list):
            for item in installsetfile:
                for key in item:
                    if key not in keylist:
                        raise InvalidFileInputError('Property %s is invalid ' \
                                                    'for an install set.' % key)
        else:
            listtype = False

        return listtype

    def checkpayloadoptions(self, options):
        """ checks for payload options and adds needed ones to payload

        :param options: command line options
        :type options: list.
        """

        payload = {}
        if options.exafter:
            self.checktime(options.exafter)
            payload["Expire"] = options.exafter
        if options.safter:
            self.checktime(options.safter)
            payload["StartAfter"] = options.safter
        if options.tover:
            payload["TPMOverride"] = True
        if options.uset:
            payload["UpdateRecoverySet"] = True
        if options.ctakeq:
            payload["ClearTaskQueue"] = True

        return payload

    def checktime(self, timestr):
        """ check the time string for valid format

        :param timestr: time string to check
        :type timestr: string.
        """
        rfdtregex = '\\d\\d\\d\\d-\\d\\d-\\d\\dT\\d\\d:\\d\\d:\\d\\dZ?'
        if not re.match(rfdtregex, timestr):
            raise InvalidCommandLineError('Invalid redfish date-time format. '
                                          'Accepted formats: YYYY-MM-DDThh:mm:ss, YYYY-MM-DDThh:mm:ssZ')

    def installsetvalidation(self, options):
        """ installset validation function

        :param options: command line options
        :type options: list.
        """
        self.cmdbase.login_select_validation(self, options)

    def definearguments(self, customparser):
        """ Wrapper function for new command main function

        :param customparser: command line input
        :type customparser: parser.
        """
        if not customparser:
            return

        self.cmdbase.add_login_arguments_group(customparser)
        subcommand_parser = customparser.add_subparsers(dest='command')
        #default sub-parser
        default_parser = subcommand_parser.add_parser(
            'default',
            help='Running without any sub-command will return a list of all available install '\
            'sets on the currently logged in server.'
        )
        default_parser.add_argument(
            '-j',
            '--json',
            dest='json',
            action="store_true",
            help="Optionally include this flag if you wish to change the"\
                 " displayed output to JSON format. Preserving the JSON data"\
                 " structure makes the information easier to parse.",
            default=False
        )
        default_parser.add_argument(
            '--removeall',
            dest='removeall',
            help='Optionally include this flag to remove all install sets on the currently logged '\
                 'in server.',
            action="store_true",
            default=False
        )
        self.cmdbase.add_login_arguments_group(default_parser)

        #add sub-parser
        add_help='Adds an install set on the currently logged in server.'
        add_parser = subcommand_parser.add_parser(
            'add',
            help=add_help,
            description=add_help + '\n\texample: installset add installsetfile.json '\
                '--name=newinstallsetname.\n\n\tNote: iLO will provide a default '\
                'install set name if the flag \'--name\' is not provided.',
            formatter_class=RawDescriptionHelpFormatter
        )
        add_parser.add_argument(
            'json',
            help='Json file containing the install set tasks and sequencing' \
                 '\n\n\texample install set JSON file:\n\t[\n\t\t{\n\t\t\t"Name": ' \
                 '"Wait",\n\t\t\t"UpdatableBy": ["RuntimeAgent"],\n\t\t\t'\
                 '"Command": "Wait",\n\t\t\t"WaitTimeSeconds": 60\n\t\t},\n\t\t{' \
                 '\n\t\t\t"Name": "uniqueName",\n\t\t\t"UpdatableBy": ' \
                 '["RuntimeAgent"],\n\t\t\t"Command": "ApplyUpdate",\n\t\t\t"' \
                 'Filename": "filename.exe"\n\t\t},\n\t\t{\n\t\t\t"Name": ' \
                 '"Reboot",\n\t\t\t"UpdatableBy": ["RuntimeAgent"],\n\t\t\t' \
                 '"Command": "ResetServer"\n\t\t}\n\t]',
            metavar='JSONFILE'
        )
        add_parser.add_argument(
            '-n',
            '--name',
            dest='name',
            help="Install set name.",
            default=None
        )
        self.cmdbase.add_login_arguments_group(add_parser)

        #invoke sub-parser
        invoke_help='Invoke execution of an install script on the currently logged in server.'
        invoke_parser = subcommand_parser.add_parser(
            'invoke',
            help=invoke_help,
            description=invoke_help + '\n\nExamples:\n\tTo simply invoke an install set\n\t'\
                'installset invoke --name=installsetname',
            formatter_class=RawDescriptionHelpFormatter
        )
        invoke_parser.add_argument(
            '-n',
            '--name',
            help="Install set name.",
            metavar='NAME',
            nargs='?',
            default='',
            required=True
        )
        invoke_parser.add_argument(
            '--cleartaskqueue',
            dest='ctakeq',
            action="store_true",
            help="This option allows previous items in the task queue to"\
                 " be cleared before the Install Set is invoked",
            default=False
        )
        invoke_parser.add_argument(
            '--expire',
            dest='exafter',
            help="Optionally include this flag if you wish to set the"\
                 " time for installset to expire. ISO 8601 Redfish-style time "\
                 "string to be written after which iLO will automatically change "\
                 "state to Expired",
            default=None
        )
        invoke_parser.add_argument(
            '--startafter',
            dest='safter',
            help="Optionally include this flag if you wish to set the"\
                 " earliest execution time for installset. ISO 8601 Redfish-style "\
                 "time string to be used.",
            default=None
        )
        invoke_parser.add_argument(
            '--tpmover',
            dest='tover',
            action="store_true",
            help="If set then the TPMOverrideFlag is passed in on the "\
                 "associated flash operations",
            default=False
        )
        invoke_parser.add_argument(
            '--updaterecoveryset',
            dest='uset',
            action="store_true",
            help="If set then the components in the flash operations are used"\
                 " to replace matching contents in the Recovery Set.",
            default=False
        )
        self.cmdbase.add_login_arguments_group(invoke_parser)

        #delete sub-parser
        delete_help='Delete one or more install sets from the currently logged in server.'
        delete_parser = subcommand_parser.add_parser(
            'delete',
            help=delete_help,
            description=delete_help + '\n\nExamples:\n\nTo delete a single install set:\n\t'\
                'installset delete --name=installsetname.\n\nTo delete all install sets\n\t' \
                'installset delete --removeall',
            formatter_class=RawDescriptionHelpFormatter
        )
        delete_parser.add_argument(
            '-n',
            '--name',
            help="Install set name",
            metavar='NAME',
            nargs='?',
            default=''
        )
        delete_parser.add_argument(
            '--removeall',
            dest='removeall',
            help='Optionally include this flag to remove all install sets on the currently logged '\
                 'in server.',
            action="store_true",
            default=False
        )
        self.cmdbase.add_login_arguments_group(delete_parser)

