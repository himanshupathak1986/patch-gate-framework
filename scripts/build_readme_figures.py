"""Build honest README figures from a frozen snapshot of the synthetic demo.

Refresh snapshot: python scripts/build_readme_figures.py --demo outputs/standalone-demo
Rebuild figures:  python scripts/build_readme_figures.py
No network calls; no candidate source execution; no inferred defect labels.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

ROOT = Path(__file__).resolve().parents[1]
LABELS = {
    "sensitive_eval": "Eval introduced",
    "benign_edit": "Documentation edit",
    "shift_existing": "Existing warning moved",
    "adaptive_miss_assert": "Assert added",
}
COLORS = {
    "adaptive": "#176b91",
    "full": "#99acba",
    "before": "#99acba",
    "after": "#176b91",
}


def freeze(demo: Path, target: Path) -> dict:
    manifest_path = demo / "demo_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    assert len(manifest["cases"]) == 4
    assert all(c["kind"] == "synthetic" for c in manifest["cases"])
    cases = []
    for cid, label in LABELS.items():
        path = demo / "reports" / cid / "report.json"
        data = json.loads(path.read_text())
        adaptive = data["analysis"]
        full = data["comparison"]["full_reference"]
        # The figures require complete scanner output in the full reference;
        # adaptive omissions remain visible and are not treated as safety evidence.
        assert not full["incomplete_checks"], cid
        assert len(adaptive["files"]) == 1, cid
        assert adaptive["files"][0]["before"]["quality"]["status"] == "completed"
        assert adaptive["files"][0]["after"]["quality"]["status"] == "completed"
        timings = {}
        for mode in ["adaptive", "full"]:
            values = [
                r["seconds"] for r in data["comparison"]["trials"] if r["mode"] == mode
            ]
            assert len(values) >= 3 and all(math.isfinite(x) and x > 0 for x in values)
            timings[mode] = values
        cases.append(
            {
                "id": cid,
                "label": label,
                "kind": "synthetic",
                "report_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "tool_versions": data["tool_versions"],
                "timings_seconds": timings,
                "new_bandit_warnings": {
                    "adaptive": sum(
                        f["tool"] == "bandit" for f in adaptive["newly_observed"]
                    ),
                    "full": sum(f["tool"] == "bandit" for f in full["newly_observed"]),
                },
                "metrics": {
                    arm: adaptive["files"][0][arm]["quality"]["metrics"]
                    for arm in ["before", "after"]
                },
                "bandit_selected": adaptive["files"][0]["bandit_selected"],
            }
        )
    snapshot = {
        "schema": "patch-gate-readme-figures/1",
        "scope": "Four synthetic engineering cases; no independent defect or vulnerability labels.",
        "timing_scope": "Warm static-check time, including selection and subprocess startup; shared input preparation and report generation excluded.",
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "cases": cases,
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(snapshot, indent=2, allow_nan=False))
    return snapshot


def save(fig, out: Path, name: str):
    fig.savefig(out / (name + ".png"), dpi=180, facecolor="white")
    fig.savefig(out / (name + ".svg"), facecolor="white", metadata={"Date": None})
    plt.close(fig)


def style(ax):
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="x", color="#e4ebef", zorder=0)
    ax.set_axisbelow(True)


def build(snapshot: dict, out: Path):
    cases = snapshot["cases"]
    assert [c["id"] for c in cases] == list(LABELS)
    assert all(c["kind"] == "synthetic" for c in cases)
    out.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "axes.labelcolor": "#243c4b",
            "text.color": "#243c4b",
            "axes.titleweight": "bold",
            "svg.hashsalt": "patch-gate-readme-v1",
        }
    )
    y = list(range(len(cases)))
    fig, ax = plt.subplots(figsize=(9, 4.8))
    for mode, offset in [("adaptive", -0.18), ("full", 0.18)]:
        trials = [[1000 * t for t in c["timings_seconds"][mode]] for c in cases]
        med = [statistics.median(t) for t in trials]
        low = [m - min(t) for m, t in zip(med, trials)]
        high = [max(t) - m for m, t in zip(med, trials)]
        ax.barh(
            [v + offset for v in y],
            med,
            height=0.30,
            color=COLORS[mode],
            label=mode.title(),
            xerr=[low, high],
            capsize=3,
            zorder=3,
        )
    ax.set_yticks(y, [c["label"] for c in cases])
    ax.invert_yaxis()
    ax.set_xlabel("Static-check time (milliseconds); median and observed min–max")
    fig.suptitle(
        "Measured checking time in four synthetic cases",
        x=0.02,
        ha="left",
        fontsize=14,
        fontweight="bold",
    )
    fig.legend(
        *ax.get_legend_handles_labels(), loc="upper right", ncol=2, frameon=False
    )
    style(ax)
    fig.text(
        0.02,
        0.02,
        "Three measured repetitions per mode after warm-up. These are local timings, not reviewer-time savings.",
        fontsize=8.5,
        color="#586b79",
    )
    fig.tight_layout(rect=(0, 0.06, 1, 0.88))
    save(fig, out, "demo_checking_time")

    fig, ax = plt.subplots(figsize=(9, 4.8))
    for mode, offset in [("adaptive", -0.18), ("full", 0.18)]:
        values = [c["new_bandit_warnings"][mode] for c in cases]
        ax.barh(
            [v + offset for v in y],
            values,
            height=0.30,
            color=COLORS[mode],
            label=mode.title(),
            zorder=3,
        )
        for v, val in zip(y, values):
            ax.text(val + 0.025, v + offset, str(val), va="center", fontsize=10)
    ax.set_yticks(y, [c["label"] for c in cases])
    ax.invert_yaxis()
    ax.set_xlim(0, 1.55)
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax.set_xlabel(
        "Newly observed Bandit diagnostics (counts, not confirmed vulnerabilities)"
    )
    fig.suptitle(
        "Selective checking can omit a scanner warning",
        x=0.02,
        ha="left",
        fontsize=14,
        fontweight="bold",
    )
    ax.text(
        0.45,
        3.0,
        "B101 omitted\nwhen Bandit is skipped",
        color="#9a4f15",
        fontsize=9,
        va="center",
    )
    fig.legend(
        *ax.get_legend_handles_labels(), loc="upper right", ncol=2, frameon=False
    )
    style(ax)
    fig.text(
        0.02,
        0.02,
        "B307 appears in the eval case. The assert case deliberately exposes a policy miss. Zero/zero is not 100% detection.",
        fontsize=8.5,
        color="#586b79",
    )
    fig.tight_layout(rect=(0, 0.06, 1, 0.88))
    save(fig, out, "demo_warning_tradeoff")

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.8), sharey=True)
    for ax, metric, label in zip(
        axes,
        ["cc_max", "mi"],
        ["Maximum Radon block CC", "Maintainability Index (0–100)"],
    ):
        for arm, offset in [("before", -0.17), ("after", 0.17)]:
            values = [c["metrics"][arm][metric] for c in cases]
            assert all(math.isfinite(x) for x in values)
            ax.barh(
                [v + offset for v in y],
                values,
                height=0.28,
                color=COLORS[arm],
                label=arm.title(),
                zorder=3,
            )
        ax.set_xlabel(label)
        ax.set_yticks(y, [c["label"] for c in cases])
        style(ax)
        pass  # A shared legend above the axes avoids hiding data.
    fig.legend(
        *axes[0].get_legend_handles_labels(), loc="upper right", ncol=2, frameon=False
    )
    axes[0].invert_yaxis()
    axes[0].xaxis.set_major_locator(MaxNLocator(integer=True))
    axes[1].set_xlim(0, 105)
    fig.suptitle(
        "Metric movement is a description, not a quality verdict",
        x=0.02,
        ha="left",
        fontsize=14,
        fontweight="bold",
    )
    fig.text(
        0.02,
        0.02,
        "The assert adds a CC path. MI can saturate at 100 for zero Halstead volume; it is not a quality percentage.",
        fontsize=8.5,
        color="#586b79",
    )
    fig.tight_layout(rect=(0, 0.06, 1, 0.88))
    save(fig, out, "demo_quality_descriptors")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--demo",
        type=Path,
        help="Refresh snapshot from a complete four-case synthetic comparison demo.",
    )
    parser.add_argument(
        "--snapshot", type=Path, default=ROOT / "docs/assets/data/demo_snapshot.json"
    )
    parser.add_argument("--output", type=Path, default=ROOT / "docs/assets")
    args = parser.parse_args()
    snapshot = (
        freeze(args.demo, args.snapshot)
        if args.demo
        else json.loads(args.snapshot.read_text())
    )
    build(snapshot, args.output)
    print("Generated three PNG/SVG figures from four synthetic cases.")


if __name__ == "__main__":
    main()
