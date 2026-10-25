"""Static checks only. Candidate modules are parsed, never imported or executed."""

from __future__ import annotations

import ast
from collections import defaultdict, deque
import importlib.metadata
import json
import subprocess
import sys
import tempfile
import time
from typing import Any

from .snapshots import Snapshot

RULESET = "E4,E7,E9,F"
SENSITIVE_MODULES = {
    "subprocess": "process execution",
    "pickle": "deserialization",
    "marshal": "deserialization",
    "yaml": "deserialization",
    "sqlite3": "database queries",
    "psycopg2": "database queries",
    "pymysql": "database queries",
    "requests": "network access",
    "urllib": "network access",
    "socket": "network access",
    "ssl": "TLS configuration",
    "hashlib": "cryptographic operations",
    "tarfile": "archive extraction",
    "zipfile": "archive extraction",
    "shutil": "file operations",
}
SENSITIVE_CALLS = {
    "eval": "dynamic execution",
    "exec": "dynamic execution",
    "compile": "dynamic execution",
    "__import__": "dynamic imports",
    "open": "file operations",
    "system": "process execution",
    "popen": "process execution",
    "Popen": "process execution",
    "execute": "database queries",
    "executemany": "database queries",
    "executescript": "database queries",
    "extractall": "archive extraction",
    "load": "deserialization",
    "loads": "deserialization",
    "unlink": "file operations",
    "remove": "file operations",
    "rmdir": "file operations",
    "write_text": "file operations",
    "write_bytes": "file operations",
}


