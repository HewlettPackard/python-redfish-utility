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
"""Base implementation for cli interaction with Redfish interface"""

# ---------Imports---------

import getpass
import os
import re
import subprocess
import sys

try:
    from rdmc_helper import UI
except ImportError:
    from ilorest.rdmc_helper import UI

if os.name == "nt":
    import ctypes
    from ctypes import windll, wintypes

# ---------End of imports---------


class CommandNotFoundException(Exception):
    """Exception throw when Command is not found"""

    pass


class ResourceAllocationError(Exception):
    """Exception throw when Command is not found"""

    pass


def get_user_config_dir():
    """Platform specific directory for user configuration.

    :returns: returns the user configuration directory.
    :rtype: string
    """
    if os.name == "nt":
        try:
            csidl_appdata = 26

            shgetfolderpath = windll.shell32.SHGetFolderPathW
            shgetfolderpath.argtypes = [
                wintypes.HWND,
                ctypes.c_int,
                wintypes.HANDLE,
                wintypes.DWORD,
                wintypes.LPCWSTR,
            ]

            path_buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            result = shgetfolderpath(0, csidl_appdata, 0, 0, path_buf)

            if result == 0:
                return path_buf.value
        except ImportError:
            pass

        return os.environ["APPDATA"]

    return os.path.expanduser("~")


def is_exe(filename):
    """Determine if filename is an executable.

    :param filename: the filename to examine.
    :type filename: string
    :returns: True if filename is executable False otherwise.
    :rtype: boolean
    """
    if sys.platform == "win32":
        if os.path.exists(filename):
            return True

        # windows uses PATHEXT to list valid executable extensions
        pathext = os.environ["PATHEXT"].split(os.pathsep)
        (_, ext) = os.path.splitext(filename)

        if ext in pathext:
            return True
    else:
        if os.path.exists(filename) and os.access(filename, os.X_OK):
            return True

    return False


def find_exe(filename, path=None):
    """Search path for a executable (aka which)

    :param filename: the filename to search for.
    :type filename: string.
    :param path: the path(s) to search (default: os.environ['PATH'])
    :param path: string separated with os.pathsep
    :returns: string with full path to the file or None if not found.
    :rtype: string or None.
    """
    if path is None:
        path = os.environ["PATH"]

    pathlist = path.split(os.pathsep)

    # handle fully qualified paths
    if os.path.isfile(filename) and is_exe(filename):
        return filename

    for innerpath in pathlist:
        foundpath = os.path.join(innerpath, filename)

        if is_exe(foundpath):
            return foundpath

    return None


def get_terminal_size():
    """Returns the rows and columns of the terminal as a tuple.

    :returns: the row and column count of the terminal
    :rtype: tuple (cols, rows)
    """
    _tuple = (80, 25)  # default

    if os.name == "nt":
        pass
    else:
        which_stty = find_exe("stty")

        if which_stty:
            args = [which_stty, "size"]
            try:
                procs = subprocess.Popen(args, shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            except OSError as excp:
                raise ResourceAllocationError(str(excp))
            (stdout_s, _) = procs.communicate()

            _ = procs.wait()
            # python3 change
            if isinstance(stdout_s, bytes):
                stdout_s = stdout_s.decode("utf-8")
            if stdout_s and re.search(r"^\d+ \d+$", stdout_s):
                rows, cols = stdout_s.split()
                _tuple = (cols, rows)

    return _tuple


class CLI(object):
    """Class for building command line interfaces."""

    def __init__(self, verbosity=1, out=sys.stdout):
        self._verbosity = verbosity
        self._out = out
        cols, rows = get_terminal_size()
        self._cols = int(cols)
        self._rows = int(rows)

    def verbosity(self, verbosity):
        self._verbosity = verbosity

    def get_hrstr(self, character="-"):
        """returns a string suitable for use as a horizontal rule.

        :param character: the character to use as the rule. (default -)
        :type character: str.
        """
        return "%s\n" % (character * self._cols)

    def printer(self, data, flush=True):
        """printing wrapper

        :param data: data to be printed to the output stream
        :type data: str.
        :param flush: flush buffer - True, not flush output buffer - False
        :type flush: boolean
        """

        UI(self._verbosity).printer(data, flush)

    def horizontalrule(self, character="-"):
        """writes a horizontal rule to the file handle.

        :param character: the character to use as the rule. (default -)
        :type character: str.
        """

        self.printer(self.get_hrstr(character=character))

    def version(self, progname, version, extracontent):
        """Prints a version string to fileh.

        :param progname: the name of the program.
        :type progname: str.
        :param version: the version of the program.
        :type version str.
        :param fileh: the file handle to write to. Default is sys.stdout.
        :type fileh: file object
        :returns: None
        """
        tmp = "%s version %s\n%s" % (progname, version, extracontent)
        self.printer(tmp)
        self.horizontalrule()

    def prompt_password(self, msg, default=None):
        """Convenient password prompting function

        :param msg: prompt text.
        :type msg: str.
        :param default: default value if user does not enter anything.
        :type default: str.
        :returns: string user entered, or default if nothing entered
        """
        message = "%s : " % msg

        if default is not None:
            message = "%s [%s] : " % (msg, default)

        i = getpass.getpass(message)

        if i is None or len(i) == 0:
            i = default

        i = str(i)

        return i.strip()
