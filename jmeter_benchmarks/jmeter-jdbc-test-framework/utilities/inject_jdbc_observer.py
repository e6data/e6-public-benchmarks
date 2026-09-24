#!/usr/bin/env python3
"""Add a zero-query JDBC result observer to a run-local JMX plan."""

import argparse
from pathlib import Path


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
    text = Path(source).read_text()
    marker = "</JDBCSampler>\n        <hashTree/>"
    if marker not in text:
        raise ValueError(f"{source}: JDBC sampler child tree was not found")
    text = text.replace(marker, "</JDBCSampler>\n        " + POSTPROCESSOR, 1)
    Path(target).write_text(text)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("target")
    args = parser.parse_args()
    inject(args.source, args.target)


if __name__ == "__main__":
    main()
