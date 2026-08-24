from pathlib import Path
import unittest

from data_synthetic_pipeline.evaluation import DataQualityEvaluator
from data_synthetic_pipeline.llm import ReplayLLMClient
from data_synthetic_pipeline.models import (
    TaskCandidate,
    TaskExecution,
    ValidationResult,
)
from data_synthetic_pipeline.quality import QualityFilterTask
from data_synthetic_pipeline.registry import TaskRegistry


ROOT = Path(__file__).resolve().parents[1]


def math_candidate(candidate_id="candidate:math-good"):
    return TaskCandidate(
        candidate_id=candidate_id,
        task_name="math_knowledge",
        task_version="v1",
        base_task_type="math",
        generation_mode="from_knowledge",
        payload={
            "instruction": "求 2+3。",
            "response": "2+3=5。",
            "reference_answer": "5",
            "knowledge_points": ["整数加法"],
            "difficulty": 1,
            "language": "zh-CN",
        },
    )


class QualityAndEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = TaskRegistry.from_directory(ROOT / "task_definitions")

    def make_filter(self, label_response, judge_response):
        return QualityFilterTask(
            label_definition=self.registry.get("quality_labeler"),
            judge_definition=self.registry.get("quality_judge"),
            labeler=ReplayLLMClient([label_response], model="small-model"),
            judge=ReplayLLMClient([judge_response], model="large-model"),
        )

    def test_small_model_and_large_judge_both_gate_acceptance(self):
        quality_filter = self.make_filter(
            {
                "accept_probability": 0.93,
                "labels": {"correctness_risk": "low"},
                "reasons": ["reference answer is consistent"],
            },
            {
                "decision": "accept",
                "hard_fail": False,
                "scores": {"correctness": 5, "clarity": 5},
                "issues": [],
                "evidence": ["2+3=5"],
                "suggested_fix": "",
                "confidence": 0.99,
            },
        )
        decision = quality_filter.run(math_candidate())

        self.assertEqual(decision.decision, "accept")
        self.assertEqual(decision.small_model["_model"], "small-model")
        self.assertEqual(decision.judge["_model"], "large-model")

    def test_deterministic_failure_short_circuits_model_calls(self):
        labeler = ReplayLLMClient([])
        judge = ReplayLLMClient([])
        quality_filter = QualityFilterTask(
            label_definition=self.registry.get("quality_labeler"),
            judge_definition=self.registry.get("quality_judge"),
            labeler=labeler,
            judge=judge,
        )
        candidate = math_candidate("candidate:bad")
        candidate.payload["instruction"] = "TODO"

        decision = quality_filter.run(candidate)

        self.assertEqual(decision.decision, "reject")
        self.assertTrue(decision.hard_fail)
        self.assertEqual(labeler.calls, [])
        self.assertEqual(judge.calls, [])

    def test_evaluation_is_grouped_by_independent_task(self):
        candidate = math_candidate()
        execution = TaskExecution(candidate, ValidationResult(True))
        quality_filter = self.make_filter(
            {"accept_probability": 0.4, "labels": {}, "reasons": ["uncertain"]},
            {
                "decision": "review",
                "hard_fail": False,
                "scores": {"correctness": 3},
                "issues": ["ambiguous evidence"],
                "evidence": ["short response"],
                "suggested_fix": "expand reasoning",
                "confidence": 0.7,
            },
        )
        decision = quality_filter.run(candidate)
        report = DataQualityEvaluator().evaluate([execution], [decision])

        self.assertEqual(report.totals["generated"], 1)
        self.assertEqual(report.totals["rejected"], 1)
        self.assertEqual(
            report.per_task["math_knowledge"]["accept_yield"], 0.0
        )
        self.assertEqual(
            report.rejection_reasons["quality:small_model_below_threshold"],
            1,
        )


if __name__ == "__main__":
    unittest.main()
