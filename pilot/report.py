"""Self-contained, escaped HTML evidence reports with no external resources."""

from __future__ import annotations

from html import escape as esc
import json

CSS = """
:root{color-scheme:light;--ink:#182b3c;--muted:#536778;--line:#d8e1e7;--paper:#fff;--bg:#eef3f6;--blue:#135c83;--amber:#835515}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
main{max-width:1200px;margin:auto;padding:40px 28px 72px}header{border-top:5px solid var(--blue);padding:26px 30px;background:#102e44;color:white;border-radius:10px}
.brand{font-size:13px;letter-spacing:.18em;color:#a9d9ed;font-weight:700}h1{font-size:34px;line-height:1.18;margin:12px 0}h2{font-size:23px;margin:0 0 12px}h3{font-size:17px;margin:16px 0 8px}
header p{max-width:850px;color:#dae6ed;margin:8px 0}.pill{display:inline-block;padding:4px 10px;border-radius:5px;background:#e9f1f6;color:#21445b;font-size:12px;font-weight:650}
header .pill{background:#fae6bd;color:#5e400e}section{margin-top:22px;padding:26px 28px;background:var(--paper);border:1px solid var(--line);border-radius:10px}
p{margin:8px 0 14px}.muted,small{color:var(--muted)}.note{border-left:4px solid #d7a34c;padding:12px 16px;background:#fff8e8;margin:16px 0}
.cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin-top:22px}.card{background:#fff;border:1px solid var(--line);border-radius:8px;padding:18px}.number{font-size:30px;font-weight:700;color:var(--blue)}.label{font-size:13px;color:var(--muted)}
.table-wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:10px 12px;text-align:left;vertical-align:top;border-bottom:1px solid var(--line)}th{background:#f3f7f9;color:#345269;font-weight:650}td code{overflow-wrap:anywhere}tr:last-child td{border-bottom:0}
code,pre{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px}pre{background:#f2f5f7;padding:12px;white-space:pre-wrap;overflow-wrap:anywhere;border-radius:5px;max-height:300px;overflow:auto}
details{margin:12px 0;border:1px solid var(--line);border-radius:6px;padding:12px 16px}summary{cursor:pointer;font-weight:650;overflow-wrap:anywhere}.meta{display:grid;grid-template-columns:160px 1fr;gap:8px 16px}.meta div{overflow-wrap:anywhere}.warning{color:#835515}.bad{color:#993b2d}.good{color:#24566b}ul{padding-left:22px}footer{margin:26px 4px;color:var(--muted);font-size:12px}
@media(max-width:760px){main{padding:16px 12px 40px}section,header{padding:20px}.cards{grid-template-columns:repeat(2,1fr)}h1{font-size:27px}.meta{grid-template-columns:1fr;gap:3px}th,td{padding:8px}}
@media print{body{background:white}main{max-width:none;padding:0}section,header{break-inside:avoid}details{break-inside:avoid}pre{max-height:none}header{color:#182b3c;background:#eef3f6}header p{color:#345269}}
"""


def table(headers, rows):
    head = "".join("<th>" + esc(str(h)) + "</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join("<td>" + str(cell) + "</td>" for cell in row) + "</tr>"
        for row in rows
    )
    return (
        '<div class="table-wrap"><table><thead><tr>'
        + head
        + "</tr></thead><tbody>"
        + body
        + "</tbody></table></div>"
    )


def label(status):
    cls = (
        "bad"
        if status in ["error", "unavailable", "timeout"]
        else "warning"
        if status == "skipped"
        else "good"
    )
    return '<span class="' + cls + '">' + esc(status.replace("_", " ")) + "</span>"


def finding_table(findings):
    if not findings:
        return '<p class="muted">None observed by the completed checks. This does not establish absence of problems.</p>'
    rows = []
    for f in findings:
        rows.append(
            [
                esc(f.get("path", "")),
                str(f["line"]),
                esc(f["tool"] + " / " + f["rule"]),
                esc(f["severity"]),
                esc(f["message"]) + "<pre>" + esc(f["snippet"][:3000]) + "</pre>",
            ]
        )
    return table(
        ["File", "Line", "Check / rule", "Scanner severity", "Diagnostic and source"],
        rows,
    )


