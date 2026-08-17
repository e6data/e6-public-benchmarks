# JDBC Drivers

The repository currently includes the e6data JDBC driver used by the checked-in test setup. Additional JDBC JARs placed here are ignored by Git. `./setup_jmeter.sh` copies third-party drivers and only the highest-versioned e6data driver into JMeter's `lib/ext/` directory.

## Bundled artifact

| File | SHA-256 |
|---|---|
| `e6-jdbc-driver-2.0.27-with-dependencies.jar` | `9dc81088a0604616ec32676ee5146ee717dc511d48cd0583da68e41097a6a10b` |

The checksum verifies repository/download integrity; it does not establish provenance. Maintainers should verify the binary against the approved internal or vendor release source before publishing a release. When upgrading it, update this checksum and record the source release in the pull request.

The setup script copies JARs from this directory into `apache-jmeter-5.6.3/lib/ext/`. Obtain drivers from the database vendor and verify that their licenses permit your intended use and redistribution.

## Common driver classes

| Engine | Driver class |
|---|---|
| e6data | `io.e6.jdbc.driver.E6Driver` |
| Trino | `io.trino.jdbc.TrinoDriver` |
| Presto | `com.facebook.presto.jdbc.PrestoDriver` |
| Amazon Athena (Simba) | `com.simba.athena.jdbc.Driver` |

For Databricks, download the current JDBC driver from Databricks and use the driver class documented for that release. Driver packaging and class names can change, so the vendor documentation is the source of truth.

## Add or update a driver

1. Download the JAR from the vendor.
2. Place it in this directory.
3. Run `./setup_jmeter.sh`.
4. Run `utilities/test_jdbc_connection.sh` before starting a load test.

Do not commit credentials or additional driver binaries without an explicit licensing and provenance review. If multiple versions of the same driver are installed, use `utilities/fix_jmeter_jar_conflicts.sh --dry-run` to identify classpath conflicts before making changes.
