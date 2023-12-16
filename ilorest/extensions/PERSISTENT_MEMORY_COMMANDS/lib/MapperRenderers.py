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
"""These are helper functions used to render different attributes"""
from __future__ import absolute_import, division

from enum import Enum

from .Mapper import Mapper
from .PmemHelpers import PmemHelpers


class MapperRenderers(object):
    """Methods used to render different attributes"""

    @staticmethod
    def format_num(num):
        """
        Method to convert any number to GiB
        Note: The result produced by the unit conversion is in GiB.
        However, it is labeled as GB to be consistent with other products.
        :param num: any number
        :return: formatted number in string format
        """
        return str(PmemHelpers.py3_round(num / 1024, 2)) + " GB"

    @staticmethod
    def format_num_json(num):
        """
        Method to convert any number to GiB in json format
        Note: The result produced by the unit conversion is in GiB.
        However, it is labeled as GB to be consistent with other products.
        :param num: any number
        :return: formatted number in json format
        """
        return {"Units": "GB", "Value": PmemHelpers.py3_round(num / 1024, 2)}

    @staticmethod
    def format_percentage(num):
        """
        Method to append % symbol
        :param num: any number
        :return: formatted percentage in string format
        """
        return "{}%".format(num)

    @staticmethod
    def format_percentage_json(num):
        """
        Method to get formatted percentage
        :param num: any number
        :return: formatted percentage in json format
        """
        return {"Units": "%", "Value": num}

    @staticmethod
    def find_pmem_interleaved(**kwargs):
        """
        Method to find whether specified member is interleaved or not
        :param kwargs:
            data (dict): all the Memory REST data for the individual Memory to check whether
                        interleaved or not
            resources (dict): a dict containing all required REST resources; the 'chunks' keyword
                              containing all MemoryChunk data is required for this method
        :return: Yes if interleaved, No if not interleaved, N/A otherwise
        """
        member = kwargs.get("data", {})
        chunks = kwargs.get("resources").get("chunks", [])
        data_id = member.get("@odata.id", "")
        for chunk in chunks:
            interleave_sets = chunk.get("InterleaveSets")
            if not interleave_sets:
                continue
            for mem_set in interleave_sets:
                if PmemHelpers.compare_id(data_id, mem_set.get("Memory").get("@odata.id")):
                    if len(interleave_sets) > 1:
                        return "Yes"
                    return "No"
        return "N/A"

    @staticmethod
    def calculate_total_capacity(**kwargs):
        """
        Method to calculate total capacity
        :param kwargs:
            data (list): all the memory members for which total capacity is to be calculated
        :return: total capacity in MiB
        """
        members = kwargs.get("data", [])
        total = 0
        if members:
            for member in members:
                capacity = Mapper.get_single_attribute(
                    member, "Capacity", MappingTable.device.value, output_as_json=True
                )
                total += capacity.get("Capacity", {}).get("Value", 0)
        # returning value in MiB
        return total * 1024

    @staticmethod
    def calculate_total_pmem(**kwargs):
        """
        Method to calculate total pmem size
         :param kwargs:
             data (list): all the memory members for which total pmem size is to be calculated
        :return: total pmem size in MiB
        """
        members = kwargs.get("data", [])
        total = 0
        if members:
            for member in members:
                capacity = Mapper.get_single_attribute(
                    member, "PmemSize", MappingTable.device.value, output_as_json=True
                )
                total += capacity.get("PmemSize", {}).get("Value", 0)
        # returning value in MiB
        return total * 1024

    @staticmethod
    def calculate_total_volatile(**kwargs):
        """
        Method to calculate total volatile size
        :param kwargs:
            data (list): all the members for which total volatile size is to be calculated
        :return: total volatile size in MiB
        """
        members = kwargs.get("data", [])
        total = 0
        if members:
            for member in members:
                capacity = Mapper.get_single_attribute(
                    member, "VolatileSize", MappingTable.device.value, output_as_json=True
                )
                total += capacity.get("VolatileSize", {}).get("Value", 0)
        # returning value in MiB
        return total * 1024

    @staticmethod
    def find_dimm_ids(**kwargs):
        """
        Method to find DimmIds present in given chunk
        :param kwargs:
            data (dict): all the MemoryChunk REST data for the individual Memory chunk of which
                        dimmids is to be found
            resources (dict): a dict containing all required REST resources; the 'memory' keyword
                              containing all memory resources is required for this method
        :return: string containing dimmids
        """
        member = kwargs.get("data", {})
        memory_members = kwargs.get("resources").get("memory", [])
        interleave_sets = member.get("InterleaveSets", [])
        locations = []
        for interleave_set in interleave_sets:
            for pmem in memory_members:
                if PmemHelpers.compare_id(interleave_set.get("Memory").get("@odata.id"), pmem.get("@odata.id")):
                    location = Mapper.get_single_attribute(
                        pmem, "Location", MappingTable.device.value, output_as_json=True
                    )
                    locations.append(location.get("Location", ""))
        return PmemHelpers.location_format_converter(locations)[0]

    @staticmethod
    def map_operation(**kwargs):
        """
        Method to map HTTP operations to user-friendly names
        :param kwargs:
            data (str): HTTP operation to be mapped to user-friendly name
        :return: mapped operation
        """
        operation = kwargs.get("data", "")
        operation_mapper = {"POST": "CREATE"}
        return operation_mapper.get(operation, operation)

    @staticmethod
    def calculate_task_pmem_size(**kwargs):
        """
        Method to calculate pmem size for a task
        :param kwargs:
            data (dict): all the Task REST data for the individual task of which pmem size
                        is to be calculated
            resources (dict): a dict containing all required REST resources; the 'memory' keyword
                              containing all memory resources is required for this method
        :return: pmem size of task in MiB
        """
        size = 0
        task = kwargs.get("data", {})
        # finding memory chunk size
        memory_chunk_size = Mapper.get_single_attribute(
            task, "MemoryChunkSize", MappingTable.tasks.value, output_as_json=True
        )
        memory_chunk_size = memory_chunk_size.get("MemoryChunkSize", {}).get("Value", None)
        if memory_chunk_size is not None:
            size = memory_chunk_size
        else:
            memory_members = kwargs.get("resources", {}).get("memory", [])
            interleave_sets = task.get("Payload").get("JsonBody").get("InterleaveSets", [])
            selected_members = []
            for interleave_set in interleave_sets:
                for pmem in memory_members:
                    if PmemHelpers.compare_id(
                        interleave_set.get("Memory").get("@odata.id"),
                        pmem.get("@odata.id"),
                    ):
                        selected_members.append(pmem)
            # finding total capacity
            total_capacity = Mapper.get_single_attribute(
                selected_members,
                "TotalCapacity",
                MappingTable.summary.value,
                output_as_json=True,
            )
            total_capacity = total_capacity.get("TotalCapacity", {}).get("Value", 0)
            # finding memory chunk size percentage
            memory_chunk_size_percentage = Mapper.get_single_attribute(
                task,
                "MemoryChunkSizePercentage",
                MappingTable.tasks.value,
                output_as_json=True,
            )
            memory_chunk_size_percentage = memory_chunk_size_percentage.get("MemoryChunkSizePercentage", {}).get(
                "Value", None
            )
            if memory_chunk_size_percentage is not None:
                size = total_capacity * memory_chunk_size_percentage / 100
        # returning value in MiB
        return size * 1024

    @staticmethod
    def calculate_task_volatile_size(**kwargs):
        """
        Method to calculate volatile size for a task
        :param kwargs:
            data (dict): all the Task REST data for the individual task of which volatile size
                        is to be calculated
            resources (dict): a dict containing all required REST resources; the 'memory' keyword
                              containing all memory resources is required for this method
        :return: volatile size of task in MiB
        """
        task = kwargs.get("data", {})
        memory_members = kwargs.get("resources", {}).get("memory", [])
        interleave_sets = task.get("Payload").get("JsonBody").get("InterleaveSets", [])
        selected_members = []
        for interleave_set in interleave_sets:
            for pmem in memory_members:
                if PmemHelpers.compare_id(interleave_set.get("Memory").get("@odata.id"), pmem.get("@odata.id")):
                    selected_members.append(pmem)
        # finding total capacity
        total_capacity = Mapper.get_single_attribute(
            selected_members,
            "TotalCapacity",
            MappingTable.summary.value,
            output_as_json=True,
        )
        total_capacity = total_capacity.get("TotalCapacity", {}).get("Value", 0)
        volatile_size = total_capacity
        # finding memory chunk size
        memory_chunk_size = Mapper.get_single_attribute(
            task, "MemoryChunkSize", MappingTable.tasks.value, output_as_json=True
        )
        memory_chunk_size = memory_chunk_size.get("MemoryChunkSize", {}).get("Value", None)
        if memory_chunk_size is not None:
            size = memory_chunk_size
            volatile_size = total_capacity - size
        else:
            # finding memory chunk size percentage
            memory_chunk_size_percentage = Mapper.get_single_attribute(
                task,
                "MemoryChunkSizePercentage",
                MappingTable.tasks.value,
                output_as_json=True,
            )
            memory_chunk_size_percentage = memory_chunk_size_percentage.get("MemoryChunkSizePercentage", {}).get(
                "Value", None
            )
            if memory_chunk_size_percentage is not None:
                size = total_capacity * memory_chunk_size_percentage / 100
                volatile_size = total_capacity - size
        # returning value in MiB
        return volatile_size * 1024

    @staticmethod
    def calculate_chunk_volatile_size(**kwargs):
        """
        Method to calculate volatile size for a chunk
        :param kwargs:
            data (dict): all the Task REST data for the individual chunk of which volatile size
                        is to be calculated
            resources (dict): a dict containing all required REST resources; the 'memory' keyword
                              containing all memory resources is required for this method
        :return: volatile size of chunk in MiB
        """
        chunk = kwargs.get("data", {})
        memory_members = kwargs.get("resources", {}).get("memory", [])
        interleave_sets = chunk.get("InterleaveSets", [])
        selected_members = []
        for interleave_set in interleave_sets:
            for pmem in memory_members:
                if PmemHelpers.compare_id(interleave_set.get("Memory").get("@odata.id"), pmem.get("@odata.id")):
                    selected_members.append(pmem)
        # finding total capacity
        total_capacity = Mapper.get_single_attribute(
            selected_members,
            "TotalCapacity",
            MappingTable.summary.value,
            output_as_json=True,
        )
        total_capacity = total_capacity.get("TotalCapacity", {}).get("Value", 0)
        volatile_size = total_capacity
        # finding memory chunk size
        memory_chunk_size = Mapper.get_single_attribute(
            chunk, "PmemSize", MappingTable.delete_task.value, output_as_json=True
        )
        memory_chunk_size = memory_chunk_size.get("PmemSize", {}).get("Value", None)
        if memory_chunk_size is not None:
            volatile_size = total_capacity - memory_chunk_size

        # returning value in MiB
        return volatile_size * 1024


