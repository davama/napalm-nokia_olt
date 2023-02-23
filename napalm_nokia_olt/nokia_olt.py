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

# napalm_nokia_olt
class NokiaOltDriver(NetworkDriver):
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
            'session_log': None,
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

    # taken from netmiko.base_connections
    def _strip_ansi_escape_codes(self, string_buffer: str) -> str:
        """
        Remove any ANSI (VT100) ESC codes from the output

        http://en.wikipedia.org/wiki/ANSI_escape_code

        Note: this does not capture ALL possible ANSI Escape Codes only the ones
        I have encountered

        Current codes that are filtered:
        ESC = '\x1b' or chr(27)
        ESC = is the escape character [^ in hex ('\x1b')
        ESC[24;27H   Position cursor
        ESC[?25h     Show the cursor
        ESC[E        Next line (HP does ESC-E)
        ESC[K        Erase line from cursor to the end of line
        ESC[2K       Erase entire line
        ESC[1;24r    Enable scrolling from start to row end
        ESC[?6l      Reset mode screen with options 640 x 200 monochrome (graphics)
        ESC[?7l      Disable line wrapping
        ESC[2J       Code erase display
        ESC[00;32m   Color Green (30 to 37 are different colors)
        ESC[6n       Get cursor position
        ESC[1D       Move cursor position leftward by x characters (1 in this case)
        ESC[9999B    Move cursor down N-lines (very large value is attempt to move to the
                     very bottom of the screen).

        HP ProCurve and Cisco SG300 require this (possible others).

        :param string_buffer: The string to be processed to remove ANSI escape codes
        :type string_buffer: str
        """  # noqa

        code_position_cursor = chr(27) + r"\[\d+;\d+H"
        code_show_cursor = chr(27) + r"\[\?25h"
        code_next_line = chr(27) + r"E"
        code_erase_line_end = chr(27) + r"\[K"
        code_erase_line = chr(27) + r"\[2K"
        code_erase_start_line = chr(27) + r"\[K"
        code_enable_scroll = chr(27) + r"\[\d+;\d+r"
        code_insert_line = chr(27) + r"\[(\d+)L"
        code_carriage_return = chr(27) + r"\[1M"
        code_disable_line_wrapping = chr(27) + r"\[\?7l"
        code_reset_mode_screen_options = chr(27) + r"\[\?\d+l"
        code_reset_graphics_mode = chr(27) + r"\[00m"
        code_erase_display = chr(27) + r"\[2J"
        code_erase_display_0 = chr(27) + r"\[J"
        code_graphics_mode = chr(27) + r"\[\dm"
        code_graphics_mode1 = chr(27) + r"\[\d\d;\d\dm"
        code_graphics_mode2 = chr(27) + r"\[\d\d;\d\d;\d\dm"
        code_graphics_mode3 = chr(27) + r"\[(3|4)\dm"
        code_graphics_mode4 = chr(27) + r"\[(9|10)[0-7]m"
        code_get_cursor_position = chr(27) + r"\[6n"
        code_cursor_position = chr(27) + r"\[m"
        code_attrs_off = chr(27) + r"\[0m"
        code_reverse = chr(27) + r"\[7m"
        code_cursor_left = chr(27) + r"\[\d+D"
        code_cursor_forward = chr(27) + r"\[\d*C"
        code_cursor_up = chr(27) + r"\[\d*A"
        code_cursor_down = chr(27) + r"\[\d*B"
        code_wrap_around = chr(27) + r"\[\?7h"
        code_bracketed_paste_mode = chr(27) + r"\[\?2004h"

        code_set = [
            code_position_cursor,
            code_show_cursor,
            code_erase_line,
            code_enable_scroll,
            code_erase_start_line,
            code_carriage_return,
            code_disable_line_wrapping,
            code_erase_line_end,
            code_reset_mode_screen_options,
            code_reset_graphics_mode,
            code_erase_display,
            code_graphics_mode,
            code_graphics_mode1,
            code_graphics_mode2,
            code_graphics_mode3,
            code_graphics_mode4,
            code_get_cursor_position,
            code_cursor_position,
            code_erase_display,
            code_erase_display_0,
            code_attrs_off,
            code_reverse,
            code_cursor_left,
            code_cursor_up,
            code_cursor_down,
            code_cursor_forward,
            code_wrap_around,
            code_bracketed_paste_mode,
        ]

        output = string_buffer
        for ansi_esc_code in code_set:
            output = re.sub(f'(-|\\\|\\/|\s|\|){ansi_esc_code}', "", output)

        return output

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
        port_output = self._strip_ansi_escape_codes(port_output)

        hostname_xml_tree = ET.fromstring(hostname_output)
        os_xml_tree = ET.fromstring(os_output)
        sn_xml_tree = ET.fromstring(sn_output)
        port_xml_tree = ET.fromstring(port_output)

        facts = {}
        port_list = []

        # create default dict and get hostname
        for elem in hostname_xml_tree.findall('.//hierarchy[@name="isam"]'):
            dummy_data = self._convert_xml_elem_to_dict(elem=elem)
            if 'description' in dummy_data:
                hostname = dummy_data['description']
                facts['hostname'] = hostname
                facts['vendor'] = 'Nokia'
                facts['uptime'] = ''
                facts['os_version'] = ''
                facts['serial_number'] = ''
                facts['model'] = ''
                facts['fqdn'] = 'Unknown'
                facts['interface_list'] = []

        # get os_version
        for elem in os_xml_tree.findall('.//hierarchy[@name="ansi"]'):
            dummy_data = self._convert_xml_elem_to_dict(elem=elem)
            if 'isam-feature-group' in dummy_data:
                os_version = dummy_data['isam-feature-group']
                facts['os_version'] = os_version

        # get serial_number and model
        for elem in sn_xml_tree.findall('.//hierarchy[@name="shelf"]'):
            dummy_data = self._convert_xml_elem_to_dict(elem=elem)
            if 'serial-no' in dummy_data:
                serial_number = dummy_data['serial-no']
                facts['serial_number'] = serial_number
            if 'variant' in dummy_data:
                model_number = dummy_data['variant']
                facts['model'] = model_number

        # get uptime
        for line in uptime_output.splitlines():
            split_line = line.split()
            # if line is empty, continue
            if not split_line:
                continue
            if 'System' in split_line[0]:
                if 'Up' in split_line[1]:
                    for r in range(4):
                        split_line.pop(0)
                    uptime = ' '.join(split_line)
                    facts['uptime'] = uptime
        # get interface_list
        for elem in port_xml_tree.findall('.//instance'):
            dummy_data = self._convert_xml_elem_to_dict(elem=elem)
            if 'port' in dummy_data:
                port_raw = dummy_data['port']
                if 'vlan' in port_raw:
                    continue
            port_list.append(port_raw)
        port_list.sort()
        facts['interface_list'] = port_list
        return facts

    def get_vlans(self):
        """
        get_vlans function
        """
        vlan_name_command = 'show vlan name'
        tagging_command = 'show vlan residential-bridge extensive'

        vlan_name_output = self._send_command(vlan_name_command, xml_format=True)
        tagging_output = self._send_command(tagging_command, xml_format=True)

        output_xml_tree = ET.fromstring(vlan_name_output)
        tag_xml_tree = ET.fromstring(tagging_output)

        vlans = {}
        # create default dict and get vlan_id and name
        for elem in output_xml_tree.findall('.//instance'):
            dummy_data = self._convert_xml_elem_to_dict(elem=elem)
            primary_key = dummy_data['id']
            if primary_key not in vlans:
                vlans[primary_key] = {}
                vlans[primary_key]['name'] = dummy_data['name']
                vlans[primary_key]['interfaces'] = []
        # get tagged/untagged ports
        for elem in tag_xml_tree.findall('.//instance'):
            dummy_data = self._convert_xml_elem_to_dict(elem=elem)
            vlan_id = dummy_data['vlan-id']
            port_raw = dummy_data['vlan-port']
            port = ':'.join(port_raw.replace('vlan-port', 'uni').split(':')[0:2])
            if 'single-tagged' in dummy_data['transmit-mode'] or 'untagged' in dummy_data['transmit-mode']:
                vlans[vlan_id]['interfaces'].append(port)
        return vlans
