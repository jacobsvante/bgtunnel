# coding: utf-8
import unittest
import os.path as op
import sys
import six
from getpass import getuser
import bgtunnel
from bgtunnel import get_available_port


dummy_ssh_cmd = '{0} {1}'.format(
    sys.executable,
    op.join(op.dirname(op.realpath(__file__)), 'bin/sshdummy.py')
)


class BaseTestCase(unittest.TestCase):

    def setUp(self):
        self.ssh_address = '1.2.3.4'
        self.host_address = '5.6.7.8'
        self.bind_address = '9.10.11.12'
        self.current_user = getuser()
        self.host_port = get_available_port()
        self.bind_port = get_available_port()
        self.default_open_kwargs = dict(
            ssh_user=self.current_user, ssh_address=self.ssh_address,
            host_address=self.host_address, bind_address=self.bind_address,
            host_port=self.host_port, bind_port=self.bind_port,
            ssh_path=dummy_ssh_cmd,
        )

    def test_settings(self):
        open_kwargs = self.default_open_kwargs.copy()
        t = bgtunnel.open(**open_kwargs)

        assert t.ssh_user == self.current_user
        assert t.host_port == self.host_port
        assert t.bind_port == self.bind_port
        assert t.ssh_address == self.ssh_address
        assert t.host_address == self.host_address
        assert t.bind_address == self.bind_address
        assert t.get_ssh_options() == [
            '-o', 'BatchMode=yes',
            '-o', 'ConnectionAttempts=1',
            '-o', 'ConnectTimeout=60',
        ]
        t.close()

    def test_strict_host_key_checking(self):
        t = bgtunnel.open(**self.default_open_kwargs)
        assert 'StrictHostKeyChecking=yes' not in t.get_ssh_options()
        assert 'StrictHostKeyChecking=no' not in t.get_ssh_options()
        t.close()

        for py_val, ssh_val in ((True, 'yes'), (False, 'no')):
            open_kwargs = self.default_open_kwargs.copy()
            open_kwargs['strict_host_key_checking'] = py_val
            t = bgtunnel.open(**open_kwargs)
            assert 'StrictHostKeyChecking={}'.format(ssh_val) in t.get_ssh_options()
            t.close()

    def test_get_ssh_path(self):
        ssh_path = bgtunnel.get_ssh_path()
        assert isinstance(ssh_path, six.string_types)