DEVICE_MAPPING_TABLE = {
    "PmemSize": {
        "path": "/PersistentRegionSizeLimitMiB",
        "renderText": MapperRenderers.format_num,
        "renderJSON": MapperRenderers.format_num_json,
    },
    "Capacity": {
        "path": "/CapacityMiB",
        "renderText": MapperRenderers.format_num,
        "renderJSON": MapperRenderers.format_num_json,
    },
    "DIMMStatus": {"path": "/Oem/Hpe/DIMMStatus", "renderJSON": lambda data: data},
    "FWVersion": {"path": "/FirmwareRevision", "renderJSON": lambda data: data},
    "Life": {
        "path": "/Oem/Hpe/PredictedMediaLifeLeftPercent",
        "renderText": MapperRenderers.format_percentage,
        "renderJSON": MapperRenderers.format_percentage_json,
    },
    "Location": {"path": "/DeviceLocator", "renderJSON": lambda data: data},
    "Status": {"path": "/Status/Health", "renderJSON": lambda data: data},
    "VolatileSize": {
        "path": "/VolatileRegionSizeLimitMiB",
        "renderText": MapperRenderers.format_num,
        "renderJSON": MapperRenderers.format_num_json,
    },
}

CONFIG_MAPPING_TABLE = {
    "PmemInterleaved": {"path": "", "compute": MapperRenderers.find_pmem_interleaved},
    "PmemSize": {
        "path": "/PersistentRegionSizeLimitMiB",
        "renderText": MapperRenderers.format_num,
        "renderJSON": MapperRenderers.format_num_json,
    },
    "Location": {
        "path": "/DeviceLocator",
        "renderJSON": lambda data: data.encode("ascii", "ignore"),
    },
    "VolatileSize": {
        "path": "/VolatileRegionSizeLimitMiB",
        "renderText": MapperRenderers.format_num,
        "renderJSON": MapperRenderers.format_num_json,
    },
}

