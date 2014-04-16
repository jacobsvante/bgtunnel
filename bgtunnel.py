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
* Bind port defaults to picking a random available one, accessible from the
  object returned by the `open` function

Usage examples
--------------

    # Enable forwarding for a MS SQL server running on the remote SSH host
    >>> import bgtunnel
    >>> forwarder = bgtunnel.open(ssh_user='manager', ssh_address='1.2.3.4',
    ...                           host_port=1433)
    >>> print(forwarder.bind_port)
    59432
    >>> import somesqlpkg
    >>> conn = somesqlpkg.connect('mssql://myuser:mypassword@localhost:' +
                                                       forwarder.port)

    # Enable forwarding for an old AS400 DB2 server accessible only via
    # the remote SSH host. Multiple ports need to be opened.
    >>> import bgtunnel
    >>> ports = [446, 449] + range(8470, 8477)
    >>> forwarders = []
    >>> for port in ports:
    ...     forwarders.append(bgtunnel.open(ssh_user='manager',
    ...                                     ssh_address='1.2.3.4',
                                            host_address='192.168.0.5',
    ...                                     host_port=port, bind_port=port))
    >>> print('\n'.join(f.bind_port for f in forwarders))
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
import os
import shlex
import socket
import subprocess as subp
import sys
import threading
import time

try:
    from Queue import Queue, Empty  # py2
except ImportError:
    from queue import Queue, Empty  # py3

__version_info__ = (0, 3, 6)
__version__ = '.'.join(str(i) for i in __version_info__)

# NOTE: Not including `open` in __all__ as doing `from bgtunnel import *`
#       would replace the builtin.
__all__ = ('SSHTunnelForwarderThread', )


class RawArgumentDefaultsHelpFormatter(argparse.ArgumentDefaultsHelpFormatter,
                                       argparse.RawTextHelpFormatter):
    """Retain both raw text descriptions and argument defaults"""
    pass


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


ON_POSIX = 'posix' in sys.builtin_module_names


def normalize_path(path):
    return os.path.abspath(os.path.expanduser(path))


def is_root_user():
    return os.geteuid() == 0


def enqueue_output(out, queue):
    for line in iter(out.readline, b''):
        queue.put(line)
    out.close()


def get_ssh_path():
    proc = subp.Popen(('which', 'ssh'), stdout=subp.PIPE, stderr=subp.PIPE)
    stdout, stderr = proc.communicate()
    return stdout.strip().decode('utf-8')


def validate_ssh_cmd_exists(path):
    check_str = u'usage: ssh'
    proc = subp.Popen(('ssh', ), stdout=subp.PIPE, stderr=subp.PIPE)
    stdout, stderr = proc.communicate()
    if (check_str in stderr.decode('utf-8')
            or check_str in stdout.decode('utf-8')):
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
                raise self.exception_class(u'{} cannot be empty'.format(key))

    def __unicode__(self):
        return u'{}@{}'.format(self.user, self.address)

    def __repr__(self):
        return u'<{}: {}>'.format(self.__class__.__name__, self)

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
        return u'{}:{}'.format(self.address, self.port)


