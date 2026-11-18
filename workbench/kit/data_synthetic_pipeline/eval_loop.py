"""Offline evaluation contracts. No model calls, code execution or semantic judging."""
import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = Path(__file__).resolve().parent / 'eval_assets'
SCHEMA = ASSETS / 'evaluation-result.schema.json'


def read_jsonl(path):
    with open(path, encoding='utf-8') as f:
        for line, text in enumerate(f, 1):
            if text.strip():
                try:
                    yield json.loads(text)
                except ValueError as exc:
                    raise ValueError(f'{path}:{line}: invalid_json: {exc}') from exc


def validate_result(row, schema=None):
    try:
        from jsonschema import Draft7Validator
    except ImportError as exc:
        raise RuntimeError("run-loop requires the optional dependency: pip install '.[eval]'") from exc
    Draft7Validator(schema or json.loads(SCHEMA.read_text(encoding='utf-8'))).validate(row)
    ids = [s['step_id'] for s in row['steps']]
    if len(ids) != len(set(ids)) or ids != sorted(ids):
        raise ValueError('step_ids_must_be_unique_and_ordered')
    bad = [s for s in row['steps'] if s['validity'] == 'incorrect']
    for step in bad:
        if not step['error_type'] or not step['evidence'].strip():
            raise ValueError('incorrect_step_requires_type_and_evidence')
    expected = ({'step_id': bad[0]['step_id'], 'type': bad[0]['error_type'], 'evidence': bad[0]['evidence']} if bad else None)
    if row['first_error'] != expected:
        raise ValueError('first_error_must_match_earliest_annotated_incorrect_step')
    primary = row['primary_error']
    if primary and not any(primary == {'step_id': s['step_id'], 'type': s['error_type'], 'evidence': s['evidence']} for s in bad):
        raise ValueError('primary_error_must_reference_an_annotated_incorrect_step')
    if row['annotation_status'] == 'unreviewed' and (bad or primary):
        raise ValueError('unreviewed_cannot_contain_error_assertions')
    return row


def evaluate(row, task_id='atomic_exact.v1'):
    result = {k: row[k] for k in ('run_id','sample_id','attempt_id','model','protocol','answer','reference')}
    steps = row.get('steps', [])
    bad = [s for s in steps if s.get('validity') == 'incorrect']
    result.update(schema_version='1.0', task_id=task_id,
                  correct=row['answer'].strip() == row['reference'].strip(),
                  annotation_status=row.get('annotation_status', 'unreviewed'), steps=steps,
                  first_error=({'step_id': bad[0]['step_id'], 'type': bad[0]['error_type'], 'evidence': bad[0]['evidence']} if bad else None),
                  primary_error=row.get('primary_error'))
    return validate_result(result)


def summarize(rows, baseline=None, target=None):
    rows = list(rows)
    if not rows:
        raise ValueError('empty_evaluation_input')
    if bool(baseline) != bool(target):
        raise ValueError('baseline_and_target_must_be_provided_together')
    seen, groups = set(), defaultdict(list)
    for row in rows:
        validate_result(row)
        key = (row['run_id'], row['task_id'], row['sample_id'], row['attempt_id'], row['protocol'])
        if key in seen:
            raise ValueError(f'duplicate_result_key:{key}')
        seen.add(key)
        groups[(row['run_id'], row['task_id'], row['sample_id'], row['protocol'])].append(row)
    per_question = [{'run_id': k[0], 'task_id': k[1], 'sample_id': k[2], 'protocol': k[3], 'n': len(v), 'correct': sum(r['correct'] for r in v), 'accuracy': sum(r['correct'] for r in v)/len(v)} for k,v in sorted(groups.items())]
    matrix = Counter({'correct→correct': 0, 'correct→incorrect': 0, 'incorrect→correct': 0, 'incorrect→incorrect': 0})
    unmatched = 0
    if baseline and target:
        if baseline == target:
            raise ValueError('baseline_and_target_must_differ')
        def index(run):
            return {(r['task_id'],r['sample_id'],r['attempt_id'],r['protocol']):r for r in rows if r['run_id'] == run}
        a,b = index(baseline),index(target)
        for key in a.keys() & b.keys():
            if a[key]['reference'] != b[key]['reference']:
                raise ValueError('paired_reference_mismatch')
            matrix[f"{'correct' if a[key]['correct'] else 'incorrect'}→{'correct' if b[key]['correct'] else 'incorrect'}"] += 1
        unmatched = len(a.keys() ^ b.keys())
        if not sum(matrix.values()):
            raise ValueError('no_matching_pairs_for_selected_runs')
    return {'records':len(rows), 'per_question':per_question, 'transitions':dict(matrix), 'paired':sum(matrix.values()), 'unmatched':unmatched, 'first_error_types':dict(Counter(r['first_error']['type'] for r in rows if r['first_error'])), 'note':'null error does not establish a correct reasoning process; pairs match task/sample/attempt/protocol'}


def _command_run_loop(args):
    task = json.loads(Path(args.task).read_text(encoding='utf-8'))
    if task.get('scorer') != 'exact_match' or task.get('normalization') != 'strip':
        raise ValueError('unsupported_atomic_task_contract')
    rows = [evaluate(r, task['task_id']) for r in read_jsonl(args.input)]
    summary = summarize(rows, args.baseline, args.target)
    out = Path(args.output); out.mkdir(parents=True,exist_ok=True)
    (out/'results.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows), encoding='utf-8')
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'status':'passed','records':len(rows),'paired':summary['paired'],'output':str(out)},ensure_ascii=False))
    return 0


def command_run_loop(args):
    try:
        return _command_run_loop(args)
    except Exception as exc:
        print(json.dumps({'status':'failed','failure_type':type(exc).__name__,'message':str(exc)},ensure_ascii=False))
        return 2


def register(subparsers):
    p = subparsers.add_parser('run-loop', help='Offline benchmark result contract and paired statistics')
    p.add_argument('--input',required=True)
    p.add_argument('--task',default=str(ASSETS/'atomic-exact.v1.json'))
    p.add_argument('--output',default='artifacts/eval-smoke')
    p.add_argument('--baseline'); p.add_argument('--target')
    p.set_defaults(handler=command_run_loop)


def main():
    parser=argparse.ArgumentParser()
    register(parser.add_subparsers(dest='command',required=True))
    args=parser.parse_args()
    try:
        return args.handler(args)
    except Exception as exc:
        print(json.dumps({'status':'failed','failure_type':type(exc).__name__,'message':str(exc)},ensure_ascii=False))
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
