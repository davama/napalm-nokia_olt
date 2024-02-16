# -*- coding: utf-8 -*-
"""NAPALM Nokia OLT Handler."""

from __future__ import print_function
from __future__ import unicode_literals
import socket
import re
from netmiko import ConnectHandler
from napalm.base.base import NetworkDriver
import xml.etree.ElementTree as ET
from collections import defaultdict


PORT_REGEX = r"^(?!=|-|\s|Port|Id.).+$"
REMOTE_HOST_REGEX = r"^System Name[\s:]+(.+)$"
REMOTE_PORT_REGEX = r"""^Port Id[\s:]+([0-9a-zA-Z:]+[\n]{0,}[\s"\/a-zA-Z0-9]+$)"""
REMOTE_CHASSIS_REGEX = r"^Chassis Id[\s]{3,}[:\s](.+)$"
REMOTE_PORT_DESCR_REGEX = r"^Port Description[:\s]+(.+)$"
REMOTE_SYS_DESCR_REGEX = r"(?<=^System Description)\s*:\s(.*)(?=\n\n\n)"
REMOTE_SYS_CAP_REGEX = r"^Supported Caps[\s:]+(.+)$"
REMOTE_SYS_EN_CAP_REGEX = r"^Enabled Caps[\s:]+(.+)$"


