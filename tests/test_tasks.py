from pathlib import Path
import unittest

from data_synthetic_pipeline.knowledge_extraction import KnowledgeExtractor
from data_synthetic_pipeline.llm import ReplayLLMClient
from data_synthetic_pipeline.models import TaskRequest
from data_synthetic_pipeline.registry import TaskRegistry
from data_synthetic_pipeline.tasks import (
    CodeGenerationTask,
    MathKnowledgeTask,
    RewriteTask,
)


ROOT = Path(__file__).resolve().parents[1]


class IndependentTaskTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = TaskRegistry.from_directory(ROOT / "task_definitions")

    def test_knowledge_extraction_is_independent(self):
        client = ReplayLLMClient(
            [
                {
                    "knowledge_points": [
                        {
                            "name": "一元二次方程求根公式",
                            "domain": "algebra",
                            "description": "用判别式和求根公式求解。",
                            "prerequisites": ["平方运算"],
                            "solving_operations": ["计算判别式", "代入求根公式"],
                            "difficulty_min": 2,
                            "difficulty_max": 3,
                        }
                    ]
                }
            ]
        )
        points = KnowledgeExtractor(
            self.registry.get("knowledge_extraction"), client
        ).extract(text="设 ax²+bx+c=0。", source_id="book-1")

        self.assertEqual(len(points), 1)
        self.assertEqual(points[0].source_id, "book-1")
        self.assertTrue(points[0].knowledge_id.startswith("knowledge:"))

    def test_math_generation_uses_requested_knowledge(self):
        client = ReplayLLMClient(
            [
                {
                    "instruction": "求方程 x²-5x+6=0 的两个根。",
                    "response": "判别式为 1，所以两根为 2 和 3。",
                    "reference_answer": "x=2 或 x=3",
                    "knowledge_points": ["一元二次方程求根公式"],
                    "solving_operations": ["计算判别式", "求根"],
                    "difficulty": 2,
                    "language": "zh-CN",
                    "verification_level": "symbolic",
                }
            ]
        )
        request = TaskRequest(
            "math-1",
            {
                "knowledge_points": ["一元二次方程求根公式"],
                "solving_operations": ["计算判别式", "求根"],
                "difficulty": 2,
                "language": "zh-CN",
                "output_constraint": "给出精确值",
            },
        )
        execution = MathKnowledgeTask(
            self.registry.get("math_knowledge"), client
        ).run(request)

        self.assertTrue(execution.succeeded, execution.to_dict())
        self.assertEqual(execution.candidate.base_task_type, "math")
        self.assertEqual(
            execution.candidate.payload["knowledge_points"],
            ["一元二次方程求根公式"],
        )

    def test_rewrite_preserves_answer_and_lineage(self):
        math_client = ReplayLLMClient(
            [
                {
                    "instruction": "12 个苹果平均分给 3 人，每人几个？",
                    "response": "12÷3=4。",
                    "reference_answer": "4",
                    "knowledge_points": ["整数除法"],
                    "solving_operations": ["除法"],
                    "difficulty": 1,
                    "language": "zh-CN",
                    "verification_level": "numeric",
                }
            ]
        )
        parent_execution = MathKnowledgeTask(
            self.registry.get("math_knowledge"), math_client
        ).run(
            TaskRequest(
                "math-parent",
                {
                    "knowledge_points": ["整数除法"],
                    "solving_operations": ["除法"],
                    "difficulty": 1,
                    "language": "zh-CN",
                    "output_constraint": "整数",
                },
            )
        )
        rewrite_client = ReplayLLMClient(
            [
                {
                    "instruction": "A teacher shares 12 apples equally among 3 students. How many does each receive?",
                    "language": "en",
                    "style": "story",
                    "transformations": ["language", "style"],
                    "rewrite_summary": "Translated and added a classroom context.",
                }
            ]
        )
        request = TaskRequest(
            "rewrite-1",
            {
                "parent": parent_execution.candidate.to_dict(),
                "transformations": ["language", "style"],
                "target_language": "en",
                "target_style": "story",
            },
        )
        execution = RewriteTask(
            self.registry.get("rewrite"), rewrite_client
        ).run(request)

        self.assertTrue(execution.succeeded, execution.to_dict())
        self.assertEqual(
            execution.candidate.payload["reference_answer"],
            parent_execution.candidate.payload["reference_answer"],
        )
        self.assertEqual(
            execution.candidate.payload["response"],
            parent_execution.candidate.payload["response"],
        )
        self.assertEqual(
            execution.candidate.parent_ids,
            [parent_execution.candidate.candidate_id],
        )

    def test_code_private_tests_are_not_in_public_candidate(self):
        client = ReplayLLMClient(
            [
                {
                    "instruction": "Implement add(a, b) and return the sum.",
                    "solution": "def add(a, b):\n    return a + b\n",
                    "language": "python",
                    "entry_point": "add",
                    "public_tests": [{"args": [1, 2], "expected": 3}],
                    "private_tests": [{"args": [-5, 2], "expected": -3}],
                    "algorithm_tags": ["arithmetic"],
                    "difficulty": 1,
                }
            ]
        )
        execution = CodeGenerationTask(
            self.registry.get("code_generation"), client
        ).run(
            TaskRequest(
                "code-1",
                {
                    "language": "python",
                    "task_family": "function",
                    "algorithm_tags": ["arithmetic"],
                    "difficulty": 1,
                    "constraints": "integers",
                },
            )
        )

        self.assertTrue(execution.succeeded, execution.to_dict())
        self.assertIn("private_tests", execution.candidate.private_payload)
        public = execution.candidate.to_dict()
        self.assertNotIn("private_payload", public)
        self.assertNotIn("private_tests", public["payload"])
        self.assertTrue(public["payload"]["private_test_set_hash"])


if __name__ == "__main__":
    unittest.main()
