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

import os
import sys
from argparse import (
    SUPPRESS,
    Action,
    ArgumentParser,
    RawDescriptionHelpFormatter,
    _ArgumentGroup,
)
from builtins import bytes, int, object, str, super

from redfish.ris import NothingSelectedError

try:
    import cliutils
except ImportError:
    from ilorest import cliutils

try:
    import versioning
except ImportError:
    from ilorest import versioning
try:
    import rdmc_helper
except ImportError:
    from ilorest import rdmc_helper

try:
    from rdmc_helper import InvalidCommandLineErrorOPTS
except ImportError:
    from ilorest.rdmc_helper import InvalidCommandLineErrorOPTS


# from extensions.COMMANDS import LoginCommand, SelectCommand

# ---------End of imports---------


class _Verbosity(Action):
    def __init__(self, option_strings, dest, nargs, **kwargs):
        super(_Verbosity, self).__init__(option_strings, dest, nargs, **kwargs)

    def __call__(self, parser, namespace, values, option_strings):
        try:
            if values:
                tmp = next(iter(values))
                if tmp.isdigit():
                    namespace.verbose = int(tmp)
                else:
                    namespace.verbose = len(tmp) + 1
                return
            namespace.verbose = 1
        except:
            raise InvalidCommandLineErrorOPTS("Invalid verbosity selection ('-v').")


class CommandBase(object):
    """Abstract base class for all Command objects.

    This class is used to build complex command line programs
    """

    def __init__(self, name, usage, summary, aliases=None, argparser=None):
        self.name = name
        self.summary = summary
        self.aliases = aliases
        self.config_required = True  # does the command access config data

        if argparser is None:
            self.parser = ArgumentParser()
        else:
            self.parser = argparser

        self.parser.usage = usage
        # TODO: See if we can remove this or stop it from opening a subprocess all the time
        # self._cli = cliutils.CLI()

    def run(self, line, help_disp=False):
        """Called to actually perform the work.

        Override this method in your derived class.  This is where your program
        actually does work.
        """
        pass


