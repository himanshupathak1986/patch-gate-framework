"""CLI orchestration and measured comparison of full/adaptive static checking."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import csv
import json
from pathlib import Path
import statistics
import sys
import time

from . import __version__
from .checks import analyze, signature, versions
from .report import render
from .snapshots import PatchError, digest, materialize


def compare_diagnostics(adaptive: dict, full: dict) -> dict:
    def key(f):
        return (f["path"], *signature(f))

    a = Counter(key(f) for f in adaptive["newly_observed"])
    b = Counter(key(f) for f in full["newly_observed"])
    matched = sum((a & b).values())
    missing = b - a
    not_seen = []
    for f in full["newly_observed"]:
        k = key(f)
        if missing[k]:
            not_seen.append(f)
            missing[k] -= 1
    incomplete_full = bool(full["incomplete_checks"]) or not full["files"]
    fraction = (
        None if incomplete_full or not sum(b.values()) else matched / sum(b.values())
    )
    if incomplete_full:
        detail = "Full-mode evidence is incomplete; a complete static-output comparison cannot be established."
    elif not sum(b.values()):
        detail = "Full mode observed no new diagnostics, so the fraction is undefined; it is not 100% detection."
    else:
        detail = "Full-scan output is a scanner reference, not ground truth for defects or security. Duplicate scanner messages are not independent harms."
    return {
        "full_new_diagnostics": sum(b.values()),
        "adaptive_new_diagnostics": sum(a.values()),
        "matched_new_diagnostics": matched,
        "fraction": fraction,
        "observed_fraction_display": f"{matched}/{sum(b.values())} ({fraction:.1%})"
        if fraction is not None
        else "unknown / undefined",
        "not_observed_by_adaptive": not_seen,
        "detail": detail,
    }


def comparison(snapshots, tools, timeout: float, repeats: int) -> tuple[dict, dict]:
    # Warm both modes before recording measurements; alternate order to reduce startup/order bias.
    analyze(snapshots, "adaptive", tools, timeout)
    analyze(snapshots, "full", tools, timeout)
    trials = []
    latest = {}
    fingerprints = {"adaptive": [], "full": []}
    for repeat in range(repeats):
        order = ["adaptive", "full"] if repeat % 2 == 0 else ["full", "adaptive"]
        for mode in order:
            r = analyze(snapshots, mode, tools, timeout)
            latest[mode] = r
            fingerprints[mode].append(
                sorted(
                    (f["path"], f["tool"], f["rule"], f["line"], f["message"])
                    for f in r["newly_observed"]
                )
            )
            trials.append(
                {
                    "repeat": repeat + 1,
                    "mode": mode,
                    "seconds": r["seconds"],
                    "new_diagnostics": len(r["newly_observed"]),
                    "incomplete_checks": len(r["incomplete_checks"]),
                }
            )
    timings = {}
    for mode in ["adaptive", "full"]:
        values = [r["seconds"] for r in trials if r["mode"] == mode]
        timings[mode] = {
            "median_seconds": statistics.median(values),
            "min_seconds": min(values),
            "max_seconds": max(values),
        }
    denominator = timings["full"]["median_seconds"]
    comp = {
        "repeats": repeats,
        "warmup_runs_per_mode": 1,
        "order": "alternating adaptive/full then full/adaptive",
        "timings": timings,
        "trials": trials,
        "time_reduction_pct": 100
        * (1 - timings["adaptive"]["median_seconds"] / denominator)
        if denominator
        else 0,
        "diagnostic_comparison": compare_diagnostics(
            latest["adaptive"], latest["full"]
        ),
        "full_reference": latest["full"],
        "new_diagnostics_stable_across_repetitions": {
            k: all(x == v[0] for x in v) for k, v in fingerprints.items()
        },
    }
    return latest["adaptive"], comp


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="PATCH-GATE: local before/after static evidence for a Python patch. Does not execute candidate code or project tests."
    )
    p.add_argument(
        "--repo",
        type=Path,
        required=True,
        help="Local checkout or base source directory (read only).",
    )
    p.add_argument(
        "--patch",
        type=Path,
        required=True,
        help="UTF-8 unified patch to analyze in a temporary copy.",
    )
    p.add_argument(
        "--base",
        default="worktree",
        help="worktree (default) or an existing local Git commit/ref.",
    )
    p.add_argument(
        "--mode", choices=["adaptive", "full", "compare"], default="adaptive"
    )
    p.add_argument(
        "--output",
        "--out",
        type=Path,
        help="New/empty output directory; existing reports are never overwritten.",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=30,
        help="Per scanner/snapshot timeout in seconds (default 30).",
    )
    p.add_argument(
        "--repeats",
        type=int,
        default=3,
        help="Measured comparisons after warm-up (default 3).",
    )
    p.add_argument(
        "--fail-on-new",
        action="store_true",
        help="Exit 1 when new diagnostics or any after-syntax error is observed.",
    )
    p.add_argument(
        "--require-complete",
        action="store_true",
        help="Exit 3 for skipped/failed/missing checks or out-of-scope files.",
    )
    p.add_argument(
        "--version", action="version", version="PATCH-GATE pilot " + __version__
    )
    return p


def main(argv: list[str] | None = None) -> int:
    p = parser()
    args = p.parse_args(argv)
    if not 0 < args.timeout <= 300:
        p.error("--timeout must be greater than 0 and at most 300 seconds.")
    if not 1 <= args.repeats <= 20:
        p.error("--repeats must be between 1 and 20.")
    started = time.perf_counter()
    stamp = datetime.now(timezone.utc)
    out = args.output or Path("outputs") / stamp.strftime("run-%Y%m%dT%H%M%S-%fZ")
    try:
        if out.exists() and (not out.is_dir() or any(out.iterdir())):
            print("Output directory must be new or empty: " + str(out), file=sys.stderr)
            return 2
        out.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print("Cannot create output directory: " + str(exc), file=sys.stderr)
        return 2
    data = {
        "schema_version": "patch-gate-pilot/1",
        "pilot_version": __version__,
        "created_at_utc": stamp.isoformat(),
        "tool_versions": versions(),
        "configuration": {
            "mode": args.mode,
            "timeout_seconds": args.timeout,
            "repeats": args.repeats,
            "ruff_rules": "E4,E7,E9,F",
            "ignore_suppressions": True,
            "large_change_lines": 20,
            "candidate_code_execution": False,
            "network_access": False,
            "project_tests_run": False,
        },
        "input": {"repo": str(args.repo.expanduser().resolve()), "base": args.base},
        "limitations": [
            "Static findings are not independently confirmed defects/vulnerabilities.",
            "No project tests, behavioral tests or semantic-completeness verification.",
            "Only changed .py files are scanned; no dependency or whole-repository data-flow analysis.",
            "Adaptive skipping can miss diagnostics; skipped evidence is unknown.",
            "Diagnostic matching can misattribute context-dependent findings.",
            "Twenty-line escalation is illustrative, not validated risk calibration.",
        ],
    }
    status = 0
    try:
        if args.patch.stat().st_size > 5 * 1024 * 1024:
            raise PatchError("Patch exceeds the 5 MiB limit.")
        patch = args.patch.read_bytes()
        data["input"]["patch_sha256"] = digest(patch)
        prep = time.perf_counter()
        with materialize(args.repo, patch, args.base) as (snapshots, provenance):
            data["preparation_seconds"] = time.perf_counter() - prep
            data["input"] = provenance
            if args.mode == "compare":
                data["analysis"], data["comparison"] = comparison(
                    snapshots, data["tool_versions"], args.timeout, args.repeats
                )
            else:
                data["analysis"] = analyze(
                    snapshots, args.mode, data["tool_versions"], args.timeout
                )
        if args.require_complete and (
            data["analysis"]["incomplete_checks"]
            or not data["analysis"]["files"]
            or provenance["unscanned_non_python_paths"]
        ):
            status = 3
        if args.fail_on_new and (
            data["analysis"]["newly_observed"]
            or data["analysis"]["after_syntax_issues"]
            or data.get("comparison", {})
            .get("diagnostic_comparison", {})
            .get("full_new_diagnostics", 0)
        ):
            status = 1 if status == 0 else status
    except (PatchError, OSError, ValueError) as exc:
        data["input_error"] = str(exc)
        status = 2
    data["overall_seconds"] = time.perf_counter() - started
    data["exit_code"] = status
    try:
        (out / "report.json").write_text(
            json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False),
            encoding="utf-8",
        )
        (out / "report.html").write_text(render(data), encoding="utf-8")
        if "comparison" in data:
            with (out / "comparison.csv").open("w", newline="", encoding="utf-8") as f:
                rows = data["comparison"]["trials"]
                w = csv.DictWriter(f, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)
    except (OSError, ValueError) as exc:
        print("Could not write report: " + str(exc), file=sys.stderr)
        return 2
    print("PATCH-GATE: " + data.get("analysis", {}).get("state", "input_error"))
    if "analysis" in data:
        s = data["analysis"]["summary"]
        print(
            f"{s['python_files']} Python file(s); {s['new_static_findings']} newly observed static diagnostic(s); {s['incomplete_check_snapshots']} incomplete/skipped check snapshot(s)."
        )
    else:
        print(data["input_error"])
    print("HTML: " + str((out / "report.html").resolve()))
    print("JSON: " + str((out / "report.json").resolve()))
    return status
