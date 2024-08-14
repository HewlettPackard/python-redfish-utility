###
# Copyright 2021-2023 Hewlett Packard Enterprise, Inc. All rights reserved.
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
""" TwoFactorAuthentication Command for rdmc """

from argparse import RawDescriptionHelpFormatter

from redfish.ris import IdTokenError
from redfish.ris.rmc_helper import IloResponseError

try:
    from rdmc_helper import (
        IloLicenseError,
        IncompatibleiLOVersionError,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        NoCurrentSessionEstablished,
        ReturnCodes,
        TfaEnablePreRequisiteError,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        IloLicenseError,
        IncompatibleiLOVersionError,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        NoCurrentSessionEstablished,
        ReturnCodes,
        TfaEnablePreRequisiteError,
    )

from redfish.ris.ris import SessionExpired


class SetTwoFactorAuthenticationCommand:
    """Main new command template class"""

    def __init__(self):
        self.ident = {
            "name": "settwofactorauthentication",
            "usage": "settwofactorauthentication\n\n",
            "description": "Run to enable ,disable ,get status or  setup smtp settings for Two factor "
            "authentication\n\t"
            "Example:\n\tsettwofactorauthentication enable or \n\t"
            "settwofactorauthentication disable \n\t"
            "settwofactorauthentication status or \n\t"
            "settwofactorauthentication status -j\n"
            "settwofactorauthentication smtp --smtpfortfaenabled true --alertmailsenderdomain 'test@hpe.com' "
            "--alertmailsmtpserver 'smtp3.hpe.com' --alertmailsmtpport 587\n",
            "summary": "Enables the server to use Two factor authentication, monitored",
            "aliases": [],
            "auxcommands": [],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def twofactorauth(self, options):
        """two authentication function

        :param enable or disable
        """

        # pre requisite checks

        path = self.rdmc.app.typepath.defs.managerpath + "NetworkProtocol"
        resp = self.rdmc.app.get_handler(path, service=False, silent=True)

        status = resp.dict["Oem"]["Hpe"]["SMTPForTFAEnabled"]
        if not status:
            self.rdmc.ui.error("SMTP for TFA is not enabled\n")
            raise TfaEnablePreRequisiteError(
                "\nTo be able to enable or disable TFA\nKindly enable and set the SMTP details prior to enabling TFA "
                "for the server . You can use our command as given below for enabling  smtp for tfa \n\n"
                "SetTwoFactorAuthentication smtp --smtpfortfaenabled true --alertmailsenderdomain 'testuser@test.com' "
                "--alertmailsmtpserver 'smtp.server.com' \n"
            )

        results = self.rdmc.app.select(selector="AccountService.", path_refresh=True)[0].dict
        path = results[self.rdmc.app.typepath.defs.hrefstring]

        # check whether default schema is selected authentication tyep
        resp = self.rdmc.app.get_handler(path, service=False, silent=True)
        if not resp.dict["LDAP"]["ServiceEnabled"]:
            self.rdmc.ui.error("Ldap service is not enabled\n")
            raise TfaEnablePreRequisiteError(
                "\nTo be able to enable or disable TFA\nKindly enable LDAP Directory Authentication to use Directory "
                "Default Schema. Same can be set using below command\n\ndirectory ldap enable "
                "--authentication=DefaultSchema\n"
            )

        body = dict()
        if options.command.lower() == "enable":
            serviceEnabled = "Enabled"
        else:
            serviceEnabled = "Disabled"
        body.update({"Oem": {"Hpe": {"TwoFactorAuth": serviceEnabled}}})

        try:
            self.rdmc.app.patch_handler(path, body)
            return ReturnCodes.SUCCESS
        except IloLicenseError:
            self.rdmc.ui.error("Error Occured while enable or disable operation for TFA")
            return ReturnCodes.ILO_LICENSE_ERROR
        except IdTokenError:
            self.rdmc.ui.error("Insufficient Privilege to enable or disable TFA ")
            return ReturnCodes.RIS_MISSING_ID_TOKEN
        except IloResponseError:
            self.rdmc.ui.error("Provided values are invalid , iLO threw error")
            return ReturnCodes.RIS_ILO_RESPONSE_ERROR

    def twofactorauth_smtp(self, options):
        """two authentication smtp setup function

        :param smtpfortfaenabled : true\false
        :type smtpfortfaenabled: str.
        """
        path = self.rdmc.app.typepath.defs.managerpath + "NetworkProtocol"
        resp_get = self.rdmc.app.get_handler(path, service=False, silent=True)
        body = dict()
        range1 = range(1, 65536, 1)
        if options.SMTPPort is not None:
            if options.SMTPPort in range1:
                SMTPPort = options.SMTPPort
            else:
                raise InvalidCommandLineError("Enter correct server port value in the range 1 to 65535")
        else:
            SMTPPort = 25

        if options.SMTPForTFA[0].lower() == "true":
            SMTPForTFAEnabled = True
        else:
            SMTPForTFAEnabled = False

        if options.SenderDomain is None:
            if resp_get.dict["Oem"]["Hpe"]["AlertMailSenderDomain"] is not None:
                SenderDomain = resp_get.dict["Oem"]["Hpe"]["AlertMailSenderDomain"]
            else:
                SenderDomain = ""
        else:
            SenderDomain = options.SenderDomain[0]

        if options.SMTPServer is None:
            if resp_get.dict["Oem"]["Hpe"]["AlertMailSMTPServer"] is not None:
                SMTPServer = resp_get.dict["Oem"]["Hpe"]["AlertMailSMTPServer"]
            else:
                SMTPServer = ""
        else:
            SMTPServer = options.SMTPServer[0]

        body.update(
            {
                "Oem": {
                    "Hpe": {
                        "SMTPForTFAEnabled": SMTPForTFAEnabled,
                        "AlertMailSenderDomain": SenderDomain,
                        "AlertMailSMTPServer": SMTPServer,
                        "AlertMailSMTPPort": SMTPPort,
                    }
                }
            }
        )
        try:
            self.rdmc.app.patch_handler(path, body)
            return ReturnCodes.SUCCESS

        except IloResponseError:
            self.rdmc.ui.error("Provided values are invalid , iLO threw error")
            return ReturnCodes.RIS_ILO_RESPONSE_ERROR
        except IloLicenseError:
            self.rdmc.ui.error("Error Occured while setting smtp settings of TFA ")
            return ReturnCodes.ILO_LICENSE_ERROR
        except IdTokenError:
            self.rdmc.ui.error("Insufficient Privilege to setting smtp settings of TFA ")
            return ReturnCodes.RIS_MISSING_ID_TOKEN

    def twofactorauth_status(self, json=False):
        """two authentication status function

        :param json: json
        :type json: bool
        """
        results = self.rdmc.app.select(selector="AccountService.", path_refresh=True)[0].dict
        path = results[self.rdmc.app.typepath.defs.hrefstring]
        resp = self.rdmc.app.get_handler(path, service=False, silent=True)
        if resp.status != 200:
            self.rdmc.ui.error("session seems to be expired\n")
            raise SessionExpired("Invalid session. Please logout and log back in or include credentials.")
        tfa_info = resp.dict["Oem"]["Hpe"]
        output = "------------------------------------------------\n"
        output += "TFA Status : %s\n" % (tfa_info["TwoFactorAuth"])
        if not json:
            self.rdmc.ui.printer(output, verbose_override=True)
        else:
            self.rdmc.ui.printer("\n--- TFA status ---\n")
            self.rdmc.ui.print_out_json(tfa_info)

        path = self.rdmc.app.typepath.defs.managerpath + "NetworkProtocol"
        resp = self.rdmc.app.get_handler(path, service=False, silent=True)
        if resp.status != 200:
            raise SessionExpired("Invalid session. Please logout and log back in or include credentials.")
        smtp_info = resp.dict["Oem"]["Hpe"]
        output = "\n------------------------------------------------\n"
        output += "SMTP for TFA Status : %s\n" % (smtp_info["SMTPForTFAEnabled"])
        if not json:
            self.rdmc.ui.printer(output, verbose_override=True)
        else:
            self.rdmc.ui.printer("\n--- SMTP for TFA status ---\n")
            self.rdmc.ui.print_out_json(smtp_info)

        return ReturnCodes.SUCCESS

    def run(self, line, help_disp=False):
        """Wrapper function for two factor authentication main function

        :param line: command line input
        :type line: string.
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
            (options, _) = self.rdmc.rdmc_parse_arglist(self, line)
        except (InvalidCommandLineErrorOPTS, SystemExit):
            if ("-h" in line) or ("--help" in line):
                return ReturnCodes.SUCCESS
            else:
                raise InvalidCommandLineErrorOPTS("")

        self.cmdbase.login_select_validation(self, options)
        if not self.rdmc.app.redfishinst:
            raise NoCurrentSessionEstablished("Please login to iLO and retry the command")

        ilo_ver = self.rdmc.app.getiloversion()
        if ilo_ver < 5.290 or (ilo_ver < 6.150 and ilo_ver > 5.999):
            raise IncompatibleiLOVersionError(
                "TFA Feature is only available with iLO 5 version 2.90 or higher and iLO 6 version 1.50 or higher.\n"
            )

        # validation checks
        self.twofactorauthenticationvalidation(options)
        if options.command:
            if options.command.lower() == "enable":
                returncode = self.twofactorauth(options)
            elif options.command.lower() == "disable":
                returncode = self.twofactorauth(options)
            elif options.command.lower() == "smtp":
                returncode = self.twofactorauth_smtp(options)
            elif options.command.lower() == "status":
                if options.json:
                    returncode = self.twofactorauth_status(json=True)
                else:
                    returncode = self.twofactorauth_status()
            else:
                raise InvalidCommandLineError("%s is not a valid option for this " "command." % str(options.command))
        else:
            raise InvalidCommandLineError(
                "Please provide either enable, disable , status or smtp as additional subcommand. "
                "For help or usage related information, use -h or --help"
            )
        # logout routine
        self.cmdbase.logout_routine(self, options)
        # Return code
        return returncode

    def twofactorauthenticationvalidation(self, options):
        """new command method validation function"""
        self.cmdbase.login_select_validation(self, options)

    def definearguments(self, customparser):
        """Wrapper function for new command main function

        :param customparser: command line input
        :type customparser: parser.
        """
        if not customparser:
            return

        self.cmdbase.add_login_arguments_group(customparser)
        subcommand_parser = customparser.add_subparsers(dest="command")
        enable_help = "To enable two factor authentication\n"
        # connect sub-parser
        enable_parser = subcommand_parser.add_parser(
            "enable",
            help=enable_help,
            description=enable_help + "\n\tExample:\n\tsettwofactorauthentication enable ",
            formatter_class=RawDescriptionHelpFormatter,
        )

        self.cmdbase.add_login_arguments_group(enable_parser)

        status_help = "To check the settwofactorauthentication status\n"
        status_parser = subcommand_parser.add_parser(
            "status",
            help=status_help,
            description=status_help + "\n\tExample:\n\tsettwofactorauthentication status or "
            "\n\tsettwofactorauthentication status -j",
            formatter_class=RawDescriptionHelpFormatter,
        )
        status_parser.add_argument(
            "-j",
            "--json",
            dest="json",
            help="to print in json format",
            action="store_true",
            default=False,
        )
        self.cmdbase.add_login_arguments_group(status_parser)

        disable_help = "To disable the two factor authentication\n"
        disable_parser = subcommand_parser.add_parser(
            "disable",
            help=disable_help,
            description=disable_help + "\n\tExample:\n\tsettwofactorauthentication disable",
            formatter_class=RawDescriptionHelpFormatter,
        )
        self.cmdbase.add_login_arguments_group(disable_parser)

        emailconfig_help = "To set the smtp setting for settwofactorauthentication\n"
        emailconfig_parser = subcommand_parser.add_parser(
            "smtp",
            help=emailconfig_help,
            description=emailconfig_help
            + "\n\tExample:\n\tsettwofactorauthentication smtp --smtpfortfaenabled true --alertmailsenderdomain "
            "'test@hpe.com' --alertmailsmtpserver 'smtp3.hpe.com' --alertmailsmtpport 587 ",
            formatter_class=RawDescriptionHelpFormatter,
        )
        emailconfig_parser.add_argument(
            "--smtpfortfaenabled",
            dest="SMTPForTFA",
            help="smtp service enable , supply either true or false as input. "
            "If true then remaining inputs cant be null or empty",
            action="append",
            default=None,
        )
        emailconfig_parser.add_argument(
            "--alertmailsenderdomain",
            dest="SenderDomain",
            action="append",
            help="smtp user name , supply a valid aduser for this field",
            default=None,
        )
        emailconfig_parser.add_argument(
            "--alertmailsmtpserver",
            dest="SMTPServer",
            action="append",
            help="smtp server , supply a valid smtp server for this parameter",
            default=None,
        )

        emailconfig_parser.add_argument(
            "--alertmailsmtpport",
            dest="SMTPPort",
            type=int,
            help="smtp port , supply a valid smtp port for this parameter, default is 25",
            default=25,
        )

        self.cmdbase.add_login_arguments_group(emailconfig_parser)
