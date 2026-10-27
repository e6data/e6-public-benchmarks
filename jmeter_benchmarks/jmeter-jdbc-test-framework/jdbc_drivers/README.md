# JDBC Drivers

The repository includes the approved e6data JDBC driver used by the checked-in
test setup. Additional JDBC JARs placed here are ignored by Git.
`./setup_jmeter.sh` downloads the supported JDBC dependencies from their
public artifact repositories and installs only the highest-versioned e6data
driver into JMeter's `lib/ext/` directory.

## Bundled artifact

| File | SHA-256 |
|---|---|
| `e6-jdbc-driver-2.1.51-with-dependencies.jar` | `dd3856807af96a6907d67b795742e013a5dd171428d76026e4f2fb07ac5906f3` |

The checksum verifies repository/download integrity; it does not establish provenance. Maintainers should verify the binary against the approved internal or vendor release source before publishing a release. When upgrading it, update this checksum and record the source release in the pull request.

The setup script copies JARs from this directory into `apache-jmeter-5.6.3/lib/ext/`. Obtain drivers from the database vendor and verify that their licenses permit your intended use and redistribution.

## Driver classes

For additional engine presets, connection templates and authentication prerequisites,
see [JDBC engine setup](../docs/jdbc-engines.md). These presets require live
validation against your service before using them for published comparisons.

| Engine | Driver class |
|---|---|
| e6data | `io.e6.jdbc.driver.E6Driver` |

For another named engine, use the optional installer below and its pinned driver
class. For custom engines, verify packaging, class name, Java requirements and
licensing against the provider's documentation before installing a JAR.

The bundled e6data 2.1.51 dependency-inclusive artifact comes from
[Maven Central](https://repo.maven.apache.org/maven2/com/e6data/e6-jdbc-driver/2.1.51/).
Its SHA-1 matches the published checksum; the SHA-256 above pins the bundled bytes.
The release POM declares Apache License 2.0. After pulling an upgrade, rerun
`./setup_jmeter.sh` while benchmarks are stopped to replace older e6 drivers in
JMeter's classpath. Pulling the repository alone does not update installed copies.

## Add or update a driver

For an additional named preset (not the bundled e6data driver), use
`python3 utilities/install_jdbc_drivers.py ENGINE`
from the framework directory. This installs its pinned driver and dependencies
into an engine-specific managed bundle and verifies Java class loading. See
[engine setup](../docs/jdbc-engines.md#optional-driver-installer).

For custom drivers not covered by the installer:

1. Download the JAR from the vendor.
2. Place it in this directory.
3. Run `./setup_jmeter.sh`.
4. Run `./utilities/test_jdbc_connection.sh connection_properties/my_connection.properties`
   using your actual profile, then a small sequential workload before a load test.

Do not commit credentials or additional driver binaries without an explicit licensing and provenance review. If multiple versions of the same driver are installed, use `utilities/fix_jmeter_jar_conflicts.sh --dry-run` to identify classpath conflicts before making changes.
