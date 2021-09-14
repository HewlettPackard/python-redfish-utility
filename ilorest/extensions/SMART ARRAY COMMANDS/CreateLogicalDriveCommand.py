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
""" Create Logical Drive Command for rdmc """

from argparse import RawDescriptionHelpFormatter

from ilorest.rdmc_helper import ReturnCodes, InvalidCommandLineError, InvalidCommandLineErrorOPTS, \
                        Encryption, InvalidSmartArrayConfigurationError

class CreateLogicalDriveCommand():
    """ Create logical drive command """
    def __init__(self):
        self.ident = {
            'name': 'createlogicaldrive',
            'usage': None,
            'description': 'Creates logical drives on compatible HPE SSA RAID controllers\nTo view '
                          'help on specific sub-commands run: createlogicaldrive <sub-command> -h\n\n'
                          'NOTE: When you select multiple physicaldrives you can select by both\n\t'
                          'physical drive name and by the location at the same time.\n\t'
                          'You can also select controllers by slot number as well as index.',
            'summary': 'Creates a new logical drive on the selected controller.',
            'aliases': [],
            'auxcommands': ["SelectCommand", "SmartArrayCommand"]
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
            (options, _) = self.rdmc.rdmc_parse_arglist(self, line)
            if not line or line[0] == "help":
                self.parser.print_help()
                return ReturnCodes.SUCCESS
        except (InvalidCommandLineErrorOPTS, SystemExit):
            if ("-h" in line) or ("--help" in line):
                # self.rdmc.ui.printer(self.ident['usage'])
                return ReturnCodes.SUCCESS
            else:
                raise InvalidCommandLineErrorOPTS("")

        self.createlogicaldrivevalidation(options)

        if options.controller:
            controllers = self.auxcommands['smartarray'].controllers(options, single_use=True)
            try:
                controller = controllers[next(iter(controllers))]
                (create_flag, newdrive) = self.createlogicaldrive(options, controller)
                if create_flag:
                    #if controller.get("DataGuard"):
                    #    controller["DataGuard"] = "Disabled"
                    temp_odata = controller['@odata.id']
                    #temp_l = controller['LogicalDrives']
                    #temp_p = controller['PhysicalDrives']
                    #readonly_removed = self.rdmc.app.removereadonlyprops(controller)
                    payload_dict = dict()
                    payload_dict['DataGuard'] = "Disabled"
                    #readonly_removed['LogicalDrives'] = controller['LogicalDrives']
                    #readonly_removed['PhysicalDrives'] = temp_p
                    if not 'settings' in temp_odata:
                        temp_odata = temp_odata + "settings/"
                    settings_controller = self.rdmc.app.get_handler(temp_odata,
                                                                    service=False, silent=True)
                    # Fix for multiple logical creation at single reboot
                    if self.rdmc.app.typepath.defs.isgen9:
                        payload_dict['logical_drives'] = dict()
                        payload_dict['logical_drives']['new'] = newdrive
                    else:
                        payload_dict['LogicalDrives'] = settings_controller.dict['LogicalDrives']
                        payload_dict['LogicalDrives'].append(newdrive)
                    self.rdmc.ui.printer("CreateLogicalDrive path and payload: %s, %s\n" % (temp_odata, payload_dict))
                    self.rdmc.app.put_handler(temp_odata, payload_dict,
                                              headers={'If-Match': self.getetag(temp_odata)})
                    self.rdmc.app.download_path([temp_odata], path_refresh=True,
                                                crawl=False)
            except Exception as excp:
                raise InvalidCommandLineError("%s for  "\
                            "controller ID ('--controller=%s')"% (str(excp), options.controller))

        self.cmdbase.logout_routine(self, options)
        #Return code
        return ReturnCodes.SUCCESS

    def createlogicaldrive(self, options, controller):
        """ Create logical drive """
        raidlvllist = ['Raid0', 'Raid1', 'Raid1ADM', 'Raid10', 'Raid10ADM',
                       'Raid5', 'Raid50', 'Raid6', 'Raid60']
        interfacetypelist = ['SAS', 'SATA']
        mediatypelist = ['SSD', 'HDD']
        sparetypelist = ['Dedicated', 'Roaming']
        acceltypelist = ['ControllerCache', 'IOBypass', 'None']
        locationtypelist = ['Internal', 'External']
        legacylist = ['Primary', 'Secondary', 'All', 'None']
        paritylist = ['Default', 'Rapid']

        sparedrives = []
        changes = False

        controller['physical_drives'] = \
                self.auxcommands['smartarray'].physical_drives(options, controller, single_use=True)
        controller['logical_drives'] = \
                self.auxcommands['smartarray'].logical_drives(options, controller, single_use=True)
        if controller.get('Links'):
            newdrive = {"Links": {"DataDrives": {}}}
        else:
            newdrive = {"links": {"DataDrives": {}}}

        changes = False
        itemadded = False

        for item in raidlvllist:
            if options.raid.lower() == item.lower():
                if options.command == 'customdrive':
                    drivecount = len(options.disks.replace(', ', ',').split(','))
                else:
                    try:
                        drivecount = int(options.disks)
                    except ValueError:
                        raise InvalidCommandLineError('Number of drives is not an integer.')
                if self.raidvalidation(item.lower(), drivecount, options):
                    itemadded = True
                    newdrive["Raid"] = item
                break

        if not itemadded:
            raise InvalidCommandLineError('Invalid raid type or configuration.')
        else:
            itemadded = False

        if options.command == 'customdrive':
            if options.sparedrives:
                sparedrives = options.sparedrives.replace(', ', ',').split(',')
                newdrive["SpareDrives"] = []
                newdrive["SpareRebuildMode"] = 'Dedicated'

            drives = options.disks.replace(', ', ',').split(',')
            newdrive["DataDrives"] = []

            if len(controller["physical_drives"]) > 0:
                for id in controller["physical_drives"]:
                    for drive in drives:
                        if drive == controller["physical_drives"][str(id)]["Location"]:
                            newdrive["DataDrives"].append(drive)

                    for sdrive in sparedrives:
                        if sdrive == controller["physical_drives"][str(id)]["Location"]:
                            newdrive["SpareDrives"].append(sdrive)
            else:
                raise InvalidCommandLineError('No Physical Drives in this controller')

            if drivecount > len(newdrive["DataDrives"]):
                raise InvalidCommandLineError("Not all of the selected drives could "
                                              "be found in the specified locations.")

            if options.sparetype:
                itemadded = False
                for item in sparetypelist:
                    if options.sparetype.lower() == item.lower():
                        newdrive["SpareRebuildMode"] = item
                        itemadded = True
                        break

                if not itemadded:
                    raise InvalidCommandLineError('Invalid spare drive type.')

            if options.drivename:
                newdrive["LogicalDriveName"] = options.drivename

            if options.capacitygib:
                try:
                    capacitygib = int(options.capacitygib)
                except ValueError:
                    raise InvalidCommandLineError('Capacity is not an integer.')
                newdrive["CapacityGiB"] = capacitygib

            if options.acceleratortype:
                itemadded = False
                for item in acceltypelist:
                    if options.acceleratortype.lower() == item.lower():
                        newdrive["Accelerator"] = item
                        itemadded = True
                        break

                if not itemadded:
                    raise InvalidCommandLineError('Invalid accelerator type.')

            if options.legacyboot:
                itemadded = False
                for item in legacylist:
                    if options.legacyboot.lower() in item.lower():
                        newdrive["LegacyBootPriority"] = item
                        itemadded = True
                        break

                if not itemadded:
                    raise InvalidCommandLineError('Invalid legacy boot priority.')

            if options.capacityblocks:
                try:
                    capacityblocks = int(options.capacityblocks)
                except ValueError:
                    raise InvalidCommandLineError('Capacity is not an integer.')

                newdrive["CapacityBlocks"] = capacityblocks

            if options.paritygroup:
                try:
                    paritygroup = int(options.paritygroup)
                except ValueError:
                    raise InvalidCommandLineError('Parity group is not an integer.')

                newdrive["ParityGroupCount"] = paritygroup

            if options.paritytype:
                itemadded = False
                for item in paritylist:
                    if options.paritytype.lower() == item.lower():
                        newdrive["ParityInitializationType"] = item
                        itemadded = True
                        break

                if not itemadded:
                    raise InvalidCommandLineError("Invalid parity type")

            if options.blocksize:
                try:
                    blocksize = int(options.blocksize)
                except ValueError:
                    raise InvalidCommandLineError('Block size is not an integer.')

                newdrive["BlockSizeBytes"] = blocksize

            if options.stripsize:
                try:
                    stripsize = int(options.stripsize)
                except ValueError:
                    raise InvalidCommandLineError('Strip size is not an integer.')

                newdrive["StripSizeBytes"] = stripsize

            if options.stripesize:
                try:
                    stripesize = int(options.stripesize)
                except ValueError:
                    raise InvalidCommandLineError('Stripe size is not an integer.')

                newdrive["StripeSizeBytes"] = stripesize
        elif options.command == 'quickdrive':
            try:
                numdrives = int(options.disks)
            except ValueError:
                raise InvalidCommandLineError('Number of drives is not an integer.')

            newdrive["DataDrives"] = {"DataDriveCount": numdrives, "DataDriveMinimumSizeGiB": 0}
            for item in mediatypelist:
                if options.drivetype.lower() == item.lower():
                    newdrive["DataDrives"]["DataDriveMediaType"] = item
                    itemadded = True
                    break
            if not itemadded:
                raise InvalidCommandLineError('Invalid media type.')
            else:
                itemadded = False
            for item in interfacetypelist:
                if options.interfacetype.lower() == item.lower():
                    newdrive["DataDrives"]["DataDriveInterfaceType"] = item
                    itemadded = True
                    break
            if not itemadded:
                raise InvalidCommandLineError('Invalid interface type.')

            if options.locationtype:
                for item in locationtypelist:
                    if options.locationtype.lower() == item.lower():
                        newdrive["DataDrives"]["DataDriveLocation"] = item
                        break
            if options.minimumsize:
                try:
                    minimumsize = int(options.minimumsize)
                except ValueError:
                    raise InvalidCommandLineError('Minimum size is not an integer.')
                newdrive["DataDrives"]["DataDriveMinimumSizeGiB"] = minimumsize

        if newdrive:
            if options.command == 'quickdrive':
                newdrive_count = newdrive["DataDrives"]["DataDriveCount"]
            else:
                newdrive_count = len(newdrive["DataDrives"])
            if len(controller["physical_drives"]) >= newdrive_count:
                drives_avail = len(controller["physical_drives"])
                accepted_drives = 0
                for cnt, drive in enumerate(controller["physical_drives"]):
                    drivechecks = (False, False, False, False)
                    if drives_avail < newdrive_count:
                        raise InvalidSmartArrayConfigurationError("Unable to continue, requested "
                                                                  "configuration not possible with current physical drive inventory.\n")
                    else:
                        drivechecks = (True, False, False, False)

                    if options.command == 'quickdrive':
                        if controller["physical_drives"][drive]["InterfaceType"] == newdrive\
                                                        ["DataDrives"]["DataDriveInterfaceType"]:
                            drivechecks = (True, True, False, False)
                        else:
                            drives_avail -= 1
                            continue
                        if controller["physical_drives"][drive]["MediaType"] == newdrive["DataDrives"]\
                                                                            ["DataDriveMediaType"]:
                            drivechecks = (True, True, True, False)
                        else:
                            drives_avail -= 1
                            continue
                    else:
                        drivechecks = (True, True, True, False)
                    in_use = False
                    for existing_logical_drives in controller['logical_drives']:
                        _logical_drive = controller['logical_drives'][existing_logical_drives]
                        if _logical_drive.get('LogicalDrives'):
                            for _data_drive in _logical_drive['LogicalDrives']['DataDrives']:
                                if drive == _logical_drive['LogicalDrives']['DataDrives']\
                                                                                [_data_drive]:
                                    in_use = True
                        elif _logical_drive.get('Links'):
                            for _data_drive in _logical_drive['Links']['DataDrives']:
                                if drive == _logical_drive['Links']['DataDrives'][_data_drive]:
                                    in_use = True
                        elif _logical_drive.get('links'):
                            for _data_drive in _logical_drive['links']['DataDrives']:
                                if drive == _logical_drive['links']['DataDrives'][_data_drive]:
                                    in_use = True
                    if in_use:
                        drives_avail -= 1
                        continue
                    else:
                        drivechecks = (True, True, True, True)
                    if drivechecks[0] and drivechecks[1] and drivechecks[2]:
                        if controller.get('Links'):
                            newdrive["Links"]["DataDrives"][drive] = controller["physical_drives"]\
                                                                                            [drive]
                        else:
                            newdrive["links"]["DataDrives"][drive] = controller["physical_drives"]\
                                                                                            [drive]
                        accepted_drives += 1
                        changes = True
                        if accepted_drives == newdrive_count:
                            break
                    else:
                        drives_avail -= 1

            if changes:
                if self.rdmc.app.typepath.defs.isgen9:
                    controller['logical_drives']['new'] = newdrive
                else:
                    try:
                        newdrive.pop('Links')
                    except KeyError:
                        newdrive.pop('links')
                    controller['LogicalDrives'].append(newdrive)
                    del controller['logical_drives']
                    del controller['physical_drives']

        return (changes, newdrive)

    def getetag(self, path):
        """ get etag from path """
        etag = None
        instance = self.rdmc.app.monolith.path(path)
        if instance:
            etag = instance.resp.getheader('etag') if 'etag' in instance.resp.getheaders() \
                                            else instance.resp.getheader('ETag')
        return etag

    def raidvalidation(self, raidtype, numdrives, options):
        """ vaidation function for raid levels
        :param raidtype: raid type
        :type options: string.
        :param numdrives: number of drives
        :type numdrives: int.
        :param options: command line options
        :type options: list.
        """

        valid = True

        if raidtype == 'raid5':
            if numdrives < 3: #or options.stripsize:
                valid = False
        elif raidtype == 'raid6':
            if numdrives < 4: #or options.stripsize:
                valid = False
        elif raidtype == 'raid50':
            if numdrives < 6:
                valid = False
        elif raidtype == 'raid60':
            if numdrives < 8:
                valid = False

        return valid

    def createlogicaldrivevalidation(self, options):
        """ Create logical drive validation function

        :param options: command line options
        :type options: list.
        """
        self.cmdbase.login_select_validation(self, options)

    @staticmethod
    def options_argument_group(parser):
        """ Define optional arguments group

        :param parser: The parser to add the login option group to
        :type parser: ArgumentParser/OptionParser
        """
        group = parser.add_argument_group('GLOBAL OPTIONS', 'Options are available for all'
                                                            'arguments within the scope of this command.')

        group.add_argument(
            '--controller',
            dest='controller',
            help="Use this flag to select the corresponding controller "
                 "using either the slot number or index.\nexample: --controller=Slot 0 OR "
                 "--controller=1",
            default=None
        )

    def definearguments(self, customparser):
        """ Wrapper function for new command main function

        :param customparser: command line input
        :type customparser: parser.
        """
        if not customparser:
            return

        self.cmdbase.add_login_arguments_group(customparser)
        self.options_argument_group(customparser)

        subcommand_parser = customparser.add_subparsers(dest='command')
        qd_help='Create a logical drive with a minimal number of arguments (utilizes default ' \
                'values on the controller).'
        #quickdrive sub-parser
        qd_parser = subcommand_parser.add_parser(
            'quickdrive',
            help=qd_help,
            description=qd_help + '\n\texample: createlogicaldrive quickdrive ' \
                '<raid-level> <num-drives> <media-type> <interface-type> ' \
                '--locationtype=Internal  --minimumsize=0 --controller=1',
            formatter_class=RawDescriptionHelpFormatter
        )
        qd_parser.add_argument(
            'raid',
            help='Specify the RAID level for the logical drive to be created.',
            metavar='Raid_Level'
        )
        qd_parser.add_argument(
            'disks',
            help='For quick drive creation, specify number of disks.',
            metavar='Drives'
        )
        qd_parser.add_argument(
            'drivetype',
            help='Specify the drive media type of the physical disk(s) (i.e. HDD or SSD)',
            metavar='Drive_Media_Type'
        )
        qd_parser.add_argument(
            'interfacetype',
            help='Specify the interface type of the physical disk(s) (i.e. SATA or SAS)',
            metavar='Drive_Interface_Type'
        )
        qd_parser.add_argument(
            '--locationtype',
            dest='locationtype',
            help='Optionally specify the location of the physical disks(s) (i.e. Internal or External)',
            default=None,
        )
        qd_parser.add_argument(
            '--minimumsize',
            dest='minimumsize',
            help="""Optionally include to set the minimum size of the drive """ \
                """in GiB. (usable in quick creation only, use -1 for max size)""",
            default=None,
        )
        self.cmdbase.add_login_arguments_group(qd_parser)
        self.options_argument_group(qd_parser)

        cd_help='Create a customized logical drive using all available properties (as optional '\
                'arguments) for creation.'
        #customdrive sub-parser
        cd_parser = subcommand_parser.add_parser(
            'customdrive',
            help=cd_help,
            description=cd_help + '\n\texample: createlogicaldrive customdrive '
                                  '<raid-level> <physicaldrivelocations> --controller=1 '
                                  '--name=drivename --spare-drives=1I:1:1,1I:1:3 --spare-type=Dedicated --capacitygib=10 '
                                  '--accelerator-type=None\n\n\tOPTIONS:\n\traid-level:\t\t'
                                  'Raid0, Raid1, Raid1ADM, Raid10, Raid10ADM, Raid5, Raid50, '
                                  'Raid6, Raid60\n\tphysicaldrivelocation(s):\tLocation, Drive-name\n\t'
                                  'media-type:\t\tSSD,HDD\n\tinterface-type:'
                                  '\t\tSAS, SATA\n\tdrive-location:\t\tInternal, External\n\t'
                                  '--spare-type:\t\tDedicated, Roaming\n\t--accelerator-type:\t'
                                  'ControllerCache, IOBypass, None\n\t--paritytype:\t\tDefault, Rapid'
                                  '\n\t--capacitygib:\t\t-1 (for Max Size)\n\t--capacityblocks:\t'
                                  '-1 (for Max Size)\n\n\t',
            formatter_class=RawDescriptionHelpFormatter
        )
        cd_parser.add_argument(
            'raid',
            help='Specify the RAID level for the logical drive to be created.',
            metavar='Raid_Level'
        )
        cd_parser.add_argument(
            'disks',
            help='For custom drive, specify a comma separated physical disk locations.',
            metavar='Drive_Indices'
        )
        cd_parser.add_argument(
            '-n',
            '--name',
            dest='drivename',
            help="""Optionally include to set the drive name (usable in """ \
                """custom creation only).""",
            default=None,
        )
        cd_parser.add_argument(
            '--spare-drives',
            dest='sparedrives',
            help="""Optionally include to set the spare drives by the """ \
                """physical drive's location. (usable in custom creation only)""",
            default=None,
        )
        cd_parser.add_argument(
            '--capacitygib',
            dest='capacitygib',
            help="""Optionally include to set the capacity of the drive in """ \
                 """GiB. (usable in custom creation only, use -1 for max """ \
                 """size)""",
            default=None,
        )
        cd_parser.add_argument(
            '--accelerator-type',
            dest='acceleratortype',
            help="""Optionally include to choose the accelerator type.""",
            default=None,
        )
        cd_parser.add_argument(
            '--spare-type',
            dest='sparetype',
            help="""Optionally include to choose the spare drive type. """ \
                """(usable in custom creation only)""",
            default=None,
        )
        cd_parser.add_argument(
            '--minimumsize',
            dest='minimumsize',
            help="""Optionally include to set the minimum size of the drive """ \
                """in GiB. (usable in quick creation only, use -1 for max size)""",
            default=None,
        )
        cd_parser.add_argument(
            '--legacy-boot',
            dest='legacyboot',
            help="""Optionally include to choose the legacy boot priority. """ \
                """(usable in custom creation only)""",
            default=None,
        )
        cd_parser.add_argument(
            '--capacityblocks',
            dest='capacityblocks',
            help="""Optionally include to choose the capacity in blocks. """ \
                """(use -1 for max size, usable in custom creation only)""",
            default=None,
        )
        cd_parser.add_argument(
            '--paritygroupcount',
            dest='paritygroup',
            help="""Optionally include to include the number of parity """ \
                """groups to use. (only valid for certain RAID levels)""",
            default=None,
        )
        cd_parser.add_argument(
            '--paritytype',
            dest='paritytype',
            help="""Optionally include to choose the parity initialization""" \
                """ type. (usable in custom creation only)""",
            default=None,
        )
        cd_parser.add_argument(
            '--block-size-bytes',
            dest='blocksize',
            help="""Optionally include to choose the block size of the disk""" \
                """ drive. (usable in custom creation only)""",
            default=None,
        )
        cd_parser.add_argument(
            '--strip-size-bytes',
            dest='stripsize',
            help="""Optionally include to choose the strip size in bytes. """ \
                """(usable in custom creation only)""",
            default=None,
        )
        cd_parser.add_argument(
            '--stripe-size-bytes',
            dest='stripesize',
            help="""Optionally include to choose the stripe size in bytes. """ \
                """(usable in custom creation only)""",
            default=None,
        )
        self.cmdbase.add_login_arguments_group(cd_parser)
        self.options_argument_group(cd_parser)
