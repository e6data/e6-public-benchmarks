import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

from utilities import install_jdbc_drivers as installer


class InstallerTests(unittest.TestCase):
    def run_cli(self, *args):
        output = io.StringIO()
        with mock.patch("sys.argv", ["install_jdbc_drivers.py", *args]), \
                contextlib.redirect_stdout(output):
            installer.main()
        return output.getvalue()

    def test_list_without_engines_does_not_install(self):
        with mock.patch.object(installer, "install") as install:
            output = self.run_cli("--list")
        self.assertEqual(output.splitlines(), sorted(set(installer.SPECS) | set(installer.ALIASES)))
        install.assert_not_called()

    def test_classpath_without_engines_does_not_install(self):
        for driver, engine in [(installer.DRIVERS["trino"], "trino"),
                               ("io.e6.jdbc.driver.E6Driver", ""), ("", "")]:
            with self.subTest(driver=driver), \
                    mock.patch.object(installer, "installed_path", return_value="") as lookup, \
                    mock.patch.object(installer, "install") as install:
                self.assertEqual(self.run_cli("--classpath", driver), "\n")
                lookup.assert_called_once_with(engine)
                install.assert_not_called()

    def test_cli_rejects_invalid_or_missing_engines_before_installing(self):
        for args in [(), ("unknown",), ("trino", "unknown"), ("--list", "unknown")]:
            with self.subTest(args=args), \
                    mock.patch.object(installer, "install") as install, \
                    contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    self.run_cli(*args)
                self.assertEqual(error.exception.code, 2)
                install.assert_not_called()

    def test_cli_resolves_and_deduplicates_aliases(self):
        with mock.patch.object(installer, "install") as install:
            self.run_cli("starburst_galaxy", "trino", "emr_trino", "athena")
        self.assertEqual(install.call_args_list, [mock.call("trino"), mock.call("athena")])

    def test_install_is_atomic_repeatable_and_repairs_corruption(self):
        def fake_download(url, destination):
            with zipfile.ZipFile(destination, "w") as jar:
                jar.writestr("test.class", b"test")

        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp)
            with mock.patch.object(installer, "download", side_effect=fake_download) as download, \
                    mock.patch.object(installer, "smoke_check"):
                installer.install("athena", store)
                original = installer.installed_path("athena", store)
                installer.install("athena", store)
                self.assertEqual(download.call_count, 1)
                jar = next(Path(original).glob("*.jar"))
                jar.write_bytes(b"corrupt")
                with self.assertRaisesRegex(ValueError, "integrity"):
                    installer.installed_path("athena", store)
                installer.install("athena", store)
                self.assertNotEqual(original, installer.installed_path("athena", store))
                self.assertEqual(download.call_count, 2)

    def test_failed_download_does_not_activate_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp)
            with mock.patch.object(installer, "download", side_effect=OSError("offline")):
                with self.assertRaises(OSError):
                    installer.install("athena", store)
            self.assertFalse((store / "athena.json").exists())
            self.assertEqual(list(store.iterdir()), [])

    def test_rejects_pointer_outside_managed_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp)
            (store / "athena.json").write_text(json.dumps({"directory": "../escape", "sha256": {}}))
            with self.assertRaisesRegex(ValueError, "Invalid managed"):
                installer.installed_path("athena", store)

    def test_optional_auth_dependencies_are_explicit(self):
        self.assertIn("azure-identity", installer.pom("fabric"))
        for module in ("auth", "sts", "redshiftserverless", "sso", "ssooidc"):
            self.assertIn(f"<artifactId>{module}</artifactId>", installer.pom("redshift"))

    def test_unknown_driver_and_uninstalled_aliases_have_no_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(installer.installed_path("unknown", Path(tmp)), "")
            self.assertEqual(installer.installed_path("emr_trino", Path(tmp)), "")


if __name__ == "__main__":
    unittest.main()
