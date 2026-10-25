"""Run a new static-check pilot on explicitly supplied public artifact caches.

No legacy measurements/results are imported. Inputs are public predictions, benchmark
metadata, recorded verdicts, and source text. Candidate code/tests never execute.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.parse import quote

from pilot.snapshots import PatchError, patch_paths, read_worktree, safe_path

ROOT = Path(__file__).resolve().parents[1]
RUNS = {
    "gemini_mini": ("original_predictions.jsonl", "Gemini 3.5 Flash / mini-SWE-agent"),
    "agentless_gpt4o": ("second_predictions.jsonl", "Agentless-1.5 / GPT-4o"),
}
TEST_PATH = re.compile(
    r"(^|/)(tests?|testing)(/|_|\.|$)|(^|/)test_.*\.py$|_test\.py$", re.I
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_csv(path, rows):
    if not rows:
        path.write_text("")
        return
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def sample_balanced(candidates, n, seed):
    groups = {}
    for c in candidates:
        groups.setdefault(c["repo"], []).append(c)
    for values in groups.values():
        values.sort(
            key=lambda c: hashlib.sha256(
                f"{seed}:{c['instance_id']}".encode()
            ).hexdigest()
        )
    selected = []
    while len(selected) < n and any(groups.values()):
        for repo in sorted(groups):
            if groups[repo] and len(selected) < n:
                selected.append(groups[repo].pop(0))
    return selected


def prepare(artifacts, original_verdicts, out, per_run, seed):
    gold_path = artifacts / "swebench_verified_gold.json"
    gold = {r["instance_id"]: r for r in json.loads(gold_path.read_text())}
    all_accounting, cohort, inputs = [], [], {}
    input_paths = [
        gold_path,
        original_verdicts,
        artifacts / "second_results.json",
        artifacts / "original_predictions.jsonl",
        artifacts / "second_predictions.jsonl",
    ]
    for p in input_paths:
        inputs[p.name] = sha(p)
    for run, (pred_file, label) in RUNS.items():
        predictions = {
            r["instance_id"]: r
            for r in map(json.loads, (artifacts / pred_file).read_text().splitlines())
        }
        verdict_path = (
            original_verdicts
            if run == "gemini_mini"
            else artifacts / "second_results.json"
        )
        resolved = json.loads(verdict_path.read_text())["resolved"]
        candidates = []
        for iid in sorted(resolved):
            status, detail = "eligible", ""
            try:
                g = gold[iid]
                patch = predictions[iid]["model_patch"]
                selected_chunks, source = [], {}
                for chunk in re.split(r"(?=^diff --git )", patch, flags=re.M):
                    if not chunk.startswith("diff --git "):
                        continue
                    paths = patch_paths(chunk.encode(), ROOT)
                    if len(paths) != 1:
                        raise ValueError("Ambiguous diff block")
                    path = paths[0]
                    if not path.endswith(".py") or TEST_PATH.search(path):
                        continue
                    url = f"https://raw.githubusercontent.com/{g['repo']}/{g['base_commit']}/{quote(path, safe='/')}"
                    cached = (
                        artifacts / "sources" / hashlib.sha256(url.encode()).hexdigest()
                    )
                    if cached.is_file():
                        source[path] = cached.read_bytes()
                    elif "--- /dev/null" in chunk:
                        source[path] = None
                    else:
                        raise ValueError(
                            "Source text unavailable in the explicit cache: " + path
                        )
                    selected_chunks.append(chunk)
                if not selected_chunks:
                    raise ValueError("No supported production Python text changes")
                candidates.append(
                    dict(
                        run=run,
                        label=label,
                        instance_id=iid,
                        repo=g["repo"],
                        base_commit=g["base_commit"],
                        patch="".join(selected_chunks),
                        sources=source,
                    )
                )
            except (KeyError, ValueError, PatchError) as exc:
                status, detail = "input_exclusion", str(exc)
            all_accounting.append(
                dict(
                    run=run,
                    instance_id=iid,
                    eligibility=status,
                    detail=detail,
                    selected=False,
                )
            )
        selected = sample_balanced(candidates, per_run, seed)
        ids = {c["instance_id"] for c in selected}
        for row in all_accounting:
            if row["run"] == run:
                row["selected"] = row["instance_id"] in ids
        for c in selected:
            folder = out / "inputs" / run / c["instance_id"]
            base = folder / "base"
            base.mkdir(parents=True)
            file_hashes = {}
            for path, content in c["sources"].items():
                file_hashes[path] = (
                    hashlib.sha256(content).hexdigest() if content is not None else None
                )
                if content is not None:
                    p = base / path
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_bytes(content)
            (folder / "change.diff").write_text(c["patch"])
            cohort.append(
                dict(
                    run=run,
                    label=c["label"],
                    instance_id=c["instance_id"],
                    repo=c["repo"],
                    base_commit=c["base_commit"],
                    patch_sha256=sha(folder / "change.diff"),
                    base_source_sha256=file_hashes,
                )
            )
    write_csv(out / "candidate_accounting.csv", all_accounting)
    (out / "cohort.json").write_text(json.dumps(cohort, indent=2))
    (out / "protocol.json").write_text(
        json.dumps(
            dict(
                role="New exploratory static-check pilot; no prior statistical results imported",
                seed=seed,
                requested_per_run=per_run,
                input_sha256=inputs,
                sampling="Repository round-robin; candidates within repository ordered by SHA256(seed:instance_id); selection before check outcomes",
                eligibility="Published resolved verdict, available prediction/metadata/base source, supported production-Python diff blocks",
                scope="Production Python diff subsets only; tests and non-Python changes excluded; historical benchmark verdicts not rerun",
                outcomes="Local static-check timing and scanner output, not independently confirmed bugs/vulnerabilities",
                dependence="Two runs share benchmark tasks; rows across runs are not independent problems",
                external_inputs="Caller must explicitly supply artifact cache and original verdict file; no automatic lookup or network access",
            ),
            indent=2,
        )
    )
    return cohort


def evaluate(cohort, out, repeats):
    rows = []
    for i, c in enumerate(cohort, 1):
        folder = out / "inputs" / c["run"] / c["instance_id"]
        report = out / "reports" / c["run"] / c["instance_id"]
        cmd = [
            sys.executable,
            str(ROOT / "patch_gate.py"),
            "--repo",
            str(folder / "base"),
            "--patch",
            str(folder / "change.diff"),
            "--mode",
            "compare",
            "--repeats",
            str(repeats),
            "--output",
            str(report),
        ]
        p = subprocess.run(
            cmd, capture_output=True, text=True, timeout=600, check=False
        )
        (folder / "command.log").write_text(p.stdout + "\n" + p.stderr)
        row = dict(
            run=c["run"],
            instance_id=c["instance_id"],
            repo=c["repo"],
            base_commit=c["base_commit"],
            exit_code=p.returncode,
            state="input_or_execution_failure",
            python_files=None,
            adaptive_seconds=None,
            full_seconds=None,
            time_reduction_pct=None,
            adaptive_new_all=None,
            full_new_all=None,
            adaptive_new_bandit=None,
            full_new_bandit=None,
            full_incomplete_snapshots=None,
            adaptive_skipped_bandit_snapshots=None,
            baseline_complete=False,
            diagnostics_stable=False,
        )
        if (report / "report.json").exists():
            d = json.loads((report / "report.json").read_text())
            if "comparison" in d:
                a = d["analysis"]
                comp = d["comparison"]
                f = comp["full_reference"]
                row.update(
                    state=a["state"],
                    python_files=len(a["files"]),
                    adaptive_seconds=comp["timings"]["adaptive"]["median_seconds"],
                    full_seconds=comp["timings"]["full"]["median_seconds"],
                    time_reduction_pct=comp["time_reduction_pct"],
                    adaptive_new_all=len(a["newly_observed"]),
                    full_new_all=len(f["newly_observed"]),
                    adaptive_new_bandit=sum(
                        x["tool"] == "bandit" for x in a["newly_observed"]
                    ),
                    full_new_bandit=sum(
                        x["tool"] == "bandit" for x in f["newly_observed"]
                    ),
                    full_incomplete_snapshots=len(f["incomplete_checks"]),
                    adaptive_skipped_bandit_snapshots=sum(
                        x["tool"] == "bandit" and x["status"] == "skipped"
                        for x in a["incomplete_checks"]
                    ),
                    baseline_complete=not f["incomplete_checks"] and bool(f["files"]),
                    diagnostics_stable=all(
                        comp["new_diagnostics_stable_across_repetitions"].values()
                    ),
                )
        rows.append(row)
        print(
            f"{i}/{len(cohort)} {c['run']} {c['instance_id']} {row['state']}",
            flush=True,
        )
        write_csv(out / "per_patch.csv", rows)
    return rows


def copy_replay(source, out):
    """Verify and copy only declared source/patch inputs; never follow source symlinks."""
    cohort = json.loads((source / "cohort.json").read_text())
    if not isinstance(cohort, list) or not 1 <= len(cohort) <= 200:
        raise ValueError("Replay cohort must contain 1–200 declared patch subsets.")
    staged = []
    seen = set()
    for c in cohort:
        run, iid = c["run"], c["instance_id"]
        if (
            run not in RUNS
            or not re.fullmatch(r"[A-Za-z0-9_.-]+", iid)
            or iid in [".", ".."]
        ):
            raise ValueError("Unsupported replay run or task identifier.")
        if (run, iid) in seen:
            raise ValueError("Duplicate replay task.")
        seen.add((run, iid))
        folder = source / "inputs" / run / iid
        patch = read_worktree(folder, "change.diff")
        if patch is None or hashlib.sha256(patch).hexdigest() != c["patch_sha256"]:
            raise ValueError("Replay patch checksum differs: " + iid)
        if len(c["base_source_sha256"]) > 200:
            raise ValueError("Replay task exceeds 200 source files.")
        contents = {}
        for rel, expected in c["base_source_sha256"].items():
            rel = safe_path(rel)
            content = read_worktree(folder / "base", rel)
            actual = (
                hashlib.sha256(content).hexdigest() if content is not None else None
            )
            if actual != expected:
                raise ValueError("Replay source checksum differs: " + iid + ":" + rel)
            contents[rel] = content
        staged.append((run, iid, patch, contents))
    for run, iid, patch, contents in staged:
        folder = out / "inputs" / run / iid
        (folder / "base").mkdir(parents=True)
        (folder / "change.diff").write_bytes(patch)
        for rel, content in contents.items():
            if content is not None:
                path = folder / "base" / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
    for name in ["cohort.json", "protocol.json", "candidate_accounting.csv"]:
        shutil.copy2(source / name, out / name)
    return cohort


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path)
    parser.add_argument(
        "--replay",
        type=Path,
        help="Replay a preserved experiment directory without upstream caches or downloads.",
    )
    parser.add_argument("--original-verdicts", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--per-run", type=int, default=30)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if not 1 <= args.per_run <= 100 or not 3 <= args.repeats <= 10:
        parser.error("Use 1–100 cases per run and 3–10 measured repeats.")
    out = args.output.resolve()
    if out.exists() and any(out.iterdir()):
        parser.error("Output must be new or empty; preserve earlier runs.")
    out.mkdir(parents=True, exist_ok=True)
    if args.replay:
        cohort = copy_replay(args.replay.resolve(), out)
    else:
        if not args.artifacts or not args.original_verdicts:
            parser.error("Supply --artifacts and --original-verdicts, or --replay.")
        cohort = prepare(
            args.artifacts.resolve(),
            args.original_verdicts.resolve(),
            out,
            args.per_run,
            args.seed,
        )
    print(
        "Selected",
        len(cohort),
        "public patch subsets before scanner outcomes.",
        flush=True,
    )
    rows = evaluate(cohort, out, args.repeats)
    print("Completed", len(rows), "attempts.", flush=True)


if __name__ == "__main__":
    main()
