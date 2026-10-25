"""Freeze new pilot tables/figures and a paper-ready methods/results section.

The input is a newly executed 60-case static-check experiment, not prior study statistics.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import random
import statistics

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

ROOT = Path(__file__).resolve().parents[1]
RUNS = [("gemini_mini", "Gemini / mini"), ("agentless_gpt4o", "Agentless / GPT-4o")]
METRICS = [
    "cc_mean",
    "cc_max",
    "mi",
    "halstead_volume",
    "max_nesting",
    "max_function_lines",
]
BLUE = "#176b91"
GRAY = "#99acba"


def csv_write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def save(fig, out, name):
    fig.savefig(out / (name + ".png"), dpi=180, facecolor="white")
    fig.savefig(out / (name + ".svg"), facecolor="white", metadata={"Date": None})
    plt.close(fig)


def table(headers, rows):
    return "\n".join(
        [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join(["---"] * len(headers)) + " |",
            *["| " + " | ".join(map(str, r)) + " |" for r in rows],
        ]
    )


def build(run_dir):
    source = list(csv.DictReader((run_dir / "per_patch.csv").open()))
    cohort = json.loads((run_dir / "cohort.json").read_text())
    accounting = list(csv.DictReader((run_dir / "candidate_accounting.csv").open()))
    assets = ROOT / "docs/assets"
    data_dir = assets / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    summaries, metric_rows, patch_metrics, warning_rows = [], [], [], []
    for run, label in RUNS:
        rows = [r for r in source if r["run"] == run]
        good = [
            r
            for r in rows
            if r["baseline_complete"] == "True" and r["exit_code"] == "0"
        ]
        assert len(rows) == 30 and len(good) == 30, (
            "This paper snapshot requires the complete 30+30 run."
        )
        cases = [c for c in cohort if c["run"] == run]
        a = [float(r["adaptive_seconds"]) for r in good]
        f = [float(r["full_seconds"]) for r in good]
        q1a, _, q3a = statistics.quantiles(a, n=4, method="inclusive")
        q1f, _, q3f = statistics.quantiles(f, n=4, method="inclusive")
        summary = dict(
            run=run,
            label=label,
            available_resolved=sum(r["run"] == run for r in accounting),
            eligible=sum(
                r["run"] == run and r["eligibility"] == "eligible" for r in accounting
            ),
            attempted=len(rows),
            full_complete=len(good),
            repositories=len({r["repo"] for r in rows}),
            affected_python_files=sum(int(r["python_files"]) for r in good),
            adaptive_median_ms=1000 * statistics.median(a),
            full_median_ms=1000 * statistics.median(f),
            adaptive_q1_ms=1000 * q1a,
            adaptive_q3_ms=1000 * q3a,
            full_q1_ms=1000 * q1f,
            full_q3_ms=1000 * q3f,
            sum_adaptive_medians_s=sum(a),
            sum_full_medians_s=sum(f),
            reduction_of_summed_medians_pct=100 * (1 - sum(a) / sum(f)),
            median_patch_reduction_pct=statistics.median(
                float(r["time_reduction_pct"]) for r in good
            ),
            adaptive_new_diagnostics=sum(int(r["adaptive_new_all"]) for r in good),
            full_new_diagnostics=sum(int(r["full_new_all"]) for r in good),
            adaptive_new_bandit=sum(int(r["adaptive_new_bandit"]) for r in good),
            full_new_bandit=sum(int(r["full_new_bandit"]) for r in good),
            skipped_bandit_snapshots=sum(
                int(r["adaptive_skipped_bandit_snapshots"]) for r in good
            ),
            diagnostic_identities_stable=all(
                r["diagnostics_stable"] == "True" for r in good
            ),
        )
        summaries.append(summary)
        for c in cases:
            p = run_dir / "reports" / run / c["instance_id"] / "report.json"
            report = json.loads(p.read_text())
            full = report["comparison"]["full_reference"]
            values = {m: [] for m in METRICS}
            for file in full["files"]:
                b = file["before"]["quality"].get("metrics")
                a_metrics = file["after"]["quality"].get("metrics")
                if b and a_metrics:
                    for m in METRICS:
                        values[m].append(a_metrics[m] - b[m])
            patch_metrics.append(
                dict(
                    run=run,
                    instance_id=c["instance_id"],
                    repo=c["repo"],
                    **{m: statistics.mean(v) if v else None for m, v in values.items()},
                )
            )
            for warning in full["newly_observed"]:
                warning_rows.append(
                    dict(
                        run=run,
                        instance_id=c["instance_id"],
                        repo=c["repo"],
                        path=warning["path"],
                        tool=warning["tool"],
                        rule=warning["rule"],
                        scanner_severity=warning["severity"],
                        independent_harm_label="unknown",
                    )
                )
        for m in METRICS:
            vals = [r[m] for r in patch_metrics if r["run"] == run and r[m] is not None]
            metric_rows.append(
                dict(
                    run=run,
                    metric=m,
                    comparable_patches=len(vals),
                    mean_delta=statistics.mean(vals),
                    median_delta=statistics.median(vals),
                    increased=sum(v > 0 for v in vals),
                    decreased=sum(v < 0 for v in vals),
                    unchanged=sum(v == 0 for v in vals),
                )
            )
    csv_write(data_dir / "public_patch_summary.csv", summaries)
    csv_write(data_dir / "public_patch_metric_summary.csv", metric_rows)
    csv_write(data_dir / "public_patch_metric_deltas.csv", patch_metrics)
    csv_write(data_dir / "public_patch_new_diagnostics.csv", warning_rows)
    # Preserve per-patch measurements and selected public identifiers for audit/replotting.
    csv_write(data_dir / "public_patch_per_case.csv", source)
    (data_dir / "public_patch_cohort.json").write_text(json.dumps(cohort, indent=2))
    (data_dir / "public_patch_protocol.json").write_text(
        (run_dir / "protocol.json").read_text()
    )
    (data_dir / "public_patch_accounting.csv").write_text(
        (run_dir / "candidate_accounting.csv").read_text()
    )
    shared = len(
        {c["instance_id"] for c in cohort if c["run"] == "gemini_mini"}
        & {c["instance_id"] for c in cohort if c["run"] == "agentless_gpt4o"}
    )

    render_figures(source, patch_metrics, summaries, assets)

    cohort_table = table(
        [
            "Public run",
            "Resolved pool",
            "Selected",
            "Repositories",
            "Affected Python files",
            "Complete full references",
        ],
        [
            [
                s["label"],
                s["available_resolved"],
                s["attempted"],
                s["repositories"],
                s["affected_python_files"],
                s["full_complete"],
            ]
            for s in summaries
        ],
    )
    timing_table = table(
        [
            "Public run",
            "Adaptive median/patch (ms)",
            "Full median/patch (ms)",
            "Reduction in summed per-patch medians",
        ],
        [
            [
                s["label"],
                f"{s['adaptive_median_ms']:.1f}",
                f"{s['full_median_ms']:.1f}",
                f"{s['reduction_of_summed_medians_pct']:.1f}%",
            ]
            for s in summaries
        ],
    )
    diag_table = table(
        [
            "Public run",
            "New diagnostics: adaptive / full",
            "New Bandit warnings: adaptive / full",
            "Skipped Bandit snapshots",
        ],
        [
            [
                s["label"],
                f"{s['adaptive_new_diagnostics']} / {s['full_new_diagnostics']}",
                f"{s['adaptive_new_bandit']} / {s['full_new_bandit']}",
                s["skipped_bandit_snapshots"],
            ]
            for s in summaries
        ],
    )
    metric_table = table(
        [
            "Public run",
            "Metric",
            "Comparable patches",
            "Mean delta",
            "Median delta",
            "Up / down / unchanged",
        ],
        [
            [
                dict(RUNS)[r["run"]],
                r["metric"],
                r["comparable_patches"],
                f"{r['mean_delta']:.3g}",
                f"{r['median_delta']:.3g}",
                f"{r['increased']} / {r['decreased']} / {r['unchanged']}",
            ]
            for r in metric_rows
        ],
    )
    tables = {
        "cohort": cohort_table,
        "timing": timing_table,
        "diagnostics": diag_table,
        "metrics": metric_table,
    }
    (data_dir / "public_patch_tables.json").write_text(json.dumps(tables, indent=2))
    for name, text in tables.items():
        (ROOT / "paper/tables" / f"{name}.md").write_text(text + "\n")
    for name in [
        "public_patch_summary.csv",
        "public_patch_metric_summary.csv",
        "public_patch_metric_deltas.csv",
        "public_patch_new_diagnostics.csv",
        "public_patch_per_case.csv",
    ]:
        (ROOT / "paper/tables" / name).write_text((data_dir / name).read_text())
    for name in [
        "public_patch_timing",
        "public_patch_diagnostics",
        "public_patch_metric_deltas",
    ]:
        for ext in ["png", "svg"]:
            (ROOT / "paper/figures" / f"{name}.{ext}").write_bytes(
                (assets / f"{name}.{ext}").read_bytes()
            )
    provenance = {
        "source_per_patch_sha256": hashlib.sha256(
            (run_dir / "per_patch.csv").read_bytes()
        ).hexdigest(),
        "scope": "new 60-case exploratory static-check evaluation, separate from synthetic demo and prior analyses",
        "selected_task_overlap": shared,
        "independent_ground_truth": "not collected",
        "notable_diagnostic_dependence": "F401 occurs on the same requests task in both runs; B310 occurs on a separate pytest task",
        "repetitions_per_mode": 3,
    }
    (data_dir / "public_patch_provenance.json").write_text(
        json.dumps(provenance, indent=2)
    )
    return summaries, tables, shared


def render_figures(source, patch_metrics, summaries, assets):
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "text.color": "#243c4b",
            "axes.labelcolor": "#243c4b",
            "svg.hashsalt": "patch-gate-public-pilot-v1",
        }
    )
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.8))
    for ax, (run, label) in zip(axes, RUNS):
        rows = [r for r in source if r["run"] == run]
        for r in rows:
            a = 1000 * float(r["adaptive_seconds"])
            f = 1000 * float(r["full_seconds"])
            ax.plot([0, 1], [a, f], color=GRAY, alpha=0.55, linewidth=0.9, zorder=1)
            ax.scatter([0], [a], color=BLUE, s=23, zorder=2)
            ax.scatter([1], [f], color="#607d8b", s=23, zorder=2)
        ax.set_xticks([0, 1], ["Adaptive", "Full"])
        ax.set_xlim(-0.35, 1.35)
        ax.set(
            ylabel="Per-patch median static-check time (ms)",
            title=label + " (30 patches)",
        )
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="y", alpha=0.2)
    fig.suptitle(
        "New exploratory run: paired static-checking time",
        x=0.02,
        ha="left",
        fontweight="bold",
        fontsize=14,
    )
    fig.text(
        0.02,
        0.02,
        "Each line is one patch subset; three measured repeats per mode. Preparation, tests and reviewer time are excluded.",
        fontsize=8.5,
    )
    fig.tight_layout(rect=(0, 0.06, 1, 0.91))
    save(fig, assets, "public_patch_timing")

    fig, axes = plt.subplots(1, 2, figsize=(10, 4.6))
    for ax, key, title in zip(
        axes,
        ["diagnostics", "bandit"],
        ["All newly observed diagnostics", "New Bandit diagnostics"],
    ):
        for mode, offset, color in [("adaptive", -0.17, BLUE), ("full", 0.17, GRAY)]:
            values = [s[f"{mode}_new_" + key] for s in summaries]
            bars = ax.bar(
                [i + offset for i in range(2)],
                values,
                width=0.30,
                color=color,
                label=mode.title(),
            )
            ax.bar_label(bars, padding=3)
        ax.set_xticks([0, 1], [label for _, label in RUNS])
        ax.set_title(title)
        ax.set_ylabel("Diagnostic messages, not confirmed harms")
        ax.set_ylim(0, 3.2)
        ax.yaxis.set_major_locator(MaxNLocator(integer=True))
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="y", alpha=0.2)
    fig.legend(
        *axes[0].get_legend_handles_labels(), loc="upper right", ncol=2, frameon=False
    )
    fig.suptitle(
        "The full-reference outcome denominator is sparse",
        x=0.02,
        ha="left",
        fontweight="bold",
        fontsize=14,
    )
    fig.text(
        0.02,
        0.02,
        "Only three diagnostic messages on two distinct tasks; 15 selected tasks overlap across runs. Zero/zero is undefined preservation.",
        fontsize=8.5,
    )
    fig.tight_layout(rect=(0, 0.06, 1, 0.87))
    save(fig, assets, "public_patch_diagnostics")

    fig, axes = plt.subplots(1, 2, figsize=(10, 4.6))
    rng = random.Random(42)
    for ax, metric, label in zip(
        axes,
        ["cc_max", "mi"],
        ["Delta of maximum Radon block CC", "Delta of Maintainability Index"],
    ):
        vals = [
            [
                r[metric]
                for r in patch_metrics
                if r["run"] == run and r[metric] is not None
            ]
            for run, _ in RUNS
        ]
        ax.boxplot(
            vals,
            tick_labels=[name for _, name in RUNS],
            showfliers=False,
            medianprops={"color": BLUE, "linewidth": 2},
        )
        for x, group in enumerate(vals, 1):
            ax.scatter(
                [x + rng.uniform(-0.09, 0.09) for _ in group],
                group,
                s=18,
                color=BLUE,
                alpha=0.5,
            )
        ax.axhline(0, color="#9a4f15", linewidth=1, linestyle="--")
        ax.set_ylabel(label)
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="y", alpha=0.2)
    fig.suptitle(
        "Observed metric changes have no independent harm labels",
        x=0.02,
        ha="left",
        fontweight="bold",
        fontsize=14,
    )
    fig.text(
        0.02,
        0.02,
        "Each point is a patch mean over comparable affected files. MI includes size/complexity; these are descriptive deltas.",
        fontsize=8.5,
    )
    fig.tight_layout(rect=(0, 0.06, 1, 0.91))
    save(fig, assets, "public_patch_metric_deltas")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, default=ROOT / "outputs/public-patch-pilot")
    p.add_argument(
        "--frozen",
        action="store_true",
        help="Replot the committed CSV snapshot without source reports or datasets.",
    )
    a = p.parse_args()
    if a.frozen:
        data = ROOT / "docs/assets/data"
        source = list(csv.DictReader((data / "public_patch_per_case.csv").open()))
        patch_metrics = list(
            csv.DictReader((data / "public_patch_metric_deltas.csv").open())
        )
        for row in patch_metrics:
            for m in METRICS:
                row[m] = float(row[m]) if row[m] else None
        summaries = list(csv.DictReader((data / "public_patch_summary.csv").open()))
        for row in summaries:
            for key, value in list(row.items()):
                if key not in ["run", "label", "diagnostic_identities_stable"]:
                    try:
                        row[key] = int(value)
                    except ValueError:
                        row[key] = float(value)
        render_figures(source, patch_metrics, summaries, ROOT / "docs/assets")
        print("Rebuilt figures from frozen CSVs without research source files.")
    else:
        summaries, tables, shared = build(a.input)
        print(json.dumps(summaries, indent=2))
        print("Overlapping selected tasks:", shared)


if __name__ == "__main__":
    main()
