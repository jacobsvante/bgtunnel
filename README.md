[![Build Status](https://travis-ci.org/jmagnusson/bgtunnel.png?branch=master)](https://travis-ci.org/jmagnusson/bgtunnel)

**Author:** Jacob Magnusson. [Follow me on Twitter][twitter]


## What is this?

`bgtunnel` is a python module for easily creating ssh tunnels in the background, from within python. An example use case is when you want to access a remote database. With `bgtunnel` all you need is ssh access to the remote machine and python installed.


## Installation

Install using `pip`:

    pip install bgtunnel


## Dependencies

python 2.7+ or 3.3+


## Testing

Clone the repo:

    git clone git@github.com:jmagnusson/bgtunnel.git

Install requirements for testing:

    pip install -r test_requirements.txt

Ensure that you have all python versions listed in `tox.ini` then to run the tests simply issue the following:

    tox


## Documentation
[docs]

[twitter]: https://twitter.com/pyjacob
[docs]: https://github.com/jmagnusson/bgtunnel
