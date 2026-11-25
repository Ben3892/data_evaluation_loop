"""Offline evaluation contracts. No model calls, code execution or semantic judging."""
import argparse
import json
import re
from collections import Counter, defaultdict
from math import comb, fsum
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = Path(__file__).resolve().parent / 'eval_assets'
SCHEMA = ASSETS / 'evaluation-result.schema.json'
AIME_INTEGER = re.compile(r'[0-9]{1,3}')
AIME_BOXED = re.compile(r'\\boxed\{\s*([0-9]{1,3})\s*\}')
# The public AIME24 replay uses a terminal boxed integer, sometimes before </think>.
TERMINAL_BOX = re.compile(r'\\boxed\{\s*([0-9]+)\s*\}(?:\s*(?:\\\)|\\\]|\$|[.。]))*\s*$')


def extract_aime_terminal_box(response):
    if not isinstance(response, str):
        raise ValueError('invalid_aime_response_type: expected a string')
    text = response.rstrip().removesuffix('</think>').rstrip()
    last_line = text.rsplit('\n', 1)[-1]
    if last_line.count(r'\boxed') != 1:
        return ''
    match = TERMINAL_BOX.search(last_line)
    return match[1] if match else ''


def score_exact_match(answer, reference):
    return answer.strip() == reference.strip(), reference


def score_aime_integer(answer, reference):
    """Return correctness and the canonical gold for an AIME final answer."""
    if not isinstance(reference, str) or not AIME_INTEGER.fullmatch(reference.strip()):
        raise ValueError('invalid_aime_reference: expected 1–3 ASCII digits')
    if not isinstance(answer, str):
        raise ValueError('invalid_aime_answer_type: expected a string')

    gold = reference.strip().zfill(3)
    candidate = answer.strip()
    if candidate.startswith('$') and candidate.endswith('$'):
        candidate = candidate[1:-1].strip()
    boxed = AIME_BOXED.fullmatch(candidate)
    if boxed:
        candidate = boxed[1]
    return bool(AIME_INTEGER.fullmatch(candidate)) and candidate.zfill(3) == gold, gold


SCORERS = {
    ('exact_match', 'strip'): score_exact_match,
    ('aime_integer', 'aime_final_answer.v1'): score_aime_integer,
}


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


def evaluate(row, task_id='atomic_exact.v1', *, scorer=None):
    if scorer is None:
        scorer = score_aime_integer if task_id == 'aime_integer.v1' else score_exact_match
    result = {k: row[k] for k in ('run_id','sample_id','attempt_id','model','protocol','answer','reference')}
    correct, reference = scorer(result['answer'], result['reference'])
    steps = row.get('steps', [])
    bad = [s for s in steps if s.get('validity') == 'incorrect']
    result.update(schema_version='1.0', task_id=task_id,
                  correct=correct, reference=reference,
                  annotation_status=row.get('annotation_status', 'unreviewed'), steps=steps,
                  first_error=({'step_id': bad[0]['step_id'], 'type': bad[0]['error_type'], 'evidence': bad[0]['evidence']} if bad else None),
                  primary_error=row.get('primary_error'))
    return validate_result(result)


def _pass_at_k(n, correct, k):
    if n < k:
        return None
    total = comb(n, k)
    return (total - comb(n - correct, k)) / total


def _add_pass_at_k(per_question, ks):
    groups = defaultdict(list)
    for question in per_question:
        question['pass_at_k'] = {
            str(k): _pass_at_k(question['n'], question['correct'], k) for k in ks
        }
        key = (question['run_id'], question['task_id'], question['protocol'])
        groups[key].append(question)

    metrics = []
    for (run_id, task_id, protocol), questions in sorted(groups.items()):
        for k in ks:
            eligible = [
                q['pass_at_k'][str(k)] for q in questions if q['n'] >= k
            ]
            metrics.append({
                'run_id': run_id, 'task_id': task_id, 'protocol': protocol, 'k': k,
                'value': fsum(eligible) / len(eligible) if eligible else None,
                'eligible_questions': len(eligible), 'total_questions': len(questions),
            })
    return metrics


def summarize(rows, baseline=None, target=None, *, pass_at_ks=()):
    rows = list(rows)
    if not rows:
        raise ValueError('empty_evaluation_input')
    if bool(baseline) != bool(target):
        raise ValueError('baseline_and_target_must_be_provided_together')
    ks = tuple(pass_at_ks)
    if any(type(k) is not int or k < 1 for k in ks):
        raise ValueError('pass_at_k_requires_positive_integer')
    ks = sorted(set(ks))
    models, references = {}, {}
    seen, groups = set(), defaultdict(list)
    for row in rows:
        validate_result(row)
        key = (row['run_id'], row['task_id'], row['sample_id'], row['attempt_id'], row['protocol'])
        if key in seen:
            raise ValueError(f'duplicate_result_key:{key}')
        seen.add(key)
        run_key = (row['run_id'], row['task_id'], row['protocol'])
        if models.setdefault(run_key, row['model']) != row['model']:
            raise ValueError(f'model_mismatch:{run_key}')
        question_key = (row['task_id'], row['sample_id'])
        if references.setdefault(question_key, row['reference']) != row['reference']:
            raise ValueError(f'reference_mismatch:{question_key}')
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
            matrix[f"{'correct' if a[key]['correct'] else 'incorrect'}→{'correct' if b[key]['correct'] else 'incorrect'}"] += 1
        unmatched = len(a.keys() ^ b.keys())
        if not sum(matrix.values()):
            raise ValueError('no_matching_pairs_for_selected_runs')
    report = {'records':len(rows), 'per_question':per_question, 'transitions':dict(matrix), 'paired':sum(matrix.values()), 'unmatched':unmatched, 'first_error_types':dict(Counter(r['first_error']['type'] for r in rows if r['first_error'])), 'note':'null error does not establish a correct reasoning process; pairs match task/sample/attempt/protocol'}
    if ks:
        report['pass_at_k'] = _add_pass_at_k(per_question, ks)
    return report


def _command_run_loop(args):
    task = json.loads(Path(args.task).read_text(encoding='utf-8'))
    scorer = SCORERS.get((task.get('scorer'), task.get('normalization')))
    if scorer is None:
        raise ValueError('unsupported_atomic_task_contract')
    if args.aime_raw_response and scorer is not score_aime_integer:
        raise ValueError('aime_raw_response_requires_aime_scorer')
    rows = []
    for row in read_jsonl(args.input):
        if args.aime_raw_response:
            if 'answer' in row:
                raise ValueError('aime_raw_response_conflicts_with_answer')
            row['answer'] = extract_aime_terminal_box(row['response'])
        rows.append(evaluate(row, task['task_id'], scorer=scorer))
    summary = summarize(rows, args.baseline, args.target, pass_at_ks=args.pass_at_k)
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
    p.add_argument('--aime-raw-response', action='store_true',
                   help='Extract a terminal boxed integer from the response field (AIME only)')
    p.add_argument('--pass-at-k', nargs='+', type=int, default=(), metavar='K',
                   help='Report pass@k for the requested positive values of k')
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
