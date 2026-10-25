"""Integrity checks for explicit public-input replay and evidence snapshots."""

import csv
import hashlib
import json
from pathlib import Path

import pytest

from experiments.run_public_patch_pilot import copy_replay, sample_balanced

ROOT = Path(__file__).resolve().parents[1]


def test_balanced_selection_is_deterministic_and_ignores_input_order():
    candidates = [
        dict(repo=repo, instance_id=f"{repo}-{i}")
        for repo in ["a", "b", "c"]
        for i in range(4)
    ]
    a = sample_balanced(candidates, 7, 42)
    b = sample_balanced(list(reversed(candidates)), 7, 42)
    assert a == b
    counts = [sum(x["repo"] == repo for x in a) for repo in ["a", "b", "c"]]
    assert max(counts) - min(counts) == 1


def replay_fixture(tmp_path):
    source = tmp_path / "source"
    folder = source / "inputs/gemini_mini/example-task"
    (folder / "base").mkdir(parents=True)
    content = b"x = 1\n"
    patch = b"diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n"
    (folder / "base/a.py").write_bytes(content)
    (folder / "change.diff").write_bytes(patch)
    cohort = [
        dict(
            run="gemini_mini",
            instance_id="example-task",
            patch_sha256=hashlib.sha256(patch).hexdigest(),
            base_source_sha256={"a.py": hashlib.sha256(content).hexdigest()},
        )
    ]
    (source / "cohort.json").write_text(json.dumps(cohort))
    (source / "protocol.json").write_text("{}")
    (source / "candidate_accounting.csv").write_text(
        "run,instance_id\ngemini_mini,example-task\n"
    )
    out = tmp_path / "out"
    out.mkdir()
    return source, folder, out


def test_replay_checks_hashes_and_copies_declared_inputs_only(tmp_path):
    source, folder, out = replay_fixture(tmp_path)
    (folder / "unrelated.txt").write_text("do not copy")
    copy_replay(source, out)
    assert (out / "inputs/gemini_mini/example-task/base/a.py").read_text() == "x = 1\n"
    assert not (out / "inputs/gemini_mini/example-task/unrelated.txt").exists()


def test_replay_rejects_changed_input(tmp_path):
    source, folder, out = replay_fixture(tmp_path)
    (folder / "base/a.py").write_text("x = 999\n")
    with pytest.raises(ValueError, match="checksum"):
        copy_replay(source, out)


def test_committed_pilot_timing_tables_match_raw_per_patch_values():
    data = ROOT / "docs/assets/data"
    rows = list(csv.DictReader((data / "public_patch_per_case.csv").open()))
    summary = list(csv.DictReader((data / "public_patch_summary.csv").open()))
    for s in summary:
        group = [r for r in rows if r["run"] == s["run"]]
        assert len(group) == int(s["attempted"])
        a = sum(float(r["adaptive_seconds"]) for r in group)
        f = sum(float(r["full_seconds"]) for r in group)
        assert float(s["reduction_of_summed_medians_pct"]) == pytest.approx(
            100 * (1 - a / f)
        )
        assert int(s["full_new_bandit"]) == sum(
            int(r["full_new_bandit"]) for r in group
        )
