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
"""This is the helper module for RDMC"""

# ---------Imports---------
from __future__ import unicode_literals

import json
import logging
import os
import sys
import time
from collections import OrderedDict
from ctypes import byref, c_char_p, create_string_buffer

import pyaes
import six
from prompt_toolkit.completion import Completer, Completion

import redfish.hpilo.risblobstore2 as risblobstore2
import redfish.ris

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


# ---------Debug logger---------
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


class InfoFilter(logging.Filter):
    def filter(self, rec):
        return rec.levelno in (logging.DEBUG, logging.INFO, logging.WARN)


LOGGER = logging.getLogger()
# default logging level setting
LOGGER.setLevel(logging.ERROR)
# loggin format
LFMT = logging.Formatter("%(levelname)s\t: %(message)s")
# when success, all logs should be in stdout. When error, it should goto stderr
# Initialize StreamHandler for Stdout and Stderr logs
LOUT = logging.StreamHandler(sys.stdout)
LERR = logging.StreamHandler(sys.stderr)
# set formatter
LERR.setFormatter(LFMT)
# default stderr level setting
LERR.setLevel(logging.ERROR)
# add logger handle
LOGGER.addHandler(LERR)
LOUT.setFormatter(LFMT)
# default stdout level setting
LOUT.setLevel(logging.WARN)
LOUT.addFilter(InfoFilter())
# add logger handle
LOGGER.addHandler(LOUT)


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
    UPLOAD_POWEROFF_ERROR = 108

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

class UploadPowerOffError(RdmcError):
    """Raised when the server power is On while uploading B- component"""

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


class InvalidSmartArrayConfigurationError(RdmcError):
    """Raised for an invalid configuration of a smart array controller and/or disk configuration"""

    pass


class FallbackChifUse(RdmcError):
    """Fallback Chif Use"""

    pass


class InstallsetError(RdmcError):
    """Error while deleting Recovery installset"""

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
        self.printer("Validating...", excp=True)

        for _ in range(0, (int(str(timeout)) + 10)):
            time.sleep(1)
            self.printer(".", excp=True)

        self.printer(
            "\nError: Could not authenticate. Invalid " "credentials, or bad username/password.\n",
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
