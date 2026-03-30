###
# Copyright 2025-2026 Hewlett Packard Enterprise, Inc. All rights reserved.
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
"""Helper to determine logging_config.json path for different platforms."""

import glob
import os
import site
import sys

# Shared cache across module instances
_cache_key = "ilorest_logging_config_path_cache"
if _cache_key not in sys.modules:
    sys.modules[_cache_key] = None


def get_logging_config_path():
    r"""Return path for logging_config.json.

    Iterates through a list of different platform paths and returns the first one where
    the directory exists and logging_config.json is present.
    Platform paths: C:\Program Files\Hewlett Packard Enterprise\RESTful Interface Tool,
    /opt/ilorest, /etc/ilorest, site-packages locations, and Python installation directory.
    Falls back to the current working directory if none are found.
    """
    if sys.modules[_cache_key] is not None:
        return sys.modules[_cache_key]
    # the below paths are added to the search list for logging_config.json
    # windows path, linux paths, and python installation paths are included in the search list
    platform_paths = [
        r"C:\Program Files\Hewlett Packard Enterprise\RESTful Interface Tool",
        "/opt/ilorest",
        "/etc/ilorest",
        "/usr/local",
        sys.prefix,
    ]

    # Dynamically find site-packages paths and check for logging_config.json in those locations
    site_packages = site.getsitepackages()
    if site.ENABLE_USER_SITE:
        site_packages.append(site.getusersitepackages())

    for site_pkg in site_packages:
        parent_dir = os.path.dirname(os.path.dirname(site_pkg))
        platform_paths.append(parent_dir)
        # Also check within ilorest package directory
        ilorest_path = os.path.join(site_pkg, "ilorest")
        platform_paths.append(ilorest_path)

        # Check for data files in .data/data/ subdirectory
        data_dirs = glob.glob(os.path.join(site_pkg, "ilorest-*.data"))
        for data_dir in data_dirs:
            data_config = os.path.join(data_dir, "data", "logging_config.json")
            platform_paths.append(data_config)

    for path in platform_paths:
        config_file = os.path.join(path, "logging_config.json")
        if os.path.isfile(config_file):
            sys.modules[_cache_key] = config_file
            return config_file

    # Fallback to current working directory
    fallback_path = os.path.join(os.getcwd(), "logging_config.json")
    sys.modules[_cache_key] = fallback_path
    return fallback_path
