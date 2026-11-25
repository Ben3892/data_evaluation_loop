import copy
import unittest
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from jsonschema import ValidationError
from data_synthetic_pipeline.eval_loop import ROOT, evaluate, read_jsonl, summarize, validate_result

class EvaluationLoopTests(unittest.TestCase):
    def setUp(self):
        self.rows=[evaluate(r) for r in read_jsonl(ROOT/'fixtures/eval-smoke.jsonl')]
    def test_four_transitions_and_question_counts(self):
        report=summarize(self.rows,'base','candidate')
        self.assertEqual(report['paired'],4)
        self.assertEqual(sorted(report['transitions'].values()),[1,1,1,1])
        self.assertEqual(len(report['per_question']),8)
    def test_duplicate_rejected(self):
        with self.assertRaisesRegex(ValueError,'duplicate_result_key'):
            summarize(self.rows+[self.rows[0]])
    def test_schema_rejects_non_boolean(self):
        row=copy.deepcopy(self.rows[0]); row['correct']='false'
        with self.assertRaises(ValidationError): validate_result(row)
    def test_first_and_primary_are_independent(self):
        row=copy.deepcopy(self.rows[3]); s=copy.deepcopy(row['steps'][0]); s['step_id']=1; s['error_type']='unsupported_claim'; row['steps'].append(s)
        row['primary_error']={'step_id':1,'type':s['error_type'],'evidence':s['evidence']}
        validate_result(row)
        self.assertEqual(row['first_error']['step_id'],0)
        self.assertEqual(row['primary_error']['step_id'],1)
    def test_bad_first_error_rejected(self):
        row=copy.deepcopy(self.rows[3]); row['first_error']=None
        with self.assertRaisesRegex(ValueError,'first_error'): validate_result(row)
    def test_missing_pair_counted(self):
        self.assertEqual(summarize(self.rows[:-1],'base','candidate')['unmatched'],1)
    def test_protocols_not_mixed(self):
        row=copy.deepcopy(self.rows[0]); row['protocol']='direct'
        self.assertEqual(summarize(self.rows[1:]+[row],'base','candidate')['paired'],3)
    def test_mismatched_references_rejected(self):
        rows=copy.deepcopy(self.rows); rows[1]['reference']='43'
        with self.assertRaisesRegex(ValueError,'reference_mismatch'): summarize(rows,'base','candidate')
    def test_unreviewed_has_no_error_claim(self):
        row=copy.deepcopy(self.rows[3]); row['annotation_status']='unreviewed'
        with self.assertRaisesRegex(ValueError,'unreviewed'): validate_result(row)
    def test_repeated_attempts_are_separate(self):
        more=copy.deepcopy(self.rows)
        for r in more:r['attempt_id']=1
        report=summarize(self.rows+more,'base','candidate')
        self.assertEqual(report['paired'],8)
        self.assertTrue(all(q['n']==2 for q in report['per_question']))

    def test_empty_input_rejected(self):
        with self.assertRaisesRegex(ValueError, 'empty_evaluation_input'):
            summarize([])

    def test_half_pair_selection_rejected(self):
        with self.assertRaisesRegex(ValueError, 'provided_together'):
            summarize(self.rows, 'base', None)

    def test_nonoverlapping_runs_rejected(self):
        with self.assertRaisesRegex(ValueError, 'no_matching_pairs'):
            summarize(self.rows, 'missing-base', 'missing-target')

    def test_cli_end_to_end_and_structured_failure(self):
        with tempfile.TemporaryDirectory() as output:
            result = subprocess.run([
                sys.executable, '-m', 'data_synthetic_pipeline', 'run-loop',
                '--input', str(ROOT/'fixtures/eval-smoke.jsonl'),
                '--baseline', 'base', '--target', 'candidate', '--output', output,
            ], cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads((Path(output)/'summary.json').read_text())
            self.assertEqual(report['paired'], 4)
            results = list(read_jsonl(Path(output)/'results.jsonl'))
            self.assertEqual(len(results), 8)
            for row in results:
                validate_result(row)
            invalid = Path(output)/'invalid.jsonl'
            invalid.write_text('{bad-json}\n')
            failed_output = Path(output)/'failed'
            result = subprocess.run([
                sys.executable, '-m', 'data_synthetic_pipeline', 'run-loop',
                '--input', str(invalid), '--output', str(failed_output),
            ], cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(result.returncode, 2, result.stderr)
            failure = json.loads(result.stdout)
            self.assertEqual(failure['status'], 'failed')
            self.assertEqual(failure['failure_type'], 'ValueError')
            self.assertFalse(failed_output.exists())

    def test_existing_cli_without_optional_dependencies(self):
        # -S omits site-packages: old data tasks must not import jsonschema.
        result = subprocess.run([
            sys.executable, '-S', '-m', 'data_synthetic_pipeline', 'list-tasks',
        ], cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(json.loads(result.stdout)), 8)

    def test_missing_eval_dependency_reports_install_command(self):
        result = subprocess.run([
            sys.executable, '-S', '-m', 'data_synthetic_pipeline', 'run-loop',
            '--input', str(ROOT/'fixtures/eval-smoke.jsonl'),
        ], cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(result.returncode, 2, result.stderr)
        failure = json.loads(result.stdout)
        self.assertIn("pip install '.[eval]'", failure['message'])

if __name__=='__main__': unittest.main()
