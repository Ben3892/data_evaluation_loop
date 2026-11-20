import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from data_synthetic_pipeline.eval_loop import (
    ASSETS,
    ROOT,
    evaluate,
    read_jsonl,
    score_aime_integer,
    summarize,
    validate_result,
)


class AimeScorerTests(unittest.TestCase):
    def test_integer_and_latex_forms(self):
        for answer, reference, expected in [
            ('60', '060', '060'),
            (' 060 ', '60', '060'),
            (r'\boxed{ 60 }', '060', '060'),
            (r'$\boxed{060}$', '060', '060'),
            ('$60$', '060', '060'),
            ('0', '000', '000'),
            ('999', '999', '999'),
        ]:
            with self.subTest(answer=answer, reference=reference):
                self.assertEqual(score_aime_integer(answer, reference), (True, expected))

    def test_ambiguous_or_invalid_answer_is_incorrect(self):
        for answer in (
            '', '61', '1000', '0060', '-60', '+60', '60.0', '６０', '60 cm',
            '60 or 61', '24 + 36 = 60', r'\boxed{60} \boxed{61}',
            r'Therefore \boxed{60}', r'\boxed{60',
        ):
            with self.subTest(answer=answer):
                self.assertEqual(score_aime_integer(answer, '060'), (False, '060'))

    def test_invalid_gold_and_non_string_answer_are_input_errors(self):
        for reference in (None, 60, '1000', '60.0', r'\boxed{60}'):
            with self.subTest(reference=reference):
                with self.assertRaisesRegex(ValueError, 'invalid_aime_reference'):
                    score_aime_integer('60', reference)
        with self.assertRaisesRegex(ValueError, 'invalid_aime_answer_type'):
            score_aime_integer(60, '060')

    def test_scoring_does_not_override_error_annotations(self):
        annotated = list(read_jsonl(ROOT / 'fixtures/aime-smoke.jsonl'))[3]
        row = {**annotated, 'answer': '060'}
        result = evaluate(row, 'aime_integer.v1', scorer=score_aime_integer)
        self.assertTrue(result['correct'])
        self.assertEqual(result['first_error']['step_id'], 1)
        self.assertEqual(result['primary_error']['step_id'], 2)

        for updates, message in [
            ({'primary_error': {'step_id': 0, 'type': 'arithmetic_error',
                                'evidence': 'No reviewed error at this step'}}, 'primary_error'),
            ({'annotation_status': 'unreviewed'}, 'unreviewed'),
        ]:
            with self.subTest(updates=updates):
                with self.assertRaisesRegex(ValueError, message):
                    evaluate({**row, **updates}, 'aime_integer.v1', scorer=score_aime_integer)


class PassAtKTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            evaluate(r, 'aime_integer.v1', scorer=score_aime_integer)
            for r in read_jsonl(ROOT / 'fixtures/aime-smoke.jsonl')
        ]

    def test_macro_average_and_coverage(self):
        base = self.rows[:3]
        short = {**base[0], 'sample_id': 'test-only-short', 'correct': False}
        two_fails = [
            {**row, 'sample_id': 'test-only-two-fails', 'correct': False}
            for row in base[:2]
        ]
        summary = summarize(base + [short] + two_fails, pass_at_ks=(32, 2, 1, 2))
        by_k = {r['k']: r for r in summary['pass_at_k']}
        self.assertEqual(list(by_k), [1, 2, 32])
        self.assertAlmostEqual(by_k[1]['value'], 2 / 9)
        self.assertEqual(by_k[2]['value'], 0.5)
        self.assertEqual((by_k[2]['eligible_questions'], by_k[2]['total_questions']), (2, 3))
        self.assertIsNone(by_k[32]['value'])
        self.assertEqual(by_k[32]['eligible_questions'], 0)

    def test_inconsistent_runs_and_references_are_rejected(self):
        for index, field, value in [(1, 'model', 'different'), (4, 'reference', '061')]:
            rows = list(self.rows)
            rows[index] = {**rows[index], field: value}
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, f'pass_at_k_{field}_mismatch'):
                    summarize(rows, pass_at_ks=(1,))

    def test_invalid_k_and_legacy_output(self):
        for k in (0, -1, True, 1.5):
            with self.subTest(k=k):
                with self.assertRaisesRegex(ValueError, 'pass_at_k_requires_positive_integer'):
                    summarize(self.rows, pass_at_ks=(k,))
        report = summarize(self.rows)
        self.assertNotIn('pass_at_k', report)
        self.assertTrue(all('pass_at_k' not in q for q in report['per_question']))

    def test_cli_real_question_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            process = subprocess.run([
                sys.executable, '-m', 'data_synthetic_pipeline', 'run-loop',
                '--task', str(ASSETS / 'aime-integer.v1.json'),
                '--input', str(ROOT / 'fixtures/aime-smoke.jsonl'),
                '--baseline', 'base', '--target', 'candidate',
                '--pass-at-k', '1', '2', '32', '--output', tmp,
            ], cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            rows = list(read_jsonl(Path(tmp) / 'results.jsonl'))
            self.assertEqual(len(rows), 7)
            self.assertTrue(all(validate_result(row) == row for row in rows))
            self.assertEqual(rows[0]['answer'], r'$\boxed{060}$')
            self.assertEqual({row['reference'] for row in rows}, {'060'})
            self.assertEqual(rows[3]['first_error']['type'], 'change_of_base_error')
            self.assertEqual(rows[3]['primary_error']['type'], 'arithmetic_error')
            self.assertFalse(rows[5]['correct'])
            self.assertIsNone(rows[5]['first_error'])
            self.assertIsNone(rows[5]['primary_error'])
            summary = json.loads((Path(tmp) / 'summary.json').read_text())
            self.assertEqual((summary['paired'], summary['unmatched']), (3, 1))
            self.assertEqual(summary['transitions']['correct→incorrect'], 2)
            self.assertEqual(summary['transitions']['incorrect→correct'], 1)
            groups = {(q['run_id'], q['protocol']): q for q in summary['per_question']}
            self.assertEqual(groups['base', 'reasoning']['pass_at_k'], {
                '1': 2 / 3, '2': 1.0, '32': None,
            })
            candidate = groups['candidate', 'reasoning']
            self.assertEqual((candidate['n'], candidate['correct'], candidate['accuracy']),
                             (3, 1, 1 / 3))
            self.assertAlmostEqual(candidate['pass_at_k']['2'], 2 / 3)
            self.assertIsNone(groups['base', 'direct']['pass_at_k']['2'])

    def test_cli_rejects_invalid_gold_without_writing_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            row = next(read_jsonl(ROOT / 'fixtures/aime-smoke.jsonl'))
            path, output = Path(tmp) / 'bad.jsonl', Path(tmp) / 'output'
            path.write_text(json.dumps({**row, 'reference': 'error'}) + '\n')
            process = subprocess.run([
                sys.executable, '-m', 'data_synthetic_pipeline', 'run-loop',
                '--task', str(ASSETS / 'aime-integer.v1.json'),
                '--input', str(path), '--output', str(output),
            ], cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
            self.assertIn('invalid_aime_reference', json.loads(process.stdout)['message'])
            self.assertFalse(output.exists())
