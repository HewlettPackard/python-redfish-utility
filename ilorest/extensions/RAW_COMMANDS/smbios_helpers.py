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
"""SMBIOS helpers used by RawGetCommand.

The logic is isolated here to keep RawGetCommand focused on request flow.
"""

import struct


def is_smbios_path(path):
    """Return True when the request targets the SMBIOS endpoint."""
    if not isinstance(path, str):
        return False

    canonical_path = path.split("?", 1)[0].rstrip("/").lower()
    return canonical_path == "/smbios" or canonical_path.endswith("/smbios")


def extract_response_headers(response, default_json=True):
    """Normalize headers from legacy and requests-style response objects."""
    if hasattr(response, "getheaders"):
        try:
            headers = response.getheaders()
            if headers:
                return dict(headers)
        except Exception:
            pass

    headers = getattr(response, "headers", None)
    if headers:
        try:
            return dict(headers)
        except Exception:
            pass

    if default_json:
        return {"Content-Type": "application/json"}

    return {}


def extract_numeric_status_code(response):
    """Return the first concrete integer status code exposed by a response object."""
    for attr_name in ("status_code", "status"):
        candidate = getattr(response, attr_name, None)
        if isinstance(candidate, int):
            return candidate

    return None


def extract_smbios_raw_payload(response):
    """Extract the raw SMBIOS payload from a legacy blobstore response."""
    raw_payload = getattr(response, "ori", None)
    if raw_payload is not None:
        return raw_payload

    raw_payload = getattr(response, "content", None)
    if raw_payload:
        return raw_payload

    return None


def normalize_smbios_payload(raw_payload):
    """Convert raw SMBIOS bytes into the JSON structure expected by rawget output."""
    return {"smbios data": unpack_smbios_data(raw_payload)}


def unpack_smbios_data(data):
    """Decode an SMBIOS byte stream into a record list.

    Uses explicit little-endian unpacking ("<BBH") per SMBIOS spec.
    """
    dataptr = 0
    fulldata = []

    if isinstance(data, str):
        data = data.encode("latin-1", "ignore")
    elif isinstance(data, bytearray):
        data = bytes(data)
    elif not isinstance(data, bytes):
        data = str(data).encode("latin-1", "ignore")

    data_len = len(data)

    while dataptr + 4 <= data_len:
        try:
            record_type, record_length, record_handle = struct.unpack_from("<BBH", data, dataptr)
        except struct.error:
            break

        if record_length < 4 or dataptr + record_length > data_len:
            break

        dataptr += record_length
        record_strings = []

        while dataptr < data_len:
            string_start = dataptr
            while dataptr < data_len and data[dataptr] != 0:
                dataptr += 1

            if dataptr >= data_len:
                break

            string_data = data[string_start:dataptr]
            dataptr += 1

            if not string_data:
                while dataptr < data_len and data[dataptr] == 0:
                    dataptr += 1
                break

            record_strings.append(string_data.decode("latin-1", "ignore"))

        record = {
            "Type": str(record_type),
            "Length": str(record_length),
            "Handle": str(record_handle),
        }
        if record_strings:
            record["Strings"] = str(record_strings)

        fulldata.append(record)

        if record_type == 127:
            break

    return fulldata


def is_json_content_type(response):
    """Return True when response headers indicate JSON payload."""
    headers = extract_response_headers(response, default_json=False)
    if not headers:
        return False

    content_type = headers.get("Content-Type") or headers.get("content-type")
    if not content_type:
        return False

    return "json" in str(content_type).lower()
