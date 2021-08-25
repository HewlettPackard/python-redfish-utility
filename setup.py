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

def version() -> str:
    '''returns version'''
    with open('.version') as file:
        return str(file.read().rstrip())

setup(
    name='python-redfish-utility',
    version=version(),
    description='Python utility for interacting with the iLOREST API.',
    long_description=readme(),
    author='',
    author_email='',
    maintainer='CSM/Metal Team',
    url='https://github.com/Cray-HPE/python-redfish-utility',
    install_requires=[
        'certifi >= 2020.6.20',
        'colorama >= 0.3.9',
        'decorator >= 3.4',
        'distribute >= 0.7.3',
        'enum34 >= 1.1.6; python_version < "3.4"',
        'jsondiff >= 1.1.1',
        'jsonpatch >= 1.3',
        'jsonpath-rw >= 1.3.0',
        'jsonpointer >= 1.1',
        'ply >= 2.4',
        'prompt_toolkit >= 2.0.8',
        'pyaes >= 1.6.1',
        'pyudev >= 0.21.0',
        'pywin32 >= 300; platform_system == "Windows"',
        'recordtype >= 1.1',
        'setproctitle >= 1.1.8; platform_system == "Linux"',
        'six >= 1.7.2',
        'tabulate >= 0.8.2',
        'urllib3 >= 1.22',
        'validictory >= 1.0.1',
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
            'pyfakefs',
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
