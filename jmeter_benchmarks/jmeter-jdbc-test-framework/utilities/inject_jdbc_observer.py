#!/usr/bin/env python3
"""Add a zero-query JDBC result observer to a run-local JMX plan."""

import argparse
import copy
import xml.etree.ElementTree as ET


POSTPROCESSOR = r'''<hashTree>
          <JSR223PostProcessor guiclass="TestBeanGUI" testclass="JSR223PostProcessor" testname="Record materialized row count">
            <stringProp name="cacheKey">true</stringProp>
            <stringProp name="filename"></stringProp>
            <stringProp name="parameters"></stringProp>
            <stringProp name="script">def value = vars.getObject('result')
int count = -1
if (value instanceof Collection) {
    count = value.size()
} else {
    def columnCount = vars.get('col1_#')
    if (columnCount != null &amp;&amp; columnCount ==~ /\d+/) count = columnCount as int
}
int limit = (props.get('LIMIT_RESULTSET') ?: '0') as int
vars.put('rows_materialized', count.toString())
vars.put('row_limit_reached', (count &gt;= 0 &amp;&amp; limit &gt; 0 &amp;&amp; count &gt;= limit).toString())</stringProp>
            <stringProp name="scriptLanguage">groovy</stringProp>
          </JSR223PostProcessor>
          <hashTree/>
        </hashTree>'''


def inject(source, target):
    tree = ET.parse(source)
    sampler_trees = []
    for parent in tree.iter():
        children = list(parent)
        for index, child in enumerate(children):
            if child.tag != "JDBCSampler":
                continue
            if index + 1 >= len(children) or children[index + 1].tag != "hashTree":
                raise ValueError(f"{source}: JDBC sampler child tree was not found")
            sampler_trees.append(children[index + 1])
    if not sampler_trees:
        raise ValueError(f"{source}: JDBC sampler was not found")
    observer = ET.fromstring(POSTPROCESSOR)
    for sampler_tree in sampler_trees:
        if any(node.get("testname") == "Record materialized row count"
               for node in sampler_tree.findall("JSR223PostProcessor")):
            continue
        for node in observer:
            sampler_tree.append(copy.deepcopy(node))
    tree.write(target, encoding="UTF-8", xml_declaration=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("target")
    args = parser.parse_args()
    inject(args.source, args.target)


if __name__ == "__main__":
    main()
