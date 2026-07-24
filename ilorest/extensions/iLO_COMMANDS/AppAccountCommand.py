###
# Copyright 2016-2026 Hewlett Packard Enterprise, Inc. All rights reserved.
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

import ctypes
import os
from argparse import RawDescriptionHelpFormatter

import redfish
import redfish.hpilo.vnichpilo
from redfish.hpilo.vnichpilo import AppAccount
from redfish.rest.connections import ChifDriverMissingOrNotFound, VnicNotEnabledError
from redfish.ris.rmc_helper import UserNotAdminError

try:
    from rdmc_helper import (
        LOGGER,
        UI,
        AppAccountExistsError,
        Encryption,
        GenBeforeLoginError,
        GenerateAndSaveAccountError,
        IncompatibleiLOVersionError,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        NoAppAccountError,
        ReactivateAppAccountTokenError,
        ReturnCodes,
        SavinginiLOError,
        SavinginTPMError,
        UsernamePasswordRequiredError,
        VnicExistsError,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        LOGGER,
        UI,
        AppAccountExistsError,
        Encryption,
        GenBeforeLoginError,
        GenerateAndSaveAccountError,
        IncompatibleiLOVersionError,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        NoAppAccountError,
        ReactivateAppAccountTokenError,
        ReturnCodes,
        SavinginiLOError,
        SavinginTPMError,
        UsernamePasswordRequiredError,
        VnicExistsError,
    )


# The VNIC virtual NIC IP used for all direct iLO REST calls from the host OS
_ILO_VNIC_BASE_URL = "https://16.1.15.1"

# Advisory printed when application accounts cannot be enumerated in-band.
#
# Enumeration goes through the library's ``ListAppIds`` -> DLL ``CompareAppIds``,
# which lists accounts over the in-band VNIC channel using the iLORest *self*
# (00b5) application account context. ``CompareAppIds`` takes only appid/appname/
# salt — it never uses iLO username/password — so supplying ``-u``/``-p`` does NOT
# enable enumeration. When the self application account is absent the firmware
# reports "no app accounts" even though other accounts (for example one created by
# Smart Update Manager) still exist in TPM/iLO. Per-account TPM checks
# (``AppIdExistsinTPM``) still work without the self account, which is why
# ``exists --hostappid <id>`` can report ``TPM: yes`` while enumeration shows
# nothing. Surface this so an empty result is not mistaken for "none exist".
_SELF_ACCOUNT_ENUM_ADVISORY = (
    "Note: Application accounts are enumerated in-band, which requires the iLORest "
    "self application account to be present on this server (iLO credentials cannot "
    "substitute for it). If application accounts exist but are not listed, create "
    "the iLORest self application account with 'appaccount create --self' and retry. "
    "A specific account can still be queried directly with "
    "'appaccount exists --hostappid <id>' or 'appaccount details --hostappid <id>'.\n"
)