class NokiaOltDriver(NetworkDriver):
    """NAPALM Nokia OLT Handler."""

    def __init__(self, hostname, username, password, timeout=60, optional_args=None):
        if optional_args is None:
            optional_args = {}
        self.transport = optional_args.get("transport", "ssh")
        self.hostname = hostname
        self.username = username
        self.password = password
        self.timeout = timeout

        """Netmiko possible arguments that can be injected from outside
            - For example: optional_args={"read_timeout_override": 300}
        """

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
            "session_log": None,
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
        """Send command to device"""
        if xml_format:
            command += " xml"
        output = self.device.send_command(command, expect_string=r"#$")
        return output

    def open(self):
        """Open an SSH tunnel connection to the device."""
        device_type = "cisco_ios_ssh"
        if self.transport == "telnet":
            device_type = "cisco_ios_telnet"
        self.device = ConnectHandler(
            device_type=device_type,
            host=self.hostname,
            username=self.username,
            password=self.password,
            **self.netmiko_optional_args,
        )
        self._prep_session()

    def close(self):
        """Close the connection to the device."""
        self.device.disconnect()

    def is_alive(self):
        """Returns a flag with the state of the connection."""
        null = chr(0)
        if self.device is None:
            return {"is_alive": False}
        else:
            # SSH
            try:
                # Try sending ASCII null byte to maintain the connection alive
                self.device.write_channel(null)
                return {"is_alive": self.device.remote_conn.transport.is_active()}
            except (socket.error, EOFError):
                # If unable to send, we can tell for sure that the connection
                # is unusable
                return {"is_alive": False}

    def _prep_session(self):
        cmds = [
            "environment mode batch inhibit-alarms",
            "exit all",
        ]
        for command in cmds:
            self._send_command(command)

    def convert_software_version_xml_to_dict(self, xml_data):
        """Convert software management version xml data to dict format"""

        if xml_data:
            for line in xml_data.splitlines():
                if "info" in line:
                    line = line.replace(">", " ").replace("<", " ").replace("name=", "")
                    line = line.split()
                    software = f"{line[-2]}"
                    return {"ISAM": software}

    def convert_xml_to_list(self, xml_data):
        """Convert xml data to list format"""
        if xml_data:
            root = """"""
            for line in xml_data.splitlines():
                if "hierarchy" in line:
                    continue
                root += line
            root = ET.fromstring(root.strip())

            instances = []
            for instance_elem in root.findall("instance"):
                data = {}
                for element in instance_elem:
                    name = element.attrib["name"]
                    value = element.text
                    data[name] = value
                instances.append(data)
            return instances
        else:
            return

    def _convert_xml_elem_to_dict(self, elem=None):
        """convert xml output to dict"""
        data = {}
        for e in elem.iter():
            if "instance" == e.tag:
                continue
            key_name = e.attrib["name"].replace(" ", "_")
            key_value = e.text
            data[key_name] = key_value
        return data

    def _convert_list_to_dict(self, data, key):
        """
        Convert list of data to dict using given key
        """
        data_dict = {}
        for record in data:
            try:
                data_dict[record[key]] = record
            except KeyError:
                pass
        return data_dict

    def cli(self, commands):
        """A generic function that allows the client to send any command to the remote device"""

        output = {}
        try:
            for cmd in commands:
                output[cmd] = self._send_command(cmd)
            return output
        except Exception as e:
            return str(e)

    def send_single_command(self, cmd):
        """A generic function that allows the client to send any command to the remote device"""

        output = self._send_command(cmd)
        return output

    def get_config(self, retrieve="all", full=False, sanitized=False):
        """Returns running config"""

        configs = {"running": "", "startup": "No Startup", "candidate": "No Candidate"}

        if retrieve in ("all", "running"):
            command = "info configure"
            output_ = self._send_command(command)
            if output_:
                configs["running"] = output_
                data = str(configs["running"]).split("\n")
                non_empty_lines = [line for line in data if line.strip() != ""]

                string_without_empty_lines = ""
                for line in non_empty_lines:
                    string_without_empty_lines += line + "\n"
                configs["running"] = string_without_empty_lines
        if retrieve.lower() in ("startup", "all"):
            pass
        return configs

    def make_device_model(self, data):
        """get device model, by parsing the "admin display-config' cmd output"""

        if data:
            lines = data.splitlines()
            for line in lines:
                if "Copyright" in line and "NOKIA" in line:
                    line_list = line.split()
                    nokia_index = line_list.index("NOKIA")
                    return f"{line_list[nokia_index + 1]} {line_list[nokia_index + 2]}"

    def get_facts(self):
        """Returns facts for device"""
        model_command = "admin display-config"
        hostname_command = "show equipment isam detail"
        os_command = "show software-mngt version ansi"
        uptime_command = "show core1-uptime"
        sn_command = "show equipment shelf 1/1 detail"
        port_command = "show equipment ont interface"

        hostname_output = self._send_command(hostname_command, xml_format=True)
        os_output = self._send_command(os_command, xml_format=True)
        uptime_output = self._send_command(uptime_command)
        sn_output = self._send_command(sn_command, xml_format=True)
        port_output = self._send_command(port_command, xml_format=True)
        model_output = self._send_command(model_command, xml_format=False)
        device_model = self.make_device_model(model_output)

        hostname_xml_tree = ET.fromstring(hostname_output)
        os_xml_tree = ET.fromstring(os_output)
        sn_xml_tree = ET.fromstring(sn_output)
        port_xml_tree = ET.fromstring(port_output)

        facts = {}
        facts["model"] = device_model
        port_list = []

        # create default dict and get hostname
        for elem in hostname_xml_tree.findall('.//hierarchy[@name="isam"]'):
            dummy_data = self._convert_xml_elem_to_dict(elem=elem)
            if "description" in dummy_data:
                hostname = dummy_data["description"]
                facts["hostname"] = hostname
                facts["vendor"] = "Nokia"
                facts["uptime"] = ""
                facts["os_version"] = ""
                facts["serial_number"] = ""
                facts["fqdn"] = "Unknown"
                facts["interface_list"] = []

        # get os_version
        for elem in os_xml_tree.findall('.//hierarchy[@name="ansi"]'):
            dummy_data = self._convert_xml_elem_to_dict(elem=elem)
            if "isam-feature-group" in dummy_data:
                os_version = dummy_data["isam-feature-group"]
                facts["os_version"] = os_version

        # get serial_number and model
        for elem in sn_xml_tree.findall('.//hierarchy[@name="shelf"]'):
            dummy_data = self._convert_xml_elem_to_dict(elem=elem)
            if "serial-no" in dummy_data:
                serial_number = dummy_data["serial-no"]
                facts["serial_number"] = serial_number
            if "variant" in dummy_data:
                variant = dummy_data["variant"]
                facts["model"] += f" ({variant})"

        # get uptime
        for line in uptime_output.splitlines():
            split_line = line.split()
            # if line is empty, continue
            if not split_line:
                continue
            if "System" in split_line[0]:
                if "Up" in split_line[1]:
                    for r in range(4):
                        split_line.pop(0)
                    uptime = " ".join(split_line)
                    facts["uptime"] = uptime
        # get interface_list
        for elem in port_xml_tree.findall(".//instance"):
            dummy_data = self._convert_xml_elem_to_dict(elem=elem)
            if "ont-idx" in dummy_data:
                port_list.append(dummy_data["ont-idx"])
        port_list.sort(key=lambda p: list(map(int, p.split("/"))))
        facts["interface_list"] = port_list
        return facts

    def get_vlans(self):
        """Returns vlans info"""
        vlan_name_command = "show vlan name"
        tagging_command = "show vlan residential-bridge extensive"

        vlan_name_output = self._send_command(vlan_name_command, xml_format=True)
        tagging_output = self._send_command(tagging_command, xml_format=True)

        output_xml_tree = ET.fromstring(vlan_name_output)
        tag_xml_tree = ET.fromstring(tagging_output)

        vlans = {}
        # create default dict and get vlan_id and name
        for elem in output_xml_tree.findall(".//instance"):
            dummy_data = self._convert_xml_elem_to_dict(elem=elem)
            primary_key = int(dummy_data["id"])
            if primary_key not in vlans:
                vlans[primary_key] = {}
                vlans[primary_key]["name"] = dummy_data["name"]
                vlans[primary_key]["interfaces"] = []

        # get tagged/untagged ports
        for elem in tag_xml_tree.findall(".//instance"):
            dummy_data = self._convert_xml_elem_to_dict(elem=elem)
            vlan_id = int(dummy_data["vlan-id"])
            port_raw = dummy_data["vlan-port"]
            port = port_raw.split(":")[1]
            if (
                "single-tagged" in dummy_data["transmit-mode"]
                or "untagged" in dummy_data["transmit-mode"]
            ):
                vlans[vlan_id]["interfaces"].append(port)

        return vlans

    def get_equipment_ont_status_xpon(self):
        """
        Get the following data for the ONTs:
            xpon | ont | sernum  | admin-status  | oper-status  | ont-olt-distance  | desc1 | desc2 | hostname

        The ONTs data is structured in xml, the relevant ONTs data is encapsulated in the following
        format:
            <instance>
              <res-id name="x-pon" short-name="x-pon" type="Gpon::OntstatusPonIdGpon::OntstatusPonId">1/1/3/16</res-id>
              <res-id name="ont" short-name="ont" type="Gpon::OntIndex">1/1/3/16/7</res-id>
              <info name="sernum" short-name="sernum" type="Gpon::SerNum2">ALCL:CFFF66B6</info>
              <info name="admin-status" short-name="admin-status" type="Itf::ifAdminStatus">up</info>
              <info name="oper-status" short-name="oper-status" type="Itf::ifAdminStatus">up</info>
              <info name="olt-rx-sig-level(dbm)" short-name="olt-rx-sig-level(dbm)" type="Gpon::OntOltRxSignalLevel">-9.9</info>
              <info name="ont-olt-distance" short-name="ont-olt-distance" type="Gpon::OntOltDist">1.1</info>
              <info name="desc1" short-name="desc1" type="Gpon::Desc">P-FFF-2C-ONT-39</info>
              <info name="desc2" short-name="desc2" type="Gpon::Desc">ONT:1/1/3/16/7</info>
              <info name="hostname" short-name="hostname" type="Gpon::HostName">undefined</info>
            </instance>
        """
        command = "show equipment ont status x-pon"
        data = self._send_command(command, xml_format=True)
        if data:
            data_list = self.convert_xml_to_list(data)
            return self._convert_list_to_dict(data_list, "ont")
        else:
            return f"No available data from the {self.hostname}"

    def get_equipment_ont_interfaces(self):
        """
        Get the following data for the ONTs:
            ont-idx | eqpt-ver-num  | sw-ver-act  | actual-num-slots | version-number | sernum  | yp-serial-no  |
            cfgfile1-ver-act  | cfgfile2-ver-act  | us-rate

        The ONTs data is structured in xml, the relevant ONTs data is encapsulated in the following
        format:
          <instance>
            <res-id name="ont-idx" short-name="ont-idx" type="Gpon::OntIndexGpon::OntIndex">1/1/3/16/22</res-id>
            <info name="eqpt-ver-num" short-name="eqpt-ver-num" type="Gpon::SwVer">3FFFF864AAAA01</info>
            <info name="sw-ver-act" short-name="sw-ver-act" type="Gpon::SwVer">3FFFF068AOTD61</info>
            <info name="actual-num-slots" short-name="actual-num-slots" type="Gpon::ActualOntSlotId">1</info>
            <info name="version-number" short-name="version-number" type="Gpon::VersionOnt">3FFFF864AAAA01</info>
            <info name="sernum" short-name="sernum" type="Gpon::SerNum2">ALCL:FFFF6BA3</info>
            <info name="yp-serial-no" short-name="yp-serial-no" type="Gpon::YpSerialNumber">unknown</info>
            <info name="cfgfile1-ver-act" short-name="cfgfile1-ver-act" type="Gpon::CfgFile"></info>
            <info name="cfgfile2-ver-act" short-name="cfgfile2-ver-act" type="Gpon::CfgFile"></info>
            <info name="actual-us-rate" short-name="actual-us-rate" type="Gpon::ActualUsRate">1.25g</info>
          </instance>
        """
        command = "show equipment ont interface"
        data = self._send_command(command, xml_format=True)
        if data:
            data_list = self.convert_xml_to_list(data)
            return self._convert_list_to_dict(data_list, "ont-idx")
        else:
            return f"No available data from the {self.hostname}"

    def get_equipment_ont_status_pon(self):
        """
        Get the following data for the ONTs:
            pon  | ont  | sernum  | admin_status  | oper-status  | ont-olt-distance  | desc1  | desc2 | hostname

        The ONTs data is structured in xml, the relevant ONTs data is encapsulated in the following
        format:
          <instance>
            <res-id name="ont-idx" short-name="ont-idx" type="Gpon::OntIndexGpon::OntIndex">1/1/3/16/22</res-id>
            <info name="eqpt-ver-num" short-name="eqpt-ver-num" type="Gpon::SwVer">3FFFF864AAAA01</info>
            <info name="sw-ver-act" short-name="sw-ver-act" type="Gpon::SwVer">3FFFF068AOTD61</info>
            <info name="actual-num-slots" short-name="actual-num-slots" type="Gpon::ActualOntSlotId">1</info>
            <info name="version-number" short-name="version-number" type="Gpon::VersionOnt">3FFFF864AAAA01</info>
            <info name="sernum" short-name="sernum" type="Gpon::SerNum2">ALCL:FFFF6BA3</info>
            <info name="yp-serial-no" short-name="yp-serial-no" type="Gpon::YpSerialNumber">unknown</info>
            <info name="cfgfile1-ver-act" short-name="cfgfile1-ver-act" type="Gpon::CfgFile"></info>
            <info name="cfgfile2-ver-act" short-name="cfgfile2-ver-act" type="Gpon::CfgFile"></info>
            <info name="actual-us-rate" short-name="actual-us-rate" type="Gpon::ActualUsRate">1.25g</info>
          </instance>
        """
        command = "show equipment ont status pon"
        data = self._send_command(command, xml_format=True)
        if data:
            data_list = self.convert_xml_to_list(data)
            return self._convert_list_to_dict(data_list, "ont")
        else:
            return f"No available data from the {self.hostname}"

    def get_vlan_residential_bridge(self):
        """
        Get the following data for the ONTs:
            vlan-id | vlan-port | association-type | qos-profile | qos  | prio-regen_name | transmit-mode

        The ONTs data is structured in xml, the relevant ONTs data is encapsulated in the following
        format:
          <instance>
            <res-id name="vlan-id" short-name="vlan-id" type="Vlan::StackedVlanVlan::StackedVlan">2940</res-id>
            <res-id name="vlan-port" short-name="vlan-port" type="Itf::VlanPortInterface">vlan-port:1/1/1/16/29/1/2:2940</res-id>
            <info name="association type" short-name="association type" type="Vlan::AssociationType">static</info>
            <info name="qos-profile" short-name="qos-profile" type="Vlan::QosProfileName">name:100M</info>
            <info name="qos" short-name="qos" type="Vlan::QosPolicy">profile:11</info>
            <info name="prio-regen-name" short-name="prio-regen-name" type="Vlan::PrioRegenProfileName">name:DATA</info>
            <info name="transmit-mode" short-name="transmit-mode" type="Vlan::PortUntagStatus">untagged</info>
          </instance>
        """
        command = "show vlan residential-bridge extensive"
        data = self._send_command(command, xml_format=True)
        if data:
            data_list = self.convert_xml_to_list(data)
            return self._convert_list_to_dict(data_list, "vlan-port")
        else:
            return f"No available data from the {self.hostname}"

    def get_unprovision_devices(self):
        """
        Get the following data for the ONTs:
        alarm-idx | gpon-index | sernum | subscriber-locid | logical-authid | actual-us-rate

        The ONTs data is structured in xml, the relevant ONTs data is encapsulated in the following
        format:
        <instance>
          <res-id name="alarm-idx" short-name="alarm-idx" type="Alarm::genAlarmIndex">69</res-id>
          <info name="gpon-index" short-name="gpon-index" type="Gpon::PonId">x-pon:1/1/1/12</info>
          <info name="sernum" short-name="sernum" type="Gpon::SerNum1">ALCLBFFF8523</info>
          <info name="subscriber-locid" short-name="subscriber-locid" type="Gpon::SubsLocId">&quot;&quot;</info>
          <info name="logical-authid" short-name="logical-authid" type="Gpon::LogAuthId"></info>
          <info name="actual-us-rate" short-name="actual-us-rate" type="Gpon::ActualUsRate">10g</info>
        </instance>
        """
        command = "show pon unprovision-onu"
        data = self._send_command(command, xml_format=True)
        if data:
            data_list = self.convert_xml_to_list(data)
            return self._convert_list_to_dict(data_list, "gpon-index")
        else:
            return f"No available data from the {self.hostname}"

    def get_equipment_slot(self):
        """Returns equipments slot info"""
        command = "show equipment slot"
        data = self._send_command(command, xml_format=True)
        if data:
            data_list = self.convert_xml_to_list(data)
            return self._convert_list_to_dict(data_list, "slot")
        else:
            return f"No available ** {command} ** data from the {self.hostname}"

    def get_equipment_slot_detail(self):
        """Returns slot details info"""
        command = "show equipment slot detail"
        data = self._send_command(command, xml_format=True)
        if data:
            data_list = self.convert_xml_to_list(data)
            return self._convert_list_to_dict(data_list, "slot")
        else:
            return f"No available ** {command} ** data from the {self.hostname}"

    def get_equipment_ont_slot(self):
        """Returns ont slot info"""
        command = "show equipment ont slot"
        data = self._send_command(command, xml_format=True)
        if data:
            data_list = self.convert_xml_to_list(data)
            return self._convert_list_to_dict(data_list, "ont-slot-idx")
        else:
            return f"No available ** {command} ** data from the {self.hostname}"

    def get_equipment_ont_optics(self):
        """Returns ont optics info"""
        command = "show equipment ont optics"
        data = self._send_command(command, xml_format=True)
        if data:
            data_list = self.convert_xml_to_list(data)
            return self._convert_list_to_dict(data_list, "ont-idx")
        else:
            return f"No available ** {command} ** data from the {self.hostname}"

    def get_pon_optics(self):
        """Returns pon optic info"""
        command = "show pon optics"
        data = self._send_command(command, xml_format=True)
        if data:
            data_list = self.convert_xml_to_list(data)
            return self._convert_list_to_dict(data_list, "pon-idx")
        else:
            return f"No available ** {command} ** data from the {self.hostname}"

    def get_equipment_ont_sw_downloads(self):
        """Returns software download info"""
        command = "show equipment ont sw-download"
        data = self._send_command(command, xml_format=True)
        if data:
            if data:
                data_list = self.convert_xml_to_list(data)
                return self._convert_list_to_dict(data_list, "ont-idx")
        else:
            return f"No available ** {command} ** data from the {self.hostname}"

    def get_vlan_fdb_board(self):
        """Returns VLAN info"""
        command = "show vlan fdb-board"
        data = self._send_command(command, xml_format=True)
        if data:
            data_list = self.convert_xml_to_list(data)
            return self._convert_list_to_dict(data_list, "mac")
        else:
            return f"No available ** {command} ** data from the {self.hostname}"

    def get_ethernet_ont_operational_data(self):
        """Returns ethernet - ont operational info"""
        command = "show ethernet ont operational-data"
        data = self._send_command(command, xml_format=True)
        if data:
            data_list = self.convert_xml_to_list(data)
            return self._convert_list_to_dict(data_list, "uni-idx")
        else:
            return f"No available ** {command} ** data from the {self.hostname}"

    def get_equipment_ont_sw_version(self):
        """Returns ont software versions"""
        command = "show equipment ont sw-version"
        data = self._send_command(command, xml_format=True)
        if data:
            data_list = self.convert_xml_to_list(data)
            return self._convert_list_to_dict(data_list, "sw-ver-id")
        else:
            return f"No available ** {command} ** data from the {self.hostname}"

    def get_software_mgmt_version_etsi(self):
        """Returns software version for management"""
        command = "show software-mngt version etsi"
        data = self._send_command(command, xml_format=True)
        if data:
            return self.convert_software_version_xml_to_dict(data)
        else:
            return f"No available ** {command} ** data from the {self.hostname}"

    def get_equipment_transceiver_inventor(self):
        """Returns transceiver inventory info"""
        command = "show equipment transceiver-inventor"
        data = self._send_command(command, xml_format=True)
        if data:
            data_list = self.convert_xml_to_list(data)
            return self._convert_list_to_dict(data_list, "index")
        else:
            return f"No available ** {command} ** data from the {self.hostname}"

    def get_equipment_diagnostics_sfp(self):
        """Returns Equipment diagnostic info"""
        command = "show equipment diagnostics sfp"
        data = self._send_command(command, xml_format=True)
        if data:
            data_list = self.convert_xml_to_list(data)
            return self._convert_list_to_dict(data_list, "position")
        else:
            return f"No available ** {command} ** data from the {self.hostname}"

    def get_vlan_name(self):
        """Returns VLANs info"""
        command = "show vlan name"
        data = self._send_command(command, xml_format=True)
        if data:
            data_list = self.convert_xml_to_list(data)
            return self._convert_list_to_dict(data_list, "id")
        else:
            return f"No available ** {command} ** data from the {self.hostname}"

    def get_vlan_bridge_port_fdb(self):
        """Returns VLANs info details"""
        command = "show vlan bridge-port-fdb"
        data = self._send_command(command, xml_format=True)
        if data:
            tmp_data = self.convert_xml_to_list(data)
            loaded_data = tmp_data
            new_dict = {}

            for entry in loaded_data:
                port_ = entry["port"]
                vlan_id_ = entry["vlan-id"]
                mac_ = entry["mac"]

                if port_ in new_dict.keys():
                    tmp_data = new_dict[port_]
                    for i in tmp_data:
                        m = i[1]
                        if m != mac_:
                            new_dict[port_] += [(vlan_id_, mac_)]
                            break
                if port_ not in new_dict.keys():
                    new_dict[port_] = [(vlan_id_, mac_)]
            return new_dict
        else:
            return f"No available ** {command} ** data from the {self.hostname}"

    def get_equipment_temperature(self):
        """Returns Equipment temperature"""
        command = "show equipment temperature"
        data = self._send_command(command, xml_format=True)
        if data:
            data_list = self.convert_xml_to_list(data)
            return self._convert_list_to_dict(data_list, "sensor-id")
        else:
            return f"No available ** {command} ** data from the {self.hostname}"

    def get_ntp_servers(self):
        """Returns IPV6 NTP servers."""
        command = "show sntp server-tablev6 "
        data = self._send_command(command, xml_format=True)
        data = self.convert_xml_to_list(data)

        ntp_servers = defaultdict(list)
        for sub in data:
            for key in sub:
                if key == "server-ip-addrv6":
                    ntp_servers[key].append(sub[key])
        return dict(ntp_servers)

    def get_interfaces(self):
        """
        Returns a dictionary of dictionaries for all ONT interfaces

        Example Output:
        {
            '1/1/1/1/1': {'is_enabled': True,
            'is_up': True,
            'description': 'test description',
            'mac_address': '0000.0000.0000',
            'last_flapped': -1.0,
            'mtu': 0,
            'speed': 1000}
        }

        mac_address is not implemented
        last_flapped is not implemented
        mtu is not implemented

        """
        pon_command = "show equipment ont status pon"
        xpon_command = "show equipment ont status x-pon"
        pon_output = self._send_command(pon_command, xml_format=True)
        xpon_output = self._send_command(xpon_command, xml_format=True)
        pon_xml_tree = ET.fromstring(pon_output)
        xpon_xml_tree = ET.fromstring(xpon_output)

        interface_dict = {}

        # parse 1GE ports
        for elem in pon_xml_tree.findall(".//instance"):
            dummy_data = self._convert_xml_elem_to_dict(elem=elem)
            if "ont" in dummy_data:
                is_enabled = bool("up" in dummy_data.get("admin-status", ""))
                is_up = bool("up" in dummy_data.get("oper-status", ""))
                interface_dict[dummy_data["ont"]] = {
                    "is_enabled": is_enabled,
                    "is_up": is_up,
                    "description": dummy_data.get("desc1", ""),
                    "mac_address": "0000.0000.0000",
                    "last_flapped": -1.0,
                    "mtu": 0,
                    "speed": 1000,
                }

        # parse 10GE ports (X-PON)
        for elem in xpon_xml_tree.findall(".//instance"):
            dummy_data = self._convert_xml_elem_to_dict(elem=elem)
            if "ont" in dummy_data:
                is_enabled = bool("up" in dummy_data.get("admin-status", ""))
                is_up = bool("up" in dummy_data.get("oper-status", ""))
                interface_dict[dummy_data["ont"]] = {
                    "is_enabled": is_enabled,
                    "is_up": is_up,
                    "description": dummy_data.get("desc1", ""),
                    "mac_address": "0000.0000.0000",
                    "last_flapped": -1.0,
                    "mtu": 0,
                    "speed": 10000,
                }

        return interface_dict

    def get_lldp_neighbors(self):
        """Returns a dictionary with LLDP neighbors"""
        port_command = "show port"
        port_data = self._send_command(port_command, xml_format=False)
        ports = []
        lldp = {}
        all_ports = re.findall(PORT_REGEX, port_data, re.MULTILINE)
        for line in all_ports:
            line = line.split()
            if len(line) > 0:
                if not line[-1] == "vport":
                    ports.append(line[0])
        for port in ports:
            lldp_command = f"show port {port} ethernet lldp remote-info"
            lldp_data = self._send_command(lldp_command, xml_format=False)
            remote_host = re.search(REMOTE_HOST_REGEX, lldp_data, re.MULTILINE)
            if remote_host:
                lldp[port] = [{"hostname": remote_host.group(1), "port": ""}]
                try:
                    remote_port_data = re.search(
                        REMOTE_PORT_REGEX, lldp_data, re.MULTILINE
                    )
                    remote_port = remote_port_data.group(1).split()[1]
                    lldp[port][0]["port"] = remote_port.replace('"', "")
                except IndexError:
                    continue
        return lldp

    def get_lldp_neighbors_detail(self):
        """Returns a detailed view of the LLDP neighbors as a dictionary"""
        port_command = "show port"
        port_data = self._send_command(port_command, xml_format=False)
        ports = []
        lldp = {}
        all_ports = re.findall(PORT_REGEX, port_data, re.MULTILINE)
        for line in all_ports:
            line = line.split()
            if len(line) > 0:
                if not line[-1] == "vport":
                    ports.append(line[0])
        for port in ports:
            lldp_command = f"show port {port} ethernet lldp remote-info"
            lldp_data = self._send_command(lldp_command, xml_format=False)
            remote_host = re.findall(REMOTE_HOST_REGEX, lldp_data, re.MULTILINE)
            if len(remote_host) > 0:
                lldp[port] = [
                    {
                        "parent_interface": port,
                        "remote_chassis_id": "",
                        "remote_system_name": remote_host[0],
                        "remote_port": "",
                        "remote_port_description": "",
                        "remote_system_description": "",
                        "remote_system_capab": "",
                        "remote_system_enable_capab": "",
                    }
                ]
                remote_chassis_id_data = re.search(
                    REMOTE_CHASSIS_REGEX, lldp_data, re.MULTILINE
                )
                remote_port_descr_data = re.search(
                    REMOTE_PORT_DESCR_REGEX, lldp_data, re.MULTILINE
                )
                remote_sys_descr_data = re.search(
                    REMOTE_SYS_DESCR_REGEX, lldp_data, flags=re.S | re.M
                )
                remote_sys_cap_data = re.search(
                    REMOTE_SYS_CAP_REGEX, lldp_data, re.MULTILINE
                )
                remote_sys_en_cap_data = re.search(
                    REMOTE_SYS_EN_CAP_REGEX, lldp_data, re.MULTILINE
                )
                lldp[port][0]["remote_chassis_id"] = remote_chassis_id_data.group(1)
                lldp[port][0]["remote_port_description"] = remote_port_descr_data.group(
                    1
                )
                lldp[port][0][
                    "remote_system_description"
                ] = remote_sys_descr_data.group(1)
                lldp[port][0]["remote_system_description"] = " ".join(
                    lldp[port][0]["remote_system_description"].split()
                )
                lldp[port][0]["remote_system_capab"] = remote_sys_cap_data.group(1)
                lldp[port][0][
                    "remote_system_enable_capab"
                ] = remote_sys_en_cap_data.group(1)
                try:
                    remote_port_data = re.search(
                        REMOTE_PORT_REGEX, lldp_data, re.MULTILINE
                    )
                    remote_port = remote_port_data.group(1).split()[1]
                    lldp[port][0]["remote_port"] = remote_port.replace('"', "")
                except IndexError:
                    continue
        return lldp
