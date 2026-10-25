"""Behavioral, evidence-integrity and checkout-preservation tests for the pilot."""

from __future__ import annotations

import json
import subprocess

import pytest

from pilot.checks import (
    compare_findings,
    context,
    diagnostic,
    scanner,
    syntax,
    versions,
)
from pilot.cli import main
from pilot.demo import make_patch
from pilot.report import render
from pilot.snapshots import (
    PatchError,
    changed_lines,
    materialize,
    patch_paths,
    safe_path,
)


def setup_patch(tmp_path, before, after, path="a.py"):
    base = tmp_path / "base"
    base.mkdir()
    target = base / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(before)
    patch = tmp_path / "change.diff"
    patch.write_text(make_patch(path, before, after))
    return base, patch, target


def report_at(tmp_path):
    return json.loads((tmp_path / "out/report.json").read_text())


def test_materialization_and_changed_function_do_not_execute_or_modify(tmp_path):
    marker = tmp_path / "must-not-exist"
    before = "def f(x):\n    return x\n"
    after = f'from pathlib import Path\nPath({str(marker)!r}).write_text("executed")\n\ndef f(x):\n    return x + 1\n'
    base, patch, original = setup_patch(tmp_path, before, after)
    with materialize(base, patch.read_bytes()) as (files, _):
        assert files[0].after == after
        ctx = context(files[0].after, files[0].added_lines)
        assert [f["name"] for f in ctx["changed_functions"]] == ["f"]
        assert syntax(files[0].after, "a.py")["status"] == "completed"
    assert original.read_text() == before
    assert not marker.exists()


