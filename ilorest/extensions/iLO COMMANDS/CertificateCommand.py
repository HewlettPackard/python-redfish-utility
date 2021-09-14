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
""" Certificates Command for rdmc """

from argparse import ArgumentParser, RawDescriptionHelpFormatter

from ilorest.rdmc_helper import ReturnCodes, InvalidCommandLineError, \
            InvalidCommandLineErrorOPTS, NoContentsFoundForOperationError, \
            InvalidFileInputError, IncompatibleiLOVersionError, Encryption

__filename__ = 'certificate.txt'

class CertificateCommand():
    """ Commands Certificates actions to the server """
    def __init__(self):
        self.ident = {
            'name':'certificate',
            'usage': None,
            'description':'Generate a certificate signing request (CSR) or import an X509 formatted'
                          ' TLS or CA certificate.\nTo view help on specific sub-commands run: '
                          'singlesignon <sub-command> -h\n\nExample: singlesignon importcert -h\n\n'
                          'NOTE: Use the singlesignon command to import single sign on certificates.\n\n'
                          'NOTE: Use quotes to include parameters which contain whitespace when '
                          'generating a CSR.\nexample: certificate csr \"Hewlett Packard Enterprise\"'
                          '\"iLORest Group\" \"CName\"\n\"United States\" \"Texas\" \"Houston\"',
            'summary':"Command for importing both iLO and login authorization "
                      "certificates as well as generating iLO certificate signing requests (CSR)",
            'aliases': [],
            'auxcommands': []
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """ Main Certificates Command function

        :param options: list of options
        :type options: list.
        """
        if help_disp:
            self.parser.print_help()
            return ReturnCodes.SUCCESS
        try:
            (options, _) = self.rdmc.rdmc_parse_arglist(self, line)
            if not line or line[0] == "help":
                self.parser.print_help()
                return ReturnCodes.SUCCESS
        except (InvalidCommandLineErrorOPTS, SystemExit):
            if ("-h" in line) or ("--help" in line):
                # self.rdmc.ui.printer(self.ident['usage'])
                return ReturnCodes.SUCCESS
            else:
                raise InvalidCommandLineErrorOPTS("")

        self.certificatesvalidation(options)

        if options.command == 'csr':
            self.generatecerthelper(options)
        elif options.command == 'ca':
            self.importcahelper(options)
        elif options.command == 'getcsr':
            self.getcerthelper(options)
        elif options.command == 'crl':
            self.importcrlhelper(options)
        elif options.command == 'tls':
            self.importtlshelper(options)

        self.cmdbase.logout_routine(self, options)
        #Return code
        return ReturnCodes.SUCCESS

    def generatecerthelper(self, options):
        """ Main Certificates Command function

        :param options: list of options
        :type options: list.
        """

        select = self.rdmc.app.typepath.defs.hphttpscerttype
        results = self.rdmc.app.select(selector=select)

        try:
            results = results[0]
        except:
            pass

        if results:
            path = results.resp.request.path
        else:
            raise NoContentsFoundForOperationError("Unable to find %s" % select)

        bodydict = results.resp.dict

        try:
            for item in bodydict['Actions']:
                if 'GenerateCSR' in item:
                    if self.rdmc.app.typepath.defs.isgen10:
                        action = item.split('#')[-1]
                    else:
                        action = "GenerateCSR"

                    path = bodydict['Actions'][item]['target']
                    break
        except:
            action = "GenerateCSR"

        body = {"Action": action, "OrgName" :options.csr_orgname.strip('\"'), "OrgUnit":
            options.csr_orgunit.strip('\"'), "CommonName": options.csr_commonname.strip('\"'),
                "Country": options.csr_country.strip('\"'), "State":
                    options.csr_state.strip('\"'), "City": options.csr_city.strip('\"')}

        self.rdmc.ui.printer("iLO is creating a new certificate signing request. "
                             "This process can take up to 10 minutes.\n")

        self.rdmc.app.post_handler(path, body)

    def getcerthelper(self, options):
        """ Helper function for importing CRL certificate

        :param options: list of options
        :type options: list.
        """

        select = self.rdmc.app.typepath.defs.hphttpscerttype
        results = self.rdmc.app.select(selector=select)

        try:
            results = results[0]
        except:
            pass

        if results:
            try:
                csr = results.resp.dict['CertificateSigningRequest']
                if not csr:
                    raise ValueError
            except (KeyError, ValueError):
                raise NoContentsFoundForOperationError('Unable to find a valid certificate. If '
                                                       'you just generated a new certificate '
                                                       'signing request the process may take '
                                                       'up to 10 minutes.')

            if not options.filename:
                filename = __filename__
            else:
                filename = options.filename[0]

            outfile = open(filename, 'w')
            outfile.write(csr)
            outfile.close()

            self.rdmc.ui.printer("Certificate saved to: %s\n" % filename)
        else:
            raise NoContentsFoundForOperationError("Unable to find %s" % select)

    def importtlshelper(self, options):
        """ Helper function for importing TLS certificate

        :param options: list of options
        :type options: list.
        """
        tlsfile = options.certfile

        try:
            with open(tlsfile) as certfile:
                certdata = certfile.read()
                certfile.close()
        except:
            raise InvalidFileInputError("Error loading the specified file.")

        select = self.rdmc.app.typepath.defs.hphttpscerttype
        results = self.rdmc.app.select(selector=select)

        try:
            results = results[0]
        except:
            pass

        if results:
            path = results.resp.request.path
        else:
            raise NoContentsFoundForOperationError("Unable to find %s" % select)

        bodydict = results.resp.dict
        try:
            for item in bodydict['Actions']:
                if 'ImportCertificate' in item:
                    if self.rdmc.app.typepath.defs.isgen10:
                        action = item.split('#')[-1]
                    else:
                        action = "ImportCertificate"
                    path = bodydict['Actions'][item]['target']
                    break
        except:
            action = "ImportCertificate"

        body = {"Action": action, "Certificate": certdata}

        self.rdmc.app.post_handler(path, body)

    def importcrlhelper(self, options):
        """ Helper function for importing CRL certificate

        :param options: list of options
        :type options: list.
        """
        if not self.rdmc.app.typepath.flagiften:
            raise IncompatibleiLOVersionError("This certificate is not available on this system.")

        select = 'HpeCertAuth.'
        results = self.rdmc.app.select(selector=select)

        try:
            results = results[0]
        except:
            pass

        if results:
            bodydict = results.resp.dict
        else:
            raise NoContentsFoundForOperationError("Unable to find %s" % select)

        for item in bodydict['Actions']:
            if 'ImportCRL' in item:
                action = item.split('#')[-1]
                path = bodydict['Actions'][item]['target']
                break

        body = {"Action": action, "ImportUri": args[1]}

        self.rdmc.app.post_handler(path, body)

    def importcahelper(self, options):
        """ Helper function for importing CA certificate

        :param options: list of options
        :type options: list.
        """
        if not self.rdmc.app.typepath.flagiften:
            raise IncompatibleiLOVersionError("This certificate is not available on this system.")

        tlsfile = options.certfile

        try:
            with open(tlsfile) as certfile:
                certdata = certfile.read()
                certfile.close()
        except:
            raise InvalidFileInputError("Error loading the specified file.")

        select = 'HpeCertAuth.'
        results = self.rdmc.app.select(selector=select)

        try:
            results = results[0]
        except:
            pass

        if results:
            bodydict = results.resp.dict
        else:
            raise NoContentsFoundForOperationError("Unable to find %s" % select)

        for item in bodydict['Actions']:
            if 'ImportCACertificate' in item:
                action = item.split('#')[-1]
                path = bodydict['Actions'][item]['target']
                break

        body = {"Action": action, "Certificate": certdata}

        self.rdmc.app.post_handler(path, body)

    def certificatesvalidation(self, options):
        """ certificates validation function

        :param options: command line options
        :type options: list.
        """
        self.cmdbase.login_select_validation(self, options)

    def definearguments(self, customparser):
        """ Wrapper function for certificates command main function

        :param customparser: command line input
        :type customparser: parser.
        """
        if not customparser:
            return

        self.cmdbase.add_login_arguments_group(customparser)

        subcommand_parser = customparser.add_subparsers(dest='command')

        #gen csr sub-parser
        gen_csr_help='Generate a certificate signing request (CSR) for iLO SSL certificate '\
                     'authentication.\nNote: iLO will create a Base64 encoded CSR in PKCS '\
                     '#10 Format.'
        gen_csr_parser = subcommand_parser.add_parser(
            'csr',
            help=gen_csr_help,
            description=gen_csr_help+'\nexample: certificate csr [ORG_NAME] [ORG_UNIT]'\
                        ' [COMMON_NAME] [COUNTRY] [STATE] [CITY]\n\nNOTE: please make ' \
                        'certain the order of arguments is correct.',
            formatter_class=RawDescriptionHelpFormatter
        )
        gen_csr_parser.add_argument(
            'csr_orgname',
            help='Organization name. i.e. Hewlett Packard Enterprise.',
            metavar='ORGNAME'
        )
        gen_csr_parser.add_argument(
            'csr_orgunit',
            help='Organization unit. i.e. Intelligent Provisioning.',
            metavar='ORGUNIT'
        )
        gen_csr_parser.add_argument(
            'csr_commonname',
            help='Organization common name. i.e. Common Organization Name.',
            metavar='ORGNAME'
        )
        gen_csr_parser.add_argument(
            'csr_country',
            help='Organization country. i.e. United States.',
            metavar='ORGCOUNTRY'
        )
        gen_csr_parser.add_argument(
            'csr_state',
            help='Organization state. i.e. Texas.',
            metavar='ORGSTATE'
        )
        gen_csr_parser.add_argument(
            'csr_city',
            help='Organization city. i.e. Houston.',
            metavar='ORGCITY'
        )
        self.cmdbase.add_login_arguments_group(gen_csr_parser)

        #get csr
        get_csr_help='Retrieve the generated certificate signing request (CSR) printed to the '\
                     'console or to a json file.'
        get_csr_parser = subcommand_parser.add_parser(
            'getcsr',
            help=get_csr_help,
            description=get_csr_help+'\nexample: certificate getcsr\nexample: certificate getcsr '\
                        '-f mycsrfile.json',
            formatter_class=RawDescriptionHelpFormatter
        )
        get_csr_parser.add_argument(
            '-f',
            '--filename',
            dest='filename',
            help="Use this flag if you wish to use a different"\
            " filename for the certificate signing request. The default" \
            " filename is %s." % __filename__,
            action="append",
            default=None,
        )
        self.cmdbase.add_login_arguments_group(get_csr_parser)

        #ca certificate
        ca_help='Upload a X.509 formatted CA certificate to iLO.'
        ca_parser = subcommand_parser.add_parser(
            'ca',
            help=ca_help,
            description=ca_help+'\nexample: certificate ca mycertfile.txt\nNote: The '
                        'certificate must be in X.509 format',
            formatter_class=RawDescriptionHelpFormatter
        )
        ca_parser.add_argument(
            'certfile',
            help='X.509 formatted CA certificate',
            metavar='CACERTFILE'
        )
        self.cmdbase.add_login_arguments_group(ca_parser)

        #crl certificate
        crl_help='Provide iLO with a URL to retrieve the X.509 formatted CA certificate.'
        crl_parser = subcommand_parser.add_parser(
            'crl',
            help=crl_help,
            description=crl_help+'\nexample: certificate crl https://mycertfileurl/mycertfile.txt' \
                        '\nNote: The certificate must be in X.509 format',
            formatter_class=RawDescriptionHelpFormatter
        )
        crl_parser.add_argument(
            'certfile_url',
            help='URL pointing to the location of the X.509 CA certificate',
            metavar='CERTFILEURL'
        )
        self.cmdbase.add_login_arguments_group(crl_parser)

        #tls certificate
        tls_help='Upload a X.509 TLS certificate to iLO.'
        tls_parser = subcommand_parser.add_parser(
            'tls',
            help=tls_help,
            description=tls_help+'\nexample: certificate tls mycertfile.txt\nNote: The '
                        'certificate must be in TLS X.509 format',
            formatter_class=RawDescriptionHelpFormatter
        )
        tls_parser.add_argument(
            'certfile',
            help='X.509 formatted TLS certificate',
            metavar='TLSCERTFILE'
        )
        self.cmdbase.add_login_arguments_group(tls_parser)
