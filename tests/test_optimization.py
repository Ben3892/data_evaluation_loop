from pathlib import Path
import unittest

from data_synthetic_pipeline.llm import ReplayLLMClient
from data_synthetic_pipeline.models import EvaluationReport
from data_synthetic_pipeline.optimization import (
    MixturePlanner,
    PromptOptimizer,
    project_bounded_simplex,
)
from data_synthetic_pipeline.registry import TaskRegistry


ROOT = Path(__file__).resolve().parents[1]


def evaluation_report():
    return EvaluationReport(
        report_id="evaluation:test",
        created_at="2026-01-01T00:00:00+00:00",
        totals={
            "requests": 100,
            "generated": 100,
            "valid": 80,
            "accepted": 50,
            "rejected": 30,
            "valid_yield": 0.8,
            "accept_yield": 0.5,
        },
        per_task={
            "math_knowledge": {"accept_yield": 0.35},
            "rewrite": {"accept_yield": 0.8},
            "code_generation": {"accept_yield": 0.45},
        },
        rejection_reasons={"quality:judge_decision:reject": 30},
    )


class OptimizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = TaskRegistry.from_directory(ROOT / "task_definitions")

    def test_prompt_optimizer_only_creates_a_versioned_candidate(self):
        target = self.registry.get("math_knowledge")
        original_prompt = target.system_prompt
        client = ReplayLLMClient(
            [
                {
                    "system_prompt": original_prompt
                    + " Before finalizing, independently recompute the answer.",
                    "hypothesis": "Independent recomputation reduces answer errors.",
                    "expected_effects": ["lower correctness rejection rate"],
                    "risks": ["longer responses"],
                }
            ]
        )
        proposal = PromptOptimizer(
            self.registry.get("prompt_optimizer"), client
        ).propose(target=target, report=evaluation_report())

        self.assertEqual(target.system_prompt, original_prompt)
        self.assertNotEqual(proposal.candidate_definition.definition_id, target.definition_id)
        self.assertIn(".candidate.", proposal.candidate_definition.version)
        self.assertEqual(proposal.target_definition_id, target.definition_id)

    def test_mixture_planner_projects_weights_to_safety_bounds(self):
        client = ReplayLLMClient(
            [
                {
                    "weights": {
                        "math_knowledge": 0.8,
                        "rewrite": 0.1,
                        "code_generation": 0.1,
                    },
                    "rationale": {
                        "math_knowledge": "collect more math error evidence",
                        "rewrite": "already high yield",
                        "code_generation": "hold roughly stable",
                    },
                }
            ]
        )
        proposal = MixturePlanner(
            self.registry.get("mixture_planner"), client
        ).propose(
            tasks=self.registry.list(kind="generator"),
            report=evaluation_report(),
        )

        self.assertAlmostEqual(sum(proposal.projected_weights.values()), 1.0)
        for name, weight in proposal.projected_weights.items():
            limits = proposal.constraints[name]
            self.assertGreaterEqual(weight, limits["min"])
            self.assertLessEqual(weight, limits["max"])

    def test_infeasible_mixture_bounds_are_rejected(self):
        with self.assertRaises(ValueError):
            project_bounded_simplex(
                {"a": 0.5, "b": 0.5},
                {"a": (0.7, 0.8), "b": (0.7, 0.8)},
            )


if __name__ == "__main__":
    unittest.main()
