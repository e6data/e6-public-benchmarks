#!/usr/bin/env python3
"""Install opt-in JDBC bundles. No credentials or live service access required."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "jdbc_drivers" / "managed"
CENTRAL = "https://repo.maven.apache.org/maven2"
ALIASES = {"starburst_galaxy": "trino", "emr_trino": "trino"}
# Fabric's optional auth dependencies must be explicit Maven roots.
SPECS = {
    "fabric": [("com.microsoft.sqlserver", "mssql-jdbc", "13.4.0.jre11"),
               ("com.azure", "azure-identity", "1.18.2"),
               ("org.bouncycastle", "bcpkix-jdk18on", "1.79")],
    "redshift": [("com.amazon.redshift", "redshift-jdbc42", "2.2.9")] + [
        ("software.amazon.awssdk", name, "2.40.5")
        for name in ("auth", "redshift", "redshiftserverless", "sts", "sso", "ssooidc")],
    "clickhouse": [("com.clickhouse", "clickhouse-jdbc", "0.9.8", "all")],
    "trino": [("io.trino", "trino-jdbc", "483")],
    "databricks": [("com.databricks", "databricks-jdbc", "3.4.2")],
    "snowflake": [("net.snowflake", "snowflake-jdbc", "4.3.3")],
    "athena": [],
}
ATHENA_URL = "https://aws-analytics-downloads-us-east-1.s3.us-east-1.amazonaws.com/athena/JDBC/3.8.2/athena-jdbc-3.8.2-with-dependencies.jar"
DRIVERS = {
    "fabric": "com.microsoft.sqlserver.jdbc.SQLServerDriver",
    "redshift": "com.amazon.redshift.jdbc.Driver",
    "clickhouse": "com.clickhouse.jdbc.ClickHouseDriver",
    "trino": "io.trino.jdbc.TrinoDriver",
    "databricks": "com.databricks.client.jdbc.Driver",
    "snowflake": "net.snowflake.client.api.driver.SnowflakeDriver",
    "athena": "com.amazon.athena.jdbc.AthenaDriver",
}


def digest(path):
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def download(url, destination):
    subprocess.run(["curl", "--fail", "--location", "--silent", "--show-error",
                    "--retry", "3", "--connect-timeout", "30", "--max-time", "600",
                    "--proto", "=https", "--proto-redir", "=https",
                    "--output", str(destination), url], check=True)


def maven(stage):
    installed = shutil.which("mvn")
    if installed:
        return installed
    # Bootstrap only inside this temporary install; no system package changes.
    name = "apache-maven-3.9.11"
    url = f"{CENTRAL}/org/apache/maven/apache-maven/3.9.11/{name}-bin.zip"
    archive = stage / "maven.zip"
    checksum = stage / "maven.sha512"
    download(url, archive)
    download(url + ".sha512", checksum)
    if hashlib.sha512(archive.read_bytes()).hexdigest() != checksum.read_text().split()[0]:
        raise ValueError("Maven archive checksum mismatch")
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            target = (stage / member.filename).resolve()
            if stage.resolve() not in target.parents:
                raise ValueError("Unsafe Maven archive path")
        bundle.extractall(stage)
    executable = stage / name / "bin" / "mvn"
    executable.chmod(0o755)
    return str(executable)


def pom(engine):
    project = ET.Element("project", xmlns="http://maven.apache.org/POM/4.0.0")
    for key, value in (("modelVersion", "4.0.0"), ("groupId", "local.benchmark"),
                       ("artifactId", "jdbc-bundle"), ("version", "1")):
        ET.SubElement(project, key).text = value
    dependencies = ET.SubElement(project, "dependencies")
    for coordinate in SPECS[engine]:
        dependency = ET.SubElement(dependencies, "dependency")
        for key, value in zip(("groupId", "artifactId", "version", "classifier"), coordinate):
            ET.SubElement(dependency, key).text = value
    return ET.tostring(project, encoding="unicode")


def smoke_check(engine, jars, stage):
    # Java source-file launch needs a JDK (the runner setup installs Java 17).
    source = stage / "JdbcLoadCheck.java"
    source.write_text('import java.sql.Driver;\nclass JdbcLoadCheck {\n'
                      ' public static void main(String[] args) throws Exception {\n'
                      '  Object driver = Class.forName(args[0]).getDeclaredConstructor().newInstance();\n'
                      '  if (!(driver instanceof Driver)) throw new Exception("Not a JDBC driver");\n'
                      '  for (int i=1; i<args.length; i++) Class.forName(args[i]);\n'
                      ' }\n}\n')
    extra = {"fabric": ["com.azure.identity.ClientSecretCredentialBuilder", "com.microsoft.aad.msal4j.ConfidentialClientApplication"],
             "redshift": ["software.amazon.awssdk.services.redshift.RedshiftClient",
                          "software.amazon.awssdk.services.redshiftserverless.RedshiftServerlessClient",
                          "software.amazon.awssdk.services.sts.StsClient"]}.get(engine, [])
    subprocess.run(["java", "--class-path", os.pathsep.join(str(p) for p in jars),
                    str(source), DRIVERS[engine]] + extra, check=True)


def installed_path(engine, store=STORE):
    engine = ALIASES.get(engine, engine)
    if engine not in SPECS:
        return ""
    pointer = store / (engine + ".json")
    if not pointer.exists():
        return ""
    data = json.loads(pointer.read_text())
    directory = (store / data["directory"]).resolve()
    if store.resolve() not in directory.parents:
        raise ValueError("Invalid managed driver directory")
    for name, expected in data["sha256"].items():
        path = directory / name
        if Path(name).name != name or not path.is_file() or digest(path) != expected:
            raise ValueError(f"Managed driver integrity check failed: {engine}; reinstall it")
    if not data["sha256"]:
        raise ValueError("Empty JDBC bundle")
    return str(directory)


def install(engine, store=STORE):
    engine = ALIASES.get(engine, engine)
    recipe = {"dependencies": SPECS[engine], "url": ATHENA_URL if engine == "athena" else None}
    pointer = store / (engine + ".json")
    if pointer.exists() and json.loads(pointer.read_text()).get("recipe") == json.loads(json.dumps(recipe)):
        try:
            if installed_path(engine, store):
                print(f"{engine}: installed and verified")
                return
        except ValueError:
            print(f"{engine}: repairing damaged bundle")
    store.mkdir(parents=True, exist_ok=True)
    print(f"{engine}: downloading pinned driver and dependencies...", flush=True)
    with tempfile.TemporaryDirectory(prefix=".install-", dir=store) as temporary:
        stage = Path(temporary)
        jars_dir = stage / "jars"
        jars_dir.mkdir()
        if engine == "athena":
            download(ATHENA_URL, jars_dir / ATHENA_URL.rsplit("/", 1)[1])
        else:
            project = stage / "pom.xml"
            project.write_text(pom(engine))
            subprocess.run([maven(stage), "-B", "-q", "-C", "-f", str(project),
                            "org.apache.maven.plugins:maven-dependency-plugin:3.8.1:copy-dependencies",
                            "-DincludeScope=runtime", f"-DoutputDirectory={jars_dir}"], check=True)
        jars = sorted(jars_dir.glob("*.jar"))
        if not jars or any(not zipfile.is_zipfile(p) for p in jars):
            raise ValueError("Download did not produce valid JDBC JARs")
        smoke_check(engine, jars, stage)
        checksums = {p.name: digest(p) for p in jars}
        identity = hashlib.sha256(json.dumps(checksums, sort_keys=True).encode()).hexdigest()[:16]
        destination = store / f"{engine}-{identity}-{uuid.uuid4().hex[:8]}"
        jars_dir.rename(destination)
        data = {"engine": engine, "recipe": recipe, "directory": destination.name, "sha256": checksums}
        new_pointer = stage / "pointer.json"
        new_pointer.write_text(json.dumps(data, indent=2) + "\n")
        os.replace(new_pointer, pointer)
        print(f"{engine}: installed {len(jars)} JAR(s); driver load check passed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("engines", nargs="*", choices=sorted(set(SPECS) | set(ALIASES)))
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--classpath", metavar="DRIVER_CLASS", help="Print installed bundle path; no downloads")
    args = parser.parse_args()
    if args.list:
        print("\n".join(sorted(set(SPECS) | set(ALIASES))))
        return
    if args.classpath is not None:
        engine = next((key for key, value in DRIVERS.items() if value == args.classpath), "")
        print(installed_path(engine))
        return
    if not args.engines:
        parser.error("Select one or more engines, or use --list")
    for engine in dict.fromkeys(ALIASES.get(e, e) for e in args.engines):
        install(engine)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f"JDBC installation failed: {exc}", file=sys.stderr)
        sys.exit(1)
