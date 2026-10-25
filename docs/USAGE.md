# PATCH-GATE local pilot 0.1.1

This is a working **before/after static-analysis tool**, not the fully validated framework proposed in the paper. It reads a unified patch, applies it to temporary copies of affected files, runs local checks, and writes an HTML report and JSON evidence. It never executes candidate code or project tests, changes the input checkout, invokes a model API, or uses cloud compute/AWS.

This standalone project includes only its prototype implementation, examples, tests and documentation. The main CLI and demonstration have no dependency on research datasets or external artifact caches.

## Quick start in this repository

The local `.venv` already contains the pilot dependencies. Python 3.11+ and Git are required. To set up a fresh environment, install `requirements-pilot.txt` in a virtual environment using free PyPI packages. These dependencies are separate from the legacy research requirements.

```sh
cd /Volumes/C/patch-gate-framework
.venv/bin/python patch_gate.py \
  --repo /path/to/local/repository \
  --patch /path/to/change.diff \
  --mode adaptive \
  --output outputs/my-first-report
```

The base defaults to the files currently on disk (`--base worktree`). The patch must apply to those files. If your checkout already contains the change, use the appropriate existing local Git base commit instead:

```sh
.venv/bin/python patch_gate.py \
  --repo /path/to/local/repository \
  --base BASE_COMMIT_SHA \
  --patch /path/to/change.diff \
  --mode compare \
  --repeats 3 \
  --output outputs/my-comparison
```

`--base HEAD` reads committed blobs; it does not reset, clean, stash or check out anything. Use the Git repository root as `--repo`. With `worktree`, `--repo` may also be an ordinary directory containing just the base files. Output directories must be new or empty so existing evidence is not overwritten.

## What it checks

| Component | Behavior |
|---|---|
| Patch applicability | Git applies the patch in a temporary directory containing copies of affected base files |
| Syntax | Compiles source to a code object without executing it; uses the current Python interpreter's grammar |
| Changed functions | AST-based before/after locations for functions intersecting changed lines; also reports module-level changes |
| Quality descriptions | Radon cyclomatic complexity, MI and Halstead volume; AST nesting and function-length descriptions |
| Lint | Ruff `E4,E7,E9,F`, isolated settings, no cache, `noqa` suppressions ignored |
| Security warnings | Bandit, default installed rules, isolated working directory, `nosec` suppressions ignored |
| Attribution | One-to-one diagnostic comparison with unchanged-line mapping, plus explicitly approximate source-text matching for moved warnings |
| Evidence gaps | Skipped, unavailable, timed-out and failed check snapshots appear explicitly in JSON and HTML |

Scanner subprocesses use the same Python environment in isolated Python mode (`-I`). Project configuration cannot silently suppress these scanner settings. No shell command is constructed from patch text. Input file hashes, patch hash, tool versions, effective settings and check timings are recorded. A new file has no comparable baseline quality metrics; an absent file is labeled not applicable, not assigned artificial zero quality.

### Adaptive selection rule

Syntax, quality descriptions and Ruff are requested for every changed `.py` file. Bandit is requested when **any** of these applies:

- Either snapshot contains recognized sensitive imports/calls, including subprocess execution, dynamic execution, deserialization, database queries, file/archive operations, networking or cryptographic operations.
- The file has at least 20 added-plus-removed lines (counted by before/after source comparison).
- Source context cannot be parsed.

Sensitive context is inspected across the whole affected file, not only changed lines. The matching is syntactic, not interprocedural/data-flow analysis: aliases, dynamic behavior and unfamiliar APIs can escape detection, while unrelated calls can over-trigger it. The 20-line cutoff is an illustrative engineering choice, not a validated risk threshold. Small changes without recognized context deliberately skip Bandit and may miss warnings. Ruff's limited rule set is not a full Python correctness checker.

Full mode requests all four checks on every changed Python file. Both modes inspect affected files only. Neither mode analyzes unmodified dependencies, proves issue completeness, or performs whole-project security analysis.

## Comparison mode

`--mode compare` warms both modes once, then alternates execution order across the requested measured repetitions. It records:

- Median/minimum/maximum static-check time for each mode and each trial's raw time.
- Newly observed diagnostics in full mode and those also observed by adaptive mode.
- Full-mode diagnostics that adaptive did not observe.
- Whether newly observed diagnostic identities stayed stable across repetitions.

