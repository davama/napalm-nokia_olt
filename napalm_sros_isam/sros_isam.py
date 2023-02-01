# -*- coding: utf-8 -*-
"""NAPALM Nokia OLT Handler."""

from __future__ import print_function
from __future__ import unicode_literals

import re
import sys
import socket
import telnetlib

from netmiko import ConnectHandler
from napalm.base.base import NetworkDriver
from napalm.base.exceptions import (
    ConnectionClosedException,
    ConnectionException,
)

import napalm.base.constants as C
import napalm.base.helpers


class SrosIsamDriver(NetworkDriver):
    """NAPALM Nokia OLT Handler."""

    def __init__(self, hostname, username, password, timeout=60, optional_args=None):
        """Constructor."""
        if optional_args is None:
            optional_args = {}
        self.transport = optional_args.get("transport", "ssh")
        self.hostname = hostname
        self.username = username
        self.password = password
        self.timeout = timeout

        # Netmiko possible arguments
        netmiko_argument_map = {
            "port": None,
            "secret": "",
            "verbose": False,
            "keepalive": 30,
            "global_delay_factor": 1,
            "use_keys": False,
            "key_file": None,
            "ssh_strict": False,
            "system_host_keys": False,
            "alt_host_keys": False,
            "alt_key_file": "",
            "ssh_config_file": None,
            "read_timeout_override": None,
        }

        # Build dict of any optional Netmiko args
        self.netmiko_optional_args = {}
        for k, v in netmiko_argument_map.items():
            try:
                self.netmiko_optional_args[k] = optional_args[k]
            except KeyError:
                pass
        self.global_delay_factor = optional_args.get("global_delay_factor", 1)
        self.port = optional_args.get("port", 22)

        self.device = None
        self.config_replace = False
        self.interface_map = {}
        self.profile = ["sros_isam"]

    def open(self):
        """Open a connection to the device."""
        device_type = "cisco_ios_ssh"
        if self.transport == "telnet":
            device_type = "cisco_ios_telnet"
        self.device = ConnectHandler(
            device_type=device_type,
            host=self.hostname,
            username=self.username,
            password=self.password,
            **self.netmiko_optional_args
        )
        self._prep_session()
        # ensure in enable mode
        ## self.device.enable()

    def close(self):
        """Close the connection to the device."""
        self.device.disconnect()

    def is_alive(self):
        """Returns a flag with the state of the connection."""
        null = chr(0)
        if self.device is None:
            return {'is_alive': False}
        else:
            # SSH
            try:
                # Try sending ASCII null byte to maintain the connection alive
                self.device.write_channel(null)
                return {'is_alive': self.device.remote_conn.transport.is_active()}
            except (socket.error, EOFError):
                # If unable to send, we can tell for sure that the connection is unusable
                return {'is_alive': False}
        ## return {'is_alive': False}

    def _prep_session(self):
        cmds = [
            'environment print no-more',
            'environment inhibit-alarms',
            'back'
        ]
        for command in cmds:
            self.device.send_command(command, expect_string=r'#')

    def get_config(self):
        cmd1 = 'show equipment ont interface'
        cmd2 = 'show equipment ont status pon'
        cmd3 = 'show equipment ont status x-pon'
        cmd4 = 'show vlan residential-bridge extensive'
