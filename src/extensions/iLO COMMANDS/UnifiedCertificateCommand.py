###
# Copyright 2021 Hewlett Packard Enterprise, Inc. All rights reserved.
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
""" unifiedcertificate Command for rdmc """

from argparse import ArgumentParser, RawDescriptionHelpFormatter

try:
    from rdmc_helper import (
        ReturnCodes,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        NoContentsFoundForOperationError,
        InvalidFileInputError,
        IncompatibleiLOVersionError,
        Encryption,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        ReturnCodes,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        NoContentsFoundForOperationError,
        InvalidFileInputError,
        IncompatibleiLOVersionError,
        Encryption,
    )


__filename__ = "certificate.txt"


class UnifiedCertificateCommand:
    """Commands Certificates actions to the server"""

    def __init__(self):
        self.ident = {
            "name": "unifiedcertificate",
            "usage": None,
            "description": "Generate a certificate signing request (CSR) or import/export X.509 "
            "formatted TLS/SSL, SSO and/or platform certificates.\nTo view help on "
            "specific sub-commands run: "
            "unifiedcertificate <sub-command> -h\n\nExample: unifiedcertificate import -h\n\n"
            "Example: unifiedcertificate export -h\n\n",
            "summary": "Command for importing and exporting X.509 TLS/SSL, SSO and platform "
            "certificates as well as generating and exporting certificate signing "
            "requests (CSR)",
            "aliases": [],
            "auxcommands": [],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """Main Certificates Command function

        :param options: list of options
        :type options: list.
        :param help_disp: display help flag
        :type line: bool.
        """
        if help_disp:
            self.parser.print_help()
            return ReturnCodes.SUCCESS
        try:
            (options, _) = self.rdmc.rdmc_parse_arglist(self, line)
        except (InvalidCommandLineErrorOPTS, SystemExit):
            if ("-h" in line) or ("--help" in line):
                return ReturnCodes.SUCCESS
            else:
                raise InvalidCommandLineErrorOPTS("")

        self.certificatesvalidation(options)

        if options.command == "gen_csr":
            self.gen_csr_helper(options)
        elif options.command == "get_csr":
            self.get_csr_helper(options)
        elif options.command == "import":
            self.importhelper(options)
        elif options.command == "export":
            self.exporthelper(options)

        self.cmdbase.logout_routine(self, options)
        # Return code
        return ReturnCodes.SUCCESS

    def importhelper(self, options):
        """Main helper function for importing certificates

        :param options: options attributes
        :type options: attributes
        """
        if (
            getattr(options, "TLSCERT")
            or getattr(options, "ROOTCACERT")
            or getattr(options, "USERCACERT")
        ):
            self.importtlscahelper(options)
        else:
            self.importplatformhelper(options)

    def importplatformhelper(self, options):
        """Helper function for importing a platform certificate

        :param options: options attributes
        :type options: attributes
        """

        ss_instance = next(
            iter(self.rdmc.app.select("SecurityService.", path_refresh=True))
        )
        if getattr(options, "LDEVID"):
            type = "iLOLDevID"
        elif getattr(options, "IDEVID"):
            type = "iLOIDevID"
        elif getattr(options, "SYSTEMIAK"):
            type = "SystemIAK"
        elif getattr(options, "SYSTEMIDEVID"):
            type = "SystemIDevID"
        elif getattr(options, "PLATFORMCERT"):
            type = "PlatformCert"
        else:
            raise InvalidCommandLineErrorOPTS(
                "An invalid set of options were selected...verify "
                " options were selected correctly and re-try."
            )

        instance_path_uri = (
            (
                ss_instance.dict[type]["Certificates"][
                    self.rdmc.app.typepath.defs.hrefstring
                ]
            )
            if ss_instance.dict.get("SystemIAK")
            else None
        )
        if instance_path_uri:
            certdata = None
            try:
                with open(options.file.strip('"'), "rb") as cf:
                    try:
                        certdata = str.decode(cf.read())
                    except:
                        certdata = cf.read()
            except:
                raise InvalidFileInputError("Error loading the specified file.")

            if certdata:
                self.rdmc.app.patch_handler(instance_path_uri, instance.data["Members"])

    def importtlscahelper(self, options):
        """Helper function for importing TLS certificate

        :param options: list of options
        :type options: list.
        """

        body = {}

        def actselect(bodydict, action_item):
            if self.rdmc.app.typepath.defs.isgen10:
                action = action_item.split("#")[-1]
            else:
                action = action_item
            path = bodydict["Actions"][action_item]["target"]
            return (path, action)

        if getattr(options, "from_url"):
            body.update({"ImportUri": next(iter(options.from_url))})
        else:
            try:
                with open(next(iter(options.filename))) as certfile:
                    body.update({"Certificate": certfile.read()})
            except:
                raise InvalidFileInputError(
                    "Error loading the specified file '%s'"
                    % next(iter(options.filename))
                )

        if getattr(options, "TLSCERT"):
            select = self.rdmc.app.typepath.defs.hphttpscerttype
        else:
            select = "HpeCertAuth."
        result = self.rdmc.app.select(selector=select, path_refresh=True)
        try:
            result = result[0]
        except:
            pass

        if not result:
            raise NoContentsFoundForOperationError(
                "Unable to find '%s'" % self.rdmc.app.selector
            )
        path = action = None
        bodydict = result.dict
        try:
            for item in bodydict["Actions"]:
                if getattr(options, "from_url"):
                    if "ImportCRL" in item:
                        path, action = actselect(bodydict, item)
                        break
                elif getattr(options, "TLSCERT"):
                    if "ImportCertificate" in item:
                        path, action = actselect(bodydict, item)
                        break
                elif "ImportCACertificate" in item:
                    path, action = actselect(bodydict, item)
                    break
        except:
            if getattr(options, "from_url"):
                action = "ImportCRL"
            elif getattr(options, "TLSCERT"):
                action = "ImportCertificate"
            else:
                action = "ImportCACertificate"

        if path and action:
            body.update({"Action": action})
            self.rdmc.app.post_handler(path, body)
        else:
            raise NoContentsFoundForOperationError("Unable to import certificate.")

    def exporthelper(self, options):

        data = None
        if getattr(options, "ROOTCACERT") or getattr(options, "USERCACERT"):
            result = self.exportcahelper(options)
            # Add entries for exporting TLS Certificate, RootCA and UserCA Certificates
        elif getattr(options, "TLSCERT"):
            raise InvalidCommandLineErrorOPTS(
                "This command is currently unable to export a TLS" " certificate."
            )
            # not seemingly possible to retrieve a TLS Cert
        else:
            result = self.exportplatformhelper(options)
        if result:
            if options.filename:
                self.file_handler(next(iter(options.filename)), result, options, "wb")
                self.rdmc.ui.printer(
                    "The certificate was saved to: %s\n" % next(iter(options.filename))
                )
            else:
                self.rdmc.ui.printer(
                    "The certificate retrieved is as follows:\n%s\n" % result
                )
        else:
            self.rdmc.ui.error(
                "An error occurred retrieving the requested certificate."
            )

    def exportplatformhelper(self, options):
        """Helper function for exporting a platform certificate

        :param options: list of options
        :type options: list.
        """

        type = "PlatformCert"  # assume platform certificate
        str_type = "Platform"
        ss_instance = next(
            iter(self.rdmc.app.select("SecurityService." + ".", path_refresh=True))
        )
        if options.LDEVID:
            type = "iLOLDevID"
            str_type = "iLO lDevID"
        elif options.IDEVID:
            type = "iLOIDevID"
            str_type = "iLO iDevID"
        elif options.SYSTEMIAK:
            type = "SystemIAK"
            str_type = "System IAK"
        elif options.SYSTEMIDEVID:
            type = "SystemIDevID"
            str_type = "System iDevID"
        instance_path_uri = (
            (
                ss_instance.dict[type]["Certificates"][
                    self.rdmc.app.typepath.defs.hrefstring
                ]
            )
            if ss_instance.dict.get("SystemIAK")
            else None
        )
        instance_data = self.rdmc.app.get_handler(instance_path_uri, silent=True)
        cert = None
        if instance_data.dict.get("Members"):
            cert = self.rdmc.app.get_handler(
                instance_data.dict["Members"][getattr(options, "id", 0) - 1].get(
                    self.rdmc.app.typepath.defs.hrefstring
                ),
                silent=True,
            ).dict
            return cert.get("CertificateString")
        else:
            raise NoContentsFoundForOperationError(
                "Unable to find specified certificate at "
                "positon %s." % getattr(options, "id", 0)
            )

    def exportcahelper(self, options):

        if not self.rdmc.app.typepath.flagiften:
            raise IncompatibleiLOVersionError(
                "This certificate is not available on this system."
            )

        try:
            cacerts_path = self.rdmc.app.select(
                selector="CertAuth.", path_refresh=True
            ).dict.get("CACertificates")
        except:
            try:
                cacerts_path = next(
                    iter(self.rdmc.app.select(selector="CertAuth.", path_refresh=True))
                ).dict.get("CACertificates")
            except:
                raise NoContentsFoundForOperationError("Unable to find CA Certificates")
        instance_data = self.rdmc.app.get_handler(
            cacerts_path.get(self.rdmc.app.typepath.defs.hrefstring), silent=True
        )
        if instance_data.dict.get("Members"):
            cert = self.rdmc.app.get_handler(
                instance_data.dict["Members"][getattr(options, "id", 0) - 1].get(
                    self.rdmc.app.typepath.defs.hrefstring
                ),
                silent=True,
            ).dict
            return cert.get("CertificateString")
        else:
            raise NoContentsFoundForOperationError(
                "Unable to find specified certificate at "
                "positon %s." % getattr(options, "id", 0)
            )

    def gen_csr_helper(self, options):
        """
        :param options: list of options
        :type options: attributes.
        """
        body = None
        path = None
        action = "GenerateCSR"
        if options.TLSCERT:
            instance = next(iter(self.rdmc.app.select("HttpsCert.", path_refresh=True)))
            body = {
                "Action": action,
                "OrgName": options.csr_orgname.strip('"'),
                "OrgUnit": options.csr_orgunit.strip('"'),
                "CommonName": options.csr_commonname.strip('"'),
                "Country": options.csr_country.strip('"'),
                "State": options.csr_state.strip('"'),
                "City": options.csr_city.strip('"'),
            }

        elif options.PLATFORM:
            # There is seemingly no way to update the Certificate subject data which
            # appears problematic.
            cs_instance = next(
                iter(self.rdmc.app.select("CertificateService.", path_refresh=True))
            )
            ss_instance = next(
                iter(self.rdmc.app.select("SecurityService.", path_refresh=True))
            )
            cert_obtain_path = ss_instance.dict.get("iLOLDevID")[
                next(iter(ss_instance.dict.get("iLOLDevID")))
            ].get(self.rdmc.app.typepath.defs.hrefstring)
            if not cert_obtain_path:
                raise NoContentsFoundForOperationError(
                    "Unable to find specified certificate path"
                    " for CSR request" % cert_key
                )
            instance = next(
                iter(self.rdmc.app.select("CertificateService.", path_refresh=True))
            )
            body = {
                "CertificateCollection": {
                    self.rdmc.app.typepath.defs.hrefstring: cert_obtain_path
                }
            }

        try:
            for act in instance.dict.get("Actions"):
                if "GenerateCSR" in act:
                    if self.rdmc.app.typepath.defs.isgen10:
                        action = act.split("#")[-1]
                    else:
                        action = "GenerateCSR"
                    path = instance.dict["Actions"][act]["target"]
                    break
        except:
            raise NoContentsFoundForOperationError(
                "Unable to find specified certificate action"
                "path for CSR request" % cert_key
            )

        self.rdmc.ui.printer(
            "iLO is creating a new certificate signing request. "
            "This request may take up to 10 minutes.\n"
        )
        return self.rdmc.app.post_handler(path, body)

    def get_csr_helper(self, options):

        result = None
        if options.TLSCERT:
            instance = next(iter(self.rdmc.app.select("HttpsCert.", path_refresh=True)))
            result = instance.dict.get("CertificateSigningRequest")
        elif options.PLATFORM:
            tmp = self.gen_csr_helper(options)
            if tmp:
                result = tmp.dict.get("CSRString")

        if result:
            if options.filename:
                self.file_handler(next(iter(options.filename)), result, options, "wb")
                self.rdmc.ui.printer(
                    "The CSR was saved to: %s\n" % next(iter(options.filename))
                )
            else:
                self.rdmc.ui.printer("The CSR retrieved is as follows:\n%s\n" % result)
        else:
            self.rdmc.ui.error("An error occurred retrieving a CSR.")

    def file_handler(self, filename, data, options, operation="rb"):
        """
        Wrapper function to read or write data to a respective file
        :param data: data to be written to output file
        :type data: container (list of dictionaries, dictionary, etc.)
        :param file: filename to be written
        :type file: string (generally this should be self.clone_file or tmp_clone_file
        :param operation: file operation to be performed
        :type operation: string ('w+', 'a+', 'r+')
        :param options: command line options
        :type options: attribute
        :returns: json file data
        """
        writeable_ops = ["wb", "w", "w+", "a", "a+"]
        readable_ops = ["rb", "r", "r+"]

        if operation in writeable_ops:
            with open(filename, operation) as fh:
                try:
                    data = data.encode("UTF-8")
                except IOError:
                    raise InvalidFileInputError(
                        "Unable to write to file '%s'" % filename
                    )
                except UnicodeEncodeError:
                    pass
                finally:
                    # No encryption...yet..?
                    # if options.encryption:
                    #    fh.write(Encryption().encrypt_file(data, options.encryption))
                    # else:
                    fh.write(data)
        else:
            # No encryption...yet...?
            # if options.encryption:
            #    fdata = Encryption().decrypt_file(fh.read(), options.encryption)
            with open(filename, operation) as fh:
                try:
                    return fdata.decode("UTF-8")
                except UnicodeDecodeError:
                    return fdata
                except IOError:
                    raise InvalidFileInputError(
                        "Unable to read from file '%s'" % filename
                    )

    def certificatesvalidation(self, options):
        """certificates validation function

        :param options: command line options
        :type options: list.
        """
        self.cmdbase.login_select_validation(self, options)

    @staticmethod
    def options_import_export_argument_group(parser):
        """Define option arguments group
        :param parser: The parser to add the login option group to
        :type parser: ArgumentParser/OptionParser
        """
        group = parser.add_argument_group()

        parser.add_argument(
            "--USERCA",
            dest="USERCACERT",
            help="specify for a user CA certificate.",
            action="store_true",
            default=None,
        )
        parser.add_argument(
            "--ROOTCA",
            dest="ROOTCACERT",
            help="specify for a root CA certificate.",
            action="store_true",
            default=None,
        )
        parser.add_argument(
            "--TLS_CERT",
            dest="TLSCERT",
            help="specify for a TLS/SSL certificate.",
            action="store_true",
            default=None,
        )

        parser.add_argument(
            "-f",
            "--filename",
            dest="filename",
            help="Use this flag to import a certificate from or export a certificate to a file.",
            action="append",
            default=None,
        )

    def definearguments(self, customparser):
        """Wrapper function for certificates command main function

        :param customparser: command line input
        :type customparser: parser.
        """
        if not customparser:
            return

        self.cmdbase.add_login_arguments_group(customparser)

        subcommand_parser = customparser.add_subparsers(dest="command")

        # gen csr sub-parser
        gen_csr_help = (
            "Generate a certificate signing request (CSR) for iLO SSL certificate "
            "authentication.\nNote: iLO will create a Base64 encoded CSR in PKCS "
            "#10 Format."
        )
        gen_csr_parser = subcommand_parser.add_parser(
            "gen_csr",
            help=gen_csr_help,
            description=gen_csr_help
            + "\nexample: unifiedcertificate csr [ORG_NAME] [ORG_UNIT]"
            " [COMMON_NAME] [COUNTRY] [STATE] [CITY]\n\nNOTE: please make "
            "certain the order of arguments is correct. **NOTE:** Use quotes "
            "to include parameters which contain whitespace when generating a CSR."
            '\nexample: unifiedcertificate csr "Hewlett Packard Enterprise"'
            '"iLORest Group" "CName"\n"United States" "Texas" "Houston"',
            formatter_class=RawDescriptionHelpFormatter,
        )
        gen_csr_parser.add_argument(
            dest="csr_orgname",
            nargs="?",
            help="Organization name. i.e. Hewlett Packard Enterprise.",
            metavar="ORGNAME",
        )
        gen_csr_parser.add_argument(
            dest="csr_orgunit",
            nargs="?",
            help="Organization unit. i.e. Intelligent Provisioning.",
            metavar="ORGUNIT",
        )
        gen_csr_parser.add_argument(
            dest="csr_commonname",
            nargs="?",
            help="Organization common name. i.e. Common Organization Name.",
            metavar="ORGNAME",
        )
        gen_csr_parser.add_argument(
            dest="csr_country",
            nargs="?",
            help="Organization country. i.e. United States.",
            metavar="ORGCOUNTRY",
        )
        gen_csr_parser.add_argument(
            dest="csr_state",
            nargs="?",
            help="Organization state. i.e. Texas.",
            metavar="ORGSTATE",
        )
        gen_csr_parser.add_argument(
            dest="csr_city",
            nargs="?",
            help="Organization city. i.e. Houston.",
            metavar="ORGCITY",
        )
        gen_csr_parser.add_argument(
            "--TLS_CERT",
            dest="TLSCERT",
            help="specify to generate a TLS/SSL certificate signing request.",
            action="store_true",
            default=None,
        )
        gen_csr_parser.add_argument(
            "--PLATFORM_CERT",
            dest="PLATFORM",
            help="specify to generate a platform certificate signing request.",
            action="store_true",
            default=None,
        )
        self.cmdbase.add_login_arguments_group(gen_csr_parser)

        # get csr
        get_csr_help = (
            "Retrieve the generated certificate signing request (CSR) printed to the "
            "console or to a json file."
        )
        get_csr_parser = subcommand_parser.add_parser(
            "get_csr",
            help=get_csr_help,
            description=get_csr_help
            + "\nExample: unifiedcertificate getcsr [CERTIFICATE] "
            "-f mycsrfile",
            formatter_class=RawDescriptionHelpFormatter,
        )
        get_csr_parser.add_argument(
            "--TLS_CERT",
            dest="TLSCERT",
            help="specify to retrieve a TLS/SSL certificate signing request.",
            action="store_true",
            default=None,
        )
        get_csr_parser.add_argument(
            "--PLATFORM_CERT",
            dest="PLATFORM",
            help="specify to retrieve a platform certificate signing request.",
            action="store_true",
            default=None,
        )

        get_csr_parser.add_argument(
            "-f",
            "--filename",
            dest="filename",
            help="Use this flag to specify a file for a certificate signing request (CSR)",
            action="append",
            default=None,
        )
        self.cmdbase.add_login_arguments_group(get_csr_parser)

        import_help = "Push an X.509 formatted platform certificate to iLO."
        import_parser = subcommand_parser.add_parser(
            "import",
            help=import_help,
            description=import_help
            + "\nExample: unifiedcertificate import [CERTIFICATE] -f "
            "mytlsfile\n**Note: Certificates can not be imported from command line.**",
            formatter_class=RawDescriptionHelpFormatter,
        )
        import_parser.add_argument(
            "--from_url",
            dest="from_url",
            help="Use this flag to specify a URL for certificate import",
            action="append",
            default=None,
        )
        self.options_import_export_argument_group(import_parser)
        self.cmdbase.add_login_arguments_group(import_parser)

        # export cert
        export_help = "Pull an X.509 formatted platform certificate from iLO."
        export_parser = subcommand_parser.add_parser(
            "export",
            help=export_help,
            description=export_help
            + "\nExample: unifiedcertificate export [CERTIFICATE] -f "
            "mytlsfile\n",
            formatter_class=RawDescriptionHelpFormatter,
        )

        export_parser.add_argument(
            "--IDEVID",
            dest="IDEVID",
            help="Specify for an IDEVID certificate. ",
            action="store_true",
            default=None,
        )
        export_parser.add_argument(
            "--LDEVID",
            dest="LDEVID",
            help="Specify for an LDEVID certificate. ",
            action="store_true",
            default=None,
        )
        export_parser.add_argument(
            "--SYSTEMIAK",
            dest="SYSTEMIAK",
            help="Specify for a system IAK certificate.",
            action="store_true",
            default=None,
        )
        export_parser.add_argument(
            "--SYSTEMIDEVID",
            dest="SYSTEMIDEVID",
            help="Specify for a system IDEVID certificate.",
            action="store_true",
            default=None,
        )
        export_parser.add_argument(
            "--PLATFORMCERT",
            dest="PLATFORMCERT",
            help="Specify for a platform certificate.",
            action="store_true",
            default=None,
        )
        export_parser.add_argument(
            "--id",
            dest="id",
            help="Optionally specify the certificate instance, if multiples are available. If"
            "the instance specified is not available, then the next is retrieved. Default is"
            "the first instance",
            default=1,
        )

        self.options_import_export_argument_group(export_parser)
        self.cmdbase.add_login_arguments_group(export_parser)
