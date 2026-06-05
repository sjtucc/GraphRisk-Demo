#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""

To install GBase Connector/Python:

    shell> python ./setup.py install

"""

from setuptools import setup
from distutils.command.install import INSTALL_SCHEMES

# Make sure that data files are actually installed in the package directory
for install_scheme in INSTALL_SCHEMES.values():
    install_scheme['data'] = install_scheme['purelib']

import setupinfo
try:
    from cpyint import metasetupinfo
    setupinfo.command_classes.update(metasetupinfo.command_classes)
except (ImportError, AttributeError):
    # python-internal not available
    pass

setup(
    name=setupinfo.name,
    version=setupinfo.version,
    description=setupinfo.description,
    long_description=setupinfo.long_description,
    author=setupinfo.author,
    author_email=setupinfo.author_email,
    license=setupinfo.cpy_gpl_license,
    keywords=setupinfo.keywords,
    url=setupinfo.url,
    download_url=setupinfo.download_url,
    package_dir=setupinfo.package_dir,
    packages=setupinfo.packages,
    classifiers=setupinfo.classifiers,
    cmdclass=setupinfo.command_classes,
    ext_modules=setupinfo.extensions,
    install_requires=setupinfo.install_requires,
    extras_require=setupinfo.extras_require,
)

