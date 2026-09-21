#!/usr/bin/env python3
"""CLI access to Benchmark Studio baseline governance and comparisons."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ui import server


def configure(args: argparse.Namespace) -> None:
    if getattr(args, "reports", None):
        server.REPORTS = Path(args.reports).expanduser().resolve()
    if getattr(args, "database", None):
        server.DB_PATH = Path(args.database).expanduser().resolve()
        server.DATABASE_URL = ""
        server.REGISTRY_BACKEND = "sqlite"
    needs_registry = args.command == "baseline" or getattr(args, "baseline", None) == "active"
    if needs_registry:
        server.init_registry()


def resolve_report(value: str) -> dict[str, Any]:
    value = str(value or "").strip()
    try:
        return {"id": value, "summary": server.report_by_id(value)}
    except ValueError:
        pass
    matches = []
    for path in server.REPORTS.glob("**/run_summary.json"):
        try:
            summary = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if str(summary.get("meta", {}).get("run_id") or "") == value:
            matches.append({"id": str(path.parent.relative_to(server.REPORTS)), "summary": summary})
    if not matches:
        raise ValueError(f"Unknown report or run ID: {value}")
    if len(matches) > 1:
        raise ValueError(f"Run ID is ambiguous; use a report ID: {value}")
    return matches[0]


def active_for(candidate: dict[str, Any]) -> dict[str, Any]:
    summary = candidate["summary"]
    engine = str(summary.get("meta", {}).get("engine") or "")
    signature = server.workload_signature(summary)
    exact = [item for item in server.reference_promotions() if
             item["engine"] == engine and item["workload_signature"] == signature]
    if not exact:
        raise ValueError("No active baseline matches the candidate's exact engine and workload configuration")
    return resolve_report(exact[0]["report_id"])


def verdict(name: str, metric: dict[str, Any], warning: float, critical: float) -> str:
    change = metric.get("change_pct")
    direction = metric.get("higher_is_better")
    if direction is None:
        return "informational"
    if change is None:
        left, right = float(metric.get("left") or 0), float(metric.get("right") or 0)
        if left == right:
            return "within-threshold"
        if name == "error_pct" and right > left:
            return "critical"
        return "informational"
    impact = change if direction else -change
    if impact >= warning:
        return "improved"
    if impact <= -critical:
        return "critical"
    if impact <= -warning:
        return "warning"
    return "within-threshold"


def comparison_payload(baseline: dict[str, Any], candidate: dict[str, Any], warning: float,
                       critical: float) -> dict[str, Any]:
    result = server.comparison(baseline["summary"], candidate["summary"], include_noise=True)
    result["report_identity"] = {
        "baseline": {"id": baseline["id"], "run_id": baseline["summary"].get("meta", {}).get("run_id")},
        "candidate": {"id": candidate["id"], "run_id": candidate["summary"].get("meta", {}).get("run_id")},
    }
    result["thresholds_pct"] = {"warning": warning, "critical": critical}
    for name, metric in result["metrics"].items():
        noise = result.get("baseline_noise", {}).get(name, {})
        observed = noise.get("cv_pct")
        metric["observed_noise_pct"] = observed
        metric["effective_warning_pct"] = max(warning, observed) if observed is not None else warning
        metric["effective_critical_pct"] = max(critical, observed * 2) if observed is not None else critical
        metric["verdict"] = verdict(
            name, metric, metric["effective_warning_pct"], metric["effective_critical_pct"]
        )
    return result


def print_comparison(result: dict[str, Any]) -> None:
    identity = result["report_identity"]
    print(f"Baseline:  {identity['baseline']['run_id'] or identity['baseline']['id']}")
    print(f"Candidate: {identity['candidate']['run_id'] or identity['candidate']['id']}")
    print(f"Thresholds: warning {result['thresholds_pct']['warning']}%, critical {result['thresholds_pct']['critical']}%")
    print("\nMetric                         Baseline      Candidate      Change       Verdict")
    for name in ("throughput_per_s", "mean_ms", "p50_ms", "p95_ms", "p99_ms", "error_pct"):
        metric = result["metrics"][name]
        change = "—" if metric["change_pct"] is None else f"{metric['change_pct']:+.2f}%"
        noise = "" if metric.get("observed_noise_pct") is None else f" · noise {metric['observed_noise_pct']}%"
        print(f"{name:28} {metric['left']:12.3f} {metric['right']:14.3f} {change:>11}   {metric['verdict']}{noise}")
    if result.get("compatibility"):
        print("\nConfiguration differences:")
        for item in result["compatibility"]:
            print(f"- {item['field']}: {item['left']} -> {item['right']} ({item['severity']})")
    if result.get("survivor_bias"):
        print(f"\nWarning: {result['survivor_bias']}")


def command_baseline(args: argparse.Namespace) -> None:
    if args.action == "promote":
        report = resolve_report(args.run_id)
        governance = server.promote_reference(report["id"], {
            "reason": args.reason, "promoted_by": args.promoted_by,
        })
        print(json.dumps(governance, indent=2, sort_keys=True))
    elif args.action == "list":
        items = server.reference_promotions(active_only=not args.all)
        if args.format == "json":
            print(json.dumps(items, indent=2, sort_keys=True))
            return
        if not items:
            print("No baselines found.")
            return
        print("ACTIVE  ENGINE        RUN ID                                   PROMOTED BY       REASON")
        for item in items:
            print(f"{str(item['active']):6}  {item['engine'][:12]:12}  {item['run_id'][:40]:40} "
                  f"{str(item['promoted_by'] or '')[:17]:17} {item['reason']}")
    else:
        print(json.dumps(server.deactivate_reference(args.run_id), indent=2))


def command_compare(args: argparse.Namespace) -> None:
    candidate = resolve_report(args.run_id) if args.run_id else {
        "id": str(Path(args.candidate_report)),
        "summary": json.loads(Path(args.candidate_report).read_text()),
    }
    if args.baseline_report:
        baseline = {"id": str(Path(args.baseline_report)),
                    "summary": json.loads(Path(args.baseline_report).read_text())}
    elif args.baseline == "active":
        baseline = active_for(candidate)
    else:
        baseline = resolve_report(args.baseline)
    result = comparison_payload(baseline, candidate, args.warning_pct, args.critical_pct)
    if args.format == "json":
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print_comparison(result)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Manage and compare JMeter benchmark baselines")
    root.add_argument("--reports", help="Reports root (default: reports/)")
    root.add_argument("--database", help="SQLite registry path (default: UI registry)")
    commands = root.add_subparsers(dest="command", required=True)
    baseline = commands.add_parser("baseline", help="Manage reference baselines")
    actions = baseline.add_subparsers(dest="action", required=True)
    promote = actions.add_parser("promote", help="Promote a completed run")
    promote.add_argument("--run-id", required=True)
    promote.add_argument("--reason", required=True)
    promote.add_argument("--promoted-by", default="cli-user")
    listing = actions.add_parser("list", help="List baselines")
    listing.add_argument("--all", action="store_true", help="Include inactive promotion history")
    listing.add_argument("--format", choices=("text", "json"), default="text")
    deactivate = actions.add_parser("deactivate", help="Deactivate a baseline")
    deactivate.add_argument("--run-id", required=True)
    compare = commands.add_parser("compare", help="Compare a candidate with a baseline")
    candidate = compare.add_mutually_exclusive_group(required=True)
    candidate.add_argument("--run-id", help="Candidate report ID or run ID")
    candidate.add_argument("--candidate-report", help="Candidate run_summary.json path")
    reference = compare.add_mutually_exclusive_group(required=True)
    reference.add_argument("--baseline", help="Baseline report/run ID, or 'active'")
    reference.add_argument("--baseline-report", help="Baseline run_summary.json path")
    compare.add_argument("--warning-pct", type=float, default=5.0)
    compare.add_argument("--critical-pct", type=float, default=10.0)
    compare.add_argument("--format", choices=("text", "json"), default="text")
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        configure(args)
        command_baseline(args) if args.command == "baseline" else command_compare(args)
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
