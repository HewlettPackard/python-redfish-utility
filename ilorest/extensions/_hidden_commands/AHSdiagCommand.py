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
""" AHS diag Command for rdmc """

import os
from ctypes import POINTER, c_char_p, c_int, c_ubyte, create_string_buffer

import redfish.hpilo.risblobstore2 as risblobstore2

try:
    from rdmc_helper import (
        LOGGER,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        ReturnCodes,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        LOGGER,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        ReturnCodes,
    )
from redfish.hpilo.rishpilo import HpIlo

if os.name != "nt":
    from _ctypes import dlclose


class AHSdiagCommand:
    """Add Sign/Marker posts into the AHS logs of the server"""

    def __init__(self):
        self.ident = {
            "name": "ahsdiag",
            "usage": None,
            "description": "Adding sign or Marker Post into AHS logs."
            "\n\tahsdiag --WriteSignPost \n\tahsdiag --WriteMarkerPost"
            ' --instance 1 --markervalue 3 --markertext "DIMM Test Start"',
            "summary": "Adding sign or Marker Post into AHS logs.",
            "aliases": ["ahsops"],
            "auxcommands": [
                "LoginCommand",
                "SelectCommand",
                "LogoutCommand",
                "ServerlogsCommand",
            ],
        }

        self.dynamicclass = -1
        self.lib = None
        self.channel = None
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

    def run(self, line, help_disp=False):
        """Main ahsdiag function

        :param line: string of arguments passed in
        :type line: str.
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

        self.ahsdiagvalidation(options)
        self.ahsdiagworkerfunction(options)
        self.cmdbase.logout_routine(self, options)
        return ReturnCodes.SUCCESS

    def ahsdiagworkerfunction(self, options):
        """Main ahsdig worker function

        :param options: command line options
        :type options: list.
        """
        if not options:
            raise InvalidCommandLineErrorOPTS("")

        if self.lib is None and self.channel is None:
            self.resetilo()

        if options.signpost and options.markerpost:
            raise InvalidCommandLineErrorOPTS("")

        if options.signpost:
            if options.inst or options.mval or options.mtext:
                raise InvalidCommandLineError("")
            self.addsignpost(options)
        elif options.markerpost:
            if options.inst and options.mval and options.mtext:
                self.addmarkerpost(options)
            else:
                raise InvalidCommandLineErrorOPTS("")
        else:
            self.rdmc.ui.printer("Choose an operation!\n")
            raise InvalidCommandLineErrorOPTS("")

    def addsignpost(self, options):
        """Function to add signpost

        :param options: command line options
        :type options: list.
        """
        excp = None
        for _ in range(0, 3):  # channel loop for iLO
            self.rdmc.ui.printer("Start writing sign post ... \n")
            try:
                if not self.spregister():
                    raise
                self.rdmc.ui.printer("Successfully registered.\n")
                fail = True

                for _ in range(3):
                    if self.signpostregister():
                        self.rdmc.ui.printer("Signpost was successful!\n")
                        fail = False
                        break
                    else:
                        self.rdmc.ui.printer("Signpost attempt failed!\n")

                if options.postIML and fail:
                    self.addimlpost(options)

                self.unregister()
                return
            except Exception:
                if self.rdmc.opts.verbose:
                    self.rdmc.ui.printer("Retrying with new channel...\n")
                self.resetilo()
        raise excp

    def spregister(self):
        """Function that registers the signpost"""
        self.bb_class_allocate()

        if self.dynamicclass == -1:
            return False

        self.lib.bb_register_wrapper(self.dynamicclass)
        size = self.lib.sizeofbbregister()
        rcode = self.dowriteread(size)

        if rcode == 0:
            self.lib.bb_descriptor_code_wrapper(self.dynamicclass)
            size = self.lib.sizeofbbdescriptorcode()
            rcode = self.dowriteread(size)

        #         if rcode > 0:
        #             return True
        #         else:
        #             return False
        return True

    def bb_class_allocate(self):
        """Function to obtain a handle for further operations"""
        self.lib.bb_class_allocate_wrapper()
        self.lib.getreq.restype = POINTER(c_ubyte)
        ptrreq = self.lib.getreq()

        # sizeofbbchifresp = self.lib.sizeofBBCHIFRESP()
        size = self.lib.sizeofbbclassalloc()
        data = bytearray(ptrreq[:size][:])

        if self.rdmc.opts.debug:
            LOGGER.info("Sending data to chif:{0}\n".format(bytes(data)))

        resp = self.channel.chif_packet_exchange(data)

        resp = create_string_buffer(bytes(resp))
        self.lib.setresp.argtypes = [c_char_p]
        self.lib.setresp(resp)

        if len(resp) != 0:
            self.dynamicclass = self.lib.respmsgrcode()
            self.rdmc.ui.printer("Do Read Return error code:{0}\n".format(self.dynamicclass))
        else:
            self.dynamicclass = 0

    def unregister(self):
        """Function to unregister the handle"""
        self.lib.bb_unregister_wrapper()
        size = self.lib.sizeinunregister()
        rcode = self.dowriteread(size)

        if rcode == 0:
            self.rdmc.ui.printer("Unregistration successful!\n")
        else:
            self.rdmc.ui.printer("Failed to unregister with code:{0}.\n".format(rcode))

    def dowriteread(self, size):
        """Function responsible for communication with the iLO

        :param size: size of the buffer to be read or written
        :type size: int
        """
        ptrreq = self.lib.getreq()
        data = bytearray(ptrreq[:size][:])
        if self.rdmc.opts.debug:
            LOGGER.info("Sending data to chif:{0}\n".format(data))
        try:
            resp = self.channel.chif_packet_exchange(data)
        except Exception:
            self.resetilo()
            return -1

        self.lib.setresp.argtypes = [c_char_p]
        resp = create_string_buffer(bytes(resp))
        self.lib.setresp(resp)
        rcode = self.lib.respmsgrcode()

        if rcode == 0:
            self.lib.updatehandle()

        return rcode

    def signpostregister(self):
        """Worker function of signpost register"""
        self.lib.bb_code_set_wrapper()
        size = self.lib.sizeinbbcodeset()
        returnval = self.dowriteread(size)

        if returnval != 0:
            self.printsignpostregister(returnval)
            return False

        self.lib.bb_log_wrapper()
        size = self.lib.sizeinbblog()
        returnval = self.dowriteread(size)

        if returnval != 0:
            self.printsignpostregister(returnval)
            return False

        self.lib.bb_log_static_wrapper()
        size = self.lib.sizeinbblog()
        returnval = self.dowriteread(size)

        if returnval != 0:
            self.printsignpostregister(returnval)
            return False

        return True

    def printsignpostregister(self, returnval):
        """Commonly used output statement.

        :param returnval: return code for signpost
        :type returnval: int
        """
        self.rdmc.ui.printer("return signpost register failed={0}\n".format(returnval))

    def addmarkerpost(self, options):
        """Function to add marker post

        :param options: command line options
        :type options: list.
        """
        excp = None
        for _ in range(0, 3):  # channel loop for iLO
            self.rdmc.ui.printer("Start writing marker post ... \n")

            try:
                for i in range(3):
                    if self.mpregister():
                        break

                    self.rdmc.ui.printer("attempting to register Marker Post..." "failed {0} times\n".format(i + 1))

                    self.resetilo()

                self.rdmc.ui.printer("Successfully registered.\n")
                fail = True

                for _ in range(3):
                    if self.markerpostregister(options):
                        self.rdmc.ui.printer("Marker Post was successful!\n")
                        fail = False
                        break
                    else:
                        self.rdmc.ui.printer("Marker Post attempt failed!\n")

                if options.postIML and fail:
                    self.addimlpost(options)

                self.unregister()
                return
            except Exception:
                if self.rdmc.opts.verbose:
                    self.rdmc.ui.printer("Retrying with new channel...\n")
                self.resetilo()
        raise excp

    def mpregister(self):
        """Function that registers the marker post"""
        self.bb_class_allocate()
        self.rdmc.ui.printer("return code(dynamic class)={0}.\n".format(self.dynamicclass))

        if self.dynamicclass == -1:
            return False

        self.lib.bb_register_mwrapper(self.dynamicclass)
        size = self.lib.sizeofbbregister()
        rcode = self.dowriteread(size)

        if rcode == 0:
            self.lib.bb_descriptor_code_mwrapper(self.dynamicclass)
            size = self.lib.sizeofbbdescriptorcode()
            rcode = self.dowriteread(size)

            if rcode == -1:
                return False
            self.lib.bb_descriptor_field_mwrapper(self.dynamicclass)
            size = self.lib.sizeofbbdescriptorcode()
            rcode = self.dowriteread(size)
            if rcode == -1:
                return False

        return True

    def markerpostregister(self, options):
        """Worker function of marker post register

        :param options: command line options
        :type options: list.
        """
        self.lib.bb_code_set_mwrapper()
        size = self.lib.sizeinbbcodeset()
        returnval = self.dowriteread(size)

        if returnval != 0:
            return False

        mval = int(options.mval)
        minst = int(options.inst)
        mtext = create_string_buffer(bytes(options.mtext, "utf-8"))

        self.lib.markerpost_wrapper.argtypes = [c_int, c_int, c_char_p]
        self.lib.markerpost_wrapper(mval, minst, mtext)

        size = self.lib.sizeinbblogm()
        returnval = self.dowriteread(size)

        if returnval != 0:
            return False

        return True

    def resetilo(self):
        """Function to reset iLO"""
        if self.channel:
            self.channel.close()
        self.loadlib()
        self.channel = HpIlo(dll=self.lib)
        self.lib.ChifDisableSecurity()

    def loadlib(self):
        """Function to load the so library"""
        self.closedll()
        try:
            if os.name == "nt":
                self.rdmc.ui.printer("Operation can be performed only on Unix based systems!\n")
                raise InvalidCommandLineErrorOPTS("")
            else:
                self.lib = risblobstore2.BlobStore2.gethprestchifhandle()
        except Exception as excp:
            raise InvalidCommandLineErrorOPTS(excp)

    def closedll(self):
        """Deallocate dll handle."""
        try:
            dlclose(self.lib)
        except Exception:
            pass

    def addimlpost(self, options):
        """Adding maintenance post from serverlogs.

        :param options: command line options
        :type options: list.
        """
        if options.signpost:
            imltext = "Signpost Writing Failed"
        elif options.markerpost:
            imltext = "Markerpost Writing Failed"

        options.service = "IML"
        options.clearlog = None
        options.mainmes = imltext

        path = self.serverlogsobj.returnimlpath()
        self.serverlogsobj.addmaintenancelogentry(options, path=path)

    def ahsdiagvalidation(self, options):
        """ahsdiag method validation function"""
        client = None

        try:
            self.cmdbase.login_select_validation(self, options)
            client = self.rdmc.app.current_client
        except Exception:
            if client:
                if not client.base_url == "blobstore://.":
                    raise InvalidCommandLineError("ahsdiag command " "available in local mode only.\n")

            if self.rdmc.config.url:
                raise InvalidCommandLineError("ahsdiag command " "available in local mode only.\n")

            if not client:
                self.lobobj.run("")

    def definearguments(self, customparser):
        """Defines the required arguments for ahsdiag command.

        :param customparser: command line input
        :type customparser: parser.
        """
        if not customparser:
            return

        self.cmdbase.add_login_arguments_group(customparser)

        customparser.add_argument(
            "--selectlog",
            dest="service",
            help="""Read log from the given log service. Options: IML, """ """IEL or AHS.""",
            default=None,
        )
        customparser.add_argument(
            "--clearlog",
            "-c",
            dest="clearlog",
            action="store_true",
            help="""Clears the logs for a the selected option.""",
            default=None,
        )
        customparser.add_argument(
            "--maintenancemessage",
            "-m",
            dest="mainmes",
            help="""Maintenance message to be inserted into the log. """ """(IML LOGS ONLY FEATURE)""",
            default=None,
        )
        customparser.add_argument(
            "--customiseAHS",
            dest="customiseAHS",
            help="""Allows customised AHS log data to be downloaded.""",
            default=None,
        )
        customparser.add_argument(
            "-s",
            "--WriteSignPost",
            dest="signpost",
            action="store_true",
            help="""Writes a sign post into the AHS log.""",
            default=False,
        )
        customparser.add_argument(
            "-r",
            "--WriteMarkerPost",
            dest="markerpost",
            action="store_true",
            help="""Writes a marker post into the AHS log.""",
            default=False,
        )
        customparser.add_argument(
            "-i",
            "--instance",
            dest="inst",
            help="""Argument required by marker post.""",
            default=None,
        )
        customparser.add_argument(
            "-l",
            "--markervalue",
            dest="mval",
            help="""Argument required by marker post.""",
            default=None,
        )
        customparser.add_argument(
            "-t",
            "--markertext",
            dest="mtext",
            help="""Argument required by marker post.""",
            default=None,
        )
        customparser.add_argument(
            "-w",
            "--WriteIMLPost",
            dest="postIML",
            action="store_true",
            help="""Writes an IML entry if failure occurs.""",
            default=False,
        )
