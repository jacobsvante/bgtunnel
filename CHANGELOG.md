# Changelog

## 0.3.3 (2014-01-03)

* SIGTERM instead of SIGINT for background ssh process. Sometimes the process would not exit with SIGINT. Thanks to @fermayo

## 0.3.2 (2013-12-18)

* Use sudo for ssh command if a privileged host port was specified.

## 0.3.1 (2013-11-27)

* Notify before starting tunnel and once started

## 0.3.0 (2013-10-09)

* Raise exception on permission denied (password)
* Made ssh connectivity checking more robust

## 0.2.0 (2013-09-26)

* Added setup.py and registered to PyPI
* Basic testing with nose and tox
* Support for Python 2.6 and 3.3 in addition to 2.7
* Added a command for running bgtunnel directly from the terminal

## 0.1.1 (2013-09-19)

* No longer requires sh package

## 0.2.2 (2013-09-26)

* Made bgtunnel into a proper console script, installed on setup

## 0.1.0 (2013-09-13)

* Initial version
