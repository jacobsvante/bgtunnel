"""bgtunnel - Initiate SSH tunnels in the background
Useful when you need to connect to a database only accessible through
another ssh-enabled host. It works by opening a port forwarding ssh
connection in the background, using threads. The connection(s) are
automatically closed when the process exits, or when explicitly calling
the `close` method of the returned SSHTunnelForwarderThread object.

Notes on default values
-----------------------

* Bind address and host address defaults to "127.0.0.1"
* SSH port defaults to 22
* Local port defaults to picking a random available one, accessible from the
  object returned by the `open` function

Usage examples
--------------

    # Enable forwarding for a MS SQL server running on the remote SSH host
    import bgtunnel
    >>> forwarder = bgtunnel.open(ssh_user='manager', ssh_address='1.2.3.4',
    ...                           bind_port=1433)
    >>> print(forwarder.host_port)
    59432
    >>> import somesqlpkg
    >>> conn = somesqlpkg.connect('mssql://myuser:mypassword@localhost:' +
                                                       forwarder.port)

    # Enable forwarding for an old AS400 DB2 server accessible only via
    # the remote SSH host. Multiple ports need to be opened.
    import bgtunnel
    >>> ports = (446, 449, 8470, 8471, 8472, 8473, 8474, 8475, 8476)
    >>> forwarders = []
    >>> for port in ports:
    ...     forwarders.append(bgtunnel.open(ssh_user='manager',
    ...                                     ssh_address='1.2.3.4',
                                            bind_address='192.168.0.5',
    ...                                     bind_port=port, host_port=port))
    >>> print(*tuple(f.host_port for f in forwarders))
    446
    449
    8470
    8471
    8472
    8473
    8474
    8475
    8476
    >>> import somesqlpkg
    >>> conn = somesqlpkg.connect('mssql://myuser:mypassword@localhost:446')

"""
from __future__ import print_function
import argparse
import getpass
import signal
import shlex
import socket
import subprocess as subp
import sys
import threading
import time

__version__ = '0.2.0'

# NOTE: Not including `open` in __all__ as doing `from bgtunnel import *`
#       would replace the builtin.
__all__ = ('SSHTunnelForwarderThread', )


class UnicodeMagicMixin(object):
    if sys.version_info > (3, 0):
        __str__ = lambda x: x.__unicode__()
    else:
        __str__ = lambda x: unicode(x).encode('utf-8')


class SSHTunnelConnectTimeout(Exception):
    """Raised when a timeout has been reached for connecting to SSH host """


class SSHTunnelError(Exception):
    """Raised when SSH connect returns an error """


class SSHStringValueError(Exception):
    """Raised when a value is invalid for an SSHString object """


class AddressPortStringValueError(Exception):
    """Raised when a value is invalid for an AddressPortString object """


class StopSSHTunnel(Exception):
    """Raised inside SSHTunnelForwarderThread to close the connection """


def get_ssh_path():
    proc = subp.Popen(('which', 'ssh'), stdout=subp.PIPE, stderr=subp.PIPE)
    stdout, stderr = proc.communicate()
    return stdout.strip()


def validate_ssh_cmd_exists(path):
    check_str = u'usage: ssh'
    proc = subp.Popen(('ssh', ), stdout=subp.PIPE, stderr=subp.PIPE)
    stdout, stderr = proc.communicate()
    if (check_str in stderr.decode('utf-8') or
        check_str in stdout.decode('utf-8')):
        return True
    else:
        return False


def get_available_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # Setting to port 0 binds to a random available port
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


class SSHString(UnicodeMagicMixin):

    validate_keys = ('user', 'address')
    user_default = getpass.getuser()
    port_default = 22
    addr_default = None
    exception_class = SSHStringValueError

    def __init__(self, user=None, address=None, port=None):

        self.user = user or self.user_default
        self.address = address or self.addr_default
        self.port = port or self.port_default

        self.validate()

    def validate(self):
        for key, val in vars(self).items():
            if key not in self.validate_keys:
                continue
            if not val:
                raise self.exception_class(u'{0} cannot be empty'.format(key))

    def __unicode__(self):
        return u'{0}@{1}'.format(self.user, self.address)

    def __repr__(self):
        return u'<{0}: {1}>'.format(self.__class__.__name__, self)

    def parse(self, s):
        user = address = port = None
        if '@' in s[1:]:
            user, _, s = s.partition('@')
        address, _, port = s.partition(':')
        return (user, address, port)


class AddressPortString(SSHString):

    validate_keys = ('address', 'port')
    port_default = None
    addr_default = '127.0.0.1'
    exception_class = AddressPortStringValueError

    def __unicode__(self):
        return u'{0}:{1}'.format(self.address, self.port)


