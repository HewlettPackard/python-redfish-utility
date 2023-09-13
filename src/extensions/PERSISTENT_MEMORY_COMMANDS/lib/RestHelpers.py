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
"""This is the helper class with functions that manipulate REST data"""
from __future__ import absolute_import  # check if python3 supported

import json
import multiprocessing
from multiprocessing.dummy import Pool as ThreadPool


class RestHelpers(object):
    """This is the helper class with functions that manipulate REST data"""

    def __init__(self, rdmcObject):
        self.rdmc = rdmcObject  # relies on the updated reference to the RDMC class object

    def get_resource(self, url):
        """
        Perform a GET request for the specified URL
        :param url: the URL of the resource to fetch
        :type: string
        :returns: object containing the REST responsed
        :rtype: RestResponse object
        """
        accepted_status = [200, 202]
        resp = self.rdmc.app.get_handler(url, service=True, silent=True)
        if resp and resp.status in accepted_status and resp.dict:
            return resp.dict
        return None

    def retrieve_memory_resources(self):
        """
        Retrieve the expanded Memory Collection resource
        """
        return self.get_resource("/redfish/v1/systems/1/memory?$expand=.")

    def retrieve_mem_domain_resources(self, chunks_flag=True):
        """
        Retrieve Memory Domain Resources and All Chunks
        """
        mem_domain_resources = self.get_resource("/redfish/v1/systems/1/MemoryDomains?$expand=.")
        domain_members = []
        all_chunks = []
        if mem_domain_resources:
            domain_members = mem_domain_resources.get("Members")
            if not chunks_flag:
                return domain_members
            chunk_id_list = list()
            for member in domain_members:
                chunk_id_list.append(member.get("MemoryChunks").get("@odata.id") + "?$expand=.")
            if chunk_id_list:
                chunks = self.concurrent_get(chunk_id_list)
            else:
                chunks = []
            # combining all chunks
            for chunk in chunks:
                chunk_members = chunk.get("Members")
                if chunk_members:
                    temp_chunks = [member for member in chunk_members]
                else:
                    temp_chunks = []
                all_chunks.extend(temp_chunks)
        return domain_members, all_chunks

    @staticmethod
    def filter_task_members(task_members):
        """
        Filters new memory chunk task members
        :param task_members: list of task members to be filtered
        :return: list of filtered task members
        """
        members = list()
        for member in task_members:
            # retrieving only new tasks
            if member.get("TaskState") == "New":
                target_uri = member.get("Payload").get("TargetUri")
                # checking if type Memory Chunk collection
                if "MemoryChunks" in target_uri:
                    json_body = member.get("Payload").get("JsonBody")
                    if json_body:
                        member["Payload"]["JsonBody"] = json.loads(json_body)
                    members.append(member)
        return members

    def retrieve_task_members(self):
        """
        Retrieve task members
        :returns: list of task members
        """
        # retrieving task resources
        task_resources = self.get_resource("/redfish/v1/TaskService/Tasks?$expand=.")
        # getting task members
        if task_resources:
            task_members = task_resources.get("Members")
            if task_members:
                return task_members
        return []

    def retrieve_mem_and_mem_domains(self):
        """
        Helper Function to retrieve Memory Resources and Memory Domain Resources
        concurrently
        :returns: memory resources, memory domain members and a list of memory chunks
        """
        # 'resource_list' is a list of functions that will be called to retrieve resources.
        resource_list = [
            self.retrieve_memory_resources,
            self.retrieve_mem_domain_resources,
        ]
        # 'response_list' contains the list of responses received on calling the functions
        # that are a part of 'resource_list', in the same order.
        response_list = self.concurrent_retrieve(resource_list)
        # Segregating individual responses from 'response_list':
        # The 'get()' call is responsible for retrieving the value that a function returns
        # from the 'AsyncResult' object returned by 'apply_async' in 'concurrent_retrieve'.
        memory = response_list[0].get()
        # domain_members and all chunks are returned as a tuple in 'response_list' as per the
        # 'retrieve_mem_domain_resources()' function definition. They are unpacked here.
        (domain_members, all_chunks) = response_list[1]
        # Returns the values of resources obtained above.
        return memory, domain_members, all_chunks

    def retrieve_task_members_and_mem_domains(self):
        """
        Helper Function to retrieve Task Resources and Memory Domain Resources
        concurrently
        :returns: task members, memory domain members and a list of memory chunks
        """
        # 'resource_list' is a list of functions that will be called to retrieve resources.
        resource_list = [self.retrieve_task_members, self.retrieve_mem_domain_resources]
        # 'response_list' contains the list of responses received on calling the functions
        # that are a part of 'resource_list', in the same order.
        response_list = self.concurrent_retrieve(resource_list)
        # Segregating individual responses from 'response_list':
        # The 'get()' call is responsible for retrieving the value that a function returns
        # from the 'AsyncResult' object returned by 'apply_async' in 'concurrent_retrieve'.
        task_members = response_list[0].get()
        # domain_members and all chunks are returned as a tuple in 'response_list' as per the
        # 'retrieve_mem_domain_resources()' function definition. They are unpacked here.
        (domain_members, all_chunks) = response_list[1]
        # Returns the values of resources obtained above.
        return task_members, domain_members, all_chunks

    @staticmethod
    def concurrent_retrieve(resource_list):
        """
        Concurrently retrieve Resources
        :param resource_list: List of resources to retrieve concurrently
        :type: List of functions
        :returns: List of response objects obtained as a result of GET requests
        :rtype: List of objects
        """
        response_list = list()
        # Spawn a pool of worker threads based on the CPU core count and
        # the number of functions to call.
        # 'len(resource_list) - 1' ensures that the last function call happens
        # on the main thread and not on a worker thread.
        pool = ThreadPool(min(len(resource_list) - 1, multiprocessing.cpu_count()))
        # Asynchronously call funtions from 'resource_list' on worker threads and
        # append responses to 'response_list'. These responses will be 'AsyncResult'
        # objects and the actual return value will have to be retrieved by a 'get()'
        # call to the returned response.
        for resource in resource_list[:-1]:
            response_list.append(pool.apply_async(resource))
        # Call the last function in 'resource_list' on the main thread so that
        # the main thread is doing some useful work and not sitting idle waiting
        # for all other threads to complete. This reduces the thread communication
        # overhead as well. The response returned here will not be an 'AsyncResult'
        # object and no 'get()' call is required to retrieve the actual return value.
        temp_response = resource_list[-1]()
        # Wait for all worker threads to complete execution.
        pool.close()
        pool.join()
        # Once all threads have finished execution, append the response recieved
        # on the main thread to the 'response_list'.
        response_list.append(temp_response)
        # Return list of responses obtained from the main and worker threads.
        return response_list

    def concurrent_get(self, uri_list):
        """
        Spawns a Threadpool and sends concurrent GET Requests
        :param uri_list: List of URIs on which the GET Requests
                         are supposed to be made
        :returns: List of responses from the GET Requests
        """
        # Spawn a pool of worker threads based on the CPU core count and
        # the number of GET requests to be sent
        pool = ThreadPool(min(multiprocessing.cpu_count(), len(uri_list)))
        response_list = pool.map(self.get_resource, uri_list)
        # Wait for worker threads to complete
        pool.close()
        pool.join()
        # Return list of responses obtained via GET requests from worker threads
        return response_list

    def delete_resource(self, url):
        """
        Perform a delete request for the specified URL
        :param url: the URL of the resource to delete
        :type: string
        :returns: status code
        """
        resp = self.rdmc.app.delete_handler(url, service=True, silent=True)
        if resp and resp.status in [200, 202]:
            return resp.status
        return None

    def post_resource(self, path, body):
        """
        Perform a post request for the specified path with body
        :param path: the URL path
        :type: string
        :body: the body to be sent
        :type: string
        :returns: status code
        """
        accepted_status = [200, 201, 202, 204]
        resp = self.rdmc.app.post_handler(path, body, service=True, silent=True)
        if resp and resp.status in accepted_status:
            return resp.status
        return None

    def in_post(self):
        """
        Check whether the server is in POST
        :return: True if server is in Post, False otherwise
        :rtype: Boolean
        """
        resp_body = self.get_resource("/redfish/v1/systems/1")
        if resp_body:
            if resp_body.get("Oem").get("Hpe").get("PostState") == "FinishedPost":
                return False
        return True

    def retrieve_security_state(self, path):
        """
        Get the security state
        """
        return self.get_resource(path)

    def retrieve_pmem_location(self):
        """
        Retrieve the Pmem location
        """
        return self.get_resource("/redfish/v1/Systems/1/Memory/?$expand=.#")

    def retrieve_model(self, rdmcObj):
        """
        Retrieve the Model
        """
        self.rdmc = rdmcObj
        return self.get_resource("/redfish/v1/Chassis/1")
