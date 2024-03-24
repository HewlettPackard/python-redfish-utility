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
""" Add Federation Command for rdmc """


from argparse import Action, RawDescriptionHelpFormatter

from redfish.ris.ris import SessionExpired
from redfish.ris.rmc_helper import IdTokenError

try:
    from rdmc_helper import (
        IncompatibleiLOVersionError,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        NoContentsFoundForOperationError,
        ResourceExists,
        ReturnCodes,
        UsernamePasswordRequiredError,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        IncompatibleiLOVersionError,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        NoContentsFoundForOperationError,
        ResourceExists,
        ReturnCodes,
        UsernamePasswordRequiredError,
    )

__subparsers__ = ["add", "modify", "changekey", "delete"]


class _FederationParse(Action):
    def __init__(self, option_strings, dest, nargs, **kwargs):
        super(_FederationParse, self).__init__(option_strings, dest, nargs, **kwargs)

    def __call__(self, parser, namespace, values, option_strings):
        """Federation privileges option helper"""

        privkey = {
            1: "LoginPriv",
            2: "RemoteConsolePriv",
            3: "UserConfigPriv",
            4: "iLOConfigPriv",
            5: "VirtualMediaPriv",
            6: "VirtualPowerAndResetPriv",
            7: "HostNICConfigPriv",
            8: "HostBIOSConfigPriv",
            9: "HostStorageConfigPriv",
            10: "SystemRecoveryConfigPriv",
        }

        for priv in next(iter(values)).split(","):
            try:
                priv = int(priv)
            except ValueError:
                try:
                    parser.error("Invalid privilege entered: %s. Privileges must " "be numbers." % priv)
                except:
                    raise InvalidCommandLineErrorOPTS("")

            try:
                if not isinstance(namespace.optprivs, list):
                    namespace.optprivs = list()
                if option_strings.startswith("--add"):
                    namespace.optprivs.append({privkey[priv]: True})
                elif option_strings.startswith("--remove"):
                    namespace.optprivs.append({privkey[priv]: False})
            except KeyError:
                try:
                    parser.error(
                        "Invalid privilege entered: %s. Number does not " "match an available privlege." % priv
                    )
                except:
                    raise InvalidCommandLineErrorOPTS("")


