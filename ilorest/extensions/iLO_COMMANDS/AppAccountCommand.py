###
# Copyright 2016-2024 Hewlett Packard Enterprise, Inc. All rights reserved.
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
""" AppAccount command for rdmc """
import ctypes
import os
from argparse import RawDescriptionHelpFormatter
from redfish.hpilo.vnichpilo import AppAccount
from redfish.rest.connections import ChifDriverMissingOrNotFound, VnicNotEnabledError
import redfish

from redfish.ris.rmc_helper import UserNotAdminError

try:
    from rdmc_helper import (
        Encryption,
        GenerateAndSaveAccountError,
        RemoveAccountError,
        AppAccountExistsError,
        ReturnCodes,
        InvalidCommandLineErrorOPTS,
        IncompatibleiLOVersionError,
        InvalidCommandLineError,
        UsernamePasswordRequiredError,
        NoAppAccountError,
        VnicExistsError,
        SavinginTPMError,
        SavinginiLOError,
        GenBeforeLoginError,
        AppIdListError,
        UI,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        Encryption,
        GenerateAndSaveAccountError,
        RemoveAccountError,
        AppAccountExistsError,
        ReturnCodes,
        InvalidCommandLineErrorOPTS,
        IncompatibleiLOVersionError,
        InvalidCommandLineError,
        UsernamePasswordRequiredError,
        NoAppAccountError,
        VnicExistsError,
        SavinginTPMError,
        SavinginiLOError,
        GenBeforeLoginError,
        AppIdListError,
        UI,
    )


