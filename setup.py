from setuptools import find_packages, setup
import site
import os
import platform
import sys

site_packages = site.getsitepackages()

extras = {}


def set_env_var():
    system = platform.system()
    bin_path = os.path.dirname(sys.executable)
    if system == "Windows":
        import winreg

        try:
            # Open the registry key for the environment variables
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment", 0, winreg.KEY_ALL_ACCESS) as reg_key:
                try:
                    current_path, _ = winreg.QueryValueEx(reg_key, "PATH")
                    reg_type = winreg.REG_SZ
                except FileNotFoundError:
                    current_path = ""
                    reg_type = winreg.REG_EXPAND_SZ  # Default type

                if bin_path not in current_path.split(os.pathsep):
                    updated_path = bin_path
                    if current_path:
                        updated_path = bin_path + os.pathsep + current_path
                    winreg.SetValueEx(reg_key, "PATH", 0, reg_type, updated_path)
        except Exception as e:
            print(f"Failed to set environment variable: {e}")
    elif system in ("Linux", "Darwin"):
        try:
            # Path to the shell configuration file
            shell_config_path = os.path.expanduser("~/.bashrc")
            if system == "Darwin":
                import sysconfig

                shell_config_path = os.path.expanduser("~/.zshrc")
                paths = sysconfig.get_paths()
                bin_path = paths.get("scripts", "")

            # Write to the shell configuration file
            with open(shell_config_path, "a+") as file:
                file.seek(0)
                file_content = file.read()
                if bin_path not in file_content:
                    file.write(f'\nexport PATH="{bin_path}:$PATH"\n')

        except Exception as e:
            print(f"Failed to set environment variable: {e}")


set_env_var()

setup(
    name="ilorest",
    version="7.1.0.0",
    description="HPE iLORest Tool",
    author="Hewlett Packard Enterprise",
    author_email="rajeevalochana.kallur@hpe.com",
    extras_require=extras,
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "License :: OSI Approved :: Apache Software License",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Communications",
    ],
    keywords="Hewlett Packard Enterprise",
    url="https://github.com/HewlettPackard/python-redfish-utility",
    packages=find_packages(".", exclude=["tests", "docs"]),
    package_dir={"": "."},
    package_data={
        "ilorest.chiflibrary": ["ilorest_chif.dll", "ilorest_chif.so"],
        "ilorest.chiflibrary.arm": ["ilorest_chif.so"],
        "ilorest.extensions.iLO_COMMANDS.data": ["*.py"],
    },
    data_files=[("", ["logging_config.json"])],
    entry_points={
        "console_scripts": [
            "ilorest = ilorest.rdmc:ilorestcommand",
        ],
    },
    install_requires=[
        "urllib3 >= 1.26.2",
        "pyaes >= 1.6.1",
        "colorama >= 0.4.4",
        "jsonpointer >= 2.0",
        "six >= 1.15.0",
        "ply",
        "requests",
        "decorator >= 4.4.2",
        "jsonpatch >= 1.28",
        "jsonpath-rw >= 1.4.0",
        'setproctitle >= 1.1.8; platform_system == "Linux"',
        "jsondiff >= 1.2.0",
        "tabulate >= 0.8.7",
        "prompt_toolkit",
        "certifi >= 2020.12.5",
        'pywin32; platform_system == "Windows"',
        "wcwidth >= 0.2.5",
        "pyudev",
        "future",
        'enum; python_version <= "2.7.19"',
        'futures; python_version <= "2.7.19"',
        "python-ilorest-library >= 7.1.0.0",
    ],
)
