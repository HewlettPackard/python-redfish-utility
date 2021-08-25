python-ilorest-utility
======================
.. image:: https://travis-ci.org/HewlettPackard/python-redfish-utility.svg?branch=master
    :target: https://travis-ci.org/HewlettPackard/python-redfish-utility
.. image:: https://img.shields.io/github/release/HewlettPackard/python-redfish-utility.svg?maxAge=2592000
	:target: https://github.com/HewlettPackard/python-redfish-utility/releases
.. image:: https://img.shields.io/badge/license-Apache%202-blue.svg
	:target: https://raw.githubusercontent.com/HewlettPackard/python-redfish-utility/master/LICENSE
.. image:: https://img.shields.io/badge/python-3.8-blue.svg?maxAge=2592000
.. image:: https://api.codacy.com/project/badge/Grade/1283adc3972d42b4a3ddb9b96660bc07
	:target: https://www.codacy.com/app/rexysmydog/python-redfish-utility?utm_source=github.com&amp;utm_medium=referral&amp;utm_content=HewlettPackard/python-ilorest-library&amp;utm_campaign=Badge_Grade


.. contents:: :depth: 1

Description
----------

The Redfish Utility is a command line interface that allows you to manage servers that take advantage of Redfish APIs. For this release of the utility, you can manage any server running a Redfish API. You can install the utility on your computer for remote use. In addition to using the utility manually to execute individual commands, you can create scripts to automate tasks.

You can download the windows and linux tool directly from HPE's website  `here <https://www.hpe.com/us/en/product-catalog/detail/pip.7630408.html#/>`_
 or download the windows, linux, debian, and mac versions from the github `releases section <https://hewlettpackard.github.io/python-redfish-utility/releases>`_.

Requirements
------------

- Python 3.9.6

Usage
----------

Installing Dependencies
~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: console

    pip install -q build
    python -m build
    pip install dist/python_redfish_utility-$(cat .version).tar.gz
    # or
    pip install dist/python_redfish_utility-*.whl


Running the utility from command line
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: console

    python3 rdmc.py


Building an executable from file source
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

 For this process you will need to install pyinstaller for python.

.. code-block:: console

    export GIT_REPO_NAME=$(pwd)
    export BUILD_METADATA=1~local~$(shell git rev-parse --short HEAD)
    make prep
    make rpm
    pyinstaller rdmc-pyinstaller-linux.spec


Documentation
~~~~~~~~~~~~~
For further usage please refer to our slate documentation: 
 
https://hewlettpackard.github.io/python-redfish-utility/

Contributing
----------

 1. Fork it!
 2. Create your feature branch: `git checkout -b my-new-feature`
 3. Commit your changes: `git commit -am 'Add some feature'`
 4. Push to the branch: `git push origin my-new-feature`
 5. Submit a pull request :D

History
----------

  * 03/29/2017: Initial release of version 1.9.0
  * 04/25/2017: Release of version 1.9.1
  * 07/17/2017: Release of version 2.0.0
  * 10/31/2017: Release of version 2.1.0
  * 02/20/2018: Release of version 2.2.0
  * 06/11/2018: Release of version 2.3.0
  * 07/02/2018: Release of version 2.3.1
  * 10/31/2018: Release of version 2.3.3
  * 11/01/2018: Release of version 2.3.4
  * 04/03/2019: Release of version 2.4.1
  * 07/05/2019: Release of version 2.5.0
  * 09/13/2019: Release of version 2.5.1
  * 11/14/2019: Release of version 3.0.0
  * 10/05/2020: Release of version 3.1.0
  * 11/17/2020: Release of version 3.1.1
  * 04/20/2021: Release of version 3.2.1
  * 06/30/2021: Release of version 3.2.2

License
----------

Copyright 2016-2020 Hewlett Packard Enterprise Development LP

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

 http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

Authors
----------

-  `Jack Garcia`_
.. _Jack Garcia: http://github.com/LumbaJack
-  `Matthew Kocurek`_
.. _Matthew Kocurek: http://github.com/Yergidy
-  `Prithvi Subrahmanya`_
.. _Prithvi Subrahmanya: http://github.com/PrithviBS
-  `Grant OConner`_
.. _Grant OConner: https://github.com/KeepSummerSaf3
-  `Rajeevalochana Kallur`_
.. _Rajeevalochana Kallur: http://github.com/rajeevkallur
