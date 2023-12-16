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
"""This module contains common helper functions used by several pmem commands"""


class PmemHelpers(object):
    """
    Class containing common helper functions used by several pmem commands
    """

    @staticmethod
    def py3_round(number, precision):
        """
        Rounds numbers in accordance with the Python 3 round specification
        :param number: number to be rounded
        :type number: floating point number
        :param precision: Number of decimal places the number should be rounded off to
        :type precision: integer
        :return: rounded off number
        """
        if abs(round(number) - number) == 0.5:
            return 2.0 * round(number / 2.0, precision)
        return round(number, precision)

    @staticmethod
    def parse_dimm_id(dimm_id_list):
        """
        Converts DIMM IDs from the 'X@Y' format
        to the 'PROC X DIMM Y' format
        :param dimm_id_list: DIMM IDs in the 'X@Y' format
        :type dimm_id_list: list
        :return: list of DIMM IDs in the 'PROC X DIMM Y' format
        """
        parsed_list = list()
        for dimm_id in dimm_id_list:
            temp = dimm_id.split("@")
            parsed_list.append("PROC " + temp[0] + " DIMM " + temp[1])
        return parsed_list

    @staticmethod
    def get_pmem_members(memory_members):
        """
        Filters persistent memory members from memory resources
        :param memory_members: members of memory collection resource
        :type memory_members: list of members
        :returns: list of persistent memory members if found else empty list
        """
        base_module_type = "PMM"
        pmem_members = list()
        pmem_dimm_id = set()
        for member in memory_members:
            memory_type = member.get("Oem").get("Hpe").get("BaseModuleType")
            if memory_type == base_module_type:
                pmem_members.append(member)
                pmem_dimm_id.add(member.get("DeviceLocator"))
        return pmem_members, pmem_dimm_id

    @staticmethod
    def get_non_aep_members(memory_members):
        """
        Filters dram memory members from memory resources
        :param memory_members: members of memory collection resource
        :type memory_members: list of members
        :returns: list of dram memory members if found else empty list
        """
        base_module_type = "PMM"
        dram_members = list()
        dram_dimm_id = set()
        for member in memory_members:
            memory_type = member.get("Oem").get("Hpe").get("BaseModuleType")
            if memory_type != base_module_type:
                dram_members.append(member)
                dram_dimm_id.add(member.get("DeviceLocator"))
        return dram_members, dram_dimm_id

    @staticmethod
    def json_to_text(dictionary):
        """
        Converts json to string format
        :param dictionary: json to be converted
        :return: list containing the string
        """
        output = ""
        for key, value in dictionary.items():
            item = "\n" + key + ":" + str(value)
            output += item
        return [output]

    @staticmethod
    def location_format_converter(location_list):
        """
        Converts location format from 'PROC X DIMM Y' to 'X@Y'
        :param location_list: list of locations of the format 'PROC X DIMM Y'
        :type location_list: list of strings
        :returns: string of locations in the 'X@Y' format (comma separated)
        """
        converted_str = ""
        for location in location_list:
            temp = location.split(" ")
            converted_str += temp[1] + "@" + temp[3]
            if location is not location_list[-1]:
                converted_str += ", "
        return converted_str, ("PROC " + converted_str[0])

    @staticmethod
    def compare_id(id1, id2):
        """
        Compares two ids
        :param id1: first id to be compared
        :param id2: second id to be compared
        :return: True if ids are same else False
        """
        if id1[-1] == "/":
            id1 = id1[:-1]
        if id2[-1] == "/":
            id2 = id2[:-1]
        return id1 == id2
