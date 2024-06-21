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
""" Login Command for RDMC """

import getpass
import os
import socket
import redfish.ris

try:
    from rdmc_helper import (
        Encryption,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        PathUnavailableError,
        ReturnCodes,
        UsernamePasswordRequiredError,
    )
except ModuleNotFoundError:
    from ilorest.rdmc_helper import (
        ReturnCodes,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        PathUnavailableError,
        Encryption,
        UsernamePasswordRequiredError,
    )

from redfish.rest.v1 import ServerDownOrUnreachableError


class LoginCommand:
    """Constructor"""

    def __init__(self):
        self.ident = {
            "name": "login",
            "usage": None,
            "description": "To login remotely run using iLO url and iLO credentials"
            "\n\texample: login <iLO url/hostname> -u <iLO username> "
            "-p <iLO password>\n\n\tTo login on a local server run without "
            "arguments\n\texample: login"
            "\n\n\tTo login through VNIC run using --force_vnic and iLO credentials "
            "\n\texample: login --force_vnic -u <iLO username> -p <iLO password>"
            "\n\nLogin using OTP can be done in 2 ways."
            "\n\n\t To login implicitly, use the tag --wait_for_otp."
            "\n\t\texample: login -u <iLO username> -p <iLO password> --wait_for_otp"
            "\n\n\n\t To login explicitly, use the tag -o/--otp and enter OTP after."
            "\n\t\texample: login -u <iLO username> -p <iLO password> -o <iLO OTP>"
            "\n\n\tNOTE: A [URL] can be specified with "
            "an IPv4, IPv6, or hostname address.",
            "summary": "Connects to a server, establishes a secure session," " and discovers data from iLO.",
            "aliases": [],
            "auxcommands": ["LogoutCommand"],
            "cert_data": {},
        }
        self.cmdbase = None
        self.rdmc = None
        self.url = None
        self.username = None
        self.password = None
        self.sessionid = None
        self.biospassword = None
        self.auxcommands = dict()
        self.cert_data = dict()
        self.login_otp = None

    def run(self, line, help_disp=False):
        """wrapper function for main login function

        :param line: command line input
        :type line: string.
        :param help_disp: flag to determine to display or not
        :type help_disp: boolean
        """
        if help_disp:
            self.parser.print_help()
            return ReturnCodes.SUCCESS
        try:
            self.loginfunction(line)

            if ("-h" in line) or ("--help" in line):
                return ReturnCodes.SUCCESS

            if not self.rdmc.app.monolith._visited_urls:
                self.auxcommands["logout"].run("")
                raise PathUnavailableError("The path specified by the --path flag is unavailable.")
        except Exception:
            raise

        # Return code
        return ReturnCodes.SUCCESS

    def perform_login(self, options, skipbuild, user_ca_cert_data):
        self.rdmc.app.login(
            username=self.username,
            password=self.password,
            sessionid=self.sessionid,
            base_url=self.url,
            path=options.path,
            skipbuild=skipbuild,
            includelogs=options.includelogs,
            biospassword=self.biospassword,
            is_redfish=self.rdmc.opts.is_redfish,
            proxy=self.rdmc.opts.proxy,
            user_ca_cert_data=user_ca_cert_data,
            json_out=self.rdmc.json,
            login_otp=self.login_otp,
            log_dir=self.rdmc.log_dir,
        )

    def loginfunction(self, line, skipbuild=None, json_out=False):
        """Main worker function for login class

        :param line: entered command line
        :type line: list.
        :param skipbuild: flag to determine if monolith should be build
        :type skipbuild: boolean.
        :param json_out: flag to determine if json output neededd
        :type skipbuild: boolean.
        """
        try:
            (options, args) = self.rdmc.rdmc_parse_arglist(self, line)
        except (InvalidCommandLineErrorOPTS, SystemExit):
            if ("-h" in line) or ("--help" in line):
                return ReturnCodes.SUCCESS
            else:
                raise InvalidCommandLineError("Invalid command line arguments")

        self.loginvalidation(options, args)

        # if proxy server provided in command line as --useproxy, it will be used,
        # otherwise it will the environment variable setting.
        # else proxy will be set as None.
        if self.rdmc.opts.proxy:
            _ = self.rdmc.opts.proxy
        elif "https_proxy" in os.environ and os.environ["https_proxy"]:
            _ = os.environ["https_proxy"]
        elif "http_proxy" in os.environ and os.environ["http_proxy"]:
            _ = os.environ["http_proxy"]
        else:
            _ = self.rdmc.config.proxy

        no_bundle = False

        if getattr(options, "ca_cert_bundle", False):
            user_ca_cert_data = {"ca_certs": options.ca_cert_bundle}
        else:
            user_ca_cert_data = {}
        if getattr(options, "user_certificate", False):
            no_bundle = True
            user_ca_cert_data.update({"cert_file": options.user_certificate})
        if getattr(options, "user_root_ca_key", False):
            no_bundle = True
            user_ca_cert_data.update({"key_file": options.user_root_ca_key})
        if getattr(options, "user_root_ca_password", False):
            no_bundle = True
            user_ca_cert_data.update({"key_password": options.user_root_ca_password})

        if not no_bundle:
            if hasattr(user_ca_cert_data, "ca_certs"):
                user_ca_cert_data.pop("ca_certs")

        try:
            if getattr(options, "force_vnic", False):
                self.rdmc.ui.printer("\nAttempt to login with Vnic...\n")
            try:
                sock = socket.create_connection((args[0], 443))
                if sock:
                    sock.close
            except:
                pass

            self.sessionid = options.sessionid
            self.login_otp = options.login_otp

            if "blobstore" in self.url and (options.waitforOTP or options.login_otp):
                options.waitforOTP = None
                options.login_otp = None
                self.rdmc.ui.printer(
                    "Warning: For local inband mode, TFA is not supported, options --wait_for_otp "
                    "and --otp will be ignored\n"
                )

            if options.waitforOTP:
                try:
                    self.perform_login(options, skipbuild, user_ca_cert_data)
                except redfish.rest.connections.OneTimePasscodeError:
                    self.rdmc.ui.printer("One Time Passcode Sent to registered email.\n")
                    ans = input("Enter OTP: ")
                    self.login_otp = ans
                    self.perform_login(options, skipbuild, user_ca_cert_data)
            else:
                self.perform_login(options, skipbuild, user_ca_cert_data)
        except ServerDownOrUnreachableError as excp:
            self.rdmc.ui.printer("The following error occurred during login: '%s'\n" % str(excp.__class__.__name__))

        self.username = None
        self.password = None

        # Warning for cache enabled, since we save session in plain text
        if not self.rdmc.encoding:
            self.rdmc.ui.warn("Cache is activated. Session keys are stored in plaintext.")

        if self.rdmc.opts.debug:
            self.rdmc.ui.warn("Logger is activated. Logging is stored in plaintext.")

        if options.selector:
            try:
                self.rdmc.app.select(selector=options.selector)

                if self.rdmc.opts.verbose:
                    self.rdmc.ui.printer(("Selected option: '%s'\n" % options.selector))
            except Exception as excp:
                raise redfish.ris.InstanceNotFoundError(excp)

    def loginvalidation(self, options, args):
        """Login helper function for login validations

        :param options: command line options
        :type options: list.
        :param args: command line arguments
        :type args: list.
        """
        # Fill user name/password from config file
        if not options.user:
            options.user = self.rdmc.config.username
        if not options.password:
            options.password = self.rdmc.config.password
        if not hasattr(options, "user_certificate"):
            options.user_certificate = self.rdmc.config.user_cert
        if not hasattr(options, "user_root_ca_key"):
            options.user_root_ca_key = self.rdmc.config.user_root_ca_key
        if not hasattr(options, "user_root_ca_password"):
            options.user_root_ca_password = self.rdmc.config.user_root_ca_password

        if (
            options.user
            and not options.password
            and (
                not hasattr(options, "user_certificate")
                or not hasattr(options, "user_root_ca_key")
                or hasattr(options, "user_root_ca_password")
            )
        ):
            # Option for interactive entry of password
            tempinput = getpass.getpass().rstrip()
            if tempinput:
                options.password = tempinput
            else:
                raise InvalidCommandLineError("Empty or invalid password was entered.")

        if options.user:
            self.username = options.user

        if options.password:
            self.password = options.password

        if options.encode:
            self.username = Encryption.decode_credentials(self.username).decode("utf-8")
            self.password = Encryption.decode_credentials(self.password).decode("utf-8")

        if options.biospassword:
            self.biospassword = options.biospassword

        # Assignment of url in case no url is entered
        if getattr(options, "force_vnic", False):
            if not (getattr(options, "ca_cert_bundle", False) or getattr(options, "user_certificate", False)):
                if not (self.username and self.password) and not options.sessionid:
                    raise UsernamePasswordRequiredError("Please provide credentials to login with VNIC")
            self.url = "https://16.1.15.1"
        else:
            self.url = "blobstore://."

        if args:
            # Any argument should be treated as an URL
            self.url = args[0]

            # Verify that URL is properly formatted for https://
            if "https://" not in self.url:
                self.url = "https://" + self.url

            if not (
                hasattr(options, "user_certificate")
                or hasattr(options, "user_root_ca_key")
                or hasattr(options, "user_root_ca_password")
            ):
                if not (options.username and options.password):
                    raise InvalidCommandLineError("Empty username or password was entered.")
        else:
            # Check to see if there is a URL in config file
            if self.rdmc.config.url:
                self.url = self.rdmc.config.url

    def definearguments(self, customparser):
        """Wrapper function for new command main function

        :param customparser: command line input
        :type customparser: parser.
        """

        def remove_argument(parser, arg):
            for action in parser._actions:
                opts = action.option_strings
                if (opts and opts[0] == arg) or action.dest == arg:
                    parser._remove_action(action)
                    break

            for action in parser._action_groups:
                for group_action in action._group_actions:
                    opts = group_action.option_strings
                    if (opts and opts[0] == arg) or group_action.dest == arg:
                        action._group_actions.remove(group_action)
                        return

        if not customparser:
            return

        customparser.add_argument(
            "--wait_for_otp",
            dest="waitforOTP",
            help="Optionally include this flag to implicitly wait for OTP.",
            action="store_true",
            default=None,
        )
        self.cmdbase.add_login_arguments_group(customparser)
        remove_argument(customparser, "url")
        customparser.add_argument(
            "--selector",
            dest="selector",
            help="Optionally include this flag to select a type to run"
            " the current command on. Use this flag when you wish to"
            " select a type without entering another command, or if you"
            " wish to work with a type that is different from the one"
            " you currently have selected.",
            default=None,
        )