def versions() -> dict[str, str | None]:
    out: dict[str, str | None] = {"python": sys.version.split()[0]}
    for name in ["ruff", "bandit", "radon"]:
        try:
            out[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            out[name] = None
    return out


def result(
    tool: str, status: str, started: float, *, findings=None, detail="", **kwargs
):
    return {
        "tool": tool,
        "status": status,
        "seconds": time.perf_counter() - started,
        "findings": findings or [],
        "detail": detail,
        **kwargs,
    }


def diagnostic(
    tool: str,
    rule: str,
    message: str,
    source: str,
    line: int,
    end_line: int | None = None,
    severity="WARNING",
    confidence="UNSPECIFIED",
):
    lines = source.splitlines()
    end_line = max(line, end_line or line)
    return {
        "tool": tool,
        "rule": rule,
        "message": message,
        "line": line,
        "end_line": end_line,
        "severity": severity,
        "confidence": confidence,
        "snippet": "\n".join(lines[max(0, line - 1) : end_line]),
    }


def syntax(source: str | None, path: str) -> dict:
    start = time.perf_counter()
    if source is None:
        return result(
            "syntax", "not_applicable", start, detail="File absent in this snapshot."
        )
    try:
        # Compilation creates a code object but does not execute it.
        compile(source, path, "exec", dont_inherit=True)
        return result("syntax", "completed", start)
    except (SyntaxError, ValueError, TypeError) as exc:
        line = getattr(exc, "lineno", None) or 1
        return result(
            "syntax",
            "completed",
            start,
            findings=[
                diagnostic(
                    "syntax",
                    "PY_SYNTAX",
                    str(exc),
                    source,
                    line,
                    severity="ERROR",
                    confidence="PARSER",
                )
            ],
        )
    except Exception as exc:
        return result("syntax", "error", start, detail=f"{type(exc).__name__}: {exc}")


def function_inventory(tree: ast.AST, lines: set[int]) -> list[dict]:
    found = []

    def walk(node: ast.AST, parents: list[str]):
        is_function = isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        is_scope = is_function or isinstance(node, ast.ClassDef)
        if is_function:
            start = min([node.lineno] + [d.lineno for d in node.decorator_list])
            end = node.end_lineno or node.lineno
            if any(start <= line <= end for line in lines):
                found.append(
                    {
                        "name": ".".join([*parents, node.name]),
                        "start": start,
                        "end": end,
                    }
                )
        next_parents = [*parents, node.name] if is_scope else parents
        for child in ast.iter_child_nodes(node):
            walk(child, next_parents)

    walk(tree, [])
    return found


def nesting(tree: ast.AST) -> int:
    kinds = (
        ast.If,
        ast.For,
        ast.AsyncFor,
        ast.While,
        ast.Try,
        ast.With,
        ast.AsyncWith,
        ast.Match,
    )

    def walk(node: ast.AST, depth: int):
        level = depth + int(isinstance(node, kinds))
        return max([level, *(walk(c, level) for c in ast.iter_child_nodes(node))])

    return walk(tree, 0)


def context(source: str | None, changed: set[int]) -> dict:
    if source is None:
        return {"categories": [], "parse_error": None, "changed_functions": []}
    try:
        tree = ast.parse(source)
        categories = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for name in node.names:
                    root = name.name.split(".")[0]
                    if root in SENSITIVE_MODULES:
                        categories.add(SENSITIVE_MODULES[root])
            if isinstance(node, ast.ImportFrom):
                root = (node.module or "").split(".")[0]
                if root in SENSITIVE_MODULES:
                    categories.add(SENSITIVE_MODULES[root])
            if isinstance(node, ast.Call):
                name = (
                    node.func.id
                    if isinstance(node.func, ast.Name)
                    else node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else ""
                )
                if name in SENSITIVE_CALLS:
                    categories.add(SENSITIVE_CALLS[name])
        return {
            "categories": sorted(categories),
            "parse_error": None,
            "changed_functions": function_inventory(tree, changed),
        }
    except Exception as exc:
        return {
            "categories": [],
            "parse_error": f"{type(exc).__name__}: {exc}",
            "changed_functions": [],
        }


def quality(source: str | None) -> dict:
    start = time.perf_counter()
    if source is None:
        return result(
            "quality",
            "not_applicable",
            start,
            detail="File absent in this snapshot.",
            metrics=None,
        )
    try:
        from radon.complexity import cc_visit
        from radon.metrics import h_visit, mi_visit
    except ImportError:
        return result(
            "quality",
            "unavailable",
            start,
            detail="Radon is not installed.",
            metrics=None,
        )
    try:
        tree = ast.parse(source)
        cc = [b.complexity for b in cc_visit(source)]
        functions = [
            n
            for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        lengths = [(n.end_lineno or n.lineno) - n.lineno + 1 for n in functions]
        metrics = {
            "lines": len(source.splitlines()),
            "function_count": len(functions),
            "cc_mean": sum(cc) / len(cc) if cc else 0,
            "cc_max": max(cc, default=0),
            "mi": mi_visit(source, multi=True),
            "halstead_volume": h_visit(source).total.volume,
            "max_nesting": nesting(tree),
            "max_function_lines": max(lengths, default=0),
        }
        return result(
            "quality",
            "completed",
            start,
            metrics=metrics,
            detail="Descriptive measurements. Increases are not automatically defects.",
        )
    except Exception as exc:
        return result(
            "quality",
            "error",
            start,
            detail=f"{type(exc).__name__}: {exc}",
            metrics=None,
        )


def scanner(
    tool: str,
    source: str | None,
    path: str,
    available: dict,
    timeout: float,
    selected=True,
    reason="",
) -> dict:
    start = time.perf_counter()
    if source is None:
        return result(
            tool, "not_applicable", start, detail="File absent in this snapshot."
        )
    if not selected:
        return result(tool, "skipped", start, detail=reason)
    if not available.get(tool):
        return result(
            tool,
            "unavailable",
            start,
            detail=f"{tool} is not installed in this Python environment.",
        )
    if tool == "ruff":
        args = [
            sys.executable,
            "-I",
            "-m",
            "ruff",
            "check",
            "--isolated",
            "--no-cache",
            "--ignore-noqa",
            "--select",
            RULESET,
            "--output-format",
            "json",
            "--stdin-filename",
            path,
            "-",
        ]
    else:
        args = [
            sys.executable,
            "-I",
            "-m",
            "bandit",
            "--ignore-nosec",
            "--format",
            "json",
            "--quiet",
            "-",
        ]
    try:
        # Run in an empty directory: target project config cannot change these scanner settings.
        with tempfile.TemporaryDirectory(prefix="patch-gate-check-") as td:
            proc = subprocess.run(
                args,
                input=source,
                text=True,
                capture_output=True,
                cwd=td,
                timeout=timeout,
            )
        if proc.returncode not in (0, 1):
            return result(
                tool,
                "error",
                start,
                detail=f"Exit {proc.returncode}: {proc.stderr[:1500]}",
                command=args,
            )
        payload = json.loads(proc.stdout)
        errors = [] if tool == "ruff" else payload.get("errors", [])
        if errors:
            return result(
                tool, "error", start, detail=json.dumps(errors)[:1500], command=args
            )
        findings = []
        records = payload if tool == "ruff" else payload["results"]
        for row in records:
            if tool == "ruff":
                findings.append(
                    diagnostic(
                        "ruff",
                        row.get("code") or "RUFF_PARSE",
                        row["message"],
                        source,
                        row["location"]["row"],
                        row["end_location"]["row"],
                    )
                )
            else:
                findings.append(
                    diagnostic(
                        "bandit",
                        row["test_id"],
                        row["issue_text"],
                        source,
                        row["line_number"],
                        max(row.get("line_range") or [row["line_number"]]),
                        row["issue_severity"],
                        row["issue_confidence"],
                    )
                )
        return result(tool, "completed", start, findings=findings, command=args)
    except subprocess.TimeoutExpired:
        return result(
            tool,
            "timeout",
            start,
            detail=f"Exceeded the {timeout:g}-second per-check limit.",
            command=args,
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return result(
            tool, "error", start, detail=f"{type(exc).__name__}: {exc}", command=args
        )


def signature(finding: dict) -> tuple:
    return (
        finding["tool"],
        finding["rule"],
        finding["message"],
        finding["severity"],
        finding["confidence"],
        finding["snippet"].strip(),
    )


def compare_findings(before: dict, after: dict, line_map: dict[int, int]) -> dict:
    """One-to-one diagnostic matching; line-shifted duplicates do not become new warnings.

    Content matching is explicitly approximate: it cannot prove unchanged semantics.
    Incomplete checks have unknown differences rather than zero new findings.
    """
    usable = {"completed", "not_applicable"}
    if before["status"] not in usable or after["status"] not in usable:
        return {
            "status": "unknown",
            "newly_observed": [],
            "matched": [],
            "no_longer_observed": [],
            "detail": "At least one snapshot was skipped, unavailable or could not be checked.",
        }
    old = before["findings"]
    new = after["findings"]
    candidates = defaultdict(deque)
    for i, f in enumerate(old):
        candidates[signature(f)].append(i)
    used = set()
    matched, introduced = [], []
    for f in new:
        queue = candidates[signature(f)]
        mapped = next(
            (i for i in queue if line_map.get(old[i]["line"]) == f["line"]), None
        )
        if mapped is not None:
            queue.remove(mapped)
            method = "unchanged-line mapping"
        elif queue:
            mapped = queue.popleft()
            method = "same diagnostic and source text; approximate relocation match"
        else:
            introduced.append(f)
            continue
        used.add(mapped)
        matched.append({"before": old[mapped], "after": f, "match_method": method})
    return {
        "status": "compared",
        "newly_observed": introduced,
        "matched": matched,
        "no_longer_observed": [f for i, f in enumerate(old) if i not in used],
        "detail": "Diagnostic attribution only. Matching does not establish unchanged behavior or vulnerability status.",
    }


def select_bandit(
    snapshot: Snapshot, before_context: dict, after_context: dict, mode: str
) -> tuple[bool, list[str]]:
    reasons = []
    if mode == "full":
        return True, ["Full mode: scan every changed Python file."]
    categories = sorted(
        set(before_context["categories"]) | set(after_context["categories"])
    )
    if categories:
        reasons.append(
            "Sensitive context anywhere in the before/after file: "
            + ", ".join(categories)
        )
    churn = len(snapshot.added_lines) + len(snapshot.removed_lines)
    if churn >= 20:
        reasons.append(
            f"Changed-line churn {churn} meets the illustrative 20-line escalation rule."
        )
    if before_context["parse_error"] or after_context["parse_error"]:
        reasons.append(
            "Could not inspect all source context; escalate rather than assume low risk."
        )
    if reasons:
        return True, reasons
    return False, [
        "Small change without recognized sensitive context; Bandit deliberately skipped. This rule can miss warnings."
    ]


def analyze(
    snapshots: list[Snapshot], mode: str, tools: dict, timeout: float
) -> dict[str, Any]:
    start = time.perf_counter()
    records = []
    for s in snapshots:
        file_start = time.perf_counter()
        bctx, actx = context(s.before, s.removed_lines), context(s.after, s.added_lines)
        selected, reasons = select_bandit(s, bctx, actx, mode)
        before = {"syntax": syntax(s.before, s.path), "quality": quality(s.before)}
        after = {"syntax": syntax(s.after, s.path), "quality": quality(s.after)}
        for name in ["ruff", "bandit"]:
            for arm, source in [(before, s.before), (after, s.after)]:
                arm[name] = scanner(
                    name,
                    source,
                    s.path,
                    tools,
                    timeout,
                    selected=selected if name == "bandit" else True,
                    reason=" ".join(reasons),
                )
        differences = {
            name: compare_findings(before[name], after[name], s.line_map)
            for name in ["syntax", "ruff", "bandit"]
        }
        metrics_before, metrics_after = (
            before["quality"].get("metrics"),
            after["quality"].get("metrics"),
        )
        delta = (
            {k: metrics_after[k] - metrics_before[k] for k in metrics_before}
            if metrics_before and metrics_after
            else None
        )
        records.append(
            {
                "path": s.path,
                "change": "added"
                if s.before is None
                else "deleted"
                if s.after is None
                else "modified",
                "before_sha256": s.before_sha256,
                "after_sha256": s.after_sha256,
                "added_lines": sorted(s.added_lines),
                "removed_lines": sorted(s.removed_lines),
                "before_context": bctx,
                "after_context": actx,
                "bandit_selected": selected,
                "selection_reasons": reasons,
                "before": before,
                "after": after,
                "differences": differences,
                "metric_delta": delta,
                "seconds": time.perf_counter() - file_start,
            }
        )
    new = [
        dict(f, path=r["path"])
        for r in records
        for d in r["differences"].values()
        for f in d["newly_observed"]
    ]
    incomplete = [
        dict(
            path=r["path"],
            snapshot=side,
            tool=tool,
            status=c["status"],
            detail=c["detail"],
        )
        for r in records
        for side in ["before", "after"]
        for tool, c in r[side].items()
        if c["status"] not in ["completed", "not_applicable"]
    ]
    syntax_issues = [
        dict(path=r["path"], **f)
        for r in records
        for f in r["after"]["syntax"]["findings"]
    ]
    state = (
        "needs_attention"
        if new or syntax_issues
        else "incomplete_evidence"
        if incomplete or not records
        else "no_new_static_findings"
    )
    return {
        "mode": mode,
        "seconds": time.perf_counter() - start,
        "files": records,
        "newly_observed": new,
        "incomplete_checks": incomplete,
        "after_syntax_issues": syntax_issues,
        "state": state,
        "summary": {
            "python_files": len(records),
            "new_static_findings": len(new),
            "incomplete_check_snapshots": len(incomplete),
            "bandit_files_selected": sum(r["bandit_selected"] for r in records),
        },
    }
