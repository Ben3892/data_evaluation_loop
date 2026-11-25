"""Offline replay of a pinned public rollout slice. See docs/AIME_INTEGRATION_zh.md."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from data_synthetic_pipeline.eval_loop import ASSETS, ROOT, read_jsonl


@unittest.skipUnless(os.environ.get('AIME_REPLAY_SOURCE'), 'set AIME_REPLAY_SOURCE to the public snapshot')
class PublicReplayTests(unittest.TestCase):
    def test_public_aime24_rollouts(self):
        manifest = json.loads((ROOT / 'fixtures/aime24-public-replay.json').read_text())
        source = Path(os.environ['AIME_REPLAY_SOURCE'])
        review = manifest['review']
        step = review['step']
        error = {'step_id': step['step_id'], 'type': step['error_type'], 'evidence': step['evidence']}
        review_key = (review['run_id'], review['sample_id'], review['attempt_id'])
        inputs = []
        expected = {}
        for run, files in manifest['runs'].items():
            for attempt, checksum in enumerate(files['sha256']):
                path = source / files['directory'] / f'run_{attempt:03}_AIME24.jsonl'
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), checksum, str(path))
                for raw in read_jsonl(path):
                    question = manifest['questions'].get(raw['example_id'])
                    if question is None:
                        continue
                    self.assertEqual(raw['run'], attempt)
                    self.assertEqual(raw['finish_reason'], 'stop')
                    key = (run, question['sample_id'], attempt)
                    row = dict(run_id=run, sample_id=question['sample_id'], attempt_id=attempt,
                               protocol='reasoning', model=raw['model_name'], response=raw['response'],
                               reference=question['reference'])
                    if key == review_key:
                        row.update(annotation_status='reviewed', steps=[step], primary_error=error)
                    inputs.append(row)
                    answer = question['answers'][run][attempt]
                    expected[key] = (answer, int(answer) == int(question['reference']))
        self.assertEqual(len(expected), 12)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'input.jsonl'
            path.write_text(''.join(json.dumps(r) + '\n' for r in inputs), encoding='utf-8')
            output = Path(tmp) / 'report'
            proc = subprocess.run([
                sys.executable, '-m', 'data_synthetic_pipeline', 'run-loop', '--aime-raw-response',
                '--task', str(ASSETS / 'aime-integer.v1.json'), '--input', str(path),
                '--baseline', 'base', '--target', 'candidate', '--pass-at-k', '1', '2', '32',
                '--output', str(output),
            ], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            results = list(read_jsonl(output / 'results.jsonl'))
            summary = json.loads((output / 'summary.json').read_text())
        self.assertEqual(len(results), 12)
        for row in results:
            key = (row['run_id'], row['sample_id'], row['attempt_id'])
            self.assertEqual((row['answer'], row['correct']), expected.pop(key), key)
            for field in ('first_error', 'primary_error'):
                self.assertEqual(row[field], error if key == review_key else None, key)
        self.assertFalse(expected)
        self.assertEqual((summary['records'], summary['paired'], summary['unmatched']), (12, 6, 0))
        self.assertEqual(summary['transitions'], {
            'correct→correct': 2, 'correct→incorrect': 1,
            'incorrect→correct': 1, 'incorrect→incorrect': 2,
        })
        by_question = {(q['run_id'], q['sample_id']): q for q in summary['per_question']}
        self.assertEqual(len(by_question), 4)
        for question in manifest['questions'].values():
            for run, answers in question['answers'].items():
                count = sum(int(a) == int(question['reference']) for a in answers)
                q = by_question[run, question['sample_id']]
                self.assertEqual((q['n'], q['correct']), (3, count))
                self.assertEqual(q['pass_at_k'], {'1': count / 3, '2': [0, 2/3, 1, 1][count], '32': None})
        for metric in summary['pass_at_k']:
            k = metric['k']
            self.assertEqual((metric['eligible_questions'], metric['total_questions']), (0 if k == 32 else 2, 2))
            if k == 32:
                self.assertIsNone(metric['value'])
            else:
                value = 5 / 6 if k == 2 and metric['run_id'] == 'base' else 0.5
                self.assertAlmostEqual(metric['value'], value)
