#!/usr/bin/env python3
"""Apply driver-specific JDBC properties to a run-local JMeter plan."""

from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from pathlib import Path


def configure(source: Path, destination: Path, connection_properties: str) -> None:
    tree = ET.parse(source)
    data_sources = tree.findall(".//JDBCDataSource")
    if not data_sources:
        raise ValueError("JMX has no JDBC Connection Configuration")
    for data_source in data_sources:
        prop = data_source.find("stringProp[@name='connectionProperties']")
        if prop is None:
            prop = ET.SubElement(data_source, "stringProp", {"name": "connectionProperties"})
        prop.text = connection_properties
    ET.indent(tree, space="  ")
    tree.write(destination, encoding="UTF-8", xml_declaration=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("connection_properties")
    args = parser.parse_args()
    configure(args.source, args.destination, args.connection_properties)


if __name__ == "__main__":
    main()
