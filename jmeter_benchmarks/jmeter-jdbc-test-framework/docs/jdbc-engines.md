# Additional JDBC engines

The CLI and Studio provide presets for Microsoft Fabric, Starburst Galaxy,
Amazon Athena, Amazon EMR Trino, Amazon Redshift and ClickHouse. These are
integrations awaiting live validation, not certified benchmark results.
They use the existing sequential, fixed/variable concurrency and fixed/variable
arrival plans, warm-up, reports, baselines and S3 artifact upload.

## Configure a runner

1. Install the engines you need with the optional installer below. It downloads
   the drivers and runtime/authentication dependencies; no manual JAR downloads
   are required. Use the Java 17 JDK provided by runner setup.
2. Copy the matching `connection_properties/<engine>.properties.template`
   to a local `.properties` file. Replace all placeholders and restrict its
   permissions with `chmod 600`. Alternatively use `./create_connection.sh`
   or Studio's Create local profile.
3. Configure service access as described below. Run a single `SELECT 1`
   through the sequential plan before using real queries. Then validate
   a small concurrent run before applying a large load.
4. Supply SQL in the target engine's dialect, with matching query aliases for
   comparisons. Use existing CLI instructions in the [README](../README.md)
   to select a plan, connection file, query CSV and optional load profile.

### Optional driver installer

On a new runner:

```bash
./setup_jmeter.sh --jdbc-engines=fabric,athena,redshift,clickhouse
```

On an existing runner, select one or more engines:

```bash
python3 utilities/install_jdbc_drivers.py --list
python3 utilities/install_jdbc_drivers.py fabric
python3 utilities/install_jdbc_drivers.py athena redshift clickhouse starburst_galaxy emr_trino
```

The installer also supports `trino`, `databricks` and `snowflake`. Galaxy and EMR
share one Trino bundle. e6data continues to use the repository-managed driver.
Downloads require HTTPS access, curl, Python 3 and a Java 17 JDK. Maven resolves
transitive dependencies; if it is missing, the installer automatically downloads
a temporary Maven 3.9.11 distribution and verifies its published SHA-512 checksum.

Versions are pinned in `utilities/install_jdbc_drivers.py`. Fabric includes Azure
Identity and certificate-auth libraries; Redshift includes AWS SDK credential,
STS, SSO, provisioned and serverless modules. Athena uses the vendor's complete
bundle. Credentials, IAM/workspace permissions, certificates, Kerberos configuration
and access to endpoints still need to be configured for your environment.

Bundles live in Git-ignored `jdbc_drivers/managed/`. Installation validates JARs
and Java driver/auth class loading before atomically activating a bundle. Reruns
verify checksums and skip intact installations; damaged bundles are rebuilt.
Previous bundle directories are retained. Each benchmark loads only its selected
managed bundle through JMeter's `user.classpath`; existing global JMeter libraries
remain visible, so remove conflicting manually installed drivers before use.
The connection-test helper also discovers managed bundles. Neither runs nor
warm-ups download dependencies. Install on every runner host, including remote
workers, before launching the UI/CLI workload. Native Windows integrated-auth
DLLs and system Kerberos tooling are not installed by this script.

To repeat the offline JMeter class-loading checks after installation (no database
requests are made):

```bash
RUN_MANAGED_JDBC_SMOKE=1 python3 -m unittest utilities.tests.test_managed_jdbc_jmeter
```

Keep `ENGINE` in profiles: Galaxy and EMR use the same driver as Trino.
Old profiles without this field remain generic Trino. Cluster size, generation,
Photon and serverless configuration belong in run metadata; they are not separate
JDBC drivers. Record the actual configuration rather than copying metadata from
another engine.

| Engine preset | Driver and prerequisites |
| --- | --- |
| `fabric` | Microsoft SQL Server JDBC, `com.microsoft.sqlserver.jdbc.SQLServerDriver`. Connect to a Fabric Warehouse or SQL analytics endpoint. The template uses Entra service-principal authentication: USER is the application client ID, PASSWORD is its secret. Install the Microsoft-documented authentication dependencies and grant the identity workspace/data access. |
| `starburst_galaxy` | Trino JDBC, `io.trino.jdbc.TrinoDriver`. Copy the endpoint, catalog/schema and authentication details from Galaxy Partner connect. Allow access to any storage endpoints required by the result protocol. |
| `athena` | Athena JDBC **3.x**, `com.amazon.athena.jdbc.AthenaDriver`. Install the dependency-inclusive distribution. The template leaves USER/PASSWORD empty for AWS credential-provider-chain authentication; configure a runner role/profile with Athena, catalog, S3 and applicable KMS access. Supply the region, workgroup and result location (unless provided by the workgroup). |
| `emr_trino` | Trino JDBC, `io.trino.jdbc.TrinoDriver`. Use your coordinator's actual port, TLS and authentication settings; the template's TLS port is an example. The runner needs network access to the coordinator. |
| `redshift` | Redshift JDBC 2.x, `com.amazon.redshift.jdbc.Driver`, with dependencies required by the chosen authentication method. The template disables session result reuse through JDBC_INIT_SQL. |
| `clickhouse` | ClickHouse JDBC, `com.clickhouse.jdbc.ClickHouseDriver`, with the dependencies for your driver distribution. Use the HTTP(S) endpoint, not the native TCP port. |

ClickHouse native, Delta and Iceberg workloads use the same connection. Provision
the relevant tables/catalogs and storage permissions on the server first and use
separate query files and metadata to identify the table format. The runner does
not create catalogs, load datasets, translate SQL or provision clusters.

## Validation and interpretation

Test each authentication method on the runner host, including unattended token
refresh for long runs. Verify expected rows and SQL semantics on a small workload.
Record result-cache settings explicitly; warm-up and disabling result reuse do
not eliminate data caches. For Athena, check workgroup limits and result-reuse
settings; for ClickHouse, check query-cache settings.

JMeter latency remains a **client-observed JDBC measurement**, including network,
driver and potentially service polling time. It is not pure engine execution
time and JDBC implementations can expose results at different stages. Retain
elapsed time and compare server query history where available. Automatic query
history collection for these new engines is not implemented by this change;
S3 artifact upload remains available independently.

## Provider references

- [Fabric connections](https://learn.microsoft.com/en-us/fabric/data-warehouse/how-to-connect)
- [Microsoft JDBC Entra authentication and dependencies](https://learn.microsoft.com/en-us/sql/connect/jdbc/connecting-using-azure-active-directory-authentication)
- [Starburst JDBC](https://docs.starburst.io/clients/jdbc.html)
- [Athena JDBC 3.x](https://docs.aws.amazon.com/athena/latest/ug/jdbc-v3-driver.html)
- [Redshift JDBC 2.x](https://docs.aws.amazon.com/redshift/latest/mgmt/jdbc20-install.html)
- [ClickHouse JDBC](https://clickhouse.com/docs/integrations/language-clients/java/jdbc)