Measured check time includes policy/context inspection, syntax/quality/scanner work and diagnostic comparison. Input materialization is shared and reported separately; report rendering, package-version lookup and the warm-up runs are not part of the per-mode timing. Scanner subprocess startup is included. `overall_seconds` is the CLI's elapsed processing time through analysis, before writing reports. The JSON retains the final measured adaptive run as the primary evidence report and the entire final full-mode reference under `comparison.full_reference`, including its per-snapshot findings and errors. Missed diagnostics are also listed in the comparison. Per-mode check timing distributions should not be presented as end-to-end deployment latency distributions.

“Full-scan diagnostics also observed” is **not defect recall**. Full mode is another static-scanner run, not independently labeled ground truth. If full mode is incomplete or finds no new diagnostics, the fraction is unknown/undefined rather than a fabricated 100%. Repeated local timing on seven selected cases is a demonstration, not a general performance claim. It does not measure human reviewer time or downstream verification effectiveness.

## Outputs and exit codes

- `report.html`: self-contained report; open it locally in a browser, with no web hosting or external fonts/scripts needed.
- `report.json`: detailed findings, source hashes, selection reasons, snapshot status, metric descriptions and operational errors.
- `comparison.csv`: raw measured repetitions in compare mode.

| Exit | Meaning |
|---|---|
| 0 | Report generated; this is not a safety or correctness verdict |
| 1 | With `--fail-on-new`, newly observed diagnostics or after-syntax errors exist; compare mode also considers new full-mode diagnostics |
| 2 | Invalid/incompatible input, output problem, or unsupported patch format |
| 3 | With `--require-complete`, some requested check snapshots were skipped/failed/unavailable, no Python files were scanned, or non-Python changes were out of scope |

When both strict flags apply, incomplete evidence takes precedence (exit 3). Without strict flags, scanner failures remain visible in the report but do not force a nonzero exit. The three analysis states are `needs_attention`, `incomplete_evidence`, and `no_new_static_findings`; none means the patch is safe. An input failure produces a separate error report and exit 2.

## Input scope and isolation

Supported: ordinary UTF-8 unified text patches affecting regular files, including additions/deletions and paths with spaces. Python source is decoded according to its declared encoding. Only `.py` files receive static checks; other affected text files are applied in the temporary copy but listed as unscanned. Source/file-mode changes are not a permission-security audit.

Unsupported changes are rejected explicitly: renames, copies, binary diffs, symlinks, submodules and unsafe paths. Limits: 5 MiB patch, 2 MiB per affected file, 200 affected files, up to 300 seconds per scanner/snapshot. The default scanner timeout is 30 seconds. Temporary directory isolation protects checkout contents; it is **not an OS sandbox for executing untrusted code**. Scanner tools and their installed plugins execute locally, but candidate source is only parsed. Do not use this pilot to execute downloaded repository code.

Existing diagnostics can change meaning when surrounding code changes. Matching source text and rule IDs cannot establish that the underlying behavior is unchanged. Likewise, disappearance of a warning is not independent confirmation of remediation. The report deliberately says “newly observed” and “no longer observed.” It makes no quantitative confidence or practical-harm claims.

## Run the offline demonstration

```sh
.venv/bin/python -m pilot.demo --repeats 3
```

This creates a fresh directory under `outputs/`, with an `index.html`, per-case evidence reports, synthetic inputs, `summary.csv` and `demo_manifest.json`. Four synthetic examples exercise a newly introduced eval warning, a benign edit, a shifted pre-existing warning and a deliberately missed assert warning. No real patch datasets are accessed and no files are downloaded. These examples demonstrate engineering behavior; they cannot establish real-world prevalence or verification efficacy.

## Validate the implementation

```sh
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check --isolated --select E4,E7,E9,F \
  pilot patch_gate.py tests/test_pilot.py
```

Tests cover source non-execution, unchanged dirty Git checkouts, additions/deletions, filenames with spaces, path traversal/symlink rejection, warning-line shifts and duplicate matching, missing tools/timeouts, syntax errors, CI exit policies, adaptive misses, report escaping and preservation of existing output files. All included tests run independently with the development requirements. Install `requirements-pilot-dev.txt` and run the commands above.

## Research status

This release establishes an executable prototype and auditable local measurements. It does not establish a new algorithm, quality/security assurance, calibrated acceptance thresholds, lower defect rates, reviewer-time savings, novelty relative to prior work, independent adoption, or immigration significance. Those require independent outcomes, broader experiments and external evaluation. The demo intentionally exposes a selection-policy miss rather than hiding it.

Scanner configuration references: [Ruff configuration](https://docs.astral.sh/ruff/configuration/) and [Bandit CLI](https://bandit.readthedocs.io/en/latest/man/bandit.html). Local versions are pinned in `requirements-pilot.txt` and recorded in every report.
