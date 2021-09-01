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
""" Version strings for the utility """

from os import path
from os import listdir

def __version() -> str:
    '''returns version'''
    # FIXME: pyinstaller does not include this file despite MANIFEST.in
    version_file = path.join(path.dirname(__file__), '.version')
    try:
        with open(version_file) as file:
            return str(file.read().rstrip())
    except FileNotFoundError:
        return '3.2.2+'


# TODO: Replace version, longname, and extracontent with calls to packages module.

__version__ = __version()
__shortname__ = 'iLOrest'
__longname__ = 'RESTful Interface Tool'
__extracontent__ = 'Copyright (c) 2014-2021 Hewlett Packard Enterprise' \
                   ' Development LP\n'
