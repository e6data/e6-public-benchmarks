import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ui import server
from utilities import jdbc_engines, run_benchmark_suite


class JdbcEngineTests(unittest.TestCase):
    def test_new_engines_build_all_jdbc_plan_environments(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(server, "ROOT", Path(tmp)):
            root = Path(tmp)
            for directory in ("connection_properties", "data_files", "test_properties"):
                (root / directory).mkdir()
            (root / "data_files/query.csv").write_text('query_alias,query_string\nq1,"select 1"\n')
            (root / "test_properties/load.csv").write_text("StartValue,EndValue,Duration\n1,1,1\n")
            for path in set(server.PLAN_TEST_PROPERTIES.values()):
                (root / path).write_text("")
            for engine in ("fabric", "starburst_galaxy", "athena", "emr_trino", "redshift", "clickhouse"):
                connection = server.create_connection_profile({
                    "name": engine, "engine": engine, "transport": "jdbc",
                    "connection_string": "jdbc:example://host/database",
                })
                for plan, (_, _, transport) in server.PLANS.items():
                    if transport != "jdbc":
                        continue
                    with self.subTest(engine=engine, plan=plan):
                        env = server.build_environment({
                            "plan": plan, "connection": connection, "engine": "e6data",
                            "query_file": "data_files/query.csv",
                            "load_profile": "test_properties/load.csv",
                        }, "engine-test")
                        self.assertEqual(env["ENGINE"], engine)

    def test_new_profiles_round_trip_through_suite_identity(self):
        for engine in ("fabric", "starburst_galaxy", "athena", "emr_trino", "redshift", "clickhouse"):
            with self.subTest(engine=engine), tempfile.TemporaryDirectory() as tmp:
                with mock.patch.object(server, "ROOT", Path(tmp)):
                    relative = server.create_connection_profile({
                        "name": engine, "engine": engine, "transport": "jdbc",
                        "connection_string": "jdbc:example://host/database",
                    })
                path = Path(tmp) / relative
                self.assertEqual(run_benchmark_suite.connection_engine(path), engine)
                self.assertIn("DRIVER_CLASS=" + jdbc_engines.JDBC_DRIVERS[engine], path.read_text())

    def test_legacy_trino_does_not_become_galaxy_or_emr(self):
        self.assertEqual(jdbc_engines.connection_engine({
            "DRIVER_CLASS": "io.trino.jdbc.TrinoDriver",
        }), "trino")

    def test_incompatible_identity_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "do not match"):
            jdbc_engines.connection_engine({
                "ENGINE": "emr_trino", "DRIVER_CLASS": jdbc_engines.JDBC_DRIVERS["snowflake"],
            })

    def test_driver_corrects_stale_dropdown(self):
        self.assertEqual(jdbc_engines.connection_engine({
            "DRIVER_CLASS": jdbc_engines.JDBC_DRIVERS["fabric"],
        }, "e6data"), "fabric")

    def test_athena_preflight_does_not_resolve_url_parameters_as_host(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "athena.properties"
            path.write_text("DRIVER_CLASS=com.amazon.athena.jdbc.AthenaDriver\n"
                            "CONNECTION_STRING=jdbc:athena://Region=us-east-1;Database=default\n")
            with mock.patch.object(run_benchmark_suite.socket, "getaddrinfo") as resolve:
                run_benchmark_suite.network_preflight(path)
            resolve.assert_not_called()

    def test_templates_have_valid_engine_identity(self):
        root = Path(__file__).resolve().parents[2]
        for path in (root / "connection_properties").glob("*.properties.template"):
            values = run_benchmark_suite.properties(path)
            if "ENGINE" in values:
                self.assertEqual(jdbc_engines.connection_engine(values), values["ENGINE"])

    def test_clickhouse_https_preflight_extracts_hostname(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "clickhouse.properties"
            path.write_text("CONNECTION_STRING=jdbc:clickhouse:https://example.com:8443/default\n")
            with mock.patch.object(run_benchmark_suite.socket, "getaddrinfo") as resolve:
                run_benchmark_suite.network_preflight(path)
            resolve.assert_called_once_with("example.com", None)


if __name__ == "__main__":
    unittest.main()
