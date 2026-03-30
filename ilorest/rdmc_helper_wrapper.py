###
# Copyright 2026 Hewlett Packard Enterprise, Inc. All rights reserved.
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
"""Wrapper module for rdmc_helper to support both package and flat import paths.

This allows logging_config.json to use "rdmc_helper_wrapper.InfoFilter" regardless of
whether the module is installed as a package (ilorest.rdmc_helper) or extracted flat.
Automatically ensures this module is importable by adding necessary paths to sys.path.
"""

import os
import sys
import importlib
import importlib.util
import site

# To ensure this wrapper module is importable from logging.config.dictConfig
if importlib.util.find_spec("rdmc_helper_wrapper") is None or __name__ == "__main__":
    paths_to_add = [
        os.path.dirname(os.path.abspath(__file__)),  # Current directory (ilorest package)
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),  # Parent directory
        "/opt/ilorest",  # VMware flat extraction
        "/etc/ilorest",  # Linux system paths
        r"C:\Program Files\Hewlett Packard Enterprise\RESTful Interface Tool",  # Windows install
    ]

    # Add PyPI site-packages directories
    try:
        for site_pkg in site.getsitepackages():
            paths_to_add.append(site_pkg)
            ilorest_pkg = os.path.join(site_pkg, "ilorest")
            if os.path.isdir(ilorest_pkg):
                paths_to_add.append(ilorest_pkg)
    except Exception:
        pass

    for path in paths_to_add:
        if os.path.isdir(path) and path not in sys.path:
            sys.path.insert(0, path)

try:
    # Try relative import first to avoid circular imports
    from . import rdmc_helper as _rdmc_helper
except ImportError:
    try:
        # Try package import
        _rdmc_helper = importlib.import_module("ilorest.rdmc_helper")
    except ImportError:
        # Fallback to local import (VMware flat extraction)
        _rdmc_helper = importlib.import_module("rdmc_helper")

# Re-export all classes and functions from rdmc_helper
InfoFilter = _rdmc_helper.InfoFilter
CommandIDFilter = _rdmc_helper.CommandIDFilter
CompressedRotatingFileHandler = _rdmc_helper.CompressedRotatingFileHandler

# Make this module importable under both names for logging config compatibility
_mod = sys.modules[__name__]
sys.modules.setdefault("rdmc_helper_wrapper", _mod)
sys.modules.setdefault("ilorest.rdmc_helper_wrapper", _mod)