# Reason printed when a *specific* account's iLO status is reported as "unknown".
#
# iLO presence for a target is derived from the in-band enumeration
# (ListAppIds -> CompareAppIds), which needs the iLORest self application account.
# When the self account is absent the enumeration returns nothing, so iLO state
# cannot be confirmed for the target — the account may well still exist in iLO.
# Reporting "unknown" (instead of a misleading "no") plus this reason keeps the
# output transparent about *why* the status could not be determined.
_ILO_STATE_UNKNOWN_REASON = (
    "Note: The iLO status above is shown as 'unknown' because it could not be "
    "verified. iLO application-account status is determined in-band (which requires "
    "the iLORest self application account, not present on this server) or by querying "
    "iLO directly with -u/-p credentials; neither could be completed here. The "
    "account may still exist in iLO. Create the self application account with "
    "'appaccount create --self', or retry with valid iLO credentials, to see "
    "accurate iLO status.\n"
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
                        # Credentials are optional for delete: when supplied they are
                        # validated and used, otherwise the operation runs in-band.
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
                            # Surfaced once by the centralized handler (UI.error);
                            # do not also log it here or it prints twice.
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

        # Validate any supplied credentials and resolve the session to use for this
        # subcommand: reuse an active session when present, otherwise create a
        # temporary one from the validated credentials. The temporary session is
        # always destroyed once the operation completes (including on error paths).
        session_context = self._acquire_session(options)
        # Expose the validated session so the REST query path can reuse it instead
        # of opening a redundant second iLO session (the redundant session is the
        # root cause of spurious "iLO: unknown" when the URI is actually reachable).
        self._session_context = session_context
        try:
            return self._process_command(options, app_obj)
        finally:
            self._release_session(session_context)
            self._session_context = None

    def _process_command(self, options, app_obj):
        """Dispatch the requested appaccount subcommand and return its result code.

        :param options: parsed command line options
        :param app_obj: the constructed AppAccount object for the operation
        :returns: a ReturnCodes value
        """
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
                    is_not_self = not options.self_register and options.hostappid and "00b5" not in options.hostappid
                    if not exists_in_tpm and is_not_self:
                        delete_response = self.rdmc.app.delete_token(app_obj)
                        LOGGER.debug(f"delete_response:{delete_response}")

                    app_obj = AppAccount(
                        appname=options.hostappname if "hostappname" in options else "self_register",
                        appid=options.hostappid if "hostappid" in options else "self_register",
                        salt=options.salt if "salt" in options else "self_register",
                        username=options.user,
                        password=options.password,
                        log_dir=self.rdmc.log_dir,
                    )
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
                except Exception as err:
                    LOGGER.debug(f"Appaccount creation failed:{err}")

            elif options.command.lower() == "delete":
                # Credentials are optional for delete. Deletion is attempted from
                # both TPM and iLO; the in-band VNIC layer enforces authorization.

                deleted_from_tpm = False

                # iLO can be modified over REST only when an active session exists
                # or credentials were supplied (for a temporary session).
                ilo_queryable = self._ilo_query_available(options)

                # iLO presence BEFORE the delete, from the in-band source (works
                # without credentials). Used to tell "removed" from "never there".
                ilo_present_before = self._exists_in_ilo_inband(app_obj, options)

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

                # Step 1: Delete from TPM (in-band via VNIC). For the self/00b5
                # account this also removes the linked iLO app account; for another
                # app a SEPARATE iLO orphan can survive and needs REST cleanup.
                try:
                    errorcode = self.rdmc.app.delete_token(app_obj)
                    if errorcode == 0:
                        deleted_from_tpm = True
                        LOGGER.debug("Successfully deleted app account from TPM")
                except Exception as tpm_error:
                    # TPM deletion failed (token may not exist in TPM), continue to try iLO deletion
                    LOGGER.debug("TPM deletion failed: %s", str(tpm_error))

                # Verify the actual iLO state AFTER the in-band delete rather than
                # assuming the TPM delete removed the iLO account.
                ilo_present_after = self._exists_in_ilo_inband(app_obj, options)

                # Step 2: If an iLO account still remains, remove it over REST when
                # iLO is reachable (covers surviving orphans for non-self apps).
                if ilo_present_after and ilo_queryable:
                    _, ilo_account = self._check_exists_in_ilo(options)
                    if ilo_account:
                        try:
                            self._cleanup_orphaned_ilo_account(ilo_account, options.user, options.password)
                            ilo_present_after = self._exists_in_ilo_inband(app_obj, options)
                            LOGGER.debug("Attempted REST removal of surviving iLO app account")
                        except Exception as ilo_error:
                            LOGGER.debug("iLO deletion failed: %s", str(ilo_error))

                # The iLO account is considered deleted only if it was present
                # before and is gone now — verified in-band, not assumed.
                deleted_from_ilo = ilo_present_before and not ilo_present_after

                self.rdmc.ui.printer("App account deleted from TPM: %s\n" % ("yes" if deleted_from_tpm else "no"))
                self.rdmc.ui.printer("App account deleted from iLO: %s\n" % ("yes" if deleted_from_ilo else "no"))
                if ilo_present_after and not ilo_queryable:
                    self.rdmc.ui.printer(
                        "Note: an app account still exists in iLO. Re-run with -u <username> "
                        "-p <password> to remove the iLO app account.\n"
                    )

                if deleted_from_tpm or deleted_from_ilo:
                    self.rdmc.ui.printer("Application account has been deleted successfully.\n")
                    return ReturnCodes.SUCCESS
                if ilo_present_after:
                    # The account still exists in iLO but could not be removed
                    # (no credentials). Do not raise the misleading "does not
                    # exist" error; the note above tells the user how to remove it.
                    return ReturnCodes.ACCOUNT_DOES_NOT_EXIST_ERROR
                raise NoAppAccountError("The application account you are trying to delete does not exist.\n")

            # Command to check if apptoken exists
            elif options.command.lower() == "exists":
                # Expand short app ID (4 chars) to full ID for the TPM token lookup.
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
                # iLO presence comes from the same in-band source `details` uses
                # (ListAppIds over VNIC), so `exists` and `details` agree. It is a
                # tri-state: yes/no when enumeration is available, or "unknown" when
                # the self application account is absent and iLO state cannot be
                # confirmed in-band (iLO credentials do not help). Reporting
                # "unknown" avoids the misleading "no" for an account that may still
                # exist in iLO.
                ilo_state = self._ilo_state_for_target(app_obj, options)

                self.rdmc.ui.printer("App account exists in TPM: %s\n" % ("yes" if exists_in_tpm else "no"))
                self.rdmc.ui.printer("App account exists in iLO: %s\n" % self._render_ilo_state(ilo_state))
                if ilo_state is None:
                    # Explain *why* iLO status is unknown so the user is not misled.
                    self.rdmc.ui.printer(_ILO_STATE_UNKNOWN_REASON)

                if exists_in_tpm or ilo_state is True:
                    self.rdmc.ui.printer("Application account exists for this host application.\n")
                    return ReturnCodes.SUCCESS
                self.rdmc.ui.printer("Application account does not exist for this hostapp.\n")
                if ilo_state is not None:
                    # Enumeration ran but did not find the account; advise that
                    # full enumeration depends on the self application account.
                    self._warn_enumeration_requires_self_account()
                return ReturnCodes.ACCOUNT_DOES_NOT_EXIST_ERROR

            # Command to list appids and if they are present in iLO and TPM
            elif options.command.lower() == "details":
                try:
                    list_of_appids = self._collect_app_accounts(app_obj, options)
                except redfish.hpilo.vnichpilo.InactiveAppAccountTokenError:
                    self.rdmc.ui.printer("AppAccount is inactive. Please run the appaccount reactivate command.\n")
                    return ReturnCodes.INACTIVE_APP_ACCOUNT_TOKEN

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
                            # Enumeration could not surface the target. This happens
                            # when the iLORest self (00b5) token is absent and no
                            # credentials were supplied: in-band ListAppIds needs one
                            # of them to authenticate, so it returns nothing. A
                            # *specific* app's TPM token can still be checked
                            # directly (exactly as `exists` does), so fall back to a
                            # direct per-app lookup before declaring it missing. This
                            # keeps `details` and `exists` consistent when the self
                            # account is not present.
                            fallback = self._direct_target_lookup(options)
                            if fallback:
                                selfdict = [fallback]
                                if "onlytoken" in options and options.onlytoken:
                                    del selfdict[0]["ExistsIniLO"]
                                elif "onlyaccount" in options and options.onlyaccount:
                                    del selfdict[0]["ExistsInTPM"]
                            else:
                                self._warn_enumeration_requires_self_account()
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
                    self._warn_enumeration_requires_self_account()
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
                    # The message is surfaced once by the centralized exception
                    # handler (UI.error). Do not log it here as well, or it prints
                    # twice on the console.
                    raise NoAppAccountError("The application account you are trying to reactivate does not exist.\n")
                try:
                    return_code = self.rdmc.app.reactivate_token(app_obj)
                    if return_code == 0:
                        self.rdmc.ui.printer("Application account has been reactivated successfully.\n")
                        return ReturnCodes.SUCCESS
                except redfish.rest.v1.InvalidCredentialsError:
                    # Surfaced once by the centralized handler (UI.invalid_credentials);
                    # keep a debug trace only, do not log to the console here.
                    LOGGER.debug("Invalid credentials during reactivate; re-raising for centralized handling")
                    raise redfish.rest.v1.InvalidCredentialsError(0)
                except Exception as excp:
                    # Carry the message on the exception so the centralized handler
                    # surfaces it once; keep the original error as a debug trace.
                    LOGGER.debug("Reactivate failed: %s", str(excp))
                    raise ReactivateAppAccountTokenError("Error occurred while reactivating application account.\n")
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

        Each dict contains at least: Id, HostAppId, HostAppName. Thin wrapper over
        :meth:`_query_ilo_app_accounts` that discards the success flag, for callers
        that only need the list. Returns an empty list when no session can be
        established or the query fails.
        """
        _ok, accounts = self._query_ilo_app_accounts(username, password)
        return accounts

    def _query_ilo_app_accounts(self, username=None, password=None):
        """Query iLO over REST for application accounts.

        Returns ``(query_ok, accounts)``. ``query_ok`` is True only when iLO was
        actually reached and the AppAccounts collection was read (HTTP 200) — i.e.
        the result is authoritative. It is False when iLO could not be reached or
        authenticated, so the absence of an account is *indeterminate* (callers
        should report "unknown" rather than "no"). ``accounts`` is a list of
        ``{Id, HostAppId, HostAppName}``.

        Session handling — each candidate session is tried in order and the first
        query that COMPLETES (HTTP 200) wins; a session that merely *exists* is not
        assumed to be usable (it may be rejected with HTTP 401
        ``Base.1.19.NoValidSession``):
          1. A credential session already validated by ``_acquire_session`` (run()),
             reused via its token. Released centrally by ``_release_session``; never
             deleted here.
          2. An active REST client session, reused via ``get_handler``.
          3. A fresh session created from the supplied ``-u``/``-p`` credentials,
             always released afterwards. This is the reliable fallback when the
             active client is an in-band CHIF session whose VNIC token iLO rejects
             for the REST AccountService. Without credentials and without a usable
             session, ``(False, [])`` is returned.
        """
        accounts = []
        session_token = None
        session_location = None
        created_session = False
        try:
            try:
                has_client = self.rdmc.app.current_client is not None
            except Exception:
                has_client = False

            # Try each available session in priority order, returning on the first
            # query that COMPLETES (HTTP 200). A session that exists is not assumed
            # to be usable: an active in-band CHIF client, or even a just-validated
            # session, can be rejected by the REST AccountService (HTTP 401
            # Base.1.19.NoValidSession). Only fall through to the next option on a
            # failed/incomplete query, and create a fresh credential session as the
            # final fallback — that is the path iLO accepted (HTTP 201) here.

            # 1. A credential session already validated by `_acquire_session`
            #    (run()). Released centrally by `_release_session`; never deleted
            #    here.
            ctx = getattr(self, "_session_context", None) or {}
            ctx_token = ctx.get("session_token")
            if ctx_token:
                LOGGER.debug("Trying the session validated by _acquire_session for the iLO app-account query")
                query_ok, found = self._fetch_app_accounts(ctx_token)
                if query_ok:
                    return query_ok, found

            # 2. An active REST client session, reused via get_handler.
            if has_client:
                query_ok, found = self._fetch_app_accounts(None)
                if query_ok:
                    return query_ok, found
                LOGGER.debug(
                    "Active-session app-account query did not complete (the active "
                    "client session may not be valid for AccountService); falling "
                    "back to the supplied credentials"
                )

            # 3. Create a fresh session from the supplied credentials. This is the
            #    most reliable path when the active client is an in-band CHIF
            #    session whose VNIC token iLO rejects for REST (HTTP 401).
            if not (username and password):
                LOGGER.debug("No usable session and no credentials – cannot query iLO app accounts via REST")
                return False, accounts
            session_token, session_location = self._create_ilo_session(username, password)
            created_session = True
            if not session_token:
                LOGGER.debug("Could not create temporary iLO session – iLO app-account state indeterminate")
                return False, accounts

            return self._fetch_app_accounts(session_token)
        except Exception as exc:
            LOGGER.debug("Failed to retrieve app accounts from iLO REST API: %s", str(exc))
            return False, accounts
        finally:
            # Only release a session this method created; never the acquired one.
            if created_session and session_token and session_location:
                self._delete_ilo_session(session_token, session_location)

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

    def _fetch_app_accounts(self, session_token):
        """Read the iLO AppAccounts collection and return ``(query_ok, accounts)``.

        ``query_ok`` is True only when the collection resource was read
        successfully (HTTP 200), making the returned list authoritative. The
        collection URI is discovered from ``AccountService`` when iLO exposes an
        OEM link, falling back to the well-known HPE path. ``accounts`` is a list
        of ``{Id, HostAppId, HostAppName}``.
        """
        import requests

        accounts = []
        seen_ids = set()
        headers = {"X-Auth-Token": session_token} if session_token else {}
        base = _ILO_VNIC_BASE_URL

        def _get(path_or_url):
            """GET a redfish resource; return its parsed dict or None on non-200."""
            path = path_or_url
            if session_token:
                url = path if path.startswith("https://") else base + path
                resp = requests.get(url, headers=headers, verify=False, timeout=10)
                if resp.status_code != 200:
                    return None
                return resp.json()
            # Active client session: use the rest handler with the bare path.
            handler_path = path
            if handler_path.startswith("https://"):
                handler_path = handler_path[len(base) :] if handler_path.startswith(base) else handler_path
            resp = self.rdmc.app.get_handler(handler_path, silent=True)
            if resp and getattr(resp, "status", None) == 200:
                return resp.dict
            return None

        collection_path = self._discover_app_accounts_path(_get)
        data = _get(collection_path)
        if not data:
            # The discovered (OEM-advertised) path could not be read. Fall back to
            # the well-known default collection before declaring the result
            # indeterminate — iLO may advertise a stale OEM link while still
            # serving the standard path.
            default_path = "/redfish/v1/AccountService/Oem/Hpe/AppAccounts/"
            if collection_path.rstrip("/") != default_path.rstrip("/"):
                LOGGER.debug(
                    "Discovered AppAccounts path '%s' unreadable; falling back to default '%s'",
                    collection_path,
                    default_path,
                )
                data = _get(default_path)
        if not data:
            # The collection could not be read -> result is indeterminate.
            return False, accounts

        for member in data.get("Members", []):
            uri = member.get("@odata.id", "")
            if not uri:
                continue
            try:
                acc = _get(uri)
                if not acc:
                    continue
                host_app_id = acc.get("HostAppId", "") or acc.get("HostApplicationId", "")
                if host_app_id and host_app_id not in seen_ids:
                    seen_ids.add(host_app_id)
                    accounts.append(
                        {
                            "Id": acc.get("Id", ""),
                            "HostAppId": host_app_id,
                            "HostAppName": acc.get("HostAppName", "") or acc.get("HostApplicationName", ""),
                        }
                    )
            except Exception:
                # A single member read failing does not invalidate the collection.
                pass
        return True, accounts

    def _discover_app_accounts_path(self, get_fn):
        """Return the iLO AppAccounts collection path.

        Discovers the collection from ``/redfish/v1/AccountService/`` when iLO
        exposes it under the HPE OEM section (``Oem.Hpe.Links.AppAccounts`` or
        ``Oem.Hpe.AppAccounts``); otherwise returns the well-known default path.
        Being link-driven makes the lookup resilient to schema path differences
        across iLO versions.
        """
        default = "/redfish/v1/AccountService/Oem/Hpe/AppAccounts/"
        try:
            acct = get_fn("/redfish/v1/AccountService/")
            if acct:
                oem_hpe = (acct.get("Oem") or {}).get("Hpe") or {}
                for container in (oem_hpe.get("Links") or {}, oem_hpe):
                    app_accounts = container.get("AppAccounts")
                    if isinstance(app_accounts, dict) and app_accounts.get("@odata.id"):
                        return app_accounts["@odata.id"]
        except Exception as exc:
            LOGGER.debug("AppAccounts collection discovery failed; using default path: %s", str(exc))
        return default

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
                # App ids are commonly referred to by their last 4 characters, and
                # a full hostappid (e.g. "…548bb") shares those last 4 with the
                # stored account ("…48bb"). Match on the last 4 for any target of
                # length >= 4, not only when the target is exactly 4 characters.
                if len(target_id) >= 4 and len(host_app_id) >= 4 and host_app_id[-4:].lower() == target_id[-4:].lower():
                    return True, account

        return False, None

    def _collect_app_accounts(self, app_obj, options):
        """Return the merged list of app accounts from the in-band source of truth.

        Uses ListAppIds (in-band over VNIC) — which reports both TPM and iLO state
        without REST credentials — and additionally merges any iLO-only orphans a
        REST query surfaces when a session/credentials are available. This is the
        single source shared by ``details``, ``exists`` and ``delete`` so their
        answers stay consistent regardless of whether credentials were supplied.

        The enumeration always uses a *generic* (``self_register``) object because
        ``ListAppIds`` returns a set filtered to whatever account ``app_obj``
        describes; a specific target object would hide iLO-only orphans for other
        apps. ``app_obj`` is therefore intentionally not forwarded to ListAppIds.

        :param app_obj: the caller's AppAccount object (kept for signature
            compatibility; not used to filter the enumeration)
        :param options: parsed command line options
        :returns: a list of account dicts with ApplicationID/ApplicationName and
            the ExistsInTPM/ExistsIniLO flags
        :raises redfish.hpilo.vnichpilo.InactiveAppAccountTokenError: propagated so
            callers can report the inactive-token state per command
        """
        # In-band enumeration (ListAppIds -> CompareAppIds), then merge any
        # iLO-only accounts a direct REST query surfaces.
        list_of_appids = self._dedupe_app_accounts(self._list_app_ids_inband(options))

        # Merge accounts found only in iLO (orphaned after a TPM clear).
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
        return list_of_appids

    @staticmethod
    def _dedupe_app_accounts(accounts):
        """Collapse duplicate app-account entries that share an ApplicationID.

        The in-band ``ListAppIds`` enumeration can report the same account more
        than once (observed for the iLORest self/00b5 account), which previously
        caused ``details --hostappid all`` to print the same account twice.
        Deduplicate case-insensitively on ``ApplicationID`` while preserving the
        first occurrence and the original ordering.

        :param accounts: list of account dicts with an ``ApplicationID`` key
        :returns: a new list with duplicate ApplicationIDs removed
        """
        seen = set()
        deduped = []
        for account in accounts:
            key = (account.get("ApplicationID", "") or "").lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(account)
        return deduped

    def _list_app_ids_inband(self, options):
        """Return the in-band ListAppIds enumeration (no REST), or ``[]``.

        ListAppIds -> DLL CompareAppIds lists accounts over the in-band VNIC
        channel using the iLORest self (00b5) application account context; it reads
        only appid/appname/salt and ignores username/password. The ``self_register``
        appid sentinel requests the full comparison set (appname/salt left None —
        AppAccount normalises None to ``"self_register"`` internally). When the self
        account is absent, CompareAppIds returns no accounts, so callers fall back
        to a direct REST query.

        :raises redfish.hpilo.vnichpilo.InactiveAppAccountTokenError: propagated so
            callers can report the inactive-token state.
        """
        enum_obj = AppAccount(
            appname=None,
            appid="self_register",
            salt=None,
            username=getattr(options, "user", None),
            password=getattr(options, "password", None),
            log_dir=self.rdmc.log_dir,
        )
        try:
            return self.rdmc.app.ListAppIds(enum_obj)
        except redfish.hpilo.vnichpilo.InactiveAppAccountTokenError:
            raise
        except Exception:
            LOGGER.debug("ListAppIds failed (TPM may have been cleared or self account absent)")
            return []

    def _match_target_account(self, accounts, options):
        """Return the account entry matching the requested target, or ``None``.

        Matches the self-registered iLORest account (00b5) for ``--self``, or the
        supplied ``--hostappid`` by full id or last-4 characters (a full hostappid
        shares its last 4 with the stored account id).
        """
        is_self = getattr(options, "self_register", False)
        target = getattr(options, "hostappid", None)
        for acc in accounts:
            appid = acc.get("ApplicationID", "")
            if is_self:
                if "00b5" in appid.lower():
                    return acc
            elif target:
                if appid.lower() == target.lower():
                    return acc
                if len(target) >= 4 and len(appid) >= 4 and appid[-4:].lower() == target[-4:].lower():
                    return acc
        return None

    def _exists_in_ilo_inband(self, app_obj, options):
        """Return True if the target account exists in iLO per the in-band source.

        Boolean view of :meth:`_ilo_state_for_target` (treating "unknown" as
        False) for callers — such as ``delete`` — that only need presence/absence.
        Mirrors what ``details`` reports (ListAppIds over VNIC), so ``exists`` and
        ``details`` agree without depending on REST credentials.
        """
        return self._ilo_state_for_target(app_obj, options) is True

    def _ilo_state_for_target(self, app_obj, options):
        """Return a target's iLO presence as a tri-state: True, False, or None.

        Resolution order:
          1. In-band enumeration (ListAppIds -> CompareAppIds). When the iLORest
             self application account is present this is authoritative — return
             True/False from the match.
          2. When in-band enumeration is unavailable (self account absent → no
             accounts), query iLO directly over REST using the supplied
             credentials. If that query completes, return a definitive True/False.
          3. Only when neither source can produce an answer (no self account and
             the REST query could not be completed) return ``None`` ("unknown"),
             so callers report "unknown" instead of a misleading "no".

        :param app_obj: the AppAccount object for the operation
        :param options: parsed command line options
        :returns: ``True``, ``False`` or ``None``
        """
        # 1. In-band enumeration (definitive when the self account is present).
        try:
            inband_accounts = self._list_app_ids_inband(options)
        except redfish.hpilo.vnichpilo.InactiveAppAccountTokenError:
            # The self token exists but is inactive; in-band enumeration is
            # unavailable. Fall through to the direct REST query.
            inband_accounts = []
        if inband_accounts:
            entry = self._match_target_account(inband_accounts, options)
            return bool(entry and entry.get("ExistsIniLO"))

        # 2. In-band unavailable — query iLO directly over REST with credentials.
        return self._rest_ilo_state_for_target(options)

    def _rest_ilo_state_for_target(self, options):
        """Return a target's iLO presence from a direct REST query as a tri-state.

        ``True``/``False`` when iLO was reached and the AppAccounts collection was
        read (the target was/was not among the accounts). ``None`` when iLO could
        not be queried (no credentials/session, or the query failed), so the answer
        is indeterminate rather than a misleading "no".

        :param options: parsed command line options
        :returns: ``True``, ``False`` or ``None``
        """
        username = getattr(options, "user", None)
        password = getattr(options, "password", None)
        if not (username and password) and not self._has_active_session():
            # Nothing to query iLO with.
            return None

        query_ok, accounts = self._query_ilo_app_accounts(username, password)
        if not query_ok:
            # iLO could not be queried -> indeterminate.
            return None

        is_self = getattr(options, "self_register", False)
        target_id = getattr(options, "hostappid", None)
        for account in accounts:
            host_app_id = account.get("HostAppId", "") or ""
            host_app_name = account.get("HostAppName", "") or ""
            if is_self:
                if "00b5" in host_app_id.lower() or host_app_name.lower() == "ilorest":
                    return True
            elif target_id:
                if host_app_id.lower() == target_id.lower():
                    return True
                if len(target_id) >= 4 and len(host_app_id) >= 4 and host_app_id[-4:].lower() == target_id[-4:].lower():
                    return True
        # Query completed and the target was not present -> definitive "no".
        return False

    @staticmethod
    def _render_ilo_state(state):
        """Render a tri-state iLO presence (True/False/None) as yes/no/unknown."""
        if state is None:
            return "unknown"
        return "yes" if state else "no"

    def _direct_target_lookup(self, options):
        """Resolve a specific ``--hostappid`` target via direct per-app checks.

        In-band ``ListAppIds`` enumeration cannot list any account when the iLORest
        self (00b5) token is absent and no credentials are supplied, because the
        privileged VNIC channel can only be authenticated with the self token or
        supplied credentials. A *specific* app's TPM token, however, can still be
        checked directly with ``token_exists`` — which is exactly what ``exists``
        relies on. ``details`` therefore falls back to the same direct checks when
        enumeration does not surface the requested target, keeping ``details`` and
        ``exists`` consistent when the self account is not present.

        :param options: parsed command line options (must carry ``hostappid``)
        :returns: an account dict (ApplicationID/ApplicationName/ExistsInTPM/
            ExistsIniLO) when the target exists in TPM or iLO, else ``None``
        """
        target_id = getattr(options, "hostappid", None)
        if not target_id:
            return None

        appname = options.hostappname if "hostappname" in options and options.hostappname else "self_register"
        salt = options.salt if "salt" in options and options.salt else "self_register"
        username = getattr(options, "user", None)
        password = getattr(options, "password", None)

        # Best-effort expansion of a short (4-char) id to its full form so the
        # direct TPM lookup targets the right token.
        resolved_id = target_id
        if len(target_id) == 4:
            try:
                base_obj = AppAccount(
                    appname=appname,
                    appid=target_id,
                    salt=salt,
                    username=username,
                    password=password,
                    log_dir=self.rdmc.log_dir,
                )
                resolved_id = self.rdmc.app.ExpandAppId(base_obj, target_id)
            except Exception:
                resolved_id = target_id

        target_obj = AppAccount(
            appname=appname,
            appid=resolved_id,
            salt=salt,
            username=username,
            password=password,
            log_dir=self.rdmc.log_dir,
        )

        exists_in_tpm = self._check_exists_in_tpm(target_obj)
        # Tri-state: True/False when enumeration is available, None ("unknown")
        # when the self application account is absent and iLO state cannot be
        # confirmed in-band.
        ilo_state = self._ilo_state_for_target(target_obj, options)
        if not (exists_in_tpm or ilo_state is True):
            return None

        return {
            "ApplicationID": resolved_id or target_id,
            # The host application name is only known when enumeration succeeds;
            # in the direct-lookup fallback it is unavailable, so leave it blank.
            "ApplicationName": getattr(options, "hostappname", None) or "",
            "ExistsInTPM": exists_in_tpm,
            "ExistsIniLO": ilo_state,
        }

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
                # silent=True: a 404 here (the account is already gone) means the
                # cleanup goal is already met and must NOT print the raw
                # "[404] Base.1.19.ResourceMissingAtURI" iLO error to the console.
                self.rdmc.app.delete_handler(delete_url_path, silent=True)
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
                    # 404 means the account is already gone -> cleanup succeeded.
                    # Treat the success/no-content/not-found codes as success and
                    # only surface genuinely unexpected failures.
                    if response.status_code not in (200, 202, 204, 404):
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

    def _has_active_session(self):
        """Return True when an active iLO REST client session is already established."""
        try:
            return self.rdmc.app.current_client is not None
        except Exception as exc:
            LOGGER.debug("Failed to probe for active session: %s", str(exc))
            return False

    def _warn_enumeration_requires_self_account(self):
        """Advise that in-band enumeration needs the iLORest self application account.

        ``ListAppIds`` (DLL ``CompareAppIds``) enumerates application accounts over
        the in-band VNIC channel using the iLORest self (00b5) application account;
        it does not use iLO credentials. When the self account is absent the
        firmware reports no accounts even though others (e.g. created by Smart
        Update Manager) exist in TPM/iLO. Surface that explanation so an empty
        result is not mistaken for "none exist".
        """
        self.rdmc.ui.printer(_SELF_ACCOUNT_ENUM_ADVISORY)

    def _ilo_query_available(self, options):
        """Return True when iLO can actually be queried over REST.

        An iLO app-account lookup is only possible when either an active REST
        client session already exists, or credentials were supplied (which can
        be used to create a temporary session). Without one of these the lookup
        cannot run, so callers must report the iLO status as "unknown" rather
        than claiming the account is absent.

        :param options: parsed command line options
        :returns: True if iLO is reachable for a REST lookup, else False
        """
        if self._has_active_session():
            return True
        username = getattr(options, "user", None)
        password = getattr(options, "password", None)
        return bool(username and password)

    def _validate_credentials(self, username, password):
        """Validate iLO credentials by establishing a probe REST session.

        Args:
            username: iLO account username (may be ``None``).
            password: iLO account password (may be ``None``).

        Returns:
            A ``(session_token, session_location)`` tuple. Both elements are
            ``None`` when no credentials were supplied.

        Raises:
            redfish.rest.v1.InvalidCredentialsError: If credentials were supplied
                but a session could not be created (i.e. they are invalid).
        """
        if not (username and password):
            return None, None

        session_token, session_location = self._create_ilo_session(username, password)
        if not session_token:
            # Surfaced once by the centralized handler (UI.invalid_credentials);
            # keep a debug trace only, do not log to the console here.
            LOGGER.debug("Provided iLO credentials could not be validated; raising InvalidCredentialsError")
            raise redfish.rest.v1.InvalidCredentialsError(0)
        return session_token, session_location

    def _acquire_session(self, options):
        """Validate credentials then resolve which session the operation should use.

        Flow (applied to every appaccount subcommand):
          1. Validate any supplied credentials — invalid credentials raise. This
             happens even when an active session already exists, so that bad
             credentials never go unreported.
          2. Probe for an active session; reuse it when present (discarding the
             short-lived validation session).
          3. Otherwise, promote the validated credentials' session to a temporary
             session that the caller must release after use.

        Returns:
            A session-context dict with keys ``session_token``,
            ``session_location``, ``temp_session`` and ``active``.

        Raises:
            redfish.rest.v1.InvalidCredentialsError: If credentials were supplied
                but could not be validated.
        """
        username = getattr(options, "user", None)
        password = getattr(options, "password", None)
        token, location = self._validate_credentials(username, password)

        if self._has_active_session():
            # The active session takes priority; discard the validation session.
            if token:
                self._delete_ilo_session(token, location)
            return {
                "session_token": None,
                "session_location": None,
                "temp_session": False,
                "active": True,
            }

        if token:
            # Reuse the validated credentials' session as the temporary session.
            return {
                "session_token": token,
                "session_location": location,
                "temp_session": True,
                "active": False,
            }

        return {
            "session_token": None,
            "session_location": None,
            "temp_session": False,
            "active": False,
        }

    def _release_session(self, session_context):
        """Destroy a temporary session created by :meth:`_acquire_session`.

        Active (reused) sessions are left untouched. Cleanup failures are logged
        but never propagated so they cannot mask the operation's own result.
        """
        if not session_context or not session_context.get("temp_session"):
            return
        try:
            self._delete_ilo_session(
                session_context.get("session_token"),
                session_context.get("session_location"),
            )
        except Exception as exc:
            LOGGER.debug("Failed to release temporary iLO session: %s", str(exc))

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
        ilo_unknown = False
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
                ilo_val = printdict[i]["ExistsIniLO"]
                final_output += "App account exists in iLO: "
                if ilo_val is None:
                    # Tri-state: iLO status could not be confirmed in-band.
                    final_output += "unknown\n"
                    ilo_unknown = True
                elif ilo_val:
                    final_output += "yes\n"
                else:
                    final_output += "no\n"
            final_output += "\n"

        if ilo_unknown:
            # Explain once why any iLO status was reported as "unknown".
            final_output += _ILO_STATE_UNKNOWN_REASON

        self.rdmc.ui.printer(final_output)

    def get_ilover_beforelogin(self, app_obj):
        try:
            ilo_ver, sec_state = self.rdmc.app.getilover_beforelogin(app_obj)
        except ChifDriverMissingOrNotFound:
            # The library could not reach iLO in-band (e.g. unsupported iLO).
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
                "Please ensure that the virtual NIC is enabled in iLO and "
                "configured properly in the host OS.\n"
                "Note: appaccount command can only be executed from the host OS of a VNIC-enabled iLO7 server.\n"
            )

        # appaccount is supported only on VNIC-enabled iLO7 (and newer) servers.
        # Checked outside the try so this version gate is not swallowed by the
        # generic exception handler above.
        if ilo_ver < 7:
            raise IncompatibleiLOVersionError("This feature is only available for iLO 7 or higher.\n")

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
