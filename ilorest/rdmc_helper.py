###
# Copyright 2017-2025 Hewlett Packard Enterprise, Inc. All rights reserved.
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
"""This is the helper module for RDMC"""

# ---------Imports---------
from __future__ import unicode_literals

import json
import logging
import os
import sys
import time
from ctypes import byref, c_char_p, create_string_buffer

try:
    from logging_config_path import get_logging_config_path
except ModuleNotFoundError:
    from ilorest.logging_config_path import get_logging_config_path


import pyaes
import six
from prompt_toolkit.completion import Completer, Completion

import redfish.hpilo.risblobstore2 as risblobstore2
import redfish.ris
import logging.config

try:
    import versioning
except ImportError:
    from ilorest import versioning

if os.name == "nt":
    from six.moves import winreg

    if six.PY2:
        from win32con import HKEY_LOCAL_MACHINE
    elif six.PY3:
        from win32.lib.win32con import HKEY_LOCAL_MACHINE

# ---------End of imports---------


# Using hard coded list until better solution is found
HARDCODEDLIST = [
    "modified",
    "attributeregistry",
    "links",
    "settingsresult",
    "actions",
    "availableactions",
    "extref",
]

# ---------Debug logger---------
# Centralized logging behaviour:
# - The JSON config in ilorest/logging_config.json defines handlers/formatters.
# - `setup_logging_from_json()` loads that config and uses `prepare_log_directory()` to
#   resolve and create a writable `logdir` (trying the configured path first and then
#   platform-specific fallbacks).  This centralizes all directory-selection logic.
# - `setup_fallback_logging()` is to support fallback logging if the JSON config
#   cannot be loaded or applied for some reason.  It uses command line flags to retain old functionality.


class InfoFilter(logging.Filter):
    """Filter to allow only INFO and WARNING messages, blocking ERROR and above"""

    def filter(self, record):
        # Allow only records below ERROR (i.e., INFO and WARNING)
        return record.levelno < logging.ERROR


# Logger instance - configuration will be handled by JSON config file
LOGGER = logging.getLogger(__name__)


def clear_existing_handlers():
    """Clear any existing log handlers to avoid conflicts."""
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)


def setup_fallback_logging(reason="Unknown error", opts=None):
    """
    Fallback logging setup when all else fails.

    Args:
        reason: The reason for falling back to fallback logging
        opts: Optional command line options that may contain logging flags
    """
    try:
        clear_existing_handlers()

        # Extract command line flags from opts or sys.argv
        debug_flag = False
        noinfo_flag = False
        nostdout_flag = False
        log_dir = os.path.join(os.getcwd(), "ilorest_logs")

        if opts:
            debug_flag = getattr(opts, "debug", False)
            noinfo_flag = getattr(opts, "noinfolog", False)
            nostdout_flag = getattr(opts, "nostdoutlog", False)
            custom_logdir = getattr(opts, "logdir", None)
            if custom_logdir:
                log_dir = os.path.normpath(custom_logdir)
        else:
            # Check sys.argv as fallback
            debug_flag = any(arg in ["-d", "--debug"] for arg in sys.argv)
            noinfo_flag = any(arg in ["--noinfolog"] for arg in sys.argv)
            nostdout_flag = any(arg in ["--nostdoutlog"] for arg in sys.argv)

        # Create log directory
        os.makedirs(log_dir, exist_ok=True)
        log_file_path = os.path.join(log_dir, "iLORest.log")

        # Determine logging level (debug takes precedence over noinfo)
        if noinfo_flag and not debug_flag:
            file_level = logging.ERROR
        elif debug_flag:
            file_level = logging.DEBUG
        else:
            file_level = logging.INFO

        # Configure file handler
        file_handler = logging.FileHandler(log_file_path)
        file_handler.setLevel(file_level)
        file_formatter = logging.Formatter("%(levelname)s\t: %(message)s")
        file_handler.setFormatter(file_formatter)

        handlers = [file_handler]

        # Configure stdout handler so that INFO (and below) do NOT go to stdout.
        # The console should show CRITICAL by default, but if the
        # global file level is higher (e.g. ERROR due to --noinfolog), keep
        # stdout at that higher level to respect the flag.
        if not nostdout_flag:
            stdout_handler = logging.StreamHandler(sys.stdout)
            # If user requested debug output on the command line, allow stdout to
            # receive DEBUG messages. Otherwise keep stdout quieter (CRITICAL)
            if debug_flag:
                stdout_level = logging.DEBUG
            else:
                # set to default CRITICAL
                stdout_level = logging.CRITICAL
            stdout_handler.setLevel(stdout_level)
            stdout_handler.setFormatter(file_formatter)
            handlers.append(stdout_handler)

        # Apply configuration to the root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(file_level)

        # Clear any existing handlers (already done above) then add ours
        for h in handlers:
            root_logger.addHandler(h)

        logger = logging.getLogger(__name__)
        logger.debug("Fallback to basic configurations for logging: %s (logdir=%s)", reason, log_dir)
        return True

    except Exception as fallback_error:
        # If even fallback setup failed, write to stderr directly
        sys.stderr.write(f"Critical: All fallback logging attempts failed: {reason} - {fallback_error}\n")
        return False


