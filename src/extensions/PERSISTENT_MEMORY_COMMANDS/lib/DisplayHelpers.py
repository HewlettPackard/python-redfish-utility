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
"""There are the helper functions for displaying data on the console"""
from __future__ import absolute_import

from enum import Enum

from tabulate import tabulate

try:
    from rdmc_helper import LOGGER, UI
except ImportError:
    from ilorest.rdmc_helper import LOGGER, UI


class OutputFormats(Enum):
    """Enum class representing output formats"""

    table = "table"
    list = "list"
    json = "json"


class DisplayHelpers(object):
    """Helper functions for printing data to display on the console"""

    output_dict = dict()

    def __init__(self, width=20):
        self.output_dict[OutputFormats.table] = self.print_table
        self.output_dict[OutputFormats.list] = self.print_list
        self.output_dict[OutputFormats.json] = self.output_to_json
        self.max_width = width
        self._ui = UI()

    def display_data(self, data_to_display, output_format, unique_id_property_name=None):
        """
        Wrapper function for displaying data in the proper format: table, list, json, etc.
        :param data_to_display: The data to display. Each object represents a row in a table
                or an item in a list.
        :type data_to_display: array of objects
        :param output_format: Specifies which output format to use
        :type output_format: enum
        :param unique_id_property_name: Specifies the property which acts as the identifier
        :type unique_id_property_name: string
        """
        if data_to_display is None or data_to_display == []:
            LOGGER.info("DCPMEM: Empty data")
            return None
        if output_format not in self.output_dict:
            LOGGER.info("Incorrect output format")
            return None
        self.output_dict[output_format](data_to_display, unique_id_property_name)
        return None

    def format_data(self, data, truncate=False):
        """
        Function to identify header properties and convert Redfish property names to friendly names.
        It also truncate strings whenever required
        :param data: The data from which header has to be identified.
        :type data: array of objects
        :param truncate: Specifies whether truncation of strings is to be done or not
        :type truncate: Boolean
        :return:2 arrays. First array is an array of properties.
        Second array is an array of objects.
        Each object is an array containing value of properties at corresponding index.
        """
        table = []
        for item in data:
            row = [":".join(x.split(":")[1:]).strip() for x in item.split("\n") if len(x.split(":")) >= 2]
            table.append(row)
        headers = [x.split(":")[0].strip() for x in data[0].split("\n") if len(x.split(":")) == 2]
        not_found = [x for x in data[0].split("\n") if len(x.split(":")) < 2]
        self._ui.printer("\n".join(not_found))
        if not truncate:
            return headers, table
        truncated_headers = [self.truncate_lengthy(str(x), self.max_width) for x in headers]
        truncated_data = [[self.truncate_lengthy(str(x), self.max_width) for x in row] for row in table]
        return truncated_headers, truncated_data

    # pylint: disable=unused-argument
    def print_table(self, table_data, property_id=None):
        """
        This function prints data in table format
        :param table_data: data to be printed in table format
        :type array of objects
        :param property_id: Specifies the property which acts as the identifier
        :type string
        """
        headers, data = self.format_data(table_data, True)
        self._ui.printer("\n")
        self._ui.printer(tabulate(data, headers, tablefmt="plain"))
        self._ui.printer("\n\n")
        return

    def print_list(self, list_data, property_id=None):
        """
        This function prints data in list format
        :param list_data: data to be printed in list format
        :type array of objects
        :param property_id: Specifies the property which acts as the identifier
        :type string
        """

        headers, data = self.format_data(list_data)
        flag = 0
        counter = 0
        if property_id is None or property_id not in headers:
            flag = 1

        if flag == 0:
            property_id_index = headers.index(property_id)
            del headers[property_id_index]

        for item in data:
            if flag == 0:
                self._ui.printer("--- " + property_id + ": " + str(item[property_id_index] + " ---"))
                item.remove(item[property_id_index])
            else:
                counter += 1
                self._ui.printer("--- " + str(counter) + " ---")
            for prop in enumerate(headers):
                self._ui.printer("\n" + headers[prop[0]] + ": " + str(item[prop[0]]))
            self._ui.printer("\n\n")
        return

    def print_properties(self, data):
        """
        This function prints the data in list format without any header
        :param data:data to be printed without header
        :type array of string
        """
        if not data:
            self._ui.printer("\n")
            return
        headers, data = self.format_data(data)
        for item in data:
            for prop in enumerate(headers):
                self._ui.printer("\n" + headers[prop[0]] + ": " + str(item[prop[0]]))
            self._ui.printer("\n")
        self._ui.printer("\n")
        return

    # pylint: disable=unused-argument
    def output_to_json(self, json_data, property_id=None):
        """
        This function prints data in json format
        :param json_data: data to be printed in json format
        :type json_data: array of objects
        :param property_id: Specifies the property which acts as the identifier
        :type property_id: string
        """
        self._ui.printer("\n")
        self._ui.print_out_json(json_data)
        self._ui.printer("\n")
        return

    @staticmethod
    def truncate_lengthy(stringin, max_length):
        """Truncate lengthy strings to a maximum size
        :param stringin: string to truncate
        :type stringin: string
        :param max_length: maximum allowed length of a string
        :type max_length: int
        :return: return the truncated string
        :rtype: string
        """
        if stringin:
            if len(stringin) > max_length:
                return stringin[: (max_length - 2)] + ".."
            return stringin
        return ""
