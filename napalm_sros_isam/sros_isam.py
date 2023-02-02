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

import xml.etree.ElementTree as ET

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

    def _send_command(self, command, xml_format=False):
        """
        Send command to device with xml_format option
        """
        # if true; append xml to the end of the command
        if xml_format:
            command = command + ' ' + 'xml'
        output = self.device.send_command(command, expect_string=r'#$')
        return output

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
            'exit all'
        ]
        for command in cmds:
            self._send_command(command)

    def _convert_xml_elem_to_dict(self, elem=None):
        """
        convert xml output to dict data
        """
        data = {}
        for e in elem.iter():
            if 'instance' == e.tag:
                continue
            key_name = e.attrib['name'].replace(' ', '_')
            key_value = e.text
            data[key_name] = key_value
        return data

    def get_config(self, retrieve="all", full=False, sanitized=False):
        """
        get_config for sros_isam.
        """
        configs = {
            "running": "",
            "startup": "No Startup",
            "candidate": "No Candidate"
        }

        if retrieve in ("all", "running"):
            command = "info configure"
            output_ = self._send_command(command)
            if output_:
                configs['running'] = output_
                data = str(configs['running']).split("\n")
                non_empty_lines = [line for line in data if line.strip() != ""]

                string_without_empty_lines = ""
                for line in non_empty_lines:
                    string_without_empty_lines += line + "\n"
                configs['running'] = string_without_empty_lines

        if retrieve.lower() in ('startup', 'all'):
            pass
        return configs

    def get_facts(self):
        """
        get_facts for device

        .. note:
            serial_number and model are taken from the chassis (shelf 1/1)
        """
        hostname_command = 'show equipment isam detail'
        os_command = 'show software-mngt version ansi'
        uptime_command = 'show core1-uptime'
        sn_command = 'show equipment shelf 1/1 detail'
        port_command = 'show interface port'

        hostname_output = self._send_command(hostname_command, xml_format=True)
        os_output = self._send_command(os_command, xml_format=True)
        uptime_output = self._send_command(uptime_command)
        sn_output = self._send_command(sn_command, xml_format=True)
        port_output = self._send_command(port_command, xml_format=True)

        # some ansi char codes cleanup
        port_output = self.device.strip_ansi_escape_codes(port_output)
        port_output = port_output.replace('-\\','')

        hostname_xml_tree = ET.fromstring(hostname_output)
        os_xml_tree = ET.fromstring(os_output)
        sn_xml_tree = ET.fromstring(sn_output)
        port_xml_tree = ET.fromstring(port_output)

        data = {}
        for elem in hostname_xml_tree.findall('.//hierarchy[@name="isam"]'):
            dummy_data = self._convert_xml_elem_to_dict(elem=elem)
            if 'description' in dummy_data:
                hostname = dummy_data['description']
                data['hostname'] = hostname
                data['vendor'] = 'Nokia'
                data['uptime'] = ''
                data['os_version'] = ''
                data['serial_number'] = ''
                data['model'] = ''
                data['fqdn'] = 'Unknown'
                data['interface_list'] = []

        for elem in os_xml_tree.findall('.//hierarchy[@name="ansi"]'):
            dummy_data = self._convert_xml_elem_to_dict(elem=elem)
            if 'isam-feature-group' in dummy_data:
                os_version = dummy_data['isam-feature-group']
                data['os_version'] = os_version

        for elem in sn_xml_tree.findall('.//hierarchy[@name="shelf"]'):
            dummy_data = self._convert_xml_elem_to_dict(elem=elem)

    def get_vlans(self):
        """
        get_vlans attempt

        .. note:
            cannot easily determine if a vlan is voice or not. Default will be false
        """
        vlan_name_command = 'show vlan name'
        tagging_command = 'show vlan residential-bridge extensive'

        vlan_name_output = self._send_command(vlan_name_command, xml_format=True)
        tagging_output = self._send_command(tagging_command, xml_format=True)

        output_xml_tree = ET.fromstring(vlan_name_output)
        tag_xml_tree = ET.fromstring(tagging_output)

        data = {}
        # get vlan id and name
        # additionally set other needed keys
        for elem in output_xml_tree.findall('.//instance'):
            dummy_data = self._convert_xml_elem_to_dict(elem=elem)
            primary_key = dummy_data['id']
            if primary_key not in data:
                data[primary_key] = {}
                data[primary_key]['id'] = primary_key
                data[primary_key]['name'] = dummy_data['name']
                data[primary_key]['voice'] = False
                data[primary_key]['tagged'] = []
                data[primary_key]['untagged'] = []

        # get tagged/untagged ports
        for elem in tag_xml_tree.findall('.//instance'):
            dummy_data = self._convert_xml_elem_to_dict(elem=elem)
            vlan_id = dummy_data['vlan-id']
            port_raw = dummy_data['vlan-port']
            port = ':'.join(port_raw.replace('vlan-port', 'uni').split(':')[0:2])
            if 'single-tagged' in dummy_data['transmit-mode']:
                data[vlan_id]['tagged'].append(port)
            if 'untagged' in dummy_data['transmit-mode']:
                data[vlan_id]['untagged'].append(port)

        return data
