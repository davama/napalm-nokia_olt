# -*- coding: UTF-8 -*-

import setuptools
from setuptools import setup, find_packages

# read the contents of your README file
with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="napalm_nokia_olt",
    version="0.0.49",
    author="Dave Macias",
    author_email = "davama@gmail.com",
    description=("Network Automation and Programmability Abstraction "
                 "Layer driver for NOKIA OLT "),
    keywords="napalm driver",
    url = "https://github.com/davama/napalm-nokia_olt",
    packages=find_packages(),
    long_description=long_description,
    long_description_content_type='text/markdown',
    classifiers=[
        "Topic :: Utilities",
        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent",
        "License :: OSI Approved :: BSD License",
    ],
    include_package_data=True,
    install_requires=('napalm>=3','xmltodict'),
)   
