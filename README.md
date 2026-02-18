# e6data Benchmarking Utilities
This repo is a collection of tools built by the e6data team for benchmarking & comparing analytical engine performance.

>These tools were built for internal use and may not have gone through stringent compatibility tests or security checks. Recommended only for use in non-production/lab environments.

## Tools

- [JMeter JDBC Test Framework](jmeter_benchmarks/jmeter-jdbc-test-framework/)
  - JMeter-based JDBC performance testing framework for load and concurrency testing
  - Property-file-driven architecture for reusable, automation-friendly test execution
  - Supports multiple database engines (E6Data, Databricks, Trino, etc.)
  - Includes batch testing with concurrency sweeps, S3 result storage, Athena integration, and comparison utilities
- [Benchmarking POV Tool](pov/)
  - Django-based GUI for running benchmarks
- [Python scripts for various engines](python_benchmarks/)
  - Python-based benchmark scripts for various analytical engines
