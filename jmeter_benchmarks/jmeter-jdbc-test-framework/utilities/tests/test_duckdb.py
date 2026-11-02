"""DuckDB preset contracts and opt-in real local JMeter execution."""
import csv
import json
import os
import shutil
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from ui import server
from utilities import install_jdbc_drivers as installer
from utilities import run_benchmark_suite
from utilities.jdbc_engines import JDBC_DRIVERS, connection_engine


class DuckDBTests(unittest.TestCase):
    def test_suite_preflight_checks_file_instead_of_dns(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / 'test.duckdb'
            database.touch()
            profile = Path(tmp) / 'test.properties'
            profile.write_text('DRIVER_CLASS=org.duckdb.DuckDBDriver\nCONNECTION_STRING=jdbc:duckdb:' + str(database))
            with mock.patch.object(run_benchmark_suite.socket, 'getaddrinfo') as dns:
                run_benchmark_suite.network_preflight(profile)
                dns.assert_not_called()
            database.unlink()
            with self.assertRaisesRegex(ValueError, 'database-file'):
                run_benchmark_suite.network_preflight(profile)

    def test_cli_profile_uses_database_path_without_login_prompts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'connection_properties').mkdir()
            shutil.copy(installer.ROOT / 'create_connection.sh', root)
            database = root / 'existing.duckdb'
            database.touch()
            result = subprocess.run(['bash', str(root / 'create_connection.sh')],
                input='1\n12\nlocal\n' + str(database) + '\n',
                text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            profile = (root / 'connection_properties/duckdb_local_connection.properties').read_text()
            self.assertIn('CONNECTION_STRING=jdbc:duckdb:' + str(database), profile)
            self.assertIn('USER=\nPASSWORD=\n', profile)

    def test_installer_and_ui_share_driver(self):
        self.assertEqual(JDBC_DRIVERS['duckdb'], installer.DRIVERS['duckdb'])
        self.assertEqual(server.ENGINE_LABELS['duckdb'], 'DuckDB')
        self.assertEqual(connection_engine({'DRIVER_CLASS': JDBC_DRIVERS['duckdb']}), 'duckdb')
        self.assertEqual(installer.SPECS['duckdb'], [('org.duckdb', 'duckdb_jdbc', '2.0.0.1')])

    def test_ui_profile_without_credentials_and_safe_preview(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(server, 'ROOT', Path(tmp)):
            path = server.create_connection_profile({'name': 'duck', 'transport': 'jdbc',
                'engine': 'duckdb', 'connection_string': 'jdbc:duckdb:/data/test.duckdb'})
            text = (Path(tmp) / path).read_text()
            self.assertIn('DRIVER_CLASS=org.duckdb.DuckDBDriver', text)
            self.assertIn('PASSWORD=\n', text)
            self.assertEqual(server.connection_preview(path)['jdbc_url'], 'jdbc:duckdb:/data/test.duckdb')
        for url in ('jdbc:duckdb:/data/db?token=secret', 'jdbc:duckdb:/data/db;password=secret'):
            self.assertNotIn('secret', server.masked_jdbc_url(url))


@unittest.skipUnless(os.environ.get('RUN_DUCKDB_SMOKE') == '1', 'optional real DuckDB benchmark')
class DuckDBRunTests(unittest.TestCase):
    def test_three_plans(self):
        root = installer.ROOT
        driver = installer.installed_path('duckdb')
        self.assertTrue(driver, 'Install DuckDB JDBC first')
        with tempfile.TemporaryDirectory(prefix='duckdb-benchmark-') as tmp:
            work = Path(tmp)
            db = work / 'benchmark.duckdb'
            source = work / 'Prepare.java'
            source.write_text('''import java.sql.*;
class Prepare { public static void main(String[] args) throws Exception {
Class.forName("org.duckdb.DuckDBDriver");
try (Connection c = DriverManager.getConnection("jdbc:duckdb:" + args[0]);
Statement s = c.createStatement()) {
s.execute("CREATE TABLE items AS SELECT i, i % 10 AS category FROM range(10000) t(i)");
}}}''')
            subprocess.run(['java', '--class-path', driver + '/*', str(source), str(db)], check=True, timeout=60)
            connection = work / 'connection.properties'
            connection.write_text('ENGINE=duckdb\nDRIVER_CLASS=org.duckdb.DuckDBDriver\n'
                'CONNECTION_STRING=jdbc:duckdb:' + str(db) + '\nUSER=\nPASSWORD=\n')
            queries = work / 'queries.csv'
            queries.write_text('query_alias,query_string\ncount,"SELECT count(*) FROM items"\n'
                               'sum,"SELECT sum(i) FROM items"\n')
            profile = work / 'profile.csv'
            profile.write_text('StartValue,EndValue,Duration\n1,1,3\n2,2,3\n')
            for name, plan, expected in [
                ('sequential', 'Test-Plan-Run-Once-static-concurrency.jmx', 4),
                ('qps', 'Test-Plan-Constant-QPS-On-Arrivals-JSR-Optimized.jmx', 12),
                ('profile', 'Test-Plan-Fire-QPS-with-load-profile.jmx', 9),
            ]:
                with self.subTest(plan=name):
                    env = os.environ.copy()
                    env.update(CONNECTION_FILE=str(connection), QUERY_FILE=str(queries),
                        TEST_PLAN='Test-Plans/' + plan, TEST_PROPERTIES_FILE='', METADATA_FILE='',
                        REPORT_PATH=str(work / name), CONCURRENT_QUERY_COUNT='1', QPS='2',
                        HOLD_PERIOD='6', RAMP_UP_TIME='0', RAMP_UP_STEPS='1', MAX_CONCURRANCY='4',
                        LOAD_PROFILE=str(profile), WARMUP_ENABLED='true' if name == 'sequential' else 'false',
                        WARMUP_QUERY_FILE=str(queries), WARMUP_ITERATIONS='1', MEASURED_ITERATIONS='2' if name == 'sequential' else '1',
                        QUERY_TIMEOUT='10', LIMIT_RESULTSET='1000', MAX_ERROR_PCT='0', RANDOM_ORDER='false',
                        RECYCLE_ON_EOF='false' if name == 'sequential' else 'true',
                        GENERATE_DASHBOARD='false', COPY_TO_S3='false', E6_QUERY_HISTORY_ENABLED='false',
                        PROMETHEUS_ENABLED='false')
                    result = subprocess.run(['./run_test.sh'], cwd=root, env=env,
                                            capture_output=True, text=True, timeout=120)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    files = list((work / name).glob('*/JmeterResultFile.csv'))
                    self.assertEqual(len(files), 1)
                    with files[0].open() as handle:
                        rows = [r for r in csv.DictReader(handle) if r['label'] in {'count', 'sum'}]
                    self.assertEqual(len(rows), expected, result.stdout)
                    self.assertTrue(all(r['success'] == 'true' for r in rows), rows)
                    self.assertTrue(all(r['Latency'].isdigit() for r in rows))
                    summary = json.loads((files[0].parent / 'run_summary.json').read_text())
                    self.assertEqual(summary['meta']['engine'], 'duckdb')
                    self.assertTrue((files[0].parent / 'artifact_manifest.json').is_file())
                    print('DuckDB %s: %s/%s successful samples' % (name, len(rows), expected))
