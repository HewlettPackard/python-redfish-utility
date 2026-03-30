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
"""AppAccount command for rdmc"""

from argparse import RawDescriptionHelpFormatter
from redfish.hpilo.vnichpilo import AppAccount
import redfish.hpilo.vnichpilo
from redfish.rest.connections import ChifDriverMissingOrNotFound, VnicNotEnabledError
import redfish
import os
import ctypes
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
        UI,
        Encryption,
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
        UI,
        Encryption,
    )


# The VNIC virtual NIC IP used for all direct iLO REST calls from the host OS
_ILO_VNIC_BASE_URL = "https://16.1.15.1"


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

    def _is_root_user(self):
        """Check if the current OS user is root (Unix/Linux) or Administrator (Windows)."""
        try:
            if os.name == "posix":  # Unix/Linux-based systems
                return os.geteuid() == 0
            elif os.name == "nt":  # Windows-based systems
                return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception as exc:
            LOGGER.debug("Failed to determine user privileges: %s", str(exc))
            return False

    def run(self, line, help_disp=False):
        if help_disp:
            line.append("-h")
            try:
                _, _ = self.rdmc.rdmc_parse_arglist(self, line)
            except:
                return ReturnCodes.SUCCESS
            return ReturnCodes.SUCCESS
        # Restrict non-root/Administrator users
        if not self._is_root_user():
            raise UserNotAdminError(
                "You should be an administrator or a root privileged user to run appaccount command.\n"
            )
        try:
            options, _ = self.rdmc.rdmc_parse_arglist(self, line)
        except (InvalidCommandLineErrorOPTS, SystemExit):
            if ("-h" in line) or ("--help" in line):
                return ReturnCodes.SUCCESS
            else:
                raise InvalidCommandLineErrorOPTS("")

        if getattr(options, "encode", False):
            if options.user:
                options.user = self._decode_credential(options.user)
            if options.password:
                options.password = self._decode_credential(options.password)

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

                        # For self-registered accounts (--self or 00b5), no credentials required.
                        # For all other accounts (e.g. SUM, SUT, AMS), iLO Administrator
                        # credentials are mandatory to prevent unauthorised deletion.
                        if not options.self_register and not is_self_registered_id:
                            if not (options.user and options.password):
                                raise InvalidCommandLineError(
                                    "iLO Administrator credentials are required to delete another "
                                    "application's account.\nPlease provide username and password "
                                    "using -u and -p flags.\n"
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
                            raise UsernamePasswordRequiredError("Please enter Username and Password.\n")

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
                app_obj = AppAccount(
                    appname=getattr(options, "hostappname", None) if "hostappname" in options else "self_register",
                    appid="self_register",
                    salt=getattr(options, "salt", None) if "salt" in options else "self_register",
                    username=None,
                    password=None,
                    log_dir=self.rdmc.log_dir,
                )
            else:
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

        if options.command:
            if options.command.lower() == "create":
                # credentials are mandatory for all create paths (--self and --hostappid/--hostappname/--salt)
                if not options.user or not options.password:
                    raise UsernamePasswordRequiredError("Please enter Username and Password.\n")

                # Clean up orphaned iLO account (exists in iLO but not in TPM after TPM clear)
                exists_in_tpm = self._check_exists_in_tpm(app_obj)
                exists_in_ilo, ilo_account = self._check_exists_in_ilo(options)
                if exists_in_ilo and not exists_in_tpm:
                    self._cleanup_orphaned_ilo_account(ilo_account, options.user, options.password)

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
                # True when the target is the caller's own iLORest self-registered account
                is_self_registered_id = options.hostappid and "00b5" in options.hostappid.lower()
                is_own_account = is_self or is_self_registered_id

                # Try to delete from both TPM and iLO
                deleted_from_tpm = False
                deleted_from_ilo = False

                # Look up the iLO account first (handles 4-char ID matching)
                _, ilo_account = self._check_exists_in_ilo(options)

                # Expand short app ID (4 chars) to full ID for TPM deletion
                if options.hostappid and len(options.hostappid) == 4:
                    try:
                        expanded_appid = self.rdmc.app.ExpandAppId(app_obj, options.hostappid)
                        app_obj = AppAccount(
                            appname=options.hostappname if "hostappname" in options else "self_register",
                            appid=expanded_appid,
                            salt=options.salt if "salt" in options else "self_register",
                            username=options.user,
                            password=options.password,
                            log_dir=self.rdmc.log_dir,
                        )
                    except Exception:
                        # If expansion fails, TPM deletion will be skipped;
                        # iLO deletion can still proceed via _check_exists_in_ilo match
                        LOGGER.debug("Failed to expand short app ID for TPM deletion")

                # Step 1: Delete from TPM.
                # Only the owner (self-registered) or an operator with iLO Administrator
                # credentials may delete an app account from TPM.
                if is_own_account or has_credentials:
                    try:
                        errorcode = self.rdmc.app.delete_token(app_obj)
                        if errorcode == 0:
                            deleted_from_tpm = True
                            LOGGER.debug("Successfully deleted app account from TPM")
                    except Exception as tpm_error:
                        # TPM deletion failed (token may not exist in TPM), continue to try iLO deletion
                        LOGGER.debug("TPM deletion failed: %s", str(tpm_error))

                # Step 2: Delete from iLO.
                # Same rule: credentials are required to delete another application's account.
                if is_own_account or has_credentials:
                    try:
                        self._cleanup_orphaned_ilo_account(ilo_account, options.user, options.password)
                        deleted_from_ilo = True
                        LOGGER.debug("Successfully deleted app account from iLO")
                    except Exception as ilo_error:
                        LOGGER.debug("iLO deletion failed: %s", str(ilo_error))

                # Report success if deleted from either TPM or iLO
                if deleted_from_tpm or deleted_from_ilo:
                    self.rdmc.ui.printer("Application account has been deleted successfully.\n")
                    return ReturnCodes.SUCCESS
                else:
                    raise NoAppAccountError("The application account you are trying to delete does not exist.\n")

            # Command to check if apptoken exists
            elif options.command.lower() == "exists":
                # Expand short app ID (4 chars) to full ID for TPM lookup
                if options.hostappid and len(options.hostappid) == 4:
                    try:
                        expanded_appid = self.rdmc.app.ExpandAppId(app_obj, options.hostappid)
                        app_obj = AppAccount(
                            appname=options.hostappname if "hostappname" in options else "self_register",
                            appid=expanded_appid,
                            salt=options.salt if "salt" in options else "self_register",
                            username=options.user,
                            password=options.password,
                            log_dir=self.rdmc.log_dir,
                        )
                    except Exception:
                        # If expansion fails, continue with original app_obj
                        pass
                exists_in_tpm = self._check_exists_in_tpm(app_obj)
                exists_in_ilo, _ = self._check_exists_in_ilo(options)
                if exists_in_tpm or exists_in_ilo:
                    self.rdmc.ui.printer("Application account exists for this host application.\n")
                    return ReturnCodes.SUCCESS
                else:
                    self.rdmc.ui.printer("Application account does not exist for this hostapp.\n")
                    return ReturnCodes.ACCOUNT_DOES_NOT_EXIST_ERROR

            # Command to list appids and if they are present in iLO and TPM
            elif options.command.lower() == "details":
                try:
                    list_of_appids = self.rdmc.app.ListAppIds(app_obj)
                except redfish.hpilo.vnichpilo.InactiveAppAccountTokenError:
                    self.rdmc.ui.printer("AppAccount is inactive. Please run the appaccount reactivate command.\n")
                    return ReturnCodes.INACTIVE_APP_ACCOUNT_TOKEN
                except Exception:
                    LOGGER.debug("ListAppIds failed (TPM may have been cleared)")
                    list_of_appids = []

                # Merge accounts found only in iLO (orphaned after TPM clear)
                ilo_accounts = self._get_app_accounts_from_ilo(
                    getattr(options, "user", None),
                    getattr(options, "password", None),
                )
                existing_ids = {a.get("ApplicationID", "")[-4:].lower() for a in list_of_appids}
                for ilo_acc in ilo_accounts:
                    host_app_id = ilo_acc.get("HostAppId", "")

                    if host_app_id[-4:].lower() not in existing_ids:
                        list_of_appids.append(
                            {
                                "ApplicationID": host_app_id,
                                "ApplicationName": ilo_acc.get("HostAppName", ""),
                                "ExistsInTPM": False,
                                "ExistsIniLO": True,
                            }
                        )

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
                                temp_app_obj = AppAccount(
                                    appname=(
                                        getattr(options, "hostappname", None)
                                        if "hostappname" in options
                                        else "self_register"
                                    ),
                                    appid=options.hostappid,
                                    salt=getattr(options, "salt", None) if "salt" in options else "self_register",
                                    username=None,
                                    password=None,
                                    log_dir=self.rdmc.log_dir,
                                )
                                target_appid = self.rdmc.app.ExpandAppId(temp_app_obj, options.hostappid)
                            except Exception:
                                # If expansion fails, try matching with last 4 chars
                                pass

                        # Handle both full and short (4 char) app IDs
                        for i in range(len(list_of_appids)):
                            full_id = list_of_appids[i]["ApplicationID"]
                            # Match full ID or last 4 chars for short ID
                            if full_id == target_appid or (
                                len(options.hostappid) == 4 and full_id[-4:].lower() == options.hostappid.lower()
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
                    if "onlytoken" in options and options.onlytoken or "onlyaccount" in options and options.onlyaccount:
                        for i in range(len(list_of_appids)):
                            if "onlytoken" in options and options.onlytoken:
                                del selfdict[i]["ExistsIniLO"]
                            elif "onlyaccount" in options and options.onlyaccount:
                                del selfdict[i]["ExistsInTPM"]

                if not selfdict:
                    self.rdmc.ui.printer("There are no application accounts.\n")
                    return ReturnCodes.SUCCESS

                if options.json:
                    tempdict = self.print_json_app_details(selfdict)
                    UI().print_out_json(tempdict)
                else:
                    self.print_app_details(selfdict)

                return ReturnCodes.SUCCESS
            elif options.command.lower() == "reactivate":
                if not options.user or not options.password:
                    raise UsernamePasswordRequiredError("Please enter Username and Password.\n")
                exists_in_tpm = self._check_exists_in_tpm(app_obj)
                exists_in_ilo, ilo_account = self._check_exists_in_ilo(options)
                if not exists_in_tpm and exists_in_ilo:
                    # Orphaned account found in iLO (TPM was cleared) – clean it up and recreate
                    self._cleanup_orphaned_ilo_account(ilo_account, options.user, options.password)
                    errorcode = self.rdmc.app.generate_save_token(app_obj)
                    if errorcode == 0:
                        self.rdmc.ui.printer("Application account has been recreated successfully.\n")
                        return ReturnCodes.SUCCESS
                if not exists_in_tpm:
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
                    raise ReactivateAppAccountTokenError()
            else:
                raise InvalidCommandLineError("The command you have entered is invalid.\n")

        else:
            raise InvalidCommandLineError("The command you have entered is invalid.\n")

    def _check_exists_in_tpm(self, app_obj):
        """Return True if the app account token exists in TPM (including inactive tokens)."""
        try:
            return self.rdmc.app.token_exists(app_obj)
        except redfish.hpilo.vnichpilo.InactiveAppAccountTokenError:
            LOGGER.debug("App token exists in TPM but is inactive")
            return True
        except Exception as exc:
            LOGGER.debug("TPM token check failed (TPM may have been cleared): %s", str(exc))
            return False

    def _get_app_accounts_from_ilo(self, username=None, password=None):
        """Query iLO REST API and return a list of app account dicts.

        Each dict contains at least: Id, HostAppId, HostAppName.
        When no active REST session exists, creates a temporary one using the
        supplied credentials (required for appaccount commands that run without
        a prior login session).  Returns an empty list when no session can be
        established.
        """
        accounts = []
        seen_ids = set()
        session_token = None
        session_location = None
        try:
            try:
                has_client = self.rdmc.app.current_client is not None
            except Exception:
                has_client = False

            if not has_client:
                # appaccount runs via CHIF/VNIC without a prior ilorest login,
                # so current_client is always None.  Create a temporary session
                # using the iLO credentials passed on the command line.
                if not (username and password):
                    LOGGER.debug("No client session and no credentials – cannot query iLO app accounts via REST")
                    return accounts
                session_token, session_location = self._create_ilo_session(username, password)
                if not session_token:
                    LOGGER.debug("Could not create temporary iLO session – cannot query app accounts via REST")
                    return accounts

            accounts = self._fetch_app_accounts(session_token, seen_ids)
        except Exception as exc:
            LOGGER.debug("Failed to retrieve app accounts from iLO REST API: %s", str(exc))
        finally:
            if session_token and session_location:
                self._delete_ilo_session(session_token, session_location)
        return accounts

    def _create_ilo_session(self, username, password):
        """POST to iLO SessionService with credentials and return (token, location)."""
        import requests

        try:
            session_url = f"{_ILO_VNIC_BASE_URL}/redfish/v1/SessionService/Sessions/"
            session_data = {"UserName": username, "Password": password}
            response = requests.post(session_url, json=session_data, verify=False, timeout=10)
            if response.status_code in (200, 201):
                token = response.headers.get("X-Auth-Token")
                location = response.headers.get("Location")
                LOGGER.debug("Temporary iLO session created for app account REST queries")
                return token, location
            LOGGER.debug("Failed to create temporary iLO session: HTTP %s", response.status_code)
        except Exception as exc:
            LOGGER.debug("Exception creating temporary iLO session: %s", str(exc))
        return None, None

    def _delete_ilo_session(self, session_token, session_location):
        """DELETE the temporary iLO session after use."""
        import requests

        try:
            if session_location:
                # session_location may be a full URL or a path
                if not session_location.startswith("https://"):
                    session_location = _ILO_VNIC_BASE_URL + session_location
                requests.delete(
                    session_location,
                    headers={"X-Auth-Token": session_token},
                    verify=False,
                    timeout=10,
                )
                LOGGER.debug("Temporary iLO session deleted")
        except Exception as exc:
            LOGGER.debug("Failed to delete temporary iLO session: %s", str(exc))

    def _fetch_app_accounts(self, session_token, seen_ids):
        """Retrieve members from /AppAccounts/ using either the active client or a bare token."""
        import requests

        accounts = []
        headers = {"X-Auth-Token": session_token} if session_token else {}
        base = _ILO_VNIC_BASE_URL

        def _get(url):
            if session_token:
                r = requests.get(url, headers=headers, verify=False, timeout=10)
                r.raise_for_status()
                return r.json()
            else:
                resp = self.rdmc.app.get_handler(url, silent=True)
                if resp and resp.status == 200:
                    return resp.dict
                return None

        url = (
            base + "/redfish/v1/AccountService/Oem/Hpe/AppAccounts/"
            if session_token
            else "/redfish/v1/AccountService/Oem/Hpe/AppAccounts/"
        )
        data = _get(url)
        if not data:
            return accounts

        for member in data.get("Members", []):
            uri = member.get("@odata.id", "")
            if not uri:
                continue
            try:
                acc_url = (base + uri) if session_token else uri
                acc = _get(acc_url)
                if not acc:
                    continue
                host_app_id = acc.get("HostAppId", "")
                if host_app_id and host_app_id not in seen_ids:
                    seen_ids.add(host_app_id)
                    accounts.append(
                        {
                            "Id": acc.get("Id", ""),
                            "HostAppId": host_app_id,
                            "HostAppName": acc.get("HostAppName", ""),
                        }
                    )
            except Exception:
                pass
        return accounts

    def _check_exists_in_ilo(self, options):
        """Return (True, account_dict) if the target account exists in iLO, else (False, None)."""
        is_self = getattr(options, "self_register", False)
        target_id = getattr(options, "hostappid", None)
        username = getattr(options, "user", None)
        password = getattr(options, "password", None)

        for account in self._get_app_accounts_from_ilo(username, password):
            host_app_id = account.get("HostAppId", "")
            host_app_name = account.get("HostAppName", "")

            if is_self:
                if "00b5" in host_app_id.lower() or host_app_name.lower() == "ilorest":
                    return True, account
            elif target_id:
                if host_app_id.lower() == target_id.lower():
                    return True, account
                if len(target_id) == 4 and len(host_app_id) >= 4 and host_app_id[-4:].lower() == target_id.lower():
                    return True, account

        return False, None

    def _cleanup_orphaned_ilo_account(self, ilo_account, username=None, password=None):
        """Delete an iLO app account that has no matching TPM token (orphaned after TPM clear)."""
        if not (ilo_account and ilo_account.get("Id")):
            return
        import requests

        delete_url_path = f"/redfish/v1/AccountService/Oem/Hpe/AppAccounts/{ilo_account['Id']}"
        try:
            has_client = self.rdmc.app.current_client is not None
        except Exception:
            has_client = False

        try:
            if has_client:
                self.rdmc.app.delete_handler(delete_url_path)
            else:
                # No active session – create a temporary one to perform the delete
                if not (username and password):
                    LOGGER.debug("No client session and no credentials – cannot remove orphaned iLO account")
                    return
                session_token, session_location = self._create_ilo_session(username, password)
                if not session_token:
                    LOGGER.debug("Could not create temporary iLO session – cannot remove orphaned account")
                    return
                try:
                    full_url = _ILO_VNIC_BASE_URL + delete_url_path
                    response = requests.delete(
                        full_url,
                        headers={"X-Auth-Token": session_token},
                        verify=False,
                        timeout=10,
                    )
                    response.raise_for_status()
                finally:
                    self._delete_ilo_session(session_token, session_location)
            LOGGER.debug("Cleaned up orphaned iLO app account: %s", ilo_account["Id"])
        except Exception as exc:
            LOGGER.debug("Failed to clean up orphaned iLO account: %s", str(exc))
            raise SavinginiLOError(
                "Found an orphaned app account in iLO but could not remove it. "
                "Please delete it manually via the iLO GUI or "
                "'appaccount delete' with credentials, then retry.\n"
            )

    def _decode_credential(self, credential):
        """Decode an encoded credential"""
        try:
            decoded = Encryption.decode_credentials(credential)
            if isinstance(decoded, bytes):
                decoded = decoded.decode("utf-8")
            return decoded
        except Exception as exc:
            LOGGER.debug("Failed to decode credential: %s", str(exc))
            # Return original if decoding fails
            return credential

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
