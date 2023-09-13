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
"""There are helper functions used to get required data using mapping table"""
from __future__ import absolute_import

from jsonpointer import resolve_pointer


class Mapper(object):
    """Helper functions for getting data"""

    def get_multiple_attributes(self, data, attributes_list, mapping_table, output_as_json=False, **resources):
        """
        Method used to get data for multiple attributes
        :param data: json from which data is to be extracted
        :param attributes_list: list of attributes to be extracted
        :param mapping_table: table used to extract data
        :param output_as_json: specifies whether the output should be in json or not
        :param resources: additional resources required to compute attributes
        :return: Either string or json containing extracted information for all the attributes
        """
        # loop over the list of attribute names provided
        if output_as_json:
            output = {}
            for attribute in attributes_list:
                output.update(
                    self.get_single_attribute(
                        data,
                        attribute,
                        mapping_table,
                        output_as_json=True,
                        resources=resources,
                    )
                )
        else:
            output = ""
            for attribute in attributes_list:
                output += "\n" + self.get_single_attribute(data, attribute, mapping_table, resources=resources)
        return output

    @staticmethod
    def get_single_attribute(data, attribute_name, mapping_table, output_as_json=False, resources=None):
        """
        Method used to get data for single attribute
        :param data: json from which data is to be extracted
        :param attribute_name: attribute to be extracted
        :param mapping_table: table used to extract data
        :param output_as_json: specifies whether the output should be in json or not
        :param resources: additional resources required to compute attributes
        :return: Either string or json containing extracted information for single attribute
        """
        output = {} if output_as_json else "No match found for '{}'".format(attribute_name)
        # finding the attribute in the mapping table
        mapping = mapping_table.get(attribute_name, None)
        if mapping:
            # attribute exists in mapping table
            resolved_data = resolve_pointer(data, mapping["path"], None)

            if resolved_data is not None:
                # attribute_name is present in data
                if "compute" in mapping:
                    resolved_data = mapping["compute"](data=resolved_data, resources=resources)
                value = resolved_data

                if output_as_json:
                    if "renderJSON" in mapping:
                        # calling the rendering function to generate the JSON output
                        value = mapping["renderJSON"](value)
                        if isinstance(value, bytes):
                            value = value.decode("utf-8")
                    output = {attribute_name: value}
                else:
                    if "renderText" in mapping:
                        # calling the rendering function to generate the TEXT output
                        value = mapping["renderText"](value)
                        if isinstance(value, bytes):
                            value = value.decode("utf-8")
                    output = "{}: {}".format(attribute_name, value)

        # attribute does not exist in mapping table or value is None
        return output
