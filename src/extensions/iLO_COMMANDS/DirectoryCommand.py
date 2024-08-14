###
# Copyright 2017 Hewlett Packard Enterprise, Inc. All rights reserved.
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
""" Directory Command for rdmc """

import re
import sys
from argparse import Action, RawDescriptionHelpFormatter

from redfish.ris.rmc_helper import IdTokenError, IloResponseError

try:
    from rdmc_helper import (
        IncompatibleiLOVersionError,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        NoContentsFoundForOperationError,
        ResourceExists,
        ReturnCodes,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        IncompatibleiLOVersionError,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        NoContentsFoundForOperationError,
        ResourceExists,
        ReturnCodes,
    )

__subparsers__ = ["ldap", "kerberos", "test"]

PRIVKEY = {
    1: ("Login", "AssignedPrivileges"),
    2: ("RemoteConsolePriv", "OemPrivileges"),
    3: ("ConfigureUsers", "AssignedPrivileges"),
    4: ("ConfigureManager", "AssignedPrivileges"),
    5: ("VirtualMediaPriv", "OemPrivileges"),
    6: ("VirtualPowerAndResetPriv", "OemPrivileges"),
    7: ("HostNICConfigPriv", "OemPrivileges"),
    8: ("HostBIOSConfigPriv", "OemPrivileges"),
    9: ("HostStorageConfigPriv", "OemPrivileges"),
    10: ("SystemRecoveryConfigPriv", "OemPrivileges"),
    11: ("ConfigureSelf", "AssignedPrivileges"),
    12: ("ConfigureComponents", "AssignedPrivileges"),
}


class _DirectoryParse(Action):
    def __init__(self, option_strings, dest, nargs, **kwargs):
        super(_DirectoryParse, self).__init__(option_strings, dest, nargs, **kwargs)

    def __call__(self, parser, namespace, values, option_strings):
        """Helper for parsing options"""
        if option_strings.endswith("disable"):
            setattr(namespace, self.dest, False)
        elif option_strings.endswith("enable"):
            setattr(namespace, self.dest, True)
        elif option_strings.endswith("enablelocalauth"):
            setattr(namespace, self.dest, False)
        elif option_strings.endswith("disablelocalauth"):
            setattr(namespace, self.dest, True)
        elif option_strings == "--removerolemap":
            setattr(namespace, self.dest, {"remove": []})
            for role in next(iter(values)).split("#"):
                role = role.replace('"', "")
                if role:
                    namespace.roles["remove"].append(role)
        elif option_strings == "--addrolemap":
            setattr(namespace, self.dest, {"add": []})
            for role in next(iter(values)).split("#"):
                role = role.replace('"', "")
                if role and re.match(".*:.*", role):
                    privs = role.split(":")[0].split(";")
                    if len(privs) > 1:
                        for priv in privs:
                            try:
                                if priv and int(priv) > 12:
                                    try:
                                        parser.error("Invalid privilege number added %s." % priv)
                                    except SystemExit:
                                        raise InvalidCommandLineErrorOPTS("")
                            except ValueError:
                                try:
                                    parser.error("Privileges must be added as numbers.")
                                except SystemExit:
                                    raise InvalidCommandLineErrorOPTS("")
                    namespace.roles["add"].append(role)
                else:
                    try:
                        parser.error("Supply roles to add in form <local role>:<remote group>")
                    except SystemExit:
                        raise InvalidCommandLineErrorOPTS("")
        elif option_strings == "--addsearch":
            setattr(namespace, self.dest, {"add": []})
            for search in next(iter(values)).split(";"):
                if search:
                    namespace.search["add"].append(search)

        elif option_strings == "--removesearch":
            setattr(namespace, self.dest, {"remove": []})
            for search in next(iter(values)).split(";"):
                if search:
                    namespace.search["remove"].append(search)