def test_new_and_deleted_files(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    patch = b"diff --git a/new.py b/new.py\nnew file mode 100644\n--- /dev/null\n+++ b/new.py\n@@ -0,0 +1 @@\n+x = 1\n"
    with materialize(base, patch) as (files, _):
        assert files[0].before is None
        assert files[0].after == "x = 1\n"
    (base / "old.py").write_text("x = 1\n")
    deletion = b"diff --git a/old.py b/old.py\ndeleted file mode 100644\n--- a/old.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-x = 1\n"
    with materialize(base, deletion) as (files, _):
        assert files[0].before == "x = 1\n"
        assert files[0].after is None
    assert (base / "old.py").exists()
    assert not (base / "new.py").exists()


@pytest.mark.parametrize(
    "path",
    [
        "../../escape.py",
        "/absolute.py",
        ".git/config",
        "a/.GIT/x",
        "C:/x.py",
        "a\\x.py",
        "a\nx.py",
        ".",
        "",
    ],
)
def test_path_escape_rejected(path):
    with pytest.raises(PatchError):
        safe_path(path)


def test_symlinks_and_unsupported_patch_fail_closed(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    outside = tmp_path / "external.py"
    outside.write_text("x = 1\n")
    (base / "a.py").symlink_to(outside)
    patch = make_patch("a.py", "x = 1\n", "x = 2\n").encode()
    with pytest.raises(PatchError, match="Symlink"):
        with materialize(base, patch):
            pass
    with pytest.raises(PatchError, match="unsupported"):
        patch_paths(
            b"diff --git a/a.py b/b.py\nrename from a.py\nrename to b.py\n", base
        )
    assert outside.read_text() == "x = 1\n"


def test_patch_with_space_in_filename(tmp_path):
    base, patch, _ = setup_patch(tmp_path, "x = 1\n", "x = 2\n", path="a file.py")
    with materialize(base, patch.read_bytes()) as (files, _):
        assert files[0].path == "a file.py"
        assert files[0].after == "x = 2\n"


def check(findings):
    return {"status": "completed", "findings": findings}


def test_warning_matching_accounts_for_line_shifts_and_multiplicity():
    before = "def f(x):\n    return eval(x)\n"
    after = "\n" + before + "\ndef g(x):\n    return eval(x)\n"
    _, _, mapping = changed_lines(before, after)
    old = diagnostic("bandit", "B307", "eval warning", before, 2)
    first = diagnostic("bandit", "B307", "eval warning", after, 3)
    extra = diagnostic("bandit", "B307", "eval warning", after, 6)
    result = compare_findings(check([old]), check([first, extra]), mapping)
    assert len(result["matched"]) == 1
    assert len(result["newly_observed"]) == 1
    assert result["matched"][0]["match_method"] == "unchanged-line mapping"


def test_incomplete_check_is_unknown_not_clean():
    result = compare_findings({"status": "unavailable", "findings": []}, check([]), {})
    assert result["status"] == "unknown"
    assert scanner("bandit", "x=1\n", "a.py", {}, 1)["status"] == "unavailable"


def test_timeout_remains_visible(monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("bandit", 0.01)

    monkeypatch.setattr(subprocess, "run", timeout)
    assert (
        scanner("bandit", "x=1\n", "a.py", {"bandit": "test"}, 0.01)["status"]
        == "timeout"
    )


def test_syntax_check_has_actual_compile_semantics():
    # ast.parse accepts this statement; compile must reject it outside a function.
    result = syntax("return 1\n", "a.py")
    assert result["status"] == "completed"
    assert result["findings"][0]["rule"] == "PY_SYNTAX"


def test_git_base_uses_commit_without_resetting_dirty_checkout(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args):
        r = subprocess.run(
            [
                "git",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "commit.gpgsign=false",
                "-c",
                "user.name=Pilot Test",
                "-c",
                "user.email=pilot@example.invalid",
                *args,
            ],
            cwd=repo,
            capture_output=True,
            check=True,
        )
        return r.stdout

    git("init", "-q")
    (repo / "a.py").write_text("x = 1\n")
    git("add", "a.py")
    git("commit", "-qm", "base")
    (repo / "a.py").write_text("x = 99\n")
    patch = make_patch("a.py", "x = 1\n", "x = 2\n").encode()
    status_before = git("status", "--porcelain")
    with materialize(repo, patch, "HEAD") as (files, provenance):
        assert files[0].before == "x = 1\n"
        assert files[0].after == "x = 2\n"
        assert provenance["resolved_commit"]
    assert (repo / "a.py").read_text() == "x = 99\n"
    assert git("status", "--porcelain") == status_before


def test_invalid_patch_generates_failure_report(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    patch = tmp_path / "bad.diff"
    patch.write_text("not a patch")
    assert (
        main(
            [
                "--repo",
                str(base),
                "--patch",
                str(patch),
                "--output",
                str(tmp_path / "out"),
            ]
        )
        == 2
    )
    data = report_at(tmp_path)
    assert "input_error" in data
    assert "analysis" not in data
    assert (tmp_path / "out/report.html").exists()


def test_adaptive_skip_and_ci_exit_are_explicit(tmp_path):
    base, patch, _ = setup_patch(tmp_path, "x = 1\n", "x = 2\n")
    assert (
        main(
            [
                "--repo",
                str(base),
                "--patch",
                str(patch),
                "--require-complete",
                "--output",
                str(tmp_path / "out"),
            ]
        )
        == 3
    )
    data = report_at(tmp_path)
    assert data["analysis"]["state"] == "incomplete_evidence"
    assert any(
        x["tool"] == "bandit" and x["status"] == "skipped"
        for x in data["analysis"]["incomplete_checks"]
    )


def test_real_scanners_find_eval_and_preserve_source(tmp_path):
    if not all(versions().get(x) for x in ["ruff", "bandit", "radon"]):
        pytest.skip("Pilot scanner dependencies not installed")
    before = "def f(x):\n    return int(x)\n"
    base, patch, original = setup_patch(
        tmp_path, before, "def f(x):\n    return eval(x)  # nosec\n"
    )
    assert (
        main(
            [
                "--repo",
                str(base),
                "--patch",
                str(patch),
                "--fail-on-new",
                "--output",
                str(tmp_path / "out"),
            ]
        )
        == 1
    )
    data = report_at(tmp_path)
    assert any(f["rule"] == "B307" for f in data["analysis"]["newly_observed"])
    assert original.read_text() == before


def test_comparison_exposes_adaptive_miss(tmp_path):
    if not all(versions().get(x) for x in ["ruff", "bandit", "radon"]):
        pytest.skip("Pilot scanner dependencies not installed")
    base, patch, _ = setup_patch(
        tmp_path,
        "def f(x):\n    return x\n",
        "def f(x):\n    assert x > 0\n    return x\n",
    )
    assert (
        main(
            [
                "--repo",
                str(base),
                "--patch",
                str(patch),
                "--mode",
                "compare",
                "--repeats",
                "1",
                "--output",
                str(tmp_path / "out"),
            ]
        )
        == 0
    )
    data = report_at(tmp_path)
    d = data["comparison"]["diagnostic_comparison"]
    assert data["comparison"]["full_reference"]["mode"] == "full"
    assert any(f["rule"] == "B101" for f in d["not_observed_by_adaptive"])
    assert d["fraction"] == 0


def test_html_escapes_input_error():
    data = {
        "created_at_utc": "test",
        "tool_versions": {},
        "input_error": "<script>alert(1)</script>",
    }
    html = render(data)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_comparison_ci_failure_includes_full_mode_warning(tmp_path):
    if not all(versions().get(x) for x in ["ruff", "bandit", "radon"]):
        pytest.skip("Pilot scanner dependencies not installed")
    base, patch, _ = setup_patch(
        tmp_path,
        "def f(x):\n    return x\n",
        "def f(x):\n    assert x > 0\n    return x\n",
    )
    assert (
        main(
            [
                "--repo",
                str(base),
                "--patch",
                str(patch),
                "--mode",
                "compare",
                "--repeats",
                "1",
                "--fail-on-new",
                "--output",
                str(tmp_path / "out"),
            ]
        )
        == 1
    )


def test_existing_output_is_never_overwritten(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    original = out / "report.json"
    original.write_text("keep this evidence")
    base, patch, _ = setup_patch(tmp_path, "x=1\n", "x=2\n")
    assert main(["--repo", str(base), "--patch", str(patch), "--output", str(out)]) == 2
    assert original.read_text() == "keep this evidence"