class SSHTunnelForwarderThread(threading.Thread, UnicodeMagicMixin):
    """The SSH forwarding thread
    Usually not interacted with directly.
    """

    # Needs to be True so that the thread dies when bgtunnel quits.
    daemon = True

    def __setattrs(self, from_obj, attrs):
        assert len(attrs) == 2, 'Wrong length'
        for to_attr, from_attr in zip(attrs, ('address', 'port')):
            setattr(self, to_attr, getattr(from_obj, from_attr))

    def __init__(self, ssh_user=None, ssh_address=None, ssh_port=22,
                 bind_address='127.0.0.1', bind_port=None,
                 host_address='127.0.0.1', host_port=None,
                 silent=False, ssh_path=None, dont_sudo=False,
                 identity_file=None, expect_hello=True):
        self.should_exit = False
        self.dont_sudo = dont_sudo
        self.stdout = None
        self.stderr = None
        self.ssh_path = ssh_path or get_ssh_path()
        self.expect_hello = expect_hello

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
                                             port=(bind_port or
                                                   get_available_port()))
        self.__setattrs(self.bind_string, ('bind_address', 'bind_port'))

        # The host on the remote end to connect to
        self.host_string = AddressPortString(address=host_address,
                                             port=host_port)
        self.__setattrs(self.host_string, ('host_address', 'host_port'))

        validate_ssh_cmd_exists(self.ssh_path)

        # The path to the private key file to use
        self.identity_file = normalize_path(identity_file or '') or None

        super(SSHTunnelForwarderThread, self).__init__()

    @property
    def use_sudo(self):
        if self.dont_sudo is True:
            return False
        elif is_root_user():
            return False
        else:
            return self.host_string.port <= 1024

    def __unicode__(self):
        return self.forwarder_string

    def __repr__(self):
        return u'<SSHTunnelForwarderThread: {}>'.format(self)

    @property
    def forwarder_string(self):
        return u'{}:{}'.format(self.bind_string, self.host_string)

    def get_ssh_options(self):
        def opts(*opts):
            return [s for opt in opts for s in ['-o', opt]]
        return opts('BatchMode=yes')

    @property
    def cmd(self):
        ssh_path = shlex.split(self.ssh_path)

        if self.use_sudo:
            ssh_path = ['sudo'] + ssh_path

        options = self.get_ssh_options()

        if self.identity_file is not None:
            options += ['-i', self.identity_file]

        return ssh_path + options + [
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
            self._process = subp.Popen(
                self.cmd,
                stdout=subp.PIPE,
                stderr=subp.PIPE,
                stdin=subp.PIPE,
                close_fds=ON_POSIX,
            )
            if self.use_sudo:
                print('\nA privileged host port was specified without '
                      'elevating the process, you might be prompted to enter '
                      'your sudo password in order to run the ssh process in '
                      'elevated mode.')
        return self._process

    def get_output_queue(self, file_handle):
        q = Queue()
        t = threading.Thread(target=enqueue_output, args=(file_handle, q))
        t.daemon = True
        t.start()
        return q

    def _validate_ssh_process(self, proc):
        if not self.expect_hello:
            return True
        stdout_queue = self.get_output_queue(proc.stdout)
        stderr_queue = self.get_output_queue(proc.stderr)

        while True:
            try:
                stderr_line = stderr_queue.get_nowait()
            except Empty:
                pass
            else:
                if stderr_line.strip():
                    return stderr_line
            try:
                stdout_line = stdout_queue.get_nowait()
            except Empty:
                pass
            else:
                if stdout_line.strip():
                    return True

    def close(self):
        self._process.terminate()
        self._process.wait()
        self.should_exit = True

    def run(self):
        if not self.silent:
                print(u'Starting tunnel with command:'
                      u' {}...'.format(self.cmd_string), end='')
        proc = self._get_ssh_process()
        validation_ret = self._validate_ssh_process(proc)
        if validation_ret is True:
            if not self.silent:
                print(u'started!')
            self.ssh_is_ready = True
        else:
            self.stderr = validation_ret
            return

        wait_time = 0.5
        retcode = None
        while retcode is None:
            if self.should_exit:
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
    msg = 'The connection timeout value of {} seconds has passed for {}.'
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


def main():
    """bgtunnel - Initiate SSH tunnels
    Useful when you need to connect to a database only accessible through
    another ssh-enabled host. It works by opening a port forwarding ssh
    connection in the background, using threads.
    """
    parser = argparse.ArgumentParser(
        description=main.__doc__,
        formatter_class=RawArgumentDefaultsHelpFormatter,
    )
    parser.add_argument('-u', '--ssh-user', help='The ssh username')
    parser.add_argument('-a', '--ssh-address', help='The ssh address')
    parser.add_argument('-P', '--ssh-port', type=int, default=22,
                        help='The ssh port')
    parser.add_argument('-b', '--bind-address', help="The bind address.")
    parser.add_argument('-B', '--bind-port', type=int, help="The bind port.")
    parser.add_argument('-r', '--host-address', help="The host address.")
    parser.add_argument('-R', '--host-port', type=int, help="The host port.")
    parser.add_argument('-i', '--identity-file', help="Identity file path.",
                        default=None)
    parser.add_argument('-n', '--no-sudo', dest='dont_sudo',
                        action='store_const', default=False, const=True,
                        help="Don't use sudo when a privileged host port is "
                             "specified and not running as root user.")
    args = parser.parse_args()
    open(**vars(args))

    # Keep the process running so the SSH connection doesn't close.
    while True:
        time.sleep(1)


if __name__ == '__main__':
    main()
