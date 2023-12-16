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
""" Single Sign On Command for rdmc """
from argparse import RawDescriptionHelpFormatter

try:
    from rdmc_helper import (
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        NoContentsFoundForOperationError,
        ReturnCodes,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        NoContentsFoundForOperationError,
        ReturnCodes,
    )


class SingleSignOnCommand:
    """Commands Single Sign On actions to the server"""

    def __init__(self):
        self.ident = {
            "name": "singlesignon",
            "usage": None,
            "description": "Add or remove single sign on (SSO) records.\nTo view help on specific "
            "sub-commands run: singlesignon <sub-command> -h\n\nExample: singlesignon "
            "importcert -h\n\n",
            "summary": "Command for all single sign on available actions. ",
            "aliases": ["sso"],
            "auxcommands": [],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """Main SingleSignOnCommand function

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
            (options, _) = self.rdmc.rdmc_parse_arglist(self, line)
        except (InvalidCommandLineErrorOPTS, SystemExit):
            if ("-h" in line) or ("--help" in line):
                return ReturnCodes.SUCCESS
            else:
                raise InvalidCommandLineErrorOPTS("")

        self.singlesignonvalidation(options)

        actionitem = None
        select = self.rdmc.app.typepath.defs.hpilossotype
        results = self.rdmc.app.select(selector=select)

        try:
            results = results[0]
        except:
            pass

        if results:
            path = results.resp.request.path
        else:
            raise NoContentsFoundForOperationError("%s not found." % select)

        bodydict = results.resp.dict

        if not options.command:
            return ReturnCodes.SUCCESS

        if options.command.lower() == "importdns":
            actionitem = "ImportDNSName"
            body = {"Action": actionitem, "DNSName": options.dnsname}
        elif options.command.lower() == "importcert":
            cert = None
            certtype = None
            actionitem = "ImportCertificate"

            try:
                cert = open(options.cert, "r")

                if cert:
                    certtext = cert.read()
                    cert.close()

                if certtext:
                    certtype = "DirectImportCert"
            except:
                pass

            if not certtype:
                certtype = "ImportCertUri"
                certtext = options.cert

            body = {"Action": actionitem, "CertType": certtype, "CertInput": certtext}

        elif options.command.lower() == "deleterecord":
            if options.record.lower() == "all":
                actionitem = "DeleteAllSSORecords"
                body = {"Action": actionitem}
            else:
                actionitem = "DeleteSSORecordbyNumber"

                try:
                    body = {"Action": actionitem, "RecordNumber": int(options.record)}
                except:
                    raise InvalidCommandLineError("Record to delete must be a number")

        try:
            for item in bodydict["Actions"]:
                if actionitem in item:
                    if self.rdmc.app.typepath.defs.isgen10:
                        actionitem = item.split("#")[-1]
                        body["Action"] = actionitem

                    path = bodydict["Actions"][item]["target"]
                    break
        except:
            pass

        self.rdmc.app.post_handler(path, body)

        self.cmdbase.logout_routine(self, options)
        # Return code
        return ReturnCodes.SUCCESS

    def singlesignonvalidation(self, options):
        """single sign on validation function

        :param options: command line options
        :type options: list.
        """
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
        save_import_dns_help = "Import a DNS name."
        # importdns sub-parser
        import_dns_parser = subcommand_parser.add_parser(
            "importdns",
            help=save_import_dns_help,
            description=save_import_dns_help + "\n\texample singlesignon importdns dnsname",
            formatter_class=RawDescriptionHelpFormatter,
        )
        import_dns_parser.add_argument("dnsname", help="DNS Name to be imported", metavar="DNSNAME")
        save_import_cert_help = "Import certificate from URI or file."
        # importcert sub-parser
        import_cert_parser = subcommand_parser.add_parser(
            "importcert",
            help=save_import_cert_help,
            description=save_import_cert_help + "\n\texample singlesignon importcert cert.txt",
            formatter_class=RawDescriptionHelpFormatter,
        )
        import_cert_parser.add_argument(
            "cert",
            help="Certificate URI or Certificate File to be imported.",
            metavar="CERTIFICATE",
        )
        # delete sub-parser
        delete_sso_help = "Delete a single or all SSO records."
        delete_sso_parser = subcommand_parser.add_parser(
            "deleterecord",
            help=delete_sso_help,
            description=delete_sso_help + "\nDelete a single record:\nexample deleterecord 2\n"
            "Delete all records:\nexample singlesignon deleterecord all",
            formatter_class=RawDescriptionHelpFormatter,
        )
        delete_sso_parser.add_argument(
            "record",
            help="Record to be deleted (or use keyword 'all' to delete all records)",
            metavar="RECORD",
        )