SUMMARY_MAPPING_TABLE = {
    "TotalCapacity": {
        "path": "",
        "compute": MapperRenderers.calculate_total_capacity,
        "renderText": MapperRenderers.format_num,
        "renderJSON": MapperRenderers.format_num_json,
    },
    "TotalPmemSize": {
        "path": "",
        "compute": MapperRenderers.calculate_total_pmem,
        "renderText": MapperRenderers.format_num,
        "renderJSON": MapperRenderers.format_num_json,
    },
    "TotalVolatileSize": {
        "path": "",
        "compute": MapperRenderers.calculate_total_volatile,
        "renderText": MapperRenderers.format_num,
        "renderJSON": MapperRenderers.format_num_json,
    },
}

LOGICAL_MAPPING_TABLE = {
    "PmemSize": {
        "path": "/MemoryChunkSizeMiB",
        "renderText": MapperRenderers.format_num,
        "renderJSON": MapperRenderers.format_num_json,
    },
    "DimmIds": {
        "path": "",
        "compute": MapperRenderers.find_dimm_ids,
        "renderJSON": lambda data: data,
    },
}

TASK_MAPPING_TABLE = {
    "DimmIds": {
        "path": "/Payload/JsonBody",
        "compute": MapperRenderers.find_dimm_ids,
        "renderJSON": lambda data: data,
    },
    "MemoryChunkSize": {
        "path": "/Payload/JsonBody/MemoryChunkSizeMiB",
        "renderText": MapperRenderers.format_num,
        "renderJSON": MapperRenderers.format_num_json,
    },
    "MemoryChunkSizePercentage": {
        "path": "/Payload/JsonBody/Oem/Hpe/MemoryChunkSizePercentage",
        "renderText": MapperRenderers.format_percentage,
        "renderJSON": MapperRenderers.format_percentage_json,
    },
    "PmemSize": {
        "path": "",
        "compute": MapperRenderers.calculate_task_pmem_size,
        "renderText": MapperRenderers.format_num,
        "renderJSON": MapperRenderers.format_num_json,
    },
    "Operation": {
        "path": "/Payload/HttpOperation",
        "compute": MapperRenderers.map_operation,
    },
    "Type": {"path": "/Payload/JsonBody/AddressRangeType"},
    "VolatileSize": {
        "path": "",
        "compute": MapperRenderers.calculate_task_volatile_size,
        "renderText": MapperRenderers.format_num,
        "renderJSON": MapperRenderers.format_num_json,
    },
}

DELETE_TASK_MAPPING_TABLE = {
    "DimmIds": {
        "path": "",
        "compute": MapperRenderers.find_dimm_ids,
        "renderJSON": lambda data: data,
    },
    "Operation": {"path": "", "compute": lambda **kwargs: "DELETE"},
    "PmemSize": {
        "path": "/MemoryChunkSizeMiB",
        "renderText": MapperRenderers.format_num,
        "renderJSON": MapperRenderers.format_num_json,
    },
    "VolatileSize": {
        "path": "",
        "compute": MapperRenderers.calculate_chunk_volatile_size,
        "renderText": MapperRenderers.format_num,
        "renderJSON": MapperRenderers.format_num_json,
    },
}


class MappingTable(Enum):
    """Enum class representing mapping tables"""

    device = DEVICE_MAPPING_TABLE
    summary = SUMMARY_MAPPING_TABLE
    config = CONFIG_MAPPING_TABLE
    logical = LOGICAL_MAPPING_TABLE
    tasks = TASK_MAPPING_TABLE
    delete_task = DELETE_TASK_MAPPING_TABLE
