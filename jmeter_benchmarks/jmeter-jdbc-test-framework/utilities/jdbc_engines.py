"""JDBC presets and connection identity shared by CLI suites and Studio.

Presets describe integration, not certification against a live service.
"""

JDBC_DRIVERS = {
    "e6data": "io.e6.jdbc.driver.E6Driver",
    "databricks": "com.databricks.client.jdbc.Driver",
    "snowflake": "net.snowflake.client.api.driver.SnowflakeDriver",
    "trino": "io.trino.jdbc.TrinoDriver",
    "fabric": "com.microsoft.sqlserver.jdbc.SQLServerDriver",
    "starburst_galaxy": "io.trino.jdbc.TrinoDriver",
    "athena": "com.amazon.athena.jdbc.AthenaDriver",
    "emr_trino": "io.trino.jdbc.TrinoDriver",
    "redshift": "com.amazon.redshift.jdbc.Driver",
    "clickhouse": "com.clickhouse.jdbc.ClickHouseDriver",
}
ENGINE_LABELS = {
    "e6data": "e6data", "databricks": "Databricks", "snowflake": "Snowflake",
    "trino": "Trino", "fabric": "Microsoft Fabric",
    "starburst_galaxy": "Starburst Galaxy", "athena": "Amazon Athena",
    "emr_trino": "Amazon EMR Trino", "redshift": "Amazon Redshift",
    "clickhouse": "ClickHouse",
}


def connection_engine(values, fallback=""):
    """Honor a compatible explicit identity; infer old profiles by driver."""
    driver = values.get("DRIVER_CLASS", "").strip()
    explicit = values.get("ENGINE", "").strip().lower()
    if explicit in JDBC_DRIVERS:
        if JDBC_DRIVERS[explicit] != driver:
            raise ValueError("Connection ENGINE and DRIVER_CLASS do not match")
        return explicit
    # First match deliberately returns generic Trino for legacy profiles.
    return next((engine for engine, cls in JDBC_DRIVERS.items() if cls == driver), fallback)
