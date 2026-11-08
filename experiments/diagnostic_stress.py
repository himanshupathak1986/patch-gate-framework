"""Controlled Bandit scanner/selection stress cases for PATCH-GATE.

Runs the existing analysis engine directly on before/after snapshots. It does not
exercise patch-file parsing, and does not claim vulnerability detection.
"""
from __future__ import annotations

from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys

from pilot.checks import analyze, versions
from pilot.snapshots import Snapshot, changed_lines

CASES = [
    ("eval_new", "def f(x):\n    return int(x)\n", "def f(x):\n    return eval(x)\n"),
    ("exec_new", "def f(x):\n    return x\n", "def f(x):\n    exec(x)\n    return x\n"),
    ("assert_small", "def f(x):\n    return x\n", "def f(x):\n    assert x\n    return x\n"),
    ("hardcoded_password", "password = None\n", 'password = "supersecretpassword123"\n'),
    ("pickle_loads", "def f(x):\n    return x\n", "import pickle\ndef f(x):\n    return pickle.loads(x)\n"),
    ("subprocess_shell", "def f():\n    return 1\n", 'import subprocess\ndef f():\n    return subprocess.call("ls", shell=True)\n'),
    ("tempfile_mktemp", "def f():\n    return 1\n", "import tempfile\ndef f():\n    return tempfile.mktemp()\n"),
    ("hashlib_md5", "def f(x):\n    return x\n", "import hashlib\ndef f(x):\n    return hashlib.md5(x).hexdigest()\n"),
    ("requests_verify_false", "def f():\n    return 1\n", 'import requests\ndef f():\n    return requests.get("https://example.org", verify=False)\n'),
    ("yaml_load", "def f(x):\n    return x\n", "import yaml\ndef f(x):\n    return yaml.load(x)\n"),
    ("shift_existing", "def f(x):\n    return eval(x)\n", '"""Docstring."""\n\ndef f(x):\n    return eval(x)\n'),
    ("duplicate_warning", "def f(x):\n    return eval(x)\n", "def f(x):\n    return eval(x)\n\ndef g(x):\n    return eval(x)\n"),
    ("benign_docstring", "def f(x):\n    return x\n", 'def f(x):\n    """Return x."""\n    return x\n'),
]


def finding_key(item):
    return tuple(item.get(k) for k in ("path", "tool", "rule", "message", "severity", "confidence", "snippet"))


def new_bandit(result):
    return [f for f in result["newly_observed"] if f["tool"] == "bandit"]


def main():
    v = versions()
    if not v.get("bandit"):
        raise SystemExit("Bandit is unavailable. Install requirements-pilot-dev.txt first.")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    root = Path("outputs") / f"reviewer-diagnostic-stress-fixed-{stamp}"
    rows = []
    for case, before, after in CASES:
        removed, added, mapping = changed_lines(before, after)
        snap = Snapshot(
            path="example.py", before=before, after=after,
            before_sha256=hashlib.sha256(before.encode()).hexdigest(),
            after_sha256=hashlib.sha256(after.encode()).hexdigest(),
            removed_lines=removed, added_lines=added, line_map=mapping,
        )
        full = analyze([snap], "full", v, 30)
        adaptive = analyze([snap], "adaptive", v, 30)
        for name, result in (("full", full), ("adaptive", adaptive)):
            checks = [r[side]["bandit"]["status"]
                      for r in result["files"] for side in ("before", "after")]
            if any(s not in ("completed", "not_applicable", "skipped") for s in checks):
                raise SystemExit(f"{case} {name}: Bandit did not complete: {checks}")
            if name == "full" and "skipped" in checks:
                raise SystemExit(f"{case}: full mode unexpectedly skipped Bandit: {checks}")
        fa, aa = new_bandit(full), new_bandit(adaptive)
        missing = Counter(map(finding_key, fa)) - Counter(map(finding_key, aa))
        missed = sum(missing.values())
        skipped = sum(
            c["tool"] == "bandit" and c["status"] == "skipped"
            for c in adaptive["incomplete_checks"]
        )
        row = dict(
            case=case, adaptive_new_bandit=len(aa), full_new_bandit=len(fa),
            missed_bandit=missed,
            full_bandit_rules=";".join(sorted({f["rule"] for f in fa})),
            adaptive_skipped_bandit_snapshots=skipped,
        )
        rows.append(row)
        out = root / "reports" / case
        out.mkdir(parents=True, exist_ok=True)
        (out / "report.json").write_text(json.dumps(
            {"role":"constructed scanner stress case, not real vulnerability evidence",
             "case":case,"before":before,"after":after,"full":full,"adaptive":adaptive}, indent=2), encoding="utf-8")
        print(f"{case}: full={len(fa)} adaptive={len(aa)} missed={missed} skipped_snapshots={skipped}")
    path = Path("paper/tables/reviewer_diagnostic_stress.csv")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    try:
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        revision = "unavailable"
    manifest = dict(
        status="13 constructed cases using in-memory snapshots; patch-file intake not evaluated",
        created_at_utc=stamp, git_revision=revision,
        python=sys.version, platform=platform.platform(), versions=v,
        case_count=len(rows), results=str(path),
    )
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Saved {path}; detailed reports in {root}")
    print("Do not interpret scanner messages as confirmed vulnerabilities or real-world recall.")

if __name__ == "__main__":
    main()
