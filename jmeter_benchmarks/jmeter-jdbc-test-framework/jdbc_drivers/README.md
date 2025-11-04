# JDBC Drivers

This directory contains custom JDBC drivers that are copied to `apache-jmeter-5.6.3/lib/ext/` during setup.

## Included Drivers

- **E6Data JDBC Driver** (`e6-jdbc-driver-1.2.82-with-dependencies.jar`) - 27MB
  - Driver class: `io.e6.jdbc.driver.E6Driver`

- **Trino JDBC Driver** (`trino-jdbc-474.jar`) - 12MB
  - Driver class: `io.trino.jdbc.TrinoDriver`

- **Presto JDBC Driver** (`presto-jdbc-0.283.jar`) - 9.4MB
  - Driver class: `com.facebook.presto.jdbc.PrestoDriver`

- **AWS Athena JDBC Driver** (`athena-jdbc-3.0.0-with-dependencies.jar`) - 18MB
  - Driver class: `com.simba.athena.jdbc.Driver`

## Adding New Drivers

To add a new JDBC driver:

1. Place the JAR file in this directory
2. Run `./setup_jmeter.sh` to copy it to JMeter's lib/ext/
3. Commit the JAR file to git (if it's a custom or hard-to-obtain driver)

For publicly available drivers (like DBR), consider adding download logic to `setup_jmeter.sh` instead of committing large JARs.

## DBR JDBC Driver

The DBR JDBC driver is NOT included here due to its size and licensing.

To use DBR:
1. Download from: https://www.dbr.com/spark/jdbc-drivers-download
2. Place `DBRJDBC42-*.jar` in `apache-jmeter-5.6.3/lib/ext/`
3. Driver class: `com.dbr.client.jdbc.Driver`

## Total Size

Current total: ~67MB (4 drivers)
