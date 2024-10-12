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

import time
from argparse import RawDescriptionHelpFormatter

try:
    from rdmc_helper import (
        IloLicenseError,
        IncompatibleiLOVersionError,
        InvalidCommandLineErrorOPTS,
        InvalidFileInputError,
        NoContentsFoundForOperationError,
        ReturnCodes,
        ScepenabledError,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        IloLicenseError,
        IncompatibleiLOVersionError,
        InvalidCommandLineErrorOPTS,
        InvalidFileInputError,
        NoContentsFoundForOperationError,
        ReturnCodes,
        ScepenabledError,
    )

__filename__ = "certificate.txt"

from redfish.ris import IdTokenError


class CertificateCommand:
    """Commands Certificates actions to the server"""

    def __init__(self):
        self.ident = {
            "name": "certificate",
            "usage": None,
            "description": "Generate a certificate signing request (CSR) or import an X509 formatted"
            " TLS or CA certificate.\nImport Scep Certificate.\nInvoke Auto Enroll of certificate generation\n\n"
            "NOTE: Use quotes to include parameters which contain whitespace when "
            'generating a CSR.\nexample: certificate gen_csr "Hewlett Packard Enterprise"'
            '"iLORest Group" "CName"\n"United States" "Texas" "Houston" "False or True"\n\n'
            "NOTE: unifiedcertificate command which was augmenting certificate command is merged"
            " into single command certificate",
            "summary": "Command for importing both iLO and login authorization "
            "certificates as well as generating iLO certificate signing requests (CSR)\n",
            "aliases": ["unifiedcertificate"],
            "auxcommands": [],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()
        self.view = None
        self.importcert = None
        self.exportcert = None
        self.delete = None
        self.gencsr = None
        self.autoenroll = None

    def run(self, line, help_disp=False):
        """Main Certificates Command function

        :param options: list of options
        :type options: list.
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

        self.certificatesvalidation(options)

        returnCode = None

        if options.command == "csr":
            self.rdmc.ui.printer(
                "This command has been deprecated. Please use the following command: "
                'certificate gen_csr "Hewlet Packard Enterprice" "ILORestGroup" ...\n'
                "It performs the same function.\n"
                "Check --help for more information.\n"
            )
            self.cmdbase.logout_routine(self, options)
            # Return code
            return returnCode
        elif options.command == "ca":
            self.rdmc.ui.printer(
                "This command has been deprecated. Please use the following "
                "command: certificate import --ca_cert <ca_txt>\n"
                "It performs the same function.\n"
                "Check --help for more information.\n"
            )
            self.cmdbase.logout_routine(self, options)
            # Return code
            return returnCode
        elif options.command == "getcsr":
            returnCode = self.get_csr_helper(options)
        elif options.command == "crl":
            self.rdmc.ui.printer(
                "This command has been deprecated. Please use the following command: "
                "certificate import --crl_cert <crl_txt>\n"
                "It performs the same function.\n"
                "Check --help for more information.\n"
            )
            self.cmdbase.logout_routine(self, options)
            # Return code
            return returnCode
        elif options.command == "tls":
            self.rdmc.ui.printer(
                "This command has been deprecated. Please use the following command: "
                "certificate import --tls_cert <tls_txt>\n"
                "It performs the same function.\n"
                "Check --help for more information.\n"
            )
            self.cmdbase.logout_routine(self, options)
            # Return code
            return returnCode
        if "view" in options.command.lower():
            self.view = True
            self.importcert = False
            self.delete = False
            self.gencsr = False
            self.autoenroll = False
            self.exportcert = False
        elif "import" in options.command.lower():
            self.view = False
            self.importcert = True
            self.delete = False
            self.gencsr = False
            self.autoenroll = False
            self.exportcert = False
        elif "export" in options.command.lower():
            self.view = False
            self.importcert = False
            self.delete = False
            self.gencsr = False
            self.autoenroll = False
            self.exportcert = True
        elif "delete" in options.command.lower():
            self.view = False
            self.importcert = False
            self.delete = True
            self.gencsr = False
            self.autoenroll = False
            self.exportcert = False
        elif "gen_csr" in options.command.lower():
            self.view = False
            self.importcert = False
            self.delete = False
            self.gencsr = True
            self.autoenroll = False
            self.exportcert = False
        elif "auto_enroll" in options.command.lower():
            self.view = False
            self.importcert = False
            self.delete = False
            self.gencsr = False
            self.autoenroll = True
            self.exportcert = False

        if self.view:
            returnCode = self.viewfunction(options)
        elif self.importcert:
            returnCode = self.importfunction(options)
        elif self.exportcert:
            returnCode = self.exportfunction(options)
        elif self.delete:
            returnCode = self.deletefunction(options)
        elif self.gencsr:
            returnCode = self.gencsrfunction(options)
        elif self.autoenroll:
            if self.rdmc.app.typepath.defs.isgen10:
                returnCode = self.autoenrollfunction(options)
            else:
                self.rdmc.ui.printer("Gen 9 doesnt support this feature\n")
                returnCode = ReturnCodes.SUCCESS

        self.cmdbase.logout_routine(self, options)
        # Return code
        return returnCode

    def autoenrollfunction(self, options):
        """Automatic Scep cert enrollement process

        :param options: list of options
        :type options: list.
        """
        select = self.rdmc.app.typepath.defs.securityservice
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
            for item in bodydict["Links"]:
                if "AutomaticCertificateEnrollment" in item:
                    path = bodydict["Links"]["AutomaticCertificateEnrollment"]["@odata.id"]
                    break
        except:
            path = path + "AutomaticCertificateEnrollment"

        body = {
            "AutomaticCertificateEnrollmentSettings": {
                "ServiceEnabled": eval(options.autoenroll_ScepService.strip('"')),
                "ServerUrl": options.autoenroll_scep_enrollAddress.strip('"'),
                "ChallengePassword": options.autoenroll_challengepassword.strip('"'),
            },
            "HttpsCertCSRSubjectValue": {
                "OrgName": options.autoenroll_orgname.strip('"'),
                "OrgUnit": options.autoenroll_orgunit.strip('"'),
                "CommonName": options.autoenroll_commonname.strip('"'),
                "Country": options.autoenroll_country.strip('"'),
                "State": options.autoenroll_state.strip('"'),
                "City": options.autoenroll_city.strip('"'),
                "IncludeIP": eval(options.autoenroll_includeIP.strip('"')),
            },
        }

        try:
            results = self.rdmc.app.patch_handler(path, body, silent=True)

            i = 0
            results1 = self.rdmc.app.get_handler(path, silent=True)
            while i < 9 and (
                results1.dict["AutomaticCertificateEnrollmentSettings"]["CertificateEnrollmentStatus"] == "InProgress"
            ):
                results1 = self.rdmc.app.get_handler(path, silent=True)
                time.sleep(1)
                i = i + 1

            if results.status == 200 and (
                not (results1.dict["AutomaticCertificateEnrollmentSettings"]["CertificateEnrollmentStatus"] == "Failed")
            ):
                self.rdmc.ui.printer("Auto enrolment Enable/Disable operation successful \n")
                return ReturnCodes.SUCCESS
            elif results.status == 400:
                self.rdmc.ui.error(
                    "There was a problem with auto enroll, Please check whether Scep CA cert is imported \t\n"
                )

                return ReturnCodes.SCEP_ENABLED_ERROR
            else:
                self.rdmc.ui.error(
                    "There was a problem with auto enroll, Plese Check the Url/Password whether it is correct\n"
                )
                return ReturnCodes.SCEP_ENABLED_ERROR
        except IloLicenseError:
            self.rdmc.ui.error("License Error Occured while auto enroll\n")
            return ReturnCodes.ILO_LICENSE_ERROR
        except IdTokenError:
            self.rdmc.ui.printer("Insufficient Privilege to auto enroll scep certificate process\n")
            return ReturnCodes.RIS_MISSING_ID_TOKEN

    def gencsrfunction(self, options):
        """Main Certificates Command function

        :param options: list of options
        :type options: list.
        """
        try:
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
                for item in bodydict["Actions"]:
                    if "GenerateCSR" in item:
                        if self.rdmc.app.typepath.defs.isgen10:
                            action = item.split("#")[-1]
                        else:
                            action = "GenerateCSR"

                        path = bodydict["Actions"][item]["target"]
                        break
            except:
                action = "GenerateCSR"
        except:
            path = "redfish/v1/Managers/1/SecurityService/HttpsCert"
            action = "GenerateCSR"

        body = {
            "Action": action,
            "OrgName": options.gencsr_orgname.strip('"'),
            "OrgUnit": options.gencsr_orgunit.strip('"'),
            "CommonName": options.gencsr_commonname.strip('"'),
            "Country": options.gencsr_country.strip('"'),
            "State": options.gencsr_state.strip('"'),
            "City": options.gencsr_city.strip('"'),
            "IncludeIP": eval(options.gencsr_parser_includeIP.strip('"')),
        }

        try:
            results = self.rdmc.app.post_handler(path, body)
            if results.status == 200:
                return ReturnCodes.SUCCESS
        except ScepenabledError:
            self.rdmc.ui.printer("SCEP is enabled , CSR cant be generated \n")
            return ReturnCodes.SCEP_ENABLED_ERROR
        except IloLicenseError:
            self.rdmc.ui.error("License Error Occured while generating CSR")
            return ReturnCodes.ILO_LICENSE_ERROR
        except IdTokenError:
            self.rdmc.ui.printer("Insufficient Privilege to generate CSR\n")
            return ReturnCodes.RIS_MISSING_ID_TOKEN

    def deletefunction(self, options):
        """Certificate Delete Function

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

        try:
            results = self.rdmc.app.delete_handler(path, silent=True)
            if results.status == 200:
                self.rdmc.ui.printer("Deleted the https certifcate successfully\n")
                return ReturnCodes.SUCCESS
            if results.status == 403:
                self.rdmc.ui.error("Insufficient Privilege to delete certificate\n")
                return ReturnCodes.RIS_MISSING_ID_TOKEN
            if results.status == 400:
                self.rdmc.ui.error("SCEP is enabled , Cant delete the certificate\n")
                return ReturnCodes.SCEP_ENABLED_ERROR
        except IloLicenseError:
            self.rdmc.ui.error("License Error Occured while delete")
            return ReturnCodes.ILO_LICENSE_ERROR
        except IncompatibleiLOVersionError:
            self.rdmc.ui.error("iLO FW version on this server doesnt support this operation")
            return ReturnCodes.INCOMPATIBLE_ILO_VERSION_ERROR

    def viewfunction(self, options):
        """View scep certifcates or https certificates

        :param options: list of options
        :type options: list.
        """

        if options.scep_cert:
            if self.rdmc.app.typepath.defs.isgen10:
                self.view_scepcertificate()  # View scep certificates
            else:
                self.rdmc.ui.printer("Feature not supported on Gen 9\n")
                return ReturnCodes.SUCCESS
        if options.https_cert:
            self.view_httpscertificate()  # View https certificates

    def view_scepcertificate(self):
        """
        View Scep certificate
        """
        select = self.rdmc.app.typepath.defs.securityservice
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
            for item in bodydict["Links"]:
                if "AutomaticCertificateEnrollment" in item:
                    path = bodydict["Links"]["AutomaticCertificateEnrollment"]["@odata.id"]
                    break
        except:
            path = path + "AutomaticCertificateEnrollment"

        try:
            results = self.rdmc.app.get_handler(path, silent=True)
            if results.status == 200:
                self.rdmc.ui.printer("Scep Certificate details ...\n")
                results = results.dict
                self.print_cert_info(results)
                return ReturnCodes.SUCCESS

        except IloLicenseError:
            self.rdmc.ui.error("Error Occured while Uninstall")
            return ReturnCodes.ILO_LICENSE_ERROR

    def print_cert_info(self, results):
        """
        Prints the cert info
        """
        for key, value in results.items():
            if "@odata" not in key:
                if type(value) is dict:
                    self.print_cert_info(value)
                else:
                    self.rdmc.ui.printer(key + ":" + str(value) + "\n")

    def view_httpscertificate(self):
        """
        View Https certificate
        """
        try:
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
        except:
            path = "redfish/v1/Managers/1/SecurityService/HttpsCert"

        try:
            results = self.rdmc.app.get_handler(path, silent=True)
            if results.status == 200:
                self.rdmc.ui.printer("Https Certificate details ...\n")
                results = results.dict
                self.print_cert_info(results)
                return ReturnCodes.SUCESS
        except IloLicenseError:
            self.rdmc.ui.error("Error Occured while Uninstall")
            return ReturnCodes.ILO_LICENSE_ERROR

    def exportfunction(self, options):
        result = self.exportplatformhelper(options)

        if result:
            if options.filename:
                self.file_handler(next(iter(options.filename)), result, options, "wb")
                self.rdmc.ui.printer("The certificate was saved to: %s\n" % next(iter(options.filename)))
                return ReturnCodes.SUCCESS
            else:
                self.rdmc.ui.printer("The certificate retrieved is as follows:\n%s\n" % result)
                return ReturnCodes.SUCCESS
        else:
            raise NoContentsFoundForOperationError("An error occurred retrieving the requested certificate.\n")

    def exportplatformhelper(self, options):
        """Helper function for exporting a platform certificate
        :param options: list of options
        :type options: list.
        """

        str_type = "PlatformCert"
        ss_instance = next(iter(self.rdmc.app.select("SecurityService." + ".", path_refresh=True)))
        if options.ldevid_cert:
            str_type = "iLOLDevID"
        elif options.idevid_cert:
            str_type = "iLOIDevID"
        elif options.systemiak_cert:
            str_type = "SystemIAK"
        elif options.systemidevid_cert:
            str_type = "SystemIDevID"
        instance_path_uri = (
            (ss_instance.dict[str_type]["Certificates"][self.rdmc.app.typepath.defs.hrefstring])
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
                "Unable to find specified certificate at " "position %s." % getattr(options, "id", 0)
            )

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

        if operation in writeable_ops:
            with open(filename, operation) as fh:
                try:
                    data = data.encode("UTF-8")
                except IOError:
                    raise InvalidFileInputError("Unable to write to file '%s'" % filename)
                except UnicodeEncodeError:
                    pass
                finally:
                    fh.write(data)
        else:
            with open(filename, operation) as fh:
                fdata = fh.read()
                try:
                    return fdata.decode("UTF-8")
                except UnicodeDecodeError:
                    return fdata
                except IOError:
                    raise InvalidFileInputError("Unable to read from file '%s'" % filename)

    def importfunction(self, options):
        if self.rdmc.app.typepath.defs.isgen10:
            return self.importfunctionhelper(options)
        else:
            self.rdmc.ui.printer("Gen 9 doesnt support this feature\n")
            return ReturnCodes.SUCCESS

    def importscephelper(self, options):
        """
        Import Scep certificate
        """
        select = self.rdmc.app.typepath.defs.securityservice
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
            for item in bodydict["Links"]:
                if "AutomaticCertificateEnrollment" in item:
                    path = bodydict["Links"]["AutomaticCertificateEnrollment"]["@odata.id"]
                    break
        except:
            path = path + "AutomaticCertificateEnrollment"

        path = path + "Actions/HpeAutomaticCertEnrollment.ImportCACertificate"

        action = "HpeAutomaticCertEnrollment.ImportCACertificate"

        certdata = None
        scep_CACert = options.certfile

        try:
            with open(scep_CACert) as certfile:
                certdata = certfile.read()
                certfile.close()
        except:
            pass

        body = {"Action": action, "Certificate": certdata}

        try:
            result = self.rdmc.app.post_handler(path, body)
            if result.status == 200:
                self.rdmc.ui.printer("Imported the scep certificate successfully\n")
                return ReturnCodes.SUCCESS
        except IdTokenError:
            self.rdmc.ui.printer("Insufficient Privilege to import scep CA certificate\n")
            return ReturnCodes.RIS_MISSING_ID_TOKEN
        except IloLicenseError:
            self.rdmc.ui.error("Error Occured while importing scep certificate")
            return ReturnCodes.ILO_LICENSE_ERROR
        except IncompatibleiLOVersionError:
            self.rdmc.ui.error("iLO FW version on this server doesnt support this operation")
            return ReturnCodes.INCOMPATIBLE_ILO_VERSION_ERROR

    def importfunctionhelper(self, options):
        result = None
        if getattr(options, "scep_cert"):
            result = self.importscephelper(options)
        elif getattr(options, "ca_cert"):
            result = self.importcahelper(options)
        elif getattr(options, "crl_cert"):
            result = self.importcrlhelper(options)
        elif getattr(options, "tls_cert"):
            result = self.importtlshelper(options)
        elif (
            getattr(options, "ldevid_cert")
            or getattr(options, "idevid_cert")
            or getattr(options, "systemiak_cert")
            or getattr(options, "systemidevid_cert")
            or getattr(options, "platform_cert")
        ):
            result = self.importplatformhelper(options)

        return result

    def generatecerthelper(self, options):
        """Main Certificates Command function

        :param options: list of options
        :type options: list.
        """
        self.rdmc.ui.printer(
            "Warning:Command CSR has been replaced with Gen_csr comamnd and "
            "CSR command will be deprecated in next release of our tool. Please plan to use gen_csr command instead \n"
        )
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
            for item in bodydict["Actions"]:
                if "GenerateCSR" in item:
                    if self.rdmc.app.typepath.defs.isgen10:
                        action = item.split("#")[-1]
                    else:
                        action = "GenerateCSR"

                    path = bodydict["Actions"][item]["target"]
                    break
        except:
            action = "GenerateCSR"

        body = {
            "Action": action,
            "OrgName": options.csr_orgname.strip('"'),
            "OrgUnit": options.csr_orgunit.strip('"'),
            "CommonName": options.csr_commonname.strip('"'),
            "Country": options.csr_country.strip('"'),
            "State": options.csr_state.strip('"'),
            "City": options.csr_city.strip('"'),
        }

        self.rdmc.ui.printer(
            "iLO is creating a new certificate signing request. " "This process can take up to 10 minutes.\n"
        )

        try:
            self.rdmc.app.post_handler(path, body)
            return ReturnCodes.SUCCESS
        except ScepenabledError:
            self.rdmc.ui.printer("SCEP is enabled , operation not allowed \n")
            return ReturnCodes.SCEP_ENABLED_ERROR

    def getcerthelper(self, options):
        """Helper function for importing CRL certificate

        :param options: list of options
        :type options: list.
        """

        select = self.rdmc.app.typepath.defs.hphttpscerttype
        results = self.rdmc.app.select(selector=select, path_refresh=True)

        try:
            results = results[0]
        except:
            pass

        if results:
            try:
                csr = results.resp.dict["CertificateSigningRequest"]
                if not csr:
                    raise ValueError
            except (KeyError, ValueError):
                raise NoContentsFoundForOperationError(
                    "Unable to find a valid certificate. If "
                    "you just generated a new certificate "
                    "signing request the process may take "
                    "up to 10 minutes."
                )

            if not options.filename:
                filename = __filename__
            else:
                filename = options.filename[0]

            outfile = open(filename, "w")
            outfile.write(csr)
            outfile.close()

            self.rdmc.ui.printer("Certificate saved to: %s\n" % filename)
            return ReturnCodes.SUCCESS
        else:
            raise NoContentsFoundForOperationError("Unable to find %s" % select)

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
            if not options.filename:
                filename = __filename__
            else:
                filename = options.filename[0]

            outfile = open(filename, "w")
            outfile.write(result)
            outfile.close()
            self.rdmc.ui.printer("Certificate saved to: %s\n" % filename)
            return ReturnCodes.SUCCESS
        else:
            self.rdmc.ui.error(
                "An error occurred retrieving a CSR. Check whether CSR is requested , "
                "if not kindly run gen_csr command and generate CSR"
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
            _ = next(iter(self.rdmc.app.select("CertificateService.", path_refresh=True)))
            ss_instance = next(iter(self.rdmc.app.select("SecurityService.", path_refresh=True)))
            cert_obtain_path = ss_instance.dict.get("iLOLDevID")[next(iter(ss_instance.dict.get("iLOLDevID")))].get(
                self.rdmc.app.typepath.defs.hrefstring
            )
            if not cert_obtain_path:
                raise NoContentsFoundForOperationError("Unable to find specified certificate path" " for CSR request")
            instance = next(iter(self.rdmc.app.select("CertificateService.", path_refresh=True)))
            body = {"CertificateCollection": {self.rdmc.app.typepath.defs.hrefstring: cert_obtain_path}}

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
            raise NoContentsFoundForOperationError("Unable to find specified certificate action" "path for CSR request")

        self.rdmc.ui.printer(
            "iLO is creating a new certificate signing request. " "This request may take up to 10 minutes.\n"
        )
        return self.rdmc.app.post_handler(path, body)

    def importtlshelper(self, options):
        """Helper function for importing TLS certificate

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
            for item in bodydict["Actions"]:
                if "ImportCertificate" in item:
                    if self.rdmc.app.typepath.defs.isgen10:
                        action = item.split("#")[-1]
                    else:
                        action = "ImportCertificate"
                    path = bodydict["Actions"][item]["target"]
                    break
        except:
            action = "ImportCertificate"

        body = {"Action": action, "Certificate": certdata}

        try:
            result = self.rdmc.app.post_handler(path, body)
            if result.status == 200:
                self.rdmc.ui.printer("Imported the TLS certificate successfully\n")
                return ReturnCodes.SUCCESS
        except IdTokenError:
            self.rdmc.ui.printer("Insufficient Privilege to import TLS certificate\n")
            return ReturnCodes.RIS_MISSING_ID_TOKEN
        except ScepenabledError:
            self.rdmc.ui.printer("SCEP is enabled , operation not allowed \n")
            return ReturnCodes.SCEP_ENABLED_ERROR
        except IloLicenseError:
            self.rdmc.ui.error("Error occurred while importing TLS certificate")
            return ReturnCodes.ILO_LICENSE_ERROR
        except IncompatibleiLOVersionError:
            self.rdmc.ui.error("iLO FW version on this server doesnt support this operation")
            return ReturnCodes.INCOMPATIBLE_ILO_VERSION_ERROR

    def importcrlhelper(self, options):
        """Helper function for importing CRL certificate

        :param options: list of options
        :type options: list.
        """
        if not self.rdmc.app.typepath.flagiften:
            raise IncompatibleiLOVersionError("This certificate is not available on this system.")

        select = "HpeCertAuth."
        results = self.rdmc.app.select(selector=select)

        try:
            results = results[0]
        except:
            pass

        if results:
            bodydict = results.resp.dict
        else:
            raise NoContentsFoundForOperationError("Unable to find %s" % select)

        for item in bodydict["Actions"]:
            if "ImportCRL" in item:
                action = item.split("#")[-1]
                path = bodydict["Actions"][item]["target"]
                break

        body = {"Action": action, "ImportUri": options.certfile}
        # self.rdmc.app.post_handler(path, body)
        try:
            result = self.rdmc.app.post_handler(path, body)
            if result.status == 200:
                self.rdmc.ui.printer("Imported the CRL certificate successfully\n")
                return ReturnCodes.SUCCESS
        except IdTokenError:
            self.rdmc.ui.printer("Insufficient Privilege to import CRL certificate\n")
            return ReturnCodes.RIS_MISSING_ID_TOKEN
        except IloLicenseError:
            self.rdmc.ui.error("Error Occured while importing CRL certificate")
            return ReturnCodes.ILO_LICENSE_ERROR
        except IncompatibleiLOVersionError:
            self.rdmc.ui.error("iLO FW version on this server doesnt support this operation")
            return ReturnCodes.INCOMPATIBLE_ILO_VERSION_ERROR

    def importcahelper(self, options):
        """Helper function for importing CA certificate

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

        select = "HpeCertAuth."
        results = self.rdmc.app.select(selector=select)

        try:
            results = results[0]
        except:
            pass

        if results:
            bodydict = results.resp.dict
        else:
            raise NoContentsFoundForOperationError("Unable to find %s" % select)

        for item in bodydict["Actions"]:
            if "ImportCACertificate" in item:
                action = item.split("#")[-1]
                path = bodydict["Actions"][item]["target"]
                break

        body = {"Action": action, "Certificate": certdata}

        try:
            result = self.rdmc.app.post_handler(path, body)
            if result.status == 200:
                self.rdmc.ui.printer("Imported the CA certificate successfully\n")
                return ReturnCodes.SUCCESS
        except IdTokenError:
            self.rdmc.ui.printer("Insufficient Privilege to import CA certificate\n")
            return ReturnCodes.RIS_MISSING_ID_TOKEN
        except IloLicenseError:
            self.rdmc.ui.error("Error occurred while importing CA certificate")
            return ReturnCodes.ILO_LICENSE_ERROR
        except IncompatibleiLOVersionError:
            self.rdmc.ui.error("iLO FW version on this server doesnt support this operation")
            return ReturnCodes.INCOMPATIBLE_ILO_VERSION_ERROR

    def importplatformhelper(self, options):
        """Helper function for importing a platform certificate
        :param options: options attributes
        :type options: attributes
        """

        # ss_instance = next(
        #     iter(self.rdmc.app.select("SecurityService.", path_refresh=True))
        # )
        if getattr(options, "ldevid_cert"):
            instance_path_uri = "/redfish/v1/Managers/1/Diagnostics/Actions/HpeiLODiagnostics.ImportiLOLDevID"
        else:
            ss_instance = self.rdmc.app.get_handler("/redfish/v1/Managers/1/Diagnostics/", service=True, silent=True)
            instance_path_uri = None

        if getattr(options, "ldevid_cert"):
            type = "iLOLDevID"
        elif getattr(options, "idevid_cert"):
            type = "iLOIDevID"
        elif getattr(options, "systemiak_cert"):
            type = "SystemIAK"
        elif getattr(options, "systemidevid_cert"):
            type = "SystemIDevID"
        elif getattr(options, "platform_cert"):
            type = "PlatformCert"
        else:
            raise InvalidCommandLineErrorOPTS(
                "An invalid set of options were selected...verify " " options were selected correctly and re-try."
            )
        type_totarget = "#HpeiLODiagnostics.Import" + type

        if not instance_path_uri:
            instance_path_uri = ss_instance.dict["Actions"][type_totarget]["target"]

        # instance_path_uri = (
        #     (
        #         ss_instance.dict[type]["Certificates"][
        #             self.rdmc.app.typepath.defs.hrefstring
        #         ]
        #     )
        #     if ss_instance.dict.get("SystemIAK")
        #     else None
        # )
        if instance_path_uri:
            certdata = None
            try:
                with open(options.certfile) as cf:
                    certdata = cf.read()
            except:
                raise InvalidFileInputError("Error loading the specified file.")

            payload = {"Certificate": certdata}

            if certdata:
                try:
                    result = self.rdmc.app.post_handler(instance_path_uri, payload)
                    if result.status == 200:
                        self.rdmc.ui.printer("Imported the %s certificate successfully\n" % type)
                        return ReturnCodes.SUCCESS
                except IdTokenError:
                    self.rdmc.ui.printer("Insufficient Privilege to import %s certificate\n" % type)
                    return ReturnCodes.RIS_MISSING_ID_TOKEN
                except IloLicenseError:
                    self.rdmc.ui.error("Error Occured while importing %s certificate\n" % type)
                    return ReturnCodes.ILO_LICENSE_ERROR
                except IncompatibleiLOVersionError:
                    self.rdmc.ui.error("iLO FW version on this server doesnt support this operation")
                    return ReturnCodes.INCOMPATIBLE_ILO_VERSION_ERROR

    def certificatesvalidation(self, options):
        """certificates validation function

        :param options: command line options
        :type options: list.
        """
        self.cmdbase.login_select_validation(self, options)

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
        gen_csr_help = "Please use the below example command to execute the same function."
        gen_csr_parser = subcommand_parser.add_parser(
            "csr",
            help=gen_csr_help,
            description=gen_csr_help + "\nexample: certificate gen_csr [ORG_NAME] [ORG_UNIT]"
            " [COMMON_NAME] [COUNTRY] [STATE] [CITY]\n\nNOTE: please make "
            "certain the order of arguments is correct.",
            formatter_class=RawDescriptionHelpFormatter,
        )
        gen_csr_parser.add_argument(
            "csr_orgname",
            help="Organization name. i.e. Hewlett Packard Enterprise.",
            metavar="ORGNAME",
        )
        gen_csr_parser.add_argument(
            "csr_orgunit",
            help="Organization unit. i.e. Intelligent Provisioning.",
            metavar="ORGUNIT",
        )
        gen_csr_parser.add_argument(
            "csr_commonname",
            help="Organization common name. i.e. Common Organization Name.",
            metavar="ORGCNAME",
        )
        gen_csr_parser.add_argument(
            "csr_country",
            help="Organization country. i.e. United States.",
            metavar="ORGCOUNTRY",
        )
        gen_csr_parser.add_argument("csr_state", help="Organization state. i.e. Texas.", metavar="ORGSTATE")
        gen_csr_parser.add_argument("csr_city", help="Organization city. i.e. Houston.", metavar="ORGCITY")
        self.cmdbase.add_login_arguments_group(gen_csr_parser)

        # get csr
        get_csr_help = (
            "Retrieve the generated certificate signing request (CSR) printed to the " "console or to a json file."
        )
        get_csr_parser = subcommand_parser.add_parser(
            "getcsr",
            help=get_csr_help,
            description=get_csr_help
            + "\nexample: certificate getcsr\nexample: certificate getcsr  --TLS_CERT/--PLATFORM_CERT"
            "-f mycsrfile.json",
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
            help="Use this flag if you wish to use a different"
            " filename for the certificate signing request. The default"
            " filename is %s." % __filename__,
            action="append",
            default=None,
        )
        self.cmdbase.add_login_arguments_group(get_csr_parser)

        # ca certificate
        ca_help = "This command has been deprecated. Please use the below example command to execute the same function."
        ca_parser = subcommand_parser.add_parser(
            "ca",
            help=ca_help,
            description=ca_help + "\nexample: certificate import --ca_cert mycertfile.txt\nNote: The "
            "certificate must be in X.509 format",
            formatter_class=RawDescriptionHelpFormatter,
        )
        ca_parser.add_argument("certfile", help="X.509 formatted CA certificate", metavar="CACERTFILE")
        self.cmdbase.add_login_arguments_group(ca_parser)

        # crl certificate
        crl_help = (
            "This command has been deprecated. Please use the below example command to execute the same function."
        )
        crl_parser = subcommand_parser.add_parser(
            "crl",
            help=crl_help,
            description=crl_help + "\nexample: certificate import --crl_cert https://mycertfileurl/mycertfile.txt"
            "\nNote: The certificate must be in X.509 format",
            formatter_class=RawDescriptionHelpFormatter,
        )
        crl_parser.add_argument(
            "certfile_url",
            help="URL pointing to the location of the X.509 CA certificate",
            metavar="CERTFILEURL",
        )
        self.cmdbase.add_login_arguments_group(crl_parser)

        # tls certificate
        tls_help = (
            "This command has been deprecated. Please use the below example command to execute the same function."
        )
        tls_parser = subcommand_parser.add_parser(
            "tls",
            help=tls_help,
            description=tls_help + "\nexample: certificate import --tls_cert mycertfile.txt\nNote: The "
            "certificate must be in TLS X.509 format",
            formatter_class=RawDescriptionHelpFormatter,
        )
        tls_parser.add_argument("certfile", help="X.509 formatted TLS certificate", metavar="TLSCERTFILE")
        self.cmdbase.add_login_arguments_group(tls_parser)

        # view certificate
        view_help = "View Certificates (https or scep)"
        view_parser = subcommand_parser.add_parser(
            "view",
            help=view_help,
            description=view_help
            + "\nexample: certificate view --https_cert  \n or \n certificate view --scep_cert \n"
            + "Webserver certificate whether self-signed or manually imported or issued by SCEP server can be viewed",
            formatter_class=RawDescriptionHelpFormatter,
        )
        view_parser.add_argument(
            "--scep_cert",
            dest="scep_cert",
            help="Gets the information of SCEP settings for iLO such as SCEP enable status, URL of the SCEP server,"
            + " ChallengePassword, SCEP CA certificate name, webserver CSR subject contents, SCEP enrollment status",
            action="store_true",
        )
        view_parser.add_argument(
            "--https_cert",
            dest="https_cert",
            help="Gets the https certificate whether self-signed or manually imported or issued by SCEP server",
            action="store_true",
        )
        self.cmdbase.add_login_arguments_group(view_parser)

        # import certificate
        import_help = "Imports the Certificates."
        import_parser = subcommand_parser.add_parser(
            "import",
            help=import_help,
            description=import_help
            + "\nexample: certificate import --scep_cert certificate.txt \n"
            + " make sure you are providing a .txt file input.\n",
            formatter_class=RawDescriptionHelpFormatter,
        )
        import_parser.add_argument(
            "--scep_cert",
            dest="scep_cert",
            help="Gets the https certificate whether self-signed or manually imported or issued by SCEP server",
            action="store_true",
        )
        import_parser.add_argument(
            "--ca_cert",
            dest="ca_cert",
            help="Upload a X.509 formatted CA certificate to iLO.",
            action="store_true",
        )
        import_parser.add_argument(
            "--crl_cert",
            dest="crl_cert",
            help="Provide iLO with a URL to retrieve the X.509 formatted CA certificate.",
            action="store_true",
        )
        import_parser.add_argument(
            "--tls_cert",
            dest="tls_cert",
            help="Upload a X.509 TLS certificate to iLO.",
            action="store_true",
        )
        import_parser.add_argument(
            "--idevid_cert",
            dest="idevid_cert",
            help="Upload an IDEVID certificate.",
            action="store_true",
        )
        import_parser.add_argument(
            "--ldevid_cert",
            dest="ldevid_cert",
            help="Upload an LDEVID certificate.",
            action="store_true",
        )
        import_parser.add_argument(
            "--systemiak_cert",
            dest="systemiak_cert",
            help="Upload an System IAK certificate.",
            action="store_true",
        )
        import_parser.add_argument(
            "--systemidevid_cert",
            dest="systemidevid_cert",
            help="Upload an system IDEVID certificate.",
            action="store_true",
        )
        import_parser.add_argument(
            "--platform_cert",
            dest="platform_cert",
            help="Upload a platform certificate.",
            action="store_true",
        )
        import_parser.add_argument(
            "--from_url",
            dest="from_url",
            help="Use this flag to specify a URL for certificate import",
            action="append",
            default=None,
        )
        import_parser.add_argument(
            "certfile",
            help="Certificate can be imported via POST action",
            metavar="certfile",
        )
        self.cmdbase.add_login_arguments_group(import_parser)

        # export cert
        export_help = "Pull an X.509 formatted platform certificate from iLO."
        export_parser = subcommand_parser.add_parser(
            "export",
            help=export_help,
            description=export_help + "\nExample: certificate export --IDEVID -f " "myidevidfile\n",
            formatter_class=RawDescriptionHelpFormatter,
        )

        export_parser.add_argument(
            "--idevid_cert",
            dest="idevid_cert",
            help="Specify for an IDEVID certificate. ",
            action="store_true",
            default=None,
        )
        export_parser.add_argument(
            "--ldevid_cert",
            dest="ldevid_cert",
            help="Specify for an LDEVID certificate. ",
            action="store_true",
            default=None,
        )
        export_parser.add_argument(
            "--systemiak_cert",
            dest="systemiak_cert",
            help="Specify for a system IAK certificate.",
            action="store_true",
            default=None,
        )
        export_parser.add_argument(
            "--systemidevid_cert",
            dest="systemidevid_cert",
            help="Specify for a system IDEVID certificate.",
            action="store_true",
            default=None,
        )
        export_parser.add_argument(
            "--platform_cert",
            dest="platform_cert",
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
        export_parser.add_argument(
            "-f",
            "--filename",
            dest="filename",
            help="Use this flag to import a certificate from or export a certificate to a file.",
            action="append",
            default=None,
        )

        self.cmdbase.add_login_arguments_group(export_parser)

        # delete certificate
        delete_help = "Deletes the https Certificate"
        delete_parser = subcommand_parser.add_parser(
            "delete",
            help=delete_help,
            description=delete_help + "\nexample: certificate delete \n  delete the https_cert certificate ",
            formatter_class=RawDescriptionHelpFormatter,
        )

        self.cmdbase.add_login_arguments_group(delete_parser)

        # gen csr sub-parser
        gencsr_help = (
            "Generate a certificate signing request (CSR) for iLO SSL certificate "
            "authentication.\nNote: iLO will create a Base64 encoded CSR in PKCS "
            "#10 Format."
        )
        gencsr_parser = subcommand_parser.add_parser(
            "gen_csr",
            help=gencsr_help,
            description=gen_csr_help + "\nexample: certificate gen_csr [ORG_NAME] [ORG_UNIT]"
            " [COMMON_NAME] [COUNTRY] [STATE] [CITY] [INCLUDEIP] \n\nNOTE: please make "
            "certain the order of arguments is correct.",
            formatter_class=RawDescriptionHelpFormatter,
        )
        gencsr_parser.add_argument(
            "gencsr_orgname",
            help="Organization name. i.e. Hewlett Packard Enterprise.",
            metavar="ORGNAME",
        )
        gencsr_parser.add_argument(
            "gencsr_orgunit",
            help="Organization unit. i.e. Intelligent Provisioning.",
            metavar="ORGUNIT",
        )
        gencsr_parser.add_argument(
            "gencsr_commonname",
            help="Organization common name. i.e. Common Organization Name.",
            metavar="ORGCNAME",
        )
        gencsr_parser.add_argument(
            "gencsr_country",
            help="Organization country. i.e. United States.",
            metavar="ORGCOUNTRY",
        )
        gencsr_parser.add_argument("gencsr_state", help="Organization state. i.e. Texas.", metavar="ORGSTATE")
        gencsr_parser.add_argument("gencsr_city", help="Organization city. i.e. Houston.", metavar="ORGCITY")
        gencsr_parser.add_argument(
            "gencsr_parser_includeIP",
            help="Include IP. i.e. True or False.",
            metavar="INCLUDEIP",
        )
        self.cmdbase.add_login_arguments_group(gencsr_parser)

        # automatic enrollment sub-parser
        autoenroll_help = (
            "Use this command for invoking the auto enroll the certificate enrollment process"
            "\nMake sure you have imported the scep CA certificate "
            "before head using certificate import --scep certifcate.txt"
        )
        autoenroll_parser = subcommand_parser.add_parser(
            "auto_enroll",
            help=autoenroll_help,
            description=autoenroll_help + "\nexample: certificate auto_enroll [ORG_NAME] [ORG_UNIT]"
            " [COMMON_NAME] [COUNTRY] [STATE] [CITY] [SCEP_ADDRESS] [CHALLENGEPASSWORD] "
            "[SERVICEENABLED] [INCLUDEIP]]\n\nNOTE: please make "
            "certain the order of arguments is correct.",
            formatter_class=RawDescriptionHelpFormatter,
        )
        autoenroll_parser.add_argument(
            "autoenroll_orgname",
            help="Organization name. i.e. Hewlett Packard Enterprise.",
            metavar="ORGNAME",
        )
        autoenroll_parser.add_argument(
            "autoenroll_orgunit",
            help="Organization unit. i.e. Intelligent Provisioning.",
            metavar="ORGUNIT",
        )
        autoenroll_parser.add_argument(
            "autoenroll_commonname",
            help="Organization common name. i.e. Common Organization Name.",
            metavar="ORGCNAME",
        )
        autoenroll_parser.add_argument(
            "autoenroll_country",
            help="Organization country. i.e. United States.",
            metavar="ORGCOUNTRY",
        )
        autoenroll_parser.add_argument("autoenroll_state", help="Organization state. i.e. Texas.", metavar="ORGSTATE")
        autoenroll_parser.add_argument("autoenroll_city", help="Organization city. i.e. Houston.", metavar="ORGCITY")
        autoenroll_parser.add_argument(
            "autoenroll_scep_enrollAddress",
            help="Scep-enroll dll address",
            metavar="AEADDRESS",
        )
        autoenroll_parser.add_argument(
            "autoenroll_challengepassword",
            help="challenge password",
            metavar="AECHALLPASS",
        )
        autoenroll_parser.add_argument(
            "autoenroll_ScepService",
            help="Scep service enable or disable",
            metavar="AESCEPSERVICE",
        )
        autoenroll_parser.add_argument(
            "autoenroll_includeIP",
            help="Include IP. i.e. True or False.",
            metavar="INCLUDEIP",
        )
        self.cmdbase.add_login_arguments_group(autoenroll_parser)
