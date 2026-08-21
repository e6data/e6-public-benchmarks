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
    prop(item, "listener.collector.listen_to", "samples")
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
    # Names intentionally match the existing, upstream-plugin-compatible Grafana dashboard.
    metric(definitions, "jmeter_response_time", "JMeter response time in milliseconds",
           "SUMMARY", "ResponseTime", ("label", "code"), "0.5,0.05|0.9,0.01|0.95,0.01|0.99,0.001")
    metric(definitions, "jmeter_success_success_total", "Successful JMeter samples",
           "COUNTER", "SuccessTotal", ("label",))
    metric(definitions, "jmeter_success_failure_total", "Failed JMeter samples",
           "COUNTER", "FailureTotal", ("label",))
    ET.SubElement(plan_tree, "hashTree")
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