class RdmcCommandBase(CommandBase):
    """Base class for rdmc commands which includes some common helper
    methods.
    """

    def __init__(self, name, usage, summary, aliases, argparser=None, **kwargs):
        """Constructor"""
        CommandBase.__init__(
            self, name=name, usage=usage, summary=summary, aliases=aliases, argparser=argparser, **kwargs
        )
        self.json = False
        self.cache = False
        self.nologo = False
        self.toolbar = False

    def login_validation(self, cmdinstance, options, skipbuild=False):
        """Combined validation function to login and select with other commands. Not for use with
        login or select commands themselves. Make sure your command imports options from
        add_login_arguments_group or there will be errors.

        :param cmdinstance: the command object instance
        :type cmdinstance: list.
        :param options: command line options
        :type options: list.
        :param skipbuild: flag to only login and skip monolith build
        :type skipbuild: bool.
        """

        logobj = cmdinstance.rdmc.load_command(cmdinstance.rdmc.search_commands("LoginCommand"))
        inputline = list()
        client = None
        loggedin = False

        if hasattr(options, "json") and cmdinstance.rdmc.config.format.lower() == "json":
            options.json = True

        try:
            client = cmdinstance.rdmc.app.current_client
        except:
            if options.user or options.password or options.url or options.force_vnic:
                if options.url:
                    inputline.extend([options.url])
                if options.user:
                    if options.encode:
                        options.user = rdmc_helper.Encryption.decode_credentials(options.user)
                        if isinstance(options.user, bytes):
                            options.user = options.user.decode("utf-8")
                    inputline.extend(["-u", options.user])
                if options.password:
                    if options.encode:
                        options.password = rdmc_helper.Encryption.decode_credentials(options.password)
                        if isinstance(options.password, bytes):
                            options.password = options.password.decode("utf-8")
                    inputline.extend(["-p", options.password])
                if options.force_vnic:
                    inputline.extend(["--force_vnic"])
                if getattr(options, "https_cert", False):
                    inputline.extend(["--https", options.https_cert])
                if getattr(options, "user_certificate", False):
                    inputline.extend(["--usercert", options.user_certificate])
                if getattr(options, "user_root_ca_key", False):
                    inputline.extend(["--userkey", options.user_root_ca_key])
                if getattr(options, "user_root_ca_password", False):
                    inputline.extend(["--userpassphrase", options.user_root_ca_password])
            else:
                if cmdinstance.rdmc.config.url:
                    inputline.extend([cmdinstance.rdmc.config.url])
                if cmdinstance.rdmc.config.username:
                    inputline.extend(["-u", cmdinstance.rdmc.config.username])
                if cmdinstance.rdmc.config.password:
                    inputline.extend(["-p", cmdinstance.rdmc.config.password])
                if cmdinstance.rdmc.config.ssl_cert:
                    inputline.extend(["--https", cmdinstance.rdmc.config.ssl_cert])
                if getattr(options, "user_certificate", False):
                    inputline.extend(["--usercert", options.user_certificate])
                if getattr(options, "user_root_ca_key", False):
                    inputline.extend(["--userkey", options.user_root_ca_key])
                if getattr(options, "user_root_ca_password", False):
                    inputline.extend(["--userpassphrase", options.user_root_ca_password])
            if options.includelogs:
                inputline.extend(["--includelogs"])
            if options.path:
                inputline.extend(["--path", options.path])

            if getattr(options, "biospassword", False):
                inputline.extend(["--biospassword", options.biospassword])
            if getattr(options, "sessionid", False):
                inputline.extend(["--sessionid", options.sessionid])

            logobj.loginfunction(inputline, skipbuild=skipbuild)
            loggedin = True

        if not (loggedin or client or options.url or cmdinstance.rdmc.app.typepath.url):
            message = "Local login initiated...\n"
            if cmdinstance.rdmc.opts.verbose:
                sys.stdout.write(message)
            else:
                rdmc_helper.LOGGER.info(message)

        if not (loggedin or client):
            logobj.loginfunction(inputline, skipbuild=skipbuild)

    def login_select_validation(self, cmdinstance, options, skipbuild=False):
        """Combined validation function to login and select with other commands. Not for use with
        login or select commands themselves. Make sure your command imports options from
        add_login_arguments_group or there will be errors.

        :param cmdinstance: the command object instance
        :type cmdinstance: list.
        :param options: command line options
        :type options: list.
        :param skipbuild: flag to only login and skip monolith build
        :type skipbuild: bool.
        """
        inputline = list()

        self.login_validation(cmdinstance, options, skipbuild=skipbuild)
        logobj = cmdinstance.rdmc.load_command(cmdinstance.rdmc.search_commands("LoginCommand"))
        selobj = cmdinstance.rdmc.load_command(cmdinstance.rdmc.search_commands("SelectCommand"))
        if hasattr(options, "selector") and options.selector:
            if inputline:
                inputline.extend(["--selector", options.selector])
                logobj.loginfunction(inputline)
            else:
                if getattr(options, "ref", False):
                    inputline.extend(["--refresh"])

                inputline.extend([options.selector])
                selobj.selectfunction(inputline)
        elif hasattr(options, "selector"):
            try:
                inputline = list()
                selector = cmdinstance.rdmc.app.selector

                if hasattr(options, "ref") and options.ref:
                    inputline.extend(["--refresh"])

                if selector:
                    inputline.extend([selector])
                    selobj.selectfunction(inputline)
            except NothingSelectedError:
                raise NothingSelectedError

    def logout_routine(self, cmdinstance, options):
        """Routine to logout of a server automatically at the completion of a command.

        :param commandinstance: the command object instance
        :type commandinstance: list.
        :param options: command line options
        :type options: list.
        """

        logoutobj = cmdinstance.rdmc.load_command(cmdinstance.rdmc.search_commands("LogoutCommand"))

        if getattr(options, "logout", False):
            logoutobj.run("")

    def add_login_arguments_group(self, parser):
        """Adds login arguments to the passed parser

        :param parser: The parser to add the login option group to
        :type parser: ArgumentParser
        """
        group = parser.add_argument_group("LOGIN OPTIONS", "Options for logging in to a system.")
        group.add_argument("--url", dest="url", help="Use the provided iLO URL to login.", default=None)
        group.add_argument(
            "--sessionid",
            dest="sessionid",
            help="Use the provided sessionid to login.",
            default=None,
        )
        group.add_argument(
            "-u",
            "--user",
            dest="user",
            help="""If you are not logged in yet, including this flag along with the
password and URL flags can be used to login to a server in the same command.""",
            default=None,
        )
        group.add_argument(
            "-p",
            "--password",
            dest="password",
            help="""Use the provided iLO password to log in.""",
            default=None,
        )
        group.add_argument(
            "-o",
            "--otp",
            dest="login_otp",
            help="""Use the provided iLO OTP to log in.""",
            default=None,
        )
        group.add_argument(
            "--biospassword",
            dest="biospassword",
            help="""Select this flag to input a BIOS password. Include this
flag if second-level BIOS authentication is needed for the command to execute.
This option is only used on Gen 9 systems.""",
            default=None,
        )
        group.add_argument(
            "--https",
            dest="https_cert",
            help="""Use the provided CA bundle or SSL certificate with your login to
connect securely to the system in remote mode. This flag has no effect in local mode.""",
            default=None,
        )
        group.add_argument(
            "--usercert",
            dest="user_certificate",
            type=str,
            help="""Specify a user certificate file path for certificate based authentication
with iLO.\n**NOTE**: Inclusion of this argument will force certficate based
authentication. A root user certificate authority key or bundle will be required.""",
            default=None,
        )
        group.add_argument(
            "--userkey",
            dest="user_root_ca_key",
            type=str,
            help="""Specify a user root ca key file path for certificate based certificate
authentication with iLO. **NOTE 1**: Inclusion of this argument will force certficate based
authentication. A root user certificate authority key or bundle will be required.
**NOTE 2**: Inclusion of this argument will force certificate based authentication.
A user certificate will be required.
**NOTE 3**: A user will be prompted for a password if the root certificate authority key
is encrypted and \'-certpass/--userrootcapassword\' is omitted.""",
            default=None,
        )
        group.add_argument(
            "--userpassphrase",
            dest="user_root_ca_password",
            type=str,
            help="""Optionally specify a user root ca key file password for encrypted
user root certificate authority keys. **NOTE 1**: Inclusion of this argument will force
certficate based authentication. A root user certificate authority key or
bundle will be required. **NOTE 2**: The user will be prompted for a password
if the user root certificate authority key requires a password""",
            default=None,
        )
        # group.add_argument(
        #    '--certbundle',
        #    dest='ca_cert_bundle',
        #    type=str,
        #    help="""Specify a file path for the certificate authority bundle location
        # (local repository for certificate collection) **NOTE**: Providing a custom certificate
        # or root CA key will override the use of certificate bundles""",
        #            default=None)
        group.add_argument(
            "-e",
            "--enc",
            dest="encode",
            action="store_true",
            help=SUPPRESS,
            default=False,
        )
        group.add_argument(
            "--includelogs",
            dest="includelogs",
            action="store_true",
            help="Optionally include logs in the data retrieval process.",
            default=False,
        )
        group.add_argument(
            "--path",
            dest="path",
            help="""Optionally set a starting point for data collection during login.
If you do not specify a starting point, the default path will be /redfish/v1/.
Note: The path flag can only be specified at the time of login.
Warning: Only for advanced users, and generally not needed for normal operations.""",
            default=None,
        )
        group.add_argument(
            "--force_vnic",
            dest="force_vnic",
            action="store_true",
            help="Force login through iLO Virtual NIC. **NOTE** " "iLO 5 required",
            default=False,
        )
        group.add_argument(
            "--logout",
            dest="logout",
            action="store_true",
            help="Logout after the completion of the command.",
            default=None,
        )


