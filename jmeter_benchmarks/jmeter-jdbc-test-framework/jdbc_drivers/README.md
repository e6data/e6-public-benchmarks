# JDBC Drivers

The repository includes the approved e6data JDBC driver used by the checked-in
test setup. Additional JDBC JARs placed here are ignored by Git.
`./setup_jmeter.sh` downloads the supported JDBC dependencies from their
public artifact repositories and installs only the highest-versioned e6data
driver into JMeter's `lib/ext/` directory.

## Bundled artifact

| File | SHA-256 |
|---|---|
| `e6-jdbc-driver-2.0.27-with-dependencies.jar` | `9dc81088a0604616ec32676ee5146ee717dc511d48cd0583da68e41097a6a10b` |

The checksum verifies repository/download integrity; it does not establish provenance. Maintainers should verify the binary against the approved internal or vendor release source before publishing a release. When upgrading it, update this checksum and record the source release in the pull request.

The setup script copies JARs from this directory into `apache-jmeter-5.6.3/lib/ext/`. Obtain drivers from the database vendor and verify that their licenses permit your intended use and redistribution.

## Driver classes

| Engine | Driver class |
|---|---|
| e6data | `io.e6.jdbc.driver.E6Driver` |

For another engine, obtain its current JDBC driver from the provider and use
the driver class documented for that release. Driver packaging, class names,
Java requirements, and licensing can change; the provider documentation is
the source of truth.

The e6data 2.0.27 artifact is repository-managed rather than published through
Maven Central, so it is updated only from an approved e6data driver release.

## Add or update a driver

1. Download the JAR from the vendor.
2. Place it in this directory.
3. Run `./setup_jmeter.sh`.
4. Run `utilities/test_jdbc_connection.sh` before starting a load test.

Do not commit credentials or additional driver binaries without an explicit licensing and provenance review. If multiple versions of the same driver are installed, use `utilities/fix_jmeter_jar_conflicts.sh --dry-run` to identify classpath conflicts before making changes.