class IloFederationCommand:
    """Add a new ilo federation to the server"""

    def __init__(self):
        self.ident = {
            "name": "ilofederation",
            "usage": None,
            "description": "View, Add, Remove and Modify iLO Federation accoutns based on the "
            "sub-command used.\nTo view help on specific sub-commands run: ilofederation "
            "<sub-command> -h\n\nExample: ilofederation add -h\n"
            "NOTE 1: By default only the login privilege is added to the newly created\n\t\t"
            'federation group with role "ReadOnly" in iLO 5 and no privileges in iLO 4.\n\t'
            "NOTE 2: Federation credentials are case-sensitive.",
            "summary": "Adds / deletes an iLO federation group on the currently logged in server.",
            "aliases": [],
            "auxcommands": [],
        }

        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """Main addfederation function
        :param line: string of arguments passed in
        :type line: str.
        :param help_disp: display help flag
        :type line: bool.
        """
        if help_disp:
            line.append("-h")
            try:
                (_, _) = self.rdmc.rdmc_parse_arglist(self, line)
            except:
                return ReturnCodes.SUCCESS
            return ReturnCodes.SUCCESS
        body = dict()
        try:
            ident_subparser = False
            for cmnd in __subparsers__:
                if cmnd in line:
                    (options, args) = self.rdmc.rdmc_parse_arglist(self, line)
                    ident_subparser = True
                    break
            if not ident_subparser:
                (options, args) = self.rdmc.rdmc_parse_arglist(self, line, default=True)
        except (InvalidCommandLineErrorOPTS, SystemExit):
            if ("-h" in line) or ("--help" in line):
                return ReturnCodes.SUCCESS
            else:
                raise InvalidCommandLineErrorOPTS("")

        self.ilofederationvalidation(options)

        redfish = self.rdmc.app.monolith.is_redfish
        path = self.rdmc.app.typepath.defs.federationpath
        results = self.rdmc.app.get_handler(path, service=True, silent=True).dict

        if redfish:
            results = results["Members"]
        else:
            if "Member" in results["links"]:
                results = results["links"]["Member"]
            else:
                results = list()

        mod_fed = None
        path = None
        for indx, acct in enumerate(results):
            fed = self.rdmc.app.get_handler(
                acct[self.rdmc.app.typepath.defs.hrefstring], service=True, silent=True
            ).dict
            try:
                if hasattr(options, "fedname"):
                    if fed["Name"].lower() == options.fedname.lower():
                        if redfish:
                            path = acct["@odata.id"]
                        else:
                            path = acct["href"]
                        mod_fed = fed
                elif options.command == "default":
                    results[indx] = fed
                else:
                    raise KeyError
            except KeyError:
                continue
            else:
                if mod_fed:
                    break

        if mod_fed:
            if options.command.lower() == "add":
                raise ResourceExists("Federation name %s is already in use." % options.fedname)
        else:
            if options.command.lower() != "add" and options.command.lower() != "default":
                raise InvalidCommandLineError("Unable to find the specified federation %s." % options.fedname)

        if options.command.lower() == "add":
            privs = self.getprivs(options)
            path = self.rdmc.app.typepath.defs.federationpath

            body = {"Name": options.fedname, "Key": options.fedkey}
            if privs:
                body.update({"Privileges": privs})
            self.addvalidation(options.fedname, options.fedkey, results)

            if path and body:
                resp = self.rdmc.app.post_handler(path, body, silent=False, service=False)

            if resp and resp.dict:
                if "resourcealreadyexist" in str(resp.dict).lower():
                    raise ResourceExists("")

        elif options.command.lower() == "changekey":
            try:
                newkey = options.fedkey
            except:
                raise InvalidCommandLineError("Invalid number of parameters.")

            body = {"Key": newkey}

            if path and body:
                self.rdmc.app.patch_handler(path, body, service=True)
            else:
                raise NoContentsFoundForOperationError("Unable to find " "the specified federation.")
        elif options.command.lower() == "modify":
            if options.optprivs:
                body.update({"Privileges": {}})
                if any(
                    priv for priv in options.optprivs if "SystemRecoveryConfigPriv" in priv
                ) and "SystemRecoveryConfigPriv" not in list(self.getsesprivs().keys()):
                    raise IdTokenError(
                        "The currently logged in federation must have The System "
                        "Recovery Config privilege to add the System Recovery "
                        "Config privilege."
                    )
                privs = self.getprivs(options)
                body["Privileges"] = privs

            self.rdmc.app.patch_handler(path, body)

        elif options.command.lower() == "delete":
            if path:
                self.rdmc.app.delete_handler(path)
        else:
            if len(results) == 0:
                self.rdmc.ui.printer("No iLO Federation accounts found.\n")
            else:
                self.rdmc.ui.printer("iLO Federation Id list with Privileges:\n")
                if options.json:
                    outdict = dict()
                    for fed in sorted(results, key=lambda k: k["Name"]):
                        outdict[fed["Name"]] = fed["Privileges"]
                    self.rdmc.ui.print_out_json_ordered(outdict)
                else:
                    for fed in sorted(results, key=lambda k: k["Name"]):
                        privstr = ""
                        privs = fed["Privileges"]
                        for priv in privs:
                            privstr += priv + "=" + str(privs[priv]) + "\n"
                        self.rdmc.ui.printer("\nName=%s:\n%s" % (fed["Name"], privstr))

        self.cmdbase.logout_routine(self, options)
        # Return code
        return ReturnCodes.SUCCESS

    def getprivs(self, options):
        """find and return the privileges to set
        :param options: command line options
        :type options: list.
        """
        sesprivs = self.getsesprivs()
        setprivs = {}
        availableprivs = self.getsesprivs(availableprivsopts=True)

        if "UserConfigPriv" not in list(sesprivs.keys()):
            raise IdTokenError(
                "The currently logged in federation does not have the Config"
                "Privilege and cannot add or modify federations."
            )

        if options.optprivs:
            for priv in options.optprivs:
                priv = next(iter(list(priv.keys())))
                if not options.user or not options.password:
                    if priv == "SystemRecoveryConfigPriv" and self.rdmc.app.current_client.base_url == "blobstore://.":
                        raise UsernamePasswordRequiredError(
                            "Privilege %s need username and password to be specified." % priv
                        )
                if priv not in availableprivs:
                    raise IncompatibleiLOVersionError("Privilege %s is not available on this " "iLO version." % priv)

            if all(priv.values() for priv in options.optprivs):
                if (
                    any(priv for priv in options.optprivs if "SystemRecoveryConfigPriv" in priv)
                    and "SystemRecoveryConfigPriv" not in sesprivs.keys()
                ):
                    raise IdTokenError(
                        "The currently logged in account must have The System "
                        "Recovery Config privilege to add the System Recovery "
                        "Config privilege."
                    )
                else:
                    setprivs = {}
            for priv in options.optprivs:
                setprivs.update(priv)

        return setprivs

    def getsesprivs(self, availableprivsopts=False):
        """Finds and returns the current session's privileges
        :param availableprivsopts: return available privileges
        :type availableprivsopts: boolean.
        """
        if self.rdmc.app.current_client:
            sespath = self.rdmc.app.current_client.session_location
            sespath = (
                self.rdmc.app.current_client.default_prefix
                + sespath.split(self.rdmc.app.current_client.default_prefix)[-1]
            )

            ses = self.rdmc.app.get_handler(sespath, service=False, silent=True)

            if ses.status != 200:
                raise SessionExpired("Invalid session. Please logout and " "log back in or include credentials.")

            sesprivs = {
                "HostBIOSConfigPriv": True,
                "HostNICConfigPriv": True,
                "HostStorageConfigPriv": True,
                "LoginPriv": True,
                "RemoteConsolePriv": True,
                "SystemRecoveryConfigPriv": True,
                "UserConfigPriv": True,
                "VirtualMediaPriv": True,
                "VirtualPowerAndResetPriv": True,
                "iLOConfigPriv": True,
            }
            if "Oem" in ses.dict:
                sesoemhp = ses.dict["Oem"][self.rdmc.app.typepath.defs.oemhp]
                if "Privileges" in list(sesoemhp.keys()):
                    sesprivs = sesoemhp["Privileges"]
            availableprivs = list(sesprivs.keys())
            keepprivs = dict()
            for priv, val in sesprivs.items():
                if val:
                    keepprivs[priv] = sesprivs[priv]
            sesprivs = keepprivs
        else:
            sesprivs = None

        if availableprivsopts:
            return availableprivs
        else:
            return sesprivs

    def addvalidation(self, username, key, feds):
        """add validation function
        :param username: username to be added
        :type username: str.
        :param key: key to be added
        :type key: str.
        :param feds: list of federation accounts
        :type feds: list.
        """

        if len(username) >= 32:
            raise InvalidCommandLineError("User name exceeds maximum length.")
        elif len(key) >= 32 or len(key) <= 7:
            raise InvalidCommandLineError("Password is invalid length.")

    def ilofederationvalidation(self, options):
        """addfederation validation function
        :param options: command line options
        :type options: list.
        """
        self.cmdbase.login_select_validation(self, options)

    @staticmethod
    def options_addprivs_argument_group(parser):
        """Define optional arguments group
        :param parser: The parser to add the addprivs option group to
        :type parser: ArgumentParser/OptionParser
        """
        parser.add_argument(
            "--addprivs",
            dest="optprivs",
            nargs="*",
            action=_FederationParse,
            type=str,
            help="Optionally include this flag if you wish to specify "
            "which privileges you want added to the iLO federation. This overrides the default of "
            "duplicating privileges of the currently logged in federation on the new federation. "
            "Pick privileges from the privilege list in the above help text. EX: --addprivs=1,2,4",
            default=None,
        )

    @staticmethod
    def options_removeprivs_argument_group(parser):
        """Additional argument
        :param parser: The parser to add the removeprivs option group to
        :type parser: ArgumentParser/OptionParser
        """

        parser.add_argument(
            "--removeprivs",
            dest="optprivs",
            nargs="*",
            action=_FederationParse,
            type=str,
            help="Optionally include this flag if you wish to specify "
            "which privileges you want removed from the iLO federation. This overrides the default"
            " of duplicating privileges of the currently logged in federation on the new "
            "federation. Pick privileges from the privilege list in the above help text. "
            "EX: --removeprivs=1,2,4",
            default=None,
        )

    def definearguments(self, customparser):
        """Wrapper function for new command main function
        :param customparser: command line input
        :type customparser: parser.
        """
        if not customparser:
            return

        self.cmdbase.add_login_arguments_group(customparser)
        subcommand_parser = customparser.add_subparsers(dest="command")
        privilege_help = (
            "\n\nPRIVILEGES:\n\t1: Login\n\t2: Remote Console\n\t3: User Config\n\t4:"
            " iLO Config\n\t5: Virtual Media\n\t6: Virtual Power and Reset\n\n\tiLO 5 added "
            "privileges:\n\t7: Host NIC Config\n\t8: Host Bios Config\n\t9: Host Storage Config"
            "\n\t10: System Recovery Config"
        )
        # default sub-parser
        default_parser = subcommand_parser.add_parser(
            "default",
            help="Running without any sub-command will return all federation group information "
            " on the currently logged in server.",
        )
        default_parser.add_argument(
            "-j",
            "--json",
            dest="json",
            action="store_true",
            help="Optionally include this flag if you wish to change the"
            " displayed output to JSON format. Preserving the JSON data"
            " structure makes the information easier to parse.",
            default=False,
        )
        self.cmdbase.add_login_arguments_group(default_parser)  # add sub-parser
        add_help = (
            "Adds an iLO federation group to the currently logged in server. Federation "
            'group privileges may be specified with\n"--addprivs". If a federation key '
            "is not "
            "provided, the user will be prompted to provide one prior to account creation."
        )
        add_parser = subcommand_parser.add_parser(
            __subparsers__[0],
            help=add_help,
            description=add_help
            + "\n\tilofederation add [FEDERATIONNAME] [FEDERATIONKEY] "
            + privilege_help
            + "\n\tilofederation add newilofedname thisfedkey --addprivs 1,3,4",
            formatter_class=RawDescriptionHelpFormatter,
        )
        add_parser.add_argument(
            "fedname",
            help="Federation name of the federation group to add.",
            type=str,
            metavar="FEDERATION NAME",
        )
        add_parser.add_argument(
            "fedkey",
            help="Federation key of the federation group to add.",
            type=str,
            metavar="FEDERATION KEY",
        )
        self.options_addprivs_argument_group(add_parser)
        self.cmdbase.add_login_arguments_group(add_parser)

        modify_help = "Modify the privileges on an existing federation group."
        modify_parser = subcommand_parser.add_parser(
            __subparsers__[1],
            help=modify_help,
            description=modify_help + "\n\nTo add privileges:\n\tilofederation modify "
            "[FEDNAME] --addprivs <list of numbered privileges>\n\nTo remove privileges:\n\t"
            "ilofederation modify [FEDNAME] --removeprivs <list of numbered privileges>\n\n" + privilege_help,
            formatter_class=RawDescriptionHelpFormatter,
        )
        modify_parser.add_argument(
            "fedname",
            help="The federation name of the iLO account to modify.",
            metavar="FEDERATION NAME",
            type=str,
        )
        self.options_addprivs_argument_group(modify_parser)
        self.options_removeprivs_argument_group(modify_parser)
        self.cmdbase.add_login_arguments_group(modify_parser)

        # changepass sub-parser
        changekey_help = "Change the key of an iLO federation group on the currently logged in " "server."
        changekey_parser = subcommand_parser.add_parser(
            __subparsers__[2],
            help=changekey_help,
            description=changekey_help + "\n\nexample:ilofederation changekey [FEDNAME] [NEWFEDKEY]",
            formatter_class=RawDescriptionHelpFormatter,
        )
        changekey_parser.add_argument(
            "fedname",
            help="The iLO federation account to be updated with a new federation key (password).",
            metavar="FEDERATION NAME",
            type=str,
        )
        changekey_parser.add_argument(
            "fedkey",
            help="The federation key (password) to be altered for the selected iLO federation "
            " account. If you do not include a federation key, you will be prompted to enter one.",
            metavar="FEDERATION KEY",
            type=str,
            nargs="?",
            default="",
        )
        self.cmdbase.add_login_arguments_group(changekey_parser)

        # delete sub-parser
        delete_help = "Deletes the provided iLO user account on the currently logged in server."
        delete_parser = subcommand_parser.add_parser(
            __subparsers__[3],
            help=delete_help,
            description=delete_help + "\n\nexample: ilofederation delete fedname",
            formatter_class=RawDescriptionHelpFormatter,
        )
        delete_parser.add_argument(
            "fedname",
            help="The iLO federation account to delete.",
            metavar="FEDERATION NAME",
            type=str,
        )
        self.cmdbase.add_login_arguments_group(delete_parser)