def load_config_file(config_path):
    """Load and validate the JSON configuration file."""
    if not os.path.isfile(config_path):
        raise FileNotFoundError(f"JSON config file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    # Validate basic structure
    if not isinstance(config, dict):
        raise ValueError("Config file must contain a JSON object")

    if "handlers" not in config:
        raise ValueError("Config file must contain 'handlers' section")

    return config


def prepare_log_directory(config):
    """Determine and prepare a writable log directory based on config and platform.

    Behavior (matching historical implementation):
    - Try the JSON-configured path first (absolute).
    - If that fails, fall back to a single directory:
        - On Windows: use APPDATA if set
        - Otherwise: use ~/.local/share
    - Return the directory that is writable; raise PermissionError if neither works.
    """
    primary = config.get("logdir", "./ilorest_logs")
    if not os.path.isabs(primary):
        primary = os.path.abspath(primary)

    def _writable_dir(path):
        try:
            os.makedirs(path, exist_ok=True)
            testfile = os.path.join(path, ".write_test")
            with open(testfile, "w") as fh:
                fh.write("ok")
            try:
                os.remove(testfile)
            except Exception:
                pass
            return True
        except Exception:
            return False

    # Try primary configured path first
    if _writable_dir(primary):
        LOGGER.debug("Selected logdir (configured): %s", os.path.normpath(primary))
        return os.path.normpath(primary)

    # Single fallback to APPDATA or ~/.local/share (matching legacy behavior)
    appdata = os.getenv("APPDATA")
    if appdata:
        fallback_dir = appdata
    else:
        fallback_dir = os.path.join(os.path.expanduser("~"), ".local", "share")

    fallback_dir = os.path.join(fallback_dir, "ilorest_logs")

    if _writable_dir(fallback_dir):
        LOGGER.debug("Selected logdir (fallback): %s", os.path.normpath(fallback_dir))
        return os.path.normpath(fallback_dir)

    # Nothing worked
    raise PermissionError(f"Unable to create or write to configured logdir '{primary}' or fallback '{fallback_dir}'")


def configure_file_handler(config, logdir):
    """Configure the file handler with proper path joining and validation."""
    file_handler = config.get("handlers", {}).get("file", {})
    if not file_handler:
        return

    original_filename = file_handler.get("filename", "iLORest.log")
    if "%(logdir)s" in original_filename:
        filename = original_filename.replace("%(logdir)s", logdir)
    else:
        filename = os.path.join(logdir, "iLORest.log")

    file_handler["filename"] = os.path.normpath(filename)

    # Test if we can write to the log file
    try:
        with open(file_handler["filename"], "a") as test_file:
            pass  # Just test if we can open for writing
    except (IOError, OSError, PermissionError) as e:
        raise ValueError(f"Cannot write to log file {file_handler['filename']}: {e}")


def set_logging_config_with_flags(config, nostdout=False, noinfo=False, debug=False):
    """Modify logging configuration based on command-line flags.

    :param config: The logging configuration dictionary to modify
    :type config: dict
    :param nostdout: Flag to suppress stdout logging
    :type nostdout: bool
    :param noinfo: Flag to suppress info level logging
    :type noinfo: bool
    :param debug: Flag to enable debug level logging
    :type debug: bool
    :returns: Modified configuration dictionary
    :rtype: dict
    """
    # Handle priority: debug takes precedence over noinfo when both are set
    if noinfo and debug:
        noinfo = False

    # Modify config based on early command-specific flags
    if nostdout and "handlers" in config and "stdout" in config["handlers"]:
        # Remove stdout handler from the configuration
        del config["handlers"]["stdout"]
        # Remove stdout from all logger handlers lists
        for logger_name, logger_config in config.get("loggers", {}).items():
            if "handlers" in logger_config and "stdout" in logger_config["handlers"]:
                logger_config["handlers"] = [h for h in logger_config["handlers"] if h != "stdout"]

    # Modify logging levels based on flags
    if noinfo:
        level = "ERROR"
    elif debug:
        level = "DEBUG"
    else:
        level = None

    if level:
        # Apply level to all loggers
        for logger_name, logger_config in config.get("loggers", {}).items():
            logger_config["level"] = level
        # Also apply to handlers if needed
        for handler_name, handler_config in config.get("handlers", {}).items():
            if handler_name != "stderr":  # Keep stderr at ERROR level
                handler_config["level"] = level

    return config


def setup_logging_from_json(opts=None):
    """Setup logging from JSON config file using dictConfig with comprehensive fallback.

    This function attempts to load logging configuration from a JSON file and falls back
    to existing configuration if the JSON config fails for any reason.
    If `opts` is provided, it extracts logging flags from the options object.

    """
    config_path = get_logging_config_path()

    try:
        # Load and validate configuration file
        config = load_config_file(config_path)

        # Extract logging flags from opts if provided and apply_flags is True
        if opts:
            nostdout = getattr(opts, "nostdoutlog", False)
            noinfo = getattr(opts, "noinfolog", False)
            debug = getattr(opts, "debug", False)
            logdir = getattr(opts, "logdir", None)

            # If caller passed an explicit logdir, use it to override the config value
            if logdir:
                # normalize and set
                config["logdir"] = os.path.normpath(logdir)

            # Modify config based on flags using the dedicated function
            config = set_logging_config_with_flags(config, nostdout, noinfo, debug)

        # Prepare log directory (this will create it if missing)
        final_logdir = prepare_log_directory(config)

        # Configure file handler paths (will replace %(logdir)s etc.)
        configure_file_handler(config, final_logdir)

        # Clear any existing handlers to avoid conflicts
        clear_existing_handlers()

        # Apply the logging configuration
        logging.config.dictConfig(config)

        # Test that logging is working (only if not suppressing info logs and flags applied)
        if opts and not getattr(opts, "noinfolog", False):
            logger = logging.getLogger(__name__)
            logger.debug("Logging configuration loaded successfully from JSON (logdir=%s)", final_logdir)
    except FileNotFoundError as e:
        setup_fallback_logging(str(e), opts)
        return None
    except (PermissionError, IOError) as e:
        setup_fallback_logging(f"File access error: {e}", opts)
        return None
    except json.JSONDecodeError as e:
        setup_fallback_logging(f"Invalid JSON format: {e}", opts)
        return None
    except (KeyError, ValueError, TypeError) as e:
        setup_fallback_logging(f"Invalid configuration structure: {e}", opts)
        return None
    except Exception as e:
        setup_fallback_logging(f"Unexpected error loading config: {e}", opts)
        return None


# ---------End of debug logger---------


class ReturnCodes(object):
    """Return code class to be used by all functions"""

    SUCCESS = 0

    # ****** RDMC ERRORS ******
    CONFIGURATION_FILE_ERROR = 1
    COMMAND_NOT_ENABLED_ERROR = 2
    INVALID_COMMAND_LINE_ERROR = 3
    INVALID_FILE_FORMATTING_ERROR = 4
    USER_NOT_ADMIN = 5
    NO_CONTENTS_FOUND_FOR_OPERATION = 6
    INVALID_FILE_INPUT_ERROR = 7
    NO_CHANGES_MADE_OR_FOUND = 8
    NO_VALID_INFO_ERROR = 9

    # ****** CLI ERRORS ******
    UI_CLI_ERROR_EXCEPTION = 10
    UI_CLI_WARN_EXCEPTION = 11
    UI_CLI_USAGE_EXCEPTION = 12
    UI_CLI_COMMAND_NOT_FOUND_EXCEPTION = 13
    INVALID_PASSWORD_LENGTH_ERROR = 14

    # ****** RMC/RIS ERRORS ******
    RIS_UNDEFINED_CLIENT_ERROR = 21
    RIS_CURRENTLY_LOGGED_IN_ERROR = 22
    RIS_INSTANCE_NOT_FOUND_ERROR = 23
    RIS_NOTHING_SELECTED_ERROR = 24
    RIS_NOTHING_SELECTED_FILTER_ERROR = 25
    RIS_NOTHING_SELECTED_SET_ERROR = 26
    RIS_INVALID_SELECTION_ERROR = 27
    RIS_VALIDATION_ERROR = 28
    RIS_MISSING_ID_TOKEN = 29
    RIS_SESSION_EXPIRED = 30

    # ****** REST V1 ERRORS ******
    V1_RETRIES_EXHAUSTED_ERROR = 31
    V1_INVALID_CREDENTIALS_ERROR = 32
    V1_SERVER_DOWN_OR_UNREACHABLE_ERROR = 33
    V1_CHIF_DRIVER_MISSING_ERROR = 34
    REST_ILOREST_CHIF_DLL_MISSING_ERROR = 35
    REST_ILOREST_UNEXPECTED_RESPONSE_ERROR = 36
    REST_ILOREST_ILO_ERROR = 37
    REST_ILOREST_CREATE_BLOB_ERROR = 38
    REST_ILOREST_READ_BLOB_ERROR = 39

    # ****** RDMC ERRORS ******
    SAME_SETTINGS_ERROR = 40
    FIRMWARE_UPDATE_ERROR = 41
    BOOT_ORDER_ENTRY_ERROR = 42
    NIC_MISSING_OR_INVALID_ERROR = 43
    NO_CURRENT_SESSION_ESTABLISHED = 44
    FAILURE_DURING_COMMIT_OPERATION = 45
    USERNAME_PASSWORD_REQUIRED_ERROR = 46
    VNIC_NOT_ENABLED_ERROR = 47
    MULTIPLE_SERVER_CONFIG_FAIL = 51
    MULTIPLE_SERVER_INPUT_FILE_ERROR = 52
    LOAD_SKIP_SETTING_ERROR = 53
    INCOMPATIBLE_ILO_VERSION_ERROR = 54
    INVALID_CLIST_FILE_ERROR = 55
    UNABLE_TO_MOUNT_BB_ERROR = 56
    BIRTHCERT_PARSE_ERROR = 57
    INCOMPATIBLE_SERVER_TYPE = 58
    ILO_LICENSE_ERROR = 59
    RESOURCE_EXISTS_ERROR = 60

    # ****** RMC/RIS ERRORS ******
    RIS_VALUE_CHANGED_ERROR = 61
    RIS_REF_PATH_NOT_FOUND_ERROR = 62
    RIS_ILO_RESPONSE_ERROR = 63
    RIS_ILO_INIT_ERROR = 64
    RIS_SCHEMA_PARSE_ERROR = 65
    RIS_ILO_CHIF_ACCESS_DENIED_ERROR = 66
    RIS_CREATE_AND_PREPARE_CHANNEL_ERROR = 67
    RIS_ILO_CHIF_PACKET_EXCHANGE_ERROR = 71
    RIS_ILO_CHIF_NO_DRIVER_ERROR = 69

    # ****** REST V1 ERRORS ******
    REST_ILOREST_WRITE_BLOB_ERROR = 70
    REST_ILOREST_BLOB_DELETE_ERROR = 68
    REST_ILOREST_BLOB_FINALIZE_ERROR = 72
    REST_ILOREST_BLOB_NOT_FOUND_ERROR = 73
    JSON_DECODE_ERROR = 74
    V1_SECURITY_STATE_ERROR = 75
    REST_ILOREST_BLOB_OVERRIDE_ERROR = 76
    REST_BLOB_RETRIES_EXHAUSETED_ERROR = 77

    # ****** RDMC ERRORS ******
    RESOURCE_ALLOCATION_ISSUES_ERROR = 80
    ENCRYPTION_ERROR = 81
    DRIVE_MISSING_ERROR = 82
    PATH_UNAVAILABLE_ERROR = 83
    ILO_RIS_CORRUPTION_ERROR = 84
    RESOURCE_NOT_READY_ERROR = 85
    INVALID_SMART_ARRAY_PAYLOAD = 86

    # ****** RIS ERRORS ******
    RIS_RIS_BIOS_UNREGISTERED_ERROR = 100

    # ***** Upload/Download ERRORS ******
    FAILED_TO_DOWNLOAD_COMPONENT = 101
    UPDATE_SERVICE_BUSY = 102
    FAILED_TO_UPLOAD_COMPONENT = 103
    TASKQUEUE_ERROR = 104
    DEVICE_DISCOVERY_IN_PROGRESS = 105
    INSTALLSET_ERROR = 106
    INVALID_TARGET_ERROR = 107
    ILO_UNSUPPORTED_FLASH = 108

    # **** ComputeOpsManagement Errors****
    CLOUD_CONNECT_TIMEOUT = 111
    CLOUD_CONNECT_FAILED = 112
    CLOUD_ALREADY_CONNECTED = 113
    PROXY_CONFIG_FAILED = 114

    # **** scep error ****
    SCEP_ENABLED_ERROR = 121

    # *** authentication error ****
    TFA_WRONG_OTP = 131
    TFA_OTP_TIMEDOUT = 132
    TFA_ENABLED_ERROR = 133
    TFA_OTP_EMAILED = 134

    # ****** GENERAL ERRORS ******
    GENERAL_ERROR = 255

    # ****** VNIC ERRORS ******
    GENERAL_ACCOUNT_GENERATE_SAVE_ERROR = 141
    VNIC_DOES_NOT_EXIST_ERROR = 142
    ACCOUNT_DOES_NOT_EXIST_ERROR = 143
    ACCOUNT_REMOVE_ERROR = 144
    ACCOUNT_EXISTS_CHECK_ERROR = 145
    VNIC_LOGIN_ERROR = 146
    ACCOUNT_SAVE_ERROR_TPM = 147
    ACCOUNT_SAVE_ERROR_ILO = 148
    GEN_BEFORE_LOGIN_ERROR = 149
    APPID_LIST_ERROR = 150
    INACTIVE_APP_ACCOUNT_TOKEN = 151
    REACTIVATE_APP_ACCOUNT_TOKEN_ERROR = 152


class RdmcError(Exception):
    """Baseclass for all rdmc exceptions"""

    errcode = 1

    def __init__(self, message=None):
        Exception.__init__(self, message)


class ConfigurationFileError(RdmcError):
    """Raised when something is wrong in the config file"""

    errcode = 3


class ProxyConfigFailedError(RdmcError):
    """Raised when ComputeOpsManagement connection fails"""

    pass


class CloudConnectTimeoutError(RdmcError):
    """Raised when ComputeOpsManagement connection times out"""

    pass


class CloudConnectFailedError(RdmcError):
    """Raised when ComputeOpsManagement connection fails"""

    pass


class TfaEnablePreRequisiteError(RdmcError):
    """Raised when pre-requisites not met while enabling TFA"""

    pass


class AlreadyCloudConnectedError(RdmcError):
    """Raised when ComputeOpsManagement is already connected"""

    pass


class CommandNotEnabledError(RdmcError):
    """Raised when user tries to invoke a command that isn't enabled"""

    pass


class iLORisCorruptionError(RdmcError):
    """Raised when user tries to invoke a command that isn't enabled"""

    pass


class ResourceNotReadyError(RdmcError):
    """Raised when user tries to invoke a command that isn't enabled"""

    pass


class UsernamePasswordRequiredError(RdmcError):
    """Raised when username and password are required for local chif login"""

    pass


class PathUnavailableError(Exception):
    """Raised when the requested path is unavailable"""

    pass


class InvalidCommandLineError(RdmcError):
    """Raised when user enter incorrect command line arguments"""

    pass


class NoCurrentSessionEstablished(RdmcError):
    """Raised when user enter incorrect command line arguments"""

    pass


class NoChangesFoundOrMadeError(RdmcError):
    """Raised when no changes were found or made on the commit function"""

    pass


class StandardBlobErrorHandler(RdmcError):
    """Raised when error occured for blob operations"""

    pass


class InvalidCommandLineErrorOPTS(RdmcError):
    """Raised when user enter incorrect command line arguments"""

    pass


class InvalidFileInputError(RdmcError):
    """Raised when user enter an invalid file input"""

    pass


class InvalidFileFormattingError(RdmcError):
    """Raised when user enter incorrect load file formatting"""

    pass


class WindowsUserNotAdmin(RdmcError):
    """Raised when user is not running as admin"""

    pass


class NoContentsFoundForOperationError(RdmcError):
    """Raised when no contents were found for the current operation"""

    pass


class InfoMissingEntriesError(RdmcError):
    """Raised when no valid entries for info were found in the current
    instance"""

    pass


class InvalidOrNothingChangedSettingsError(RdmcError):
    """Raised when something is wrong with the settings"""

    pass


class InvalidPasswordLengthError(RdmcError):
    """Raised when password length is invalid"""

    pass


class InvalidSmartArrayConfigurationError(RdmcError):
    """Raised when no changes were found or made on the commit function"""

    pass


class NoDifferencesFoundError(RdmcError):
    """Raised when no differences are found in the current configuration"""

    pass


class NothingSelectedError(RdmcError):
    """Raised when type selection is reference but none have been provided"""

    pass


class InvalidPropertyError(RdmcError):
    """Raised when one or more properties or attributes are in conflict with current or
    specified configuration"""

    pass


class MultipleServerConfigError(RdmcError):
    """Raised when one or more servers failed to load given configuration"""

    pass


class InvalidMSCfileInputError(RdmcError):
    """Raised when servers input file for load has incorrect parameters"""

    pass


class FirmwareUpdateError(RdmcError):
    """Raised when there is an error while updating firmware"""

    pass


class FailureDuringCommitError(RdmcError):
    """Raised when there is an error during commit"""

    pass


class BootOrderMissingEntriesError(RdmcError):
    """Raised when no entries were found for bios tools"""

    pass


class NicMissingOrConfigurationError(RdmcError):
    """ Raised when no entries are found for given NIC or all NICs are \
     configured or when wrong inputs are presented for NIC entries"""

    pass


class IncompatibleiLOVersionError(RdmcError):
    """Raised when the iLO version is above or below the required \
    version"""

    pass


class IncompatableServerTypeError(RdmcError):
    """Raised when the server type is incompatable with the requested\
    command"""

    pass


class IloLicenseError(RdmcError):
    """Raised when the proper iLO license is not available for a command"""

    pass


class ScepenabledError(RdmcError):
    """Raised when the generation csr or deletion of https cert is issues when scep is enabled"""

    pass


class ResourceExists(RdmcError):
    """Raised when the account to be added already exists"""

    pass


class InvalidCListFileError(RdmcError):
    """Raised when an error occurs while reading the cfilelist \
    within AHS logs"""

    pass


class PartitionMoutingError(RdmcError):
    """Raised when there is error or iLO fails to respond to \
    partition mounting request"""

    pass


class DownloadError(RdmcError):
    """Raised when the component fails to download"""

    pass


class UploadError(RdmcError):
    """Raised when the component fails to download"""

    pass


class FlashUnsupportedByIloError(RdmcError):
    """Raised when the flashing of the component is not supported by iLO"""

    pass


class TimeOutError(RdmcError):
    """Raised when the update service times out"""

    pass


class LibHPsrvMissingError(RdmcError):
    """Raised when unable to obtain the libhpsrv handle"""

    pass


class BirthcertParseError(RdmcError):
    """Raised when unable to parse the birthcert"""

    pass


class InvalidKeyError(RdmcError):
    """Raised when an invalid encryption key is used"""

    pass


class UnableToDecodeError(RdmcError):
    """Raised when the file is unable to be decoded using the given key"""

    pass


class UnabletoFindDriveError(RdmcError):
    """Raised when there is an issue finding required label"""

    pass


class TaskQueueError(RdmcError):
    """Raised when there is an issue with the current order of taskqueue"""

    pass


class DeviceDiscoveryInProgress(RdmcError):
    """Raised when device discovery in progress"""

    pass


class FallbackChifUse(RdmcError):
    """Fallback Chif Use"""

    pass


class InstallsetError(RdmcError):
    """Error while deleting Recovery installset"""

    pass


class GenerateAndSaveAccountError(RdmcError):
    """Raised when errors occurred while generating and saving app account"""

    pass


class NoAppAccountError(RdmcError):
    """Raised when the app account to be deleted does not exist."""

    pass


class RemoveAccountError(RdmcError):
    """Raised when errors occurred while removing app account"""

    pass


class AppAccountExistsError(RdmcError):
    """Raised when errors occurred while removing app account"""

    pass


class ReactivateAppAccountTokenError(RdmcError):
    """Raised when errors occurred while reactivating app account"""

    pass


class InactiveAppAccountTokenError(RdmcError):
    """Raised when inactive app account token"""

    pass


class VnicLoginError(RdmcError):
    """Raised when error occurs while VNIC login"""

    pass


class VnicExistsError(RdmcError):
    """Raised when VNIC is not enabled"""

    pass


class SavinginTPMError(RdmcError):
    """Raised when error occurs while saving app account in TPM"""

    pass


class SavinginiLOError(RdmcError):
    """Raised when error occurs while saving app account in iLO"""

    pass


class GenBeforeLoginError(RdmcError):
    """Raised when error occurs while getting iLO Gen before login"""

    pass


class AppIdListError(RdmcError):
    """Raised when error occurs while retrieving list of apptokens and appaccounts"""

    pass


class UI(object):
    """UI class handles all of our printing etc so we have
    consistency across the project"""

    def __init__(self, verbosity=1):
        self.verbosity = verbosity

    def printer(self, data, flush=True, excp=None, verbose_override=False):
        """Print wrapper for stdout vs fileout"""
        if self.verbosity >= 0 or verbose_override:
            if excp:
                sys.stderr.write(str(data))
            else:
                try:
                    sys.stdout.write(str(data))
                    if flush:
                        sys.stdout.flush()
                except IOError:
                    pass

    def command_not_found(self, cmd):
        """Called when command was not found"""
        self.printer(
            ("\nCommand '%s' not found. Use the help command to " "see a list of available commands\n" % cmd),
            excp=True,
        )
        return ReturnCodes.UI_CLI_COMMAND_NOT_FOUND_EXCEPTION

    def command_not_enabled(self, cmd, excp):
        """Called when command has not been enabled"""
        self.printer(("\nCommand '%s' has not been enabled: %s\n" % (cmd, excp)), excp=excp)

    def invalid_commmand_line(self, excp):
        """Called when user entered invalid command line entries"""
        self.printer(("Error: %s\n" % excp), excp=excp)

    def ilo_ris_corruption(self, excp):
        """Called when user entered invalid command line entries"""
        self.printer(("\nError: %s\n" % excp), excp=excp)

    def standard_blob_error(self, excp):
        """Called when user error encountered with blob"""
        self.printer(("\nError: Blob operation failed with error code %s\n" % excp), excp=excp)

    def invalid_file_formatting(self, excp):
        """Called when file formatting is unrecognizable"""
        self.printer(("\nError: %s\n" % excp), excp=excp)

    def user_not_admin(self):
        """Called when file formatting in unrecognizable"""
        self.printer(
            (
                "\nBoth remote and local mode is accessible when %s "
                "is run as administrator. Only remote mode is available for non-"
                "admin user groups.\n" % versioning.__longname__
            ),
            excp=True,
        )

    def no_contents_found_for_operation(self, excp):
        """Called when no contents were found for the current operation"""
        self.printer(("\nError: %s\n" % excp), excp=True)

    def nothing_selected(self):
        """Called when nothing has been select yet"""
        self.printer(
            "\nNo type currently selected. Please use the"
            " 'types' command to\nget a list of types, or input"
            " your type by using the '--selector' flag.\n",
            excp=True,
        )

    def nothing_selected_filter(self):
        """Called when nothing has been select after a filter set"""
        self.printer("\nNothing was found to match your provided filter.\n", excp=True)

    def nothing_selected_set(self):
        """Called when nothing has been select yet"""
        self.printer("\nNothing is selected or selection is read-only.\n", excp=True)

    def no_differences_found(self, excp):
        """Called when no difference is found in the current configuration"""
        self.printer(("Error: %s\n" % excp), excp=True)

    def multiple_server_config_fail(self, excp):
        """Called when one or more servers failed to load given configuration"""
        self.printer(("Error: %s\n" % excp), excp=True)

    def multiple_server_config_input_file(self, excp):
        """Called when servers input file has incorrect information"""
        self.printer(("Error: %s\n" % excp), excp=True)

    def invalid_credentials(self, timeout):
        """Called user has entered invalid credentials
        :param timeout: timeout given for failed login attempt
        :type timeout: int.
        """
        self.printer("Authenticating to iLO", excp=True)

        timeout = 0
        for _ in range(0, (int(str(timeout)) + 3)):
            time.sleep(2)
            self.printer(".", excp=True)

        self.printer(
            "\nInvalid credentials. Unable to authenticate to iLO. \n"
            "Please ensure to specify correct username and password.\n",
            excp=True,
        )

    def bios_unregistered_error(self):
        """Called when ilo/bios unregistered error occurs"""
        self.printer(
            "\nERROR 100: Bios provider is unregistered. Please"
            " refer to the documentation for details on this issue.\n",
            excp=True,
        )

    def error(self, msg, inner_except=None):
        """Used for general error handling
        :param inner_except: raised exception to be logged
        :type inner_except: exception.
        :param msg: warning message
        :type msg: string.
        """
        if inner_except is not None:
            LOGGER.error(msg, exc_info=True)
        else:
            LOGGER.error(msg)

    def warn(self, msg, inner_except=None):
        """Used for general warning handling
        :param inner_except: raised exception to be logged
        :type inner_except: exception.
        :param msg: warning message
        :type msg: string.
        """
        if inner_except is not None:
            LOGGER.warning(msg, exc_info=True)
        else:
            LOGGER.warning(msg)

    def retries_exhausted_attemps(self):
        """Called when url retries have been exhausted"""
        LOGGER.error("Could not reach URL. Retries have been exhausted.")

    def retries_exhausted_vnic_not_enabled(self):
        """Called when there is no VNIC is Enabled"""
        self.printer("\nError: Could not reach URL, VNIC is not enabled. \n", excp=True)

    def print_out_json(self, content):
        """Print out json content to std.out with sorted keys
        :param content: content to be printed out
        :type content: str.
        """
        # stringify
        content = json.dumps(content, indent=2, cls=redfish.ris.JSONEncoder, sort_keys=True)
        self.printer(content, verbose_override=True)
        self.printer("\n")

    def print_out_json_ordered(self, content):
        """Print out sorted json content to std.out
        :param content: content to be printed out
        :type content: str.
        """
        content = json.dumps(content, indent=2, cls=redfish.ris.JSONEncoder)
        self.printer(content, verbose_override=True)
        self.printer("\n")

    def print_out_human_readable(self, content):
        """Print out human readable content to std.out
        :param content: content to be printed out
        :type content: str.
        """
        self.pretty_human_readable(content, enterloop=True)
        self.printer("\n")

    def pretty_human_readable(self, content, indent=0, start=0, enterloop=False):
        """Convert content to human readable and print out to std.out
        :param content: content to be printed out
        :type content: str.
        :param indent: indent string to be used as seperator
        :type indent: str.
        :param start: used to determine the indent level
        :type start: int.
        """
        space = "\n" + "\t" * indent + " " * start
        if isinstance(content, list):
            for item in content:
                if item is None:
                    continue

                self.pretty_human_readable(item, indent, start)

                if content.index(item) != (len(content) - 1):
                    self.printer(space)
        elif isinstance(content, dict):
            for key, value in content.items():
                if space and not enterloop:
                    self.printer(space)

                enterloop = False
                self.printer((str(key) + "="))
                self.pretty_human_readable(value, indent, (start + len(key) + 2))
        else:
            content = content if isinstance(content, six.string_types) else str(content)

            content = '""' if not content else content
            # Changed to support py3, verify if there is a unicode prit issue.

            self.printer(content)


class Encryption(object):
    """Encryption/Decryption object"""

    @staticmethod
    def check_fips_mode_os():
        """Function to check for the OS fips mode
        :param key: string to encrypt with
        :type key: str.
        :returns: returns True if FIPS mode is active, False otherwise
        """
        fips = False
        if os.name == "nt":
            reg = winreg.ConnectRegistry(None, HKEY_LOCAL_MACHINE)
            try:
                reg = winreg.OpenKey(
                    reg,
                    "System\\CurrentControlSet\\Control\\" "Lsa\\FipsAlgorithmPolicy",
                )
                winreg.QueryInfoKey(reg)
                value, _ = winreg.QueryValueEx(reg, "Enabled")
                if value:
                    fips = True
            except:
                fips = False
        else:
            try:
                fipsfile = open("/proc/sys/crypto/fips_enabled")
                result = fipsfile.readline()
                if int(result) > 0:
                    fipsfile = True
                fipsfile.close()
            except:
                fips = False
        return fips

    @staticmethod
    def check_fips_mode_ssl():
        """Function to check for the SSL fips mode
        Uses custom cpython ssl module API, if available. Otheriwse
        probes using ctypes.cdll APIs.
        :returns: returns True if FIPS mode is active, False otherwise
        """
        import ssl

        if hasattr(ssl, "FIPS_mode"):
            return ssl.FIPS_mode()

        from ctypes import cdll

        libcrypto = cdll.LoadLibrary(ssl._ssl.__file__)
        return libcrypto.FIPS_mode()

    def encrypt_file(self, filetxt, key):
        """encrypt a file given a key
        :param filetxt: content to be encrypted
        :type content: str.
        :param key: string to encrypt with
        :type key: str.
        """
        try:
            filetxt = filetxt.encode()
        except (UnicodeDecodeError, AttributeError):
            pass  # must be encoded already
        try:
            key = key.encode()
        except (UnicodeDecodeError, AttributeError):
            pass  # must be encoded already
        if Encryption.check_fips_mode_os():
            raise CommandNotEnabledError("Encrypting of files is not available" " in FIPS mode.")
        if len(key) not in [16, 24, 32]:
            raise InvalidKeyError("")
        else:
            encryptedfile = pyaes.AESModeOfOperationCTR(key).encrypt(filetxt)

        return encryptedfile

    def decrypt_file(self, filetxt, key):
        """decrypt a file given a key
        :param filetxt: content to be decrypted
        :type content: str.
        :param key: string to decrypt with
        :type key: str.
        :returns: returns the decrypted file
        """
        try:
            filetxt = filetxt.encode()
        except (UnicodeDecodeError, AttributeError):
            pass  # must be encoded already
        try:
            key = key.encode()
        except (UnicodeDecodeError, AttributeError):
            pass  # must be encoded already
        if len(key) not in [16, 24, 32]:
            raise InvalidKeyError("")
        else:
            decryptedfile = pyaes.AESModeOfOperationCTR(key).decrypt(filetxt)
            try:
                json.loads(decryptedfile)
            except:
                raise UnableToDecodeError(
                    "Unable to decrypt the file, make " "sure the key is the same as used in encryption."
                )

        return decryptedfile

    @staticmethod
    def decode_credentials(credential):
        """decode an encoded credential
        :param credential: credential to be decoded
        :type credential: str.
        :returns: returns the decoded credential
        """

        lib = risblobstore2.BlobStore2.gethprestchifhandle()
        credbuff = create_string_buffer(credential.encode("utf-8"))
        retbuff = create_string_buffer(128)

        lib.decode_credentials.argtypes = [c_char_p]

        lib.decode_credentials(credbuff, byref(retbuff))

        risblobstore2.BlobStore2.unloadchifhandle(lib)
        # try:
        #    if isinstance(retbuff.value, bytes):
        #        retbuff.value = retbuff.value.decode('utf-8', 'ignore')
        #    if not retbuff.value:
        #        raise UnableToDecodeError("")
        # except:
        #    raise UnableToDecodeError("Unable to decode credential %s." % credential)

        return retbuff.value

    @staticmethod
    def encode_credentials(credential):
        """encode a credential
        :param credential: credential to be encoded
        :type credential: str.
        :returns: returns the encoded credential
        """

        lib = risblobstore2.BlobStore2.gethprestchifhandle()
        if isinstance(credential, bytes):
            credential = credential.decode("utf-8")
        credbuff = create_string_buffer(credential.encode("utf-8"))

        retbuff = create_string_buffer(128)

        lib.encode_credentials.argtypes = [c_char_p]

        lib.encode_credentials(credbuff, byref(retbuff))

        risblobstore2.BlobStore2.unloadchifhandle(lib)
        try:
            if six.PY2:
                enc_val = retbuff.value.encode("utf-8")
            elif six.PY3:
                enc_val = retbuff.value.decode("utf-8")  # .encode('utf-8')
            if not retbuff.value:
                raise UnableToDecodeError("")
        except Exception:
            raise UnableToDecodeError("Unable to decode credential %s." % credential)

        return enc_val


class TabAndHistoryCompletionClass(Completer):
    """Tab and History Class used by interactive mode"""

    def __init__(self, options):
        self.options = options
        self.toolbar_text = None
        self.last_complete = None

    def get_completions(self, document, complete_event):
        """Function to return the options for autocomplete"""
        word = ""
        self.toolbar_text = ""
        lstoption = self.options
        if document.text:
            tokens = document.text.split()
            # We aren't completing options yet
            tokens = [token for token in tokens if not token.startswith("-")]

            self.last_complete = tokens[-1]
            nestedtokens = self.last_complete.split("/")

            if not document.text.endswith(" "):
                tokens.pop()
                word = document.get_word_under_cursor()
            else:
                nestedtokens = []
            if word == "/":
                word = ""

            if len(tokens) >= 1:
                if tokens[0] == "select":
                    # only first type
                    if len(tokens) >= 2:
                        lstoption = []
                    else:
                        lstoption = self.options.get(tokens[0], {})
                elif tokens[0] in ["get", "list", "info", "set"]:
                    # Match properties
                    nested_data = self.options.get("nestedprop", {})
                    nested_info = self.options.get("nestedinfo", {})
                    for token in nestedtokens:
                        try:
                            nested_data = nested_data[token]
                            if tokens[0] == "get" and isinstance(nested_data, dict):
                                for k in list(nested_data.keys()):
                                    if (
                                        k.lower() in HARDCODEDLIST
                                        or "@odata" in k.lower()
                                        or "@redfish.allowablevalues" in k.lower()
                                    ):
                                        del nested_data[k]
                            if nested_info:
                                if "properties" in nested_info:
                                    nested_info = nested_info["properties"]
                                if "AttributeName" not in nested_info[token]:
                                    nested_info = (
                                        nested_info["properties"][token]
                                        if "properties" in nested_info
                                        else nested_info[token]
                                    )
                                else:
                                    nested_info = nested_info[token]
                        except Exception:
                            break
                    nested_data = list(nested_data.keys()) if isinstance(nested_data, dict) else []
                    lstoption = nested_data

                    # Try to get info for help bar
                    help_text = nested_info.get("HelpText", "")
                    enum_tab = []
                    if "Type" in nested_info and nested_info["Type"].lower() == "enumeration":
                        help_text += "\nPossible Values:\n"
                        for value in nested_info["Value"]:
                            enum_tab.append(value["ValueName"])
                            help_text += six.u(str(value["ValueName"])) + " "

                    if not help_text:
                        try:
                            nested_info = nested_info["properties"]
                        except KeyError:
                            pass
                        help_text = nested_info.get("description", "")
                        if "enum" in nested_info:
                            help_text += "\nPossible Values:\n"
                            for value in nested_info["enum"]:
                                enum_tab.append(value)
                                help_text += six.u(str(value)) + " "
                    if isinstance(help_text, str):
                        help_text = help_text.replace(". ", ".\n")
                    self.toolbar_text = help_text
                    if tokens[0] in ["set"]:
                        lstoption = self.options.get("set")
                else:
                    lstoption = {}
            else:
                for token in tokens:
                    # just match commands
                    lstoption = self.options.get(token, {})

        for opt in lstoption:
            if opt == word:
                self.last_complete = opt
            if opt.startswith(word):
                yield Completion(opt + "", start_position=-len(word))

    def bottom_toolbar(self):
        return self.toolbar_text if self.toolbar_text else None

    def updates_tab_completion_lists(self, options):
        """Function to update tab completion lists
        :param options: options list
        :type options: list.
        """
        # Loop through options passed and add them to them
        # to the current tab options list
        for key, value in options.items():
            self.options[key] = value
