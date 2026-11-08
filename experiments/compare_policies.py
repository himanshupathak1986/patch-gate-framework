"""Compare Bandit selection strategies using PATCH-GATE's completed full reports.
No scanner is rerun: these are counterfactual scan-count/output calculations.
"""
import csv
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

RUNS = {'gemini_mini', 'agentless_gpt4o'}
THRESHOLDS = (10, 15, 20, 25, 30)


def load_files(root):
    datasets = defaultdict(list)
    seen_cases = set()
    for path in root.rglob('report.json'):
        parts = path.parts
        try:
            ix = parts.index('reports')
        except ValueError:
            continue
        if ix + 3 != len(parts) - 1 or parts[ix + 1] not in RUNS:
            continue
        try:
            report = json.loads(path.read_text(encoding='utf-8'))
            ref = report['comparison']['full_reference']
            if ref['incomplete_checks']:
                print(f'SKIP incomplete full reference: {path}', file=sys.stderr)
                continue
            if not ref['files']:
                continue
            run = parts[ix + 1]
            case_id = parts[ix + 2]
            if (run, case_id) in seen_cases:
                print(f'SKIP duplicate run/case {run}/{case_id}: {path}', file=sys.stderr)
                continue
            seen_cases.add((run, case_id))
            for file in ref['files']:
                old = file['before_context']
                new = file['after_context']
                bandit = file['differences']['bandit']
                if bandit['status'] != 'compared':
                    print(f'SKIP incomparable Bandit output: {path}', file=sys.stderr)
                    continue
                sides = sum(file[side]['bandit']['status'] != 'not_applicable' for side in ('before', 'after'))
                datasets[run].append({
                    'id': f'{case_id}:{file["path"]}',
                    'sensitive': bool(old['categories'] or new['categories']),
                    'parse_failed': bool(old['parse_error'] or new['parse_error']),
                    'churn': len(file['added_lines']) + len(file['removed_lines']),
                    'snapshots': sides,
                    'bandit_new': len(bandit['newly_observed']),
                })
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as e:
            print(f'SKIP malformed report {path}: {e}', file=sys.stderr)
    return datasets


def picks(files, name, threshold):
    if name == 'full':
        return {f['id'] for f in files}
    if name == 'combined':
        return {f['id'] for f in files if f['sensitive'] or f['parse_failed'] or f['churn'] >= threshold}
    if name == 'size_only':
        return {f['id'] for f in files if f['parse_failed'] or f['churn'] >= threshold}
    if name == 'context_only':
        return {f['id'] for f in files if f['parse_failed'] or f['sensitive']}
    raise ValueError(name)


def random_matched(files, target):
    # Match Bandit snapshot count, while always scanning parse failures.
    mandatory = [f for f in files if f['parse_failed']]
    rest = [f for f in files if not f['parse_failed']]
    random.Random(42).shuffle(rest)
    base = sum(f['snapshots'] for f in mandatory)
    budget = max(0, target - base)
    sums = {0: ()}
    for i, f in enumerate(rest):
        for total, chosen in list(sums.items()):
            new_total = total + f['snapshots']
            if new_total <= budget and new_total not in sums:
                sums[new_total] = chosen + (i,)
    total = max(sums)
    if total != budget:
        print(f'NOTE random budget nearest feasible: {base + total}/{target} scan snapshots', file=sys.stderr)
    return {f['id'] for f in mandatory} | {rest[i]['id'] for i in sums[total]}


def main():
    root = Path('outputs')
    files_by_run = load_files(root) if root.exists() else {}
    if not files_by_run:
        sys.exit('No detailed full-reference reports found under outputs/**/reports/<run>/<case>/report.json. Restore/replay preserved public-patch inputs first. CSV summary files alone are insufficient.')
    rows = []
    for run, files in sorted(files_by_run.items()):
        cases = len({f['id'].split(':', 1)[0] for f in files})
        print(f'{run}: {cases}/30 cases, {len(files)} affected files')
        combined = picks(files, 'combined', 20)
        budget = sum(f['snapshots'] for f in files if f['id'] in combined)
        scenarios = [('full', 20, picks(files, 'full', 20)),
                     ('combined', 20, combined),
                     ('size_only', 20, picks(files, 'size_only', 20)),
                     ('context_only', 20, picks(files, 'context_only', 20)),
                     ('random_budget_matched', 20, random_matched(files, budget))]
        scenarios += [('combined', threshold, picks(files, 'combined', threshold)) for threshold in THRESHOLDS if threshold != 20]
        for policy, threshold, selected in scenarios:
            rows.append({
                'run': run,
                'cases_in_sample': cases,
                'policy': policy,
                'changed_line_threshold': threshold if policy in ('combined', 'size_only') else '',
                'files_scanned': sum(f['id'] in selected for f in files),
                'bandit_snapshot_scans': sum(f['snapshots'] for f in files if f['id'] in selected),
                'bandit_new_preserved': sum(f['bandit_new'] for f in files if f['id'] in selected),
                'bandit_new_missed': sum(f['bandit_new'] for f in files if f['id'] not in selected),
                'scan_time_seconds': 'NOT MEASURED',
            })
    out = Path('paper/tables/reviewer_policy_comparison.csv')
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f'Saved {out}. These are retrospective scan/output calculations, NOT measured policy runtimes.')
    if any(len({f['id'].split(':', 1)[0] for f in files}) < 30 for files in files_by_run.values()) or len(files_by_run) < 2:
        print('WARNING: partial cohort; do not present as full 60-patch evaluation.')


if __name__ == '__main__':
    main()
