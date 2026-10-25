"""Self-contained offline demonstration using four explicitly synthetic cases."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import difflib
import hashlib
import json
from pathlib import Path

from .cli import main as run_cli

ROOT = Path(__file__).resolve().parents[1]


def make_patch(path: str, before: str, after: str) -> str:
    return (
        "diff --git a/"
        + path
        + " b/"
        + path
        + "\n"
        + "".join(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile="a/" + path,
                tofile="b/" + path,
            )
        )
    )


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Build local pilot demonstration reports without network access."
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args(argv)
    root = args.output or ROOT / "outputs" / datetime.now(timezone.utc).strftime(
        "demo-%Y%m%dT%H%M%S-%fZ"
    )
    if root.exists() and any(root.iterdir()):
        parser.error("Output directory must be new or empty.")
    root.mkdir(parents=True, exist_ok=True)
    fixtures = [
        (
            "sensitive_eval",
            "synthetic",
            "def calculate(value):\n    return int(value)\n",
            "def calculate(value):\n    return eval(value)\n",
            "Introduces eval; scanner warning expected, not a validated exploit.",
        ),
        (
            "benign_edit",
            "synthetic",
            "def add(a, b):\n    return a + b\n",
            'def add(a, b):\n    """Add two numbers."""\n    return a + b\n',
            "Small documentation edit; security scanner may be skipped.",
        ),
        (
            "shift_existing",
            "synthetic",
            "def calculate(value):\n    return eval(value)\n",
            '"""Example module."""\n\ndef calculate(value):\n    return eval(value)\n',
            "Existing eval warning moves lines; should match the baseline.",
        ),
        (
            "adaptive_miss_assert",
            "synthetic",
            "def positive(value):\n    return value\n",
            "def positive(value):\n    assert value > 0\n    return value\n",
            "Deliberate policy limitation: full Bandit can warn about assert while adaptive skips it.",
        ),
    ]
    cases = []
    for name, kind, before, after, explanation in fixtures:
        folder = root / "inputs" / name
        base = folder / "base"
        base.mkdir(parents=True)
        (base / "example.py").write_text(before)
        patch = folder / "change.diff"
        patch.write_text(make_patch("example.py", before, after))
        cases.append(
            dict(name=name, kind=kind, base=base, patch=patch, explanation=explanation)
        )
    summary = []
    for c in cases:
        out = root / "reports" / c["name"]
        status = run_cli(
            [
                "--repo",
                str(c["base"]),
                "--patch",
                str(c["patch"]),
                "--mode",
                "compare",
                "--repeats",
                str(args.repeats),
                "--output",
                str(out),
            ]
        )
        if status:
            raise RuntimeError("Demonstration failed: " + c["name"])
        report = json.loads((out / "report.json").read_text())
        comp = report["comparison"]
        diag = comp["diagnostic_comparison"]
        summary.append(
            dict(
                case=c["name"],
                kind=c["kind"],
                explanation=c["explanation"],
                adaptive_seconds=comp["timings"]["adaptive"]["median_seconds"],
                full_seconds=comp["timings"]["full"]["median_seconds"],
                time_reduction_pct=comp["time_reduction_pct"],
                adaptive_new=diag["adaptive_new_diagnostics"],
                full_new=diag["full_new_diagnostics"],
                diagnostics_not_observed=len(diag["not_observed_by_adaptive"]),
                diagnostic_comparison_defined=diag["fraction"] is not None,
                report="reports/" + c["name"] + "/report.html",
            )
        )
    with (root / "summary.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summary[0]))
        w.writeheader()
        w.writerows(summary)
    (root / "demo_manifest.json").write_text(
        json.dumps(
            dict(
                role="Demonstration, not independent validation. Synthetic cases deliberately exercise limitations.",
                scope="Four synthetic cases only; no candidate code or project tests executed.",
                repeats=args.repeats,
                cases=[
                    dict(
                        name=c["name"],
                        kind=c["kind"],
                        explanation=c["explanation"],
                        patch_sha256=hashlib.sha256(
                            c["patch"].read_bytes()
                        ).hexdigest(),
                    )
                    for c in cases
                ],
            ),
            indent=2,
        )
    )
    from html import escape
    from .report import CSS, table

    rows = [
        [
            escape(r["case"]),
            escape(r["kind"]),
            f"{r['adaptive_seconds']:.4f}s",
            f"{r['full_seconds']:.4f}s",
            f"{r['time_reduction_pct']:.1f}%",
            str(r["adaptive_new"]) + " / " + str(r["full_new"]),
            '<a href="'
            + escape(r["report"], quote=True)
            + '">Open evidence report</a>',
        ]
        for r in summary
    ]
    html = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PATCH-GATE pilot demonstration</title><style>'
        + CSS
        + '</style></head><body><main><header><div class="brand">PATCH-GATE / LOCAL PILOT</div><h1>Measured checking, visible limits</h1><p>{synthetic_count} self-contained synthetic cases. A demonstration of the tool, not evidence of real-world defect detection or research superiority.</p></header><section><h2>Adaptive versus full checking</h2><p>Median local static-check time after warming both modes. Mode order alternates between repetitions. Positive reductions mean faster checking; source preparation is separate.</p>'
        + table(
            [
                "Case",
                "Type",
                "Adaptive",
                "Full",
                "Time reduction",
                "New diagnostics: adaptive / full",
                "Evidence",
            ],
            rows,
        )
        + '<div class="note">The deliberate assert example shows that adaptive skipping can miss a Bandit warning. These synthetic examples do not establish real-world detection accuracy. Scanner warnings are not confirmed vulnerabilities. Zero new full-mode warnings does not mean perfect detection.</div></section><section><h2>Demonstration scope</h2><p>Syntax, Ruff, Radon descriptions and selectively requested Bandit checks. No repository tests or candidate code are executed. Reports expose missing, failed and skipped evidence; no patch is certified safe.</p></section></main></body></html>'
    )
    html = html.replace(
        "{synthetic_count}", str(sum(c["kind"] == "synthetic" for c in cases))
    )
    (root / "index.html").write_text(html)
    print("Demo index: " + str(root / "index.html"))
    print("Summary: " + str(root / "summary.csv"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
