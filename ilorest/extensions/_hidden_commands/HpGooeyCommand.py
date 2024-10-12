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
""" Hp Gooey Command for rdmc """

import ctypes
import gzip
import itertools
import os
import platform
import string
import struct
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as et

from six import BytesIO, StringIO

import redfish.hpilo.risblobstore2 as risblobstore2

try:
    from rdmc_helper import (
        BirthcertParseError,
        CommandNotEnabledError,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        InvalidFileInputError,
        PartitionMoutingError,
        ReturnCodes,
        StandardBlobErrorHandler,
    )
except ImportError:
    from ilorest.rdmc_helper import (
        BirthcertParseError,
        CommandNotEnabledError,
        InvalidCommandLineError,
        InvalidCommandLineErrorOPTS,
        InvalidFileInputError,
        PartitionMoutingError,
        ReturnCodes,
        StandardBlobErrorHandler,
    )


if os.name == "nt":
    import win32api
elif sys.platform != "darwin" and "VMkernel" not in platform.uname():
    import pyudev


class HpGooeyCommand:
    """Hp Gooey class command"""

    def __init__(self):
        self.ident = {
            "name": "hpgooey",
            "usage": None,
            "description": "Directly writes/reads from blobstore"
            "\n\tBlobstore read example:\n\thpgooey --read "
            "--key keyexample --namespace perm -f <outputfile>"
            "\n\n\tBlobstore write example:\n\thpgooey --write"
            " --key keyexample --namespace perm -f <outputfile"
            ">\n\n\tBlobstore delete example:\n\thpgooey "
            "--delete --key keyexample --namespace perm\n\n\t"
            "Blobstore list example:\n\thpgooey --list "
            "--namespace perm\n\n\tNAMESPACES:\n\tperm, "
            "tmp, dropbox, sfw, ris, volatile",
            "summary": "directly writes/reads from blobstore",
            "aliases": [],
            "auxcommands": [],
        }
        self.cmdbase = None
        self.rdmc = None
        self.auxcommands = dict()

        # TODO: Hack for high security cred issue (We need to keep a dll handle open)
        try:
            self.lib = risblobstore2.BlobStore2.gethprestchifhandle()
        except:
            self.lib = None

    def run(self, line, help_disp=False):
        """Access blobstore directly and perform desired function

        :param line: string of arguments passed in
        :type line: str.
        :param help_disp: display help flag
        :type line: bool.
        """
        if help_disp:
            self.parser.print_help()
            return ReturnCodes.SUCCESS
        try:
            if sys.platform == "darwin":
                raise CommandNotEnabledError("'%s' command is not supported on MacOS" % str(self.name))
            elif "VMkernel" in platform.uname():
                raise CommandNotEnabledError("'%s' command is not supported on VMWare" % str(self.name))
            (options, _) = self.rdmc.rdmc_parse_arglist(self, line)
        except (InvalidCommandLineErrorOPTS, SystemExit):
            if ("-h" in line) or ("--help" in line):
                return ReturnCodes.SUCCESS
            else:
                raise InvalidCommandLineErrorOPTS("")

        self.hpgooeyvalidation(options)

        if options.key == "hpmbirthcert":
            self.remote_run(options)
        else:
            if self.rdmc.app.current_client.base_url.startswith("blobstore"):
                self.local_run(options)
            else:
                self.remote_run(options)

        self.cmdbase.logout_routine(self, options)
        # Return code
        return ReturnCodes.SUCCESS

    def remote_run(self, options):
        path = "/blob"
        if options.namespace:
            path += "/%s" % options.namespace
        if options.key:
            path += "/%s" % options.key

        if options.write:
            if not (options.key and options.namespace):
                raise InvalidCommandLineError("Key and namespace are required for hpblob operations.")
            if not options.filename or not os.path.isfile(options.filename[0]):
                raise InvalidFileInputError("Please provide a file with input data or given file does not exist")

            blobfiledata = None
            if options.binfile:
                _read_mode = "rb"
            else:
                _read_mode = "r"

            with open(options.filename[0], _read_mode) as bfh:
                blobfiledata = bfh.read()

            if options.key == "hpmbirthcert":
                blobfiledata = self.writebirthcert(blobfiledata=blobfiledata, blobdata=None, key=options.key)
            if options.key == "birthcert":
                try:
                    bcert = self.remote_read(path)
                    if isinstance(bcert, bytes):
                        bcert = bcert.decode("utf-8")
                except StandardBlobErrorHandler:
                    bcert = ""
                if not isinstance(bcert, bytes):
                    blobdata = bytearray(bcert, encoding="utf-8")
                blobfiledata = self.writebirthcert(blobfiledata=blobfiledata, blobdata=blobdata, key=options.key)

            self.remote_write(path, blobfiledata)

        elif options.read:
            if not (options.key and options.namespace):
                raise InvalidCommandLineError("Key and namespace are required for hpblob operations.")

            filedata = BytesIO()

            filedatastr = bytes(self.remote_read(path))

            if options.key == "birthcert" or options.key == "hpmbirthcert":
                filedatastr = self.readbirthcert(filedatastr, options.key)

            if not isinstance(filedatastr, bytes):
                filedatastr = filedatastr.encode("utf-8", "ignore")
            filedata.write(filedatastr)
            if options.filename:
                self.rdmc.ui.printer("Writing data to %s..." % options.filename[0])

                with open(options.filename[0], "wb") as outfile:
                    outfile.write(filedata.getvalue())

                self.rdmc.ui.printer("Done\n")
            else:
                filedata_value = filedata.getvalue()
                if isinstance(filedata_value, bytes):
                    filedata_value = filedata_value.decode("utf-8")
                if filedata_value == "":
                    self.rdmc.ui.printer("HPM Birth Certificate does not exist!!\n")
                else:
                    self.rdmc.ui.printer("%s\n" % filedata_value)

        elif options.delete:
            if not (options.key and options.namespace):
                raise InvalidCommandLineError("Key and namespace are required" " for hpblob operations.")
            self.remote_delete(path)

        elif options.list:
            if not options.namespace:
                raise InvalidCommandLineError("Namespace is required for hpblob operations.")
            bs2 = risblobstore2.BlobStore2()
            recvpacket = bs2.list(options.namespace)
            errorcode = struct.unpack("<I", recvpacket[8:12])[0]

            if not (
                errorcode == risblobstore2.BlobReturnCodes.SUCCESS
                or errorcode == risblobstore2.BlobReturnCodes.NOTMODIFIED
            ):
                raise StandardBlobErrorHandler(errorcode)

            datalength = struct.unpack("<H", recvpacket[12:14])[0]

            rtndata = bytearray()
            rtndata.extend(recvpacket[44 : datalength + 44])

            foundcnts = False
            for item in rtndata.split(b"\0", 1)[0].decode("utf-8").split():
                sys.stdout.write("%s\n" % item)
                foundcnts = True

            if not foundcnts:
                sys.stdout.write("No blob entries found.\n")

        elif options.mountabsr:
            try:
                bs2.absaroka_media_mount()
                sys.stdout.write("Checking mounted absaroka repo...")
                self.check_mount_path("REPO")
                sys.stdout.write("Done\n")
            except PartitionMoutingError:
                bs2.absr_media_unmount()
                raise
            except AttributeError:
                try:
                    self.parser.error("The option %s is not available for %s" % ("--mountabsr", self.name))
                except SystemExit:
                    raise InvalidCommandLineErrorOPTS("")

        elif options.mountgaius:
            try:
                bs2.gaius_media_mount()
                sys.stdout.write("Checking mounted gaius media...")
                self.check_mount_path("EMBEDDED")
                sys.stdout.write("Done\n")
            except PartitionMoutingError:
                bs2.gaius_media_unmount()
                raise
            except AttributeError:
                try:
                    self.parser.error("The option %s is not available for %s" % ("--mountgaius", self.name))
                except SystemExit:
                    raise InvalidCommandLineErrorOPTS("")
        elif options.mountvid:
            try:
                bs2.vid_media_mount()
                sys.stdout.write("Checking mounted vid media...")
                self.check_mount_path("VID")
                sys.stdout.write("Done\n")
            except AttributeError:
                try:
                    self.parser.error("The option %s is not available for %s" % ("--mountvid", self.name))
                except SystemExit:
                    raise InvalidCommandLineErrorOPTS("")
        elif options.mountflat:
            try:
                bs2.mountflat()
                sys.stdout.write("Checking mounted media in flat mode...")
                self.check_flat_path()
                sys.stdout.write("Done\n")
            except AttributeError:
                try:
                    self.parser.error("The option %s is not available for %s" % ("--mountflat", self.name))
                except SystemExit:
                    raise InvalidCommandLineErrorOPTS("")
        elif options.unmountmedia:
            try:
                self.osunmount(["REPO", "EMBEDDED", "VID", "BLACKBOX"])
                bs2.media_unmount()
                sys.stdout.write("Unmounting media...")
                sys.stdout.write("Done\n")
            except AttributeError:
                try:
                    self.parser.error("The option %s is not available for %s" % ("--unmountmedia", self.name))
                except SystemExit:
                    raise InvalidCommandLineErrorOPTS("")
        elif options.unmountvid:
            try:
                self.osunmount(["VID"])
                bs2.vid_media_unmount()
                sys.stdout.write("Unmounting vid media...")
                sys.stdout.write("Done\n")
            except AttributeError:
                try:
                    self.parser.error("The option %s is not available for %s" % ("--unmountvid", self.name))
                except SystemExit:
                    raise InvalidCommandLineErrorOPTS("")
        elif options.unmountabsr:
            try:
                self.osunmount(["REPO"])
                bs2.absr_media_unmount()
                sys.stdout.write("Unmounting absaroka media...")
                sys.stdout.write("Done\n")
            except AttributeError:
                try:
                    self.parser.error("The option %s is not available for %s" % ("--unmountabsr", self.name))
                except SystemExit:
                    raise InvalidCommandLineErrorOPTS("")
        elif options.unmountgaius:
            try:
                self.osunmount(["EMBEDDED", "VID", "BLACKBOX"])
                bs2.gaius_media_unmount()
                sys.stdout.write("Unmounting gaius media...")
                sys.stdout.write("Done\n")
            except AttributeError:
                try:
                    self.parser.error("The option %s is not available for %s" % ("--unmountgaius", self.name))
                except SystemExit:
                    raise InvalidCommandLineErrorOPTS("")
        else:
            sys.stderr.write("No command entered")

    def local_run(self, options):
        log_dir = self.rdmc.log_dir
        bs2 = risblobstore2.BlobStore2()
        risblobstore2.BlobStore2.initializecreds(options.user, options.password,log_dir)
        bs2.gethprestchifhandle()

        if options.write:
            if not (options.key and options.namespace):
                raise InvalidCommandLineError("Key and namespace are required for hpblob operations.")

            if not options.filename or not os.path.isfile(options.filename[0]):
                raise InvalidFileInputError("Please provide a file with input data or given file does not exist")

            if options.binfile:
                _read_mode = "rb"
            else:
                _read_mode = "r"

            with open(options.filename[0], _read_mode) as bfh:
                blobfiledata = bfh.read()

            if options.key == "birthcert" and options.namespace == "factory":
                try:
                    bs2.get_info(options.key, options.namespace)
                except:
                    bs2.create(options.key, options.namespace)
            else:
                try:
                    bs2.delete(options.key, options.namespace)
                except:
                    pass
                bs2.create(options.key, options.namespace)

            if options.key == "birthcert":
                blobdata = bytearray(bs2.read(options.key, options.namespace))
                blobfiledata = self.writebirthcert(blobfiledata=blobfiledata, blobdata=blobdata, key=options.key)

            errorcode = bs2.write(options.key, options.namespace, blobfiledata)

            if not (
                errorcode == risblobstore2.BlobReturnCodes.SUCCESS
                or errorcode == risblobstore2.BlobReturnCodes.NOTMODIFIED
            ):
                raise StandardBlobErrorHandler(errorcode)
        elif options.read:
            if not (options.key and options.namespace):
                raise InvalidCommandLineError("Key and namespace are required" " for hpblob operations.")

            filedata = BytesIO()

            try:
                filedatastr = bytes(bs2.read(options.key, options.namespace))

                if options.key == "birthcert":
                    filedatastr = self.readbirthcert(filedatastr, options.key)

                # if isinstance(filedatastr, bytes):
                #    filedatastr = filedatastr.decode('utf-8', 'ignore')
                filedata.write(filedatastr)
                if options.filename:
                    self.rdmc.ui.printer("Writing data to %s..." % options.filename[0])

                    with open(options.filename[0], "wb") as outfile:
                        outfile.write(filedata.getvalue())

                    self.rdmc.ui.printer("Done\n")
                else:
                    filedata_value = filedata.getvalue()
                    if isinstance(filedata_value, bytes):
                        filedata_value = filedata_value.decode("utf-8")
                    self.rdmc.ui.printer("%s\n" % filedata_value)
            except risblobstore2.BlobNotFoundError as excp:
                raise excp
            except Exception as excp:
                raise StandardBlobErrorHandler(excp)
        elif options.delete:
            if not (options.key and options.namespace):
                raise InvalidCommandLineError("Key and namespace are required for hpblob operations.")

            try:
                bs2.get_info(options.key, options.namespace)
                errorcode = bs2.delete(options.key, options.namespace)
            except Exception as excp:
                raise StandardBlobErrorHandler(excp)

            if not (
                errorcode == risblobstore2.BlobReturnCodes.SUCCESS
                or errorcode == risblobstore2.BlobReturnCodes.NOTMODIFIED
            ):
                raise StandardBlobErrorHandler()
        elif options.list:
            if not options.namespace:
                raise InvalidCommandLineError("Namespace is required for hpblob operations.")

            recvpacket = bs2.list(options.namespace)
            errorcode = struct.unpack("<I", recvpacket[8:12])[0]

            if not (
                errorcode == risblobstore2.BlobReturnCodes.SUCCESS
                or errorcode == risblobstore2.BlobReturnCodes.NOTMODIFIED
            ):
                raise StandardBlobErrorHandler(errorcode)

            datalength = struct.unpack("<H", recvpacket[12:14])[0]

            rtndata = bytearray()
            rtndata.extend(recvpacket[44 : datalength + 44])

            foundcnts = False
            for item in rtndata.split(b"\0", 1)[0].decode("utf-8").split():
                self.rdmc.ui.printer("%s\n" % item)
                foundcnts = True

            if not foundcnts:
                self.rdmc.ui.printer("No blob entries found.\n")
        elif options.mountabsr:
            try:
                bs2.absaroka_media_mount()
                self.rdmc.ui.printer("Checking mounted absaroka repo...")
                self.check_mount_path("REPO")
                self.rdmc.ui.printer("Done\n")
            except PartitionMoutingError:
                bs2.absr_media_unmount()
                raise
            except AttributeError:
                try:
                    self.parser.error("The option %s is not available for %s" % ("--mountabsr", self.name))
                except SystemExit:
                    raise InvalidCommandLineErrorOPTS("")
        elif options.mountgaius:
            try:
                bs2.gaius_media_mount()
                self.rdmc.ui.printer("Checking mounted gauis media...")
                self.check_mount_path("EMBEDDED")
                self.rdmc.ui.printer("Done\n")
            except PartitionMoutingError:
                bs2.gaius_media_unmount()
                raise
            except AttributeError:
                try:
                    self.parser.error("The option %s is not available for %s" % ("--mountgaius", self.name))
                except SystemExit:
                    raise InvalidCommandLineErrorOPTS("")
        elif options.mountvid:
            try:
                bs2.vid_media_mount()
                self.rdmc.ui.printer("Checking mounted vid media...")
                self.check_mount_path("VID")
                self.rdmc.ui.printer("Done\n")
            except AttributeError:
                try:
                    self.parser.error("The option %s is not available for %s" % ("--mountvid", self.name))
                except SystemExit:
                    raise InvalidCommandLineErrorOPTS("")
        elif options.mountflat:
            try:
                bs2.mountflat()
                self.rdmc.ui.printer("Checking mounted media in flat mode...")
                self.check_flat_path()
                self.rdmc.ui.printer("Done\n")
            except AttributeError:
                try:
                    self.parser.error("The option %s is not available for %s" % ("--mountflat", self.name))
                except SystemExit:
                    raise InvalidCommandLineErrorOPTS("")
        elif options.unmountmedia:
            try:
                self.osunmount(["REPO", "EMBEDDED", "VID", "BLACKBOX"])
                bs2.media_unmount()
                self.rdmc.ui.printer("Unmounting media...")
                self.rdmc.ui.printer("Done\n")
            except AttributeError:
                try:
                    self.parser.error("The option %s is not available for %s" % ("--unmountmedia", self.name))
                except SystemExit:
                    raise InvalidCommandLineErrorOPTS("")
        elif options.unmountvid:
            try:
                self.osunmount(["VID"])
                bs2.vid_media_unmount()
                self.rdmc.ui.printer("Unmounting vid media...")
                self.rdmc.ui.printer("Done\n")
            except AttributeError:
                try:
                    self.parser.error("The option %s is not available for %s" % ("--unmountvid", self.name))
                except SystemExit:
                    raise InvalidCommandLineErrorOPTS("")
        elif options.unmountabsr:
            try:
                self.osunmount(["REPO"])
                bs2.absr_media_unmount()
                self.rdmc.ui.printer("Unmounting absaroka media...")
                self.rdmc.ui.printer("Done\n")
            except AttributeError:
                try:
                    self.parser.error("The option %s is not available for %s" % ("--unmountabsr", self.name))
                except SystemExit:
                    raise InvalidCommandLineErrorOPTS("")
        elif options.unmountgaius:
            try:
                self.osunmount(["EMBEDDED", "VID", "BLACKBOX"])
                bs2.gaius_media_unmount()
                self.rdmc.ui.printer("Unmounting gaius media...")
                self.rdmc.ui.printer("Done\n")
            except AttributeError:
                try:
                    self.parser.error("The option %s is not available for %s" % ("--unmountgaius", self.name))
                except SystemExit:
                    raise InvalidCommandLineErrorOPTS("")
        else:
            self.rdmc.ui.error("No command entered")

    def remote_read(self, path):
        """Remote version of blob read"""
        data = ""
        resp = self.rdmc.app.get_handler(path, silent=True, service=True, uncache=True)
        if resp.status == 200:
            data = resp.ori
            if data != b"":
                if "hpm" in path.lower():
                    self.rdmc.ui.printer("Successfully read HPM Birth Certificate.\n")
                else:
                    self.rdmc.ui.printer("Successfully read Birth Certificate.\n")
            else:
                if "hpm" in path.lower():
                    raise risblobstore2.BlobNotFoundError("No HPM Birth Certificate found.\n")
                else:
                    raise risblobstore2.BlobNotFoundError("No Birth Certificate found.\n")
        else:
            raise StandardBlobErrorHandler("remote or vnic read failure")

        return data

    def remote_write(self, path, data):
        """Remote version of blob write"""
        # if isinstance(data, bytes):
        #    data = data.decode('utf-8')
        resp = self.rdmc.app.post_handler(path, data, silent=True, service=True)
        if resp.status == 201 or resp.status == 200:
            if "hpm" in path.lower():
                self.rdmc.ui.printer("Successfully written HPM Birth Certificate.\n")
            else:
                self.rdmc.ui.printer("Successfully written Birth Certificate.\n")
        else:
            raise StandardBlobErrorHandler("remote or vnic write failure")

    def remote_delete(self, path):
        """Remote version of blob delete"""
        resp = self.rdmc.app.delete_handler(path, silent=True, service=True)
        if resp.status == 200:
            if "hpm" in path.lower():
                self.rdmc.ui.printer("Successfully deleted HPM Birth Certificate.\n")
            else:
                self.rdmc.ui.printer("Successfully deleted Birth Certificate.\n")
        else:
            raise StandardBlobErrorHandler("remote or vnic delete failure")

    def check_mount_path(self, label):
        """Get mount folder path."""
        count = 0
        while count < 120:
            if os.name == "nt":
                drives = self.get_available_drives()

                for i in drives:
                    try:
                        label = win32api.GetVolumeInformation(i + ":")[0]
                        if label == label:
                            abspathbb = i + ":\\"
                            return (False, abspathbb)
                    except:
                        pass
            else:
                with open("/proc/mounts", "r") as fmount:
                    while True:
                        lin = fmount.readline()

                        if len(lin.strip()) == 0:
                            break

                        if label in lin:
                            abspathbb = lin.split()[1]
                            return (False, abspathbb)

                if count > 3:
                    found, path = self.manualmount(label)
                    if found:
                        return (True, path)

            count = count + 1
            time.sleep(1)

        raise PartitionMoutingError("Partition with label %s not found on the NAND, so not able to mount" % label)

    def check_flat_path(self):
        """Check flat path directory."""
        context = pyudev.Context()
        count = 0

        while count < 20:
            for dev in context.list_devices(subsystem="block"):
                if str(dev.get("ID_SERIAL")).startswith("HP_iLO_LUN"):
                    path = dev.get("DEVNAME")
                    return (True, path)

            count = count + 1
            time.sleep(1)

        raise PartitionMoutingError("iLO not responding to request for mounting partition")

    def manualmount(self, label):
        """Manually mount after fixed time."""
        context = pyudev.Context()

        for device in context.list_devices(subsystem="block"):
            if device.get("ID_FS_LABEL") == label:
                dirpath = os.path.join(tempfile.gettempdir(), label)

                if not os.path.exists(dirpath):
                    try:
                        os.makedirs(dirpath)
                    except Exception as excp:
                        raise excp

                pmount = subprocess.Popen(
                    ["mount", device.device_node, dirpath],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                _, _ = pmount.communicate()
                return (True, dirpath)

        return (False, None)

    def get_available_drives(self):
        """Obtain all drives"""
        if "Windows" not in platform.system():
            return []

        drive_bitmask = ctypes.cdll.kernel32.GetLogicalDrives()
        return list(
            itertools.compress(
                string.ascii_uppercase,
                [ord(drive) - ord("0") for drive in bin(drive_bitmask)[:1:-1]],
            )
        )

    def detecttype(self, readdata):
        """Function to detect a packets encryption

        :param readdata: data read from the call
        :type readdata: str.
        """
        magic_dict = {
            "\x1f\x8b\x08": "gz",
            "\x42\x5a\x68": "bz2",
            "\x50\x4b\x03\x04": "zip",
        }
        max_len = max(len(x) for x in magic_dict)
        file_start = readdata[:max_len]

        for magic, filetype in list(magic_dict.items()):
            if file_start.startswith(magic):
                return filetype

        return "no match"

    def osunmount(self, labels=None):
        """Function to unmount media using labels

        :param labels: list of labels to unmount
        :type labels: list.
        """
        if labels:
            for label in labels:
                try:
                    (_, path) = self.check_mount_path(label)
                except PartitionMoutingError:
                    if self.rdmc.opts.verbose:
                        self.rdmc.ui.printer("Unable to find {0} partition.".format(label))
                    continue
                pumount = subprocess.Popen(["umount", path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                _, _ = pumount.communicate()

    def readbirthcert(self, blobdata, key):
        """Function to read the birth certificate

        :param blobdata: data read from birth certificate call
        :type blobdata: str.
        """
        if key != "hpmbirthcert":
            if "blobstore" in self.rdmc.app.redfishinst.base_url:
                blobio = BytesIO(blobdata)
                filehand = gzip.GzipFile(mode="rb", fileobj=blobio)

                data = filehand.read()
                filehand.close()
            else:
                data = blobdata
        else:
            blobio = BytesIO(blobdata)
            filehand = gzip.GzipFile(mode="rb", fileobj=blobio)

            data = filehand.read()
            filehand.close()
            # if isinstance(blobdata, bytes):
            #    data = blobdata.decode("utf-8")
            # else:
            #    data = blobdata
        return data

    def writebirthcert(self, blobdata, blobfiledata, key):
        """Function to read the birth certificate

        :param blobdata: data to be written to birth certificate call
        :type blobdata: str.
        :param blobfiledata: data read from birth certificate call
        :type blobfiledata: str.
        """
        filetype = self.detecttype(blobfiledata)
        if filetype != "no match":
            raise StandardBlobErrorHandler

        if key != "hpmbirthcert":
            if "blobstore" in self.rdmc.app.redfishinst.base_url:
                blobdataunpacked = self.readbirthcert(blobdata, key)
            else:
                if isinstance(blobdata, bytes):
                    blobdataunpacked = blobdata.decode("utf-8")
                else:
                    blobdataunpacked = blobdata
            totdata = self.parsebirthcert(blobdataunpacked, blobfiledata)
        else:
            totdata = self.parsebirthcert(None, blobfiledata)

        databuf = BytesIO()

        filehand = gzip.GzipFile(mode="wb", fileobj=databuf)
        filehand.write(totdata)
        filehand.close()

        compresseddata = databuf.getvalue()
        return compresseddata

    def parsebirthcert(self, blobdataunpacked=None, blobfiledata=None):
        """Parse birth certificate function."""
        filedata = StringIO(blobfiledata)
        if blobdataunpacked:
            if isinstance(blobdataunpacked, bytes):
                blobdataunpacked = blobdataunpacked.decode("utf-8")
            readdata = StringIO(blobdataunpacked)

            try:
                readtree = et.parse(readdata)
                readroot = readtree.getroot()
                readstr = b""

                if readroot.tag == "BC":
                    for child in readroot:
                        readstr += et.tostring(child)

                    if isinstance(readstr, bytes):
                        readstr = readstr.decode("utf-8")
                    totstr = readstr + blobfiledata
                    totstrdata = StringIO(totstr)
                    iterdata = itertools.chain("<BC>", totstrdata, "</BC>")
                    readroot = et.fromstringlist(iterdata)
                    totdata = et.tostring(readroot)
                else:
                    raise
            except Exception as excp:
                self.rdmc.ui.error("Error while parsing birthcert.\n", excp)
                raise BirthcertParseError(excp)
        else:
            iterdata = itertools.chain("<BC>", filedata, "</BC>")
            newroot = et.fromstringlist(iterdata)
            totdata = et.tostring(newroot)

        return totdata

    def birthcertdelete(self, options=None, compdata=None):
        """Delete birth certificate function."""
        totdata = ""
        databuf = StringIO()
        filehand = gzip.GzipFile(mode="wb", fileobj=databuf)

        filehand.write(totdata)
        filehand.close()
        compresseddata = databuf.getvalue()

        if compdata:
            compresseddata = compdata

        bs2 = risblobstore2.BlobStore2()
        risblobstore2.BlobStore2.initializecreds(options.user, options.password)

        errorcode = bs2.write(options.key, options.namespace, compresseddata)

        if not (
            errorcode == risblobstore2.BlobReturnCodes.SUCCESS or errorcode == risblobstore2.BlobReturnCodes.NOTMODIFIED
        ):
            raise StandardBlobErrorHandler(errorcode)

        return errorcode

    def hpgooeyvalidation(self, options):
        """Download command method validation function

        :param options: command options
        :type options: options.
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

        customparser.add_argument(
            "-f",
            "--filename",
            dest="filename",
            help="""Use the provided filename to perform operations.""",
            action="append",
            default=None,
        )
        customparser.add_argument(
            "-r",
            "--read",
            dest="read",
            action="store_true",
            help="""read data into the provided filename""",
            default=None,
        )
        customparser.add_argument(
            "-w",
            "--write",
            dest="write",
            action="store_true",
            help="""use the provided filename to output data""",
            default=None,
        )
        customparser.add_argument(
            "-d",
            "--delete",
            dest="delete",
            action="store_true",
            help="""delete the file from the provided namespace""",
            default=None,
        )
        customparser.add_argument(
            "-l",
            "--list",
            dest="list",
            action="store_true",
            help="""list the files from the provided namespace""",
            default=None,
        )
        customparser.add_argument(
            "-k",
            "--key",
            dest="key",
            help="""blobstore key name to use for opetations with no """ """spaces and 32 character limit""",
            default=None,
        )
        customparser.add_argument(
            "-n",
            "--namespace",
            dest="namespace",
            help="""namespace where operation is to be performed""",
            default=None,
        )
        customparser.add_argument(
            "--mountabsr",
            dest="mountabsr",
            action="store_true",
            help="""use this flag to mount absaroka repo""",
            default=None,
        )
        customparser.add_argument(
            "--mountgaius",
            dest="mountgaius",
            action="store_true",
            help="""use this flag to mount gaius""",
            default=None,
        )
        customparser.add_argument(
            "--mountvid",
            dest="mountvid",
            action="store_true",
            help="""use this flag to mount vid""",
            default=None,
        )
        customparser.add_argument(
            "--mountflat",
            dest="mountflat",
            action="store_true",
            help="""use this flag to mount flat mode""",
            default=None,
        )
        customparser.add_argument(
            "--unmountabsr",
            dest="unmountabsr",
            action="store_true",
            help="""use this flag to unmount absaroka media""",
            default=None,
        )
        customparser.add_argument(
            "--unmountvid",
            dest="unmountvid",
            action="store_true",
            help="""use this flag to vid media""",
            default=None,
        )
        customparser.add_argument(
            "--unmountgaius",
            dest="unmountgaius",
            action="store_true",
            help="""use this flag to unmount gaius media""",
            default=None,
        )
        customparser.add_argument(
            "--unmountmedia",
            dest="unmountmedia",
            action="store_true",
            help="""use this flag to unmount all NAND partitions""",
            default=None,
        )
        customparser.add_argument(
            "--binfile",
            dest="binfile",
            action="store_true",
            help="""use this flag to write and read binary files""",
            default=None,
        )
