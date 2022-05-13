# Copyright 2021 Hewlett Packard Enterprise Development LP
from setuptools import find_packages
from setuptools import setup


def readme() -> str:
    """
    Print the README file.
    :returns: Read README file.
    """
    with open('README.rst') as file:
        return str(file.read())


setup(
    name='ilorest',
    version='3.5.0.0',
    description='Python utility for interacting with the iLOREST API.',
    long_description=readme(),
    author='',
    author_email='',
    maintainer='CSM/Metal Team',
    url='https://github.com/Cray-HPE/python-redfish-utility',
    install_requires=[
        'certifi >= 2020.12.5',
        'colorama >= 0.4.4',
        'decorator >= 4.4.2',
        'distribute >= 0.7.3',
        'enum34 >= 1.1.6; python_version < "3.4"',
        'jsondiff >= 1.2.0',
        'jsonpatch >= 1.28',
        'jsonpath-rw >= 1.4.0',
        'jsonpointer >= 2.0',
        'ply >= 3.11',
        'prompt_toolkit >= 3.0.10',
        'pyaes >= 1.6.1',
        'python-ilorest-library >= 3.2.2',
        'pyudev >= 0.21.0',
        'pywin32 >= 300; platform_system == "Windows"',
        'recordtype >= 1.1',
        'setproctitle >= 1.1.8; platform_system == "Linux"',
        'six >= 1.15.0',
        'tabulate >= 0.8.7',
        'urllib3 >= 1.26.2',
        'validictory >= 1.0.1',
        'wcwidth >= 0.2.5',
    ],
    extras_require={
        'ci': [
            'tox',
        ],
        'lint': [
            'pycodestyle',
        ],
        'unit': [
            'pytest',
            'pytest-mock',
        ],
        'docs': [
            'sphinx',
            'sphinx-click',
        ],
    },
    packages=find_packages(),
    include_package_data=True,
    zip_safe=False,
)
