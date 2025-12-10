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
        LOGGER,
        GenerateAndSaveAccountError,
        AppAccountExistsError,
        ReactivateAppAccountTokenError,
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
        LOGGER,
        GenerateAndSaveAccountError,
        AppAccountExistsError,
        ReactivateAppAccountTokenError,
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
        if "blobstore" in self.rdmc.app.current_client.base_url or "16.1.15." in self.rdmc.app.current_client.base_url:
            if os.name == "nt":
                if not ctypes.windll.shell32.IsUserAnAdmin() != 0:
                    self.rdmc.app.typepath.adminpriv = False
            elif not os.getuid() == 0:
                self.rdmc.app.typepath.adminpriv = False

            if self.rdmc.app.typepath.adminpriv is False:
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
                        # Validate hostappid is provided
                        if not options.hostappid:
                            raise InvalidCommandLineError(
                                "--hostappid is a required parameter for the appaccount delete command.\n"
                            )

                        # Check if hostappid is 00b5 (self-registered) - treat as --self
                        is_self_registered_id = options.hostappid and "00b5" in options.hostappid.lower()

                        # For self-registered accounts (--self or 00b5), no credentials required
                        if not options.self_register and not is_self_registered_id:
                            # For delete, require either credentials OR host app info (but not both are mandatory)
                            has_credentials = all([options.user, options.password])
                            has_app_info = all([options.hostappname, options.salt])

                            # If hostappid is provided, user must provide EITHER credentials OR app info
                            if not has_credentials and not has_app_info:
                                raise InvalidCommandLineError(
                                    "For deleting application accounts, please provide either:\n"
                                    "  1. Username and password (using -u and -p flags), OR\n"
                                    "  2. Host application information (using --hostappname and --salt flags)\n"
                                )

                            # If partial credentials or partial app info, validate completeness
                            if (options.user or options.password) and not has_credentials:
                                raise InvalidCommandLineError("Please provide both username and password\n")
                            if (options.hostappname or options.salt) and not has_app_info:
                                raise InvalidCommandLineError(
                                    "Please provide all the required host application"
                                    " information.\nTo proceed without entering host "
                                    "application details, include "
                                    "--self in the command.\n"
                                )
                    elif options.command.lower() == "exists":
                        if not options.hostappid:
                            raise InvalidCommandLineError(
                                "Please provide hostappid."
                                " To proceed without entering the ID,"
                                " include --self in the command.\n"
                            )
                    elif options.command.lower() == "details":
                        if not options.hostappid and not options.self_register:
                            raise InvalidCommandLineError(
                                "Please provide hostappid using --hostappid <id> or --hostappid all."
                                " To view self-registered account, use --self.\n"
                            )
                    elif options.command.lower() == "reactivate":
                        if not (options.user and options.password):
                            LOGGER.error("Please provide both username and password.\n")
                            raise InvalidCommandLineError("Please provide both username and password.\n")

                        if not (options.hostappname and options.hostappid and options.salt):
                            LOGGER.error(
                                "Please provide all the required host application"
                                " information.\nTo proceed without entering host "
                                "application details, include "
                                "--self in the command.\n"
                            )
                            raise InvalidCommandLineError(
                                "Please provide all the required host application"
                                " information.\nTo proceed without entering host "
                                "application details, include "
                                "--self in the command.\n"
                            )
                else:
                    raise InvalidCommandLineError("The command you have entered is invalid.\n")

        try:
            # For details command, no credentials needed (read-only operation)
            # Only delete command for non-00b5 accounts needs credentials
            if options.command and options.command.lower() == "details":
                # Handle hostappid="all" - don't pass to AppAccount as it's not a real app ID
                hostappid_value = getattr(options, "hostappid", None) if "hostappid" in options else None
                if hostappid_value and hostappid_value.lower() == "all":
                    hostappid_value = None

                app_obj = AppAccount(
                    appname=getattr(options, "hostappname", None) if "hostappname" in options else "self_register",
                    appid="self_register",
                    salt=getattr(options, "salt", None) if "salt" in options else "self_register",
                    username=None,
                    password=None,
                    log_dir=self.rdmc.log_dir,
                )
            else:
                # Handle hostappid="all" for non-details commands too (though it shouldn't be used)
                hostappid_value = options.hostappid if "hostappid" in options else None
                if hostappid_value and hostappid_value.lower() == "all":
                    hostappid_value = None

                app_obj = AppAccount(
                    appname=options.hostappname if "hostappname" in options else "self_register",
                    appid=options.hostappid if "hostappid" in options else "self_register",
                    salt=options.salt if "salt" in options else "self_register",
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

        # Check if app account exists - skip for details command
        already_exists = False
        command_lower = options.command.lower() if options.command else ""
        hostappid_option = getattr(options, "hostappid", None)
        skip_token_check = (
            command_lower == "details"
        )

        if not skip_token_check:
            try:
                # For short app IDs (4 chars), check using ListAppIds
                if (
                    command_lower in ["delete", "exists"]
                    and getattr(options, "hostappid", None)
                    and len(options.hostappid) == 4
                ):
                    try:
                        list_of_appids = self.rdmc.app.ListAppIds(app_obj)
                        for app_id in list_of_appids:
                            if app_id["ApplicationID"][-4:].lower() == options.hostappid.lower():
                                already_exists = True
                                break
                    except Exception:
                        already_exists = self.rdmc.app.token_exists(app_obj)
                else:
                    already_exists = self.rdmc.app.token_exists(app_obj)
            except Exception as excp:
                if command_lower != "details":
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
                is_self = getattr(options, "self_register", False)
                has_credentials = options.user and options.password
                has_app_info = options.hostappname and options.salt

                # Try to delete from both TPM and iLO
                deleted_from_tpm = False
                deleted_from_ilo = False
                app_id_to_delete = None

                # Step 1: Try to delete from TPM (may not exist after TPM reset)
                try:
                    errorcode = self.rdmc.app.delete_token(app_obj)
                    if errorcode == 0:
                        deleted_from_tpm = True
                        LOGGER.debug("Successfully deleted app account from TPM")
                except Exception as tpm_error:
                    # TPM deletion failed (token may not exist in TPM), continue to try iLO deletion
                    LOGGER.debug("TPM deletion failed: %s", str(tpm_error))
                    pass

                # Step 2: Try to delete from iLO - requires credentials or authenticated session
                if has_credentials or is_self or has_app_info:
                    try:
                        # Get the app ID to delete
                        list_of_appids = self.rdmc.app.ListAppIds(app_obj)

                        if is_self:
                            for app_account in list_of_appids:
                                if "00b5" in app_account.get("ApplicationID", "").lower():
                                    app_id_to_delete = app_account["ApplicationID"]
                                    break
                        elif options.hostappid:
                            for app_account in list_of_appids:
                                full_id = app_account["ApplicationID"]
                                # Match full ID or last 4 chars (short ID)
                                if full_id == options.hostappid or (
                                    len(options.hostappid) == 4 and full_id[-4:].lower() == options.hostappid.lower()
                                ):
                                    app_id_to_delete = full_id
                                    break

                        # Delete from iLO via REST API
                        if app_id_to_delete:
                            delete_url = (
                                f"/redfish/v1/AccountService/Accounts/{app_id_to_delete}"
                            )
                            try:
                                self.rdmc.app.delete_handler(delete_url)
                                deleted_from_ilo = True
                                LOGGER.debug("Successfully deleted app account from iLO")
                            except Exception as ilo_error:
                                LOGGER.debug("iLO deletion failed: %s", str(ilo_error))
                    except Exception as e:
                        LOGGER.debug("Error during iLO deletion: %s", str(e))

                # Report success if deleted from either TPM or iLO
                if deleted_from_tpm or deleted_from_ilo:
                    self.rdmc.ui.printer("Application account has been deleted successfully.\n")
                    return ReturnCodes.SUCCESS
                else:
                    raise NoAppAccountError(
                        "The application account you are trying to delete does not exist.\n"
                    )

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
                try:
                    list_of_appids = self.rdmc.app.ListAppIds(app_obj)
                except Exception:
                    raise AppIdListError("Error occured while retrieving list of App Ids.\n")

                selfdict = list()
                if "self_register" in options and options.self_register:
                    for app_id in list_of_appids:
                        app_id_value = app_id["ApplicationID"]
                        # Check only for 00b5 identifier for true self-registered iLORest accounts
                        # (00b5 is the reserved ID prefix for iLORest self-registration)
                        if "00b5" in app_id_value.lower():
                            selfdict = [app_id]
                            break

                    # If no self-registered app account found, inform user
                    if not selfdict:
                        self.rdmc.ui.printer("No self-registered iLORest app account found.\n")
                        self.rdmc.ui.printer("Use 'appaccount details --hostappid all' to see all app accounts.\n")
                        return ReturnCodes.SUCCESS

                elif options.hostappid:
                    if options.hostappid.lower() == "all":
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
                        # Expand short app ID (4 chars) to full ID like master code does
                        target_appid = options.hostappid
                        if len(options.hostappid) == 4:
                            try:
                                target_appid = self.rdmc.app.ExpandAppId(app_obj, options.hostappid)
                            except Exception:
                                # If expansion fails, try matching with last 4 chars
                                pass

                        # Handle both full and short (4 char) app IDs
                        for i in range(len(list_of_appids)):
                            full_id = list_of_appids[i]["ApplicationID"]
                            # Match full ID or last 4 chars for short ID
                            if full_id == target_appid or (
                                len(options.hostappid) == 4
                                and full_id[-4:].lower() == options.hostappid.lower()
                            ):
                                selfdict = [list_of_appids[i]]
                                if "onlytoken" in options and options.onlytoken:
                                    del selfdict[0]["ExistsIniLO"]
                                elif "onlyaccount" in options and options.onlyaccount:
                                    del selfdict[0]["ExistsInTPM"]
                                break
                        if not selfdict:
                            raise AppAccountExistsError(
                                "There is no application account exists for the given hostappid. "
                                "Please recheck the entered value.\n"
                            )
                else:
                    # No --hostappid provided - list all app accounts (master behavior)
                    selfdict = list_of_appids
                    if (
                        "onlytoken" in options and options.onlytoken
                        or "onlyaccount" in options and options.onlyaccount
                    ):
                        for i in range(len(list_of_appids)):
                            if "onlytoken" in options and options.onlytoken:
                                del selfdict[i]["ExistsIniLO"]
                            elif "onlyaccount" in options and options.onlyaccount:
                                del selfdict[i]["ExistsInTPM"]

                if options.json:
                    tempdict = self.print_json_app_details(selfdict)
                    UI().print_out_json(tempdict)
                else:
                    self.print_app_details(selfdict)

                return ReturnCodes.SUCCESS
            elif options.command.lower() == "reactivate":
                if not already_exists:
                    LOGGER.error("The application account you are trying to reactivate does not exist.")
                    raise NoAppAccountError("The application account you are trying to reactivate does not exist.\n")
                try:
                    return_code = self.rdmc.app.reactivate_token(app_obj)
                    if return_code == 0:
                        self.rdmc.ui.printer("Application account has been reactivated successfully.\n")
                        return ReturnCodes.SUCCESS
                except redfish.rest.v1.InvalidCredentialsError:
                    LOGGER.error("Please enter valid credentials.")
                    raise redfish.rest.v1.InvalidCredentialsError(0)
                except Exception as excp:
                    LOGGER.error("Error occurred while reactivating application account.")
                    raise ReactivateAppAccountTokenError("Error occurred while reactivating application account.\n")
            else:
                raise InvalidCommandLineError("The command you have entered is invalid.\n")

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

        # Reactivate apptoken command arguments
        help_text = "To reactivate Application account"
        reactivate_parser = subcommand_parser.add_parser(
            "reactivate",
            help=help_text,
            description="appaccount reactivate --username temp_user --password pasxx",
            formatter_class=RawDescriptionHelpFormatter,
        )

        reactivate_parser.add_argument(
            "--hostappid", dest="hostappid", help="Parameter to specify hostappid", default=None
        )
        reactivate_parser.add_argument(
            "--hostappname", dest="hostappname", help="Parameter to specify hostappname", default=None
        )
        reactivate_parser.add_argument(
            "--salt", dest="salt", help="Parameter to specify application owned salt", default=None
        )
        help_text = "Self tag for customers with no access to host information."
        reactivate_parser.add_argument(
            "--self", dest="self_register", help=help_text, action="store_true", default=False
        )
        self.cmdbase.add_login_arguments_group(reactivate_parser)