def render(data: dict) -> str:
    error = data.get("input_error")
    analysis = data.get("analysis", {})
    state = analysis.get("state", "input_error")
    title = {
        "needs_attention": "Static findings need review",
        "incomplete_evidence": "Some verification evidence is missing",
        "no_new_static_findings": "No new findings in completed static checks",
        "input_error": "The patch could not be analyzed",
    }[state]
    chunks = [
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
        '<meta name="color-scheme" content="light"><title>PATCH-GATE · Evidence report</title><style>',
        CSS,
        '</style></head><body><main><header><div class="brand">PATCH-GATE / LOCAL PILOT</div><h1>',
        title,
        '</h1><span class="pill">',
        esc(state.replace("_", " ")),
        "</span><p>Before/after static analysis of a Python patch. ",
        "Candidate code was not executed. Scanner warnings are evidence for review, not confirmed defects or vulnerabilities.</p></header>",
    ]
    if error:
        chunks += [
            "<section><h2>Input could not be verified</h2><pre>",
            esc(error),
            "</pre><p>No findings or safety conclusions can be inferred from this failed run.</p></section>",
        ]
    else:
        s = analysis["summary"]
        cards = [
            (s["python_files"], "changed Python files"),
            (s["new_static_findings"], "newly observed diagnostics"),
            (s["incomplete_check_snapshots"], "skipped or incomplete check snapshots"),
            (f"{analysis['seconds']:.3f}s", "static-check analysis time"),
        ]
        chunks.append(
            '<div class="cards">'
            + "".join(
                '<div class="card"><div class="number">'
                + esc(str(n))
                + '</div><div class="label">'
                + esc(card_label)
                + "</div></div>"
                for n, card_label in cards
            )
            + "</div>"
        )
        chunks += [
            '<section><h2>Read this result correctly</h2><div class="note">This pilot does not run project tests, validate issue requirements, establish semantic completeness, or certify a patch as safe. ',
            "A skipped check is unknown evidence. Quality metric increases do not automatically imply deterioration.</div>",
            "<p><strong>Mode:</strong> ",
            esc(analysis["mode"]),
            ". Syntax, descriptive quality metrics and Ruff are requested for every changed Python file. ",
            "Adaptive mode requests Bandit for recognized sensitive context, at least 20 changed lines, or unparseable context. ",
            "The rule is illustrative and can miss findings.</p></section>",
        ]
        comp = data.get("comparison")
        if comp:
            chunks += [
                "<section><h2>Adaptive versus full static checking</h2><p>Both modes analyze the same snapshots. ",
                "The first run of each mode warms the tools; measured mode order alternates between repetitions. ",
                "Timing includes selection, static checks and diagnostic comparison; shared input preparation is reported separately. ",
                "These local timings are not reviewer-time savings or verified defect-detection rates.</p>",
            ]
            rows = [
                [
                    esc(mode),
                    f"{value['median_seconds']:.4f}s",
                    f"{value['min_seconds']:.4f}s",
                    f"{value['max_seconds']:.4f}s",
                ]
                for mode, value in comp["timings"].items()
            ]
            chunks.append(
                table(["Mode", "Median check time", "Minimum", "Maximum"], rows)
            )
            speed = comp["time_reduction_pct"]
            chunks.append(
                "<p><strong>Measured median check-time change:</strong> "
                + f"{speed:.1f}% reduction"
                + " (negative means adaptive was slower).</p>"
            )
            coverage = comp["diagnostic_comparison"]
            chunks.append(
                "<p><strong>New full-scan diagnostics also observed by adaptive:</strong> "
                + esc(str(coverage.get("observed_fraction_display", "unknown")))
                + ". "
                + esc(coverage["detail"])
                + "</p>"
            )
            if coverage["not_observed_by_adaptive"]:
                chunks += [
                    "<h3>Full-mode diagnostics adaptive did not observe</h3>",
                    finding_table(coverage["not_observed_by_adaptive"]),
                ]
            chunks.append("</section>")
        chunks += [
            '<section><h2>Newly observed diagnostics</h2><p class="muted">Compared with the base snapshot. “Newly observed” describes scanner output; it does not prove the patch introduced a vulnerability.</p>',
            finding_table(analysis["newly_observed"]),
            "</section>",
        ]
        chunks.append("<section><h2>Evidence gaps and scope</h2>")
        gaps = analysis["incomplete_checks"]
        if gaps:
            chunks.append(
                table(
                    ["File", "Snapshot", "Check", "Status", "Explanation"],
                    [
                        [
                            esc(g["path"]),
                            esc(g["snapshot"]),
                            esc(g["tool"]),
                            label(g["status"]),
                            esc(g["detail"]),
                        ]
                        for g in gaps
                    ],
                )
            )
        else:
            chunks.append(
                "<p>All requested static-check snapshots completed. Functional tests, semantic requirements and independent vulnerability labels remain outside this pilot.</p>"
            )
        unscanned = data["input"].get("unscanned_non_python_paths", [])
        if unscanned:
            chunks.append(
                "<h3>Non-Python changes not scanned</h3><ul>"
                + "".join("<li><code>" + esc(p) + "</code></li>" for p in unscanned)
                + "</ul>"
            )
        if not analysis["files"]:
            chunks.append(
                '<p class="warning">No changed Python files were analyzed. This patch is outside the supported scanning scope.</p>'
            )
        chunks.append("</section><section><h2>File-by-file evidence</h2>")
        for r in analysis["files"]:
            chunks += [
                "<details><summary>",
                esc(r["path"]),
                " · ",
                esc(r["change"]),
                "</summary><p>",
                esc(" ".join(r["selection_reasons"])),
                "</p>",
            ]
            for side in ["before", "after"]:
                names = r[side + "_context"]["changed_functions"]
                chunks.append(
                    "<p><strong>Changed functions ("
                    + side
                    + "):</strong> "
                    + esc(
                        ", ".join(f"{x['name']}:{x['start']}–{x['end']}" for x in names)
                        or "none identified; changes may be at module/class level"
                    )
                    + "</p>"
                )
            rows = [
                [
                    esc(tool),
                    label(r["before"][tool]["status"]),
                    str(len(r["before"][tool]["findings"])),
                    label(r["after"][tool]["status"]),
                    str(len(r["after"][tool]["findings"])),
                    f"{r['before'][tool]['seconds'] + r['after'][tool]['seconds']:.4f}s",
                ]
                for tool in ["syntax", "quality", "ruff", "bandit"]
            ]
            chunks.append(
                table(
                    [
                        "Check",
                        "Before status",
                        "Before count",
                        "After status",
                        "After count",
                        "Both snapshots time",
                    ],
                    rows,
                )
            )
            bmetrics = r["before"]["quality"].get("metrics") or {}
            ametrics = r["after"]["quality"].get("metrics") or {}
            if bmetrics or ametrics:
                delta = r["metric_delta"] or {}
                rows = [
                    [
                        esc(k),
                        f"{bmetrics[k]:.4g}" if k in bmetrics else "not available",
                        f"{ametrics[k]:.4g}" if k in ametrics else "not available",
                        f"{delta[k]:+.4g}" if k in delta else "not comparable",
                    ]
                    for k in dict.fromkeys([*bmetrics, *ametrics])
                ]
                chunks += [
                    "<h3>Descriptive quality measurements</h3>",
                    table(["Metric", "Before", "After", "Delta"], rows),
                ]
            chunks.append("<h3>Matched and no-longer-observed diagnostics</h3>")
            rows = []
            for tool, d in r["differences"].items():
                for f in d["matched"]:
                    rows.append(
                        [
                            esc(tool + " / " + f["after"]["rule"]),
                            esc(f["after"]["message"]),
                            str(f["before"]["line"]) + " → " + str(f["after"]["line"]),
                            esc(f["match_method"]),
                        ]
                    )
                for f in d["no_longer_observed"]:
                    rows.append(
                        [
                            esc(tool + " / " + f["rule"]),
                            esc(f["message"]),
                            str(f["line"]) + " → absent",
                            "No longer observed; remediation not independently confirmed",
                        ]
                    )
            chunks.append(
                table(["Check / rule", "Diagnostic", "Line", "Attribution"], rows)
                if rows
                else '<p class="muted">No matches or removals could be established by completed comparisons.</p>'
            )
            chunks.append("</details>")
        chunks.append("</section>")
    meta = data.get("input", {})
    rows = [
        ("Created (UTC)", data["created_at_utc"]),
        ("Input repository", meta.get("repo", "unavailable")),
        ("Base", meta.get("resolved_commit") or meta.get("base", "unavailable")),
        ("Patch SHA-256", meta.get("patch_sha256", "unavailable")),
        ("Python and tools", json.dumps(data["tool_versions"], sort_keys=True)),
        ("Input preparation", f"{data.get('preparation_seconds', 0):.4f}s"),
        (
            "Suppression policy",
            "Ruff noqa and Bandit nosec suppressions ignored; isolated scanner settings.",
        ),
    ]
    chunks.append(
        '<section><h2>Run provenance</h2><div class="meta">'
        + "".join(
            '<div class="muted">'
            + esc(k)
            + "</div><div><code>"
            + esc(str(v))
            + "</code></div>"
            for k, v in rows
        )
        + "</div></section>"
    )
    chunks.append(
        "<footer>PATCH-GATE pilot 0.1.1 · Local static checks only · No model APIs or network calls · Full machine-readable evidence is in report.json.</footer></main></body></html>"
    )
    return "".join(chunks)