class AppAccountCommand:
    """Main command template"""

    def __init__(self):
        self.ident = {
            "name": "appaccount",
            "usage": "appaccount\n\n",
            "description": "Manages application accounts in iLO and TPM, allowing creation,"
            "deletion, and verification with appaccount create, appaccount delete, "
            "and appaccount exists."
            "Retrieves details of all application accounts using appaccount details.\n"
            "Supported only on VNIC-enabled iLO7 servers.\n"
            "For help on specific subcommands, run: appaccount <sub-command> -h.\n\n",
            "summary": "Creates/Deletes application account, Checks the existence of an"
            " application account, Provides details on all app accounts present in the server.",
            "aliases": [],
            "auxcommands": [],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        if help_disp:
            line.append("-h")
            try:
                (_, _) = self.rdmc.rdmc_parse_arglist(self, line)
            except:
                return ReturnCodes.SUCCESS
            return ReturnCodes.SUCCESS
        try:
            (options, _) = self.rdmc.rdmc_parse_arglist(self, line)
        except (InvalidCommandLineErrorOPTS, SystemExit):
            if ("-h" in line) or ("--help" in line):
                return ReturnCodes.SUCCESS
            else:
                raise InvalidCommandLineErrorOPTS("")
        # Check for admin privileges
        if "blobstore" in self.rdmc.app.current_client.base_url or "16.1.15." in self.rdmc.app.current_client.base_url :
            if os.name == "nt":
                if not ctypes.windll.shell32.IsUserAnAdmin() != 0:
                    self.rdmc.app.typepath.adminpriv = False
            elif not os.getuid() == 0:
                self.rdmc.app.typepath.adminpriv = False

            if self.rdmc.app.typepath.adminpriv is False :
                raise UserNotAdminError("")

        client = self.appaccountvalidation(options)
        if client:
            if "16.1.15.1" not in client.base_url:
                raise VnicExistsError(
                    "Appaccount command can only be executed " "from the host OS of a VNIC-enabled iLO7 based server.\n"
                )

        # To populate the correct host app information
        if "self_register" in options:
            if options.self_register:
                if (
                    ("hostappname" in options and options.hostappname)
                    or ("hostappid" in options and options.hostappid)
                    or ("salt" in options and options.salt)
                ):
                    raise InvalidCommandLineError(
                        "The parameters provided in the command are invalid."
                        " You may include either the --self tag "
                        "or the combination of --hostappid, --hostappname, and --salt tags,"
                        " but not both.\n"
                    )
            else:
                if options.command:
                    if options.command.lower() == "create":
                        if not (options.hostappname and options.hostappid and options.salt):
                            raise InvalidCommandLineError(
                                "Please provide all the required host application"
                                " information.\nTo proceed without entering host "
                                "application details, include "
                                "--self in the command.\n"
                            )
                    elif options.command.lower() == "delete":
                        if options.hostappid:
                            if options.user or options.password:
                                if not (options.user and options.password):
                                    raise InvalidCommandLineError("Please provide both username and password\n")
                            elif options.hostappname or options.salt:
                                if not (options.hostappname and options.salt):
                                    raise InvalidCommandLineError(
                                        "Please provide all the required host application"
                                        " information.\nTo proceed without entering host "
                                        "application details, include "
                                        "--self in the command.\n"
                                    )
                        else:
                            raise InvalidCommandLineError(
                                "--hostappid is a required parameter for the appaccount delete command.\n"
                            )
                    elif options.command.lower() in {"exists", "details"}:
                        if not options.hostappid:
                            raise InvalidCommandLineError(
                                "Please provide hostappid."
                                " To proceed without entering the ID,"
                                " include --self in the command.\n"
                            )
                else:
                    raise InvalidCommandLineError("The command you have entered is invalid.\n")

        if options.encode:
            if not options.user or not options.password:
                raise UsernamePasswordRequiredError("Username and Password are required when --enc is passed.\n")
            options.user = Encryption.decode_credentials(options.user).decode("utf-8")
            options.password = Encryption.decode_credentials(options.password).decode("utf-8")
        try:
            if options.command and options.command.lower() == "details":
                app_obj = AppAccount(
                    appname=None,
                    appid=None,
                    salt=None,
                    log_dir=self.rdmc.log_dir,
                )
            else:
                app_obj = AppAccount(
                    appname=options.hostappname if "hostappname" in options else None,
                    appid=options.hostappid if "hostappid" in options else None,
                    salt=options.salt if "salt" in options else None,
                    username=options.user,
                    password=options.password,
                    log_dir=self.rdmc.log_dir,
                )
        except Exception as excp:
            raise NoAppAccountError(
                "Error occured while locating application" " account. Please recheck the entered inputs.\n"
            )

        # Function to find out the iLO Generation
        self.get_ilover_beforelogin(app_obj)

        try:
            already_exists = self.rdmc.app.token_exists(app_obj)
        except Exception as excp:
            raise AppAccountExistsError("Error occurred while checking if application account exists.\n")

        if options.command:
            if options.command.lower() == "create":
                if not options.user or not options.password:  # Check if this is the correct variable
                    raise UsernamePasswordRequiredError("Please enter Username and Password.\n")

                try:
                    errorcode = self.rdmc.app.generate_save_token(app_obj)
                    if errorcode == 0:
                        self.rdmc.ui.printer("Application account has been generated and saved successfully.\n")
                        return ReturnCodes.SUCCESS
                except redfish.hpilo.vnichpilo.AppAccountExistsError:
                    self.rdmc.ui.printer("Application account already exists for the specified host application.\n")
                    return ReturnCodes.SUCCESS
                except redfish.hpilo.vnichpilo.SavinginTPMError:  # Check for specific error messages
                    raise SavinginTPMError(
                        "Failed to save the app account in TPM. "
                        "Please execute the appaccount delete command"
                        " with the same host application information and "
                        "attempt to create the app account again.\n"
                        "Alternatively, you can use the --no_app_account "
                        "option in the Login Command to log in using your iLO user account credentials.\n"
                    )
                except redfish.hpilo.vnichpilo.SavinginiLOError:
                    raise SavinginiLOError(
                        "Failed to save app account in iLO. "
                        "Please execute the appaccount delete command"
                        " with the same host application information and "
                        "attempt to create the app account again.\n"
                        "Alternatively, you can use the --no_app_account "
                        "option in the Login Command to log in using your iLO user account credentials.\n"
                    )
                except redfish.rest.v1.InvalidCredentialsError:
                    raise redfish.rest.v1.InvalidCredentialsError(0)
                except redfish.hpilo.vnichpilo.GenerateAndSaveAccountError:
                    raise GenerateAndSaveAccountError(
                        "Error occurred while generating and saving app account. "
                        "Please retry after sometime.\n"
                        "Alternatively, you can use the --no_app_account "
                        "option in the Login Command to log in using your iLO user account credentials.\n"
                    )

            elif options.command.lower() == "delete":
                if not already_exists:
                    raise NoAppAccountError("The application account you are trying to delete does not exist.\n")
                try:
                    errorcode = self.rdmc.app.delete_token(app_obj)
                    if errorcode == 0:
                        self.rdmc.ui.printer("Application account has been deleted successfully.\n")
                        return ReturnCodes.SUCCESS
                except redfish.rest.v1.InvalidCredentialsError:
                    raise redfish.rest.v1.InvalidCredentialsError(0)
                except Exception as excp:
                    raise RemoveAccountError("Error occurred while deleting application account.\n")

            # Command to check if apptoken exists
            elif options.command.lower() == "exists":
                if already_exists:
                    self.rdmc.ui.printer("Application account exists for this host application.\n")
                    return ReturnCodes.SUCCESS
                else:
                    self.rdmc.ui.printer("Application account does not exist for this hostapp.\n")
                    return ReturnCodes.ACCOUNT_DOES_NOT_EXIST_ERROR

            # Command to list appids and if they are present in iLO and TPM
            elif options.command.lower() == "details":
                if not already_exists:
                    raise NoAppAccountError(
                        "iLORest app account not found. Please create one using ilorest appaccount create to proceed.\n"
                    )
                try:
                    list_of_appids = self.rdmc.app.ListAppIds(app_obj)
                except Exception:
                    raise AppIdListError("Error occured while retrieving list of App Ids.\n")

                selfdict = list()
                if "self_register" in options and options.self_register:
                    for i in range(len(list_of_appids)):
                        if "00b5" in list_of_appids[i]["ApplicationID"]:
                            selfdict = [list_of_appids[i]]
                            break

                elif options.hostappid:
                    if options.hostappid == "all":
                        selfdict = list_of_appids
                        if (
                            "onlytoken" in options
                            and options.onlytoken
                            or "onlyaccount" in options
                            and options.onlyaccount
                        ):
                            for i in range(len(list_of_appids)):
                                if "onlytoken" in options and options.onlytoken:
                                    del selfdict[i]["ExistsIniLO"]
                                elif "onlyaccount" in options and options.onlyaccount:
                                    del selfdict[i]["ExistsInTPM"]
                    else:
                        if options.hostappid and len(options.hostappid) == 4:
                            try:
                                options.hostappid = self.rdmc.app.ExpandAppId(app_obj, options.hostappid)
                            except Exception:
                                raise NoAppAccountError(
                                    "There is no application account exists for the given hostappid."
                                    " Please recheck the entered inputs.\n"
                                )
                        for i in range(len(list_of_appids)):
                            if list_of_appids[i]["ApplicationID"] == options.hostappid:
                                selfdict = [list_of_appids[i]]
                                if "onlytoken" in options and options.onlytoken:
                                    del selfdict[0]["ExistsIniLO"]
                                elif "onlyaccount" in options and options.onlyaccount:
                                    del selfdict[0]["ExistsInTPM"]
                                break
                        if not selfdict:
                            raise AppAccountExistsError(
                                "There is no application account exists for the given hostappid."
                                " Please recheck the entered value.\n"
                            )
                if options.json:
                    tempdict = self.print_json_app_details(selfdict)
                    UI().print_out_json(tempdict)
                else:
                    self.print_app_details(selfdict)

                return ReturnCodes.SUCCESS

        else:
            raise InvalidCommandLineError("The command you have entered is invalid.\n")

    def appaccountvalidation(self, options):
        """appaccount validation function

        :param options: command line options
        :type options: list.
        """
        return self.rdmc.login_select_validation(self, options)

    def print_json_app_details(self, selfdict):
        for i in range(len(selfdict)):
            selfdict[i]["ApplicationID"] = "**" + selfdict[i]["ApplicationID"][-4:]
        return selfdict

    def print_app_details(self, printdict):
        final_output = ""
        for i in range(len(printdict)):
            final_output += "Application Name: "
            final_output += printdict[i]["ApplicationName"]
            final_output += "\n"
            final_output += "Application Id: **"
            final_output += printdict[i]["ApplicationID"][-4:]
            final_output += "\n"
            if "ExistsInTPM" in printdict[i]:
                final_output += "App account exists in TPM: "
                if printdict[i]["ExistsInTPM"]:
                    final_output += "yes\n"
                else:
                    final_output += "no\n"
            if "ExistsIniLO" in printdict[i]:
                final_output += "App account exists in iLO: "
                if printdict[i]["ExistsIniLO"]:
                    final_output += "yes\n"
                else:
                    final_output += "no\n"
            final_output += "\n"

        self.rdmc.ui.printer(final_output)

    def get_ilover_beforelogin(self, app_obj):
        try:
            ilo_ver, sec_state = self.rdmc.app.getilover_beforelogin(app_obj)
            if ilo_ver < 7:
                raise ChifDriverMissingOrNotFound()
        except ChifDriverMissingOrNotFound:
            raise IncompatibleiLOVersionError("This feature is only available for iLO 7 or higher.\n")
        except VnicNotEnabledError:
            raise VnicExistsError(
                "Unable to access iLO using virtual NIC. "
                "Please ensure virtual NIC is enabled in iLO. "
                "Ensure that virtual NIC in the host OS is "
                "configured properly. Refer to documentation for more information.\n"
            )
        except redfish.hpilo.vnichpilo.InvalidCommandLineError:
            raise InvalidCommandLineError(
                "There is no app account present for the given hostappid." " Please recheck the entered value.\n"
            )
        except Exception:
            raise GenBeforeLoginError(
                "An error occurred while retrieving the iLO generation. "
                "Please ensure that the virtual NIC is enabled for iLO7 based "
                "servers, or that the CHIF driver is installed for iLO5 and iLO6 "
                "based servers.\n "
                "Note: appaccount command can only be executed from the host OS of a VNIC-enabled iLO7 server.\n"
            )

    def definearguments(self, customparser):
        if not customparser:
            return

        self.cmdbase.add_login_arguments_group(customparser)
        subcommand_parser = customparser.add_subparsers(dest="command")

        # Create apptoken command arguments
        help_text = "To generate and save Application account"
        create_parser = subcommand_parser.add_parser(
            "create",
            help=help_text,
            description="appaccount create --username temp_user --password "
            "pasxx --hostappname xxx --hostappid xxx --salt xxx",
            formatter_class=RawDescriptionHelpFormatter,
        )

        create_parser.add_argument("--hostappid", dest="hostappid", help="Parameter to specify hostappid", default=None)
        create_parser.add_argument(
            "--hostappname", dest="hostappname", help="Parameter to specify hostappname", default=None
        )
        create_parser.add_argument(
            "--salt", dest="salt", help="Parameter to specify application owned salt", default=None
        )
        help_text = "Self tag for customers with no access to host information."
        create_parser.add_argument("--self", dest="self_register", help=help_text, action="store_true", default=False)
        self.cmdbase.add_login_arguments_group(create_parser)

        # Delete apptoken command arguments
        help_text = "To delete Application account"
        delete_parser = subcommand_parser.add_parser(
            "delete",
            help=help_text,
            description="appaccount delete --hostappname xxx -u user123 -p passxx",
            formatter_class=RawDescriptionHelpFormatter,
        )
        delete_parser.add_argument("--hostappid", dest="hostappid", help="Parameter to specify hostappid", default=None)
        delete_parser.add_argument(
            "--hostappname", dest="hostappname", help="Parameter to specify hostappname", default=None
        )
        delete_parser.add_argument(
            "--salt", dest="salt", help="Parameter to specify application owned salt", default=None
        )
        help_text = "Self tag for customers with no access to host information."
        delete_parser.add_argument("--self", dest="self_register", help=help_text, action="store_true", default=False)
        self.cmdbase.add_login_arguments_group(delete_parser)

        # token exists command arguments
        help_text = "To check if Application account exists"
        exists_parser = subcommand_parser.add_parser(
            "exists",
            help=help_text,
            description="appaccount exists --hostappid xxx",
            formatter_class=RawDescriptionHelpFormatter,
        )
        exists_parser.add_argument("--hostappid", dest="hostappid", help="Parameter to specify hostappid", default=None)

        help_text = "Self tag for customers with no access to host information."
        exists_parser.add_argument("--self", dest="self_register", help=help_text, action="store_true", default=False)
        self.cmdbase.add_login_arguments_group(exists_parser)

        # Details command arguments
        help_text = "To list details of app accounts present in TPM and iLO."
        details_parser = subcommand_parser.add_parser(
            "details",
            help=help_text,
            description="appaccount details --hostappid xxx",
            formatter_class=RawDescriptionHelpFormatter,
        )
        details_parser.add_argument(
            "--hostappid", dest="hostappid", help="Parameter to specify hostappid", default=None
        )
        details_parser.add_argument(
            "--only_token",
            dest="onlytoken",
            help="Parameter provides details of app account in TPM",
            action="store_true",
            default=False,
        )
        details_parser.add_argument(
            "--only_account",
            dest="onlyaccount",
            help="Parameter provides details of app account in iLO.",
            action="store_true",
            default=False,
        )
        help_text = "Self tag for customers with no access to host information."
        details_parser.add_argument("--self", dest="self_register", help=help_text, action="store_true", default=False)
        details_parser.add_argument(
            "-j",
            "--json",
            dest="json",
            action="store_true",
            help="Optionally include this flag if you wish to change the"
            " displayed output to JSON format. Preserving the JSON data"
            " structure makes the information easier to parse.",
            default=False,
        )
        self.cmdbase.add_login_arguments_group(details_parser)