class SSHTunnelForwarderThread(threading.Thread, UnicodeMagicMixin):
    """The SSH forwarding thread
    Usually not interacted with directly.
    """

    daemon = True

    def __setattrs(self, from_obj, attrs):
        assert len(attrs) == 2, 'Wrong length'
        for to_attr, from_attr in zip(attrs, ('address', 'port')):
            setattr(self, to_attr, getattr(from_obj, from_attr))

    def __init__(self, ssh_user=None, ssh_address=None, ssh_port=22,
                 bind_address='127.0.0.1', bind_port=None,
                 host_address='127.0.0.1', host_port=None,
                 silent=False, ssh_path=None):
        self.sigint_received = False
        self.stdout = None
        self.stderr = None
        self.ssh_path = ssh_path or get_ssh_path()

        self.ssh_is_ready = False

        # If the tunnel creation message should be suppressed
        self.silent = silent

        # The ssh connect string
        self.ssh_string = SSHString(user=ssh_user,
                                    address=ssh_address, port=ssh_port)
        self.ssh_user = self.ssh_string.user
        self.__setattrs(self.ssh_string, ('ssh_address', 'ssh_port'))

        # The host to bind to locally
        self.bind_string = AddressPortString(address=bind_address,
                                        port=bind_port or get_available_port())
        self.__setattrs(self.bind_string, ('bind_address', 'bind_port'))

        # The host on the remote end to connect to
        self.host_string = AddressPortString(address=host_address,
                                             port=host_port)
        self.__setattrs(self.host_string, ('host_address', 'host_port'))

        validate_ssh_cmd_exists(self.ssh_path)

        super(SSHTunnelForwarderThread, self).__init__()

    def __unicode__(self):
        return self.forwarder_string

    def __repr__(self):
        return u'<SSHTunnelForwarderThread: {0}>'.format(self)

    @property
    def forwarder_string(self):
        return u'{0}:{1}'.format(self.bind_string, self.host_string)

    @property
    def cmd(self):
        ssh_path = shlex.split(self.ssh_path)
        return ssh_path + [
            '-T',
            '-p', str(self.ssh_string.port),
            '-L', self.forwarder_string,
            str(self.ssh_string),
        ]

    @property
    def cmd_string(self):
        return subp.list2cmdline(self.cmd)

    def _get_ssh_process(self):
        if not hasattr(self, '_process'):
            self._process = subp.Popen(self.cmd, stdout=subp.PIPE,
                               stderr=subp.PIPE, stdin=subp.PIPE)
        return self._process

    def _validate_ssh_process(self, proc):
        while True:
            stdout_line = proc.stdout.readline()
            if stdout_line:
                return True
            stderr_line = proc.stderr.readline()
            if stderr_line:
                return stderr_line

    def close(self):
        self._process.send_signal(signal.SIGINT)
        self.sigint_received = True

    def run(self):
        proc = self._get_ssh_process()
        validation_ret = self._validate_ssh_process(proc)
        if validation_ret is True:
            if not self.silent:
                print(u'Started tunnel with command:'
                      u' {0}'.format(self.cmd_string))
            self.ssh_is_ready = True
        else:
            self.stderr = validation_ret
            return

        wait_time = 0.5
        retcode = None
        while retcode is None:
            if self.sigint_received:
                return
            retcode = proc.poll()
            if retcode is not None and retcode > 0:
                self.stderr = proc.stderr.read()
                return
            else:
                self.stdout
            time.sleep(wait_time)


def open(*args, **kwargs):
    """Open an SSH tunnel in the background
    Blocks until the connection is successfully created or 60 seconds
    have passed. The timeout value can be overridden with the `timeout`
    kwarg.
    """
    wait_time = 0.1
    timeout = timeout_countdown = kwargs.pop('timeout', 60)
    t = SSHTunnelForwarderThread(*args, **kwargs)
    t.start()
    msg = 'The connection timeout value of {0} seconds has passed for {1}.'
    while True:
        if t.stderr:
            raise SSHTunnelError(t.stderr)
        if timeout_countdown <= 0:
            raise SSHTunnelConnectTimeout(msg.format(timeout, t.cmd))
        if t.ssh_is_ready is True:
            break
        else:
            timeout_countdown - wait_time
            time.sleep(wait_time)
    return t


__cmddoc__ = """bgtunnel - Initiate SSH tunnels
Useful when you need to connect to a database only accessible through
another ssh-enabled host. It works by opening a port forwarding ssh
connection in the background, using threads.
"""

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description=__cmddoc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('-u', '--ssh-user', help='The ssh username')
    parser.add_argument('-a', '--ssh-address', help='The ssh address')
    parser.add_argument('-P', '--ssh-port', type=int, default=22,
                        help='The ssh port')
    parser.add_argument('-b', '--bind-address', help="The bind address.")
    parser.add_argument('-B', '--bind-port', type=int, help="The bind port.")
    parser.add_argument('-r', '--host-address', help="The host address.")
    parser.add_argument('-R', '--host-port', type=int, help="The host port.")
    args = parser.parse_args()
    open(**vars(args))

    # Keep the process running so the SSH connection doesn't close.
    while True:
        time.sleep(1)
