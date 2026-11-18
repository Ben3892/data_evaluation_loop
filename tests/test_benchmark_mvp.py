import io
import json
import unittest
from contextlib import redirect_stderr
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from data_synthetic_pipeline.benchmark import compare_attempts, evaluate_attempt
from data_synthetic_pipeline.cli import main
from data_synthetic_pipeline.registry import TaskRegistry
from data_synthetic_pipeline.utils import iter_jsonl, write_jsonl

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "examples" / "benchmark_attempts.jsonl"
JUDGE = ROOT / "examples" / "benchmark_judge_responses.jsonl"


class BenchmarkMVPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.definition = TaskRegistry.from_directory(ROOT / "task_definitions").get(
            "benchmark_trace_annotation", "v1"
        )
        cls.inputs = list(iter_jsonl(INPUT))

    def test_run_and_stats(self):
        with TemporaryDirectory() as directory:
            result = Path(directory) / "results.jsonl"
            stats = Path(directory) / "stats.json"
            self.assertEqual(main([
                "benchmark-run", "--input", str(INPUT), "--output", str(result),
                "--judge-responses", str(JUDGE),
            ]), 0)
            rows = list(iter_jsonl(result))
            self.assertEqual(len(rows), 8)
            self.assertEqual(rows[0]["steps"][0]["quality"], "neutral")
            self.assertEqual(rows[0]["first_error"]["index"], 1)
            self.assertEqual(rows[1]["trace_status"], "unavailable")
            self.assertIsNone(rows[1]["first_error"])
            self.assertIsNone(rows[1]["primary_error"])
            self.assertIsNone(rows[2]["primary_error"])
            self.assertEqual(rows[3]["primary_error"]["rubric_ids"], ["no_preamble"])
            self.assertEqual(rows[4]["primary_error"]["code"], "unauthorized_edit")
            self.assertEqual(rows[5]["primary_error"]["code"], "stale_state")
            self.assertEqual(rows[6]["first_error"]["code"], "calculation")
            self.assertEqual(rows[6]["primary_error"]["code"], "case_omission")
            self.assertEqual(rows[7]["annotation_source"]["method"], "judge")
            self.assertEqual(rows[7]["primary_error"]["code"], "invalid_inference")

            self.assertEqual(main([
                "benchmark-stats", "--results", str(result), "--output", str(stats),
                "--k", "2", "--slice", "operator",
            ]), 0)
            summary = json.loads(stats.read_text(encoding="utf-8"))
            simpleqa = next(group for group in summary["groups"] if group["benchmark"] == "simpleqa")
            self.assertAlmostEqual(simpleqa["pass_at_k"], 2 / 3)
            self.assertEqual(simpleqa["pass_at_k_eligible_items"], 1)
            self.assertEqual(simpleqa["unlocalized_failures"], 1)
            self.assertEqual(simpleqa["marker_attempt_counts"]["simulated_search"], 1)
            self.assertEqual(simpleqa["transition_counts"]["use_tool->emit_answer"], 1)
            self.assertEqual(simpleqa["slice_value"], "fact_recall")
            aime = next(group for group in summary["groups"] if group["benchmark"] == "aime")
            self.assertIsNone(aime["pass_at_k"])

    def test_comparison_reports_unmatched_and_unscored(self):
        before = [evaluate_attempt(row, definition=self.definition) for row in self.inputs[:3]]
        candidate = deepcopy(self.inputs[:2])
        for row in candidate:
            row.update(run_id="smoke-candidate", model="toy-candidate", trace=[])
            row.pop("annotation", None)
        candidate[0]["score"]["outcome"] = "correct"
        candidate[1]["score"]["outcome"] = "unscored"
        after = [evaluate_attempt(row, definition=self.definition) for row in candidate]
        result = compare_attempts(before, after)["groups"][0]
        self.assertEqual(result["improved"], 1)
        self.assertEqual(result["matched_scored"], 1)
        self.assertEqual(result["unscored_pairs"], 1)
        self.assertEqual(result["baseline_only"], 1)
        self.assertEqual(result["delta_attempt_accuracy"], 1.0)
        with TemporaryDirectory() as directory:
            directory = Path(directory)
            baseline_path = directory / "before.jsonl"
            candidate_path = directory / "after.jsonl"
            report_path = directory / "compare.json"
            write_jsonl(baseline_path, before)
            write_jsonl(candidate_path, after)
            self.assertEqual(main([
                "benchmark-compare", "--baseline", str(baseline_path),
                "--candidate", str(candidate_path), "--output", str(report_path),
            ]), 0)
            self.assertEqual(json.loads(report_path.read_text())["groups"][0], result)

    def test_reject_repaired_or_unlinked_primary(self):
        row = deepcopy(self.inputs[6])
        row["annotation"]["primary_error"]["index"] = 0
        with self.assertRaisesRegex(ValueError, "still affect"):
            evaluate_attempt(row, definition=self.definition)
        row = deepcopy(self.inputs[3])
        row["annotation"]["primary_error"]["rubric_ids"] = ["bullet_count"]
        with self.assertRaisesRegex(ValueError, "failed criterion"):
            evaluate_attempt(row, definition=self.definition)

    def test_failed_replay_preserves_previous_output(self):
        with TemporaryDirectory() as directory:
            directory = Path(directory)
            result = directory / "result.jsonl"
            result.write_text("previous\n", encoding="utf-8")
            responses = directory / "responses.jsonl"
            response = next(iter_jsonl(JUDGE))
            response["attempt_id"] = "wrong-id"
            write_jsonl(responses, [response])
            stderr = io.StringIO()
            with redirect_stderr(stderr), self.assertRaises(SystemExit) as error:
                main([
                    "benchmark-run", "--input", str(INPUT), "--output", str(result),
                    "--judge-responses", str(responses),
                ])
            self.assertEqual(error.exception.code, 2)
            self.assertIn("attempt_id does not match", stderr.getvalue())
            self.assertEqual(result.read_text(encoding="utf-8"), "previous\n")
