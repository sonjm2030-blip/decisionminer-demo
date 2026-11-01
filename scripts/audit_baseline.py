"""Read-only audit of the competition snapshot. Does not call an LLM or edit data."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path
import openpyxl

ROOT = Path(__file__).resolve().parents[1]

def normalized(value):
    return unicodedata.normalize('NFC', str(value or '')).strip()

def csv_rows(path):
    with path.open(encoding='utf-8-sig', newline='') as handle:
        return list(csv.DictReader(handle))

def unique_index(rows, field):
    result = {}
    for row in rows:
        key = normalized(row[field])
        if not key or key in result:
            raise ValueError(f'Missing or duplicate {field}: {key}')
        result[key] = row
    return result

def agreement(rows, labels):
    matrix = Counter()
    for row in rows:
        key = normalized(row[1])
        if key not in labels:
            raise ValueError(f'Unmatched review ID: {key}')
        matrix[(labels[key], normalized(row[4]).replace(' ', ''))] += 1
    levels = {'Gold': 0, '적합': 0, '보정필요': 1, '검토': 1, '탈락': 2, '부적합': 2}
    human_levels = {'OK': 0, '보정필요': 1, '환각': 2}
    if any(a not in levels or h not in human_levels for a, h in matrix):
        raise ValueError('Unknown review label')
    strict = sum(n for (a, h), n in matrix.items() if levels[a] == human_levels[h])
    # Reproduce the historical script's asymmetric acceptance rule exactly.
    historical_pairs = {('Gold', 'OK'), ('보정필요', '보정필요'), ('탈락', '환각'),
                        ('보정필요', 'OK'), ('보정필요', '환각'), ('탈락', '보정필요')}
    historical = sum(n for pair, n in matrix.items() if pair in historical_pairs)
    binary = sum(n for (a, h), n in matrix.items() if (levels[a] == 2) == (human_levels[h] == 2))
    return {'n': len(rows), 'strict_matches': strict, 'binary_matches': binary,
            'historical_direction_matches': historical if any(a == 'Gold' for a, _ in matrix) else None,
            'matrix': [{'automatic': a, 'human': h, 'n': n} for (a, h), n in sorted(matrix.items())]}

def audit(root=ROOT):
    root = Path(root)
    master = csv_rows(root / '11_data_quality/qa_evaluated_990.csv')
    master_index = unique_index(master, 'ID')
    inventory = csv_rows(root / '01_data_inventory/inventory_full.csv')
    locked = csv_rows(root / '01_data_inventory/22_LOCKED_v1.csv')
    workbook_path = root / 'releases/competition_final.xlsx'
    workbook = openpyxl.load_workbook(workbook_path, read_only=True, data_only=True)
    qa = list(workbook['전체_QA'].values)[2:]
    final_labels = {}
    for row in qa:
        if not row[0]:
            continue
        key = normalized(row[0])
        if key in final_labels:
            raise ValueError(f'Duplicate final ID: {key}')
        match = re.search(r'\[신뢰등급\]\s*(부적합|검토|적합)', str(row[16]))
        if not match:
            raise ValueError(f'Missing explicit final label: {key}')
        final_labels[key] = match.group(1)
    reviews = [row for row in workbook['법리_검수'].values
               if row[0] and str(row[0]).startswith('QA-') and row[1]]
    workbook.close()
    if len({normalized(r[0]) for r in reviews}) != len(reviews):
        raise ValueError('Duplicate review IDs')
    raw_workbook = openpyxl.load_workbook(root / 'releases/reviewer_100.xlsx', read_only=True, data_only=True)
    raw_review = unique_index([dict(zip(next(iter(raw_workbook.active.values)), row))
                               for row in list(raw_workbook.active.values)[1:] if row[0]], 'QA_ID')
    raw_workbook.close()
    for row in reviews:
        if normalized(raw_review[normalized(row[0])]['검수자 평가']).replace(' ', '') != normalized(row[4]).replace(' ', ''):
            raise ValueError(f'Review label changed: {row[0]}')
    legacy_rows = csv_rows(root / '11_data_quality/qc_result_990_v2.csv')
    legacy = {key: row['judgment'] for key, row in unique_index(legacy_rows, 'QA_ID').items()}
    static = {normalized(k): v for k, v in json.loads((root / '11_data_quality/static_labels_990.json').read_text()).items()}
    if set(master_index) != set(final_labels) or final_labels != static:
        raise ValueError('Final workbook, master IDs, and static labels do not align')
    raw_case_dirs = sorted(p for p in (root / '04_raw_outputs').iterdir() if p.is_dir()
                           and not p.name.startswith(('_', '.', 'v2_')) and (p / 'qa_list.json').exists())
    missing = []
    raw_counts = {}
    for case in raw_case_dirs:
        for filename in ['facts.json', 'legal.json', 'sanction.json', 'evidence.json', 'qa_list.json']:
            if not (case / filename).exists():
                missing.append(str((case / filename).relative_to(root)))
        rows = json.loads((case / 'qa_list.json').read_text())
        raw_counts[normalized(case.name)] = len(rows)
    meta = {name: len(csv_rows(root / ('11_data_quality/dataset_' + name + '_22.csv')))
            for name in ['summary', 'facts', 'classification', 'inference']}
    correction_rows = csv_rows(root / 'qa_corrections_100.csv')
    result = {'snapshot': 'competition-baseline', 'inventory_rows': len(inventory), 'locked_cases': len(locked),
              'qa_rows': len(master), 'unique_qa_ids': len(master_index), 'qa_case_count': len({r['사건키'] for r in master}),
              'qa_per_case': dict(sorted(Counter(Counter(r['사건키'] for r in master).values()).items())),
              'metadata_rows': meta, 'final_tiers': dict(sorted(Counter(final_labels.values()).items())),
              'legacy_csv_tiers': dict(sorted(Counter(legacy.values()).items())),
              'raw_qa_case_count': len(raw_counts), 'raw_qa_count': sum(raw_counts.values()),
              'missing_sidecars': missing, 'review_rows': len(reviews), 'raw_review_rows': len(raw_review),
              'review_correction_csv_rows': len(correction_rows),
              'legacy_agreement': agreement(reviews, legacy), 'final_static_agreement': agreement(reviews, final_labels),
              'training_evaluation_overlap': 'Same underlying QA pool; not independent train/test splits',
              'input_sha256': {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in
                               [workbook_path, root / 'releases/reviewer_100.xlsx', root / '11_data_quality/qa_evaluated_990.csv',
                                root / '11_data_quality/qc_result_990_v2.csv', root / '11_data_quality/static_labels_990.json']}}
    return result

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='Optional JSON report path; source data remain unchanged')
    args = parser.parse_args()
    result = audit()
    text = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding='utf-8')
        print(f"QA={result['qa_rows']}, cases={result['locked_cases']}, reviews={result['review_rows']}; report: {args.output}")
    else:
        print(text, end='')

if __name__ == '__main__':
    main()
