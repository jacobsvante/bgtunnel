# coding: utf-8
from __future__ import print_function
import os
import sys
import six
from getpass import getuser
import bgtunnel
from bgtunnel import get_available_port


dummy_ssh_cmd = '{0} {1}'.format(sys.executable,
  os.path.join(os.path.dirname(os.path.realpath(__file__)), 'bin/sshdummy.py'))


def test_create_tunnel():
    ssh_address = '1.2.3.4'
    host_address = '5.6.7.8'
    bind_address = '9.10.11.12'
    current_user = getuser()
    host_port = get_available_port()
    bind_port = get_available_port()
    t = bgtunnel.open(ssh_user=current_user, ssh_address=ssh_address,
                      host_address=host_address, bind_address=bind_address,
                      host_port=host_port, bind_port=bind_port,
                      ssh_path=dummy_ssh_cmd)

    assert t.ssh_user == current_user
    assert t.host_port == host_port
    assert t.bind_port == bind_port
    assert t.ssh_address == ssh_address
    assert t.host_address == host_address
    assert t.bind_address == bind_address

def test_get_ssh_path():
    ssh_path = bgtunnel.get_ssh_path()
    assert isinstance(ssh_path, six.string_types)
