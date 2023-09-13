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
"""Rdmc config"""

import os

try:
    from config.config import AutoConfigParser
except ImportError:
    from ilorest.config.config import AutoConfigParser


class RdmcConfig(AutoConfigParser):
    """Rdmc config class for loading and parsing the .conf file global configuration options.
    Uses the AutoConfigParser."""

    def __init__(self, filename=None):
        """Initialize RdmcConfig

        :param filename: file name to be used for Rdmcconfig loading.
        :type filename: str

        """
        AutoConfigParser.__init__(self, filename=filename)
        self._sectionname = "redfish"
        self._configfile = filename
        self._ac__logdir = os.getcwd()
        self._ac__cache = True
        self._ac__url = ""
        self._ac__username = ""
        self._ac__password = ""
        self._ac__sslcert = ""
        self._ac__commit = ""
        self._ac__format = ""
        self._ac__cachedir = ""
        self._ac__savefile = ""
        self._ac__loadfile = ""
        self._ac__user_cert = ""
        self._ac__user_root_ca_key = ""
        self._ac__user_root_ca_password = ""

    @property
    def configfile(self):
        """The current configuration file"""
        return self._configfile

    @configfile.setter
    def configfile(self, config_file):
        """Set the current configuration file

        :param config_file: file name to be used for Rmcconfig loading.
        :type config_file: str
        """
        self._configfile = config_file

    @property
    def logdir(self):
        """Get the current log directory"""
        return self._get("logdir")

    @logdir.setter
    def logdir(self, value):
        """Set the current log directory

        :param value: current working directory for logging
        :type value: str
        """
        return self._set("logdir", value)

    @property
    def cache(self):
        """Get the config file cache status"""

        if isinstance(self._get("cache"), bool):
            return self._get("cache")

        return self._get("cache").lower() in ("yes", "true", "t", "1")

    @cache.setter
    def cache(self, value):
        """Get the config file cache status

        :param value: status of config file cache
        :type value: bool
        """
        return self._set("cache", value)

    @property
    def url(self):
        """Get the config file URL"""
        url = self._get("url")
        url = url[:-1] if url.endswith("/") else url

        return url

    @url.setter
    def url(self, value):
        """Set the config file URL

        :param value: URL path for the config file
        :type value: str
        """
        return self._set("url", value)

    @property
    def username(self):
        """Get the config file user name"""
        return self._get("username")

    @username.setter
    def username(self, value):
        """Set the config file user name

        :param value: user name for config file
        :type value: str
        """
        return self._set("username", value)

    @property
    def password(self):
        """Get the config file password"""
        return self._get("password")

    @password.setter
    def password(self, value):
        """Set the config file password

        :param value: password for config file
        :type value: str
        """
        return self._set("password", value)

    @property
    def commit(self):
        """Get the config file commit status"""
        return self._get("commit")

    @commit.setter
    def commit(self, value):
        """Set the config file commit status

        :param value: commit status
        :type value: str
        """
        return self._set("commit", value)

    @property
    def format(self):
        """Get the config file default format"""
        return self._get("format")

    @format.setter
    def format(self, value):
        """Set the config file default format

        :param value: set the config file format
        :type value: str
        """
        return self._set("format", value)

    @property
    def cachedir(self):
        """Get the config file cache directory"""
        return self._get("cachedir")

    @cachedir.setter
    def cachedir(self, value):
        """Set the config file cache directory

        :param value: config file cache directory
        :type value: str
        """
        return self._set("cachedir", value)

    @property
    def defaultsavefilename(self):
        """Get the config file default save name"""
        return self._get("savefile")

    @defaultsavefilename.setter
    def defaultsavefilename(self, value):
        """Set the config file default save name

        :param value: config file save name
        :type value: str
        """
        return self._set("savefile", value)

    @property
    def defaultloadfilename(self):
        """Get the config file default load name"""
        return self._get("loadfile")

    @defaultloadfilename.setter
    def defaultloadfilename(self, value):
        """Set the config file default load name

        :param value: name of config file to load by default
        :type value: str
        """
        return self._set("loadfile", value)

    @property
    def proxy(self):
        """Get proxy value to be set for communication"""
        return self._get("proxy")

    @proxy.setter
    def proxy(self, value):
        """Set proxy value for communication"""
        return self._set("proxy", value)

    @property
    def ssl_cert(self):
        """Get proxy value to be set for communication"""
        return self._get("sslcert")

    @ssl_cert.setter
    def ssl_cert(self, value):
        """Set proxy value for communication"""
        return self._set("sslcert", value)

    @property
    def user_cert(self):
        return self._get("usercert")

    @user_cert.setter
    def user_cert(self, value):
        return self._set("usercert", value)

    @property
    def user_root_ca_key(self):
        return self._get("user_root_ca_key")

    @user_root_ca_key.setter
    def user_root_ca_key(self, value):
        return self._set("user_root_ca_key", value)

    @property
    def user_root_ca_password(self):
        return self._get("user_root_ca_password")

    @user_root_ca_password.setter
    def user_root_ca_password(self, value):
        return self._set("user_root_ca_password", value)