class RdmcOptionParser(ArgumentParser):
    """Constructor"""

    def __init__(self):
        super().__init__(
            usage="%s [GLOBAL OPTIONS] [COMMAND] [COMMAND ARGUMENTS] " "[COMMAND OPTIONS]" % versioning.__shortname__,
            description="iLOrest is a command-line or interactive interface that allows users "
            "to manage Hewlett Packard Enterprise products that take advantage"
            " of RESTful APIs.\n\nIn order to view or manage a system you must"
            " first login. You can login using the login command or during "
            "execution of any other command.\nFrom here you can run any other "
            "commands. To learn more about specific commands, run iLOrest "
            "COMMAND -h.",
            epilog="Examples:\n\nThe following is the standard flow of command"
            "s to view system data.\n\tThe first example is each command "
            "run individually: \n\n\tilorest login\n\tilorest select Bios.\n\t"
            "ilorest get\n\n\tThe second is the list of all of the commands "
            "run at once. First locally, then remotely.\n\tilorest get "
            "--select Bios.\n\tilorest get --select Bios. --url <iLO IP> -u"
            " <iLO Username> -p <iLO Password>",
            formatter_class=RawDescriptionHelpFormatter,
        )
        globalgroup = _ArgumentGroup(self, "GLOBAL OPTIONS")

        self.add_argument(
            "--config",
            dest="config",
            help="Use the provided configuration file instead of the default one.",
            metavar="FILE",
        )

        config_dir_default = os.path.join(cliutils.get_user_config_dir(), ".%s" % versioning.__shortname__)
        self.add_argument(
            "--cache-dir",
            dest="config_dir",
            default=config_dir_default,
            help="Use the provided directory as the location to cache data"
            " (default location: %s)" % config_dir_default,
            metavar="PATH",
        )
        self.add_argument(
            "-v",
            "--verbose",
            dest="verbose",
            action="count",
            help="Display verbose information (with increasing level). '-v': Level 1, "
            "Logging, Stdout, Stderr. '-vv': Level 2, Extends Level 1 with slightly "
            "elaborated iLO and HTTP response message. '-vvv': Level3, Extends Level 2 "
            "with message id, validation class, message text with embedded args, and "
            "possible resolution/mitigation for iLO responses. Includes HTTP responses. "
            "**NOTE 1**: Some responses may only contain limited information from the source."
            "**NOTE 2**: Default level is 0.",
            default=0,
        )
        self.add_argument(
            "-d",
            "--debug",
            dest="debug",
            action="store_true",
            help="""Display debug information.""",
            default=False,
        )
        self.add_argument(
            "--logdir",
            dest="logdir",
            default=None,
            help="""Use the provided directory as the location for log file.""",
            metavar="PATH",
        )
        self.add_argument(
            "--nostdoutlog",
            dest="nostdoutlog",
            action="store_true",
            help="""Disable debug logs to stdout.""",
            default=False,
        )
        self.add_argument(
            "--nocache",
            dest="nocache",
            action="store_true",
            help="During execution the application will temporarily store data only in memory.",
            default=False,
        )
        self.add_argument(
            "--nologo",
            dest="nologo",
            action="store_true",
            help="""Include to block copyright and logo.""",
            default=False,
        )
        self.add_argument(
            "--toolbar",
            dest="toolbar",
            action="store_true",
            help="""Show toolbar at the bottom.""",
            default=False,
        )
        self.add_argument(
            "--notab",
            dest="notab",
            action="store_true",
            help="""Disable tab complete.""",
            default=False,
        )
        self.add_argument(
            "--redfish",
            dest="is_redfish",
            action="store_true",
            help="Use this flag if you wish to to enable "
            "Redfish only compliance. It is enabled by default "
            "in systems with iLO5 and above.",
            default=False,
        )
        self.add_argument(
            "--latestschema",
            dest="latestschema",
            action="store_true",
            help="Optionally use the latest schema instead of the one "
            "requested by the file. Note: May cause errors in some data "
            "retrieval due to difference in schema versions.",
            default=False,
        )
        self.add_argument(
            "--useproxy",
            dest="proxy",
            default=None,
            help="""Use the provided proxy for communication.""",
            metavar="URL",
        )
        self.add_argument(
            "--redirectconsole",
            dest="redirect",
            help="Optionally include this flag to redirect stdout/stderr console.",
            nargs="?",
            default=None,
            const=True,
            metavar="REDIRECT CONSOLE",
        )
        self.add_argument_group(globalgroup)
