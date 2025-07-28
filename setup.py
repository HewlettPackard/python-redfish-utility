from setuptools import find_packages, setup
import site

site_packages = site.getsitepackages()

extras = {}

setup(name='ilorest',
      version='6.2.0.0',
      description='HPE iLORest Tool',
      author='Hewlett Packard Enterprise',
      author_email='rajeevalochana.kallur@hpe.com',
      extras_require=extras,
      classifiers=[
          'Development Status :: 5 - Production/Stable',
          'License :: OSI Approved :: Apache Software License',
          'Programming Language :: Python :: 3.6',
          'Programming Language :: Python :: 3.8',
          'Programming Language :: Python :: 3.9',
          'Programming Language :: Python :: 3.10',
          'Programming Language :: Python :: 3.11',
          'Programming Language :: Python :: 3.12',
          'Topic :: Communications'
      ],
      keywords='Hewlett Packard Enterprise',
      url='https://github.com/HewlettPackard/python-redfish-utility',
      packages=find_packages('.', exclude=["tests", "docs"]),
      package_dir={'': '.'},
      package_data={"ilorest.chiflibrary": ["ilorest_chif.dll", "ilorest_chif.so"]},
      entry_points={
        'console_scripts': [
          'ilorest = ilorest.rdmc:ilorestcommand',
        ],
      },
      install_requires=[
          'urllib3 >= 1.26.2',
          'pyaes >= 1.6.1',
          'colorama >= 0.4.4',
          'jsonpointer >= 2.0',
          'six >= 1.15.0',
          'ply',
          'requests',
          'decorator >= 4.4.2',
          'jsonpatch >= 1.28',
          'jsonpath-rw >= 1.4.0',
          'setproctitle >= 1.1.8; platform_system == "Linux"',
          'jsondiff >= 1.2.0',
          'tabulate >= 0.8.7',
          'prompt_toolkit',
          'certifi >= 2020.12.5',
          'pywin32; platform_system == "Windows"',
          'wcwidth >= 0.2.5',
          'pyudev',
          'future',
          'enum; python_version <= "2.7.19"',
          'futures; python_version <= "2.7.19"',
          'python-ilorest-library >= 6.0.0.0',
      ])