class DirectoryCommand:
    """Update directory settings on the server"""

    def __init__(self):
        self.ident = {
            "name": "directory",
            "usage": None,
            "description": "\tAdd credentials, service address, two search strings, and enable"
            "\n\tLDAP directory service, remote role groups (mapping), local custom role\n\t"
            "IDs with privileges.\n\n\tTo view help on specific sub-commands"
            " run: directory <sub-command> -h\n\n\tExample: directory ldap -h\n",
            "summary": "Update directory settings, add/delete directory roles, and test directory "
            "settings on the currently logged in server.",
            "aliases": ["ad", "activedirectory"],
            "auxcommands": ["IloAccountsCommand"],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """Main directory Function

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

        self.directoryvalidation(options)

        if self.rdmc.app.getiloversion() < 5.140:
            raise IncompatibleiLOVersionError("Directory settings are only available on " "iLO 5 1.40 or greater.")
        results = None
        if options.command.lower() == "ldap" or (
            (True if options.ldap_kerberos == "ldap" else False) if hasattr(options, "ldap_kerberos") else False
        ):
            try:
                results = self.rdmc.app.select(selector="AccountService.", path_refresh=True)[0].dict
                path = results[self.rdmc.app.typepath.defs.hrefstring]
                oem = results["Oem"][self.rdmc.app.typepath.defs.oemhp]
                local_auth = results["LocalAccountAuth"]
                results = results["LDAP"]
                if "RemoteRoleMapping" not in results:
                    rolemap = {"RemoteRoleMapping": {}}
                    results.update(rolemap)
                name = "LDAP"
            except (KeyError, IndexError):
                raise NoContentsFoundForOperationError("Unable to gather LDAP settings.")

        elif options.command.lower() == "kerberos" or (
            (True if options.ldap_kerberos == "kerberos" else False) if hasattr(options, "ldap_kerberos") else False
        ):
            try:
                results = self.rdmc.app.select(selector="AccountService.", path_refresh=True)[0].dict
                path = results[self.rdmc.app.typepath.defs.hrefstring]
                oem = results["Oem"][self.rdmc.app.typepath.defs.oemhp]
                local_auth = results["LocalAccountAuth"]
                results = results["ActiveDirectory"]
                if "RemoteRoleMapping" not in results:
                    rolemap = {"RemoteRoleMapping": {}}
                    results.update(rolemap)
                name = "ActiveDirectory"
            except (KeyError, IndexError):
                raise NoContentsFoundForOperationError("Unable to gather Kerberos settings.")

        if results:
            keytab = None
            payload = {}
            if hasattr(options, "keytab"):
                keytab = options.keytab
            try:
                directory_settings = self.directory_helper(results, options)
                if "ldap" in line and options.roles and "add" in options.roles:
                    role_val = options.roles["add"]
                    for r in role_val:
                        if ";" in r.split(":")[0]:
                            name = "ActiveDirectory"
                            break
            except IndexError:
                directory_settings = self.directory_helper(results, options)

            if directory_settings:
                payload[name] = directory_settings

            if hasattr(options, "authmode"):
                if options.authmode:
                    payload.update(
                        {"Oem": {"Hpe": {"DirectorySettings": {"LdapAuthenticationMode": options.authmode}}}}
                    )

            if not payload and not keytab:
                if getattr(options, "json", False):
                    # self.rdmc.ui.print_out_json({name: results, 'LocalAccountAuth': local_auth,
                    #                             "Oem": {"Hpe": oem}})
                    text_content = self.print_s(results, oem, local_auth, name)
                    self.rdmc.ui.print_out_json(text_content)
                else:
                    self.print_settings(results, oem, local_auth, name)

            if payload:
                priv_patches = {}
                try:
                    if hasattr(options, "localauth"):
                        if options.localauth:
                            payload["LocalAccountAuth"] = "Enabled" if options.localauth else "Disabled"
                    elif local_auth:
                        payload["LocalAccountAuth"] = "Enabled" if local_auth else "Disabled"
                except (NameError, AttributeError):
                    payload["LocalAccountAuth"] = "Disabled"
                try:
                    maps = {}
                    if payload.get("LDAP"):
                        maps = payload["LDAP"].get("RemoteRoleMapping", {})
                    elif payload.get("ActiveDirectory"):
                        maps = payload["ActiveDirectory"].get("RemoteRoleMapping", {})
                        # Check if we need to modify roles after creating
                        for mapping in maps:
                            privs = mapping["LocalRole"].split(";")
                            if len(privs) > 1:
                                privs = [int(priv) for priv in privs if priv]

                                if 10 in privs:
                                    user_privs = self.auxcommands["iloaccounts"].getsesprivs()
                                    if "SystemRecoveryConfigPriv" not in list(user_privs.keys()):
                                        raise IdTokenError(
                                            "The currently logged in account "
                                            "must have the System Recovery Config privilege to "
                                            "add the System Recovery Config privilege to a local "
                                            "role group."
                                        )

                                priv_patches[mapping["RemoteGroup"]] = privs
                                mapping["LocalRole"] = "ReadOnly"
                except Exception as excp:
                    self.rdmc.ui.error(excp)
                self.rdmc.ui.printer("Changing settings...\n")
                try:
                    self.rdmc.app.patch_handler(path, payload)
                except IloResponseError as excp:
                    if not results["ServiceEnabled"]:
                        self.rdmc.ui.error(
                            "You must enable this directory service before or "
                            "during assignment of username and password. Try adding the flag "
                            "--enable.\n",
                            excp,
                        )
                    else:
                        raise IloResponseError
                if priv_patches:
                    self.update_mapping_privs(priv_patches)
            if keytab:
                path = oem["Actions"][next(iter(oem["Actions"]))]["target"]
                self.rdmc.ui.printer("Adding keytab...\n")
                self.rdmc.app.post_handler(path, {"ImportUri": keytab})
        elif options.command.lower() == "test":
            self.test_directory(options, json=getattr(options, "json", False))
        self.cmdbase.logout_routine(self, options)
        # Return code
        return ReturnCodes.SUCCESS

    def update_mapping_privs(self, roles_to_update):
        """Helper function to update created role mappings to match user privileges.

        :param roles_to_update: Dictionary of privileges to update.
        :type roles_to_update: dict
        """
        self.rdmc.ui.printer("Updating privileges of created role maps...\n")
        try:
            results = self.rdmc.app.select(selector="AccountService.", path_refresh=True)[0].dict
            roles = self.rdmc.app.getcollectionmembers(self.rdmc.app.getidbytype("RoleCollection.")[0])
        except (KeyError, IndexError):
            raise NoContentsFoundForOperationError(
                "Unable to gather Role settings. Roles may not " "be updated to match privileges requested."
            )
        for rolemap in results["LDAP"]["RemoteRoleMapping"]:
            for role in roles:
                if role["RoleId"] == rolemap["LocalRole"]:
                    role["RemoteGroup"] = rolemap["RemoteGroup"]
                    break
        for role in roles:
            privs = {"AssignedPrivileges": [], "OemPrivileges": []}

            for update_role in list(roles_to_update.keys()):
                if role.get("RemoteGroup", None) == update_role:
                    for priv in roles_to_update[update_role]:
                        privs[PRIVKEY[priv][1]].append(PRIVKEY[priv][0])
                    try:
                        self.rdmc.app.patch_handler(role["@odata.id"], privs)
                        self.rdmc.ui.printer("Updated privileges for %s\n" % update_role)
                    except IloResponseError as excp:
                        self.rdmc.ui.error("Unable to update privileges for %s\n" % update_role, excp)
                    break

    def directory_helper(self, settings, options):
        """Helper function to set the payload based on options and arguments

        :param settings: dictionary to change
        :type settings: dict.
        :param options: list of options
        :type options: list.
        """

        payload = {}
        serviceaddress = None

        if hasattr(options, "serviceaddress"):
            if isinstance(options.serviceaddress, str):
                serviceaddress = options.serviceaddress
                if serviceaddress == '""' or serviceaddress == "''":
                    serviceaddress = ""
        if hasattr(options, "port"):
            if isinstance(options.port, str):
                if serviceaddress is None:
                    serviceaddress = settings["ServiceAddresses"][0]
                serviceaddress = serviceaddress + ":" + options.port
        if hasattr(options, "realm"):
            if isinstance(options.realm, str):
                if serviceaddress is None:
                    serviceaddress = settings["ServiceAddresses"][0]
                if options.realm == '""' or options.realm == "''":
                    options.realm = ""
                serviceaddress = serviceaddress + "@" + options.realm
        if serviceaddress is not None:
            payload["ServiceAddresses"] = [serviceaddress]

        if hasattr(options, "enable"):
            if options.enable is not None:
                payload["ServiceEnabled"] = options.enable

        if hasattr(options, "ldap_username") and hasattr(options, "ldap_password"):
            if options.ldap_username and options.ldap_password:
                payload.update(
                    {
                        "Authentication": {
                            "Username": options.ldap_username,
                            "Password": options.ldap_password,
                        }
                    }
                )

        if hasattr(options, "roles"):
            if options.roles:
                payload["RemoteRoleMapping"] = self.role_helper(options.roles, settings["RemoteRoleMapping"])

        if hasattr(options, "search"):
            if options.search:
                payload.update(
                    {
                        "LDAPService": {
                            "SearchSettings": self.search_helper(
                                options.search,
                                settings["LDAPService"]["SearchSettings"],
                            )
                        }
                    }
                )
        return payload

    def test_directory(self, options, json=False):
        """Function to perform directory testing

        :param options: namespace of custom parser attributes which contain the original command
                        arguments for 'start/stop/viewresults'
        :type options: namespace
        :param json: Bool to print in json format or not.
        :type json: bool.
        """
        results = self.rdmc.app.select(selector="HpeDirectoryTest.", path_refresh=True)[0].dict
        if options.start_stop_view.lower() == "start":
            path = None
            for item in results["Actions"]:
                if "StartTest" in item:
                    path = results["Actions"][item]["target"]
                    break
            if not path:
                raise NoContentsFoundForOperationError("Unable to start directory test.")
            self.rdmc.ui.printer(
                "Starting the directory test. Monitor results with " 'command: "directory test viewresults".\n'
            )
            self.rdmc.app.post_handler(path, {})
        elif options.start_stop_view.lower() == "stop":
            path = None
            for item in results["Actions"]:
                if "StopTest" in item:
                    path = results["Actions"][item]["target"]
                    break
            if not path:
                raise NoContentsFoundForOperationError("Unable to stop directory test.")
            self.rdmc.ui.printer("Stopping the directory test.\n")
            self.rdmc.app.post_handler(path, {})
        elif options.start_stop_view.lower() == "viewresults":
            if getattr(options, "json", False):
                self.rdmc.ui.print_out_json(results["TestResults"])
            else:
                for test in results["TestResults"]:
                    self.rdmc.ui.printer("Test: %s\n" % test["TestName"])
                    self.rdmc.ui.printer("------------------------\n")
                    self.rdmc.ui.printer("Status: %s\n" % test["Status"])
                    self.rdmc.ui.printer("Notes: %s\n\n" % test["Notes"])

    def print_s(self, settings, oem_settings, local_auth_setting, name):
        setting = "Kerberos" if name == "ActiveDirectory" else name
        enable = str(settings["ServiceEnabled"])
        serviceaddress = settings["ServiceAddresses"][0]
        address = serviceaddress if serviceaddress else "Not Set"
        username = settings["Authentication"]["Username"]
        dis_name = username if username else "Not Set"
        auth = local_auth_setting
        content = {
            "Settings": setting,
            "Enabled": enable,
            "Service Address": address,
            "Distinguished Name": dis_name,
            "Local Account Authorization": auth,
        }
        if name.lower() == "activedirectory":
            address_settings = oem_settings["KerberosSettings"]
            port = address_settings["KDCServerPort"]
            realm = address_settings["KerberosRealm"] if address_settings["KerberosRealm"] else "Not Set"
            content.update({"Port": port, "Realm": realm})

        else:
            address_settings = oem_settings["DirectorySettings"]
            port = address_settings["LdapServerPort"]
            authmode = address_settings["LdapAuthenticationMode"]
            content.update({"Port": port, "Authentication Mode": authmode})
            addsearch = []
            try:
                count = 1
                for search in settings["LDAPService"]["SearchSettings"]["BaseDistinguishedNames"]:
                    # search = (count, search)
                    search = "Search %s: %s" % (count, search)
                    addsearch.append(search)
                    count += 1
                content.update({"Search Settings": addsearch})
            except KeyError:
                search = "No Search Settings"
                content.update({"Search Settings": {search}})
        addval = []
        if "RemoteRoleMapping" in settings:
            if len(settings["RemoteRoleMapping"]) > 0:
                for role in settings["RemoteRoleMapping"]:
                    roleadd = {
                        "Local Role": role["LocalRole"],
                        "Remote Group": role["RemoteGroup"],
                    }
                    addval.append(roleadd)
                content.update({"Remote Role Mapping(s)": addval})
            else:
                addval = {"No Remote Role Mappings"}
                content.update({"Remote Role Mapping(s)": addval})
        else:
            content.update({"No Remote Role Mappings"})
        return content

    def print_settings(self, settings, oem_settings, local_auth_setting, name):
        """Pretty print settings of LDAP or Kerberos

        :param settings: settings to print
        :type settings: dict.
        :param oem_settings: oem_settings to print
        :type oem_settings: dict.
        :param local_auth_settings: local authorization setting
        :type local_auth_settings: str.
        :param name: type of setting (activedirectory or ldap)
        :type name: str.
        """

        self.rdmc.ui.printer("%s settings:\n" % ("Kerberos" if name == "ActiveDirectory" else name))
        self.rdmc.ui.printer("--------------------------------\n")
        self.rdmc.ui.printer("Enabled: %s\n" % str(settings["ServiceEnabled"]))

        serviceaddress = settings["ServiceAddresses"][0]

        self.rdmc.ui.printer("Service Address: %s\n" % (serviceaddress if serviceaddress else "Not Set"))
        username = settings["Authentication"]["Username"]
        self.rdmc.ui.printer("Distinguished Name: %s\n" % (username if username else "Not Set"))

        self.rdmc.ui.printer("Local Account Authorization: %s\n" % local_auth_setting)

        if name.lower() == "activedirectory":
            address_settings = oem_settings["KerberosSettings"]
            self.rdmc.ui.printer("Port: %s\n" % address_settings["KDCServerPort"])

            self.rdmc.ui.printer(
                "Realm: %s\n" % (address_settings["KerberosRealm"] if address_settings["KerberosRealm"] else "Not Set")
            )
        else:
            address_settings = oem_settings["DirectorySettings"]
            self.rdmc.ui.printer("Port: %s\n" % address_settings["LdapServerPort"])
            self.rdmc.ui.printer("Authentication Mode: %s\n" % address_settings["LdapAuthenticationMode"])

            try:
                self.rdmc.ui.printer("Search Settings:\n")
                count = 1
                for search in settings["LDAPService"]["SearchSettings"]["BaseDistinguishedNames"]:
                    self.rdmc.ui.printer("\tSearch %s: %s\n" % (count, search))
                    count += 1
            except KeyError:
                self.rdmc.ui.printer("\tNo Search Settings\n")

        if "RemoteRoleMapping" in settings:
            self.rdmc.ui.printer("Remote Role Mapping(s):\n")
            if len(settings["RemoteRoleMapping"]) > 0:
                for role in settings["RemoteRoleMapping"]:
                    self.rdmc.ui.printer("\tLocal Role: %s\n" % role["LocalRole"])
                    self.rdmc.ui.printer("\tRemote Group: %s\n" % role["RemoteGroup"])
            else:
                self.rdmc.ui.printer("\tNo Remote Role Mappings.\n")
        else:
            self.rdmc.ui.printer("No Remote Role Mappings.\n")

    def role_helper(self, new_roles, curr_roles):
        """Helper to prepare adding and removing roles for patching

        :param new_roles: dictionary of new roles to add or remove
        :type new_roles: dict.
        :param curr_roles: list of current roles on the system
        :type curr_roles: list.
        """
        final_roles = curr_roles
        if "add" in new_roles:
            for role in new_roles["add"]:
                role = role.split(":", 1)
                if not self.duplicate_group(role[1], curr_roles):
                    if len(curr_roles) > 0:
                        final_roles.append({"LocalRole": role[0], "RemoteGroup": role[1]})
                    else:
                        final_roles = [{"LocalRole": role[0], "RemoteGroup": role[1]}]
                        curr_roles = final_roles

                else:
                    raise ResourceExists('Group DN "%s" already exists.' % role[1].split(":")[0])
        if "remove" in new_roles:
            removed = False
            for role in new_roles["remove"]:
                removed = False
                for item in reversed(final_roles):
                    if item["LocalRole"] == role:
                        if len(curr_roles) > 1:
                            del final_roles[final_roles.index(item)]
                            removed = True
                            break
                        elif len(curr_roles) == 1:
                            del final_roles[final_roles.index(item)]
                            final_roles = [{}]
                            removed = True
                            break
                if not removed:
                    raise InvalidCommandLineError("Unable to find local role %s to delete" % role)
        return final_roles

    def duplicate_group(self, group_dn, curr_roles):
        """Checks if new role is a duplicate

        :param group_dn: group domain name from user
        :type group_dn: str.
        :param curr_roles: list of current roles
        :type curr_roles: list.
        """
        group_dn = group_dn.split(":")[0]
        for item in curr_roles:
            comp_dn = item["RemoteGroup"].split(":")[0]
            if comp_dn == group_dn:
                return True
        return False

    def search_helper(self, new_searches, curr_searches):
        """Helper to prepare search strings for patching

        :param new_serches: dictionary of new searches to add
        :type new_searches: dict.
        :param curr_searches: list of current searches
        :type curr_searches: dict.
        """
        final_searches = curr_searches

        if "add" in new_searches:
            if "BaseDistinguishedNames" in final_searches:
                for search in new_searches["add"]:
                    for key, value in final_searches.items():
                        for v in value:
                            if search.lower() == v.lower():
                                raise ResourceExists('Search Setting "%s" already exists.\n' % search)

                    final_searches["BaseDistinguishedNames"].append(search)
            else:
                final_searches["BaseDistinguishedNames"] = new_searches["add"]
        elif "remove" in new_searches:
            to_remove = []

            if "BaseDistinguishedNames" not in curr_searches:
                raise NoContentsFoundForOperationError("No search strings to remove")

            for search in new_searches["remove"]:
                if search in curr_searches["BaseDistinguishedNames"]:
                    to_remove.append(search)
                else:
                    raise InvalidCommandLineError("Unable to find search %s to delete" % search)
            for item in to_remove:
                final_searches["BaseDistinguishedNames"].remove(item)

            if not final_searches["BaseDistinguishedNames"]:
                sys.stdout.write("Attempting to delete all searches.\n")
                final_searches["BaseDistinguishedNames"].append("")

        return final_searches

    def directoryvalidation(self, options):
        """directory validation function

        :param options: command line options
        :type options: list.
        """
        self.cmdbase.login_select_validation(self, options)

    def options_argument_group(self, parser):
        """Additional argument

        :param parser: The parser to add the removeprivs option group to
        :type parser: ArgumentParser/OptionParser
        """

        parser.add_argument(
            "-j",
            "--json",
            dest="json",
            action="store_true",
            help="Optionally include this flag if you wish to change the"
            " displayed output to JSON format. Preserving the JSON data"
            " structure makes the information easier to parse.",
            default=False,
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
        default_parser = subcommand_parser.add_parser("default")

        default_parser.add_argument(
            "ldap_kerberos",
            help="Specify LDAP or Kerberos configuration settings",
            metavar="LDAP_KERBEROS",
            nargs="?",
            type=str,
            default=None,
        )
        self.cmdbase.add_login_arguments_group(default_parser)

        privilege_help = (
            "\n\nPRIVILEGES:\n\t1: Login\n\t2: Remote Console\n\t"
            "3: User Config\n\t4: iLO (Manager) Config\n\t5: Virtual Media\n\t"
            "6: Virtual Power and Reset\n\t7: Host NIC Config\n\t8: Host Bios Config\n\t9: "
            "Host Storage Config\n\t10: System Recovery Config\n\t11: Self Password Change\n\t"
            "12: Configure Components\n\n\tLOCAL ROLES:\n\tReadOnly\n\tOperator\n\tAdministrator"
            "\n\n\tNOTE: The Self Password Change privilege is automatically added to roles with "
            "the Login privilege."
        )
        ldap_help = "Show, add or modify properties pertaining to iLO LDAP Configuration."
        ldap_parser = subcommand_parser.add_parser(
            __subparsers__[0],
            help=ldap_help,
            description=ldap_help + "\n\n\tSimply show LDAP configuration:\n\t\tdirectory ldap\n\n"
            "To modify the LDAP username, password, service address, search strings or "
            "enable/disable LDAP.\n\t\tdirectory ldap <username> <password> "
            '--serviceaddress x.x.y.z --addsearch "string1;string2" --enable.\n\n\tTo add role '
            'mapping.\n\t\tdirectory ldap <username> <password> --addrolemap "LocalRole1:'
            'RemoteGroup3#LocalRole2:RemoteGroup4:SID".\n\n\tTo remove role mapping.\n\t\t'
            "directory ldap <username> <password> --removerolemap LocalRole1#LocalRole2." + privilege_help,
            formatter_class=RawDescriptionHelpFormatter,
        )
        ldap_parser.add_argument(
            "ldap_username",
            help="The LDAP username used in verifying AD (optional outside of '--enable' and" "'--disable')",
            metavar="USERNAME",
            nargs="?",
            type=str,
            default=None,
        )
        ldap_parser.add_argument(
            "ldap_password",
            help="The LDAP password used in verifying AD (optional outside of '--enable' and" "'--disable')",
            metavar="PASSWORD",
            nargs="?",
            type=str,
            default=None,
        )
        ldap_parser.add_argument(
            "--enable",
            "--disable",
            dest="enable",
            type=str,
            nargs="*",
            action=_DirectoryParse,
            help="Optionally add this flag to enable LDAP services.",
            default=None,
        )
        ldap_parser.add_argument(
            "--addsearch",
            "--removesearch",
            dest="search",
            nargs="*",
            action=_DirectoryParse,
            help="Optionally add this flag to add or remove search strings for " "generic LDAP services.",
            type=str,
            default={},
        )
        ldap_parser.add_argument(
            "--serviceaddress",
            dest="serviceaddress",
            help="Optionally include this flag to set the service address of the LDAP Services.",
            default=None,
        )
        ldap_parser.add_argument(
            "--port",
            dest="port",
            help="Optionally include this flag to set the port of the LDAP services.",
            default=None,
        )
        ldap_parser.add_argument(
            "--addrolemap",
            "--removerolemap",
            dest="roles",
            nargs="*",
            action=_DirectoryParse,
            help="Optionally add this flag to add or remove Role Mapping(s) for the LDAP."
            " Remove EX: --removerolemap LocalRole1#LocalRole2 "
            'Add EX: --addrolemap "LocalRole1:RemoteGroup3#LocalRole2:RemoteGroup4\n\n"'
            'SID EX: --addrolemap "LocalRole1:RemoteGroup2:SID#LocalRole2:RemoteGroup5:SID"'
            "\n\nNOTE 1: Create a custom local role group (and subsequently assign to a role map)"
            "by adding the numbers associated with privilege(s) desired separated by a semicolon"
            "(;)\n\nNOTE 2: SID is optional",
            type=str,
            default={},
        )
        ldap_parser.add_argument(
            "--enablelocalauth",
            "--disablelocalauth",
            dest="localauth",
            nargs="*",
            type=str,
            action=_DirectoryParse,
            help="Optionally include this flag if you wish to enable or disable authentication " "for local accounts.",
            default=None,
        )
        ldap_parser.add_argument(
            "--authentication",
            dest="authmode",
            choices=["DefaultSchema", "ExtendedSchema"],
            help="Optionally include this flag if you would like to choose a LDAP authentication "
            "mode Valid choices are: DefaultSchema (Directory Default Schema or Schema-free) or "
            "ExtendedSchema (HPE Extended Schema).",
            default=None,
        )
        self.cmdbase.add_login_arguments_group(ldap_parser)

        self.options_argument_group(ldap_parser)

        kerberos_help = "Show, add or modify properties pertaining to AD Kerberos Configuration."
        kerberos_parser = subcommand_parser.add_parser(
            __subparsers__[1],
            help=kerberos_help,
            description=kerberos_help + "\n\nExamples:\n\nShow Kerberos specific AD/LDAP configuration "
            "settings.\n\tdirectory kerberos\n\nShow current AD Kerberos configuration."
            "\n\tdirectory kerberos\n\nAlter kerberos service address, AD realm and Port.\n\t"
            "directory kerberos --serviceaddress x.x.y.z --port 8888 --realm adrealm1",
            formatter_class=RawDescriptionHelpFormatter,
        )
        kerberos_parser.add_argument(
            "--serviceaddress",
            dest="serviceaddress",
            help="Optionally include this flag to set the Kerberos serviceaddress.",
            default=None,
        )
        kerberos_parser.add_argument(
            "--port",
            dest="port",
            help="Optionally include this flag to set the Kerberos port.",
            default=None,
        )
        kerberos_parser.add_argument(
            "--realm",
            dest="realm",
            help="Optionally include this flag to set the Kerberos realm.",
            default=None,
        )
        kerberos_parser.add_argument(
            "--keytab",
            dest="keytab",
            help="Optionally include this flag to import a Kerberos Keytab by it's URI location.",
            default="",
        )
        kerberos_parser.add_argument(
            "--enable",
            "--disable",
            dest="enable",
            type=str,
            nargs="*",
            action=_DirectoryParse,
            help="Optionally add this flag to enable or disable Kerberos services.",
            default=None,
        )
        self.cmdbase.add_login_arguments_group(kerberos_parser)

        self.options_argument_group(kerberos_parser)

        directory_test_help = (
            "Start, stop or view results of an AD/LDAP test which include: ICMP, "
            "Domain Resolution, Connectivity, Authentication, Bindings, LOM Object and User "
            "Context tests."
        )
        directory_test_parser = subcommand_parser.add_parser(
            __subparsers__[2],
            help=directory_test_help,
            description=directory_test_help + "\n\nExamples:\n\nStart a directory test:\n\tdirectory test "
            "start\n\nStop a directory test:\n\tdirectory test stop\n\nView results of the last "
            "directory test:\n\tdirectory test viewresults",
            formatter_class=RawDescriptionHelpFormatter,
        )
        directory_test_parser.add_argument(
            "start_stop_view",
            help="Start, stop, or view results on an AD/LDAP test.",
            metavar="START, STOP, VIEWRESULTS",
            default="viewresults",
        )
        self.cmdbase.add_login_arguments_group(directory_test_parser)
