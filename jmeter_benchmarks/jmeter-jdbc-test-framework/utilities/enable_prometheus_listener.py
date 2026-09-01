#!/usr/bin/env python3
"""Add the upstream Prometheus Listener to a run-specific JMeter plan."""

from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from pathlib import Path


def prop(parent: ET.Element, name: str, value: str) -> None:
    ET.SubElement(parent, "stringProp", {"name": name}).text = value


def metric(definitions: ET.Element, name: str, help_text: str, kind: str,
           measuring: str, labels: tuple[str, ...] = (), quantiles: str = "") -> None:
    item = ET.SubElement(definitions, "elementProp", {
        "name": "", "elementType": "com.github.johrstrom.listener.ListenerCollectorConfig",
    })
    prop(item, "collector.help", help_text)
    prop(item, "collector.metric_name", name)
    prop(item, "collector.type", kind)
    label_collection = ET.SubElement(item, "collectionProp", {"name": "collector.labels"})
    for index, label in enumerate(labels):
        prop(label_collection, str(1000 + index), label)
    prop(item, "collector.quantiles_or_buckets", quantiles)
    prop(item, "listener.collector.measuring", measuring)


def enable(source: Path, destination: Path) -> None:
    tree = ET.parse(source)
    root = tree.getroot()
    if root.find(".//com.github.johrstrom.listener.PrometheusListener") is not None:
        tree.write(destination, encoding="UTF-8", xml_declaration=True)
        return

    outer_tree = root.find("hashTree")
    plan_tree = outer_tree.find("hashTree") if outer_tree is not None else None
    if plan_tree is None:
        raise ValueError("JMX has no Test Plan hashTree")
    listener = ET.SubElement(plan_tree, "com.github.johrstrom.listener.PrometheusListener", {
        "guiclass": "com.github.johrstrom.listener.gui.PrometheusListenerGui",
        "testclass": "com.github.johrstrom.listener.PrometheusListener",
        "testname": "Prometheus metrics (generated)", "enabled": "true",
    })
    definitions = ET.SubElement(listener, "collectionProp", {"name": "prometheus.collector_definitions"})
    # These collector names intentionally match the upstream plugin's bundled
    # Grafana dashboard. The listener itself supplies jmeter_threads and JVM
    # process metrics. Do not set listener.collector.listen_to for sample
    # collectors: the upstream JMX leaves that property absent unless a
    # collector explicitly listens to assertions.
    metric(definitions, "ResponseTime", "JMeter response time in milliseconds",
           "SUMMARY", "ResponseTime", ("label", "code"), "0.5,0.05|0.9,0.01|0.95,0.01|0.99,0.001")
    metric(definitions, "Ratio", "JMeter sample success ratio",
           "SUCCESS_RATIO", "SuccessRatio", ("label", "code"))
    ET.SubElement(plan_tree, "hashTree")
    # ElementTree.indent was added in Python 3.9. Formatting is cosmetic, so
    # retain compatibility with older runner hosts (for example Amazon Linux 2
    # with Python 3.7) instead of preventing the measured benchmark from
    # starting when Prometheus is enabled.
    if hasattr(ET, "indent"):
        ET.indent(tree, space="  ")
    tree.write(destination, encoding="UTF-8", xml_declaration=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    enable(args.source, args.destination)


if __name__ == "__main__":
    main()
