# -*- coding: UTF-8 -*-
import setuptools
from setuptools import setup, find_packages

# read the contents of your README file
with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name = "napalm_nokia_olt",
    version = "0.0.02",
    author = "Dave Macias",
    author_email = "davama@gmail.com",
    description = ("Napaml Nokia driver for OLT devices"),
    license = "BSD",
    keywords = "napalm drive",
    url="https://github.com/davama/napalm-nokia_olt",
    packages=['napalm_nokia_olt'],
    long_description=long_description,
    long_description_content_type='text/markdown',
    classifiers=[
        "Topic :: Utilities",
        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent",
        "License :: OSI Approved :: BSD License",
    ],
)
