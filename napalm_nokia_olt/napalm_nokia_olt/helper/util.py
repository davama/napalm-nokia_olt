import json


def convert_software_version_xml_to_json(xml_data):
    """Convert software management version xml data to json format"""

    if xml_data:
        for line in xml_data.splitlines():
            if "info" in line:
                line = line.replace(">", " ").replace("<", " ").replace("name=", "")
                line = line.split()
                software = f"{line[-2]}"
                return json.dumps({'ISAM': software}, indent=2)


