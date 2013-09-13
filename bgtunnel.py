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

    # Enable forwarding of a MS SQL server running at the default port
    import tunnel
    >>> forwarder = bgtunnel.open(ssh_user='manager', ssh_address='1.2.3.4',
    ...                           bind_port=1433)
    >>> print(forwarder.host_port)
    59432
    >>> import somesqlpkg
    >>> somesqlpkg.connect('mssql://myuser:mypassword@localhost:' +
                                                       forwarder.port)


    # As above but with SSH-style syntax and explicitly defined local port
    >>> forwarder = bgtunnel.open(ssh_string='manager@1.2.3.4',
    ...                           ssh_port='22',
    ...                           bind_string='127.0.0.1:1433',
    ...                           host_string='127.0.0.1:24314')
    >>> print(forwarder.host_port)
    24314

"""
from __future__ import print_function
import socket
import time
import threading
import getpass
import sh

__version__ = '0.1.0'
__all__ = ('open', 'SSHTunnelForwarderThread')


class SSHTunnelTimeout(Exception):
    """ Raised when a timeout has been reached for an SSH tunnel connection """


class SSHStringValueError(Exception):
    """ Raised when a value is invalid for an SSHString object """


class AddressPortStringValueError(Exception):
    """ Raised when a value is invalid for an AddressPortString object """


class StopSSHTunnel(Exception):
    """ Raised inside SSHTunnelForwarderThread to close the connection """


def get_available_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # Setting to port 0 binds to a random available port
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


class SSHString(object):

    validate_keys = ('user', 'address')
    user_default = getpass.getuser()
    port_default = 22
    addr_default = None
    exception_class = SSHStringValueError

    def __init__(self, string=None, user=None, address=None, port=None):
        self.user, self.address, self.port = self.parse(string or '')

        if user is not None:
            self.user = user
        if address is not None:
            self.address = address
        if port is not None:
            self.port = port

        self.user = self.user or self.user_default
        self.address = self.address or self.addr_default
        self.port = self.port or self.port_default

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


class SSHTunnelForwarderThread(threading.Thread):

    daemon = True

    def __setattrs(self, from_obj, attrs):
            assert len(attrs) == 2, 'Wrong length'
            for to_attr, from_attr in zip(attrs, ('address', 'port')):
                setattr(self, to_attr, getattr(from_obj, from_attr))

    def __init__(self, ssh_string=None, bind_string=None, host_string=None,
                 ssh_user=None, ssh_address=None, ssh_port=22,
                 bind_address='127.0.0.1', bind_port=None,
                 host_address='127.0.0.1', host_port=None,
                 silent=False):

        host_port = host_port or get_available_port()

        # Set to true once connected
        self.ssh_is_ready = False

        # If the tunnel creation message should be suppressed
        self.silent = silent

        # The ssh connect string
        self.ssh_string = SSHString(ssh_string, user=ssh_user,
                                    address=ssh_address, port=ssh_port)
        self.ssh_user = self.ssh_string.user
        self.__setattrs(self.ssh_string, ('ssh_address', 'ssh_port'))

        # The host to bind to locally
        self.bind_string = AddressPortString(bind_string, address=bind_address,
                                             port=bind_port)
        self.__setattrs(self.bind_string, ('bind_address', 'bind_port'))

        # The host on the remote end to connect to
        self.host_string = AddressPortString(host_string, address=host_address,
                                             port=host_port)
        self.__setattrs(self.host_string, ('host_address', 'host_port'))

        super(SSHTunnelForwarderThread, self).__init__()

    def __unicode__(self):
        return self.forwarder_string

    def __repr__(self):
        return u'<SSHTunnelForwarderThread: {0}>'.format(self)

    @property
    def forwarder_string(self):
        return u'{0}:{1}'.format(self.bind_string, self.host_string)

    def close(self):
        # TODO: Implement
        pass

    def run(self):
        cmd = sh.ssh(self.ssh_string, '-T', p=self.ssh_string.port,
                     L=self.forwarder_string, _iter=True)

        # Iterate over stdout (default for _iter method) and break
        # when a line is encountered
        for line in cmd:
            if line:
                self.ssh_is_ready = True
                if not self.silent:
                    print(u'Started tunnel with command: {0}'.format(cmd.ran))
                break
        # Keep the process alive
        cmd.wait()


def open(*args, **kwargs):
    """ Shortcut to opening an ssh tunnel
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
        if timeout_countdown <= 0:
            raise SSHTunnelTimeout(msg.format(timeout, t))
        if t.ssh_is_ready is True:
            break
        else:
            timeout_countdown - wait_time
            time.sleep(wait_time)
    return t
