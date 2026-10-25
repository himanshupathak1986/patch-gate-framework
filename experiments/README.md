# Public-patch static-check pilot

This directory runs a **new exploratory evaluation of the current PATCH-GATE tool** on public generated patches. It does not import earlier measurement tables or statistical results. Every selected patch is rescanned locally by the current implementation.

The frozen result snapshot contains 30 benchmark-resolved patches from each of two public runs, selected with repository round-robin sampling. Only supported production-Python text-diff blocks are materialized. Tests/non-Python changes are excluded; the historical benchmark verdict is metadata, not a locally rerun test result.

## Inputs and provenance

- Original public predictions: [Gemini / mini-SWE-agent artifact](https://raw.githubusercontent.com/SWE-bench/20260901_mini-v2.4.2_gemini-3-5-flash/main/all_preds.jsonl).
- Original recorded verdicts: [public experiment results](https://raw.githubusercontent.com/SWE-bench/experiments/main/evaluation/verified/20260901_mini-v2.4.2_gemini-3-5-flash/results/results.json).
- Second predictions/verdicts: Agentless-1.5/GPT-4o at commit `dda1f6e6338c69111516d86e95fa3c21c63e0f9e` in the [public experiment archive](https://github.com/SWE-bench/experiments/tree/dda1f6e6338c69111516d86e95fa3c21c63e0f9e/evaluation/verified/20241028_agentless-1.5_gpt4o).
- Benchmark metadata: public SWE-bench Verified task IDs, repositories and base commits.
- Base source: text at each exact base commit from the public repository.

`docs/assets/data/public_patch_protocol.json` records input hashes, sampling and scope; `public_patch_cohort.json` records selected task/base identities and source/patch hashes. `public_patch_accounting.csv` records all candidate eligibility and selection. Fifteen selected task IDs overlap between runs. The second run is a different model/scaffold, but the two samples are not independent problem populations.

The source distribution contains tabular measurements and provenance, not all upstream repositories or a newly generated model run. Raw materialized subsets and detailed reports remain in the local experiment output directory. Public redistribution should retain applicable upstream attribution/license requirements.

## Run from an explicitly supplied public cache

```sh
.venv/bin/python -m experiments.run_public_patch_pilot \
  --artifacts /path/to/public-artifact-cache \
  --original-verdicts /path/to/original_results.json \
  --output outputs/public-patch-pilot-new \
  --per-run 30 --repeats 3 --seed 42
```

The caller supplies the cache explicitly; the program does not search other research folders or download anything. Its cache layout is `swebench_verified_gold.json`, `original_predictions.jsonl`, `second_predictions.jsonl`, `second_results.json`, and `sources/` files keyed by SHA256 of each raw GitHub base-source URL. The source is fetched/cached separately; the stored base-source hashes are also checked on replay.

## Replay preserved inputs independently of upstream caches

```sh
.venv/bin/python -m experiments.run_public_patch_pilot \
  --replay /path/to/preserved-public-patch-pilot \
  --output outputs/public-patch-replay --repeats 3
```

Replay reads the saved `cohort.json`, protocol, candidate accounting and `inputs/` directory. Patch/base hashes are verified before scanning. Outputs must be new or empty; earlier results are preserved. All scanner outcomes are newly computed. Candidate source and repository tests are never executed.

## Rebuild tables and figures

```sh
.venv/bin/python -m pip install -r requirements-docs.txt
MPLCONFIGDIR=/tmp/patch-gate-mpl .venv/bin/python scripts/build_public_pilot_results.py \
  --input outputs/public-patch-pilot
```

To rebuild charts from the committed tabular snapshot without raw code or reports:

```sh
MPLCONFIGDIR=/tmp/patch-gate-mpl .venv/bin/python scripts/build_public_pilot_results.py --frozen
MPLCONFIGDIR=/tmp/patch-gate-mpl .venv/bin/python scripts/build_readme_figures.py
```

## Interpretation

Cost is warm static-check time, including selection and scanner subprocess startup. Shared snapshot preparation, report output, project test time and human review are excluded. Per-patch repetitions are timing measurements, not additional independent patches. The sum of per-patch median times is a descriptive workload proxy, not wall-clock duration of the entire experiment driver.

The reference is full static-scanner output, not defect ground truth. Sparse newly observed warnings limit any preservation claim. Scanner rules may overlap or repeat on the same benchmark task across runs. New warning identities were stable across repetitions; that does not establish correctness. The current policy remains fixed and illustrative, not trained or validated against independently confirmed harm.
