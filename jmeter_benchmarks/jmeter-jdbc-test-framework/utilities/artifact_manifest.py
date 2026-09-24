#!/usr/bin/env python3
"""Build and verify a checksum manifest for a benchmark evidence bundle."""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from urllib.parse import urlparse


EXCLUDED = {"artifact_manifest.json", "s3_upload.json"}


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def included(relative, exclude_dashboard_assets=False):
    value = relative.as_posix()
    if relative.name in EXCLUDED or value.endswith(".tmp"):
        return False
    if exclude_dashboard_assets and value.startswith((
        "dashboard/sbadmin2-1.0.7/", "dashboard/content/css/", "dashboard/content/js/"
    )):
        return False
    return True


def build(run_dir, exclude_dashboard_assets=False):
    run_dir = Path(run_dir).resolve()
    summary_path = run_dir / "run_summary.json"
    if summary_path.is_file():
        summary = json.loads(summary_path.read_text())
        summary["artifact_integrity"] = {"status": "manifested", "manifest": "artifact_manifest.json"}
        summary_path.write_text(json.dumps(summary, indent=2) + "\n")
    artifacts = []
    for path in sorted(item for item in run_dir.rglob("*") if item.is_file() and not item.is_symlink()):
        relative = path.relative_to(run_dir)
        if included(relative, exclude_dashboard_assets):
            artifacts.append({"path": relative.as_posix(), "size_bytes": path.stat().st_size,
                              "sha256": sha256(path)})
    manifest = {
        "schema_version": 1,
        "run_id": json.loads(summary_path.read_text()).get("meta", {}).get("run_id") if summary_path.is_file() else None,
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
    }
    target = run_dir / "artifact_manifest.json"
    target.write_text(json.dumps(manifest, indent=2) + "\n")
    return target, manifest


def verify(run_dir, destination):
    run_dir = Path(run_dir).resolve()
    manifest_path = run_dir / "artifact_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    parsed = urlparse(destination)
    if parsed.scheme != "s3" or not parsed.netloc:
        raise ValueError("destination must be an s3:// URI")
    prefix = parsed.path.lstrip("/").rstrip("/")
    checked = []
    for item in manifest["artifacts"] + [{
        "path": "artifact_manifest.json", "size_bytes": manifest_path.stat().st_size,
        "sha256": sha256(manifest_path),
    }]:
        key = "/".join(part for part in (prefix, item["path"]) if part)
        result = subprocess.run(
            ["aws", "s3api", "head-object", "--bucket", parsed.netloc, "--key", key,
             "--query", "{ContentLength:ContentLength,ETag:ETag,VersionId:VersionId}", "--output", "json"],
            capture_output=True, text=True, check=False,
        )
        if result.returncode:
            raise RuntimeError(f"S3 verification failed for {item['path']}: {result.stderr.strip()}")
        remote = json.loads(result.stdout)
        if int(remote.get("ContentLength", -1)) != item["size_bytes"]:
            raise RuntimeError(f"S3 size mismatch for {item['path']}")
        download = subprocess.Popen(
            ["aws", "s3", "cp", f"s3://{parsed.netloc}/{key}", "-", "--only-show-errors"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        digest = hashlib.sha256()
        assert download.stdout is not None
        for block in iter(lambda: download.stdout.read(1024 * 1024), b""):
            digest.update(block)
        stderr = download.stderr.read().decode(errors="replace") if download.stderr else ""
        if download.wait() or digest.hexdigest() != item["sha256"]:
            raise RuntimeError(f"S3 checksum verification failed for {item['path']}: {stderr.strip()}")
        checked.append({**item, "etag": remote.get("ETag"), "version_id": remote.get("VersionId")})
    return {
        "status": "verified", "uri": destination.rstrip("/") + "/",
        "manifest_sha256": sha256(manifest_path), "verified_objects": len(checked), "objects": checked,
    }


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("build")
    create.add_argument("run_dir")
    create.add_argument("--exclude-dashboard-assets", action="store_true")
    check = sub.add_parser("verify-s3")
    check.add_argument("run_dir")
    check.add_argument("destination")
    check.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.command == "build":
        target, manifest = build(args.run_dir, args.exclude_dashboard_assets)
        print(f"Wrote {target} with {manifest['artifact_count']} artifact(s)")
    else:
        try:
            receipt = verify(args.run_dir, args.destination)
        except Exception as exc:
            receipt = {"status": "failed", "uri": args.destination.rstrip("/") + "/", "error": str(exc)}
            Path(args.output).write_text(json.dumps(receipt, indent=2) + "\n")
            print(str(exc))
            raise SystemExit(1) from exc
        Path(args.output).write_text(json.dumps(receipt, indent=2) + "\n")
        print(f"Verified {receipt['verified_objects']} S3 object(s)")


if __name__ == "__main__":
    main()
