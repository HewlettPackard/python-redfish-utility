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
""" Delete Logical Drive Command for rdmc """

from six.moves import input

from ilorest.rdmc_helper import ReturnCodes, InvalidCommandLineError, Encryption, \
                    InvalidCommandLineErrorOPTS, NoContentsFoundForOperationError

class DeleteLogicalDriveCommand():
    """ Delete logical drive command """
    def __init__(self):
        self.ident = {
            'name':'deletelogicaldrive',
            'usage': None,
            'description':'To delete a logical '
                    'drive a controller by index.\n\texample: deletelogicaldrive '
                    '1 --controller=1\n\n\tTo delete multiple logical drives by '
                    'index.\n\tExample: deletelogicaldrive 1,2 --controller=1'
                    '\n\n\tTo delete all logical drives on a controller.\n\t'
                    'deletelogicaldrive --controller=1 --all\n\n\t'
                    'deletelogicaldrive --controller="Slot1" --all\n\n\tNOTE: '
                    'You can also delete logical drives by '
                    '"VolumeUniqueIdentifier".\n\n\t'
                    'You can also delete logical drives by '
                    '"LogicalDriveName".',
            'summary':'Deletes logical drives from the selected controller.',
            'aliases': [],
            'auxcommands': ["SelectCommand"]
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """ Main disk inventory worker function

        :param line: command line input
        :type line: string.
        """
        if help_disp:
            self.parser.print_help()
            return ReturnCodes.SUCCESS
        try:
            (options, args) = self.rdmc.rdmc_parse_arglist(self, line)
        except (InvalidCommandLineErrorOPTS, SystemExit):
            if ("-h" in line) or ("--help" in line):
                # self.rdmc.ui.printer(self.ident['usage'])
                return ReturnCodes.SUCCESS
            else:
                raise InvalidCommandLineErrorOPTS("")

        self.deletelogicaldrivevalidation(options)

        self.auxcommands['select'].selectfunction("SmartStorageConfig.")
        content = self.rdmc.app.getprops()

        if not args and not options.all:
            raise InvalidCommandLineError('You must include a logical drive to delete.')
        elif not options.controller:
            raise InvalidCommandLineError('You must include a controller to select.')
        else:
            if len(args) > 1:
                logicaldrives = args
            elif len(args) == 1:
                logicaldrives = args[0].replace(', ', ',').split(',')
            else:
                logicaldrives = None

        controllist = []

        try:
            if options.controller.isdigit():
                slotlocation = self.get_location_from_id(options.controller)
                if slotlocation:
                    slotcontrol = slotlocation.lower().strip('\"').split('slot')[-1].lstrip()
                    for control in content:
                        if slotcontrol.lower() == control["Location"].lower().split('slot')[-1].lstrip():
                            controllist.append(control)
            if not controllist:
                raise InvalidCommandLineError("")
        except InvalidCommandLineError:
            raise InvalidCommandLineError("Selected controller not found in the current inventory "
                                          "list.")

        self.deletelogicaldrives(controllist, logicaldrives, options.all, options.force)

        self.cmdbase.logout_routine(self, options)
        #Return code
        return ReturnCodes.SUCCESS

    def get_location_from_id(self, controller_id):
        self.rdmc.ui.printer("Controller ID: %s\n" % (controller_id))
        for sel in self.rdmc.app.select("SmartStorageArrayController", path_refresh=True):
            if 'Collection' not in sel.maj_type:
                controller = sel.dict
                self.rdmc.ui.printer("Controller ID: %s\n" % (controller['Id']))
                if controller['Id'] == str(controller_id):
                    self.rdmc.ui.printer("Controller Location: %s\n" % (controller['Location']))
                    return controller["Location"]
        return None

    def deletelogicaldrives(self, controllist, drivelist, allopt, force):
        """Gets logical drives ready for deletion

        :param controllist: list of controllers
        :type controllist: list.
        :param drivelist: logical drives to delete
        :type drivelist: list.
        :param allopt: flag for deleting all logical drives
        :type allopt: bool.
        """

        for controller in controllist:
            changes = False

            numdrives = len(controller['LogicalDrives'])
            deletecount = 0

            if allopt:
                controller['LogicalDrives'] = []
                controller['DataGuard'] = "Disabled"
                self.lastlogicaldrive(controller)
                changes = True
            else:
                for deldrive in drivelist:
                    found = False

                    if deldrive.isdigit():
                        deldrive = int(deldrive)

                    for idx, ldrive in enumerate(controller['LogicalDrives']):
                        if deldrive == ldrive['LogicalDriveNumber']:
                            if not force:
                                while True:
                                    ans = input("Are you sure you would"\
                                            " like to continue deleting drive"\
                                            ' %s? (y/n)' % ldrive['LogicalDriveName'])

                                    if ans.lower() == 'y':
                                        break
                                    elif ans.lower() == 'n':
                                        self.rdmc.ui.warn("Stopping command without "
                                                          "deleting logical drive.\n")
                                        return
                            self.rdmc.ui.printer('Setting logical drive %s ' \
                                                 'for deletion\n' % ldrive['LogicalDriveName'])

                            controller['LogicalDrives'][idx]['Actions'] = \
                                        [{"Action": "LogicalDriveDelete"}]

                            controller['DataGuard'] = "Permissive"
                            deletecount += 1

                            changes = True
                            found = True
                            break

                    if not found:
                        raise NoContentsFoundForOperationError('Logical '\
                                        'drive %s not found.'% str(deldrive))

                if deletecount == numdrives:
                    self.lastlogicaldrive(controller)

            if changes:
                self.rdmc.ui.printer(
                    "DeleteLogicalDrive path and payload: %s, %s\n" % (controller["@odata.id"], controller))
                self.rdmc.app.put_handler(controller["@odata.id"], controller,
                                          headers={'If-Match': self.getetag(controller['@odata.id'])})
                self.rdmc.app.download_path([controller["@odata.id"]], path_refresh=True,
                                            crawl=False)

    def lastlogicaldrive(self, controller):
        """Special case that sets required properties after last drive deletion

        :param controller: controller change settings on
        :type controller: dict.
        """
        changelist = ['PredictiveSpareRebuild', 'SurfaceScanAnalysisPriority',
                      'FlexibleLatencySchedulerSetting', 'DegradedPerformanceOptimization',
                      'CurrentParallelSurfaceScanCount', 'SurfaceScanAnalysisDelaySeconds',
                      'MonitorAndPerformanceAnalysisDelaySeconds',
                      'InconsistencyRepairPolicy', 'DriveWriteCache',
                      'ExpandPriority', 'EncryptionEULA', 'NoBatteryWriteCache',
                      'ReadCachePercent', 'WriteCacheBypassThresholdKiB',
                      'RebuildPriority', 'QueueDepth', 'ElevatorSort']

        for item in changelist:
            if item in list(controller.keys()):
                controller[item] = None

    def getetag(self, path):
        """ get etag from path """
        etag = None
        instance = self.rdmc.app.monolith.path(path)
        if instance:
            etag = instance.resp.getheader('etag') if 'etag' in instance.resp.getheaders() \
                                            else instance.resp.getheader('ETag')
        return etag

    def deletelogicaldrivevalidation(self, options):
        """ delete logical drive validation function

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

        customparser.add_argument(
            '--controller',
            dest='controller',
            help="Use this flag to select the corresponding controller "
                "using either the slot number or index.",
            default=None,
        )
        customparser.add_argument(
            '--all',
            dest='all',
            help="""Use this flag to delete all logical drives on a """ \
                """controller.""",
            action="store_true",
            default=False,
        )
        customparser.add_argument(
            '--force',
            dest='force',
            help="""Use this flag to override the "are you sure?" text when """ \
                """deleting a logical drive.""",
            action="store_true",
            default=False,
        )
