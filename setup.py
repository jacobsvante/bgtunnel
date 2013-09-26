#!/usr/bin/env python
from __future__ import print_function
from setuptools import setup
import codecs
import os
import sys


appname = 'bgtunnel'
app = __import__(appname)
version = app.__version__


read = lambda filepath: codecs.open(filepath, 'r', 'utf-8').read()


if sys.argv[-1] == 'publish':
    os.system("python setup.py sdist upload")
    print("You probably also want to tag the version now with:")
    print("git tag -a {0} -m 'version {0}'\n  git push --tags".format(version))
    sys.exit()

setup(
    name=appname,
    version=version,
    description="Initiate SSH tunnels in the background",
    long_description=app.__doc__,
    py_modules=[appname],
    author='Jacob Magnusson',
    author_email='m@jacobian.se',
    url='https://github.com/jmagnusson/bgtunnel',
    license='BSD',
    platforms=['unix', 'macos'],
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Operating System :: Unix',
        'Programming Language :: Python',
    ],
)
